"""Real inert local Git histories exercise preparation without builds or network."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import zlib

import pytest

import recipes
import recipe_bisection as bisection
import recipe_source_range as ranges
import recipe_targets as targets

TOOLCHAIN = 'sha256:'+'a'*64
RUNTIME = 'sha256:'+'b'*64


def git(root,*args):
    env = {key:value for key,value in os.environ.items() if not key.startswith('GIT_')}
    env.update(GIT_CONFIG_GLOBAL='/dev/null',GIT_CONFIG_NOSYSTEM='1')
    return subprocess.check_output(['git','-c','core.hooksPath=/dev/null',
        '-c','commit.gpgsign=false','-C',str(root),*map(str,args)],env=env,
        stderr=subprocess.STDOUT).decode().strip()


@pytest.fixture
def source(tmp_path,monkeypatch):
    home = tmp_path/'home'
    home.mkdir()
    monkeypatch.setenv('HOME',str(home))
    root = tmp_path/'source'
    root.mkdir()
    git(root,'init','-q')
    git(root,'config','user.name','Inert source fixture')
    git(root,'config','user.email','fixture@example.invalid')
    (root/'configure.ac').write_text('# Inert source-range fixture, never executed\n')
    (root/'Makefile.in').write_text('# Inert source-range fixture, never executed\n')
    revisions = []
    for index in range(3):
        (root/'main.c').write_text(f'/* inert revision {index} */\n')
        git(root,'add','.')
        git(root,'commit','-qm',f'fixture revision {index}')
        revisions.append(git(root,'rev-parse','HEAD'))
    return root,revisions


@pytest.fixture
def recipe():
    return recipes.read_document(ranges.ENGINE_ROOT/'examples/recipes/synthetic-ipv4.recipe.json')


def prepare(recipe,source,output,**options):
    root,revisions = source
    return ranges.prepare_range(recipe,source_root=root,good=revisions[0],bad=revisions[-1],
        toolchain_image=TOOLCHAIN,runtime_image=RUNTIME,output_dir=output,**options)


def state(root):
    return {path.relative_to(root).as_posix():(path.stat().st_mode,path.stat().st_mtime_ns,
        hashlib.sha256(path.read_bytes()).hexdigest()) for path in root.rglob('*') if path.is_file()}


def read(path):
    return json.loads(path.read_text())


def test_prepare_uses_one_independent_clone_and_leaves_original_source_untouched(recipe,source,tmp_path,monkeypatch):
    root,revisions = source
    (root/'main.c').write_text('local maintainer edits remain unchanged\n')
    (root/'untracked-note').write_text('retain me\n')
    sentinel = tmp_path/'hook-ran'
    hook = root/'.git/hooks/post-checkout'
    hook.write_text('#!/bin/sh\ntouch '+str(sentinel)+'\n')
    hook.chmod(0o755)
    before = state(root)
    monkeypatch.setattr(targets,'build_target',lambda *a,**k:pytest.fail('build started'))
    import recipe_run
    monkeypatch.setattr(recipe_run,'run_recipe',lambda *a,**k:pytest.fail('worker started'))
    monkeypatch.setattr(socket.socket,'__init__',lambda *a,**k:pytest.fail('Python network contacted'))
    output = tmp_path/'prepared'
    manifest = prepare(recipe,source,output)
    assert state(root) == before
    assert not sentinel.exists() and not (root/'.git/worktrees').exists()
    assert [row['revision'] for row in manifest['candidates']] == revisions
    assert manifest['recipe_sha256'] == recipes.recipe_sha256(recipe)
    assert manifest['source_signatures']['before'] == manifest['source_signatures']['after']
    assert manifest['execution'] == 'not_requested'
    assert manifest['performance'] == {'qualification':'not_assessed','policy':'disabled'}
    plan = bisection.validate_plan(read(output/'bisection-plan.json'))
    for candidate,frozen in zip(manifest['candidates'],plan['candidates'],strict=True):
        checkout = output/candidate['source_root']
        assert git(checkout,'rev-parse','HEAD') == candidate['revision']
        build = read(output/candidate['build_plan'])
        assert build == frozen['build_plan']
        assert build['source_root'] == str(checkout)
        assert build['source']['dirty'] is False and build['source']['include_dirty'] is False
        assert build['source']['snapshot_sha256']
    commands = read(output/'git-commands.json')
    clone = [row for row in commands if row['arguments'][0]=='clone']
    assert len(clone) == 1
    assert {'--local','--bare','--no-hardlinks'} <= set(clone[0]['arguments'])
    assert len([row for row in commands if row['arguments'][:2]==['worktree','add']]) == 3
    # --no-hardlinks makes the new repository independent of original object files.
    original_object = next(p for p in (root/'.git/objects').rglob('*') if p.is_file())
    copied_object = output/'repository.git/objects'/original_object.relative_to(root/'.git/objects')
    assert copied_object.stat().st_ino != original_object.stat().st_ino
    assert ranges.verify_preparation(output/'source-range.json')['valid'] is True


def test_verification_never_needs_original_repository(recipe,source,tmp_path):
    output = tmp_path/'prepared'
    prepare(recipe,source,output)
    source[0].rename(tmp_path/'original-moved')
    assert ranges.verify_preparation(output/'source-range.json')['valid'] is True
    assert read(output/'outcome.json')['status'] == 'prepared'


@pytest.mark.parametrize('what',['checkout','plan','manifest','report'])
def test_verification_refuses_changed_preparation(recipe,source,tmp_path,what):
    output = tmp_path/'prepared'
    manifest = prepare(recipe,source,output)
    if what == 'checkout':
        (output/manifest['candidates'][0]['source_root']/'main.c').write_text('changed\n')
    elif what == 'plan':
        (output/manifest['candidates'][0]['build_plan']).write_text('{}\n')
    elif what == 'report':
        (output/'REPORT.md').write_text('Changed conclusion\n')
    else:
        document = read(output/'source-range.json')
        document['candidates'][0]['source_root'] = '../outside'
        (output/'source-range.json').write_text(json.dumps(document))
    with pytest.raises(recipes.ContractError):
        ranges.verify_preparation(output/'source-range.json')


@pytest.mark.parametrize('kind',['local-filter','global-filter','partial','promisor','sparse','hidden',
    'shallow','alternates','replace','graft','object-symlink'])
def test_unsafe_source_is_refused_before_output_or_commands_can_execute(recipe,source,tmp_path,kind):
    root,revisions = source
    sentinel = tmp_path/'filter-ran'
    if kind in ('local-filter','global-filter'):
        if kind == 'local-filter':
            git(root,'config','filter.trap.clean','touch '+str(sentinel)+'; cat')
        else:
            (Path(os.environ['HOME'])/'.gitconfig').write_text(
                '[filter "trap"]\n clean = touch '+str(sentinel)+'; cat\n')
    elif kind == 'partial':
        git(root,'config','extensions.partialClone','origin')
    elif kind == 'promisor':
        git(root,'config','remote.origin.promisor','true')
    elif kind == 'sparse':
        git(root,'config','core.sparseCheckout','true')
    elif kind == 'hidden':
        git(root,'update-index','--assume-unchanged','main.c')
    elif kind == 'shallow':
        (root/'.git/shallow').write_text(revisions[0]+'\n')
    elif kind == 'alternates':
        (root/'.git/objects/info/alternates').write_text('/unselected/object/store\n')
    elif kind == 'replace':
        git(root,'replace',revisions[0],revisions[-1])
    elif kind == 'graft':
        (root/'.git/info/grafts').write_text(revisions[-1]+'\n')
    else:
        (root/'.git/objects/unsafe-link').symlink_to(tmp_path,target_is_directory=True)
    output = tmp_path/'refused'
    with pytest.raises(recipes.ContractError):
        prepare(recipe,source,output)
    assert not output.exists() and not sentinel.exists()


def test_hooks_templates_and_inherited_git_environment_cannot_redirect_preparation(recipe,source,tmp_path,monkeypatch):
    hook_root = tmp_path/'hostile-hooks'
    hook_root.mkdir()
    sentinel = tmp_path/'hostile-hook-ran'
    hook = hook_root/'post-checkout'
    hook.write_text('#!/bin/sh\ntouch '+str(sentinel)+'\n')
    hook.chmod(0o755)
    template = tmp_path/'hostile-template'
    (template/'hooks').mkdir(parents=True)
    shutil.copyfile(hook,template/'hooks/post-checkout')
    (template/'hooks/post-checkout').chmod(0o755)
    (Path(os.environ['HOME'])/'.gitconfig').write_text(
        '[core]\n hooksPath = '+str(hook_root)+'\n[init]\n templateDir = '+str(template)+'\n')
    monkeypatch.setenv('GIT_DIR','/unselected/repository.git')
    monkeypatch.setenv('GIT_WORK_TREE','/unselected/worktree')
    monkeypatch.setenv('GIT_CONFIG_COUNT','1')
    monkeypatch.setenv('GIT_CONFIG_KEY_0','core.sshCommand')
    monkeypatch.setenv('GIT_CONFIG_VALUE_0','touch '+str(sentinel))
    output = tmp_path/'prepared'
    prepare(recipe,source,output)
    assert not sentinel.exists()
    assert list((output/'hooks').iterdir()) == []
    assert not (output/'repository.git/hooks/post-checkout').exists()


def test_selected_symlink_is_refused_without_materializing_alias(recipe,source,tmp_path):
    root,revisions = source
    (root/'alias.c').symlink_to('main.c')
    git(root,'add','alias.c')
    git(root,'commit','-qm','fixture unsupported symlink')
    source = root,[revisions[0],git(root,'rev-parse','HEAD')]
    with pytest.raises(recipes.ContractError,match='symlinks/submodules'):
        prepare(recipe,source,tmp_path/'refused')
    assert not (tmp_path/'refused').exists() and (root/'alias.c').is_symlink()


@pytest.mark.parametrize('kind',['same','backward','off-first-parent','too-many'])
def test_invalid_ranges_are_refused_before_mutation(recipe,source,tmp_path,monkeypatch,kind):
    root,revisions = source
    good,bad = revisions[0],revisions[-1]
    if kind == 'same':
        good = bad
    elif kind == 'backward':
        good,bad = bad,good
    elif kind == 'too-many':
        monkeypatch.setattr(bisection,'MAX_CANDIDATES',2)
    else:
        git(root,'checkout','-qb','side',revisions[0])
        (root/'side.c').write_text('/* side branch */\n')
        git(root,'add','side.c')
        git(root,'commit','-qm','side revision')
        good = git(root,'rev-parse','HEAD')
    with pytest.raises(recipes.ContractError):
        ranges.prepare_range(recipe,source_root=root,good=good,bad=bad,toolchain_image=TOOLCHAIN,
            runtime_image=RUNTIME,output_dir=tmp_path/'refused')
    assert not (tmp_path/'refused').exists()


@pytest.mark.parametrize('bound',['MAX_OBJECT_BYTES','MAX_OBJECT_FILES','MAX_CHECKOUT_BYTES','MAX_CHECKOUT_FILES'])
def test_resource_limits_refuse_before_clone(recipe,source,tmp_path,monkeypatch,bound):
    monkeypatch.setattr(ranges,bound,1)
    with pytest.raises(recipes.ContractError,match='resource limit'):
        prepare(recipe,source,tmp_path/'refused')
    assert not (tmp_path/'refused').exists()


def test_post_clone_failure_retains_partial_files_and_failure_outcome(recipe,source,tmp_path,monkeypatch):
    before = state(source[0])
    original = targets.plan_source_build
    calls = []
    def interrupted(*args,**kwargs):
        calls.append(args)
        if len(calls) == 2:
            raise OSError('SIMULATED source-plan interruption')
        return original(*args,**kwargs)
    monkeypatch.setattr(targets,'plan_source_build',interrupted)
    output = tmp_path/'partial'
    with pytest.raises(OSError,match='SIMULATED'):
        prepare(recipe,source,output)
    assert state(source[0]) == before
    assert (output/'repository.git').is_dir()
    assert len(list((output/'build-plans').glob('*.json'))) == 1
    outcome = read(output/'outcome.json')
    assert outcome['status'] == 'failed' and 'SIMULATED' in outcome['reason']
    assert len(list((output/'checkouts').iterdir())) == 2
    with pytest.raises(recipes.ContractError,match='new directory'):
        prepare(recipe,source,output)


def test_fixed_controls_and_explicit_public_cli(recipe,source,tmp_path,capsys):
    recipe_path = tmp_path/'recipe.json'
    recipe_path.write_text(json.dumps(recipe))
    root,revisions = source
    output = tmp_path/'prepared'
    assert ranges.main(['prepare','--recipe',str(recipe_path),'--source',str(root),
        '--good',revisions[0],'--bad',revisions[-1],'--toolchain-image',TOOLCHAIN,
        '--runtime-image',RUNTIME,'--output',str(output),'--max-trials','12',
        '--build-timeout','90','--worker-timeout','45','--cflags=-O1 -g',
        '--configure-flag=--disable-client']) == 0
    manifest = json.loads(capsys.readouterr().out)
    assert manifest['controls']['cflags'] == '-O1 -g'
    assert manifest['controls']['configure_flags'] == ['--disable-client']
    plan = read(output/'bisection-plan.json')
    assert (plan['max_trials'],plan['build_timeout'],plan['worker_timeout']) == (12,90,45)
    assert ranges.main(['verify',str(output/'source-range.json')]) == 0
    assert json.loads(capsys.readouterr().out)['valid'] is True


def test_wrapper_uses_only_local_git_with_isolated_environment(source,monkeypatch):
    original = subprocess.Popen
    calls = []
    def checked(argv,**kwargs):
        assert argv[0] == 'git'
        assert 'protocol.allow=never' in argv and 'protocol.file.allow=never' in argv
        assert 'core.hooksPath=/dev/null' in argv
        env = kwargs['env']
        assert env['GIT_NO_LAZY_FETCH'] == env['GIT_NO_REPLACE_OBJECTS'] == '1'
        assert env['GIT_CONFIG_GLOBAL'] == env['GIT_CONFIG_SYSTEM'] == '/dev/null'
        calls.append(argv)
        return original(argv,**kwargs)
    monkeypatch.setattr(subprocess,'Popen',checked)
    assert ranges.LocalGit().run(source[0],'rev-parse','--verify','HEAD^{commit}').strip()
    assert len(calls) == 1


def test_output_is_new_absolute_nonsymlink_and_outside_both_checkouts(recipe,source,tmp_path):
    existing = tmp_path/'existing'
    existing.mkdir()
    sentinel = existing/'keep'
    sentinel.write_text('retain')
    for output in (existing,source[0]/'nested',ranges.ENGINE_ROOT/'nested',Path('relative')):
        with pytest.raises(recipes.ContractError):
            prepare(recipe,source,output)
    assert sentinel.read_text() == 'retain'
    alias = tmp_path/'alias'
    alias.symlink_to(tmp_path,target_is_directory=True)
    with pytest.raises(recipes.ContractError,match='symlinks'):
        prepare(recipe,source,alias/'prepared')


def reseal(output,document):
    (output/'source-range.json').write_text(json.dumps(document))
    outcome = read(output/'outcome.json')
    outcome['source_range_sha256'] = hashlib.sha256((output/'source-range.json').read_bytes()).hexdigest()
    (output/'outcome.json').write_text(json.dumps(outcome))


@pytest.mark.parametrize('pointer',['checkout','commondir','gitdir','symlink','repository-commondir'])
def test_pointer_ownership_is_checked_before_git_can_follow_checkout_metadata(recipe,source,tmp_path,monkeypatch,pointer):
    output = tmp_path/'prepared'
    manifest = prepare(recipe,source,output)
    checkout = output/manifest['candidates'][0]['source_root']
    admin = output/'repository.git/worktrees'/checkout.name
    if pointer == 'checkout':
        (checkout/'.git').write_text('gitdir: '+str(source[0]/'.git')+'\n')
    elif pointer == 'symlink':
        (checkout/'.git').unlink()
        (checkout/'.git').symlink_to(source[0]/'.git/HEAD')
    elif pointer == 'repository-commondir':
        (output/'repository.git/commondir').write_text(str(source[0]/'.git')+'\n')
    else:
        (admin/pointer).write_text(str(source[0]/'.git')+'\n')
    original = ranges.LocalGit.run
    def checked(self,root,*args,**kwargs):
        assert Path(root) not in (checkout,source[0]),'Git followed an unverified or external pointer'
        return original(self,root,*args,**kwargs)
    monkeypatch.setattr(ranges.LocalGit,'run',checked)
    with pytest.raises(recipes.ContractError):
        ranges.verify_preparation(output/'source-range.json')


def test_resealed_false_human_policy_claim_is_rejected(recipe,source,tmp_path):
    output = tmp_path/'prepared'
    manifest = prepare(recipe,source,output)
    report = output/'REPORT.md'
    report.write_text('CALIBRATED PERFORMANCE ACCEPTED; execute all workers now.\n')
    manifest['report_sha256'] = hashlib.sha256(report.read_bytes()).hexdigest()
    reseal(output,manifest)
    with pytest.raises(recipes.ContractError,match='human report disagrees'):
        ranges.verify_preparation(output/'source-range.json')


@pytest.mark.parametrize('field,value',[('source_signatures',{}),
    ('source_signatures',{'before':None,'after':None}),('accounting',{}),
    ('accounting',{'objects':{},'checkouts':{},'trees':[],'checkout_upper_bound':{}})])
def test_malformed_nested_contracts_fail_as_clean_refusals(recipe,source,tmp_path,field,value):
    output = tmp_path/'prepared'
    manifest = prepare(recipe,source,output)
    manifest[field] = value
    reseal(output,manifest)
    with pytest.raises(recipes.ContractError):
        ranges.verify_preparation(output/'source-range.json')


@pytest.mark.parametrize('phase',['source','prepared'])
def test_packed_replacement_refs_are_refused(recipe,source,tmp_path,phase):
    root,revisions = source
    output = tmp_path/'prepared'
    if phase == 'prepared':
        prepare(recipe,source,output)
        root = output/'repository.git'
    git(root,'replace',revisions[0],revisions[-1])
    git(root,'pack-refs','--all','--prune')
    with pytest.raises(recipes.ContractError,match='[Rr]eplacement'):
        if phase == 'source':
            prepare(recipe,source,output)
        else:
            ranges.verify_preparation(output/'source-range.json')


@pytest.mark.parametrize('attribute',['ident','working-tree-encoding=UTF-32'])
def test_expanding_source_attributes_require_manual_preparation(recipe,source,tmp_path,attribute):
    root,revisions = source
    (root/'.gitattributes').write_text('*.c '+attribute+'\n')
    git(root,'add','.gitattributes')
    git(root,'commit','-qm','fixture unsupported checkout conversion')
    source = root,[revisions[0],git(root,'rev-parse','HEAD')]
    with pytest.raises(recipes.ContractError,match='attributes require manual'):
        prepare(recipe,source,tmp_path/'refused')
    assert not (tmp_path/'refused').exists()


def test_crlf_checkout_expansion_is_conservatively_budgeted(recipe,source,tmp_path):
    root,revisions = source
    (root/'.gitattributes').write_text('*.c text eol=crlf\n')
    git(root,'add','.gitattributes')
    git(root,'commit','-qm','fixture bounded CRLF checkout')
    source = root,[revisions[0],git(root,'rev-parse','HEAD')]
    output = tmp_path/'prepared'
    manifest = prepare(recipe,source,output)
    assert manifest['accounting']['checkouts']['bytes'] <= manifest['accounting']['checkout_upper_bound']['bytes']
    assert ranges.verify_preparation(output/'source-range.json')['valid'] is True


@pytest.mark.parametrize('kind',['blob','tree'])
@pytest.mark.parametrize('phase',['source','prepared'])
def test_raw_object_hashes_are_verified_even_when_git_accepts_corrupt_storage(recipe,source,tmp_path,kind,phase):
    root,revisions = source
    output = tmp_path/'prepared'
    if phase == 'prepared':
        prepare(recipe,source,output)
        root = output/'repository.git'
    object_id = git(root,'rev-parse',revisions[0]+(':main.c' if kind=='blob' else '^{tree}'))
    metadata = root if phase=='prepared' else root/'.git'
    path = metadata/'objects'/object_id[:2]/object_id[2:]
    original = zlib.decompress(path.read_bytes())
    changed = original.replace(b'revision 0',b'revision 9') if kind=='blob' else original.replace(b'main.c',b'evil.c')
    assert changed != original and len(changed) == len(original)
    path.chmod(0o600)
    path.write_bytes(zlib.compress(changed))
    # cat-file reads wrong payload under the original object name; it does not
    # authenticate the content-addressed storage on behalf of its caller.
    assert ranges.LocalGit().run(root,'cat-file',kind,object_id) == changed.split(b'\0',1)[1]
    with pytest.raises(recipes.ContractError,match='raw (blob|tree) object hash differs|hash mismatch'):
        if phase == 'source':
            prepare(recipe,source,output)
        else:
            ranges.verify_preparation(output/'source-range.json')


def test_shared_source_commondir_is_refused_before_git(recipe,source,tmp_path,monkeypatch):
    (source[0]/'.git/commondir').write_text('/unselected/metadata\n')
    monkeypatch.setattr(ranges.LocalGit,'run',lambda *a,**k:pytest.fail('Git followed shared metadata'))
    with pytest.raises(recipes.ContractError,match='Shared'):
        prepare(recipe,source,tmp_path/'refused')


def test_external_owned_config_include_is_refused_before_git(recipe,source,tmp_path,monkeypatch):
    output = tmp_path/'prepared'
    prepare(recipe,source,output)
    with (output/'repository.git/config').open('a') as stream:
        stream.write('[include]\n path = '+str(source[0]/'.git/config')+'\n')
    monkeypatch.setattr(ranges.LocalGit,'run',lambda *a,**k:pytest.fail('Git read external config'))
    with pytest.raises(recipes.ContractError,match='config includes'):
        ranges.verify_preparation(output/'source-range.json')


def test_aggregate_tree_entries_are_bounded_before_checkout(recipe,source,tmp_path,monkeypatch):
    # Nine source files across the three revisions fit; root directory entries
    # bring the materialized total to twelve and must also consume the bound.
    monkeypatch.setattr(ranges,'MAX_CHECKOUT_FILES',10)
    with pytest.raises(recipes.ContractError,match='tree traversal exceeds'):
        prepare(recipe,source,tmp_path/'refused')
    assert not (tmp_path/'refused').exists()


def test_added_empty_directories_consume_materialized_entry_budget(recipe,source,tmp_path,monkeypatch):
    output = tmp_path/'prepared'
    manifest = prepare(recipe,source,output)
    checkout = output/manifest['candidates'][0]['source_root']
    for index in range(4):
        (checkout/f'empty-{index}').mkdir()
    monkeypatch.setattr(ranges,'MAX_CHECKOUT_FILES',13)
    manifest['resource_limits'] = ranges._limits()
    reseal(output,manifest)
    with pytest.raises(recipes.ContractError,match='Aggregate materialized checkout entry'):
        ranges.verify_preparation(output/'source-range.json')
