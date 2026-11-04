"""Pure minimization contracts: modeled outcomes are never runtime evidence."""
import copy
import hashlib
import json

import pytest

import recipes
import recipe_minimization as minimization
from recipe_assertions import default_assertions


def original_recipe(*, peers=8, routes=16, complex_source=False):
    target = {'name': 'bird', 'version': '3.3.2', 'threads': 2,
              'image': 'sha256:' + '1' * 64, 'label': 'fixed target'}
    test = {'name': 'modeled-reduction', 'neighbors': [peers],
            'prefixes': [peers * routes if complex_source else routes],
            'filter_test': [None], 'targets': [target], 'monitor': 'sink',
            'pin': 'target=0,monitor=1,testers=2-3'}
    if complex_source:
        test.update(prefix_scope='total', repetitions=3, order='shuffle', seed=91)
    cells = recipes.construct_batch_cells(test, recipes.expand_target_versions(test['targets']),
        repetitions=test.get('repetitions', 1), prefix_resolver=recipes.resolve_prefix_scope,
        path_diversity=1, receivers=0, churn_prefixes=0, churn_bursts=0,
        policy_reload_blocks=0, pin=recipes._recipe_pin(test['pin']), monitor='sink')
    cell = cells[-1]
    key = recipes.batch_cell_key(recipes.batch_cell_id(test['name'], cell))
    roles = {role: {'adapter': adapter, 'image': 'sha256:' + digit * 64}
             for role, adapter, digit in [('target', 'bird', '1'),
                                         ('generator', 'bird', '2'),
                                         ('observer', 'sink', '3')]}
    return recipes._recipe(json.dumps({'tests': [test]}), test['name'], key,
                           'a' * 40, roles, 'MODELED count mismatch', 'experiment_completed')


def plan_for(recipe=None, **kwargs):
    return minimization.make_plan(recipe or original_recipe(), assertion='observer.count', **kwargs)


def append_trial(plan, trials, classification):
    request = copy.deepcopy(minimization.summarize(plan, trials)['next'])
    assert request is not None
    document = minimization.candidate_recipe(plan['recipe'], request['peers'], request['routes'])
    row = next(item for item in default_assertions(document, include_prefixes=True)['assertions']
               if item['name'] == plan['assertion'])
    row.update(status={'preserved': 'failed', 'not_preserved': 'passed',
                       'inconclusive': 'unmeasured'}[classification],
               observed=None, evidence=[], reason='MODELED outcome; no worker')
    assessment = {'classification': classification, 'attempt_id': f'MODELED-{len(trials)}',
                  'recipe_sha256': request['recipe_sha256'],
                  'result_sha256': hashlib.sha256(f'MODELED-{len(trials)}'.encode()).hexdigest(),
                  'observed_images': {role: identity['image']
                                      for role, identity in document['roles'].items()},
                  'assertion': row, 'reason': 'MODELED outcome; no worker'}
    trials.append({'request': request, 'assessment': assessment})
    return request


def test_projection_recomputes_source_scope_identity_and_expectations_without_aliases():
    original = original_recipe(complex_source=True)
    before = copy.deepcopy(original)
    candidate = minimization.candidate_recipe(original, 3, 5)
    recipes.validate_recipe(candidate)
    assert original == before
    assert candidate['resolved']['neighbors'] == 3
    assert candidate['resolved']['prefixes_per_peer'] == 5
    assert candidate['resolved']['prefix_scope'] == 'per-peer'
    source = recipes._source_tests(candidate['source']['text'])
    assert len(source) == 1
    assert source[0]['neighbors'] == [3]
    assert source[0]['prefixes'] == [5]
    assert source[0]['prefix_scope'] == 'per-peer'
    assert source[0]['targets'] == [original['source']['raw_target']]
    for key in ('roles', 'engine', 'resources', 'reproduction', 'completion', 'inputs'):
        assert candidate[key] == original[key]
    assert candidate['resolved']['pin'] == original['resolved']['pin']
    assert candidate['resolved']['target'] == original['resolved']['target']
    assert candidate['legacy'] != original['legacy']
    assert recipes.recipe_sha256(candidate) != recipes.recipe_sha256(original)
    counts = {row['name']: row['expected'] for row in default_assertions(candidate)['assertions']}
    assert counts['sessions.ready'] == 3
    assert counts['observer.count'] == 15
    candidate['roles']['target']['image'] = 'sha256:' + 'f' * 64
    candidate['source']['raw_target']['threads'] = 999
    assert original == before


def test_same_shape_preserves_exact_original_source_and_selection_but_returns_copy():
    original = original_recipe(complex_source=True)
    result = minimization.candidate_recipe(original, 8, 16)
    assert result == original
    assert result is not original
    result['source']['raw_target']['threads'] = 999
    assert original['source']['raw_target']['threads'] == 2


@pytest.mark.parametrize('peers,routes', [(True, 2), (2, False), (0, 2), (2, 0),
                                        (9, 2), (2, 17), (2.0, 2)])
def test_candidate_refuses_invalid_or_expanding_coordinates(peers, routes):
    with pytest.raises(recipes.ContractError):
        minimization.candidate_recipe(original_recipe(), peers, routes)


@pytest.mark.parametrize('changes', [
    {'max_trials': True}, {'max_trials': 2}, {'max_trials': 257},
    {'timeout': True}, {'timeout': float('nan')}, {'timeout': float('inf')},
    {'timeout': 0}, {'timeout': 3601}, {'dimensions': ()},
    {'dimensions': ('peers', 'peers')}, {'dimensions': ('attributes',)},
    {'min_peers': True}, {'min_peers': 9}, {'min_routes': 0}, {'min_routes': 17},
])
def test_plan_refuses_unsupported_bounds_and_dimensions(changes):
    with pytest.raises(recipes.ContractError):
        plan_for(**changes)


def test_plan_freezes_original_and_refuses_unknown_contract_fields():
    original = original_recipe()
    plan = plan_for(original)
    assert minimization.validate_plan(plan) == plan
    original['roles']['observer']['image'] = 'sha256:' + 'f' * 64
    assert plan['recipe']['roles']['observer']['image'] != original['roles']['observer']['image']
    for key, value in [('unexpected', True), ('strategy', 'binary-search'),
                       ('projection', 'arbitrary-subsets')]:
        changed = copy.deepcopy(plan)
        changed[key] = value
        with pytest.raises(recipes.ContractError):
            minimization.validate_plan(changed)


def test_plan_refuses_new_oracles():
    with pytest.raises(recipes.ContractError):
        minimization.make_plan(original_recipe(), assertion='attributes.correct')


@pytest.mark.parametrize('dimensions', [None, 'peers', {'peers'}, {'peers': True}])
def test_dimensions_are_explicit_bounded_sequences(dimensions):
    with pytest.raises(recipes.ContractError):
        plan_for(dimensions=dimensions)


def test_unbounded_dimension_iterator_is_refused_without_consuming_it():
    def forbidden_iterator():
        pytest.fail('Untrusted iterator was consumed before shape validation')
        yield 'peers'

    with pytest.raises(recipes.ContractError):
        plan_for(dimensions=forbidden_iterator())


def test_baseline_is_original_and_missing_failure_stops_without_candidates():
    plan = plan_for(original_recipe(complex_source=True))
    initial = minimization.summarize(plan, [])
    assert initial['next']['phase'] == 'baseline'
    assert initial['next']['recipe_sha256'] == recipes.recipe_sha256(plan['recipe'])
    for classification, state in [('not_preserved', 'original_not_reproduced'),
                                  ('inconclusive', 'baseline_inconclusive')]:
        trials = []
        append_trial(plan, trials, classification)
        result = minimization.summarize(plan, trials)
        assert result['state'] == state
        assert result['next'] is None
        assert result['confirmed'] is False


def test_passing_minimum_does_not_prune_larger_nonmonotone_failure():
    plan = plan_for(dimensions=('peers',), max_trials=8)
    trials = []
    append_trial(plan, trials, 'preserved')
    first = append_trial(plan, trials, 'not_preserved')
    assert first['peers'] == 1
    middle = append_trial(plan, trials, 'preserved')
    assert middle['peers'] == 4
    summary = minimization.summarize(plan, trials)
    assert summary['best'] == {'peers': 4, 'routes': 16}
    assert summary['next']['peers'] == 2
    assert summary['smaller_observed'] is True
    assert summary['confirmed'] is False


def test_three_trial_budget_reserves_fresh_confirmation_after_one_search():
    plan = plan_for(max_trials=3)
    trials = []
    baseline = append_trial(plan, trials, 'preserved')
    search = append_trial(plan, trials, 'preserved')
    confirmation = minimization.summarize(plan, trials)['next']
    assert [baseline['phase'], search['phase'], confirmation['phase']] == [
        'baseline', 'search', 'confirmation']
    assert confirmation['recipe_sha256'] == search['recipe_sha256']
    assert confirmation['index'] != search['index']
    append_trial(plan, trials, 'preserved')
    final = minimization.summarize(plan, trials)
    assert final['state'] == 'complete'
    assert final['confirmed'] is True
    assert final['conclusion'] == 'confirmed_smaller'
    assert final['trials_recorded'] == 3
    assert final['search_budget_exhausted'] is True
    assert final['next'] is None


@pytest.mark.parametrize('classification,state', [
    ('not_preserved', 'confirmation_not_preserved'),
    ('inconclusive', 'confirmation_inconclusive')])
def test_discovery_does_not_survive_unsuccessful_confirmation(classification, state):
    plan = plan_for(max_trials=3)
    trials = []
    append_trial(plan, trials, 'preserved')
    append_trial(plan, trials, 'preserved')
    append_trial(plan, trials, classification)
    final = minimization.summarize(plan, trials)
    assert final['state'] == state
    assert final['confirmed'] is False
    assert final['smaller_observed'] is True
    assert final['next'] is None


def test_search_unmeasured_stops_before_another_worker():
    plan = plan_for()
    trials = []
    append_trial(plan, trials, 'preserved')
    append_trial(plan, trials, 'inconclusive')
    final = minimization.summarize(plan, trials)
    assert final['state'] == 'search_inconclusive'
    assert final['next'] is None
    assert final['confirmed'] is False


def test_no_available_reduction_still_requires_fresh_original_confirmation():
    plan = plan_for(original_recipe(peers=1, routes=1))
    trials = []
    append_trial(plan, trials, 'preserved')
    assert minimization.summarize(plan, trials)['next']['phase'] == 'confirmation'
    append_trial(plan, trials, 'preserved')
    final = minimization.summarize(plan, trials)
    assert final['conclusion'] == 'no_reduction'
    assert final['confirmed'] is True
    assert final['smaller_observed'] is False


@pytest.mark.parametrize('mutation', ['request', 'recipe', 'duplicate_attempt', 'extra',
                                     'status', 'assertion_name', 'expectation',
                                     'deadline', 'capability', 'missing_row_field',
                                     'extra_row_field'])
def test_history_rejects_unexpected_requests_reused_attempts_and_tampering(mutation):
    plan = plan_for(max_trials=3)
    trials = []
    append_trial(plan, trials, 'preserved')
    append_trial(plan, trials, 'preserved')
    if mutation == 'request':
        trials[1]['request']['routes'] += 1
    elif mutation == 'recipe':
        trials[1]['assessment']['recipe_sha256'] = 'f' * 64
    elif mutation == 'duplicate_attempt':
        trials[1]['assessment']['attempt_id'] = trials[0]['assessment']['attempt_id']
    elif mutation == 'extra':
        trials[1]['assessment']['trusted'] = True
    elif mutation == 'status':
        trials[1]['assessment']['assertion']['status'] = 'passed'
    elif mutation == 'assertion_name':
        trials[1]['assessment']['assertion']['name'] = 'roles.healthy'
    elif mutation == 'expectation':
        trials[1]['assessment']['assertion']['expected'] += 1
    elif mutation == 'deadline':
        trials[1]['assessment']['assertion']['deadline']['kind'] = 'pre_cleanup_snapshot'
    elif mutation == 'capability':
        trials[1]['assessment']['assertion']['capability'] = 'experiment_completion'
    elif mutation == 'missing_row_field':
        del trials[1]['assessment']['assertion']['observed']
    else:
        trials[1]['assessment']['assertion']['trusted'] = True
    with pytest.raises(recipes.ContractError):
        minimization.summarize(plan, trials)


def test_dimension_order_is_explicit_and_a_single_selected_axis_keeps_other_fixed():
    plan = plan_for(dimensions=('routes',))
    trials = []
    append_trial(plan, trials, 'preserved')
    attempted = []
    while minimization.summarize(plan, trials)['next'] is not None:
        request = minimization.summarize(plan, trials)['next']
        assert request['peers'] == 8
        if request['phase'] == 'search':
            attempted.append(request['routes'])
        append_trial(plan, trials, 'preserved' if request['phase'] == 'confirmation'
                     else 'not_preserved')
    assert attempted == [1, 8, 15]
    final = minimization.summarize(plan, trials)
    assert final['conclusion'] == 'no_reduction'
    assert final['search_budget_exhausted'] is False


def test_no_more_trials_accepted_after_terminal_baseline_outcome():
    plan = plan_for()
    trials = []
    append_trial(plan, trials, 'not_preserved')
    trials.append(copy.deepcopy(trials[0]))
    trials[-1]['assessment']['attempt_id'] = 'MODELED-extra'
    with pytest.raises(recipes.ContractError):
        minimization.summarize(plan, trials)


@pytest.mark.parametrize('role', ['target', 'generator', 'observer'])
def test_changed_observed_physical_image_cannot_retain_failure(role):
    plan = plan_for(max_trials=3)
    trials = []
    append_trial(plan, trials, 'preserved')
    append_trial(plan, trials, 'preserved')
    trials[1]['assessment']['observed_images'][role] = 'sha256:' + 'f' * 64
    with pytest.raises(recipes.ContractError):
        minimization.summarize(plan, trials)


@pytest.mark.parametrize('classification', ['preserved', 'not_preserved'])
def test_decisive_assessment_requires_observed_physical_image_for_every_role(classification):
    plan = plan_for()
    trials = []
    append_trial(plan, trials, classification)
    trials[0]['assessment']['observed_images']['generator'] = None
    with pytest.raises(recipes.ContractError):
        minimization.summarize(plan, trials)


def test_missing_observed_image_is_retained_as_inconclusive():
    plan = plan_for()
    trials = []
    append_trial(plan, trials, 'inconclusive')
    trials[0]['assessment']['observed_images']['observer'] = None
    assert minimization.summarize(plan, trials)['state'] == 'baseline_inconclusive'
