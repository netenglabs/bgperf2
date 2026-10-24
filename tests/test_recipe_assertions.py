"""Offline correctness predicates use actual lifecycle shapes and sealed bytes."""
import copy
import json
from pathlib import Path

import pytest

import recipes
from measurements import EventKind, EventPhase, LifecycleEvent
from recipe_assertions import default_assertions, evaluate_assertions, validate_assertions
from recipe_results import write_result_package

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def recipe():
    return recipes.read_document(ROOT / 'examples/recipes/synthetic-ipv4.recipe.json')


def evidence(recipe):
    sessions = recipe['resolved']['neighbors']
    total = sessions * recipe['resolved']['prefixes_per_peer']
    counters = {'sessions': sessions, 'sessions_measured': sessions,
                'expected_prefixes': total, 'offered_prefixes': total}
    producer = 'bgperf_recipe_fixture_bgperf_bird_tester0'
    events = [
        LifecycleEvent(EventKind.BENCH_CLOCK_STARTED, 10, 'controller', EventPhase.SETUP),
        LifecycleEvent(EventKind.TESTER_SESSION_READY, 11, producer, EventPhase.SETUP, counters),
        LifecycleEvent(EventKind.TESTER_FIRST_UPDATE, 11, producer, EventPhase.INJECTION, counters),
        LifecycleEvent(EventKind.TESTER_COMPLETE, 12, producer, EventPhase.INJECTION, counters),
        LifecycleEvent(EventKind.CONVERGENCE_CONFIRMED, 14, 'bgperf_recipe_fixture_bgperf_monitor',
                       EventPhase.ASSURANCE, {'accepted_prefixes': total}),
    ]
    return {'raw-events.json': {'events': [event.to_dict() for event in events],
                                'source': 'existing lifecycle events before final collectors'},
            'execution-budget.json': {'schema': 'bgperf2/execution-budget/v1alpha1', 'scope': 'worker',
                                      'timeout_seconds': 120, 'elapsed_seconds': 5,
                                      'completed_within_budget': True},
            'runtime.json': {'status': 'completed'},
            'diagnostics.json': {'schema': 'bgperf2/diagnostics/v1alpha1',
                                 'containers': [{'role': role, 'state': {'Running': True,
                                    'OOMKilled': False, 'Error': ''}}
                                    for role in ('target', 'generator', 'observer')]}}


def package(tmp_path, recipe, files=None, status='completed'):
    work = tmp_path / 'source'
    work.mkdir()
    for name, document in (evidence(recipe) if files is None else files).items():
        (work / name).write_text(json.dumps(document))
    destination = tmp_path / 'result'
    write_result_package(recipe, results_dir=destination, workdir=work,
                         attempt_id='bgperf_recipe_fixture', status=status, reason='controlled fixture')
    return destination / 'result.json'


def evaluate(tmp_path, recipe, files=None, status='completed', spec=None):
    return evaluate_assertions(spec or default_assertions(recipe), recipe,
                               package(tmp_path, recipe, files, status))


def by_capability(result):
    return {item['capability']: item for item in result['assertions']}


def test_export_round_trip_preserves_bound_expectations(recipe):
    spec = json.loads(json.dumps(default_assertions(recipe)))
    assert validate_assertions(spec, recipe) == spec
    assert spec['recipe_sha256'] == recipes.recipe_sha256(recipe)
    assert len(spec['assertions']) == 5


@pytest.mark.parametrize('mutation', ['capability', 'expected', 'deadline', 'field', 'digest', 'duplicate', 'empty'])
def test_strict_spec_refuses_unsupported_or_tampered_contract(recipe, mutation):
    spec = default_assertions(recipe)
    if mutation == 'capability':
        spec['assertions'][0]['capability'] = 'route_attribute_correctness'
    elif mutation == 'expected':
        spec['assertions'][2]['expected'] = 99
    elif mutation == 'deadline':
        spec['assertions'][0]['deadline'] = {'sleep_seconds': 10}
    elif mutation == 'field':
        spec['assertions'][0]['action'] = 'reload-policy'
    elif mutation == 'digest':
        spec['recipe_sha256'] = 'a' * 64
    elif mutation == 'duplicate':
        spec['assertions'].append(copy.deepcopy(spec['assertions'][0]))
    else:
        spec['assertions'] = []
    with pytest.raises(recipes.ContractError):
        validate_assertions(spec, recipe)


def test_full_existing_synthetic_evidence_passes_with_named_hashed_witnesses(tmp_path, recipe):
    result = evaluate(tmp_path, recipe)
    assert result['outcome'] == 'passed'
    assert all(item['status'] == 'passed' for item in result['assertions'])
    assert all(item['evidence'] for item in result['assertions'])
    assert all(len(witness['sha256']) == 64 for item in result['assertions'] for witness in item['evidence'])
    assert result['worker_deadline']['satisfied'] is True


def test_exact_count_is_independent_of_existing_99_percent_completion(tmp_path, recipe):
    files = evidence(recipe)
    files['raw-events.json']['events'][-1]['counters']['accepted_prefixes'] = 99
    result = evaluate(tmp_path, recipe, files)
    assertions = by_capability(result)
    assert result['outcome'] == 'failed'
    assert assertions['observer_route_count']['observed'] == 99
    assert assertions['observer_route_count']['status'] == 'failed'
    assert assertions['experiment_completion']['status'] == 'passed'
    assert 'attributes are unmeasured' in assertions['observer_route_count']['reason']


def test_impossible_event_span_cannot_attest_deadline_bound_witness(tmp_path, recipe):
    files = evidence(recipe)
    files['raw-events.json']['events'][-1]['monotonic_s'] = 1_000_000_000
    result = evaluate(tmp_path, recipe, files)
    answers = by_capability(result)
    assert result['outcome'] == 'inconclusive'
    for capability in ('session_establishment', 'injection_completion', 'observer_route_count'):
        assert answers[capability]['status'] == 'unmeasured'
        assert answers[capability]['observed'] is None
        assert 'exceeds recorded worker elapsed' in answers[capability]['reason']
    assert answers['observed_role_health']['status'] == 'passed'


def test_missing_artifacts_remain_null_with_reasons(tmp_path, recipe):
    result = evaluate(tmp_path, recipe, {})
    assert result['outcome'] == 'inconclusive'
    assert all(item['status'] == 'unmeasured' and item['observed'] is None
               and item['reason'] for item in result['assertions'])
    assert result['worker_deadline']['timeout_seconds'] is None


@pytest.mark.parametrize('change', ['absent', 'false', 'infinite', 'boolean', 'elapsed_exceeded', 'null', 'negative'])
def test_deadline_absence_or_failure_cannot_attest_bounded_success(tmp_path, recipe, change):
    files = evidence(recipe)
    budget = files['execution-budget.json']
    if change == 'absent':
        del files['execution-budget.json']
    elif change == 'false':
        budget['completed_within_budget'] = False
    elif change == 'infinite':
        budget['timeout_seconds'] = float('inf')
    elif change == 'boolean':
        budget['timeout_seconds'] = True
    elif change == 'elapsed_exceeded':
        budget['elapsed_seconds'] = 121
    elif change == 'null':
        budget['completed_within_budget'] = None
    else:
        budget['elapsed_seconds'] = -1
    result = evaluate(tmp_path, recipe, files)
    assert result['outcome'] == 'inconclusive'
    for item in result['assertions']:
        assert item['status'] == ('passed' if item['capability'] == 'observed_role_health' else 'unmeasured')


def test_health_counterexample_survives_missing_deadline_and_harness_failure(tmp_path, recipe):
    files = evidence(recipe)
    del files['execution-budget.json']
    files['diagnostics.json']['containers'][0]['state']['Running'] = False
    files['runtime.json'] = {'status': 'harness_failed', 'experiment_status_before_collection': 'completed'}
    result = evaluate(tmp_path, recipe, files, status='harness_failed')
    assert result['outcome'] == 'failed'
    assert by_capability(result)['observed_role_health']['status'] == 'failed'


@pytest.mark.parametrize('change', ['missing', 'duplicate', 'malformed', 'unknown_role', 'oom_unknown'])
def test_partial_or_malformed_health_is_unmeasured(tmp_path, recipe, change):
    files = evidence(recipe)
    containers = files['diagnostics.json']['containers']
    if change == 'missing':
        containers.pop()
    elif change == 'duplicate':
        containers.append(copy.deepcopy(containers[0]))
    elif change == 'malformed':
        containers[0]['state'] = []
    elif change == 'unknown_role':
        containers[0]['role'] = {}
    else:
        containers[0]['state']['OOMKilled'] = None
    assertion = by_capability(evaluate(tmp_path, recipe, files))['observed_role_health']
    assert assertion['status'] == 'unmeasured'
    assert assertion['observed'] is None


@pytest.mark.parametrize('change', ['duplicate', 'negative', 'bool_counter', 'inverted', 'no_origin', 'completion_without_start'])
def test_bad_event_witnesses_are_retained_but_not_interpreted(tmp_path, recipe, change):
    files = evidence(recipe)
    events = files['raw-events.json']['events']
    if change == 'duplicate':
        events.append(copy.deepcopy(events[-1]))
    elif change == 'negative':
        events[-1]['counters']['accepted_prefixes'] = -1
    elif change == 'bool_counter':
        events[-1]['counters']['accepted_prefixes'] = True
    elif change == 'inverted':
        events[3]['monotonic_s'] = 10.5
    elif change == 'no_origin':
        events.pop(0)
    else:
        events.pop(2)
    result = by_capability(evaluate(tmp_path, recipe, files))
    assert result['observer_route_count']['status'] == 'unmeasured'
    assert result['observer_route_count']['observed'] is None
    assert result['experiment_completion']['status'] == 'passed'


def test_missing_session_events_are_not_experiment_failure(tmp_path, recipe):
    files = evidence(recipe)
    files['raw-events.json']['events'] = [item for item in files['raw-events.json']['events']
                                         if item['event'] != 'tester_session_ready']
    result = by_capability(evaluate(tmp_path, recipe, files))
    assert result['session_establishment']['status'] == 'unmeasured'
    assert result['session_establishment']['observed'] is None


def test_explicit_engine_failure_is_separate_from_other_missing_evidence(tmp_path, recipe):
    result = evaluate(tmp_path, recipe, {'runtime.json': {'status': 'experiment_failed'}}, status='experiment_failed')
    assert result['outcome'] == 'failed'
    assert by_capability(result)['experiment_completion']['observed'] == 'experiment_failed'
    assert by_capability(result)['observer_route_count']['observed'] is None


@pytest.mark.parametrize('change', ['bytes', 'symlink', 'unlisted'])
def test_unverified_or_unsafe_artifacts_are_refused_before_reading(tmp_path, recipe, change):
    path = package(tmp_path, recipe)
    artifact = path.parent / 'work/raw-events.json'
    if change == 'bytes':
        artifact.write_text('{}')
    elif change == 'symlink':
        artifact.unlink()
        artifact.symlink_to(tmp_path / 'source/raw-events.json')
    else:
        (path.parent / 'extra.json').write_text('{}')
    with pytest.raises(recipes.ContractError):
        evaluate_assertions(default_assertions(recipe), recipe, path)


def test_result_recipe_binding_checked_even_when_package_itself_verifies(tmp_path, recipe):
    path = package(tmp_path, recipe)
    other = copy.deepcopy(recipe)
    other['reproduction']['question'] = 'Another declared question'
    with pytest.raises(recipes.ContractError, match='another recipe'):
        evaluate_assertions(default_assertions(other), other, path)


def test_single_final_engine_event_artifact_can_supply_fallback(tmp_path, recipe):
    files = evidence(recipe)
    files['synthetic.events.json'] = files.pop('raw-events.json')
    files['synthetic.events.json'].update(schema='bgperf2/measurement-events/v1alpha1', status='converged')
    assert evaluate(tmp_path, recipe, files)['outcome'] == 'passed'
