"""Frozen serial comparison sequencing, stop boundaries and public commands."""
import copy
import json
import shutil
from pathlib import Path

import pytest

import recipes
from recipe_comparison import make_comparison_plan, run_comparison, validate_comparison_plan
from recipe_targets import supplied_target
from test_recipe_investigation import package, BASE, FIX


@pytest.fixture
def recipe():
    return recipes.read_document(Path(__file__).parents[1] / 'examples/recipes/synthetic-ipv4.recipe.json')


def plan_for(recipe, **kwargs):
    return make_comparison_plan(recipe,
        baseline_target=supplied_target(recipe, BASE, instrumentation='optimized'),
        candidate_target=supplied_target(recipe, FIX, instrumentation='debug'),
        repetitions=kwargs.pop('repetitions', 3), **kwargs)


def test_alternating_repeats_pair_and_preserves_round_identity(recipe):
    plan = plan_for(recipe)
    assert [item['role'] for item in plan['sequence']] == ['baseline', 'candidate', 'candidate', 'baseline', 'baseline', 'candidate']
    assert [item['id'] for item in plan['sequence']] == ['r001-baseline', 'r001-candidate', 'r002-candidate', 'r002-baseline', 'r003-baseline', 'r003-candidate']
    assert plan_for(recipe, repetitions=4)['sequence'][:6] == plan['sequence']
    before = copy.deepcopy(plan)
    validate_comparison_plan(plan)
    assert plan == before


def test_shuffle_is_reconstructible_and_has_every_role_per_round(recipe):
    first = plan_for(recipe, order='shuffle', seed=43)
    assert [item['id'] for item in first['sequence']] == [
        'r001-candidate', 'r001-baseline', 'r002-baseline', 'r002-candidate',
        'r003-baseline', 'r003-candidate']
    assert first == plan_for(recipe, order='shuffle', seed=43)
    for pair in range(1, 4):
        assert {x['role'] for x in first['sequence'] if x['pair'] == pair} == {'baseline', 'candidate'}
    changed = copy.deepcopy(first)
    changed['sequence'].reverse()
    with pytest.raises(recipes.ContractError, match='sequence'):
        validate_comparison_plan(changed)


@pytest.mark.parametrize('options', [dict(repetitions=0), dict(repetitions=True), dict(repetitions=101),
    dict(order='shuffle'), dict(seed=3), dict(timeout=0), dict(timeout=float('nan')), dict(timeout=10**400),
    dict(diagnostics='profile'), dict(order='unsupported')])
def test_invalid_plans_refuse_before_any_probe(recipe, options):
    with pytest.raises(recipes.ContractError):
        plan_for(recipe, **options)


def test_precheck_both_targets_before_creating_anything(recipe, tmp_path):
    calls = []
    def check(document, **kwargs):
        calls.append(kwargs['target']['image'])
        return {'status': 'checks_passed' if len(calls) == 1 else 'refused'}
    result = run_comparison(plan_for(recipe), workdir=tmp_path / 'work', results_dir=tmp_path / 'results',
        check=check, run=lambda *a, **k: pytest.fail('runtime started'))
    assert calls == [BASE, FIX]
    assert result['exit_code'] == 2
    assert not list(tmp_path.iterdir())


def runtime(tmp_path, *, statuses=None, corrupt=False):
    calls = []
    def execute(document, **kwargs):
        calls.append(kwargs)
        source = package(tmp_path / f'fixture-{len(calls)}', document, kwargs['target']['image'],
                         status=(statuses or {}).get(len(calls), 'completed'), outcome='inconclusive')
        shutil.copytree(source.parent, kwargs['results_dir'])
        manifest = recipes.read_document(Path(kwargs['results_dir']) / 'result.json')
        if corrupt:
            (Path(kwargs['results_dir']) / 'work/runtime.json').write_text('tampered')
        return manifest
    return calls, execute


def test_each_attempt_serial_unique_and_plan_ledger_preserved(recipe, tmp_path):
    calls, execute = runtime(tmp_path)
    plan = plan_for(recipe)
    result = run_comparison(plan, workdir=tmp_path / 'work', results_dir=tmp_path / 'results',
        run=execute, check=lambda *a, **k: {'status': 'checks_passed'})
    assert result['exit_code'] == 0
    assert len(calls) == 6
    assert len({str(x['workdir']) for x in calls}) == 6
    assert [x['target'] for x in calls] == [plan['targets'][x['role']] for x in plan['sequence']]
    assert recipes.read_document(tmp_path / 'results/comparison-plan.json') == plan
    ledger = recipes.read_document(tmp_path / 'results/attempts.json')
    assert all(x['status'] == 'completed' and x['result'] for x in ledger)
    from recipe_comparison_report import verify_comparison_report
    assert verify_comparison_report(result['report'])['valid']


@pytest.mark.parametrize('status,exit_code', [('experiment_failed', 4), ('harness_failed', 3),
    ('inconclusive', 5), ('interrupted', 130)])
def test_stops_on_first_noncompletion_without_retry_and_retains_never_run(recipe, tmp_path, status, exit_code):
    calls, execute = runtime(tmp_path, statuses={2: status})
    result = run_comparison(plan_for(recipe), workdir=tmp_path / 'work', results_dir=tmp_path / 'results',
        run=execute, check=lambda *a, **k: {'status': 'checks_passed'})
    assert result['exit_code'] == exit_code
    assert len(calls) == 2
    ledger = recipes.read_document(tmp_path / 'results/attempts.json')
    assert ledger[1]['status'] == status and ledger[1]['result']
    assert all(x['status'] == 'not_run' and x['result'] is None for x in ledger[2:])


def test_unverified_package_stops_and_preserves_original_without_packaging_it(recipe, tmp_path):
    calls, execute = runtime(tmp_path, corrupt=True)
    result = run_comparison(plan_for(recipe), workdir=tmp_path / 'work', results_dir=tmp_path / 'results',
        run=execute, check=lambda *a, **k: {'status': 'checks_passed'})
    assert result['exit_code'] == 3 and len(calls) == 1
    ledger = recipes.read_document(tmp_path / 'results/attempts.json')
    assert ledger[0]['status'] == 'harness_failed' and ledger[0]['result'] is None
    assert (tmp_path / 'results/r001-baseline/result.json').is_file()


def test_comparison_plan_cli_is_offline_and_preserves_existing_output(recipe, tmp_path, capsys):
    recipe_path = tmp_path / 'recipe.json'
    recipe_path.write_text(json.dumps(recipe))
    targets = []
    for image, label in [(BASE, 'baseline'), (FIX, 'candidate')]:
        path = tmp_path / (label + '.json')
        path.write_text(json.dumps(supplied_target(recipe, image)))
        targets.append(path)
    output = tmp_path / 'plan.json'
    args = ['comparison-plan', str(recipe_path), '--baseline-target', str(targets[0]),
            '--candidate-target', str(targets[1]), '--repetitions', '2', '--output', str(output)]
    assert recipes.main(args) == 0
    assert len(recipes.read_document(output)['sequence']) == 4
    original = output.read_bytes()
    assert recipes.main(args) == 2
    assert output.read_bytes() == original


def test_assertion_export_cli_selects_explicit_capability_subset(recipe, tmp_path, capsys):
    path = tmp_path / 'recipe.json'
    path.write_text(json.dumps(recipe))
    assert recipes.main(['assertions-export', str(path), '--capability', 'observer_route_count']) == 0
    spec = json.loads(capsys.readouterr().out)
    assert [item['capability'] for item in spec['assertions']] == ['observer_route_count']
    assert recipes.main(['assertions-export', str(path), '--capability', 'observer_route_count',
                         '--capability', 'observer_route_count']) == 2
