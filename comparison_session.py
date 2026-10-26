# Copyright (C) 2026 bgperf2 contributors. Apache-2.0.
"""Staged public comparison execution with explicit operational and review gates."""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading

import recipes
from recipe_comparison import validate_comparison_plan, _destinations
from recipe_comparison_report import _safe_path, _validate_entries, build_comparison_report, verify_comparison_report
from recipe_investigation import _load, _read_attempt
from recipe_results import verify_result_package, _regular_bytes, _regular_file

SCHEMA = 'bgperf2/comparison-session/v1alpha1'
REVIEW_SCHEMA = 'bgperf2/comparison-review/v1alpha1'
ROOT = Path(__file__).parent


class GateBlocked(recipes.ContractError):
    def __init__(self, message, code=5):
        self.code = code
        super().__init__(message)


def _digest(value):
    return hashlib.sha256(recipes.canonical_json(value).encode()).hexdigest()


def _atomic(path, value):
    _safe_path(path)
    fd, name = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n')
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


@contextmanager
def _locked(results):
    results = _safe_path(results)
    fd = os.open(results / 'session.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise recipes.ContractError('Another command holds the comparison session lock') from exc
        yield results
    finally:
        os.close(fd)


def validate_review(path, *, final=False):
    path = _safe_path(path)
    receipt = recipes.read_document(path)
    recipes._keys(receipt, ('schema', 'phase', 'decision', 'reviewer', 'plan_sha256',
                            'report', 'report_sha256', 'evidence', 'evidence_sha256', 'assessments'), where='review receipt')
    recipes._choice(receipt['schema'], (REVIEW_SCHEMA,), 'review schema')
    recipes._choice(receipt['phase'], ('first', 'final'), 'review phase')
    recipes._choice(receipt['decision'], ('accepted', 'rejected'), 'review decision')
    recipes._text(receipt['reviewer'], 'reviewer')
    report_path = _safe_path(receipt['report'])
    evidence = _safe_path(receipt['evidence'])
    if hashlib.sha256(_regular_bytes(report_path.parent, report_path.name)).hexdigest() != receipt['report_sha256']:
        raise recipes.ContractError('Reviewed comparison report changed')
    if hashlib.sha256(_regular_bytes(evidence.parent, evidence.name)).hexdigest() != receipt['evidence_sha256']:
        raise recipes.ContractError('Original review evidence changed')
    if not isinstance(receipt['assessments'], list) or not receipt['assessments']:
        raise recipes.ContractError('Missing reviewed assessment bindings')
    for item in receipt['assessments']:
        recipes._keys(item, ('path', 'sha256'), where='reviewed assessment')
        source = _safe_path(item['path'])
        if hashlib.sha256(_regular_bytes(source.parent, source.name)).hexdigest() != item['sha256']:
            raise recipes.ContractError('Reviewed operational assessment changed')
    verify_comparison_report(report_path)
    report = recipes.read_document(report_path)
    recipes._same(receipt['plan_sha256'], _digest(report['plan']), 'review plan binding')
    if final:
        if receipt['phase'] != 'final' or receipt['decision'] != 'accepted':
            raise recipes.ContractError('An accepted final review is required')
        if any(x['status'] != 'completed' or x['assertions']['outcome'] != 'passed' for x in report['attempts']):
            raise recipes.ContractError('Prior reviewed series is incomplete or has unpassed assertions')
    return receipt, report


def start_session(plan, *, workdir, results_dir, observer_window=False, pressure=None,
                  prior_review=None, check=None):
    validate_comparison_plan(plan)
    if type(observer_window) is not bool:
        raise recipes.ContractError('observer_window must be boolean')
    if observer_window:
        from observer_timing import CAPABILITIES
        if {x['capability'] for x in plan['assertions']['assertions']} != CAPABILITIES:
            raise recipes.ContractError('Observer window requires exactly the four worker-budget assertions')
    if pressure is not None:
        from comparison_pressure import validate_policy
        validate_policy(pressure)
    prior = None
    if prior_review is not None:
        receipt, previous = validate_review(prior_review, final=True)
        recipes._same(previous['plan']['recipe'], plan['recipe'], 'prior series recipe')
        recipes._same(previous['plan']['targets']['baseline'], plan['targets']['baseline'], 'prior series baseline')
        prior = {'path': str(_safe_path(prior_review)), 'sha256': _digest(receipt)}
    work, results = _destinations(workdir, results_dir)
    from recipe_preflight import check_recipe
    checks = []
    for role in ('baseline', 'candidate'):
        entry = next(x for x in plan['sequence'] if x['role'] == role)
        checks.append((check or check_recipe)(plan['recipe'], workdir=work / entry['id'],
                        results_dir=results / 'attempts' / entry['id'], target=plan['targets'][role]))
    if any(x.get('status') != 'checks_passed' for x in checks):
        return {'status': 'setup_refused', 'exit_code': 2, 'prerequisites': checks}
    work.mkdir(mode=0o700, parents=True)
    results.mkdir(mode=0o700, parents=True)
    for name in ('attempts', 'supplements', 'pressure', 'reports', 'reviews', 'commands'):
        (results / name).mkdir(mode=0o700)
    policy = {'schema': SCHEMA + '/policy', 'plan_sha256': _digest(plan),
              'require_assertions': True, 'observer_window': observer_window, 'pressure': pressure,
              'prior_review': prior}
    state = {'schema': SCHEMA, 'plan_sha256': _digest(plan), 'policy_sha256': _digest(policy),
             'workdir': str(work), 'next_index': 0, 'stage': 'ready', 'checkpoint': None,
             'first_review': None, 'final_review': None, 'stop_reason': None}
    ledger = [{**x, 'result': None, 'status': 'not_run', 'reason': 'Planned attempt has not run.'}
              for x in plan['sequence']]
    for name, data in [('comparison-plan.json', plan), ('execution-policy.json', policy),
                       ('attempts.json', ledger), ('session.json', state), ('prerequisites.json', checks),
                       ('recipe.json', plan['recipe']), ('assertions.json', plan['assertions']),
                       ('target-baseline.json', plan['targets']['baseline']),
                       ('target-candidate.json', plan['targets']['candidate'])]:
        recipes._write_document(data, results / name)
    return {'status': 'ready', 'exit_code': 0, 'session': str(results / 'session.json')}


def _read_session(results):
    state, plan, policy, ledger = [_load(results, name) for name in
                                  ('session.json', 'comparison-plan.json', 'execution-policy.json', 'attempts.json')]
    for name in ('attempts', 'supplements', 'pressure', 'reports', 'reviews', 'commands'):
        if not _safe_path(results / name).is_dir():
            raise recipes.ContractError('Missing session output directory: ' + name)
    validate_comparison_plan(plan)
    recipes._keys(state, ('schema', 'plan_sha256', 'policy_sha256', 'workdir', 'next_index', 'stage',
                         'checkpoint', 'first_review', 'final_review', 'stop_reason'), where='session')
    recipes._choice(state['schema'], (SCHEMA,), 'session schema')
    recipes._choice(state['stage'], ('ready', 'running', 'first_review', 'final_review', 'complete', 'stopped'), 'session stage')
    recipes._same(state['plan_sha256'], _digest(plan), 'session plan binding')
    recipes._same(state['policy_sha256'], _digest(policy), 'session policy binding')
    recipes._keys(policy, ('schema', 'plan_sha256', 'require_assertions', 'observer_window', 'pressure', 'prior_review'), where='session policy')
    recipes._same(policy['schema'], SCHEMA + '/policy', 'policy schema')
    recipes._same(policy['plan_sha256'], _digest(plan), 'policy plan binding')
    for name, expected in [('recipe.json', plan['recipe']), ('assertions.json', plan['assertions']),
                           ('target-baseline.json', plan['targets']['baseline']),
                           ('target-candidate.json', plan['targets']['candidate'])]:
        recipes._same(_load(results, name), expected, name + ' binding')
    work = _safe_path(state['workdir'])
    if work == results or work in results.parents or results in work.parents or ROOT.resolve() in work.parents or work == ROOT.resolve():
        raise recipes.ContractError('Session workdir changed to an unsafe destination')
    if policy['require_assertions'] is not True or type(policy['observer_window']) is not bool:
        raise recipes.ContractError('Session assertion or observer policy changed')
    if policy['pressure'] is not None:
        from comparison_pressure import validate_policy
        validate_policy(policy['pressure'])
    _validate_entries(plan, ledger)
    recipes._integer(state['next_index'], 'next_index', 0)
    if state['next_index'] > len(ledger):
        raise recipes.ContractError('Session next_index exceeds sequence')
    if policy['prior_review'] is not None:
        previous, report = validate_review(policy['prior_review']['path'], final=True)
        recipes._same(_digest(previous), policy['prior_review']['sha256'], 'prior review binding')
        recipes._same(report['plan']['recipe'], plan['recipe'], 'prior recipe')
    return state, plan, policy, ledger


def _assess_attempt(results, plan, policy, entry, *, create_supplement=False):
    path = results / 'attempts' / entry['id'] / 'result.json'
    verify_result_package(path)
    evidence, recipe, result = _read_attempt(path, entry['role'], None)
    recipes._same(recipe, plan['recipe'], 'attempt recipe')
    recipes._same(evidence['target'], plan['targets'][entry['role']], 'attempt target')
    if result['status'] != 'completed':
        raise recipes.ContractError(f"Attempt status is {result['status']}")
    from recipe_assertions import evaluate_assertions
    assertions = evaluate_assertions(plan['assertions'], plan['recipe'], path)
    if assertions['outcome'] != 'passed' or assertions['worker_deadline']['timeout_seconds'] != plan['timeout']:
        raise GateBlocked('Correctness assertions or frozen worker budget did not pass', 4 if assertions['outcome'] == 'failed' else 5)
    runtime = _load(path.parent, 'work/runtime.json')
    if type(runtime.get('cleanup_errors')) is not list or runtime['cleanup_errors']:
        raise GateBlocked('Owned resource cleanup is missing or reported errors')
    if policy['observer_window']:
        from observer_timing import review_result
        observed = review_result(path, results / 'assertions.json')
        supplement = results / 'supplements' / (entry['id'] + '.json')
        if supplement.exists():
            recipes._same(recipes.read_document(supplement), observed, 'observer supplement')
        elif create_supplement:
            recipes._write_document(observed, supplement)
        else:
            raise GateBlocked('Original observer supplement is missing')
        if observed['resolution_gate']['outcome'] != 'passed':
            raise GateBlocked('Observer delivery-window resolution screen blocked')
    if policy['pressure'] is not None:
        from comparison_pressure import assess
        pressure = assess(json.loads(_regular_bytes(results, 'pressure/' + entry['id'] + '.json')), policy['pressure'])
        if pressure['outcome'] != 'passed':
            raise GateBlocked('Recorded host pressure blocks this attempt and its successors')
    return result


def _history(results, state, plan, policy, ledger):
    ids = set()
    if policy['prior_review'] is not None:
        _, previous = validate_review(policy['prior_review']['path'], final=True)
        ids.update(x['source_attempt_id'] for x in previous['attempts'])
    for entry in ledger[:state['next_index']]:
        if entry['status'] != 'completed' or entry['result'] != str(results / 'attempts' / entry['id'] / 'result.json'):
            raise recipes.ContractError('Earlier attempt is not a bound completed entry')
        result = _assess_attempt(results, plan, policy, entry)
        if result['attempt']['id'] in ids:
            raise recipes.ContractError('Original attempt ID reused within session')
        ids.add(result['attempt']['id'])
    if state['next_index']:
        checkpoint = _safe_path(state['checkpoint'])
        verify_comparison_report(checkpoint)
        report = recipes.read_document(checkpoint)
        recipes._same(report['plan'], plan, 'checkpoint plan')
        expected = {x['id']: x['source_attempt_id'] for x in report['attempts'] if x['status'] == 'completed'}
        for entry in ledger[:state['next_index']]:
            original = _load(results / 'attempts' / entry['id'], 'result.json')
            recipes._same(expected.get(entry['id']), original['attempt']['id'], 'checkpoint source attempt binding')
    if state['next_index'] > 1 or (state['next_index'] and state['stage'] == 'ready'):
        if not state['first_review']:
            raise recipes.ContractError('First-attempt review is required')
        receipt, first = validate_review(state['first_review'])
        if receipt['decision'] != 'accepted' or receipt['phase'] != 'first':
            raise recipes.ContractError('First-attempt review did not accept continuation')
        recipes._same(receipt['plan_sha256'], _digest(plan), 'first review plan binding')
        if receipt['report'] != str(results / 'reports/after-001/comparison.json'):
            raise recipes.ContractError('First review does not bind this session first checkpoint')
        recipes._same(first['attempts'][0]['source_attempt_id'],
                      _load(results / 'attempts' / ledger[0]['id'], 'result.json')['attempt']['id'],
                      'first reviewed original attempt')
    return ids


def _execute(plan, entry, *, workdir, results_dir, session, pressure, sample=None):
    """Run the owned public controller; graceful termination leaves its cleanup intact."""
    from comparison_pressure import assess, host_sample
    args = [sys.executable, str(ROOT / 'recipes.py'), 'run', str(session / 'recipe.json'),
            '--target', str(session / ('target-' + entry['role'] + '.json')),
            '--workdir', str(workdir), '--results-dir', str(results_dir),
            '--timeout', str(plan['timeout']), '--diagnostics', plan['diagnostics']]
    samples = []
    if pressure is not None:
        try:
            samples.append((sample or host_sample)())
            _atomic(session / 'pressure' / (entry['id'] + '.json'), samples)
            if assess(samples, pressure)['outcome'] != 'passed':
                return {'started': False, 'exit_code': 2, 'reason': 'Pre-launch pressure observation blocks execution'}
        except (OSError, ValueError) as exc:
            return {'started': False, 'exit_code': 2, 'reason': f'Pre-launch pressure unavailable: {exc}'}
    log = session / 'commands' / entry['id']
    recipes._write_document({'argv': args}, log.with_suffix('.json'))
    old_handler = None
    if threading.current_thread() is threading.main_thread() and signal.getsignal(signal.SIGTERM) == signal.SIG_DFL:
        def stop(signum, frame):
            raise SystemExit(128 + signum)
        old_handler = signal.signal(signal.SIGTERM, stop)
    process = None
    try:
        with log.with_suffix('.stdout').open('x') as stdout, log.with_suffix('.stderr').open('x') as stderr:
            process = subprocess.Popen(args, stdout=stdout, stderr=stderr, start_new_session=True)
            while True:
                try:
                    code = process.wait(timeout=pressure['sample_seconds'] if pressure else None)
                    finished = True
                except subprocess.TimeoutExpired:
                    finished = False
                if pressure is not None:
                    samples.append((sample or host_sample)())
                    _atomic(session / 'pressure' / (entry['id'] + '.json'), samples)
                    if assess(samples, pressure)['outcome'] != 'passed' and not finished:
                        process.terminate()
                        process.wait()  # Let the owned controller collect and clean; no retry.
                        return {'exit_code': 143, 'reason': 'Explicit operational pressure screen stopped the controller'}
                if finished:
                    if code == 2 and not os.path.lexists(workdir) and not os.path.lexists(results_dir):
                        # The public controller repeats preflight after our
                        # check. A changed lock/host may refuse before any worker.
                        with _regular_file(log.parent, log.with_suffix('.stdout').name) as stream:
                            raw = stream.read(65537)
                        try:
                            outcome = json.loads(raw, object_pairs_hook=recipes._pairs,
                                                 parse_constant=recipes._nonfinite) if len(raw) <= 65536 else None
                        except (ValueError, UnicodeError):
                            outcome = None
                        if (isinstance(outcome, dict) and outcome.get('status') == 'setup_refused'
                                and type(outcome.get('exit_code')) is int and outcome['exit_code'] == 2):
                            return {'started': False, 'exit_code': 2,
                                    'reason': 'Public controller refused setup before worker; see preserved command stdout'}
                    return {'exit_code': code}
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            process.wait()
        if old_handler is not None:
            signal.signal(signal.SIGTERM, old_handler)


def step_session(results_dir, *, execute=None, check=None):
    with _locked(results_dir) as results:
        state, plan, policy, ledger = _read_session(results)
        if state['stage'] != 'ready':
            raise recipes.ContractError(f"Session is {state['stage']}; no worker may start")
        try:
            observed = _history(results, state, plan, policy, ledger)
        except (Exception, KeyboardInterrupt, SystemExit) as exc:
            state.update(stage='stopped', stop_reason=f'Between-attempt assessment failed: {exc}')
            _atomic(results / 'session.json', state)
            raise
        index = state['next_index']
        if index >= len(ledger):
            raise recipes.ContractError('The frozen sequence is exhausted')
        entry = ledger[index]
        from recipe_preflight import check_recipe
        try:
            prerequisite = (check or check_recipe)(plan['recipe'], workdir=Path(state['workdir']) / entry['id'],
                             results_dir=results / 'attempts' / entry['id'], target=plan['targets'][entry['role']])
        except (Exception, KeyboardInterrupt, SystemExit) as exc:
            state.update(stage='stopped', stop_reason=f'Prerequisite assessment failed: {exc}')
            _atomic(results / 'session.json', state)
            raise
        if prerequisite.get('status') != 'checks_passed':
            state.update(stage='stopped', stop_reason='Prerequisites refused before next worker')
            _atomic(results / 'session.json', state)
            recipes._write_document(prerequisite, results / ('prerequisite-stop-' + entry['id'] + '.json'))
            return {'status': 'stopped', 'exit_code': 2, 'reason': state['stop_reason']}
        state['stage'] = 'running'
        _atomic(results / 'session.json', state)
        code, reason = 0, None
        try:
            outcome = (execute or _execute)(plan, entry, workdir=Path(state['workdir']) / entry['id'],
                          results_dir=results / 'attempts' / entry['id'], session=results, pressure=policy['pressure'])
            if outcome.get('started') is False:
                state.update(stage='stopped', stop_reason=outcome.get('reason', 'Execution refused before worker'))
                entry['reason'] = 'Never run: ' + state['stop_reason']
                _atomic(results / 'attempts.json', ledger)
                _atomic(results / 'session.json', state)
                return {'status': 'stopped', 'exit_code': outcome['exit_code'], 'reason': state['stop_reason']}
            code = outcome['exit_code']
            if type(code) is not int:
                raise recipes.ContractError('Controller exit code must be an integer')
            if code != 0:
                raise recipes.ContractError(outcome.get('reason', f'Public recipe controller exited {code}'))
            result = _assess_attempt(results, plan, policy, entry, create_supplement=True)
            if result['attempt']['id'] in observed:
                raise recipes.ContractError('A runtime attempt identity cannot supply multiple entries')
        except (Exception, KeyboardInterrupt, SystemExit) as exc:
            code = (exc.code if isinstance(exc, SystemExit) and exc.code in (130, 143)
                    else 130 if isinstance(exc, KeyboardInterrupt) else code or getattr(exc, 'code', 3))
            reason = f'{type(exc).__name__}: {exc}; original work/package retained; no retry'
        path = results / 'attempts' / entry['id'] / 'result.json'
        try:
            if path.exists():
                verify_result_package(path)
                evidence, bound, result = _read_attempt(path, entry['role'], None)
                recipes._same(bound, plan['recipe'], 'attempt recipe')
                recipes._same(evidence['target'], plan['targets'][entry['role']], 'attempt target')
                entry.update(result=str(path), status=result['status'], reason=result.get('reason', 'Recorded original outcome'))
            else:
                entry.update(result=None, status='interrupted' if code in (130, 143) else 'harness_failed', reason=reason or 'Missing result package')
        except (OSError, ValueError) as exc:
            entry.update(result=None, status='harness_failed', reason=f'Original package withheld: {exc}')
            code, reason = code or 3, reason or str(exc)
        state['next_index'] += 1
        _atomic(results / 'attempts.json', ledger)
        try:
            checkpoint = results / 'reports' / f'after-{state["next_index"]:03d}'
            build_comparison_report(plan, ledger, checkpoint)
            state['checkpoint'] = str(checkpoint / 'comparison.json')
        except (OSError, ValueError) as exc:
            code, reason = code or 3, reason or f'Checkpoint failed: {exc}'
        state.update(stage=('stopped' if code else 'first_review' if index == 0 else
                            'final_review' if state['next_index'] == len(ledger) else 'ready'), stop_reason=reason)
        _atomic(results / 'session.json', state)
        return {'status': state['stage'], 'exit_code': code, 'reason': reason, 'checkpoint': state['checkpoint']}


def record_review(results_dir, *, reviewer, evidence, decision):
    with _locked(results_dir) as results:
        state, plan, policy, ledger = _read_session(results)
        if state['stage'] not in ('first_review', 'final_review'):
            raise recipes.ContractError('Session is not waiting for a review')
        recipes._text(reviewer, 'reviewer')
        recipes._choice(decision, ('accepted', 'rejected'), 'decision')
        _history(results, state, plan, policy, ledger)
        source = _safe_path(evidence)
        with _regular_file(source.parent, source.name) as stream:
            data = stream.read(1024 * 1024 + 1)
        if not data.strip() or len(data) > 1024 * 1024:
            raise recipes.ContractError('Provide nonempty review evidence of at most 1 MiB')
        phase = 'first' if state['stage'] == 'first_review' else 'final'
        destination = results / 'reviews' / (phase + '.txt')
        with destination.open('xb') as stream:
            stream.write(data)
        report = _safe_path(state['checkpoint'])
        assessments = [results / 'execution-policy.json']
        for entry in ledger[:state['next_index']]:
            if policy['observer_window']:
                assessments.append(results / 'supplements' / (entry['id'] + '.json'))
            if policy['pressure'] is not None:
                assessments.append(results / 'pressure' / (entry['id'] + '.json'))
        receipt = {'schema': REVIEW_SCHEMA, 'phase': phase, 'decision': decision, 'reviewer': reviewer,
                   'plan_sha256': _digest(plan), 'report': str(report),
                   'report_sha256': hashlib.sha256(_regular_bytes(report.parent, report.name)).hexdigest(),
                   'evidence': str(destination), 'evidence_sha256': hashlib.sha256(data).hexdigest(),
                   'assessments': [{'path': str(x), 'sha256': hashlib.sha256(_regular_bytes(x.parent, x.name)).hexdigest()}
                                   for x in assessments]}
        path = results / 'reviews' / (phase + '.json')
        recipes._write_document(receipt, path)
        state[phase + '_review'] = str(path)
        state['stage'] = 'stopped' if decision == 'rejected' else 'complete' if phase == 'final' else 'ready'
        if decision == 'rejected':
            state['stop_reason'] = 'External reviewer rejected continuation'
        _atomic(results / 'session.json', state)
        return {'status': state['stage'], 'exit_code': 0 if decision == 'accepted' else 5,
                'receipt': str(path), 'review_limit': 'Reviewer independence is an external attestation, not verified by this tool.'}
