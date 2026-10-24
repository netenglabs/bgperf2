# Copyright (C) 2026 bgperf2 contributors. Apache-2.0.
"""Strict target substitutions and explicit, local-only BIRD source builds.

Importing this module probes no host and initializes no Docker client. Source
code is an explicit local trust boundary: the fixed build recipe executes that
code only through build_target(), never while creating or validating a plan.
"""
import copy
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import shlex
import signal
import stat
import subprocess
import tarfile
import threading
import uuid

import recipes
import recipe_preflight as runtime

TARGET_SCHEMA = 'bgperf2/target/v1alpha1'
BUILD_SCHEMA = 'bgperf2/target-build/v1alpha1'
INSTRUMENTATION = ('unknown', 'optimized', 'debug', 'asan', 'profiling')
SOURCE_LIMIT = 256 * 1024 * 1024
FLAG = re.compile(r'[A-Za-z0-9_./=+,:@%\-]+\Z')


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _file_sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _json(value):
    return json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n'


def _hex(value, where):
    return recipes._match(value, recipes._HEX64, where, 'a SHA-256 digest')


def _image(value, where):
    return recipes._match(value, recipes._IMAGE, where, 'an immutable image ID or repository digest')


def _source(value):
    recipes._keys(value, ('requested_revision', 'commit', 'checkout_head', 'dirty',
                         'include_dirty', 'patch_sha256', 'untracked', 'snapshot_sha256'), where='source')
    for field in ('requested_revision', 'commit', 'checkout_head'):
        recipes._match(value[field], recipes._REVISION, 'source.' + field, 'a full Git commit')
    if value['requested_revision'] != value['commit'] or value['checkout_head'] != value['commit']:
        raise recipes.ContractError('source: requested commit must be the explicit checkout HEAD')
    for field in ('dirty', 'include_dirty'):
        if not isinstance(value[field], bool):
            raise recipes.ContractError('source.' + field + ': expected a boolean')
    if value['dirty'] and not value['include_dirty']:
        raise recipes.ContractError('source: dirty state requires explicit include_dirty')
    for field in ('patch_sha256', 'snapshot_sha256'):
        _hex(value[field], 'source.' + field)
    if not isinstance(value['untracked'], list):
        raise recipes.ContractError('source.untracked: expected a list')
    seen = set()
    for item in value['untracked']:
        recipes._keys(item, ('path', 'sha256'), where='source.untracked item')
        recipes._artifact_path(item['path'], 'source.untracked.path')
        _hex(item['sha256'], 'source.untracked.sha256')
        if item['path'] in seen:
            raise recipes.ContractError('source.untracked: duplicate path')
        seen.add(item['path'])
    return value


def _flags(cflags, configure_flags, instrumentation):
    recipes._choice(instrumentation, INSTRUMENTATION, 'instrumentation')
    if not isinstance(cflags, str):
        raise recipes.ContractError('cflags: expected text')
    try:
        flags = shlex.split(cflags)
    except ValueError as exc:
        raise recipes.ContractError('cflags: invalid flag spelling') from exc
    if not all(FLAG.fullmatch(flag) for flag in flags):
        raise recipes.ContractError('cflags: shell syntax and unsupported characters are refused')
    if not isinstance(configure_flags, (list, tuple)) or not all(
            isinstance(flag, str) and flag.startswith('--') and FLAG.fullmatch(flag)
            for flag in configure_flags):
        raise recipes.ContractError('configure_flags: use a list of declarative --options, without shell syntax')
    if instrumentation == 'asan' and not any(flag.startswith('-fsanitize=') and 'address' in flag.split('=', 1)[1].split(',') for flag in flags):
        raise recipes.ContractError('asan instrumentation requires -fsanitize=address in cflags')
    observed_optimizations = [flag for flag in flags if re.fullmatch(r'-O[0-3sgz]', flag)]
    instrumentation_flags = ('-fsanitize=', '--coverage', '-fprofile', '-ftest-coverage', '-finstrument-functions', '-pg')
    if instrumentation == 'optimized' and (not observed_optimizations or observed_optimizations[-1] not in ('-O1', '-O2', '-O3', '-Os', '-Oz')
            or any(flag.startswith(instrumentation_flags) for flag in flags)):
        raise recipes.ContractError('optimized instrumentation requires optimization flags and refuses sanitizer/profiling flags')
    if instrumentation == 'profiling' and not any(flag.startswith(instrumentation_flags[1:]) for flag in flags):
        raise recipes.ContractError('profiling instrumentation requires explicit profiling/coverage flags')
    return ' '.join(flags), list(configure_flags)


def supplied_target(recipe, image, *, label=None, instrumentation='unknown'):
    """Declare a supplied binary, keeping unknown source/build facts explicit."""
    recipes.validate_recipe(recipe)
    _image(image, 'image')
    recipes._choice(instrumentation, INSTRUMENTATION, 'instrumentation')
    document = {'schema': TARGET_SCHEMA, 'recipe_sha256': recipes.recipe_sha256(recipe),
                'adapter': 'bird', 'image': image, 'label': label,
                'provenance': {'kind': 'supplied_image', 'source': None, 'build': None,
                               'instrumentation': instrumentation,
                               'limits': ['Source, toolchain, compiler flags, binary hash and reconstructibility are unknown for a supplied image.',
                                          'Instrumentation is a caller declaration, not a verified binary property.']}}
    return validate_target(document, recipe)


def validate_target(document, recipe=None):
    """Validate the strict override, optionally binding it to the exact base recipe."""
    recipes._keys(document, ('schema', 'recipe_sha256', 'adapter', 'image', 'label', 'provenance'))
    recipes._choice(document['schema'], (TARGET_SCHEMA,), 'schema')
    _hex(document['recipe_sha256'], 'recipe_sha256')
    recipes._choice(document['adapter'], ('bird',), 'adapter')
    _image(document['image'], 'image')
    if document['label'] is not None:
        recipes._text(document['label'], 'label')
    provenance = document['provenance']
    recipes._keys(provenance, ('kind', 'source', 'build', 'instrumentation', 'limits'), where='provenance')
    recipes._choice(provenance['kind'], ('supplied_image', 'local_source'), 'provenance.kind')
    recipes._choice(provenance['instrumentation'], INSTRUMENTATION, 'provenance.instrumentation')
    if not isinstance(provenance['limits'], list) or not provenance['limits'] or not all(isinstance(item, str) and item.strip() for item in provenance['limits']):
        raise recipes.ContractError('provenance.limits: expected nonempty explanatory strings')
    if provenance['kind'] == 'supplied_image':
        if provenance['source'] is not None or provenance['build'] is not None:
            raise recipes.ContractError('supplied images must not invent source/build identities')
    else:
        source = _source(provenance['source'])
        build = provenance['build']
        recipes._keys(build, ('recipe', 'toolchain_image', 'runtime_image', 'toolchain_image_id', 'runtime_image_id', 'compiler_flags', 'linker_flags',
                             'configure_flags', 'dockerfile_sha256', 'source_snapshot_sha256',
                             'build_log_sha256', 'image_id', 'binary_sha256', 'reconstructible'), where='build')
        recipes._choice(build['recipe'], ('bird-local/v1',), 'build.recipe')
        for field in ('toolchain_image', 'runtime_image', 'toolchain_image_id', 'runtime_image_id', 'image_id'):
            _image(build[field], 'build.' + field)
        if not all(build[field].startswith('sha256:') for field in ('toolchain_image_id', 'runtime_image_id')):
            raise recipes.ContractError('Observed toolchain/runtime identities must be actual immutable image IDs')
        if not build['image_id'].startswith('sha256:') or document['image'] != build['image_id']:
            raise recipes.ContractError('local build image must equal its observed immutable image ID')
        for field in ('dockerfile_sha256', 'source_snapshot_sha256', 'build_log_sha256'):
            _hex(build[field], 'build.' + field)
        if build['source_snapshot_sha256'] != source['snapshot_sha256']:
            raise recipes.ContractError('build/source snapshot identities differ')
        _flags(build['compiler_flags'], build['configure_flags'], provenance['instrumentation'])
        if build['linker_flags'] != build['compiler_flags']:
            raise recipes.ContractError('bird-local/v1 passes the recorded flags to compilation and linking')
        if build['binary_sha256'] is not None or build['reconstructible'] is not False:
            raise recipes.ContractError('binary identity and reconstruction are not established by this builder')
    if recipe is not None:
        recipes.validate_recipe(recipe)
        if document['recipe_sha256'] != recipes.recipe_sha256(recipe):
            raise recipes.ContractError('target override belongs to a different base recipe')
    return document


def effective_roles(recipe, target=None):
    recipes.validate_recipe(recipe)
    roles = copy.deepcopy(recipe['roles'])
    if target is not None:
        validate_target(target, recipe)
        roles['target']['image'] = target['image']
    return roles


def _git(root, *args):
    env = runtime._environment()
    env['GIT_NO_LAZY_FETCH'] = '1'
    env['GIT_TERMINAL_PROMPT'] = '0'
    command = ['git', '-c', 'core.fsmonitor=false', '-c', 'core.untrackedCache=false', '-C', str(root), *map(str, args)]
    try:
        result = subprocess.run(command, env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, timeout=15, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise recipes.ContractError('Cannot inspect explicit source checkout: ' + str(exc)) from exc
    if result.returncode:
        raise recipes.ContractError('Source Git inspection failed: ' + result.stderr.decode('utf-8', 'replace')[-2000:])
    return result.stdout


def _snapshot(source_root, revision, include_dirty):
    root = Path(source_root)
    if not root.is_absolute() or not root.is_dir():
        raise recipes.ContractError('source_root: specify an existing absolute Git checkout')
    root = root.resolve()
    if Path(_git(root, 'rev-parse', '--show-toplevel').decode().strip()).resolve() != root:
        raise recipes.ContractError('source_root must name the Git checkout root, not a subdirectory')
    # --no-textconv/--no-ext-diff do not disable Git clean/process filters.
    # Refuse inherited or checkout-local filter configuration before any work
    # tree comparison can execute a command from the source's Git configuration.
    configured = _git(root, 'config', '--name-only', '--list').decode('utf-8').splitlines()
    if any(key.startswith('filter.') for key in configured):
        raise recipes.ContractError('Source planning refuses configured Git clean/process filters, including inherited filters; use a checkout/configuration without them')
    if any(key == 'extensions.partialclone' or re.fullmatch(r'remote\..+\.promisor', key)
           for key in configured):
        raise recipes.ContractError('Source planning refuses partial-clone/promisor configuration; use a complete local checkout with no lazy object acquisition')
    if ('core.sparsecheckout' in configured
            and _git(root, 'config', '--bool', '--get', 'core.sparsecheckout').decode().strip() == 'true'):
        raise recipes.ContractError('Source planning requires a full nonsparse checkout; sparse checkout capture is unsupported')
    index_entries = _git(root, 'ls-files', '-v', '-z').decode('utf-8').split('\0')
    if any(entry and entry[:1] != 'H' for entry in index_entries):
        raise recipes.ContractError('Source planning requires a full checkout without skip-worktree or assume-unchanged index flags')
    recipes._match(revision, recipes._REVISION, 'revision', 'a full source commit')
    if not isinstance(include_dirty, bool):
        raise recipes.ContractError('include_dirty: expected a boolean')
    head = _git(root, 'rev-parse', '--verify', 'HEAD^{commit}').decode().strip()
    actual = _git(root, 'rev-parse', '--verify', revision + '^{commit}').decode().strip()
    if head != actual or actual != revision:
        raise recipes.ContractError('Select the source checkout at the exact requested commit; no checkout is changed automatically')
    patch = _git(root, 'diff', '--binary', '--no-ext-diff', '--no-textconv', revision, '--')
    untracked_paths = _git(root, 'ls-files', '--others', '--exclude-standard', '-z').decode('utf-8').split('\0')
    untracked_paths = sorted(path for path in untracked_paths if path)
    dirty = bool(patch or untracked_paths)
    if dirty and not include_dirty:
        raise recipes.ContractError('Source has local changes; explicitly select include_dirty to capture tracked and untracked modifications')
    tree = _git(root, 'ls-tree', '-rz', '--full-tree', revision).split(b'\0')
    entries = {}
    for item in tree:
        if not item:
            continue
        metadata, raw_path = item.split(b'\t', 1)
        mode, kind, object_id = metadata.decode().split()
        path = raw_path.decode('utf-8')
        recipes._artifact_path(path, 'source path')
        if kind != 'blob' or mode not in ('100644', '100755'):
            raise recipes.ContractError('Source symlinks/submodules are unsupported: ' + path)
        size = int(_git(root, 'cat-file', '-s', object_id))
        if size > SOURCE_LIMIT or sum(len(data) for _, data in entries.values()) + size > SOURCE_LIMIT:
            raise recipes.ContractError('Source snapshot exceeds the 256 MiB limit')
        entries[path] = (mode == '100755', _git(root, 'cat-file', 'blob', object_id))
    if include_dirty:
        # Use the work tree, including added tracked/untracked files and deletions.
        selected = sorted(set(path for path in _git(root, 'ls-files', '-z').decode('utf-8').split('\0') if path) | set(untracked_paths))
        if len(selected) > 20000:
            raise recipes.ContractError('Source snapshot exceeds the 20,000-file limit')
        entries = {}
        consumed = 0
        for path in selected:
            recipes._artifact_path(path, 'source path')
            file = root / path
            try:
                observed = file.lstat()
            except FileNotFoundError:
                continue
            if not stat.S_ISREG(observed.st_mode):
                raise recipes.ContractError('Source must contain regular files, not symlinks/submodules/endpoints: ' + path)
            remaining = SOURCE_LIMIT - consumed
            if observed.st_size > remaining:
                raise recipes.ContractError('Source snapshot exceeds the 256 MiB limit')
            # Share the package reader's dirfd walk: a changing ancestor must
            # not redirect an explicitly selected source read outside its root.
            from recipe_results import _regular_file
            with _regular_file(root, path) as stream:
                actual_mode = os.fstat(stream.fileno()).st_mode
                data = stream.read(remaining + 1)
                if len(data) > remaining:
                    raise recipes.ContractError('Source snapshot exceeds the 256 MiB limit')
                entries[path] = (bool(actual_mode & 0o111), data)
                consumed += len(data)
    if not entries or len(entries) > 20000 or sum(len(data) for _, data in entries.values()) > SOURCE_LIMIT:
        raise recipes.ContractError('Source snapshot is empty or exceeds the 256 MiB/20,000-file limit')
    if not {'configure.ac', 'Makefile.in'} <= entries.keys():
        raise recipes.ContractError('bird-local/v1 requires a BIRD-style configure.ac and Makefile.in source tree')
    if (_git(root, 'rev-parse', '--verify', 'HEAD^{commit}').decode().strip() != head
            or _git(root, 'diff', '--binary', '--no-ext-diff', '--no-textconv', revision, '--') != patch
            or sorted(path for path in _git(root, 'ls-files', '--others', '--exclude-standard', '-z').decode('utf-8').split('\0') if path) != untracked_paths):
        raise recipes.ContractError('Source checkout changed while taking its snapshot; retry planning after edits stop')
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w', format=tarfile.USTAR_FORMAT) as archive:
        for path, (executable, data) in sorted(entries.items()):
            item = tarfile.TarInfo(path)
            item.size = len(data); item.mode = 0o755 if executable else 0o644
            item.mtime = item.uid = item.gid = 0
            item.uname = item.gname = ''
            archive.addfile(item, io.BytesIO(data))
    snapshot = buffer.getvalue()
    source = {'requested_revision': revision, 'commit': actual, 'checkout_head': head,
              'dirty': dirty, 'include_dirty': include_dirty, 'patch_sha256': _sha(patch),
              'untracked': [{'path': path, 'sha256': _sha(entries[path][1])} for path in untracked_paths if path in entries],
              'snapshot_sha256': _sha(snapshot)}
    return source, snapshot, patch


def plan_source_build(recipe, source_root, revision, *, toolchain_image, runtime_image,
                      instrumentation='debug', cflags='-O0 -g', include_dirty=False,
                      configure_flags=()):
    """Inspect local source and emit identities; never execute code or Docker."""
    recipes.validate_recipe(recipe)
    _image(toolchain_image, 'toolchain_image'); _image(runtime_image, 'runtime_image')
    cflags, configure_flags = _flags(cflags, configure_flags, instrumentation)
    source, _, _ = _snapshot(source_root, revision, include_dirty)
    plan = {'schema': BUILD_SCHEMA, 'recipe': copy.deepcopy(recipe),
            'recipe_sha256': recipes.recipe_sha256(recipe), 'source_root': str(Path(source_root).resolve()),
            'source': source, 'toolchain_image': toolchain_image, 'runtime_image': runtime_image,
            'instrumentation': instrumentation, 'cflags': cflags, 'configure_flags': configure_flags,
            'build_recipe': 'bird-local/v1', 'network': 'none',
            'requirements': ['Toolchain image must already contain bash, tar, autoreconf, C compiler, make and BIRD development dependencies.',
                             'Runtime image must already contain bash, iproute2 and all libraries required by the installed BIRD binaries.'],
            'limits': ['Only the explicit source checkout is trusted. Its configure/build code executes inside the selected Docker builder.',
                       'Source planning refuses Git clean/process filter configuration before comparing the work tree.',
                       'Source planning requires a complete nonsparse local Git checkout without hidden index flags; partial-clone/promisor configuration and lazy object acquisition are unsupported.',
                       'No package installation, Git clone, registry pull or source checkout modification is performed.',
                       'Immutable base images and source hashes do not prove hermetic builds or a reconstructible binary.',
                       'Compiler/linker flags are requested build configuration; trusted source may override them. Build commands remain in build.log.',
                       'Build timeout stops owned CLI clients; daemon-side build/cache work may continue.']}
    return validate_build_plan(plan)


def validate_build_plan(plan):
    recipes._keys(plan, ('schema', 'recipe', 'recipe_sha256', 'source_root', 'source',
                        'toolchain_image', 'runtime_image', 'instrumentation', 'cflags',
                        'configure_flags', 'build_recipe', 'network', 'requirements', 'limits'))
    recipes._choice(plan['schema'], (BUILD_SCHEMA,), 'schema')
    recipes.validate_recipe(plan['recipe'])
    if recipes.recipe_sha256(plan['recipe']) != plan['recipe_sha256']:
        raise recipes.ContractError('Build plan recipe binding differs')
    if not isinstance(plan['source_root'], str) or not Path(plan['source_root']).is_absolute():
        raise recipes.ContractError('source_root: expected an absolute checkout path')
    _source(plan['source'])
    for field in ('toolchain_image', 'runtime_image'):
        _image(plan[field], field)
    cflags, options = _flags(plan['cflags'], plan['configure_flags'], plan['instrumentation'])
    if cflags != plan['cflags'] or options != plan['configure_flags']:
        raise recipes.ContractError('Build flags must use their canonical spelling')
    recipes._choice(plan['build_recipe'], ('bird-local/v1',), 'build_recipe')
    recipes._choice(plan['network'], ('none',), 'network')
    for field in ('requirements', 'limits'):
        if not isinstance(plan[field], list) or not plan[field] or not all(isinstance(value, str) and value.strip() for value in plan[field]):
            raise recipes.ContractError(field + ': expected nonempty explanatory strings')
    return plan


def _dockerfile(toolchain_id, runtime_id, plan):
    options = ' '.join(shlex.quote(value) for value in plan['configure_flags'])
    return (f'FROM {toolchain_id} AS build\nWORKDIR /src/bird\n'
            'COPY source.tar /src/source.tar\n'
            'RUN tar -xf /src/source.tar -C /src/bird\n'
            f'ENV CFLAGS={json.dumps(plan["cflags"])}\nENV LDFLAGS={json.dumps(plan["cflags"])}\n'
            f'RUN autoreconf -i && ./configure --prefix=/usr/local {options} && make -j2 && make install DESTDIR=/install '
            '&& test -x /install/usr/local/sbin/bird && test -x /install/usr/local/sbin/birdc\n'
            f'FROM {runtime_id}\nCOPY --from=build /install/usr/local /usr/local\n'
            'ENV PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin\n'
            'ENTRYPOINT []\nCMD ["/bin/bash"]\n')


def _run_build(argv, *, env, timeout, log_path):
    previous = None
    if threading.current_thread() is threading.main_thread() and signal.getsignal(signal.SIGTERM) == signal.SIG_DFL:
        previous = signal.signal(signal.SIGTERM, runtime._terminate_command)
    try:
        with Path(log_path).open('xb') as output:
            process = subprocess.Popen(list(map(str, argv)), env=env, stdout=output,
                                       stderr=subprocess.STDOUT, start_new_session=True)
            try:
                code = process.wait(timeout=timeout)
            except BaseException as exc:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired as stop_error:
                    raise recipes.ContractError('Build client could not be reaped after SIGKILL; retain work and inspect host/daemon state') from stop_error
                if isinstance(exc, subprocess.TimeoutExpired):
                    raise recipes.ContractError('Local source build timed out; its client group stopped, but daemon/cache work may continue') from exc
                raise
            if code:
                raise recipes.ContractError(f'Local source build exited {code}; inspect preserved build.log')
    finally:
        if previous is not None:
            signal.signal(signal.SIGTERM, previous)


def build_target(plan, *, output_dir, emit_disclosure, timeout=1200, command=None):
    """Explicitly build one trusted local snapshot, retaining every build artifact."""
    validate_build_plan(plan)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise recipes.ContractError('Build timeout must be finite and positive')
    if not callable(emit_disclosure):
        raise recipes.ContractError('A build disclosure callback is required')
    output = Path(output_dir)
    if not output.is_absolute() or os.path.lexists(output):
        raise recipes.ContractError('Build output must be a new absolute directory')
    canonical = output.resolve()
    checkout = Path(plan['source_root']).resolve()
    if canonical == checkout or checkout in canonical.parents:
        raise recipes.ContractError('Build output must be outside the maintainer source checkout')
    engine = Path(__file__).resolve().parent
    if canonical == engine or engine in canonical.parents:
        raise recipes.ContractError('Build output must be outside the engine checkout')
    source, snapshot, patch = _snapshot(plan['source_root'], plan['source']['requested_revision'], plan['source']['include_dirty'])
    if source != plan['source']:
        raise recipes.ContractError('Local source changed since planning; create and review a new plan')
    report = runtime._report(plan['recipe'], 'target-build')
    env, host, ready = runtime.runtime_prerequisites(report, plan['recipe'])
    if not ready or report['status'] == 'refused':
        raise recipes.ContractError('Build prerequisites refused: ' + _json(report))
    bases = {role: runtime.inspect_image(plan[role], host, env) for role in ('toolchain_image', 'runtime_image')}
    tag = 'bgperf/bird-local:' + uuid.uuid4().hex
    inspect = ['docker', '--host', host, 'image', 'inspect', tag]
    try:
        runtime.run_command(inspect, env=env)
    except runtime.CommandError as exc:
        from recipe_prepare import _missing_image
        if not _missing_image(exc, tag, host):
            raise recipes.ContractError('Cannot establish a new unique build tag: ' + str(exc)) from exc
    else:
        raise recipes.ContractError('Unique build tag already exists; no existing tag is overwritten')
    dockerfile = _dockerfile(bases['toolchain_image']['image_id'], bases['runtime_image']['image_id'], plan)
    disclosure = {'operation': 'explicit_local_source_build', 'tag': tag, 'source': source,
                  'base_images': bases, 'network': 'none', 'output_dir': str(canonical),
                  'timeout_seconds': timeout, 'limits': plan['limits']}
    emit_disclosure(copy.deepcopy(disclosure))
    # Recheck the guard after the operator-visible disclosure and before mutation.
    runtime.run_command([str(runtime.ROOT / 'venv/bin/python'), '-I',
                         str(runtime.ROOT / 'scripts/quality_gate.py'), '--guard-only'], env=env)
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    (output / 'source.tar').write_bytes(snapshot)
    (output / 'source.patch').write_bytes(patch)
    (output / 'Dockerfile').write_text(dockerfile)
    (output / '.dockerignore').write_text('*\n!Dockerfile\n!source.tar\n')
    (output / 'plan.json').write_text(_json(plan))
    (output / 'disclosure.json').write_text(_json(disclosure))
    argv = ['docker', '--host', host, 'build', '--pull=false', '--network=none', '--rm=true',
            '--label', 'bgperf2.local_source_sha256=' + source['snapshot_sha256'],
            '--tag', tag, str(output)]
    try:
        (command or _run_build)(argv, env=env, timeout=timeout, log_path=output / 'build.log')
        images = json.loads(runtime.run_command(inspect, env=env))
        if not isinstance(images, list) or len(images) != 1:
            raise recipes.ContractError('Built image inspection did not return one image')
        image_id = images[0].get('Id')
        recipes._match(image_id, re.compile(r'sha256:[0-9a-f]{64}\Z'), 'built image ID', 'an immutable image ID')
        labels = images[0].get('Config', {}).get('Labels') or {}
        if labels.get('bgperf2.local_source_sha256') != source['snapshot_sha256']:
            raise recipes.ContractError('Built image does not carry the selected source snapshot identity')
        runtime.inspect_image(image_id, host, env)
        target = {'schema': TARGET_SCHEMA, 'recipe_sha256': plan['recipe_sha256'], 'adapter': 'bird',
                  'image': image_id, 'label': 'BIRD local ' + source['commit'][:12],
                  'provenance': {'kind': 'local_source', 'source': source,
                                 'instrumentation': plan['instrumentation'], 'limits': plan['limits'],
                                 'build': {'recipe': 'bird-local/v1', 'toolchain_image': plan['toolchain_image'],
                                           'runtime_image': plan['runtime_image'], 'compiler_flags': plan['cflags'],
                                           'toolchain_image_id': bases['toolchain_image']['image_id'],
                                           'runtime_image_id': bases['runtime_image']['image_id'],
                                           'linker_flags': plan['cflags'],
                                           'configure_flags': plan['configure_flags'], 'dockerfile_sha256': _sha(dockerfile.encode()),
                                           'source_snapshot_sha256': source['snapshot_sha256'], 'build_log_sha256': _file_sha(output / 'build.log'),
                                           'image_id': image_id, 'binary_sha256': None, 'reconstructible': False}}}
        validate_target(target, plan['recipe'])
        (output / 'target.json').write_text(_json(target))
        (output / 'build-result.json').write_text(_json({'status': 'built', 'image_id': image_id, 'tag': tag}))
        return target
    except BaseException as exc:
        (output / 'build-result.json').write_text(_json({'status': 'failed', 'reason': f'{type(exc).__name__}: {exc}',
                                                     'tag': tag, 'retention': 'Build work, partial logs and any Docker cache/image state are retained; no rollback.'}))
        raise
