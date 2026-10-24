#!/usr/bin/env python3
# Copyright (C) 2026 bgperf2 contributors. Apache-2.0.
"""Exercise a controlled baseline/fix investigation without Docker or a build.

Git identities, images, builds and runtime observations in this smoke are
explicitly simulated. Read-only path/capacity checks still observe the local
filesystem. The output contains portable investigation reports and
partial results for review, never a claim about BIRD behavior or performance.
"""
import argparse
from contextlib import ExitStack, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import socket
import subprocess
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import recipes
import recipe_preflight as preflight
from scripts.recipe_smoke import SimulatedHost, _write

BASELINE_IMAGE = 'sha256:' + '1' * 64
CANDIDATE_IMAGE = 'sha256:' + '4' * 64
TOOLCHAIN_IMAGE = 'sha256:' + '7' * 64
RUNTIME_IMAGE = 'sha256:' + '8' * 64
SOURCE_REVISION = 'a' * 40


def _command(arguments, *, expected=(0,)):
    output = io.StringIO()
    with redirect_stdout(output):
        code = recipes.main(list(map(str, arguments)))
    if code not in expected:
        raise RuntimeError(f'Simulated {arguments[0]} exited {code}; expected {expected}')
    return json.loads(output.getvalue()) if output.getvalue().strip() else None


def _forbidden(*args, **kwargs):
    raise AssertionError('Investigation smoke forbids unmodelled subprocess and network operations')


class FixtureSource:
    """A modeled local Git checkout with a tracked fix and an untracked note."""
    def __init__(self, root):
        self.root = root
        self.calls = []
        self.original = {
            'configure.ac': b'# SIMULATED inert source fixture; never executed\n',
            'Makefile.in': b'# SIMULATED inert make fixture; never executed\n',
            'fixture.c': b'/* SIMULATED baseline: reproduce crash */\n',
        }
        self.blobs = {hashlib.sha1(value).hexdigest(): value for value in self.original.values()}
        root.mkdir()
        for name, value in self.original.items():
            (root / name).write_bytes(value)
        (root / 'fixture.c').write_bytes(b'/* SIMULATED candidate: controlled fix */\n')
        (root / 'local-note.txt').write_text('SIMULATED untracked source provenance fixture.\n')

    def git(self, root, *arguments):
        root = Path(root)
        args = tuple(map(str, arguments))
        self.calls.append({'root': str(root), 'arguments': list(args)})
        if root != self.root.resolve():
            raise AssertionError('Source probe selected an unrelated checkout')
        if args == ('rev-parse', '--show-toplevel'):
            return (str(self.root.resolve()) + '\n').encode()
        if args == ('config', '--name-only', '--list'):
            return b''  # SIMULATED source has no executable Git filters.
        if args == ('ls-files', '-v', '-z'):
            return ''.join('H ' + name + '\0' for name in sorted(self.original)).encode()
        if args in (('rev-parse', '--verify', 'HEAD^{commit}'),
                    ('rev-parse', '--verify', SOURCE_REVISION + '^{commit}')):
            return (SOURCE_REVISION + '\n').encode()
        if args == ('diff', '--binary', '--no-ext-diff', '--no-textconv', SOURCE_REVISION, '--'):
            return (b'diff --git a/fixture.c b/fixture.c\n--- a/fixture.c\n+++ b/fixture.c\n'
                    b'@@ -1 +1 @@\n-/* SIMULATED baseline: reproduce crash */\n'
                    b'+/* SIMULATED candidate: controlled fix */\n')
        if args == ('ls-files', '--others', '--exclude-standard', '-z'):
            return b'local-note.txt\0'
        if args == ('ls-files', '-z'):
            return b'\0'.join(name.encode() for name in sorted(self.original)) + b'\0'
        if args == ('ls-tree', '-rz', '--full-tree', SOURCE_REVISION):
            return b''.join(b'100644 blob ' + hashlib.sha1(value).hexdigest().encode() +
                            b'\t' + name.encode() + b'\0'
                            for name, value in sorted(self.original.items()))
        if len(args) == 3 and args[:2] == ('cat-file', 'blob') and args[2] in self.blobs:
            return self.blobs[args[2]]
        if len(args) == 3 and args[:2] == ('cat-file', '-s') and args[2] in self.blobs:
            return str(len(self.blobs[args[2]])).encode()
        raise AssertionError(f'Unmodelled source Git operation: {args!r}')


class InvestigationHost(SimulatedHost):
    """Allow only maintained read-only probes and one simulated selected build."""
    def __init__(self, document, source):
        super().__init__(document)
        self.source = source
        self.build_calls = []
        self.tag = None
        self.built = False
        self.snapshot = None

    def command(self, argv, *, env=None, timeout=15):
        args = list(map(str, argv))
        docker = ['docker', '--host', 'unix:///var/run/docker.sock', 'image', 'inspect']
        if len(args) == 6 and args[:5] == docker:
            reference = args[-1]
            if reference.startswith('bgperf/bird-local:'):
                self.calls.append(args)
                if self.tag is not None and reference != self.tag:
                    raise AssertionError('Simulated build selected a second image tag')
                self.tag = reference
                if not self.built:
                    raise preflight.CommandError(args, 1, '[]\n',
                        f'Error response from daemon: No such image: {reference}\n')
                return json.dumps([{'Id': CANDIDATE_IMAGE,
                    'Config': {'Labels': {'bgperf2.local_source_sha256': self.snapshot}}}])
            selected = {role['image'] for role in self.document['roles'].values()}
            selected.update((CANDIDATE_IMAGE, TOOLCHAIN_IMAGE, RUNTIME_IMAGE))
            if reference in selected:
                self.calls.append(args)
                return json.dumps([{'Id': reference, 'RepoDigests': [], 'Size': 123,
                                    'Os': 'linux', 'Architecture': 'amd64'}])
        return super().command(args, env=env, timeout=timeout)

    def build(self, argv, *, env, timeout, log_path):
        args = list(map(str, argv))
        prefix = ['docker', '--host', 'unix:///var/run/docker.sock', 'build',
                  '--pull=false', '--network=none', '--rm=true', '--label']
        if args[:8] != prefix or len(args) != 12 or args[9:11] != ['--tag', self.tag]:
            raise AssertionError(f'Unmodelled build operation: {args!r}')
        if not args[8].startswith('bgperf2.local_source_sha256='):
            raise AssertionError('Build omitted source snapshot identity')
        self.snapshot = args[8].split('=', 1)[1]
        self.build_calls.append(args)
        Path(log_path).write_text(
            'SIMULATED source build: no compiler, Docker daemon or network operation ran.\n')
        self.built = True


class InvestigationRuntime:
    """Controlled crash/completion and unavailable-evidence fixtures."""
    def __init__(self, scenario='resolved'):
        self.scenario = scenario
        self.attempts = []

    def execute(self, document, workdir, attempt_id, timeout):
        selected = recipes.read_document(workdir / 'target-selection.json')
        target = recipes.read_document(workdir / 'target.json')
        baseline = target['image'] == BASELINE_IMAGE
        collector_failed = baseline and self.scenario == 'collector-failure'
        status = 'harness_failed' if collector_failed else ('experiment_failed' if baseline else 'completed')
        reason = ('SIMULATED diagnostic collector failure; partial evidence retained.' if collector_failed
                  else 'SIMULATED baseline crash.' if baseline else 'SIMULATED candidate completion.')
        outcome = {'status': status, 'reason': reason, 'simulation': True}
        if not collector_failed:
            outcome['reproduction'] = {
                'outcome': 'reproduced' if baseline else 'not_reproduced',
                'reason': reason, 'evidence': ['work/live-diagnostics.json']}
        self.attempts.append({'id': attempt_id, 'target': target['image'],
                              'roles': selected['roles'], 'scenario': self.scenario,
                              'timeout': timeout, 'status': status})
        missing_memory = self.scenario == 'missing-memory' or collector_failed
        memory = {'units': 'bytes', 'peak_bytes': None if missing_memory else 4096,
                  'ending_bytes': None if missing_memory else 2048,
                  'sampled_peak_bytes': None if missing_memory else 4096,
                  'accounting': 'SIMULATED cgroup-v2 container memory; includes process and cache costs.',
                  'peak_definition': 'SIMULATED lifetime kernel cgroup peak before cleanup.',
                  'ending_definition': 'SIMULATED final pre-cleanup memory.current observation.',
                  'daemon_process_rss_bytes': None,
                  'daemon_process_reason': 'SIMULATED fixture does not measure daemon process RSS.',
                  'reason': 'SIMULATED unavailable cgroup observations.' if missing_memory else None}
        log_text = ('SIMULATED BIRD child exit 139 inside a still-running shell container.\n'
                    if baseline and not collector_failed else reason + '\n')
        log_path = workdir / 'diagnostic-logs/simulated-target.log'
        log_path.parent.mkdir()
        log_path.write_text(log_text)
        container = {'id': 'SIMULATED-target', 'name': attempt_id + '_bird_target',
                     'role': 'target', 'image_id': target['image'],
                     'state': {'Status': 'running', 'Running': True, 'ExitCode': 0,
                               'OOMKilled': False, 'Error': ''},
                     'memory': memory,
                     'log': {'path': 'diagnostic-logs/simulated-target.log',
                             'truncated': False, 'captured_bytes': len(log_text.encode()),
                             'requested_tail_lines': 200}}
        diagnostic = {'schema': 'bgperf2/diagnostics/v1alpha1', 'mode': selected['diagnostics'],
                      'status': 'partial' if collector_failed else 'collected',
                      'containers': [container], 'errors': ['SIMULATED collector failure'] if collector_failed else [],
                      'missing': ['SIMULATED memory unavailable'] if missing_memory else [],
                      'memory': {'target': memory}, 'instrumentation': target['provenance']['instrumentation'],
                      'simulation': True}
        _write(workdir / 'diagnostics.json', diagnostic)
        if not collector_failed:
            _write(workdir / 'live-diagnostics.json', {
                'schema': 'bgperf2/diagnostics/v1alpha1', 'simulation': True,
                'instrumentation': 'SIMULATED fixed BIRD process-list and exit-witness observations.',
                'samples': [{'container_id': 'SIMULATED-target', 'role': 'target',
                             'bird_process_present': True, 'memory_bytes': None if missing_memory else 4096,
                             'monotonic_s': 0, 'errors': []},
                            {'container_id': 'SIMULATED-target', 'role': 'target',
                             'bird_process_present': not baseline,
                             'daemon_exit_code': 139 if baseline else None,
                             'memory_bytes': None if missing_memory else 2048,
                             'monotonic_s': 1, 'errors': []}]})
        _write(workdir / 'stages.json', {'schema': 'bgperf2/stages/v1alpha1',
            'events': [{'stage': stage, 'status': 'completed', 'monotonic_s': index,
                        'reason': 'SIMULATED stage observation'} for index, stage in enumerate(
                       ('setup', 'session_establishment', 'observation', 'collection'))],
            'current_stage': 'collection', 'simulation': True})
        _write(workdir / 'simulated.events.json', {'simulation': True, 'status': status,
            'received': None if baseline else 100})
        _write(workdir / 'simulated.versions.json', {'simulation': True,
            'engine': document['engine'], 'roles': selected['roles']})
        _write(workdir / 'runtime.json', outcome)
        (workdir / 'runtime.log').write_text(reason + '\nNo real daemon ran.\n')
        if not baseline:
            (workdir / 'scenario.yaml').write_text('# SIMULATED configuration, never executed\n')
            (workdir / 'simulated.csv').write_text('simulation,received\ntrue,100\n')
        return outcome


def run_smoke(output):
    """Retain a complete controlled investigation using the maintained CLI."""
    import recipe_run
    import recipe_targets
    output = Path(output)
    if not output.is_absolute():
        raise ValueError('Choose an absolute new output directory')
    canonical = output.resolve()
    if canonical == ROOT or ROOT in canonical.parents:
        raise ValueError('Choose an output directory outside the engine checkout')
    output.mkdir()
    (output / 'SIMULATION.txt').write_text(
        'All Git identities, builds, images, diagnostics and runtime outcomes here are SIMULATED.\n'
        'No actual BIRD bug, fix, performance result or host qualification is represented.\n')
    recipe_path = output / 'recipe.json'
    fixture = recipes.read_document(ROOT / 'examples/recipes/synthetic-ipv4.recipe.json')
    _command(['export', '--batch', ROOT / 'examples/recipes/synthetic-ipv4.yaml',
        '--test', fixture['selection']['test'], '--cell', fixture['selection']['cell_key'],
        '--engine-revision', fixture['engine']['revision'], '--target-image', BASELINE_IMAGE,
        '--generator-image', 'sha256:' + '2' * 64, '--observer-image', 'sha256:' + '3' * 64,
        '--question', 'SIMULATED crash baseline/fix investigation; no actual bug is investigated.',
        '--expected-outcome', 'target_crash', '--output', recipe_path])
    document = recipes.read_document(recipe_path)
    source = FixtureSource(output / 'simulated-source')
    host = InvestigationHost(document, source)
    reports = {}
    runtimes = {}
    with ExitStack() as stack:
        host.patch(stack)
        stack.enter_context(patch.object(recipe_targets, '_git', source.git))
        stack.enter_context(patch.object(recipe_targets, '_run_build', host.build))
        stack.enter_context(patch.object(subprocess, 'Popen', _forbidden))
        stack.enter_context(patch.object(socket.socket, 'connect', _forbidden))
        stack.enter_context(patch.object(socket, 'create_connection', _forbidden))
        baseline_path = output / 'baseline-target.json'
        _command(['target-image', recipe_path, '--image', BASELINE_IMAGE,
            '--label', 'SIMULATED released baseline', '--instrumentation', 'optimized', '--output', baseline_path])
        _command(['target-validate', baseline_path, '--recipe', recipe_path])
        plan_path = output / 'candidate-build-plan.json'
        _command(['target-source-plan', recipe_path, '--source', source.root,
            '--revision', SOURCE_REVISION, '--toolchain-image', TOOLCHAIN_IMAGE,
            '--runtime-image', RUNTIME_IMAGE, '--instrumentation', 'debug',
            '--cflags=-O0 -g', '--include-dirty', '--output', plan_path])
        _command(['target-build', plan_path, '--output-dir', output / 'simulated-build'])
        candidate_path = output / 'simulated-build/target.json'
        _command(['target-validate', candidate_path, '--recipe', recipe_path])
        direct = InvestigationRuntime()
        with patch.object(recipe_run, 'SubprocessBackend', lambda **kwargs: direct):
            _command(['run', recipe_path, '--target', candidate_path,
                      '--workdir', output / 'direct-override/work',
                      '--results-dir', output / 'direct-override/results', '--timeout', '10'])
        _command(['result-verify', output / 'direct-override/results/result.json'])
        for scenario in ('resolved', 'collector-failure', 'missing-memory'):
            runtime = InvestigationRuntime(scenario)
            runtimes[scenario] = runtime
            case = output / scenario
            with patch.object(recipe_run, 'SubprocessBackend', lambda **kwargs: runtime):
                reports[scenario] = _command(['investigate', recipe_path,
                    '--baseline-target', baseline_path, '--candidate-target', candidate_path,
                    '--workdir', case / 'work', '--results-dir', case / 'results', '--timeout', '10'],
                    expected=(0, 3))
            report_path = case / 'results/report/investigation.json'
            _command(['investigation-verify', report_path])
            report_args = ['investigation-report', '--baseline', case / 'results/baseline/result.json',
                           '--output-dir', case / 'report-only']
            if (case / 'results/candidate/result.json').is_file():
                report_args += ['--candidate', case / 'results/candidate/result.json']
            _command(report_args)
            _command(['investigation-verify', case / 'report-only/investigation.json'])
    summary = {'simulation': True, 'status': 'passed',
        'scope': 'Controlled fixtures only; no download, build, benchmark, daemon or host qualification.',
        'operations': ['export', 'target-image', 'target-validate', 'target-source-plan', 'target-build',
                       'run', 'result-verify', 'investigate', 'investigation-report', 'investigation-verify'],
        'recipe_sha256': recipes.recipe_sha256(document),
        'report': str(output / 'resolved/results/report/investigation.json'),
        'cases': {name: {'report': str(output / name / 'results/report/investigation.json'),
                        'attempts': runtime.attempts} for name, runtime in runtimes.items()},
        'direct_override': {'result': str(output / 'direct-override/results/result.json'),
                            'attempts': direct.attempts},
        'probe_commands': host.calls, 'build_commands': host.build_calls,
        'source_git_commands': source.calls}
    _write(output / 'smoke.json', summary)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    args = parser.parse_args(argv)
    try:
        summary = run_smoke(args.output)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f'investigation smoke: {exc}', file=sys.stderr)
        return 2
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
