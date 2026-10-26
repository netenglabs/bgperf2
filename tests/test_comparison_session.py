"""Offline session lifecycle tests: no Docker, real worker or host sampling."""
import json
import shutil
import hashlib

import pytest

import recipes
from comparison_pressure import assess
from comparison_session import start_session, step_session, record_review, validate_review
from test_recipe_comparison_report import plan, package, replace_artifact


POLICY = dict(sample_seconds=1, max_gap_seconds=2, busy_percent=75,
              cpu_psi_percent=20, consecutive_intervals=2, min_memory_bytes=1024)


def sample(at, busy=0, idle=0, psi=0, memory=9999):
    return dict(monotonic_seconds=at, stat=f'cpu {busy} 0 0 {idle} 0 0 0 0\n',
                meminfo=f'MemAvailable: {memory} kB\n', cpu_pressure=f'some avg10={psi} avg60=0 total=0\n')


def check(*args, **kwargs):
    return {'status': 'checks_passed'}


def runner(tmp_path, *, fail=False, missing_cleanup=False, pressure_samples=None):
    def run(plan, entry, *, results_dir, session, **kwargs):
        source = package(tmp_path / 'fake' / entry['id'], plan, entry)
        runtime = {'status': 'completed', 'cleanup_errors': []}
        if missing_cleanup:
            runtime.pop('cleanup_errors')
        replace_artifact(source, 'work/runtime.json', runtime)
        if fail:
            budget = json.loads((source.parent / 'work/execution-budget.json').read_text())
            budget['completed_within_budget'] = False
            replace_artifact(source, 'work/execution-budget.json', budget)
        shutil.copytree(source.parent, results_dir)
        if pressure_samples is not None:
            (session / 'pressure' / (entry['id'] + '.json')).write_text(json.dumps(pressure_samples))
        return {'exit_code': 0}
    return run


def start(tmp_path, plan, **options):
    work, results = tmp_path / 'work', tmp_path / 'session'
    assert start_session(plan, workdir=work, results_dir=results, check=check, **options)['status'] == 'ready'
    return results


def review(results, tmp_path, decision='accepted'):
    evidence = tmp_path / 'review.txt'
    evidence.write_text('SIMULATED external review: package, assertions, operational screen and cleanup inspected.')
    return record_review(results, reviewer='SIMULATED reviewer', evidence=evidence, decision=decision)


def test_one_busy_core_is_allowed_but_sustained_selected_pressure_latches():
    assert assess([sample(0), sample(1, 1, 31, 99)], POLICY)['outcome'] == 'passed'
    assert assess([sample(0), sample(1, 99, 1, 30), sample(2, 198, 2, 30),
                   sample(3, 198, 102)], POLICY)['outcome'] == 'blocked'
    with pytest.raises(recipes.ContractError):
        assess([sample(0), sample(3, 1, 31)], POLICY)
    assert assess([sample(0, memory=0)], POLICY)['outcome'] == 'blocked'


def test_refused_setup_creates_no_destinations(tmp_path, plan):
    result = start_session(plan, workdir=tmp_path / 'work', results_dir=tmp_path / 'session',
                           check=lambda *a, **k: {'status': 'refused'})
    assert result['status'] == 'setup_refused'
    assert not (tmp_path / 'work').exists() and not (tmp_path / 'session').exists()


def test_serial_review_gates_and_final_receipt(tmp_path, plan):
    results = start(tmp_path, plan)
    assert (results / 'supplements').is_dir()
    run = runner(tmp_path)
    assert step_session(results, execute=run, check=check)['status'] == 'first_review'
    with pytest.raises(recipes.ContractError, match='first_review'):
        step_session(results, execute=run, check=check)
    review(results, tmp_path)
    for _ in plan['sequence'][1:]:
        outcome = step_session(results, execute=run, check=check)
    assert outcome['status'] == 'final_review'
    receipt = review(results, tmp_path)
    assert receipt['status'] == 'complete'
    _, report = validate_review(receipt['receipt'], final=True)
    assert report['performance']['policy'] == 'disabled'
    with pytest.raises(recipes.ContractError, match='complete'):
        step_session(results, execute=run, check=check)
    (results / 'reviews/final.txt').write_text('changed')
    with pytest.raises(recipes.ContractError, match='evidence changed'):
        validate_review(receipt['receipt'], final=True)


@pytest.mark.parametrize('options', [{'fail': True}, {'missing_cleanup': True}])
def test_gate_failure_preserves_completed_package_and_never_runs_rest(tmp_path, plan, options):
    results = start(tmp_path, plan)
    outcome = step_session(results, execute=runner(tmp_path, **options), check=check)
    assert outcome['status'] == 'stopped' and outcome['exit_code'] != 0
    ledger = json.loads((results / 'attempts.json').read_text())
    assert ledger[0]['status'] == 'completed'
    assert all(x['status'] == 'not_run' for x in ledger[1:])
    with pytest.raises(recipes.ContractError, match='stopped'):
        step_session(results, check=check)


def test_recorded_pressure_rechecked_before_next_worker(tmp_path, plan):
    results = start(tmp_path, plan, pressure=POLICY)
    samples = [sample(0), sample(1, 1, 31)]
    step_session(results, execute=runner(tmp_path, pressure_samples=samples), check=check)
    review(results, tmp_path)
    first = plan['sequence'][0]['id']
    (results / 'pressure' / (first + '.json')).write_text(json.dumps([sample(0, memory=0)]))
    with pytest.raises(recipes.ContractError, match='pressure'):
        step_session(results, execute=lambda *a, **k: pytest.fail('worker started'), check=check)
    assert json.loads((results / 'session.json').read_text())['stage'] == 'stopped'


def test_prelaunch_refusal_does_not_consume_attempt(tmp_path, plan):
    results = start(tmp_path, plan)
    outcome = step_session(results, execute=lambda *a, **k: dict(started=False, exit_code=2, reason='screen unavailable'), check=check)
    assert outcome['status'] == 'stopped'
    assert all(x['status'] == 'not_run' for x in json.loads((results / 'attempts.json').read_text()))


def test_controller_termination_waits_for_cleanup(tmp_path, plan, monkeypatch):
    import comparison_session as session
    results = start(tmp_path, plan, pressure=POLICY)
    events = []
    class Process:
        def wait(self, timeout=None):
            if 'terminate' not in events:
                raise session.subprocess.TimeoutExpired('SIMULATED', timeout)
            events.append('waited')
            return 143
        def terminate(self):
            events.append('terminate')
        def poll(self):
            return 143 if 'waited' in events else None
    monkeypatch.setattr(session.subprocess, 'Popen', lambda *a, **k: Process())
    samples = iter([sample(0), sample(1, 99, 1, 30), sample(2, 198, 2, 30)])
    outcome = session._execute(plan, plan['sequence'][0], workdir=tmp_path / 'worker',
        results_dir=tmp_path / 'attempt', session=results, pressure=POLICY, sample=lambda: next(samples))
    assert outcome['exit_code'] == 143 and events == ['terminate', 'waited']


def test_observer_supplement_is_synchronous_and_cannot_be_recreated(tmp_path, plan):
    from test_observer_timing import log_text
    plan['assertions']['assertions'] = plan['assertions']['assertions'][:4]
    results = start(tmp_path, plan, observer_window=True)
    base = runner(tmp_path)
    def execute(plan, entry, **kwargs):
        outcome = base(plan, entry, **kwargs)
        path = kwargs['results_dir'] / 'result.json'
        result = json.loads(path.read_text())
        for relative, data in {
            'work/owned/monitor/sink.log': log_text(),
            'work/artifacts/bird_mon-sink.events.json': json.dumps({'instrument': {'sink_log': {
                'processes': 1, 'sessions_established': 1, 'sessions_lost': 0,
                'malformed_lines': 0, 'refused_messages': 0, 'kept_messages': 0, 'accepted': 100}}})}.items():
            file = path.parent / relative
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(data)
            result['artifacts'].append(dict(path=relative, availability='present', reason=None,
                kind='log', sha256=hashlib.sha256(file.read_bytes()).hexdigest()))
        path.write_text(json.dumps(result))
        return outcome
    assert step_session(results, execute=execute, check=check)['status'] == 'first_review'
    supplement = results / 'supplements' / (plan['sequence'][0]['id'] + '.json')
    assert json.loads(supplement.read_text())['resolution_gate']['outcome'] == 'passed'
    review(results, tmp_path)
    supplement.unlink()
    with pytest.raises(recipes.ContractError, match='supplement is missing'):
        step_session(results, execute=lambda *a, **k: pytest.fail('worker started'), check=check)


def test_prior_series_requires_final_acceptance_and_unique_original_attempts(tmp_path, plan):
    first = start(tmp_path / 'first', plan)
    run = runner(tmp_path / 'first')
    step_session(first, execute=run, check=check)
    receipt = review(first, tmp_path)
    with pytest.raises(recipes.ContractError, match='accepted final'):
        start(tmp_path / 'early', plan, prior_review=receipt['receipt'])
    for _ in plan['sequence'][1:]:
        step_session(first, execute=run, check=check)
    receipt = review(first, tmp_path)
    second = start(tmp_path / 'second', plan, prior_review=receipt['receipt'])
    outcome = step_session(second, execute=runner(tmp_path / 'second'), check=check)
    assert outcome['status'] == 'stopped' and 'identity' in outcome['reason']


def test_cli_dispatches_explicit_session_controls(tmp_path, plan, monkeypatch):
    import comparison_session
    selected = []
    def started(document, **options):
        selected.append((document, options))
        return {'exit_code': 0}
    monkeypatch.setattr(comparison_session, 'start_session', started)
    document = tmp_path / 'plan.json'
    document.write_text(json.dumps(plan))
    pressure = tmp_path / 'pressure.json'
    pressure.write_text(json.dumps(POLICY))
    assert recipes.main(['comparison-start', str(document), '--workdir', str(tmp_path / 'work'),
        '--results-dir', str(tmp_path / 'results'), '--observer-window',
        '--pressure-policy', str(pressure), '--prior-review', '/absolute/final.json']) == 0
    assert selected[0][1]['pressure'] == POLICY
    assert selected[0][1]['prior_review'] == '/absolute/final.json'
    assert selected[0][1]['observer_window'] is True
    monkeypatch.setattr(comparison_session, 'step_session', lambda path: {'exit_code': 5})
    assert recipes.main(['comparison-step', str(tmp_path)]) == 5
    monkeypatch.setattr(comparison_session, 'record_review', lambda path, **kw: {'exit_code': 0})
    assert recipes.main(['comparison-review', str(tmp_path), '--reviewer', 'SIMULATED',
                         '--evidence', str(document), '--decision', 'accepted']) == 0


@pytest.mark.parametrize('structured', [True, False])
def test_public_controller_setup_race_preserves_never_run_accounting(tmp_path, plan, monkeypatch, structured):
    import comparison_session
    results = start(tmp_path, plan)
    class Refused:
        def __init__(self, *args, stdout, **kwargs):
            # A child writes directly to the fd, independently of parent's buffers.
            import os
            os.write(stdout.fileno(), (json.dumps({'status': 'setup_refused', 'exit_code': 2})
                                     if structured else 'unexpected failure').encode())
        def wait(self, **kwargs):
            return 2
        def poll(self):
            return 2
    monkeypatch.setattr(comparison_session.subprocess, 'Popen', Refused)
    outcome = step_session(results, check=check)
    assert outcome['status'] == 'stopped'
    state = json.loads((results / 'session.json').read_text())
    ledger = json.loads((results / 'attempts.json').read_text())
    assert state['next_index'] == (0 if structured else 1)
    assert ledger[0]['status'] == ('not_run' if structured else 'harness_failed')
