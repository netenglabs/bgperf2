#!/usr/bin/env python3
# Copyright (C) 2026 bgperf2 contributors. Apache-2.0.
"""Public supplied-image FRR workflow with strictly SIMULATED workers.

Real local contracts and packaging; no real daemon, source, image acquisition,
subprocess or network. Modeled mismatches establish no FRR defect or fix.
"""
import argparse
from contextlib import ExitStack
import ipaddress
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import minimization_cli
import comparison_session
import recipe_bisection
import recipe_prefixes as prefixes
import recipe_run
import recipes
from scripts.comparison_smoke import BASELINE_IMAGE, CANDIDATE_IMAGE, ComparisonHost, ComparisonRuntime
from scripts.maintainer_smoke import Commands, _forbidden
from scripts.recipe_smoke import SimulatedOS, _write


class FRRRuntime:
    """Reuse maintained witnesses, retaining actual selected FRR role payloads."""
    def __init__(self, *, mismatch=True):
        self.runtime = ComparisonRuntime('known-difference')
        self.attempts = []
        self.mismatch = mismatch
        self.failure_images = {BASELINE_IMAGE}

    def execute(self, document, workdir, attempt_id, timeout):
        selection = recipes.read_document(workdir / 'target-selection.json')
        assert document['resolved']['target']['name'] == 'frr_c'
        assert selection['roles']['target']['adapter'] == 'frr_c'
        outcome = self.runtime.execute(document, workdir, attempt_id, timeout)
        outcome['cleanup_errors'] = []
        (workdir / 'runtime.json').write_text(json.dumps(outcome))
        budget = recipes.read_document(workdir / 'execution-budget.json')
        budget.update(started_monotonic_s=1, ended_monotonic_s=1 + budget['elapsed_seconds'])
        (workdir / 'execution-budget.json').write_text(json.dumps(budget))
        total = prefixes.expected_count(document)
        wrong = self.mismatch and selection['roles']['target']['image'] in self.failure_images and total >= 2
        events = recipes.read_document(workdir / 'raw-events.json')
        events['events'][-1]['counters']['accepted_prefixes'] = total - int(wrong)
        (workdir / 'raw-events.json').write_text(json.dumps(events))
        selected = (workdir / 'observer-prefix-selection.json').exists()
        if selected:
            first = int(ipaddress.IPv4Address('100.0.0.0'))
            values = [str(ipaddress.IPv4Address(first + n)) + '/32' for n in range(total)]
            if wrong:
                values[0] = '192.0.2.1/32'
            requested = int((budget['elapsed_seconds'] - 3) * 1_000_000_000)
            _write(workdir / 'observer-prefixes.json', {
                'schema': prefixes.CAPTURE_SCHEMA, 'recipe_sha256': recipes.recipe_sha256(document),
                'status': 'collected', 'phase': 'post_measurement', 'reason': None,
                'requested_ns': requested, 'completed_ns': requested + 200_000_000,
                'snapshot': {'schema': prefixes.SCHEMA, 'status': 'complete', 'reason': None,
                    'monotonic_ns': requested + 100_000_000, 'connection_id': 1, 'updates': 2,
                    'accepted_count': total, 'prefixes': values}})
        self.attempts.append({'id': attempt_id, 'roles': selection['roles'],
            'target': document['resolved']['target'], 'routes': total,
            'selected_failure': wrong, 'capture_selected': selected, 'simulation': True})
        return outcome


def _run_smoke(output):
    output = recipe_bisection.safe(output)
    if output == ROOT or ROOT in output.parents:
        raise ValueError('Choose a fresh output outside the engine checkout')
    output.mkdir(mode=0o700)
    commands = Commands(output / 'commands')
    batch = output / 'batch.yaml'
    batch.write_text('tests:\n  - name: supplied-frr\n    monitor: sink\n'
        '    neighbors: [1]\n    prefixes: [8]\n    filter_test: [None]\n'
        '    targets:\n      - name: frr_c\n')
    test = {'name': 'supplied-frr', 'neighbors': [1], 'prefixes': [8], 'filter_test': ['None']}
    cells = recipes.construct_batch_cells(test, [{'name': 'frr_c'}], repetitions=1,
        prefix_resolver=recipes.resolve_prefix_scope, path_diversity=1, receivers=0,
        churn_prefixes=0, churn_bursts=1, policy_reload_blocks=0, pin=None, monitor='sink')
    key = recipes.batch_cell_key(recipes.batch_cell_id('supplied-frr', cells[0]))
    recipe_path = output / 'recipe.json'
    revision = recipes.read_document(ROOT / 'examples/recipes/synthetic-ipv4.recipe.json')['engine']['revision']
    commands.call(recipes, ['export', '--batch', batch, '--test', 'supplied-frr', '--cell', key,
        '--engine-revision', revision, '--target-image', BASELINE_IMAGE,
        '--generator-image', 'sha256:' + '2' * 64, '--observer-image', 'sha256:' + '3' * 64,
        '--question', 'SIMULATED supplied FRR images; no real FRR fault or source change.',
        '--output', recipe_path])
    recipe = recipes.read_document(recipe_path)
    host, runtime = ComparisonHost(recipe), FRRRuntime()
    verification = {}
    with ExitStack() as stack:
        host.patch(stack)
        stack.enter_context(patch.dict('os.environ', {
            'BGPERF_ARTIFACT_STORE': str(output / 'artifact-store')}))
        stack.enter_context(patch.object(recipe_run, 'os', SimulatedOS(output / 'modeled-host.lock')))
        stack.enter_context(patch.object(recipe_run, 'SubprocessBackend', lambda **kwargs: runtime))
        for operation in ('validate', 'inspect', 'plan'):
            _write(output / (operation + '.json'), commands.call(recipes, [operation, recipe_path]))
        baseline, candidate = output / 'baseline.json', output / 'candidate.json'
        for path, image in ((baseline, BASELINE_IMAGE), (candidate, CANDIDATE_IMAGE)):
            commands.call(recipes, ['target-image', recipe_path, '--image', image,
                '--label', 'SIMULATED supplied FRR image', '--output', path])
        commands.call(recipes, ['check', recipe_path, '--target', baseline,
            '--workdir', output / 'check-work', '--results-dir', output / 'check-results'])
        commands.call(recipes, ['run', recipe_path, '--target', baseline,
            '--workdir', output / 'reproduction-work', '--results-dir', output / 'reproduction',
            '--timeout', 120, '--observer-prefixes'])
        spec = output / 'assertions.json'
        capabilities = ('session_establishment', 'injection_completion', 'observer_route_count',
                        'experiment_completion', 'observed_role_health', 'observer_prefix_identity')
        args = ['assertions-export', recipe_path, '--output', spec]
        for capability in capabilities:
            args += ['--capability', capability]
        commands.call(recipes, args)
        assertions = commands.call(recipes, ['assertions-check', spec,
            '--result', output / 'reproduction/result.json'], expected=4)
        commands.call(recipes, ['investigate', recipe_path, '--baseline-target', baseline,
            '--candidate-target', candidate, '--workdir', output / 'investigation-work',
            '--results-dir', output / 'investigation', '--timeout', 120, '--observer-prefixes'])
        report = output / 'investigation/report/investigation.json'
        commands.call(recipes, ['investigation-status', report])
        commands.call(recipes, ['investigation-check', report], expected=4)
        commands.call(recipes, ['investigation-check', report, '--side', 'candidate'])
        commands.call(recipes, ['investigation-rebuild', report, '--output-dir', output / 'investigation-rebuilt'])
        commands.call(recipes, ['investigation-report', '--baseline', output / 'reproduction/result.json',
            '--observer-prefixes', '--output-dir', output / 'incomplete'])
        commands.call(recipes, ['investigation-check', output / 'incomplete/investigation.json',
            '--side', 'candidate'], expected=5)
        plan = output / 'comparison-plan.json'
        commands.call(recipes, ['comparison-plan', recipe_path, '--baseline-target', baseline,
            '--candidate-target', candidate, '--repetitions', 2, '--order', 'alternating',
            '--timeout', 120, '--diagnostics', 'basic', '--assertions', spec,
            '--observer-prefixes', '--output', plan])
        commands.call(recipes, ['compare', plan, '--workdir', output / 'comparison-work',
            '--results-dir', output / 'comparison'])
        commands.call(recipes, ['comparison-report', plan, '--attempts', output / 'comparison/attempts.json',
            '--output-dir', output / 'comparison-rebuilt'])
        # Separate passing fixtures exercise the generic staged controller's
        # assessment and review gates. They make no claim about either image.
        staged_plan = output / 'staged-plan.json'
        commands.call(recipes, ['comparison-plan', recipe_path, '--baseline-target', baseline,
            '--candidate-target', candidate, '--repetitions', 1, '--order', 'alternating',
            '--timeout', 120, '--diagnostics', 'basic', '--assertions', spec,
            '--observer-prefixes', '--output', staged_plan])
        staged = output / 'staged'
        staged_runtime = FRRRuntime(mismatch=False)

        def staged_execute(plan, entry, *, workdir, results_dir, session, pressure, sample=None):
            if pressure is not None:
                raise AssertionError('This modeled staged case selects no pressure screen')
            commands.call(recipes, ['run', session / 'recipe.json', '--target',
                session / ('target-' + entry['role'] + '.json'), '--workdir', workdir,
                '--results-dir', results_dir, '--timeout', plan['timeout'],
                '--diagnostics', plan['diagnostics'], '--observer-prefixes'])
            return {'exit_code': 0}

        with patch.object(recipe_run, 'SubprocessBackend', lambda **kwargs: staged_runtime), \
                patch.object(comparison_session, '_execute', staged_execute):
            before = len(staged_runtime.attempts)
            prepared = commands.call(recipes, ['comparison-start', staged_plan,
                '--workdir', output / 'staged-work', '--results-dir', staged])
            assert prepared['status'] == 'ready' and len(staged_runtime.attempts) == before
            first = commands.call(recipes, ['comparison-step', staged])
            assert first['status'] == 'first_review' and len(staged_runtime.attempts) == 1
            commands.call(recipes, ['comparison-step', staged], expected=2)
            assert len(staged_runtime.attempts) == 1
            for phase in ('first', 'final'):
                evidence = output / (phase + '-staged-review.txt')
                evidence.write_text('SIMULATED review attestation: original package, six assertions, '
                    'budget and explicit empty cleanup errors inspected. No independent human review claimed.\n')
                review = commands.call(recipes, ['comparison-review', staged,
                    '--reviewer', 'SIMULATED reviewer', '--evidence', evidence, '--decision', 'accepted'])
                if phase == 'first':
                    assert review['status'] == 'ready'
                    final = commands.call(recipes, ['comparison-step', staged])
                    assert final['status'] == 'final_review' and len(staged_runtime.attempts) == 2
                    commands.call(recipes, ['comparison-step', staged], expected=2)
                    assert len(staged_runtime.attempts) == 2
                else:
                    assert review['status'] == 'complete'
            commands.call(recipes, ['comparison-step', staged], expected=2)
            assert len(staged_runtime.attempts) == 2
        staged_receipt, _ = comparison_session.validate_review(staged / 'reviews/final.json', final=True)
        commands.call(recipes, ['comparison-report', staged_plan, '--attempts', staged / 'attempts.json',
            '--output-dir', output / 'staged-rebuilt'])
        minim = output / 'minimization-plan.json'
        commands.call(minimization_cli, ['plan', recipe_path, '--assertion', 'observer.count',
            '--max-trials', 16, '-o', minim])
        session = output / 'minimization'
        commands.call(minimization_cli, ['init', minim, '--workdir', output / 'minimization-work',
            '--results-dir', session])
        before = len(runtime.attempts)
        for operation in ('status', 'next', 'step'):
            commands.call(minimization_cli, [operation, session])
        assert len(runtime.attempts) == before
        for _ in range(17):
            status = commands.call(minimization_cli, ['status', session])
            if status['next'] is None:
                break
            commands.call(minimization_cli, ['step', session, '--execute'])
        else:
            raise RuntimeError('Modeled minimization exceeded its bounded budget')
        if not status['confirmed'] or status['best']['routes'] != 2:
            raise RuntimeError('Modeled selected failure did not confirm at two routes')
        commands.call(minimization_cli, ['report', session, '--output-dir', output / 'minimization-report'])
        commands.call(minimization_cli, ['rebuild', output / 'minimization-report/minimization.json',
            '--output-dir', output / 'minimization-rebuilt'])
        before = len(runtime.attempts)
        portable = output / 'return'
        portable.mkdir()
        for source, name, module, operation, filename in (
            ('reproduction', 'reproduction', recipes, 'result-verify', 'result.json'),
            ('investigation/report', 'investigation', recipes, 'investigation-verify', 'investigation.json'),
            ('incomplete', 'incomplete', recipes, 'investigation-verify', 'investigation.json'),
            ('comparison/report', 'comparison', recipes, 'comparison-verify', 'comparison.json'),
            ('staged-rebuilt', 'staged', recipes, 'comparison-verify', 'comparison.json'),
            ('minimization-report', 'minimization', minimization_cli, 'verify', 'minimization.json')):
            shutil.copytree(output / source, portable / name)
            verification[name] = commands.call(module, [operation, portable / name / filename])
        for name, module, operation, filename in (
            ('investigation', recipes, 'investigation-verify', 'investigation.json'),
            ('comparison', recipes, 'comparison-verify', 'comparison.json'),
            ('minimization', minimization_cli, 'verify', 'minimization.json')):
            verification[name + '-rebuilt'] = commands.call(module,
                [operation, output / (name + '-rebuilt') / filename])
        tampered = output / 'tampered'
        shutil.copytree(portable / 'comparison', tampered)
        (tampered / 'REPORT.md').write_text('SIMULATED forged conclusion\n')
        commands.call(recipes, ['comparison-verify', tampered / 'comparison.json'], expected=2)
        assert len(runtime.attempts) == before
    summary = {'status': 'passed', 'simulation': True, 'target_adapter': 'frr_c',
        'assertions': assertions, 'minimization': status, 'attempts': runtime.attempts,
        'staged': {'simulation': True, 'case': 'separate passing observations for both supplied images',
                   'status': review['status'], 'attempts': staged_runtime.attempts,
                   'final_review': staged_receipt},
        'probe_commands': host.calls, 'performance_policy': 'disabled',
        'qualification': 'not_assessed', 'calibration': 'deferred',
        'index': str(output / 'REPORT.md'), 'portable_directory': str(output / 'return')}
    _write(output / 'commands.json', commands.records)
    _write(output / 'verification.json', verification)
    _write(output / 'smoke.json', summary)
    (output / 'REPORT.md').write_text('''# Supplied-image FRR modeled workflow

All images, observations, counts, differences and workers are **SIMULATED**.
No FRR fault, fix, source change, daemon execution or performance result is claimed.

- [Frozen recipe](recipe.json), [offline plan](plan.json), and [commands](commands.json).
- [Reproduction](return/reproduction/SUMMARY.txt): completed; selected correctness fails.
- [Investigation](return/investigation/REPORT.md): six assertions; candidate passes.
- [Incomplete pair](return/incomplete/REPORT.md): missing candidate remains inconclusive.
- [Repeated comparison](return/comparison/REPORT.md): four independent original attempts.
- [Staged comparison](return/staged/REPORT.md): two additional passing modeled originals;
  explicit first/final review pauses and refused premature steps.
  [First review](staged/reviews/first.json) and [final review](staged/reviews/final.json)
  bind copied modeled attestations and assessments in the retained local session.
- [Minimization](return/minimization/REPORT.md): selected count failure, fresh confirmation.
- [Verification](verification.json): relocation and reconstruction require no worker.

The changed-image candidate is supplied, with unknown source provenance. It is
not a compiled fix. Portable reports retain originals, not the whole work/session.
Tampered report refusal is retained in commands.json. Checksums do not authenticate
execution. Performance policy is disabled; formal 10% calibration is deferred.

The separate staged case models passing observations for both images so that
the assessment/review gates can advance. It does not replace or contradict the
earlier controlled mismatch case. Reviews are modeled attestations, not an
independent human review. There are 14 distinct modeled originals in total:
1 reproduction, 2 investigation, 4 repeated, 2 staged and 5 minimization.
The portable staged report bundles originals. Local review receipts retain
absolute session bindings and are not claimed portable.
''')
    return summary


def run_smoke(output):
    with ExitStack() as stack:
        stack.enter_context(patch.object(subprocess, 'Popen', _forbidden))
        for name in ('__init__', 'connect', 'connect_ex', 'sendto'):
            stack.enter_context(patch.object(socket.socket, name, _forbidden))
        stack.enter_context(patch.object(socket, 'create_connection', _forbidden))
        return _run_smoke(output)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    args = parser.parse_args(argv)
    try:
        result = run_smoke(args.output)
    except (OSError, ValueError, RuntimeError) as exc:
        print('FRR workflow smoke: ' + str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
