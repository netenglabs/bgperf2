#!/usr/bin/env python3
# Copyright (C) 2026 bgperf2 contributors. Apache-2.0.
"""Retain controlled comparison reports without Docker, builds or measurements.

All identities, observations and differences are SIMULATED. This walkthrough
uses the public CLI and real local packaging/verification with exact fake
prerequisite and runtime responses. It establishes no performance policy,
daemon behavior, adapter qualification or host qualification.
"""
import argparse
from contextlib import ExitStack
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
from scripts.investigation_smoke import _command
from scripts.recipe_smoke import SimulatedHost, _write

BASELINE_IMAGE = 'sha256:' + '1' * 64
CANDIDATE_IMAGE = 'sha256:' + '4' * 64
CASES = ('known-difference', 'noise', 'confounded', 'stopped', 'missing-measurements')


def _forbidden(*args, **kwargs):
    raise AssertionError('Comparison smoke forbids unmodelled subprocess and network operations')


class ComparisonHost(SimulatedHost):
    """Permit only the existing read-only probes and two selected image IDs."""

    def command(self, argv, *, env=None, timeout=15):
        args = list(map(str, argv))
        if args == ['docker', '--host', 'unix:///var/run/docker.sock',
                    'image', 'inspect', CANDIDATE_IMAGE]:
            self.calls.append(args)
            return json.dumps([{'Id': CANDIDATE_IMAGE, 'RepoDigests': [], 'Size': 123,
                                'Os': 'linux', 'Architecture': 'amd64'}])
        return super().command(args, env=env, timeout=timeout)

    def patch(self, stack):
        super().patch(stack)
        import recipe_diagnostics
        stack.enter_context(patch.object(recipe_diagnostics, 'host_snapshot', lambda: {
            'schema': 'bgperf2/host/v1alpha1', 'hostname': 'SIMULATED host',
            'kernel_release': 'SIMULATED kernel', 'architecture': 'SIMULATED architecture',
            'boot_id': 'SIMULATED same boot', 'cpu_model': 'SIMULATED processor',
            'cpu_count': 4, 'cpu_affinity': [0, 1, 2, 3], 'unavailable': {},
            'scope': 'SIMULATED identity/capacity only; no hardware qualification.'}))


class ComparisonRuntime:
    """Actual-shaped lifecycle/package witnesses with controlled numeric inputs."""

    def __init__(self, scenario):
        if scenario not in CASES:
            raise ValueError('Unknown simulated comparison case')
        self.scenario = scenario
        self.attempts = []

    def execute(self, document, workdir, attempt_id, timeout):
        from recipe_diagnostics import memory_record
        selected = recipes.read_document(workdir / 'target-selection.json')
        baseline = selected['roles']['target']['image'] == BASELINE_IMAGE
        role = 'baseline' if baseline else 'candidate'
        pair = 1 + sum(attempt['role'] == role for attempt in self.attempts)
        stopped = self.scenario == 'stopped' and not baseline
        missing = self.scenario == 'missing-measurements' and baseline and pair == 2
        status = 'harness_failed' if stopped else 'completed'
        reason = ('SIMULATED harness collection failure; later attempts must not run.' if stopped
                  else 'SIMULATED completion; no benchmark or daemon ran.')
        if self.scenario == 'noise':
            elapsed = ([9, 12, 10] if baseline else [10, 9, 12])[pair - 1]
        else:
            elapsed = (10 if baseline else 15) + pair - 1
        cpu = (10 if baseline else 20) + pair - 1
        memory_bytes = (1 if baseline else 2) * 1024 ** 3 + 128 * 1024 ** 2 * (pair - 1)
        if self.scenario == 'noise':
            cpu, memory_bytes = elapsed, elapsed * 512 * 1024 ** 2
        self.attempts.append({'id': attempt_id, 'role': role, 'pair': pair,
                              'status': status, 'timeout': timeout,
                              'simulation': True, 'elapsed_seconds': None if missing else elapsed})
        outcome = {'status': status, 'reason': reason, 'simulation': True}
        row = {'elapsed (s)': elapsed, 'total time': elapsed + 5, 'max cpu %': cpu,
               'max mem (GB)': memory_bytes / 1024 ** 3,
               'max foreign cpu %': 0, 'min idle%': 90, 'min free mem (GB)': 8,
               'required': 100, 'received': 100, 'failed': ''}
        if not missing:
            outcome['row'] = row
            (workdir / 'stats.csv').write_text(
                ','.join(row) + '\n' + ','.join(map(str, row.values())) + '\n')
        _write(workdir / 'runtime.json', outcome)
        _write(workdir / 'diagnostic-options.json', {'mode': selected['diagnostics']})
        _write(workdir / 'execution-budget.json', {
            'schema': 'bgperf2/execution-budget/v1alpha1', 'scope': 'worker',
            'timeout_seconds': timeout, 'elapsed_seconds': elapsed + 5,
            'completed_within_budget': True, 'simulation': True})
        (workdir / 'runtime.log').write_text(reason + '\nAll measurements here are SIMULATED.\n')
        (workdir / 'scenario.yaml').write_text('# SIMULATED configuration, never executed.\n')
        memory = memory_record(
            {} if missing else {'peak_bytes': memory_bytes, 'ending_bytes': memory_bytes // 2},
            reason='SIMULATED unavailable memory.' if missing else 'SIMULATED cgroup values.',
            sampled_peak_bytes=None if missing else memory_bytes)
        containers = [{'id': 'SIMULATED-' + name, 'name': attempt_id + '_' + name,
                       'role': name, 'image_id': identity['image'],
                       'state': {'Running': True, 'Status': 'running', 'ExitCode': 0,
                                 'OOMKilled': False, 'Error': ''}}
                      for name, identity in selected['roles'].items()]
        diagnostic = {
            'schema': 'bgperf2/diagnostics/v1alpha1', 'mode': selected['diagnostics'],
            'status': 'partial' if stopped else 'collected', 'containers': containers,
            'errors': [reason] if stopped else [], 'missing': [memory['reason']] if missing else [],
            'memory': {'target': memory}, 'simulation': True}
        if selected['diagnostics'] == 'none':
            # Match the actual disabled collector: legacy stats remain available,
            # but final container states and cgroup measurements do not exist.
            diagnostic.update(status='disabled', containers=[],
                              missing=['Optional runtime diagnostics were explicitly disabled.'],
                              memory={'target': memory_record(reason='No target memory observation.')})
        _write(workdir / 'diagnostics.json', diagnostic)
        total = document['resolved']['neighbors'] * document['resolved']['prefixes_per_peer']
        sessions = document['resolved']['neighbors']
        counters = {'sessions': sessions, 'sessions_measured': sessions,
                    'expected_prefixes': total, 'offered_prefixes': total}
        producer = attempt_id + '_bgperf_bird_tester0'
        def event(kind, time, source, phase, counts=None):
            return {'event': kind, 'monotonic_s': time, 'producer': source,
                    'phase': phase, 'counters': counts or {}, 'details': {}}
        _write(workdir / 'raw-events.json', {'simulation': True, 'events': [
            event('bench_clock_started', 1, 'controller', 'setup'),
            event('tester_session_ready', 2, producer, 'setup', counters),
            event('tester_first_update', 2, producer, 'injection'),
            event('tester_complete', 3, producer, 'injection', counters),
            event('convergence_confirmed', elapsed + 1, attempt_id + '_monitor', 'assurance',
                  {'accepted_prefixes': total})]})
        return outcome


def _run_smoke(output):
    """Create evidence while the outer guard blocks all real subprocess/network work."""
    import recipe_run
    output = Path(output)
    if not output.is_absolute():
        raise ValueError('Choose an absolute new output directory')
    canonical = output.resolve()
    if canonical == ROOT or ROOT in canonical.parents:
        raise ValueError('Choose an output directory outside the engine checkout')
    output.mkdir()
    (output / 'SIMULATION.txt').write_text(
        'All identities, numeric values, outcomes and comparisons are SIMULATED.\n'
        'No Docker, network, download, build, daemon or benchmark ran.\n'
        'Known differences and noise are controlled fixtures, never a regression verdict.\n')
    recipe_path = output / 'recipe.json'
    fixture = recipes.read_document(ROOT / 'examples/recipes/synthetic-ipv4.recipe.json')
    _command(['export', '--batch', ROOT / 'examples/recipes/synthetic-ipv4.yaml',
              '--test', fixture['selection']['test'], '--cell', fixture['selection']['cell_key'],
              '--engine-revision', fixture['engine']['revision'], '--target-image', BASELINE_IMAGE,
              '--generator-image', 'sha256:' + '2' * 64, '--observer-image', 'sha256:' + '3' * 64,
              '--question', 'SIMULATED repeated comparison; no real performance verdict.',
              '--output', recipe_path])
    document = recipes.read_document(recipe_path)
    host = ComparisonHost(document)
    cases = {}
    with ExitStack() as stack:
        host.patch(stack)
        baseline = output / 'baseline-target.json'
        candidate = output / 'candidate-target.json'
        debug = output / 'debug-candidate-target.json'
        for path, image, label, instrumentation in (
                (baseline, BASELINE_IMAGE, 'baseline', 'optimized'),
                (candidate, CANDIDATE_IMAGE, 'candidate', 'optimized'),
                (debug, CANDIDATE_IMAGE, 'debug candidate confounder', 'debug')):
            _command(['target-image', recipe_path, '--image', image,
                      '--label', 'SIMULATED ' + label, '--instrumentation', instrumentation,
                      '--output', path])
        assertions = output / 'assertions.json'
        _command(['assertions-export', recipe_path, '--output', assertions])
        for scenario in CASES:
            case = output / scenario
            case.mkdir()
            plan = case / 'plan.json'
            spec = assertions
            if scenario in ('known-difference', 'noise'):
                subset = recipes.read_document(assertions)
                subset['assertions'] = [item for item in subset['assertions']
                                        if item['capability'] != 'observed_role_health']
                spec = case / 'assertions.json'
                _write(spec, subset)
            arguments = ['comparison-plan', recipe_path, '--baseline-target', baseline,
                         '--candidate-target', debug if scenario == 'confounded' else candidate,
                         '--repetitions', 3, '--order', 'shuffle' if scenario == 'noise' else 'alternating',
                         '--timeout', 120, '--diagnostics', 'none' if scenario in ('known-difference', 'noise') else 'basic',
                         '--assertions', spec, '--output', plan]
            if scenario == 'noise':
                arguments += ['--seed', 1729]
            _command(arguments)
            runtime = ComparisonRuntime(scenario)
            with patch.object(recipe_run, 'SubprocessBackend', lambda **kwargs: runtime):
                _command(['compare', plan, '--workdir', case / 'work',
                          '--results-dir', case / 'results'], expected=(0, 3))
            report_path = case / 'results/report/comparison.json'
            _command(['comparison-verify', report_path])
            ledger = case / 'results/attempts.json'
            _command(['comparison-report', plan, '--attempts', ledger,
                      '--output-dir', case / 'report-only'])
            _command(['comparison-verify', case / 'report-only/comparison.json'])
            # Use the first frozen attempt, including when shuffle starts with the candidate.
            first_result = case / 'results' / recipes.read_document(plan)['sequence'][0]['id'] / 'result.json'
            checked = _command(['assertions-check', spec, '--result', first_result])
            cases[scenario] = {'report': str(report_path), 'report_only': str(case / 'report-only/comparison.json'),
                               'plan': str(plan), 'ledger': str(ledger), 'attempts': runtime.attempts,
                               'assertions': checked,
                               'assertion_scope': ('Session, injection, count and completion within the worker budget; '
                                                   'final health snapshots are excluded because diagnostics are disabled.'
                                                   if scenario in ('known-difference', 'noise') else
                                                   'Default assertions including final pre-cleanup container health.')}
    summary = {'simulation': True, 'status': 'passed',
               'scope': 'Controlled fixtures only; no runtime, performance policy or host qualification.',
               'operations': ['export', 'target-image', 'assertions-export', 'assertions-check',
                              'comparison-plan', 'compare', 'comparison-report', 'comparison-verify'],
               'recipe_sha256': recipes.recipe_sha256(document),
               'report': cases['known-difference']['report'], 'cases': cases,
               'probe_commands': host.calls}
    _write(output / 'smoke.json', summary)
    return summary


def run_smoke(output):
    """Create new, inspectable simulated evidence through maintained commands."""
    with ExitStack() as stack:
        stack.enter_context(patch.object(subprocess, 'Popen', _forbidden))
        stack.enter_context(patch.object(socket.socket, 'connect', _forbidden))
        stack.enter_context(patch.object(socket, 'create_connection', _forbidden))
        return _run_smoke(output)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, help='absolute new directory outside the engine checkout')
    args = parser.parse_args(argv)
    try:
        summary = run_smoke(args.output)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f'comparison smoke: {exc}', file=sys.stderr)
        return 2
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
