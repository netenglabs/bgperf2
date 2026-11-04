"""Supplied FRR recipe identities and early unsupported-capability refusals."""
import copy
import json
from pathlib import Path

import pytest

import recipes
import recipe_targets as targets

ROOT = Path(__file__).resolve().parents[1]


def frr_recipe(*, target=None, neighbors=2, prefixes=8, pin=None):
    test = dict(name='frr-functional', neighbors=[neighbors], prefixes=[prefixes],
                filter_test=[None], monitor='sink', targets=[target or {'name': 'frr_c'}])
    if pin:
        test['pin'] = pin
    cells = recipes.construct_batch_cells(test, recipes.expand_target_versions(test['targets']),
        repetitions=1, prefix_resolver=recipes.resolve_prefix_scope, path_diversity=1,
        receivers=0, churn_prefixes=0, churn_bursts=0, policy_reload_blocks=0,
        pin=recipes._recipe_pin(pin) if pin else None, monitor='sink')
    key = recipes.batch_cell_key(recipes.batch_cell_id(test['name'], cells[0]))
    roles = {role: {'adapter': adapter, 'image': 'sha256:' + digit * 64}
             for role, adapter, digit in [('target', 'frr_c', '1'), ('generator', 'bird', '2'), ('observer', 'sink', '3')]}
    return recipes._recipe(json.dumps({'tests': [test]}), test['name'], key,
                           'a' * 40, roles, 'FRR functional synthetic workload', 'experiment_completed')


def test_frr_recipe_roundtrip_preserves_generator_observer_and_cpu_layout():
    recipe = frr_recipe(target={'name': 'frr_c', 'version': '10.7', 'label': 'FRR supplied'},
                        pin='target=0,monitor=1,testers=2-3')
    assert recipes.validate_recipe(copy.deepcopy(recipe)) == recipe
    assert recipe['roles']['target']['adapter'] == 'frr_c'
    assert recipe['resolved']['target']['name'] == 'frr_c'
    assert recipe['source']['raw_target'] == {'name': 'frr_c', 'version': '10.7', 'label': 'FRR supplied'}
    assert recipe['roles']['generator']['adapter'] == 'bird'
    assert recipe['roles']['observer']['adapter'] == 'sink'
    assert recipe['resolved']['pin'] == 'target=0,monitor=1,testers=2-3'


def test_cli_export_infers_frr_from_source_without_new_adapter_flag(tmp_path, capsys):
    document = frr_recipe()
    batch = tmp_path / 'source.yaml'
    batch.write_text(document['source']['text'])
    args = ['export', '--batch', str(batch), '--test', document['selection']['test'],
            '--cell', document['selection']['cell_key'], '--engine-revision', 'a' * 40,
            '--question', document['reproduction']['question']]
    for role, identity in document['roles'].items():
        args += ['--' + role + '-image', identity['image']]
    assert recipes.main(args) == 0
    assert json.loads(capsys.readouterr().out) == document


def test_supplied_frr_override_changes_only_selected_target_image():
    recipe = frr_recipe()
    before = copy.deepcopy(recipe)
    target = targets.supplied_target(recipe, 'sha256:' + '4' * 64)
    assert target['adapter'] == 'frr_c'
    assert target['provenance']['kind'] == 'supplied_image'
    assert target['provenance']['source'] is None and target['provenance']['build'] is None
    roles = targets.effective_roles(recipe, target)
    assert roles['target']['image'] == target['image']
    assert roles['generator'] == recipe['roles']['generator']
    assert roles['observer'] == recipe['roles']['observer']
    assert recipe == before
    target['adapter'] = 'bird'
    with pytest.raises(recipes.ContractError, match='adapter'):
        targets.validate_target(target, recipe)


@pytest.mark.parametrize('role,bad', [('target', 'bird'), ('generator', 'frr_c'), ('observer', 'bird')])
def test_adapter_mismatch_is_not_silently_reinterpreted(role, bad):
    recipe = frr_recipe()
    recipe['roles'][role]['adapter'] = bad
    with pytest.raises(recipes.ContractError):
        recipes.validate_recipe(recipe)


@pytest.mark.parametrize('threads', [1, 2])
def test_frr_thread_control_refused_before_runtime(threads):
    with pytest.raises(recipes.ContractError, match='thread'):
        frr_recipe(target={'name': 'frr_c', 'threads': threads})


def test_frr_crash_question_refused_without_claiming_bird_exit_witness():
    recipe = frr_recipe()
    recipe['reproduction']['expected_outcome'] = 'target_crash'
    with pytest.raises(recipes.ContractError, match='FRR target_crash'):
        recipes.validate_recipe(recipe)


def test_frr_crash_search_refused_before_source_or_host_probe(monkeypatch):
    import recipe_source_range as ranges
    import recipe_bisection as bisection
    monkeypatch.setattr(targets, '_git', lambda *a, **k: pytest.fail('Git probed'))
    with pytest.raises(recipes.ContractError, match='FRR target_crash'):
        ranges.prepare_range(frr_recipe(), source_root='/must-not-open', good='a' * 40,
            bad='b' * 40, toolchain_image='sha256:' + 'a' * 64,
            runtime_image='sha256:' + 'b' * 64, output_dir='/must-not-create',
            predicate='target_crash')
    def forbidden_iterator():
        pytest.fail('source plans iterated')
        yield
    with pytest.raises(recipes.ContractError, match='FRR target_crash'):
        bisection.make_plan(frr_recipe(), forbidden_iterator(), forbidden_iterator(),
                            predicate='target_crash', max_trials=4)


def test_frr_minimization_rebuilds_valid_candidate_and_dynamic_assertion():
    import recipe_minimization as minimize
    from recipe_assertions import default_assertions
    original = frr_recipe(neighbors=4, prefixes=16)
    candidate = minimize.candidate_recipe(original, 2, 8)
    assert recipes.validate_recipe(candidate) == candidate
    assert candidate['roles'] == original['roles']
    assert candidate['resolved']['target']['name'] == 'frr_c'
    count = next(row for row in default_assertions(candidate)['assertions'] if row['name'] == 'observer.count')
    assert count['expected'] == 16


def test_bird_export_keeps_checked_in_recipe_bytes_and_identity(tmp_path):
    fixture = recipes.read_document(ROOT / 'examples/recipes/synthetic-ipv4.recipe.json')
    path = tmp_path / 'source.yaml'
    path.write_bytes(fixture['source']['text'].encode())
    assert recipes.export_recipe(path, fixture['selection']['test'], fixture['selection']['cell_key'],
        engine_revision=fixture['engine']['revision'], roles=fixture['roles'],
        question=fixture['reproduction']['question']) == fixture


def test_mixed_target_source_uses_distinct_daemon_names():
    source = {'tests': [dict(name='mixed', neighbors=[1], prefixes=[8], filter_test=[None],
                            targets=[{'name': 'bird'}, {'name': 'frr_c'}])]}
    assert len(recipes._source_tests(json.dumps(source))[0]['targets']) == 2
