#!/usr/bin/env python3
# Copyright (C) 2026 bgperf2 contributors. Apache-2.0.
"""Freeze one offline sink-build/prefix-capture case; never execute commands."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shlex
import sys
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import recipes
from recipe_results import _regular_file
from recipe_source_range import LocalGit

SCHEMA = 'bgperf2/prefix-identity-case/v1alpha1'
GO = 'sha256:e3c6b02e53225e75dff3e6a3b4c0bf9567fe16564fb20a5f63d4e39361ee32e3'
RUNTIME = 'sha256:db9f02c6bde9fa90cc8074c92754b2b046947392f1a857726e77f041febb7b82'
BIRD = 'sha256:db0a8e144635b1d4b9f81f24ee78f11383c5b0cbd79f10353edcb8452e9af423'
MODULES = (('github.com/osrg/gobgp/v4', 'v4.9.0'), ('golang.org/x/sys', 'v0.45.0'))
GO_MOD = '68a633be5947671b167fd7cea339f71b6623d3a8c07308801111d829ff2bc955'
GO_SUM = '1e790973d4ce7a1939be9616452b1d155c9a662b31702e932af9e4d6aa2da72e'
MAX_FILE = 16 * 1024 * 1024
QUESTION = 'Does one BIRD peer deliver exactly the expected 100 IPv4 host routes to the new sink snapshot?'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def safe(value):
    path = Path(value)
    if not path.is_absolute() or '..' in path.parts:
        raise recipes.ContractError('Use an absolute path without parent traversal')
    for parent in (path, *path.parents):
        if parent.is_symlink():
            raise recipes.ContractError('Symlink paths are unsupported: ' + str(parent))
    return path


def read(root, relative):
    with _regular_file(root, relative) as stream:
        data = stream.read(MAX_FILE + 1)
    if len(data) > MAX_FILE:
        raise recipes.ContractError('Input exceeds the 16 MiB file bound')
    return data


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(data)


def encode(value):
    return (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()


def revision():
    git = LocalGit()
    head = git.run(ROOT, 'rev-parse', '--verify', 'HEAD^{commit}').decode().strip()
    entries = git.run(ROOT, 'ls-files', '-v', '-z').split(b'\0')
    if any(entry and entry[:1] != b'H' for entry in entries):
        raise recipes.ContractError('Engine index has hidden or unsupported entries')
    if git.run(ROOT, 'status', '--porcelain', '--untracked-files=all', '--ignore-submodules=none').strip():
        raise recipes.ContractError('Prepare from a clean committed engine checkout')
    if not re.fullmatch('[0-9a-f]{40}', head):
        raise recipes.ContractError('Invalid engine revision')
    return head


def source_archive():
    files = sorted(p.name for p in (ROOT/'sink').iterdir()
                   if p.suffix == '.go' or p.name in ('go.mod', 'go.sum'))
    if not 1 <= len(files) <= 128:
        raise recipes.ContractError('Unexpected sink source file count')
    contents = {name: read(ROOT/'sink', name) for name in files}
    if sha(contents['go.mod']) != GO_MOD or sha(contents['go.sum']) != GO_SUM:
        raise recipes.ContractError('This bounded case requires the reviewed GoBGP 4.9.0/x-sys 0.45.0 pins')
    if b'const sinkVersion = "0.2.0"' not in contents.get('main.go', b''):
        raise recipes.ContractError('This case requires the reviewed sink 0.2.0 source')
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w', format=tarfile.USTAR_FORMAT) as archive:
        for name, data in contents.items():
            item = tarfile.TarInfo(name)
            item.size, item.mode, item.mtime = len(data), 0o644, 0
            archive.addfile(item, io.BytesIO(data))
    return output.getvalue()


def cache_inputs(cache):
    result = {}
    for module, version in MODULES:
        stem = module + '/@v/' + version
        for suffix in ('.info', '.mod', '.zip'):
            data = read(cache, stem + suffix)
            if suffix == '.zip':
                with zipfile.ZipFile(io.BytesIO(data)) as archive:
                    rows = archive.infolist()
                    names = [row.filename for row in rows]
                    if (len(rows) > 2000 or len(set(names)) != len(names)
                            or sum(row.file_size for row in rows) > 32 * 1024 * 1024
                            or any(not name.startswith(module + '@' + version + '/')
                                   or '..' in Path(name).parts or '\\' in name for name in names)
                            or any((row.external_attr >> 16) & 0o170000 == 0o120000 for row in rows)):
                        raise recipes.ContractError('Unsafe or oversized cached module archive')
            # Do not copy cached .ziphash or extracted trees: the offline Go
            # build must recompute checksums against the committed go.sum.
            result['inputs/cache/' + stem + suffix] = data
    return result


def cache_archive(inputs):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w', format=tarfile.USTAR_FORMAT) as archive:
        for path, data in sorted(inputs.items()):
            item = tarfile.TarInfo(path.removeprefix('inputs/cache/'))
            item.size, item.mode, item.mtime = len(data), 0o644, 0
            archive.addfile(item, io.BytesIO(data))
    return output.getvalue()


def dockerfile(source_sha, case_id):
    return f'''FROM {GO} AS build
LABEL org.bgperf2.validation.case="{case_id}"
ENV GOPROXY=off GOSUMDB=off GOTOOLCHAIN=local GOMAXPROCS=2 GOFLAGS="-mod=readonly -p=2" GOMODCACHE=/bgperf-mod-{case_id}
COPY sink-source.tar module-cache.tar /bgperf-inputs/
RUN test ! -e /bgperf-work-{case_id} && test ! -e "$GOMODCACHE" && mkdir -p /bgperf-work-{case_id} "$GOMODCACHE/cache/download" && tar -xf /bgperf-inputs/sink-source.tar -C /bgperf-work-{case_id} && tar -xf /bgperf-inputs/module-cache.tar -C "$GOMODCACHE/cache/download" && cd /bgperf-work-{case_id} && go mod download && go mod verify && go vet ./... && go test -count=1 ./... && CGO_ENABLED=0 go build -trimpath -ldflags '-X main.sourceHash={source_sha[:12]}' -o /bgperf-sink .
FROM {RUNTIME}
COPY --from=build /bgperf-sink /usr/local/bin/bgperf-sink
LABEL org.bgperf2.validation.source-sha256="{source_sha}"
LABEL org.bgperf2.validation.case="{case_id}"
'''.encode()


def commands(case, execution):
    python, script, cli = str(ROOT/'venv/bin/python'), str(Path(__file__).resolve()), str(ROOT/'recipes.py')
    build, bound = execution/'build', execution/'bound'
    return {
        'guard': [python, str(ROOT/'scripts/quality_gate.py'), '--guard-only'],
        'environment': [python, '-I', str(ROOT/'scripts/bootstrap.py'), '--check'],
        'images': ['docker', '--host', 'unix:///var/run/docker.sock', 'image', 'inspect', GO, RUNTIME, BIRD],
        'mount': ['findmnt', '-T', str(case.parent), '-o', 'TARGET,SOURCE,FSTYPE,OPTIONS', '--json'],
        'disk': ['df', '-B1', str(case.parent)],
        'memory': ['free', '-b'],
        'processes': ['ps', '-eo', 'pid,ppid,etime,args'],
        'cpu_admission': ['timeout', '--signal=TERM', '--kill-after=5', '45', 'mpstat', '-P', 'ALL', '-o', 'JSON', '5', '6'],
        'containers': ['docker', '--host', 'unix:///var/run/docker.sock', 'ps', '-a', '--no-trunc', '--format', '{{json .}}'],
        'networks': ['docker', '--host', 'unix:///var/run/docker.sock', 'network', 'ls', '--no-trunc', '--format', '{{json .}}'],
        'volumes': ['docker', '--host', 'unix:///var/run/docker.sock', 'volume', 'ls', '--format', '{{json .}}'],
        'build': ['timeout', '--signal=TERM', '--kill-after=10', '900', 'env', 'DOCKER_BUILDKIT=0',
            'docker', '--host', 'unix:///var/run/docker.sock', 'build', '--network=none', '--pull=false',
            '--rm=false', '--iidfile', str(build/'image-id.txt'), '--file', str(case/'context/Dockerfile'), str(case/'context')],
        'image_commands': [python, script, 'image-commands', str(case)],
        'bind': [python, script, 'bind', str(case)],
        'verify_bound': [python, script, 'verify-bound', str(case)],
        'check': [python, cli, 'check', str(bound/'recipe.json'), '--workdir', str(execution/'work'), '--results-dir', str(execution/'results')],
        'run': [python, cli, 'run', str(bound/'recipe.json'), '--timeout', '120', '--diagnostics', 'basic',
            '--observer-prefixes', '--workdir', str(execution/'work'), '--results-dir', str(execution/'results')],
        'verify': [python, cli, 'result-verify', str(execution/'results/result.json')],
        'assertions': [python, cli, 'assertions-check', str(bound/'assertions.json'), '--result', str(execution/'results/result.json')]}


def runbook(case, meta, graph):
    lines = ['# Prefix-identity execution case', '',
        'PREPARED ONLY. One execution approval is required; no command has run.', '',
        'Authoritative conditions: ' + str(ROOT/'docs/plans/observer-prefix-runtime-validation.md'), '',
        f'Engine: `{meta["engine_revision"]}`; source archive SHA-256: `{meta["source_sha256"]}`.', '',
        'Budget: one 900-second offline sink build, one 15-second version probe container,',
        'one 120-second BIRD worker; 30-minute overall operator ceiling; zero retries.', '',
        'Save admission stdout/stderr/exits in the fresh sibling admissionNN directory.',
        'For each mpstat interval, aggregate busy fraction x number-of-cpus must be <= 1 core.',
        'Total busy CPU is a conservative bound on outside work; no quiet-throughout claim follows.',
        'Confirm no other development/build/test work; do not treat passing CPU alone as exclusivity.',
        'Repeat guard/images/memory/disk immediately before build and worker; retain all outputs.',
        'Repeat full Docker inventories after worker/terminal handling and review unrelated-resource preservation.', '',
        'Only after admission, create the selected execution/build directories.',
        'Save build stdout/stderr and its actual exit at execution/build/build.log and build-exit.json.',
        'Stop on failure; timeout may leave Docker daemon work and build containers to inspect.',
        'Build intermediates are retained (--rm=false); never prune them.', '',
        'After build, image-commands prints exact commands using the strictly validated returned image ID.',
        'Save their stdout at build/image-inspect.json and build/version.txt and actual exits.',
        'Bind runs offline only after successful build/readback review; it creates bound recipe/assertions.',
        'No future observer image ID is guessed. Keep current bgperf/sink images untouched.', '',
        '## Commands in dependency order', '']
    for name, argv in graph.items():
        lines += ['### ' + name, '', '```sh', shlex.join(argv), '```', '']
    return '\n'.join(lines)


def material(cache, case, execution):
    head, archive = revision(), source_archive()
    case_id = sha(str(case).encode())[:16]
    meta = {'schema': SCHEMA, 'engine_revision': head, 'cache': str(cache), 'case_id': case_id,
            'execution': str(execution), 'source_sha256': sha(archive), 'authorization': 'pending',
            'source_builds': 1, 'workers': 1, 'version_probe_containers': 1,
            'version_probe_seconds': 15, 'build_kill_grace_seconds': 10, 'probe_kill_grace_seconds': 5,
            'build_seconds': 900, 'worker_seconds': 120, 'operator_seconds': 1800,
            'retries': 0, 'performance_policy': 'disabled', 'calibration': 'deferred'}
    graph = commands(case, execution)
    data = cache_inputs(cache)
    data.update({'context/sink-source.tar': archive, 'context/module-cache.tar': cache_archive(data),
                 'context/Dockerfile': dockerfile(sha(archive), case_id),
                 'case.json': encode(meta), 'commands.json': encode(graph),
                 'CASE.md': runbook(case, meta, graph).encode()})
    return data


def roots(cache, case, execution):
    cache, case, execution = map(safe, (cache, case, execution))
    roots = (ROOT.resolve(), cache, case, execution)
    if any(a == b or a in b.parents or b in a.parents for i, a in enumerate(roots) for b in roots[i+1:]):
        raise recipes.ContractError('Engine, cache, case and execution roots must be disjoint')
    if not re.fullmatch('case[0-9]{2,}', case.name) or execution != case.with_name('execution'+case.name[4:]):
        raise recipes.ContractError('Select caseNN and its fixed sibling executionNN destination')
    return cache, case, execution


def prepare(cache, case, execution):
    cache, case, execution = roots(cache, case, execution)
    if os.path.lexists(case) or os.path.lexists(execution):
        raise recipes.ContractError('Choose fresh case and execution destinations')
    data = material(cache, case, execution)
    case.mkdir(mode=0o700)
    for relative, value in data.items():
        save(case/relative, value)
    save(case/'SHA256SUMS.json', encode({name: sha(value) for name, value in data.items()}))
    return verify(case)


def verify(case, *, started=False):
    case = safe(case)
    meta = json.loads(read(case, 'case.json'), object_pairs_hook=recipes._pairs)
    cache, case, execution = roots(meta['cache'], case, meta['execution'])
    expected = material(cache, case, execution)
    expected['SHA256SUMS.json'] = encode({name: sha(value) for name, value in expected.items()})
    files = set()
    for count, path in enumerate(case.rglob('*'), 1):
        if count > 256:
            raise recipes.ContractError('Case entry count exceeds bound')
        if path.is_symlink() or (not path.is_dir() and not path.is_file()):
            raise recipes.ContractError('Unsafe case entry')
        if path.is_file():
            files.add(str(path.relative_to(case)))
    if files != set(expected) or any(read(case, name) != value for name, value in expected.items()):
        raise recipes.ContractError('Case differs from independently reconstructed inputs/commands')
    if not started and os.path.lexists(execution):
        raise recipes.ContractError('Execution root exists; use --started for read-only verification')
    return {'valid': True, 'engine_revision': meta['engine_revision'],
            'source_sha256': meta['source_sha256'], 'execution_root_absent': not os.path.lexists(execution),
            'execution': 'not_requested'}


def image_commands(case):
    verify(case, started=True)
    meta = json.loads(read(case, 'case.json'))
    execution = safe(meta['execution'])
    image = read(execution/'build', 'image-id.txt').decode().strip()
    if not re.fullmatch('sha256:[0-9a-f]{64}', image) or image in (GO, RUNTIME, BIRD):
        raise recipes.ContractError('Build did not return a distinct immutable sink image ID')
    return {'image_id': image,
        'inspect': ['docker', '--host', 'unix:///var/run/docker.sock', 'image', 'inspect', image],
        'version': ['timeout', '--signal=TERM', '--kill-after=5', '15', 'docker', '--host', 'unix:///var/run/docker.sock',
            'run', '--rm', '--pull=never', '--network=none', '--read-only', '--cap-drop=ALL',
            '--security-opt=no-new-privileges', '--name', 'bgperf_prefix_probe_' + meta['case_id'],
            '--label', 'org.bgperf2.validation.case=' + meta['case_id'],
            image, '/usr/local/bin/bgperf-sink', '-version']}


def binding_material(case):
    plan = image_commands(case)
    meta = json.loads(read(case, 'case.json'))
    execution = safe(meta['execution'])
    rows = json.loads(read(execution/'build', 'image-inspect.json'), object_pairs_hook=recipes._pairs)
    if not isinstance(rows, list) or len(rows) != 1:
        raise recipes.ContractError('Expected exactly one inspected built image')
    image = rows[0]
    if (image.get('Id') != plan['image_id'] or image.get('Os') != 'linux'
            or (image.get('Config', {}).get('Labels') or {}).get('org.bgperf2.validation.source-sha256') != meta['source_sha256']):
        raise recipes.ContractError('Built image/source readback differs')
    if (image.get('Config', {}).get('Labels') or {}).get('org.bgperf2.validation.case') != meta['case_id']:
        raise recipes.ContractError('Built image is not bound to this case')
    version = read(execution/'build', 'version.txt').decode().strip()
    if version != f'bgperf-sink 0.2.0 (src {meta["source_sha256"][:12]}) gobgp/v4 v4.9.0 go1.25.14':
        raise recipes.ContractError('Built sink version/source/compiler readback differs')
    for name in ('build', 'inspect', 'version'):
        receipt = json.loads(read(execution/'build', name+'-exit.json'), object_pairs_hook=recipes._pairs)
        recipes._same(receipt, {'exit_code': 0}, name+' exit receipt')
    recipe = recipes.export_recipe(ROOT/'examples/recipes/synthetic-ipv4.yaml', 'synthetic-ipv4',
        'f94a3878b2dad49e', engine_revision=meta['engine_revision'],
        roles={'target': {'adapter': 'bird', 'image': BIRD}, 'generator': {'adapter': 'bird', 'image': BIRD},
               'observer': {'adapter': 'sink', 'image': plan['image_id']}}, question=QUESTION)
    from recipe_assertions import default_assertions
    data = {'recipe.json': encode(recipe),
            'assertions.json': encode(default_assertions(recipe, include_prefixes=True)),
            'binding.json': encode({'source_sha256': meta['source_sha256'], 'image_id': plan['image_id'],
        'recipe_sha256': recipes.recipe_sha256(recipe), 'version': version,
        'limits': 'Local readback is not authenticated publisher provenance or binary reproducibility.'})}
    return execution/'bound', data


def bind(case):
    bound, data = binding_material(case)
    bound.mkdir(mode=0o700)
    for name, value in data.items():
        save(bound/name, value)
    return verify_bound(case)


def verify_bound(case):
    bound, data = binding_material(case)
    if set(p.name for p in bound.iterdir()) != set(data) or any(read(bound, name) != value for name, value in data.items()):
        raise recipes.ContractError('Runtime recipe/assertions differ from selected case')
    return {'valid': True, 'recipe_sha256': recipes.recipe_sha256(json.loads(data['recipe.json'])),
            'execution': 'not_requested'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    prep = sub.add_parser('prepare')
    for name in ('cache', 'output', 'execution'):
        prep.add_argument('--'+name, required=True)
    for name in ('verify', 'image-commands', 'bind', 'verify-bound'):
        command = sub.add_parser(name)
        command.add_argument('case')
        if name == 'verify':
            command.add_argument('--started', action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.command == 'prepare':
            value = prepare(args.cache, args.output, args.execution)
        elif args.command == 'verify':
            value = verify(args.case, started=args.started)
        elif args.command == 'image-commands':
            value = image_commands(safe(args.case))
        elif args.command == 'verify-bound':
            value = verify_bound(safe(args.case))
        else:
            value = bind(safe(args.case))
        print(json.dumps(value, indent=2))
        return 0
    except (OSError, ValueError, TypeError, AttributeError, KeyError, zipfile.BadZipFile) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
