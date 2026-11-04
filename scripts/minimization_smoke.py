#!/usr/bin/env python3
# Copyright (C) 2026 bgperf2 contributors. Apache-2.0.
"""Public minimization walkthrough with SIMULATED observations only.

No real subprocess, network, build, daemon or measurement is permitted. Local
planning, reservation, packaging and independent verification are real.
"""
import argparse
from contextlib import ExitStack, redirect_stdout
import io
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import recipes
import minimization_cli
from scripts.comparison_smoke import ComparisonRuntime
from scripts.recipe_smoke import SimulatedHost, SimulatedOS, _write

CASES = ('reduction', 'unrelated-failure', 'inconclusive', 'budget-exhausted',
         'failed-confirmation', 'recovery', 'duplicate-identity')


def _forbidden(*args, **kwargs):
    raise AssertionError('Minimization smoke forbids unmodelled subprocess/network operations')


def _command(arguments, *, expected=0):
    output = io.StringIO()
    with redirect_stdout(output):
        code = minimization_cli.main(list(map(str, arguments)))
    if code != expected:
        raise RuntimeError(f'Minimization {arguments[0]} returned {code}, expected {expected}')
    return json.loads(output.getvalue()) if output.getvalue().strip() else None


class MinimizationRuntime:
    """One count disagreement; never represents a BIRD fault or source change."""
    def __init__(self, scenario):
        self.scenario = scenario
        self.runtime = ComparisonRuntime('known-difference')
        self.attempts = []

    def execute(self, document, workdir, attempt_id, timeout):
        point = (document['resolved']['neighbors'], document['resolved']['prefixes_per_peer'])
        repeated = point in [tuple(item['point']) for item in self.attempts]
        baseline = not self.attempts
        preserved = point[1] >= 2
        if self.scenario in ('unrelated-failure', 'inconclusive') and not baseline:
            preserved = False
        if self.scenario == 'failed-confirmation' and repeated:
            preserved = False
        outcome = self.runtime.execute(document, workdir, attempt_id, timeout)
        outcome['cleanup_errors'] = []
        budget = recipes.read_document(workdir / 'execution-budget.json')
        budget.update(started_monotonic_s=1, ended_monotonic_s=1 + budget['elapsed_seconds'])
        (workdir / 'execution-budget.json').write_text(json.dumps(budget))
        events = recipes.read_document(workdir / 'raw-events.json')
        if preserved:
            events['events'][-1]['counters']['accepted_prefixes'] -= 1
        if self.scenario == 'inconclusive' and not baseline:
            events['events'].pop()
        (workdir / 'raw-events.json').write_text(json.dumps(events))
        if self.scenario == 'unrelated-failure' and not baseline:
            outcome.update(status='experiment_failed', reason='SIMULATED unrelated completion failure.')
        (workdir / 'runtime.json').write_text(json.dumps(outcome))
        self.attempts.append({'point': list(point), 'attempt_id': attempt_id,
                              'selected_failure': preserved, 'simulation': True})
        return outcome


def _run_smoke(output):
    import recipe_run
    import recipe_minimization as core
    output = Path(output)
    if not output.is_absolute() or output.resolve() == ROOT or ROOT in output.resolve().parents:
        raise ValueError('Choose an absolute new output directory outside the engine checkout')
    output.mkdir(mode=0o700)
    (output / 'SIMULATION.txt').write_text(
        'All identities and observations are SIMULATED. No BIRD fault is represented.\n'
        'No real subprocess, network, acquisition, build, worker or daemon ran.\n'
        'Local packages demonstrate accounting and verification, not performance or host qualification.\n')
    recipe = recipes.read_document(ROOT / 'examples/recipes/synthetic-ipv4.recipe.json')
    recipe = core.candidate_recipe(recipe, 1, 8)
    cases = {}
    for scenario in CASES:
        case = output / scenario
        case.mkdir()
        recipe_path = case / 'recipe.json'
        _write(recipe_path, recipe)
        plan_path = case / 'plan.json'
        runtime = MinimizationRuntime(scenario)
        host = SimulatedHost(recipe)
        with ExitStack() as stack:
            host.patch(stack)
            stack.enter_context(patch.object(recipe_run, 'os', SimulatedOS(output / 'modeled-host.lock')))
            stack.enter_context(patch.object(recipe_run, 'SubprocessBackend', lambda **kwargs: runtime))
            if scenario == 'duplicate-identity':
                stack.enter_context(patch.object(recipe_run.uuid, 'uuid4',
                    lambda: SimpleNamespace(hex='a' * 32)))
            _command(['plan', recipe_path, '--assertion', 'observer.count', '--max-trials',
                      3 if scenario == 'budget-exhausted' else 32, '-o', plan_path])
            _command(['init', plan_path, '--workdir', case / 'work', '--results-dir', case / 'session'])
            session = case / 'session'
            initial = _command(['status', session])
            _command(['next', session])
            _command(['step', session])
            if runtime.attempts or initial['trials_recorded']:
                raise RuntimeError('Read-only operations launched work')
            for _ in range(33):
                status = _command(['status', session])
                if status.get('next') is None:
                    break
                if scenario == 'recovery' and not runtime.attempts:
                    reservation = _command(['reserve', session])
                    _command(['record', session], expected=2)
                    from scripts.investigation_smoke import _command as recipe_command
                    argv = reservation['argv']
                    recipe_command(argv[argv.index('run'):])
                    _command(['recover', session])
                else:
                    duplicate = scenario == 'duplicate-identity' and bool(runtime.attempts)
                    _command(['step', session, '--execute'], expected=2 if duplicate else 0)
                    if duplicate:
                        _command(['recover', session], expected=2)
                        break
            else:
                raise RuntimeError('Search exceeded its finite budget')
            status = _command(['status', session])
            if scenario in ('reduction', 'recovery') and (
                    not status['confirmed'] or status['best']['routes'] != 2):
                raise RuntimeError('SIMULATED reduction was not freshly confirmed at two routes')
            if scenario in ('inconclusive', 'failed-confirmation') and status['confirmed']:
                raise RuntimeError('Unmeasured work or failed confirmation was reported confirmed')
            if scenario == 'budget-exhausted' and len(runtime.attempts) != 3:
                raise RuntimeError('Budget failed to include original baseline and fresh confirmation')
            if scenario == 'unrelated-failure' and status['best']['routes'] != 8:
                raise RuntimeError('An unrelated assertion failure preserved the selected failure')
            if scenario == 'duplicate-identity' and status['state'] != 'recovery_required':
                raise RuntimeError('Duplicate identity did not preserve its charged reservation')
            _command(['report', session, '--output-dir', case / 'report'])
            report = case / 'report/minimization.json'
            _command(['verify', report])
            _command(['rebuild', report, '--output-dir', case / 'rebuilt'])
            _command(['verify', case / 'rebuilt/minimization.json'])
            shutil.copytree(case / 'report', case / 'relocated')
            _command(['verify', case / 'relocated/minimization.json'])
            changed = case / 'relocated/minimization.json'
            changed.write_text(changed.read_text().replace('observer.count', 'observer.changed', 1))
            _command(['verify', changed], expected=2)
            cases[scenario] = {'simulation': True, 'status': status,
                               'report': str(report), 'attempts': runtime.attempts,
                               'probe_commands': host.calls}
    summary = {'simulation': True, 'status': 'passed', 'cases': cases,
               'operations': ['plan', 'init', 'status', 'next', 'step', 'reserve',
                              'record', 'recover', 'report', 'verify', 'rebuild'],
               'scope': 'SIMULATED selected assertion only; no real daemon or performance verdict.'}
    _write(output / 'smoke.json', summary)
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
    parser.add_argument('--output', required=True, help='new absolute directory outside the engine checkout')
    args = parser.parse_args(argv)
    try:
        summary = run_smoke(args.output)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f'minimization smoke: {exc}', file=sys.stderr)
        return 2
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
