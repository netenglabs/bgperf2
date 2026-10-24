#!/usr/bin/env python3
# Copyright (C) 2026 bgperf2 contributors.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy at http://www.apache.org/licenses/LICENSE-2.0

"""Exercise the public recipe workflow with simulated prerequisites and runtime.

No Docker daemon, image, network, private checkout or measurement is required.
The new output directory is retained for inspecting the simulated return package.
This is a developer smoke check, never runtime or hardware qualification.
"""

import argparse
from contextlib import ExitStack, redirect_stdout
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import recipes
import recipe_preflight as preflight


def _command(arguments):
    """Call the maintained CLI parser while retaining its machine-readable output."""
    stream = io.StringIO()
    with redirect_stdout(stream):
        code = recipes.main(arguments)
    if code:
        raise RuntimeError(f'Recipe smoke command failed ({code}): {arguments[0]}')
    return json.loads(stream.getvalue()) if stream.getvalue().strip() else None


class SimulatedHost:
    """Exact command allowlist: every unmodelled operation is an error."""

    def __init__(self, document):
        self.document = document
        self.calls = []

    def command(self, argv, *, env=None, timeout=15):
        argv = list(map(str, argv))
        self.calls.append(argv)
        git = ['git', '-c', 'core.fsmonitor=false', '-c', 'core.untrackedCache=false',
               '-C', str(preflight.ROOT)]
        if argv == [*git, 'rev-parse', '--verify', 'HEAD^{commit}']:
            return self.document['engine']['revision'] + '\n'
        if argv == [*git, 'status', '--porcelain', '--untracked-files=all',
                    '--ignore-submodules=none']:
            return ''
        python = str(preflight.ROOT / 'venv/bin/python')
        if argv in ([python, '-I', str(preflight.ROOT / 'scripts/bootstrap.py'), '--check'],
                    [python, '-I', str(preflight.ROOT / 'scripts/quality_gate.py'), '--guard-only']):
            return 'SIMULATED locked environment and idle guard\n'
        docker = ['docker', '--host', 'unix:///var/run/docker.sock', 'image', 'inspect']
        if len(argv) == 6 and argv[:5] == docker:
            selected = {role['image'] for role in self.document['roles'].values()}
            if argv[-1] in selected:
                return json.dumps([{'Id': argv[-1], 'RepoDigests': [], 'Size': 123,
                                    'Os': 'linux', 'Architecture': 'amd64'}])
        raise AssertionError(f'Smoke forbids unmodelled command: {argv!r}')

    def patch(self, stack):
        import recipe_diagnostics
        stack.enter_context(patch.object(recipe_diagnostics, 'host_snapshot', lambda: {
            'schema': 'bgperf2/host/v1alpha1', 'hostname': 'SIMULATED host',
            'kernel_release': 'SIMULATED kernel', 'architecture': 'SIMULATED architecture',
            'boot_id': 'SIMULATED same boot', 'unavailable': {},
            'scope': 'SIMULATED host identity; no host qualification.'}))
        stack.enter_context(patch.object(preflight, 'run_command', self.command))
        stack.enter_context(patch.object(preflight, 'sys', SimpleNamespace(version_info=(3, 14, 0))))
        stack.enter_context(patch.object(preflight.platform, 'system', lambda: 'Linux'))
        stack.enter_context(patch.object(preflight.shutil, 'which', lambda tool: '/simulated/' + tool))
        stack.enter_context(patch.dict('os.environ', {'DOCKER_HOST': 'unix:///var/run/docker.sock'}))
        original = Path.is_file
        stack.enter_context(patch.object(Path, 'is_file', lambda path: True
            if path == preflight.ROOT / 'venv/bin/python' else original(path)))


def _write(path, document):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(document, stream, indent=2, sort_keys=True)
        stream.write('\n')


class SimulatedRuntime:
    """Write conspicuously simulated evidence for exactly the selected roles."""

    def __init__(self):
        self.attempts = []

    def execute(self, document, workdir, attempt_id, timeout):
        self.attempts.append({'id': attempt_id, 'roles': document['roles'],
                              'timeout': timeout})
        # This intentionally contains no timings or invented performance numbers.
        _write(workdir / 'runtime.json', {
            'simulation': True, 'status': 'completed',
            'reason': 'SIMULATED engine completion; no experiment ran.',
            'roles': document['roles']})
        _write(workdir / 'simulated.events.json', {
            'simulation': True, 'completion': 'SIMULATED', 'samples': []})
        _write(workdir / 'simulated.provenance.json', {
            'simulation': True, 'engine': document['engine'], 'roles': document['roles']})
        (workdir / 'scenario.yaml').write_text(
            '# SIMULATED configuration fixture; never executed\n', encoding='utf-8')
        (workdir / 'simulated.csv').write_text(
            'simulation\ntrue\n', encoding='utf-8')
        (workdir / 'runtime.log').write_text(
            'SIMULATED runtime: no Docker, network, build or benchmark ran.\n', encoding='utf-8')
        return {'status': 'completed', 'reason': 'SIMULATED completion; no runtime qualification.'}


def run_smoke(output):
    """Run the maintained workflow under bounded, explicit simulated dependencies."""
    import recipe_run
    import socket
    import subprocess

    output = Path(output)
    if not output.is_absolute():
        raise ValueError('Choose an absolute new output directory outside the engine checkout')
    canonical = output.resolve()
    if canonical == ROOT or ROOT in canonical.parents:
        raise ValueError('Choose an output directory outside the engine checkout')
    output.mkdir()  # Exclusive: retain earlier evidence and never overwrite.
    recipe_path = output / 'recipe.json'
    fixture = recipes.read_document(ROOT / 'examples/recipes/synthetic-ipv4.recipe.json')
    _command(['export', '--batch', str(ROOT / 'examples/recipes/synthetic-ipv4.yaml'),
              '--test', fixture['selection']['test'], '--cell', fixture['selection']['cell_key'],
              '--engine-revision', fixture['engine']['revision'],
              '--target-image', 'sha256:' + '1' * 64,
              '--generator-image', 'sha256:' + '2' * 64,
              '--observer-image', 'sha256:' + '3' * 64,
              '--question', 'SIMULATED newcomer workflow smoke; no experiment is executed.',
              '--output', str(recipe_path)])
    document = recipes.read_document(recipe_path)
    reports = {}
    for operation in ('validate', 'inspect', 'plan'):
        reports[operation] = _command([operation, str(recipe_path)])
        _write(output / (operation + '.json'), reports[operation])
    host, backend = SimulatedHost(document), SimulatedRuntime()

    def forbidden(*args, **kwargs):
        raise AssertionError('Smoke forbids real subprocess and network operations')

    with ExitStack() as stack:
        host.patch(stack)
        stack.enter_context(patch.object(subprocess, 'Popen', forbidden))
        stack.enter_context(patch.object(socket.socket, 'connect', forbidden))
        stack.enter_context(patch.object(socket, 'create_connection', forbidden))
        reports['check'] = _command(['check', str(recipe_path),
            '--workdir', str(output / 'work'), '--results-dir', str(output / 'results')])
        _write(output / 'check.json', reports['check'])
        reports['prepare'] = _command(['prepare', str(recipe_path)])
        _write(output / 'prepare.json', reports['prepare'])
        stack.enter_context(patch.object(recipe_run, 'SubprocessBackend', lambda **kwargs: backend))
        manifest = _command(['run', str(recipe_path), '--workdir', str(output / 'work'),
            '--results-dir', str(output / 'results'), '--timeout', '10'])
        if manifest['status'] != 'completed':
            raise RuntimeError('Simulated recipe did not complete: ' + repr(manifest))
        reports['result-validate'] = _command(
            ['result-validate', str(output / 'results/result.json')])
        reports['result-verify'] = _command(
            ['result-verify', str(output / 'results/result.json')])
        _write(output / 'result-verify.json', reports['result-verify'])
    summary = {
        'simulation': True,
        'status': 'passed',
        'scope': 'Fake prerequisites and fake runtime only; no download, build, benchmark or host qualification.',
        'operations': ['export', 'validate', 'inspect', 'plan', 'check', 'prepare',
                       'run', 'result-validate', 'result-verify'],
        'recipe_sha256': recipes.recipe_sha256(document),
        'result': str(output / 'results/result.json'),
        'probe_commands': host.calls,
        'attempts': backend.attempts,
    }
    _write(output / 'smoke.json', summary)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True,
                        help='absolute new output directory outside the engine checkout')
    args = parser.parse_args(argv)
    try:
        report = run_smoke(args.output)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f'recipe smoke: {exc}', file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
