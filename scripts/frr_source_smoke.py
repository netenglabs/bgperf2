#!/usr/bin/env python3
# Copyright (C) 2026 bgperf2 contributors. Apache-2.0.
"""SIMULATED FRR source, rollback, minimization and correctness localization.

Public CLI contracts execute locally. Source inspection, images, builders and
workers are modeled; subprocess/network guards forbid real execution throughout.
"""
import argparse
import copy
from contextlib import ExitStack
import hashlib
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
import recipe_bisection as bisection
import recipe_minimization as minimization
import recipe_prefixes as prefixes
import recipe_run
import recipe_targets as targets
import recipes
from scripts.bisection_smoke import BisectionHost, SimulatedChain, SimulatedBisection, TOOLCHAIN, RUNTIME
from scripts.frr_workflow_smoke import FRRRuntime
from scripts.maintainer_smoke import Commands, _forbidden
from scripts.recipe_smoke import SimulatedOS, _write


class SourceRuntime(FRRRuntime):
    """A count-preserving wrong prefix, introduced at modeled revision four."""
    def __init__(self, chain, host):
        super().__init__()
        self.failure_images = set()
        self.builder = SimulatedBisection('assertions', chain, host)

    def build(self, document, **kwargs):
        kwargs['output_dir'] = Path(kwargs['output_dir'])
        result = self.builder.build(document, **kwargs)
        if self.builder.indices[document['source']['commit']] >= 4:
            self.failure_images.add(result['image'])
        return result

    def execute(self, document, workdir, attempt_id, timeout):
        outcome = super().execute(document, workdir, attempt_id, timeout)
        events = recipes.read_document(workdir / 'raw-events.json')
        events['events'][-1]['counters']['accepted_prefixes'] = prefixes.expected_count(document)
        (workdir / 'raw-events.json').write_text(json.dumps(events))
        return outcome


def _chain(root, recipe):
    chain = SimulatedChain(root, recipe)
    for build in chain.builds:
        build['build_recipe'] = 'frr-local/v1'
        targets.validate_build_plan(build)
    return chain


def _run_smoke(output):
    output = bisection.safe(output)
    if output == ROOT or ROOT in output.parents:
        raise ValueError('Choose a new output outside the engine checkout')
    output.mkdir(mode=0o700)
    commands = Commands(output / 'commands')
    batch = output / 'batch.yaml'
    batch.write_text('tests:\n  - name: frr-source\n    monitor: sink\n'
        '    neighbors: [2]\n    prefixes: [8]\n    filter_test: [None]\n'
        '    targets:\n      - name: frr_c\n')
    test = recipes._source_tests(batch.read_text())[0]
    cell = recipes.construct_batch_cells(test, test['targets'], repetitions=1,
        prefix_resolver=recipes.resolve_prefix_scope, path_diversity=1, receivers=0,
        churn_prefixes=0, churn_bursts=0, policy_reload_blocks=0, pin=None, monitor='sink')[0]
    key = recipes.batch_cell_key(recipes.batch_cell_id(test['name'], cell))
    revision = recipes.read_document(ROOT / 'examples/recipes/synthetic-ipv4.recipe.json')['engine']['revision']

    def export(path, image):
        commands.call(recipes, ['export', '--batch', batch, '--test', test['name'], '--cell', key,
            '--engine-revision', revision, '--target-image', image,
            '--generator-image', 'sha256:' + '2' * 64, '--observer-image', 'sha256:' + '3' * 64,
            '--question', 'SIMULATED FRR count-preserving prefix fault; candidate is an explicit local rollback.',
            '--output', path])
        return recipes.read_document(path)

    recipe_path = output / 'recipe.json'
    recipe = export(recipe_path, 'sha256:' + '1' * 64)
    chain = _chain(output, recipe)
    host = BisectionHost(recipe)
    runtime = SourceRuntime(chain, host)
    verification = {}

    def snapshot(root, requested, include_dirty, *, adapter='bird'):
        assert adapter == 'frr_c' and include_dirty is False
        build = next(row for row in chain.builds if row['source_root'] == str(root))
        assert requested == build['source']['commit']
        return copy.deepcopy(build['source']), b'SIMULATED snapshot', b''

    with ExitStack() as stack:
        host.patch(stack)
        stack.enter_context(patch.dict('os.environ', {'BGPERF_ARTIFACT_STORE': str(output / 'artifact-store')}))
        stack.enter_context(patch.object(recipe_run, 'os', SimulatedOS(output / 'modeled-host.lock')))
        stack.enter_context(patch.object(targets, '_git', chain.git))
        stack.enter_context(patch.object(targets, '_snapshot', snapshot))
        stack.enter_context(patch.object(targets, 'build_target', runtime.build))
        stack.enter_context(patch.object(recipe_run, 'SubprocessBackend', lambda **_: runtime))
        # The fixed history has one good->bad transition. Candidate rolls back
        # to revision three; this does not pretend to be an upstream fix.
        for name, index in (('baseline', 8), ('candidate', 3)):
            build = chain.builds[index]
            commands.call(recipes, ['target-source-plan', recipe_path, '--source', build['source_root'],
                '--revision', build['source']['commit'], '--toolchain-image', TOOLCHAIN,
                '--runtime-image', RUNTIME, '--output', output / (name + '-build-plan.json')])
            commands.call(recipes, ['target-build', output / (name + '-build-plan.json'),
                '--output-dir', output / ('build-' + name), '--timeout', 60])
        baseline, candidate = (output / ('build-' + name) / 'target.json' for name in ('baseline', 'candidate'))
        commands.call(recipes, ['run', recipe_path, '--target', baseline, '--workdir', output / 'repro-work',
            '--results-dir', output / 'repro', '--timeout', 120, '--diagnostics', 'basic', '--observer-prefixes'])
        commands.call(recipes, ['investigate', recipe_path, '--baseline-target', baseline,
            '--candidate-target', candidate, '--workdir', output / 'pair-work', '--results-dir', output / 'pair',
            '--timeout', 120, '--diagnostics', 'basic', '--observer-prefixes'])
        investigation = output / 'pair/report/investigation.json'
        commands.call(recipes, ['investigation-check', investigation], expected=4)
        commands.call(recipes, ['investigation-check', investigation, '--side', 'candidate'])
        commands.call(recipes, ['investigation-rebuild', investigation, '--output-dir', output / 'pair-rebuilt'])

        # Image-only minimization requires an explicitly exported recipe. The
        # source-bound original target remains bound to its original recipe.
        image_recipe_path = output / 'image-recipe.json'
        image_recipe = export(image_recipe_path, recipes.read_document(baseline)['image'])
        plan_path, session = output / 'minimization-plan.json', output / 'minimization'
        commands.call(minimization_cli, ['plan', image_recipe_path, '--assertion', 'observer.prefixes',
            '--max-trials', 20, '-o', plan_path])
        commands.call(minimization_cli, ['init', plan_path, '--workdir', output / 'min-work', '--results-dir', session])
        for _ in range(21):
            status = commands.call(minimization_cli, ['status', session])
            if status['next'] is None:
                break
            commands.call(minimization_cli, ['step', session, '--execute'])
        else:
            raise RuntimeError('Modeled minimization exceeded its fixed budget')
        if not status['confirmed'] or status['best'] != {'peers': 1, 'routes': 2}:
            raise RuntimeError('Expected a fresh confirmed one-peer/two-route reduction')
        commands.call(minimization_cli, ['report', session, '--output-dir', output / 'min-report'])
        commands.call(minimization_cli, ['rebuild', output / 'min-report/minimization.json',
            '--output-dir', output / 'min-rebuilt'])
        reduced = minimization.candidate_recipe(image_recipe, **status['best'])
        reduced_path = output / 'reduced-recipe.json'
        _write(reduced_path, reduced)
        commands.call(recipes, ['validate', reduced_path])
        commands.call(recipes, ['target-validate', baseline, '--recipe', reduced_path], expected=2)
        reduced_chain = _chain(output, reduced)
        # Replan each source selection against the new canonical recipe. These
        # plans retain the same source proofs and fixed controls, with new
        # recipe bindings and resulting build identities.
        args = ['plan', '--recipe', reduced_path, '--predicate', 'prefix_assertions',
            '--max-trials', 16, '--worker-timeout', 120, '--build-timeout', 60,
            '--output', output / 'bisection-plan.json']
        for index, build in enumerate(reduced_chain.builds):
            path = output / f'reduced-build-{index}.json'
            commands.call(recipes, ['target-source-plan', reduced_path, '--source', build['source_root'],
                '--revision', build['source']['commit'], '--toolchain-image', TOOLCHAIN,
                '--runtime-image', RUNTIME, '--output', path])
            args += ['--build-plan', path]
        commands.call(bisection, args)
        search = output / 'search'
        commands.call(bisection, ['init', output / 'bisection-plan.json', '--session', search])
        before = len(runtime.attempts)
        commands.call(bisection, ['status', search, '--json'])
        commands.call(bisection, ['step', search])
        assert len(runtime.attempts) == before
        for _ in range(2):
            commands.call(bisection, ['step', search, '--execute'])

        def interrupted(*_, **__):
            raise RuntimeError('SIMULATED interruption after original package, before journal append')

        with patch.object(bisection, 'append_result', interrupted):
            commands.call(bisection, ['step', search, '--execute'], expected=2)
        _write(output / 'pending-status.json', commands.call(bisection, ['status', search, '--json']))
        pending = search / 'results/t0003/result.json'
        original_sha = hashlib.sha256(pending.read_bytes()).hexdigest()
        counts = (len(runtime.builder.builds), len(runtime.attempts))
        commands.call(bisection, ['report', search, '--output', output / 'pending-report'])
        commands.call(bisection, ['step', search, '--execute'], expected=2)
        commands.call(bisection, ['recover', search, '--result', pending])
        assert counts == (len(runtime.builder.builds), len(runtime.attempts))
        assert original_sha == hashlib.sha256(pending.read_bytes()).hexdigest()
        conclusion = commands.call(bisection, ['run', search, '--execute'])
        if conclusion['state'] != 'confirmed':
            raise RuntimeError('Expected fresh boundary confirmations')
        counts = (len(runtime.builder.builds), len(runtime.attempts))
        for name in ('search-report', 'search-rebuilt'):
            commands.call(bisection, ['report', search, '--output', output / name])
        portable = output / 'return'
        portable.mkdir()
        for name, source, module, operation, filename in (
                ('repro', output / 'repro', recipes, 'result-verify', 'result.json'),
                ('pair', investigation.parent, recipes, 'investigation-verify', 'investigation.json'),
                ('pair-rebuilt', output / 'pair-rebuilt', recipes, 'investigation-verify', 'investigation.json'),
                ('minimization', output / 'min-report', minimization_cli, 'verify', 'minimization.json'),
                ('min-rebuilt', output / 'min-rebuilt', minimization_cli, 'verify', 'minimization.json'),
                ('pending', output / 'pending-report', bisection, 'verify', 'bisection.json'),
                ('search', output / 'search-report', bisection, 'verify', 'bisection.json'),
                ('search-rebuilt', output / 'search-rebuilt', bisection, 'verify', 'bisection.json')):
            shutil.copytree(source, portable / name)
            verification[name] = commands.call(module, [operation, portable / name / filename])
        for left, right, filename in (('pair', 'pair-rebuilt', 'investigation.json'),
                ('minimization', 'min-rebuilt', 'minimization.json'), ('search', 'search-rebuilt', 'bisection.json')):
            assert recipes.read_document(portable / left / filename) == recipes.read_document(portable / right / filename)
        assert counts == (len(runtime.builder.builds), len(runtime.attempts))
        tampered = output / 'tampered'
        shutil.copytree(portable / 'search', tampered)
        with (tampered / 'REPORT.md').open('a') as stream:
            stream.write('\nSIMULATED changed-evidence refusal.\n')
        commands.call(bisection, ['verify', tampered / 'bisection.json'], expected=2)
    ids = [row['id'] for row in runtime.attempts]
    assert len(ids) == len(set(ids))
    summary = {'status': 'passed', 'simulation': True, 'adapter': 'frr_c',
        'attempts': runtime.attempts, 'builds': runtime.builder.builds,
        'minimization': status, 'conclusion': conclusion,
        'recovered_original_sha256': original_sha,
        'performance_policy': 'disabled', 'calibration': 'deferred', 'qualification': 'not_assessed'}
    _write(output / 'commands.json', commands.records)
    _write(output / 'verification.json', verification)
    _write(output / 'smoke.json', summary)
    (output / 'REPORT.md').write_text('''# Simulated FRR source maintainer workflow

All source inspection, commit histories, builds, images, workers and numeric
observations are **SIMULATED**. No real FRR source, compiler, daemon or network ran.

This example asks whether a maintainer can detect a route-identity regression,
check a rollback, shrink the reproducer and locate the first bad source change.
The baseline deliberately delivers the correct count with one wrong prefix;
its failed identity assertion is the expected starting observation. The rollback
passes. The later reduction and source boundary are confirmed using fresh
simulated observations, not reused endpoint results. No numeric value here is
a performance measurement. Read the linked reports below in order.

- [Source recipe](recipe.json), [baseline plan](baseline-build-plan.json) and
  [candidate plan](candidate-build-plan.json): candidate is an explicit rollback
  to pre-fault revision three, not an upstream fix.
- [Reproduction](return/repro/SUMMARY.txt) and [investigation](return/pair/REPORT.md):
  count passes while prefix identity fails on the baseline. Candidate CI passes.
- [Minimization](return/minimization/REPORT.md): fresh confirmation at one peer
  and two routes. The built failing image is explicitly selected in a new recipe.
- [Reduced recipe](reduced-recipe.json): source plans are regenerated against
  this recipe; the old target binding is deliberately refused.
- [Pending original](return/pending/REPORT.md) and [pending status](pending-status.json):
  recovery records exactly the already collected original without another worker.
- [Boundary](return/search/REPORT.md): revision three to four, with fresh good/bad
  confirmations. This assumes a single monotone transition in this modeled history.
- [Verification](verification.json) and [command receipts](commands.json): reports
  reconstruct and verify after relocation; changed evidence is refused.

Checksums do not authenticate execution. FRR crash and thread controls remain
unsupported. Performance policy is disabled, calibration deferred and broader
live qualification unassessed. Source-range and handoff preparation have separate
inert real-Git tests; this walkthrough models source inspection explicitly.

To prepare your own source and workload, continue with docs/first-run.md in
your checkout. The fixture's revisions, images and observations are illustrative
inputs and cannot be relabeled into real execution evidence.
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
        summary = run_smoke(args.output)
    except (OSError, ValueError, RuntimeError) as exc:
        print('FRR source smoke: ' + str(exc), file=sys.stderr)
        return 2
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
