#!/usr/bin/env python3
# Copyright (C) 2026 bgperf2 contributors. Apache-2.0.
"""Walk one SIMULATED crash from reproduction through rollback and bisection.

The public CLI handles all contracts and evidence. Existing maintained fixtures
replace source, image, build and worker operations; no real subprocess or socket
is permitted anywhere in this walkthrough. Output is retained outside the checkout.
"""
import argparse
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import hashlib
import io
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
import recipe_run
import recipe_targets as targets
from scripts.bisection_smoke import BisectionHost, SimulatedBisection, SimulatedChain, SimulatedOS
from scripts.recipe_smoke import _write


def _forbidden(*args, **kwargs):
    raise AssertionError('Maintainer smoke forbids unmodelled subprocess and network operations')


class MaintainerRuntime(SimulatedBisection):
    """The existing crash history, with explicit reproduction evidence attached."""
    def build(self, document, *, output_dir, emit_disclosure, timeout):
        return super().build(document, output_dir=Path(output_dir),
                             emit_disclosure=emit_disclosure, timeout=timeout)

    def execute(self, document, workdir, attempt_id, timeout):
        outcome = super().execute(document, workdir, attempt_id, timeout)
        bad = self.attempts[-1]['index'] >= 4
        outcome['reproduction'] = {
            'outcome': 'reproduced' if bad else 'not_reproduced',
            'reason': 'SIMULATED captured abnormal exit.' if bad else 'SIMULATED completion without crash.',
            'evidence': ['work/live-diagnostics.json', 'work/runtime.json']}
        (workdir / 'runtime.json').write_text(json.dumps(outcome))
        return outcome


class Commands:
    """Retain the exact public command, exit, stdout and stderr, including refusal."""
    def __init__(self, output):
        self.output, self.records = output, []
        output.mkdir()

    def call(self, module, arguments, *, expected=0):
        arguments = list(map(str, arguments))
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            try:
                code = module.main(arguments)
            except SystemExit as exc:
                code = exc.code
        record = {'entrypoint': Path(module.__file__).name, 'arguments': arguments,
                  'exit_code': code, 'stdout': stdout.getvalue(), 'stderr': stderr.getvalue()}
        self.records.append(record)
        _write(self.output / f'{len(self.records):03d}.json', record)
        if code != expected:
            raise RuntimeError(f'{record["entrypoint"]} {arguments[0]} exited {code}: {record["stderr"]}')
        return json.loads(stdout.getvalue()) if stdout.getvalue().strip() else None


def _index(output):
    (output / 'REPORT.md').write_text('''# One simulated maintainer investigation

All revisions, images, builds, worker observations and numeric fixture values
are **SIMULATED**. No actual daemon, compiler, download or benchmark ran.
Performance policy is disabled; calibration remains deferred.

1. [Frozen crash recipe](recipe.json) and [validated offline plan](plan.json):
   understand the fixed workload, role identities and `target_crash` question.
2. [Reproduction package](return/reproduction/SUMMARY.txt): inspect the bad tip's
   `experiment_failed` status and its separate `reproduced` crash observation.
3. [Local rollback investigation](return/investigation/REPORT.md): the same bad
   tip is compared with revision 3 from this same inert history. The candidate
   is an explicit rollback to pre-regression source, with fresh attempts.
   Source/build identities and observed target differences remain visible.
   [Stopped investigation](return/investigation-stopped/REPORT.md) separately
   retains a verified baseline package and a controller stop before the candidate
   runs. Its outcome is inconclusive. Both investigations are rebuilt through
   the public offline command without losing unavailable-attempt reasons.
4. [Interrupted controller status](interruption/status.json) and
   [portable pending report](return/pending/REPORT.md): two trials are recorded;
   trial 3 has a completed original package but its journal append was interrupted.
   The reservation is retained and no automatic retry runs.
5. [Recovery receipt](interruption/recovery.json): public `recover --result`
   records that exact original package without another build or worker.
   [Before](interruption/pending.json) and [after](interruption/status-after.json)
   retain the reservation and recovery accounting.
6. [Confirmed boundary](return/bisection/REPORT.md): the search independently
   locates the 3→4 transition, then uses fresh original confirmation attempts.
   Cached builds never substitute for fresh worker observations.
7. [Verification receipts](verification.json) and [all public commands](commands.json):
   the copied return packages verify after relocation. Report-only reconstruction
   uses existing evidence and starts no build or worker.

The `return/` directory contains portable recipe/result, investigation and
bisection evidence; its reports link to bundled originals. `session/` retains
all work, cache, original result packages and journal state. `interruption/`
preserves the pre-recovery state and error rather than erasing the interruption.
Checksums detect changed evidence; they do not authenticate execution.
The observed single-transition boundary and scoped baseline/candidate outcome
establish neither a general fix nor a performance conclusion.
''')


def _run_smoke(output):
    output = bisection.safe(output)
    if output == ROOT or ROOT in output.parents:
        raise ValueError('Choose an output directory outside the engine checkout')
    output.mkdir(mode=0o700)
    (output / 'SIMULATION.txt').write_text(
        'SIMULATED source, builds, images and workers only. No actual bug/fix or performance result.\n')
    commands = Commands(output / 'commands')
    recipe_path = output / 'recipe.json'
    fixture = recipes.read_document(ROOT / 'examples/recipes/synthetic-ipv4.recipe.json')
    commands.call(recipes, ['export', '--batch', ROOT / 'examples/recipes/synthetic-ipv4.yaml',
        '--test', fixture['selection']['test'], '--cell', fixture['selection']['cell_key'],
        '--engine-revision', fixture['engine']['revision'], '--target-image', 'sha256:'+'1'*64,
        '--generator-image', 'sha256:'+'2'*64, '--observer-image', 'sha256:'+'3'*64,
        '--question', 'SIMULATED tip crash, local rollback and deterministic first-bad history.',
        '--expected-outcome', 'target_crash', '--output', recipe_path])
    recipe = recipes.read_document(recipe_path)
    for operation in ('validate', 'inspect', 'plan'):
        _write(output / (operation+'.json'), commands.call(recipes, [operation, recipe_path]))
    chain = SimulatedChain(output, recipe)
    host = BisectionHost(recipe)
    runtime = MaintainerRuntime('target-crash', chain, host)
    verification = {}
    with ExitStack() as stack:
        host.patch(stack)
        stack.enter_context(patch.object(recipe_run, 'os', SimulatedOS(output/'simulated-host.lock')))
        stack.enter_context(patch.object(targets, '_git', chain.git))
        stack.enter_context(patch.object(targets, 'build_target', runtime.build))
        stack.enter_context(patch.object(recipe_run, 'SubprocessBackend', lambda **kwargs: runtime))
        plan_args = ['plan', '--recipe', recipe_path, '--predicate', 'target_crash',
            '--max-trials', 32, '--worker-timeout', 120, '--build-timeout', 60,
            '--output', output/'bisection-plan.json']
        for index, build in enumerate(chain.builds):
            path = output / f'build-plan-{index}.json'
            _write(path, build)
            plan_args += ['--build-plan', path]
        for name, index in (('baseline',8), ('candidate',3)):
            commands.call(recipes, ['target-build', output/f'build-plan-{index}.json',
                '--output-dir', output/f'build-{name}', '--timeout', 60])
            commands.call(recipes, ['target-validate', output/f'build-{name}/target.json',
                '--recipe', recipe_path])
        baseline, candidate = (output/f'build-{name}/target.json' for name in ('baseline','candidate'))
        reproduction = commands.call(recipes, ['run', recipe_path, '--target', baseline,
            '--workdir', output/'reproduction-work', '--results-dir', output/'reproduction',
            '--diagnostics', 'basic', '--timeout', 120], expected=4)
        if reproduction['reproduction']['outcome'] != 'reproduced':
            raise RuntimeError('Expected the modeled tip crash to reproduce')
        verification['reproduction'] = commands.call(recipes,
            ['result-verify', output/'reproduction/result.json'])
        investigation = commands.call(recipes, ['investigate', recipe_path,
            '--baseline-target', baseline, '--candidate-target', candidate,
            '--workdir', output/'investigation-work', '--results-dir', output/'investigation',
            '--diagnostics', 'basic', '--timeout',120])
        if investigation['assessment']['outcome'] != 'baseline_reproduced_candidate_not_reproduced':
            raise RuntimeError('The controlled rollback investigation lost its functional outcome')
        verification['investigation'] = commands.call(recipes,
            ['investigation-verify', output/'investigation/report/investigation.json'])
        commands.call(recipes, ['investigation-rebuild',
            output/'investigation/report/investigation.json',
            '--output-dir', output/'investigation-rebuilt'])
        verification['investigation-rebuilt'] = commands.call(recipes,
            ['investigation-verify', output/'investigation-rebuilt/investigation.json'])
        # A separate fresh investigation demonstrates a controller stop after a
        # valid baseline package. Preserve that observation, never run candidate.
        original_run = recipe_run.run_recipe

        def stopped_controller(*args, **kwargs):
            original_run(*args, **kwargs)
            raise SystemExit(143)

        before_stopped = len(runtime.attempts)
        with patch.object(recipe_run, 'run_recipe', stopped_controller):
            stopped = commands.call(recipes, ['investigate', recipe_path,
                '--baseline-target', baseline, '--candidate-target', candidate,
                '--workdir', output/'stopped-work', '--results-dir', output/'investigation-stopped',
                '--diagnostics', 'basic', '--timeout', 120], expected=143)
        if len(runtime.attempts) != before_stopped+1 or stopped['assessment']['outcome'] != 'inconclusive':
            raise RuntimeError('Stopped controller lost its inconclusive outcome or started candidate')
        verification['investigation-stopped'] = commands.call(recipes,
            ['investigation-verify', output/'investigation-stopped/report/investigation.json'])
        before_rebuild = (len(runtime.builds), len(runtime.attempts))
        commands.call(recipes, ['investigation-rebuild',
            output/'investigation-stopped/report/investigation.json',
            '--output-dir', output/'investigation-stopped-rebuilt'])
        verification['investigation-stopped-rebuilt'] = commands.call(recipes,
            ['investigation-verify', output/'investigation-stopped-rebuilt/investigation.json'])
        for source, rebuilt in ((output/'investigation/report',output/'investigation-rebuilt'),
                (output/'investigation-stopped/report',output/'investigation-stopped-rebuilt')):
            if recipes.read_document(source/'investigation.json') != recipes.read_document(rebuilt/'investigation.json'):
                raise RuntimeError('Investigation rebuild changed observations, missing reasons or stop')
        if before_rebuild != (len(runtime.builds), len(runtime.attempts)):
            raise RuntimeError('Investigation rebuild started modeled work')
        commands.call(bisection, plan_args)
        session = output / 'session'
        commands.call(bisection, ['init', output/'bisection-plan.json', '--session', session])
        counts = (len(runtime.builds), len(runtime.attempts))
        commands.call(bisection, ['status', session, '--json'])
        commands.call(bisection, ['run', session])
        if counts != (len(runtime.builds),len(runtime.attempts)):
            raise RuntimeError('Read-only status or preview started a modeled trial')
        for _ in range(2):
            commands.call(bisection, ['step', session, '--execute'])
        interruption = output / 'interruption'
        interruption.mkdir()

        def interrupted_append(*args, **kwargs):
            raise RuntimeError('SIMULATED controller interruption after verified original result, before journal append')

        with patch.object(bisection, 'append_result', interrupted_append):
            commands.call(bisection, ['step', session, '--execute'], expected=2)
        shutil.copyfile(session/'pending.json', interruption/'pending.json')
        before = (len(runtime.builds), len(runtime.attempts))
        status = commands.call(bisection, ['status', session, '--json'])
        _write(interruption/'status.json', status)
        if status['conclusion']['state'] != 'recovery_required' or status['trials_recorded'] != 2:
            raise RuntimeError('Controller interruption lost the pending reservation')
        pending_result = session/'results/t0003/result.json'
        original_hash = hashlib.sha256(pending_result.read_bytes()).hexdigest()
        verification['pending-original'] = commands.call(recipes, ['result-verify', pending_result])
        commands.call(bisection, ['report', session, '--output', output/'pending-report'])
        verification['pending-report'] = commands.call(bisection,
            ['verify', output/'pending-report/bisection.json'])
        # Attempting execution with a pending reservation must refuse without work.
        commands.call(bisection, ['step', session, '--execute'], expected=2)
        recovery = commands.call(bisection, ['recover', session, '--result', pending_result])
        _write(interruption/'recovery.json', recovery)
        _write(interruption/'status-after.json', commands.call(bisection, ['status',session,'--json']))
        if before != (len(runtime.builds),len(runtime.attempts)) or original_hash != hashlib.sha256(pending_result.read_bytes()).hexdigest():
            raise RuntimeError('Inspection/recovery changed the original or started more modeled work')
        conclusion = commands.call(bisection, ['run',session,'--execute'])
        if conclusion['state'] != 'confirmed':
            raise RuntimeError('Expected the controlled crash transition to confirm')
        before_reports = (len(runtime.builds),len(runtime.attempts))
        for name in ('bisection-report','bisection-rebuilt'):
            commands.call(bisection, ['report',session,'--output',output/name])
            verification[name] = commands.call(bisection, ['verify',output/name/'bisection.json'])
        if recipes.read_document(output/'bisection-report/bisection.json') != recipes.read_document(output/'bisection-rebuilt/bisection.json'):
            raise RuntimeError('Offline report reconstruction changed the boundary evidence')
        portable = output / 'return'
        portable.mkdir()
        for source, destination in ((output/'reproduction','reproduction'),
                (output/'investigation/report','investigation'),
                (output/'investigation-stopped/report','investigation-stopped'),
                (output/'pending-report','pending'), (output/'bisection-report','bisection')):
            shutil.copytree(source,portable/destination)
        verification['portable-reproduction'] = commands.call(recipes,['result-verify',portable/'reproduction/result.json'])
        verification['portable-investigation'] = commands.call(recipes,['investigation-verify',portable/'investigation/investigation.json'])
        verification['portable-investigation-stopped'] = commands.call(recipes,
            ['investigation-verify',portable/'investigation-stopped/investigation.json'])
        for name in ('pending','bisection'):
            verification['portable-'+name] = commands.call(bisection,['verify',portable/name/'bisection.json'])
        if before_reports != (len(runtime.builds),len(runtime.attempts)):
            raise RuntimeError('Offline reports started modeled source/build/runtime work')
    ids = [attempt['source_attempt_id'] for attempt in runtime.attempts]
    if len(ids) != len(set(ids)):
        raise RuntimeError('Separate stages reused an original attempt identity')
    summary = {'simulation':True, 'status':'passed',
        'scope':'One controlled crash history; local rollback, recovery and first-bad search. No real experiment.',
        'recipe_sha256':recipes.recipe_sha256(recipe), 'predicate':'target_crash',
        'baseline_revision':chain.builds[8]['source']['commit'],
        'candidate_revision':chain.builds[3]['source']['commit'],
        'candidate_meaning':'Local rollback to revision 3 in the same modeled history.',
        'conclusion':conclusion, 'interruption_original_sha256':original_hash,
        'index':str(output/'REPORT.md'), 'portable_directory':str(output/'return'),
        'builds':runtime.builds, 'attempts':runtime.attempts,
        'probe_commands':host.calls, 'source_commands':chain.calls,
        'performance_policy':'disabled', 'qualification':'not_assessed', 'calibration':'deferred'}
    _write(output/'commands.json',commands.records)
    _write(output/'verification.json',verification)
    _write(output/'smoke.json',summary)
    _index(output)
    return summary


def run_smoke(output):
    """Guard setup, public CLI calls, recovery, copies and report-only verification."""
    with ExitStack() as stack:
        stack.enter_context(patch.object(subprocess,'Popen',_forbidden))
        for name in ('__init__','connect','connect_ex','sendto'):
            stack.enter_context(patch.object(socket.socket,name,_forbidden))
        stack.enter_context(patch.object(socket,'create_connection',_forbidden))
        return _run_smoke(output)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,help='new absolute directory outside the checkout')
    args = parser.parse_args(argv)
    try:
        summary = run_smoke(args.output)
    except (OSError,ValueError,RuntimeError) as exc:
        print(f'maintainer smoke: {exc}',file=sys.stderr)
        return 2
    print(json.dumps(summary,indent=2,sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
