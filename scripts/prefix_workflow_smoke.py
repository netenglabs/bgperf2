#!/usr/bin/env python3
# Copyright (C) 2026 bgperf2 contributors. Apache-2.0.
"""Connect inert local Git preparation to SIMULATED prefix regression evidence.

Only the setup's allowlisted local Git commands execute. Builds, images and
daemon outcomes are simulated, not BIRD faults. Public CLIs handle contracts,
capture selection, CI, repeated comparison, recovery and boundary confirmation.
"""
import argparse
import base64
from contextlib import ExitStack
import hashlib
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

import recipes
import recipe_bisection as bisection
import recipe_prefixes as prefixes
import recipe_run
import recipe_targets as targets
from scripts import checkout_workflow_smoke as checkout
from scripts.bisection_smoke import BisectionHost, SimulatedBisection, SimulatedOS
from scripts.maintainer_smoke import Commands, _forbidden
from scripts.recipe_smoke import _write


class PreparedChain:
    """Read the actual inert preparation's frozen commit proofs, without Git."""
    def __init__(self, plan):
        self.builds = [item['build_plan'] for item in plan['candidates']]
        self.objects = {(build['source_root'], item['revision']): base64.b64decode(item['commit_object'])
                        for build, item in zip(self.builds, plan['candidates'])}
        self.calls = []

    def git(self, root, *arguments):
        args = tuple(map(str, arguments))
        self.calls.append({'root': str(root), 'arguments': list(args)})
        if len(args) == 3 and args[:2] == ('cat-file', 'commit'):
            value = self.objects.get((str(root), args[2]))
            if value is not None:
                return value
        raise AssertionError('Prefix walkthrough refused an unmodeled source operation')


class PrefixRuntime(SimulatedBisection):
    """Model one count-preserving set substitution; no source fault executes."""
    def build(self, document, *, output_dir, emit_disclosure, timeout):
        return super().build(document, output_dir=Path(output_dir),
                             emit_disclosure=emit_disclosure, timeout=timeout)

    def execute(self, document, workdir, attempt_id, timeout):
        outcome = self.runtime.execute(document, workdir, attempt_id, timeout)
        target = recipes.read_document(workdir / 'target.json')
        source = target['provenance']['source']
        index = self.indices[source['commit']]
        wrong = index >= 2 and not source['dirty']
        budget = recipes.read_document(workdir / 'execution-budget.json')
        budget.update(started_monotonic_s=1, ended_monotonic_s=1 + budget['elapsed_seconds'])
        _write(workdir / 'prefix-fixture.json', {'simulation': True,
            'reason': 'Modeled evidence only; inert source comments were never compiled.',
            'index': index, 'dirty_candidate': source['dirty'], 'substituted_prefix': wrong})
        (workdir / 'execution-budget.json').write_text(json.dumps(budget))
        requested = (budget['elapsed_seconds'] - 3) * 1_000_000_000
        selected = (workdir / 'observer-prefix-selection.json').exists()
        if selected:
            first = int(ipaddress.IPv4Address('100.0.0.0'))
            values = [str(ipaddress.IPv4Address(first + n)) + '/32'
                      for n in range(prefixes.expected_count(document))]
            if wrong:
                values[0] = '192.0.2.1/32'
            _write(workdir / 'observer-prefixes.json', {
                'schema': prefixes.CAPTURE_SCHEMA, 'recipe_sha256': recipes.recipe_sha256(document),
                'status': 'collected', 'phase': 'post_measurement', 'reason': None,
                'requested_ns': int(requested), 'completed_ns': int(requested + 200_000_000),
                'snapshot': {'schema': prefixes.SCHEMA, 'status': 'complete', 'reason': None,
                    'monotonic_ns': int(requested + 100_000_000), 'connection_id': 1, 'updates': 2,
                    'accepted_count': len(values), 'prefixes': values}})
        self.attempts.append({'index': index, 'source_attempt_id': attempt_id,
            'status': 'completed', 'timeout': timeout, 'simulation': True,
            'capture_selected': selected, 'substituted_prefix': wrong,
            'dirty_candidate': source['dirty']})
        return outcome


def _tree(root):
    result = {}
    for path in root.rglob('*'):
        if path.is_symlink():
            raise recipes.ContractError('Unexpected symlink in preserved inert fixture: ' + str(path))
        if path.is_file():
            result[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
        elif not path.is_dir():
            raise recipes.ContractError('Unexpected nonregular entry in preserved inert fixture: ' + str(path))
    return result


def _run_stages(output):
    prepared = output / 'checkout'
    packet = prepared / 'handoff'
    manifest = recipes.read_document(packet / 'handoff.json')
    graph = recipes.read_document(packet / 'commands.json')
    steps = {step['id']: step for step in graph['steps']}
    plan = recipes.read_document(packet / 'inputs/bisection-plan.json')
    recipe = plan['recipe']
    chain = PreparedChain(plan)
    host = BisectionHost(recipe)
    runtime = PrefixRuntime('assertions', chain, host)
    commands = Commands(output / 'commands')
    verification = {}
    source_before = _tree(prepared / 'maintainer-source')
    _write(output / 'source-before.json', source_before)
    def frozen_inputs():
        return {'prepared-range': _tree(prepared / 'prepared-range'),
                'handoff': _tree(packet),
                'candidate-build-plan.json': hashlib.sha256(
                    (prepared / 'candidate-build-plan.json').read_bytes()).hexdigest()}
    prepared_before = frozen_inputs()
    _write(output / 'prepared-before.json', prepared_before)
    session = Path(manifest['destinations']['session'])
    results = Path(manifest['destinations']['results_root'])
    builds = Path(manifest['destinations']['build_root'])

    def step(name, expected=0):
        argv = steps[name]['argv']
        module = recipes if Path(argv[1]).name == 'recipes.py' else bisection
        return commands.call(module, argv[2:], expected=expected)

    with ExitStack() as stack:
        host.patch(stack)
        stack.enter_context(patch.object(recipe_run, 'os', SimulatedOS(output / 'modeled-recipe.lock')))
        stack.enter_context(patch.object(targets, '_git', chain.git))
        stack.enter_context(patch.object(targets, 'build_target', runtime.build))
        stack.enter_context(patch.object(recipe_run, 'SubprocessBackend', lambda **kwargs: runtime))
        for name in ('build_baseline', 'build_candidate', 'check_baseline', 'reproduce'):
            step(name)
        verification['reproduction'] = step('verify_reproduction')
        step('export_assertions')
        reproduction_assertions = step('check_reproduction_assertions', expected=4)
        step('investigate')
        verification['investigation'] = step('verify_investigation')
        candidate_check = step('check_candidate_correctness')
        both_check = commands.call(recipes, ['investigation-check', results / 'investigation/report/investigation.json'], expected=4)
        step('rebuild_investigation')
        incomplete = output / 'incomplete-report'
        commands.call(recipes, ['investigation-report', '--baseline',
            results / 'investigation/baseline/result.json', '--observer-prefixes', '--output-dir', incomplete])
        missing_check = commands.call(recipes, ['investigation-check', incomplete / 'investigation.json',
                                               '--side', 'candidate'], expected=5)
        for name in ('plan_comparison', 'compare'):
            step(name)
        verification['comparison'] = step('verify_comparison')
        comparison = recipes.read_document(results / 'comparison/report/comparison.json')
        if comparison['correctness']['baseline']['failed'] != 2 or comparison['correctness']['candidate']['passed'] != 2:
            raise RuntimeError('Repeated comparison lost the modeled set mismatch')
        commands.call(recipes, ['comparison-report', builds / 'comparison-plan.json',
            '--attempts', results / 'comparison/attempts.json', '--output-dir', output / 'comparison-rebuilt'])
        verification['comparison-rebuilt'] = commands.call(recipes,
            ['comparison-verify', output / 'comparison-rebuilt/comparison.json'])
        step('init_bisection')
        preview_counts = len(runtime.builds), len(runtime.attempts)
        commands.call(bisection, ['status', session, '--json'])
        step('preview_bisection')
        if preview_counts != (len(runtime.builds), len(runtime.attempts)):
            raise RuntimeError('Read-only preview started modeled work')
        for _ in range(2):
            step('step_bisection')
        interruption = output / 'interruption'
        interruption.mkdir()

        def interrupt(*args, **kwargs):
            raise RuntimeError('SIMULATED stop after original prefix package, before journal append')

        with patch.object(bisection, 'append_result', interrupt):
            step('step_bisection', expected=2)
        shutil.copyfile(session / 'pending.json', interruption / 'pending.json')
        before = len(runtime.builds), len(runtime.attempts)
        pending_result = session / 'results/t0003/result.json'
        pending_hash = hashlib.sha256(pending_result.read_bytes()).hexdigest()
        _write(interruption / 'status.json', commands.call(bisection, ['status', session, '--json']))
        commands.call(bisection, ['report', session, '--output', output / 'pending-report'])
        step('step_bisection', expected=2)
        recovered = commands.call(bisection, ['recover', session, '--result', pending_result])
        _write(interruption / 'recovery.json', recovered)
        if before != (len(runtime.builds), len(runtime.attempts)) or pending_hash != hashlib.sha256(pending_result.read_bytes()).hexdigest():
            raise RuntimeError('Recovery repeated modeled work or changed its original evidence')
        conclusion = commands.call(bisection, ['run', session, '--execute'])
        if conclusion['state'] != 'confirmed':
            raise RuntimeError('The modeled prefix boundary did not confirm')
        offline_counts = len(runtime.builds), len(runtime.attempts)
        for name in ('bisection-report', 'bisection-rebuilt'):
            commands.call(bisection, ['report', session, '--output', output / name])
            verification[name] = commands.call(bisection, ['verify', output / name / 'bisection.json'])
        portable = output / 'return'
        portable.mkdir()
        for source, destination in ((results / 'reproduction', 'reproduction'),
                (results / 'investigation/report', 'investigation'), (incomplete, 'incomplete'),
                (results / 'comparison/report', 'comparison'), (output / 'pending-report', 'pending'),
                (output / 'bisection-report', 'bisection')):
            shutil.copytree(source, portable / destination)
        for name in ('investigation', 'incomplete'):
            verification['portable-' + name] = commands.call(recipes,
                ['investigation-verify', portable / name / 'investigation.json'])
        commands.call(recipes, ['investigation-check', portable / 'investigation/investigation.json', '--side', 'candidate'])
        verification['portable-comparison'] = commands.call(recipes,
            ['comparison-verify', portable / 'comparison/comparison.json'])
        for name in ('pending', 'bisection'):
            verification['portable-' + name] = commands.call(bisection,
                ['verify', portable / name / 'bisection.json'])
        if offline_counts != (len(runtime.builds), len(runtime.attempts)):
            raise RuntimeError('Offline reports started modeled work')
    source_after = _tree(prepared / 'maintainer-source')
    _write(output / 'source-after.json', source_after)
    prepared_after = frozen_inputs()
    _write(output / 'prepared-after.json', prepared_after)
    if source_before != source_after or prepared_before != prepared_after:
        raise RuntimeError('Execution fixtures changed the original or prepared inert source/inputs')
    ids = [item['source_attempt_id'] for item in runtime.attempts]
    if len(ids) != len(set(ids)) or not all(item['capture_selected'] for item in runtime.attempts):
        raise RuntimeError('Stages reused an original attempt or lost capture selection')
    summary = {'status': 'passed', 'simulation': True, 'real_local_git_preparation': True,
        'predicate': 'prefix_assertions', 'recipe_sha256': recipes.recipe_sha256(recipe),
        'baseline_revision': chain.builds[-1]['source']['commit'],
        'candidate_meaning': 'SIMULATED local dirty fix on the same inert source tip; never compiled.',
        'original_source_preserved': True, 'prepared_sources_preserved': True,
        'candidate_check': candidate_check['outcome'],
        'both_check': both_check['outcome'], 'missing_candidate_check': missing_check['outcome'],
        'reproduction_assertions': reproduction_assertions, 'conclusion': conclusion,
        'interruption_original_sha256': pending_hash, 'builds': runtime.builds, 'attempts': runtime.attempts,
        'index': str(output / 'REPORT.md'), 'portable_directory': str(output / 'return'),
        'performance_policy': 'disabled', 'qualification': 'not_assessed', 'calibration': 'deferred'}
    _write(output / 'commands.json', commands.records)
    _write(output / 'verification.json', verification)
    _write(output / 'smoke.json', summary)
    (output / 'REPORT.md').write_text('''# One exact-prefix maintainer workflow

Local Git preparation used inert comments-only fixtures. All builds, images,
daemon behavior and numeric observations are **SIMULATED**; no BIRD source or
fault was compiled or executed. No actual bug/fix or performance verdict is claimed.

1. [Checkout and verified handoff](checkout/REPORT.md) prepare four real local
   first-parent revisions and retain the dirty candidate without changing it.
   That report is a frozen setup snapshot: its then-future destinations later
   receive the simulated execution evidence shown here; it grants no real run.
   [Prepared inputs before](prepared-before.json) and [after](prepared-after.json)
   retain the historical checkouts, private Git bank, handoff and candidate plan.
2. [Reproduction](return/reproduction/SUMMARY.txt) completes and reports count
   100, but its exact set has one substituted prefix. Recipe reproduction asks
   only for completion; correctness is a separate named assertion.
3. [Investigation](return/investigation/REPORT.md) retains that mismatch and a
   passing candidate. CI exits 4 for both sides and 0 for the candidate; a
   [missing candidate](return/incomplete/REPORT.md) exits 5, not a silent pass.
4. [Repeated comparison](return/comparison/REPORT.md) retains four distinct
   original attempts, separate count/identity results and capture confounders.
   Numeric observations are fixtures, not performance measurements.
5. [Pending search](return/pending/REPORT.md), [reservation](interruption/pending.json)
   and [recovery](interruption/recovery.json) show that an already collected
   original is recorded without another modeled build or worker.
6. [Confirmed boundary](return/bisection/REPORT.md) retains fresh good/bad
   confirmations for revisions 1 and 2 under the declared monotone assumption.
7. [Verification](verification.json), [commands](commands.json) and [summary](smoke.json)
   retain exact public CLI outcomes and prove report reconstruction/relocation
   starts no modeled work. Original work, source checkouts and prepared paths
   remain local; the portable reports are not a complete backup.

Performance policy remains disabled and formal 10% calibration deferred.
''')
    return summary


def run_smoke(output):
    output = bisection.safe(output)
    if output == ROOT or ROOT in output.parents:
        raise ValueError('Choose a fresh output outside the engine checkout')
    output.mkdir(mode=0o700)
    # This maintained setup has its own allowlist for local inert Git only.
    checkout.run_smoke(output / 'checkout', predicate='prefix_assertions')
    with ExitStack() as stack:
        stack.enter_context(patch.object(subprocess, 'Popen', _forbidden))
        for name in ('__init__', 'connect', 'connect_ex', 'sendto'):
            stack.enter_context(patch.object(socket.socket, name, _forbidden))
        stack.enter_context(patch.object(socket, 'create_connection', _forbidden))
        return _run_stages(output)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    args = parser.parse_args(argv)
    try:
        result = run_smoke(args.output)
    except (OSError, ValueError, RuntimeError) as exc:
        print('Prefix workflow smoke: ' + str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
