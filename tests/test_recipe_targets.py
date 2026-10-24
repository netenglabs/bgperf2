"""Only a selected local target may change; source builds use controlled fakes."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest
import recipes
import recipe_preflight as runtime
import recipe_targets as targets

ROOT = Path(__file__).resolve().parents[1]
TOOLCHAIN = 'sha256:' + 'a' * 64
RUNTIME = 'sha256:' + 'b' * 64
BUILT = 'sha256:' + 'c' * 64


@pytest.fixture
def recipe():
    return recipes.read_document(ROOT / 'examples/recipes/synthetic-ipv4.recipe.json')


def git(root, *args):
    # Pre-commit exports GIT_DIR/GIT_INDEX_FILE. A scratch fixture must never
    # reuse that caller's repository, index, work tree or config overrides.
    env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
    return subprocess.check_output(['git', '-c', 'core.hooksPath=/dev/null',
        '-c', 'commit.gpgsign=false', '-C', str(root), *args], env=env,
        stderr=subprocess.STDOUT).decode().strip()


@pytest.fixture
def source(tmp_path):
    root = tmp_path / 'maintainer-source'
    root.mkdir()
    git(root, 'init', '-q')
    git(root, 'config', 'user.name', 'Controlled fixture')
    git(root, 'config', 'user.email', 'fixture@example.invalid')
    (root / 'configure.ac').write_text('AC_INIT([fixture], [0])\n')
    (root / 'Makefile.in').write_text('all:\n\t@echo controlled fixture\n')
    (root / 'main.c').write_text('int main(void) { return 0; }\n')
    git(root, 'add', '.')
    git(root, 'commit', '-qm', 'fixture: initial controlled source')
    return root, git(root, 'rev-parse', 'HEAD')


def plan(recipe, source, **kwargs):
    root, revision = source
    return targets.plan_source_build(recipe, str(root), revision, toolchain_image=TOOLCHAIN,
                                      runtime_image=RUNTIME, **kwargs)


def test_supplied_target_changes_only_target_without_probes(recipe, monkeypatch):
    original = copy.deepcopy(recipe)
    monkeypatch.setattr(runtime, 'run_command', lambda *a, **k: pytest.fail('runtime contacted'))
    candidate = targets.supplied_target(recipe, BUILT, label='local fix', instrumentation='asan')
    roles = targets.effective_roles(recipe, candidate)
    assert roles['target']['image'] == BUILT
    assert roles['generator'] == original['roles']['generator']
    assert roles['observer'] == original['roles']['observer']
    assert recipe == original
    assert candidate['provenance']['source'] is None
    assert candidate['provenance']['build'] is None
    assert 'unknown' in candidate['provenance']['limits'][0]
    assert targets.validate_target(json.loads(json.dumps(candidate)), recipe) == candidate


@pytest.mark.parametrize('mutation', ['recipe', 'tag', 'unknown', 'invented', 'adapter'])
def test_target_refuses_wrong_binding_unpinned_or_invented_contract(recipe, mutation):
    candidate = targets.supplied_target(recipe, BUILT)
    if mutation == 'recipe':
        candidate['recipe_sha256'] = '0' * 64
    elif mutation == 'tag':
        candidate['image'] = 'bird:latest'
    elif mutation == 'unknown':
        candidate['shell'] = 'execute something'
    elif mutation == 'invented':
        candidate['provenance']['source'] = {'commit': '1' * 40}
    else:
        candidate['adapter'] = 'other'
    with pytest.raises(recipes.ContractError):
        targets.validate_target(candidate, recipe)


def test_source_plan_is_read_only_and_binds_clean_source(recipe, source, monkeypatch):
    root, revision = source
    before = {str(path.relative_to(root)):path.read_bytes() for path in root.rglob('*') if path.is_file()}
    monkeypatch.setattr(runtime, 'run_command', lambda *a, **k: pytest.fail('Docker contacted'))
    document = plan(recipe, source)
    assert document['source']['commit'] == revision
    assert document['source']['dirty'] is False
    assert document['source']['untracked'] == []
    assert document['source']['patch_sha256'] == hashlib.sha256(b'').hexdigest()
    assert document['instrumentation'] == 'debug'
    assert document['network'] == 'none'
    assert targets.validate_build_plan(json.loads(json.dumps(document))) == document
    assert {str(path.relative_to(root)):path.read_bytes() for path in root.rglob('*') if path.is_file()} == before


def test_dirty_patch_untracked_bytes_and_file_modes_are_bound(recipe, source):
    root, revision = source
    clean = plan(recipe, source)
    (root / 'main.c').write_text('int main(void) { return 1; }\n')
    (root / 'fix.txt').write_text('local fix evidence\n')
    with pytest.raises(recipes.ContractError, match='include_dirty'):
        plan(recipe, source)
    dirty = plan(recipe, source, include_dirty=True)
    assert dirty['source']['dirty']
    assert dirty['source']['snapshot_sha256'] != clean['source']['snapshot_sha256']
    assert dirty['source']['patch_sha256'] != clean['source']['patch_sha256']
    assert dirty['source']['untracked'] == [{'path':'fix.txt', 'sha256':hashlib.sha256(b'local fix evidence\n').hexdigest()}]
    assert git(root, 'rev-parse', 'HEAD') == revision


def test_source_plan_refuses_commit_switch_symlink_and_subdirectory(recipe, source):
    root, revision = source
    with pytest.raises(recipes.ContractError):
        targets.plan_source_build(recipe, str(root), '0' * 40, toolchain_image=TOOLCHAIN, runtime_image=RUNTIME)
    (root / 'unsafe').symlink_to('/etc/passwd')
    with pytest.raises(recipes.ContractError, match='regular'):
        plan(recipe, source, include_dirty=True)
    (root / 'unsafe').unlink()
    nested = root / 'nested'
    nested.mkdir()
    with pytest.raises(recipes.ContractError, match='checkout root'):
        targets.plan_source_build(recipe, str(nested), revision, toolchain_image=TOOLCHAIN, runtime_image=RUNTIME)


@pytest.mark.parametrize('kwargs', [
    {'cflags':'-O2; touch /tmp/surprise'},
    {'configure_flags':['--option=$(whoami)']},
    {'instrumentation':'optimized', 'cflags':'-O0 -g'},
    {'instrumentation':'optimized', 'cflags':'-O2 -fsanitize=address'},
    {'instrumentation':'asan', 'cflags':'-O0 -g'},
    {'toolchain_image':'builder:latest'},
])
def test_plan_refuses_unsafe_flags_instrumentation_and_unpinned_bases(recipe, source, kwargs):
    inputs = {'toolchain_image':TOOLCHAIN, 'runtime_image':RUNTIME}
    inputs.update(kwargs)
    with pytest.raises(recipes.ContractError):
        targets.plan_source_build(recipe, str(source[0]), source[1], **inputs)


@pytest.fixture
def build_host(monkeypatch):
    calls = []
    state = {'built':False, 'tag':None, 'snapshot':None, 'fail':None, 'guard_fail':False}
    env = {'DOCKER_HOST':'unix:///var/run/docker.sock', 'GIT_OPTIONAL_LOCKS':'0'}
    monkeypatch.setattr(runtime, 'runtime_prerequisites', lambda *a, **k: (env, env['DOCKER_HOST'], True))
    def image(reference, host, observed_env):
        assert reference in (TOOLCHAIN, RUNTIME, BUILT)
        calls.append(('image', reference))
        return {'image_id':reference, 'repo_digests':[], 'platform':{'os':'linux','architecture':'amd64','variant':None},'local_size_bytes':42,'download_bytes':None}
    monkeypatch.setattr(runtime, 'inspect_image', image)
    def command(argv, **kwargs):
        args = list(map(str, argv))
        calls.append(('command', args))
        if args[-1:] == ['--guard-only']:
            if state['guard_fail']:
                raise runtime.ProbeError('active measurement')
            return 'guard passed'
        assert args[:5] == ['docker','--host',env['DOCKER_HOST'],'image','inspect']
        state['tag'] = args[-1]
        if not state['built']:
            raise runtime.CommandError(args, 1, '[]\n', 'Error response from daemon: No such image: '+args[-1])
        return json.dumps([{'Id':BUILT, 'Config':{'Labels':{'bgperf2.local_source_sha256':state['snapshot']}}}])
    monkeypatch.setattr(runtime, 'run_command', command)
    def build(argv, *, env, timeout, log_path):
        calls.append(('build', list(map(str, argv))))
        Path(log_path).write_text('SIMULATED compilation output; no build ran\n')
        if state['fail']:
            raise state['fail']
        state['built'] = True
    return calls, state, build


def test_explicit_source_build_captures_complete_identity_and_keeps_other_roles(recipe, source, tmp_path, build_host):
    calls, state, command = build_host
    document = plan(recipe, source)
    state['snapshot'] = document['source']['snapshot_sha256']
    output = tmp_path / 'build-result'
    disclosures = []
    candidate = targets.build_target(document, output_dir=output, emit_disclosure=disclosures.append, command=command)
    assert candidate['image'] == BUILT
    assert candidate['provenance']['kind'] == 'local_source'
    assert candidate['provenance']['build']['compiler_flags'] == '-O0 -g'
    assert candidate['provenance']['instrumentation'] == 'debug'
    assert candidate['provenance']['build']['binary_sha256'] is None
    assert candidate['provenance']['build']['reconstructible'] is False
    assert targets.effective_roles(recipe, candidate)['generator'] == recipe['roles']['generator']
    assert json.loads((output / 'target.json').read_text()) == candidate
    assert hashlib.sha256((output / 'source.tar').read_bytes()).hexdigest() == document['source']['snapshot_sha256']
    assert (output / '.dockerignore').read_text() == '*\n!Dockerfile\n!source.tar\n'
    assert disclosures[0]['tag'].startswith('bgperf/bird-local:')
    build = next(item[1] for item in calls if item[0] == 'build')
    assert '--pull=false' in build and '--network=none' in build
    assert not any('pull' in item[1] for item in calls if item[0] == 'command')
    assert 'git clone' not in (output / 'Dockerfile').read_text()
    assert 'apt-get' not in (output / 'Dockerfile').read_text()
    assert git(source[0], 'status', '--porcelain') == ''


def test_source_build_refuses_changed_plan_or_guard_without_output(recipe, source, tmp_path, build_host):
    calls, state, command = build_host
    document = plan(recipe, source)
    state['snapshot'] = document['source']['snapshot_sha256']
    (source[0] / 'main.c').write_text('changed')
    with pytest.raises(recipes.ContractError, match='include_dirty|changed since'):
        targets.build_target(document, output_dir=tmp_path/'changed', emit_disclosure=lambda _:None, command=command)
    assert not (tmp_path/'changed').exists()
    (source[0] / 'main.c').write_text('int main(void) { return 0; }\n')
    state['guard_fail'] = True
    with pytest.raises(runtime.ProbeError, match='active measurement'):
        targets.build_target(document, output_dir=tmp_path/'guarded', emit_disclosure=lambda _:None, command=command)
    assert not (tmp_path/'guarded').exists()


@pytest.mark.parametrize('failure', [RuntimeError('compiler failed'), KeyboardInterrupt(), SystemExit(143)])
def test_build_failure_and_interrupt_preserve_snapshot_and_partial_log(recipe, source, tmp_path, build_host, failure):
    calls, state, command = build_host
    document = plan(recipe, source)
    state['snapshot'] = document['source']['snapshot_sha256']
    state['fail'] = failure
    output = tmp_path/'partial'
    with pytest.raises(type(failure)):
        targets.build_target(document, output_dir=output, emit_disclosure=lambda _:None, command=command)
    assert (output/'source.tar').is_file()
    assert (output/'build.log').read_text().startswith('SIMULATED')
    assert json.loads((output/'build-result.json').read_text())['status'] == 'failed'
    assert not (output/'target.json').exists()


def test_build_never_reuses_an_existing_output(recipe, source, tmp_path, build_host):
    output = tmp_path/'existing'; output.mkdir()
    marker=output/'marker'; marker.write_text('retained')
    with pytest.raises(recipes.ContractError, match='new absolute'):
        targets.build_target(plan(recipe, source), output_dir=output, emit_disclosure=lambda _:None)
    assert marker.read_text()=='retained'


def test_build_missing_disclosure_is_refused_before_source_or_docker(recipe, monkeypatch):
    monkeypatch.setattr(targets, '_snapshot', lambda *a: pytest.fail('source probed'))
    # Invalid contracts must fail before all mutation/probes too.
    with pytest.raises(recipes.ContractError):
        targets.build_target({}, output_dir='/tmp/no-created-build', emit_disclosure=None)


@pytest.mark.parametrize('failure', ['timeout', 'interrupt', 'term', 'exit'])
def test_build_client_supervision_preserves_log_and_stops_owned_group(tmp_path, monkeypatch, failure):
    import signal
    log = tmp_path/'build.log'
    state={'waits':0,'killed':[]}
    class Process:
        pid=43210
        def wait(self, timeout):
            state['waits']+=1
            if state['waits']==1:
                if failure=='timeout':
                    raise subprocess.TimeoutExpired('docker build',timeout)
                if failure=='interrupt':
                    raise KeyboardInterrupt()
                if failure=='term':
                    raise SystemExit(143)
                return 1
            return -9
    def popen(argv, **kwargs):
        assert kwargs['start_new_session'] is True
        assert kwargs['stderr']==subprocess.STDOUT
        kwargs['stdout'].write(b'controlled partial compiler output\n')
        return Process()
    monkeypatch.setattr(targets.subprocess,'Popen',popen)
    monkeypatch.setattr(targets.os,'killpg',lambda pid,sig:state['killed'].append((pid,sig)))
    expected={'timeout':recipes.ContractError,'interrupt':KeyboardInterrupt,'term':SystemExit,'exit':recipes.ContractError}[failure]
    with pytest.raises(expected):
        targets._run_build(['docker','build','fixture'],env={},timeout=0.01,log_path=log)
    assert log.read_text()=='controlled partial compiler output\n'
    assert state['killed']==([] if failure=='exit' else [(43210,signal.SIGKILL)])


def test_source_plan_does_not_silently_accept_concurrent_edits(recipe, source, monkeypatch):
    original=targets._git
    calls={'diff':0}
    def changing(root,*args):
        result=original(root,*args)
        if args[:1]==('diff',):
            calls['diff']+=1
            if calls['diff']==1:
                (source[0]/'main.c').write_text('concurrent edit\n')
        return result
    monkeypatch.setattr(targets,'_git',changing)
    with pytest.raises(recipes.ContractError,match='changed while'):
        plan(recipe,source)


def test_instrumented_build_flags_are_visible_at_compile_and_link(recipe, source):
    for instrumentation, flags in [('asan','-O1 -g -fsanitize=address'),('profiling','-O2 -pg')]:
        document=plan(recipe,source,instrumentation=instrumentation,cflags=flags)
        dockerfile=targets._dockerfile(TOOLCHAIN,RUNTIME,document)
        assert 'ENV CFLAGS='+json.dumps(flags) in dockerfile
        assert 'ENV LDFLAGS='+json.dumps(flags) in dockerfile
        assert document['instrumentation']==instrumentation
    with pytest.raises(recipes.ContractError):
        plan(recipe,source,instrumentation='optimized',cflags='-O2 -O0')


def test_exported_build_identity_separates_requested_and_observed_bases(recipe, source, tmp_path, build_host, monkeypatch):
    calls,state,command=build_host
    document=plan(recipe,source)
    requested_toolchain='fixture/toolchain@sha256:'+'d'*64
    requested_runtime='fixture/runtime@sha256:'+'e'*64
    document.update(toolchain_image=requested_toolchain,runtime_image=requested_runtime)
    state['snapshot']=document['source']['snapshot_sha256']
    original=runtime.inspect_image
    def inspect(reference,*args):
        return original({requested_toolchain:TOOLCHAIN,requested_runtime:RUNTIME}.get(reference,reference),*args)
    monkeypatch.setattr(runtime,'inspect_image',inspect)
    output=tmp_path/'base-identities'
    candidate=targets.build_target(document,output_dir=output,emit_disclosure=lambda _:None,command=command)
    build=candidate['provenance']['build']
    assert build['toolchain_image']==requested_toolchain
    assert build['runtime_image']==requested_runtime
    assert build['toolchain_image_id']==TOOLCHAIN
    assert build['runtime_image_id']==RUNTIME
    dockerfile=(output/'Dockerfile').read_text()
    assert 'FROM '+TOOLCHAIN+' AS build' in dockerfile
    assert 'FROM '+RUNTIME+'\n' in dockerfile
    assert 'ENV PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin\n' in dockerfile
    assert requested_toolchain not in dockerfile and requested_runtime not in dockerfile
    broken=copy.deepcopy(candidate)
    broken['provenance']['build']['toolchain_image_id']=requested_toolchain
    with pytest.raises(recipes.ContractError,match='actual immutable image IDs'):
        targets.validate_target(broken,recipe)


def test_source_planning_never_executes_configured_clean_filters(recipe, source, tmp_path):
    root,revision=source
    (root/'.gitattributes').write_text('main.c filter=audit\n')
    git(root,'add','.gitattributes')
    git(root,'commit','-qm','fixture: attribute selector without filter command')
    revision=git(root,'rev-parse','HEAD')
    sentinel=tmp_path/'filter-was-executed'
    git(root,'config','filter.audit.clean','touch '+str(sentinel)+'; cat')
    (root/'main.c').write_text('local modification\n')
    with pytest.raises(recipes.ContractError,match='Git clean/process filters'):
        plan(recipe,(root,revision),include_dirty=True)
    assert not sentinel.exists()


def test_dirty_snapshot_rejects_cumulative_size_before_reading_extra_files(recipe, source, monkeypatch):
    root,revision=source
    (root/'a-large.txt').write_bytes(b'a'*100)
    (root/'b-large.txt').write_bytes(b'b'*100)
    monkeypatch.setattr(targets,'SOURCE_LIMIT',150)
    import recipe_results
    original=recipe_results._regular_file
    reads=[]
    def reader(root,path):
        reads.append(path)
        return original(root,path)
    monkeypatch.setattr(recipe_results,'_regular_file',reader)
    with pytest.raises(recipes.ContractError,match='limit'):
        plan(recipe,source,include_dirty=True)
    assert 'a-large.txt' in reads
    assert 'b-large.txt' not in reads


def test_fixed_build_recipe_requires_new_bird_and_client_installation(recipe, source):
    document=plan(recipe,source,configure_flags=['--sbindir=/somewhere-else'])
    dockerfile=targets._dockerfile(TOOLCHAIN,RUNTIME,document)
    assert 'test -x /install/usr/local/sbin/bird && test -x /install/usr/local/sbin/birdc' in dockerfile


@pytest.mark.parametrize('key,value', [('extensions.partialclone','origin'),('remote.origin.promisor','true')])
def test_partial_clone_configuration_refused_before_object_queries(recipe, source, monkeypatch, key, value):
    root,revision=source
    git(root,'config',key,value)
    original=targets._git
    calls=[]
    def tracked(checkout,*args):
        calls.append(args)
        if 'cat-file' in args or 'diff' in args or ('rev-parse' in args and '--verify' in args):
            pytest.fail('Object/work-tree query before rejecting lazy-acquisition checkout')
        return original(checkout,*args)
    monkeypatch.setattr(targets,'_git',tracked)
    with pytest.raises(recipes.ContractError,match='partial-clone/promisor'):
        plan(recipe,source)
    assert calls[-1]==('config','--name-only','--list')


def test_source_git_disables_lazy_fetch_and_terminal_prompts(tmp_path, monkeypatch):
    observed=[]
    def run(command, **kwargs):
        observed.append(kwargs['env'])
        return type('Reply',(),{'returncode':0,'stdout':b'local-only','stderr':b''})()
    monkeypatch.setenv('GIT_NO_LAZY_FETCH','0')
    monkeypatch.setenv('GIT_TERMINAL_PROMPT','1')
    monkeypatch.setattr(targets.subprocess,'run',run)
    assert targets._git(tmp_path,'config','--name-only','--list')==b'local-only'
    assert observed[0]['GIT_NO_LAZY_FETCH']=='1'
    assert observed[0]['GIT_TERMINAL_PROMPT']=='0'


def test_sparse_capture_refused_before_hidden_files_can_disappear(recipe, source):
    root,revision=source
    git(root,'config','core.sparseCheckout','true')
    git(root,'update-index','--skip-worktree','main.c')
    (root/'main.c').unlink()
    with pytest.raises(recipes.ContractError,match='full nonsparse checkout'):
        plan(recipe,source,include_dirty=True)


@pytest.mark.parametrize('flag', ['--skip-worktree','--assume-unchanged'])
def test_hidden_index_flags_are_not_silently_captured_as_clean_source(recipe, source, flag):
    root,revision=source
    git(root,'update-index',flag,'main.c')
    (root/'main.c').write_text('hidden local modification\n')
    with pytest.raises(recipes.ContractError,match='hidden|skip-worktree|assume-unchanged'):
        plan(recipe,source,include_dirty=True)


def test_source_fixtures_and_inspection_cannot_inherit_callers_git_context(tmp_path, recipe, monkeypatch):
    outer = tmp_path / 'caller-repository'
    outer.mkdir()
    git(outer, 'init', '-q')
    git(outer, 'config', 'user.name', 'Caller identity')
    git(outer, 'config', 'user.email', 'caller@example.invalid')
    (outer / 'sentinel').write_text('caller work must remain unchanged')
    git(outer, 'add', '.')
    git(outer, 'commit', '-qm', 'fixture: caller repository')
    before = {name: (outer / '.git' / name).read_bytes() for name in ('HEAD', 'index', 'config')}
    head = git(outer, 'rev-parse', 'HEAD')
    monkeypatch.setenv('GIT_DIR', str(outer / '.git'))
    monkeypatch.setenv('GIT_WORK_TREE', str(outer))
    monkeypatch.setenv('GIT_INDEX_FILE', str(outer / '.git/index'))
    inner = tmp_path / 'selected-source'
    inner.mkdir()
    git(inner, 'init', '-q')
    git(inner, 'config', 'user.name', 'Inner fixture')
    git(inner, 'config', 'user.email', 'inner@example.invalid')
    (inner / 'configure.ac').write_text('AC_INIT([fixture], [0])\n')
    (inner / 'Makefile.in').write_text('all:\n\t@echo fixture\n')
    git(inner, 'add', '.')
    git(inner, 'commit', '-qm', 'fixture: isolated source')
    revision = git(inner, 'rev-parse', 'HEAD')
    document = plan(recipe, (inner, revision))
    assert document['source']['commit'] == revision
    assert revision != head
    assert git(outer, 'rev-parse', 'HEAD') == head
    assert {name: (outer / '.git' / name).read_bytes() for name in before} == before
    assert (outer / 'sentinel').read_text() == 'caller work must remain unchanged'
