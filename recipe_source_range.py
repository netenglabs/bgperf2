# Copyright (C) 2026 bgperf2 contributors. Apache-2.0.
"""Prepare a bounded local first-parent range without changing its source repo.

Only local Git object copying and owned detached checkouts occur. Source code,
hooks, image acquisition, builds and workers are never executed here.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import threading
import time

import recipes
import recipe_bisection as bisection
import recipe_preflight as preflight
import recipe_targets as targets

SCHEMA = 'bgperf2/source-range/v1alpha1'
ENGINE_ROOT = Path(__file__).resolve().parent
MAX_OBJECT_BYTES = 1024 ** 3
MAX_OBJECT_FILES = 200_000
MAX_CHECKOUT_BYTES = 1024 ** 3
MAX_CHECKOUT_FILES = 200_000
MAX_METADATA_BYTES = 64 * 1024 ** 2
MAX_METADATA_FILES = 200_000
MAX_GIT_OUTPUT = 64 * 1024 ** 2
GIT_TIMEOUT = 30


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _bytes(path, limit=MAX_GIT_OUTPUT):
    from recipe_results import _regular_file
    path = bisection.safe(path)
    with _regular_file(path.parent, path.name) as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise recipes.ContractError('Preparation file exceeds its inspection bound: ' + str(path))
    return data


class LocalGit:
    """Fixed Git safety options, bounded output/time and no inherited Git env."""
    def __init__(self, hooks='/dev/null'):
        self.hooks, self.calls = str(hooks), []

    def run(self, root, *arguments, effective_config=False, output_limit=MAX_GIT_OUTPUT):
        env = preflight._environment()
        env.update(GIT_NO_LAZY_FETCH='1', GIT_TERMINAL_PROMPT='0',
                   GIT_NO_REPLACE_OBJECTS='1', GIT_ATTR_NOSYSTEM='1',
                   GIT_CEILING_DIRECTORIES=str(Path(root).parent))
        if not effective_config:
            env.update(GIT_CONFIG_GLOBAL='/dev/null', GIT_CONFIG_SYSTEM='/dev/null',
                       GIT_CONFIG_NOSYSTEM='1')
        local_clone = bool(arguments and arguments[0] == 'clone')
        if local_clone:
            expected = ('clone','--bare','--local','--no-hardlinks','--no-tags')
            if tuple(arguments[:5]) != expected or len(arguments) != 9 or arguments[6] != '--':
                raise recipes.ContractError('Only the fixed explicit local clone operation is permitted')
            for path in arguments[7:]:
                bisection.safe(path)
        command = ['git', '--no-optional-locks', '--no-replace-objects',
            '-c', 'core.fsmonitor=false', '-c', 'core.untrackedCache=false',
            '-c', 'core.hooksPath=' + self.hooks, '-c', 'protocol.allow=never',
            '-c', 'protocol.file.allow=' + ('always' if local_clone else 'never'),
            '-c', 'submodule.recurse=false',
            '-c', 'core.attributesFile=/dev/null', '-c', 'core.autocrlf=false', '-c', 'core.eol=lf',
            '-c', 'maintenance.auto=false', '-c', 'gc.auto=0',
            '-c', 'fetch.writeCommitGraph=false', '-c', 'advice.detachedHead=false',
            '-C', str(root), *map(str, arguments)]
        record = {'root': str(root), 'arguments': list(map(str, arguments)),
                  'effective_config_probe': effective_config}
        self.calls.append(record)
        output = {name: bytearray() for name in ('stdout', 'stderr')}
        process = None
        previous = None
        if threading.current_thread() is threading.main_thread() and signal.getsignal(signal.SIGTERM) == signal.SIG_DFL:
            previous = signal.signal(signal.SIGTERM,preflight._terminate_command)
        try:
            process = subprocess.Popen(command, env=env, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, start_new_session=True)
            deadline = time.monotonic() + GIT_TIMEOUT
            with selectors.DefaultSelector() as selector:
                for name in output:
                    stream = getattr(process, name)
                    os.set_blocking(stream.fileno(), False)
                    selector.register(stream, selectors.EVENT_READ, name)
                while selector.get_map():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise recipes.ContractError('Local Git preparation timed out')
                    for key, _ in selector.select(min(remaining, 0.1)):
                        block = os.read(key.fd, 65536)
                        if not block:
                            selector.unregister(key.fileobj)
                            continue
                        output[key.data].extend(block)
                        if len(output[key.data]) > output_limit:
                            raise recipes.ContractError('Local Git output exceeds the inspection bound')
                code = process.wait(timeout=max(0.01, deadline-time.monotonic()))
            record.update(exit_code=code, stdout_sha256=_sha(output['stdout']),
                          stderr_sha256=_sha(output['stderr']))
            if code:
                raise recipes.ContractError('Local Git preparation failed: ' +
                    output['stderr'].decode('utf-8', 'replace')[-2000:])
            return bytes(output['stdout'])
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise recipes.ContractError('Cannot execute bounded local Git preparation: ' + str(exc)) from exc
        finally:
            if process is not None:
                if process.poll() is None:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait(timeout=10)
                for name in output:
                    getattr(process, name).close()
            if previous is not None:
                signal.signal(signal.SIGTERM,previous)


def _inventory(root, *, objects=False):
    """Refuse metadata endpoints/symlinks before Git opens or copies them."""
    root = bisection.safe(root)
    if not root.is_dir():
        raise recipes.ContractError('Expected a complete local Git metadata directory')
    total = count = entry_count = 0
    limit = MAX_OBJECT_BYTES if objects else MAX_METADATA_BYTES
    file_limit = MAX_OBJECT_FILES if objects else MAX_METADATA_FILES
    pending = [root]
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                entry_count += 1
                if entry_count > file_limit:
                    raise recipes.ContractError('Local Git object/metadata entry resource limit exceeded')
                mode = entry.stat(follow_symlinks=False).st_mode
                path = Path(entry.path)
                if stat.S_ISDIR(mode):
                    # Objects are separately budgeted and inspected.
                    if not objects and path == root/'objects':
                        continue
                    pending.append(path)
                elif stat.S_ISREG(mode):
                    count += 1
                    total += entry.stat(follow_symlinks=False).st_size
                    if path.name.endswith('.promisor'):
                        raise recipes.ContractError('Partial/promisor object storage is unsupported')
                else:
                    raise recipes.ContractError('Git metadata/object symlinks and endpoints are unsupported: ' + str(path))
                if count > file_limit or total > limit:
                    raise recipes.ContractError('Local Git object/metadata copy resource limit exceeded')
    return {'bytes': total, 'files': count}


def _config_guard(git, root):
    raw = git.run(root, 'config', '--includes', '--null', '--list', effective_config=True)
    entries = [part.split(b'\n', 1) for part in raw.split(b'\0') if part]
    keys = [part[0].decode('utf-8').lower() for part in entries]
    if any(key.startswith('filter.') for key in keys):
        raise recipes.ContractError('Source preparation refuses effective Git clean/smudge/process filters, including inherited filters')
    if any(key == 'extensions.partialclone' or re.fullmatch(r'remote\..+\.promisor', key) for key in keys):
        raise recipes.ContractError('Source preparation requires complete local objects, without partial/promisor configuration')
    for parts in entries:
        if parts[0].lower() == b'core.sparsecheckout' and (len(parts) == 1 or parts[1].lower() not in (b'false', b'no', b'off', b'0')):
            raise recipes.ContractError('Sparse source checkouts are unsupported')
    return raw


def _metadata_guard(root):
    _inventory(root)
    for relative in ('commondir', 'shallow', 'info/grafts', 'objects/info/alternates', 'objects/info/http-alternates'):
        if os.path.lexists(root/relative):
            raise recipes.ContractError('Shared, shallow, grafted or alternate object storage is unsupported: ' + relative)
    replacements = root/'refs/replace'
    if replacements.exists() and any(replacements.iterdir()):
        raise recipes.ContractError('Replacement refs are unsupported')
    return _inventory(root/'objects', objects=True)


def _source_signature(git, root, config):
    index = root/'.git/index'
    return {'head': git.run(root, 'rev-parse', '--verify', 'HEAD^{commit}').decode().strip(),
            'head_file_sha256': _sha(_bytes(root/'.git/HEAD')),
            'refs_sha256': _sha(git.run(root, 'for-each-ref', '--format=%(refname)%00%(objectname)')),
            'index_sha256': _sha(_bytes(index)) if index.exists() else None,
            'config_sha256': _sha(config),
            'status_sha256': _sha(git.run(root, 'status', '--porcelain=v1', '-z',
                '--untracked-files=all', '--ignore-submodules=all')),
            'diff_sha256': _sha(git.run(root, 'diff', '--binary', '--no-ext-diff', '--no-textconv', 'HEAD', '--'))}


def _tree_budget(git, root, revision):
    rows = git.run(root, 'ls-tree', '-rlz', '--full-tree', revision).split(b'\0')
    count = total = 0
    names = set()
    for row in rows:
        if not row:
            continue
        metadata, raw_name = row.split(b'\t', 1)
        mode, kind, object_id, size = metadata.split()
        name = raw_name.decode('utf-8')
        recipes._artifact_path(name, 'selected source path')
        if '.git' in {part.lower() for part in Path(name).parts}:
            raise recipes.ContractError('Selected source contains a reserved .git path')
        if mode not in (b'100644', b'100755') or kind != b'blob':
            raise recipes.ContractError('Selected source symlinks/submodules are unsupported: ' + name)
        names.add(name)
        count += 1
        total += int(size)
        if count > 20_000 or total > targets.SOURCE_LIMIT:
            raise recipes.ContractError('Selected source exceeds the 256 MiB/20,000-file snapshot limit')
        if Path(name).name == '.gitattributes':
            attributes = git.run(root,'cat-file','blob',object_id.decode('ascii'))
            for line in attributes.splitlines():
                if line.lstrip().startswith(b'#') or len(line.split(None,1)) != 2:
                    continue
                declarations = line.split(None,1)[1]
                if re.search(rb'(?<![A-Za-z0-9_-])(?:working-tree-encoding|ident)(?:=|\s|$)',declarations):
                    raise recipes.ContractError('Selected working-tree-encoding/ident attributes require manual preparation')
    if not {'configure.ac','Makefile.in'} <= names:
        raise recipes.ContractError('Every selected revision requires BIRD-style configure.ac and Makefile.in')
    return {'bytes': total, 'files': count}


def _checkout_budget(root):
    """Check materialized regular files, excluding the bounded Git pointer file."""
    root = bisection.safe(root)
    total = count = entry_count = 0
    pending = [root]
    while pending:
        with os.scandir(pending.pop()) as entries:
            for entry in entries:
                entry_count += 1
                if entry_count > MAX_CHECKOUT_FILES:
                    raise recipes.ContractError('Materialized checkout entry resource limit exceeded')
                observed = entry.stat(follow_symlinks=False)
                path = Path(entry.path)
                if path == root/'.git':
                    if not stat.S_ISREG(observed.st_mode) or observed.st_size > 4096:
                        raise recipes.ContractError('Prepared worktree must have a bounded regular Git pointer')
                    continue
                if stat.S_ISDIR(observed.st_mode):
                    pending.append(path)
                elif stat.S_ISREG(observed.st_mode):
                    total += observed.st_size
                    count += 1
                else:
                    raise recipes.ContractError('Materialized source symlinks/endpoints are unsupported')
                if total > MAX_CHECKOUT_BYTES or count > MAX_CHECKOUT_FILES:
                    raise recipes.ContractError('Materialized checkout resource limit exceeded')
    return {'bytes':total,'files':count,'entries':entry_count}


def _owned_worktree(root, checkout):
    """Check reciprocal Git pointer files before Git can follow their contents."""
    repository = bisection.safe(root/'repository.git')
    checkout = bisection.safe(checkout)
    admin = bisection.safe(repository/'worktrees'/checkout.name)
    if not admin.is_dir():
        raise recipes.ContractError('Prepared worktree administration directory is unavailable')
    expected = ((checkout/'.git',f'gitdir: {admin}\n'.encode()),
                (admin/'commondir',b'../..\n'),
                (admin/'gitdir',(str(checkout/'.git')+'\n').encode()))
    for path, content in expected:
        if _bytes(path,4096) != content:
            raise recipes.ContractError('Prepared Git pointer/commondir/gitdir ownership differs')
    # These are read by ordinary Git startup. Validate their nofollow path walk.
    _bytes(admin/'HEAD',4096)
    _bytes(admin/'index',MAX_METADATA_BYTES)


def _owned_config_guard(repository):
    """Fresh clone config never needs an include into external metadata."""
    config = _bytes(repository/'config',MAX_METADATA_BYTES)
    if re.search(rb'(?im)^\s*\[\s*include(?:if)?(?:\s|\])',config):
        raise recipes.ContractError('Prepared repository config includes are unsupported')
    if any(repository.rglob('config.worktree')):
        raise recipes.ContractError('Prepared per-worktree configuration is unsupported')


def _signature_schema(value):
    recipes._keys(value,('head','head_file_sha256','refs_sha256','index_sha256',
        'config_sha256','status_sha256','diff_sha256'),where='source signature')
    recipes._match(value['head'],recipes._REVISION,'source signature head','a full Git commit')
    for key in ('head_file_sha256','refs_sha256','config_sha256','status_sha256','diff_sha256'):
        targets._hex(value[key],'source signature '+key)
    if value['index_sha256'] is not None:
        targets._hex(value['index_sha256'],'source signature index_sha256')


def _account_schema(value, count):
    recipes._keys(value,('objects','checkouts','trees','checkout_upper_bound'),where='preparation accounting')
    if not isinstance(value['trees'],list) or len(value['trees']) != count:
        raise recipes.ContractError('Preparation tree accounting count differs')
    rows = [value[key] for key in ('objects','checkouts','checkout_upper_bound')] + value['trees']
    for row in rows:
        recipes._keys(row,('bytes','files'),where='preparation resource count')
        for key in ('bytes','files'):
            recipes._integer(row[key],'preparation '+key,0)
    for key,limit in (('bytes',MAX_OBJECT_BYTES),('files',MAX_OBJECT_FILES)):
        if value['objects'][key] > limit:
            raise recipes.ContractError('Recorded object copy resource bound exceeded')


def _chain(git, root, good, bad):
    selected, proofs = [], []
    revision = bad
    while len(selected) <= bisection.MAX_CANDIDATES:
        raw = git.run(root, 'cat-file', 'commit', revision)
        parents = bisection.commit_parents(base64.b64encode(raw).decode('ascii'), revision)
        selected.append(revision)
        proofs.append(raw)
        if revision == good:
            break
        if not parents:
            raise recipes.ContractError('Good endpoint is not on the bad endpoint first-parent chain')
        revision = parents[0]
    if selected[-1] != good or not 2 <= len(selected) <= bisection.MAX_CANDIDATES:
        raise recipes.ContractError('Select 2..256 consecutive first-parent revisions including good and bad')
    return list(reversed(selected)), list(reversed(proofs))


def _object_hash(kind, data):
    digest = hashlib.sha1()
    digest.update(kind.encode('ascii')+b' '+str(len(data)).encode('ascii')+b'\0')
    digest.update(data)
    return digest.hexdigest()


def _verify_objects(git, root, revisions, proofs):
    """Git cat-file does not authenticate its object storage; hash selected bytes."""
    budgets = [_tree_budget(git,root,revision) for revision in revisions]
    if (2*sum(row['bytes'] for row in budgets) > MAX_CHECKOUT_BYTES
            or sum(row['files'] for row in budgets) > MAX_CHECKOUT_FILES):
        raise recipes.ContractError('Selected object traversal exceeds the aggregate preparation bound')
    trees, blobs = {}, set()
    tree_bytes = entries_total = 0
    for revision, proof in zip(revisions,proofs,strict=True):
        raw = git.run(root,'cat-file','commit',revision)
        if raw != proof or _object_hash('commit',raw) != revision:
            raise recipes.ContractError('Selected raw commit object hash differs')
        tree_line = raw.split(b'\n',1)[0]
        if not re.fullmatch(rb'tree [0-9a-f]{40}',tree_line):
            raise recipes.ContractError('Selected commit tree identity is malformed')
        pending = [(tree_line[5:].decode('ascii'),0)]
        entries = 0
        while pending:
            object_id,depth = pending.pop()
            if depth > 256:
                raise recipes.ContractError('Selected Git tree nesting exceeds the preparation bound')
            if object_id not in trees:
                data = git.run(root,'cat-file','tree',object_id)
                if _object_hash('tree',data) != object_id:
                    raise recipes.ContractError('Selected raw tree object hash differs')
                tree_bytes += len(data)
                if tree_bytes > MAX_GIT_OUTPUT:
                    raise recipes.ContractError('Selected raw tree metadata exceeds the preparation bound')
                children = []
                file_count = 0
                position = 0
                while position < len(data):
                    separator = data.find(b' ',position)
                    ending = data.find(b'\0',separator+1)
                    if separator < 0 or ending < 0 or ending+21 > len(data):
                        raise recipes.ContractError('Selected raw Git tree entry is malformed')
                    mode,name = data[position:separator],data[separator+1:ending]
                    if not name or b'/' in name or name in (b'.',b'..'):
                        raise recipes.ContractError('Selected raw Git tree path is unsafe')
                    child = data[ending+1:ending+21].hex()
                    position = ending+21
                    if mode == b'40000':
                        children.append(child)
                    elif mode in (b'100644',b'100755'):
                        file_count += 1
                        if child not in blobs:
                            size = int(git.run(root,'cat-file','-s',child))
                            if not 0 <= size <= targets.SOURCE_LIMIT:
                                raise recipes.ContractError('Selected raw blob exceeds the source snapshot bound')
                            blob = git.run(root,'cat-file','blob',child,output_limit=targets.SOURCE_LIMIT)
                            if len(blob) != size or _object_hash('blob',blob) != child:
                                raise recipes.ContractError('Selected raw blob object hash differs')
                            blobs.add(child)
                    else:
                        raise recipes.ContractError('Selected source symlinks/submodules are unsupported')
                trees[object_id] = children,file_count
            entries += 1
            entries_total += 1+trees[object_id][1]
            if entries > MAX_CHECKOUT_FILES or entries_total > MAX_CHECKOUT_FILES:
                raise recipes.ContractError('Selected raw tree traversal exceeds the preparation bound')
            pending.extend((child,depth+1) for child in trees[object_id][0])


def _limits():
    return {'object_bytes':MAX_OBJECT_BYTES, 'object_files':MAX_OBJECT_FILES,
            'checkout_bytes':MAX_CHECKOUT_BYTES, 'checkout_files':MAX_CHECKOUT_FILES,
            'source_bytes_per_revision':targets.SOURCE_LIMIT, 'source_files_per_revision':20_000,
            'candidates':bisection.MAX_CANDIDATES}


def _report(manifest):
    return ('# Prepared local source range\n\n'
        'No build, image acquisition or worker was requested. Performance policy is disabled; '
        'qualification is not assessed. Endpoint names declare intended outcomes; they are not observations.\n\n'
        f"Original source: {json.dumps(manifest['source_root'])}. Its bounded before/after signatures agree. "
        'The original repository is never cloned with shared objects or registered worktrees.\n\n'
        f"Selected {len(manifest['candidates'])} consecutive first-parent revisions, inclusive of "
        f"`{manifest['good']}` and `{manifest['bad']}`.\n\n"
        '[Frozen preparation](source-range.json), [bisection plan](bisection-plan.json), '
        '[preparation commands](git-commands.json), and [terminal preparation outcome](outcome.json).\n\n'
        'Review the build plans and their fixed controls before initializing a separate search session. '
        'Only a later explicit step/run --execute builds source or starts a worker. '
        'Keep this local preparation at its selected path: build plans contain absolute checkout paths. '
        'Portable execution reports are separate artifacts. Failure retains owned partial files without cleanup.\n')


def prepare_range(recipe, *, source_root, good, bad, toolchain_image, runtime_image,
                  output_dir, instrumentation='debug', cflags='-O0 -g', configure_flags=(),
                  predicate='assertions', max_trials=32, worker_timeout=120, build_timeout=1200):
    """Create one isolated local clone and clean per-revision build plans."""
    recipes.validate_recipe(recipe)
    recipes._match(good, recipes._REVISION, 'good', 'a full Git commit')
    recipes._match(bad, recipes._REVISION, 'bad', 'a full Git commit')
    targets._image(toolchain_image, 'toolchain_image')
    targets._image(runtime_image, 'runtime_image')
    cflags, configure_flags = targets._flags(cflags, configure_flags, instrumentation)
    recipes._choice(predicate, ('assertions','target_crash'), 'predicate')
    expected = 'target_crash' if predicate == 'target_crash' else 'experiment_completed'
    if recipe['reproduction']['expected_outcome'] != expected:
        raise recipes.ContractError('Predicate differs from the frozen reproduction question')
    recipes._integer(max_trials, 'max_trials', 4)
    if max_trials > bisection.MAX_TRIALS:
        raise recipes.ContractError('max_trials exceeds 1024')
    bisection.finite(worker_timeout, 'worker_timeout')
    bisection.finite(build_timeout, 'build_timeout')
    source, output = bisection.safe(source_root), bisection.safe(output_dir)
    if not source.is_dir() or not (source/'.git').is_dir() or (source/'.git').is_symlink():
        raise recipes.ContractError('Select a full standalone local Git checkout with a regular .git directory')
    if output.exists() or os.path.lexists(output):
        raise recipes.ContractError('Preparation output must be a new directory')
    for original in (source,ENGINE_ROOT):
        if output == original or original in output.parents or output in original.parents:
            raise recipes.ContractError('Preparation output must be outside and nonnested with source and engine checkouts')
    if not output.parent.is_dir():
        raise recipes.ContractError('Preparation output parent must already exist')
    git = LocalGit()
    object_budget = _metadata_guard(source/'.git')
    if Path(git.run(source,'rev-parse','--show-toplevel').decode().strip()) != source:
        raise recipes.ContractError('Select the original Git checkout root')
    config = _config_guard(git,source)
    if git.run(source,'for-each-ref','--format=%(refname)','refs/replace').strip():
        raise recipes.ContractError('Replacement refs are unsupported')
    hidden = git.run(source,'ls-files','-v','-z').split(b'\0')
    if any(row and not row.startswith(b'H ') for row in hidden):
        raise recipes.ContractError('Source must have no hidden skip-worktree or assume-unchanged index flags')
    before = _source_signature(git,source,config)
    revisions, proofs = _chain(git,source,good,bad)
    tree_budgets = [_tree_budget(git,source,revision) for revision in revisions]
    totals = {key:sum(row[key] for row in tree_budgets) for key in ('bytes','files')}
    upper_bound = {'bytes':2*totals['bytes'],'files':totals['files']}
    if upper_bound['bytes'] > MAX_CHECKOUT_BYTES or upper_bound['files'] > MAX_CHECKOUT_FILES:
        raise recipes.ContractError('Aggregate selected checkout resource limit exceeded')
    _verify_objects(git,source,revisions,proofs)
    free = shutil.disk_usage(output.parent).free
    if free < object_budget['bytes'] + upper_bound['bytes'] + MAX_METADATA_BYTES + 16*1024**2:
        raise recipes.ContractError('Insufficient observed free disk for bounded local preparation')
    output.mkdir(mode=0o700)
    bisection.write(output/'outcome-started.json', {'status':'preparing','execution':'not_requested'})
    try:
        for name in ('hooks','template','checkouts','build-plans','progress'):
            (output/name).mkdir(mode=0o700)
        owned_git = LocalGit(output/'hooks')
        owned_git.calls = git.calls
        repository = output/'repository.git'
        owned_git.run(output,'clone','--bare','--local','--no-hardlinks','--no-tags',
                '--template='+str(output/'template'),'--',source,repository)
        _metadata_guard(repository)
        _verify_objects(owned_git,repository,revisions,proofs)
        build_plans, candidates, materialized = [], [], []
        for index,(revision,raw) in enumerate(zip(revisions,proofs,strict=True)):
            relative = f'checkouts/{index:03d}-{revision}'
            checkout = output/relative
            owned_git.run(repository,'worktree','add','--detach','--',checkout,revision)
            materialized.append(_checkout_budget(checkout))
            if sum(row['entries'] for row in materialized) > MAX_CHECKOUT_FILES:
                raise recipes.ContractError('Aggregate materialized checkout entry bound exceeded')
            if any(sum(row[key] for row in materialized) > upper_bound[key] for key in ('bytes','files')):
                raise recipes.ContractError('Materialized checkouts exceed predeclared resource bound')
            build = targets.plan_source_build(recipe,checkout,revision,
                toolchain_image=toolchain_image,runtime_image=runtime_image,
                instrumentation=instrumentation,cflags=cflags,configure_flags=configure_flags)
            path = f'build-plans/{index:03d}-{revision}.json'
            bisection.write(output/path,build)
            candidate = {'revision':revision,'source_root':relative,'build_plan':path,
                'build_plan_sha256':_sha(_bytes(output/path)), 'commit_sha256':_sha(raw)}
            candidates.append(candidate)
            build_plans.append(build)
            bisection.write(output/f'progress/{index:03d}.json',candidate)
        plan = bisection.make_plan(recipe,build_plans,proofs,predicate=predicate,
            max_trials=max_trials,worker_timeout=worker_timeout,build_timeout=build_timeout)
        bisection.write(output/'bisection-plan.json',plan)
        after = _source_signature(git,source,_config_guard(git,source))
        recipes._same(before,after,'original source before/after signatures')
        manifest = {'schema':SCHEMA,'recipe':recipe,'recipe_sha256':recipes.recipe_sha256(recipe),
            'source_root':str(source),'good':good,'bad':bad,'controls':bisection.build_controls(build_plans[0]),
            'candidates':candidates,'prepared_repository':'repository.git',
            'bisection_plan':'bisection-plan.json',
            'bisection_plan_sha256':_sha(_bytes(output/'bisection-plan.json')),
            'source_signatures':{'before':before,'after':after},'resource_limits':_limits(),
            'accounting':{'objects':object_budget,'checkouts':{
                key:sum(row[key] for row in materialized) for key in ('bytes','files')},
                'trees':tree_budgets,'checkout_upper_bound':upper_bound},
            'execution':'not_requested','performance':bisection.POLICY,
            'copy_mode':'local-bare-clone-no-hardlinks'}
        (output/'REPORT.md').write_text(_report(manifest))
        manifest['report_sha256'] = _sha(_bytes(output/'REPORT.md'))
        bisection.write(output/'git-commands.json',git.calls)
        manifest['git_commands_sha256'] = _sha(_bytes(output/'git-commands.json'))
        bisection.write(output/'source-range.json',manifest)
        _verify_preparation(output/'source-range.json', terminal=False)
        bisection.write(output/'outcome.json',{'status':'prepared','execution':'not_requested',
            'source_range_sha256':_sha(_bytes(output/'source-range.json'))})
        return manifest
    except BaseException as exc:
        if not os.path.lexists(output/'outcome.json'):
            bisection.write(output/'outcome.json',{'status':'failed','execution':'not_requested',
                'reason':f'{type(exc).__name__}: {exc}',
                'limits':'Owned clone/checkouts/plans and partial files are retained; no automatic retry or cleanup.'})
        raise


def _verify_preparation(manifest_path, *, terminal=True):
    path = bisection.safe(manifest_path)
    root = path.parent
    manifest = bisection.load(path)
    recipes._keys(manifest, ('schema','recipe','recipe_sha256','source_root','good','bad','controls',
        'candidates','prepared_repository','bisection_plan','bisection_plan_sha256','source_signatures',
        'resource_limits','accounting','execution','performance','copy_mode','report_sha256','git_commands_sha256'))
    if manifest['schema'] != SCHEMA or manifest['execution'] != 'not_requested' or manifest['performance'] != bisection.POLICY:
        raise recipes.ContractError('Unsupported source-range contract or execution policy')
    if manifest['prepared_repository'] != 'repository.git' or manifest['bisection_plan'] != 'bisection-plan.json' or manifest['copy_mode'] != 'local-bare-clone-no-hardlinks':
        raise recipes.ContractError('Prepared source layout differs')
    recipes.validate_recipe(manifest['recipe'])
    if recipes.recipe_sha256(manifest['recipe']) != manifest['recipe_sha256']:
        raise recipes.ContractError('Prepared recipe binding differs')
    for key in ('good','bad'):
        recipes._match(manifest[key],recipes._REVISION,key,'a full Git commit')
    if not isinstance(manifest['source_root'],str) or not Path(manifest['source_root']).is_absolute():
        raise recipes.ContractError('Original source provenance must be an absolute path')
    recipes._keys(manifest['source_signatures'],('before','after'),where='source signatures')
    for signature in manifest['source_signatures'].values():
        _signature_schema(signature)
    recipes._same(manifest['resource_limits'],_limits(),'preparation resource limits')
    recipes._same(manifest['source_signatures']['before'],manifest['source_signatures']['after'],'source preservation signatures')
    for filename, field in (('bisection-plan.json','bisection_plan_sha256'),
            ('REPORT.md','report_sha256'),('git-commands.json','git_commands_sha256')):
        if _sha(_bytes(root/filename)) != manifest[field]:
            raise recipes.ContractError('Prepared artifact hash differs: '+filename)
    plan = bisection.validate_plan(bisection.load(root/'bisection-plan.json'))
    recipes._same(plan['recipe'],manifest['recipe'],'prepared bisection recipe')
    if not isinstance(manifest['candidates'],list) or len(manifest['candidates']) != len(plan['candidates']):
        raise recipes.ContractError('Prepared candidate count differs')
    _account_schema(manifest['accounting'],len(plan['candidates']))
    if manifest['good'] != plan['candidates'][0]['revision'] or manifest['bad'] != plan['candidates'][-1]['revision']:
        raise recipes.ContractError('Prepared range endpoint binding differs')
    git = LocalGit(root/'hooks')
    _metadata_guard(root/'repository.git')
    _owned_config_guard(root/'repository.git')
    if git.run(root/'repository.git','for-each-ref','--format=%(refname)','refs/replace').strip():
        raise recipes.ContractError('Prepared replacement refs are unsupported')
    _verify_objects(git,root/'repository.git',
        [candidate['revision'] for candidate in plan['candidates']],
        [base64.b64decode(candidate['commit_object'],validate=True) for candidate in plan['candidates']])
    tree_budgets, materialized = [], []
    for index,(candidate,frozen) in enumerate(zip(manifest['candidates'],plan['candidates'],strict=True)):
        recipes._keys(candidate,('revision','source_root','build_plan','build_plan_sha256','commit_sha256'))
        revision = frozen['revision']
        relative = f'checkouts/{index:03d}-{revision}'
        build_path = f'build-plans/{index:03d}-{revision}.json'
        if (candidate['revision'],candidate['source_root'],candidate['build_plan']) != (revision,relative,build_path):
            raise recipes.ContractError('Prepared candidate layout or revision differs')
        checkout = bisection.safe(root/relative)
        _owned_worktree(root,checkout)
        materialized.append(_checkout_budget(checkout))
        if sum(row['entries'] for row in materialized) > MAX_CHECKOUT_FILES:
            raise recipes.ContractError('Aggregate materialized checkout entry bound exceeded')
        _config_guard(git,checkout)
        common = git.run(checkout,'rev-parse','--git-common-dir').decode().strip()
        if (checkout/Path(common)).resolve() != root/'repository.git':
            raise recipes.ContractError('Prepared checkout points outside its owned repository')
        if _sha(_bytes(root/build_path)) != candidate['build_plan_sha256']:
            raise recipes.ContractError('Prepared build-plan bytes differ')
        build = targets.validate_build_plan(bisection.load(root/build_path))
        recipes._same(build,frozen['build_plan'],'frozen candidate build plan')
        if build['source_root'] != str(checkout):
            raise recipes.ContractError('Prepared checkout path differs; reprepare after relocation')
        controls = bisection.build_controls(build)
        recipes._same(controls,manifest['controls'],'prepared fixed controls')
        current = targets.plan_source_build(manifest['recipe'],checkout,revision,
            toolchain_image=controls['toolchain_image'],runtime_image=controls['runtime_image'],
            instrumentation=controls['instrumentation'],cflags=controls['cflags'],
            configure_flags=controls['configure_flags'])
        recipes._same(current,build,'current prepared source snapshot')
        raw = git.run(checkout,'cat-file','commit',revision)
        if _sha(raw) != candidate['commit_sha256'] or raw != base64.b64decode(frozen['commit_object'],validate=True):
            raise recipes.ContractError('Prepared commit proof differs')
        tree_budgets.append(_tree_budget(git,checkout,revision))
    totals = {key:sum(row[key] for row in tree_budgets) for key in ('bytes','files')}
    upper_bound = {'bytes':2*totals['bytes'],'files':totals['files']}
    physical_totals = {key:sum(row[key] for row in materialized) for key in ('bytes','files')}
    if any(upper_bound[key] > _limits()['checkout_'+key] or physical_totals[key] > upper_bound[key] for key in ('bytes','files')):
        raise recipes.ContractError('Prepared aggregate resource bound exceeded')
    recipes._same(tree_budgets,manifest['accounting']['trees'],'prepared tree accounting')
    recipes._same(physical_totals,manifest['accounting']['checkouts'],'prepared checkout accounting')
    recipes._same(upper_bound,manifest['accounting']['checkout_upper_bound'],'prepared checkout upper bound')
    if _bytes(root/'REPORT.md') != _report(manifest).encode():
        raise recipes.ContractError('Prepared human report disagrees with the frozen preparation')
    if terminal:
        outcome = bisection.load(root/'outcome.json')
        recipes._same(outcome,{'status':'prepared','execution':'not_requested',
            'source_range_sha256':_sha(_bytes(path))},'terminal source-range outcome')
    return {'valid':True,'schema':SCHEMA,'candidates':len(plan['candidates']),
            'recipe_sha256':manifest['recipe_sha256'],'execution':'not_requested',
            'performance':bisection.POLICY}


def verify_preparation(manifest_path):
    """Verify only owned preparation evidence/checkouts; never reopen source_root."""
    return _verify_preparation(manifest_path)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command',required=True)
    prepare = commands.add_parser('prepare')
    for name in ('recipe','source','good','bad','toolchain-image','runtime-image','output'):
        prepare.add_argument('--'+name,required=True)
    prepare.add_argument('--instrumentation',default='debug')
    prepare.add_argument('--cflags',default='-O0 -g')
    prepare.add_argument('--configure-flag',action='append',default=[])
    prepare.add_argument('--predicate',choices=('assertions','target_crash'),default='assertions')
    prepare.add_argument('--max-trials',type=int,default=32)
    prepare.add_argument('--worker-timeout',type=float,default=120)
    prepare.add_argument('--build-timeout',type=float,default=1200)
    verify = commands.add_parser('verify')
    verify.add_argument('manifest')
    args = parser.parse_args(argv)
    try:
        if args.command == 'verify':
            result = verify_preparation(args.manifest)
        else:
            result = prepare_range(bisection.load(args.recipe),source_root=args.source,
                good=args.good,bad=args.bad,toolchain_image=args.toolchain_image,
                runtime_image=args.runtime_image,output_dir=args.output,
                instrumentation=args.instrumentation,cflags=args.cflags,
                configure_flags=args.configure_flag,predicate=args.predicate,
                max_trials=args.max_trials,worker_timeout=args.worker_timeout,
                build_timeout=args.build_timeout)
        print(json.dumps(result,indent=2,sort_keys=True,allow_nan=False))
        return 0
    except (OSError,ValueError,TypeError,recipes.ContractError) as exc:
        print('Source range refused: '+str(exc),file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
