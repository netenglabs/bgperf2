"""Real local Git, inert source: the real-case preparer cannot execute source."""
import json
import socket

import pytest

import recipe_targets
import recipes
from scripts import prepare_real_bird_case as case
from test_bird_alias_source import source


def test_case_prepares_full_public_contracts_but_excludes_search_and_runtime(source, tmp_path, monkeypatch):
    root, revisions = source
    monkeypatch.setattr(case, 'GOOD', revisions[0])
    monkeypatch.setattr(case, 'BAD', revisions[1])
    def forbidden(*args, **kwargs):
        pytest.fail('Preparation attempted a runtime or network operation')
    monkeypatch.setattr(socket.socket, '__init__', forbidden)
    monkeypatch.setattr(recipe_targets, 'build_target', forbidden)
    monkeypatch.setattr(recipe_targets.runtime, 'run_command', forbidden)
    monkeypatch.setattr(recipe_targets.runtime, 'check_recipe', forbidden)
    output = tmp_path / 'case'
    verification = case.prepare(root, output)
    assert verification['source_range']['valid'] and verification['handoff']['valid']
    assert verification['runtime_destinations_absent']
    scope = json.loads((output / 'execution-scope.json').read_text())
    graph = json.loads((output / 'handoff/commands.json').read_text())
    recipe = recipes.read_document(output / 'recipe.json')
    assert recipe['resolved']['neighbors'] == 1 and recipe['resolved']['prefixes_per_peer'] == 100
    assert recipe['reproduction']['expected_outcome'] == 'experiment_completed'
    assert scope['source_builds'] == 2 and scope['workers'] == 3
    assert scope['build_worker_seconds_ceiling'] == 2760
    assert scope['bisection_workers'] == scope['comparison_workers'] == scope['retries'] == 0
    assert all('bisection' not in step['id'] for step in scope['steps'])
    assert all('bisection' in name for name in scope['excluded_handoff_steps'])
    assert any(step['id'] == 'step_bisection' for step in graph['steps'])
    selected = {step['id']: step for step in scope['steps']}
    exported = selected['export_assertions']['argv']
    assert exported.count('--capability') == 4 and 'observed_role_health' not in exported
    assert selected['assert_baseline']['argv'][-1] == str(output / 'results/investigation/baseline/result.json')
    assert selected['verify_rebuilt']['argv'][-1] == str(output / 'results/investigation-rebuilt/investigation.json')
    for name in ('builds', 'work', 'results', 'unused-search'):
        assert not (output / name).exists()
    mapping = recipes.read_document(output / 'packaging/packaging.json')
    assert mapping['source_signatures']['before'] == mapping['source_signatures']['after']
    assert (output / 'CASE.md').read_text().count('```sh') == len(scope['steps'])
    # Rehashing/relabeling selected commands cannot widen this approval scope.
    changed = json.loads((output / 'execution-scope.json').read_text())
    changed['workers'] = 7
    (output / 'execution-scope.json').write_text(json.dumps(changed))
    with pytest.raises(recipes.ContractError, match='execution scope'):
        case.verify(output)
    (output / 'execution-scope.json').write_text(json.dumps(scope))
    changed = json.loads(json.dumps(scope))
    changed['steps'][0]['argv'][-1] = '9999'
    (output / 'execution-scope.json').write_text(json.dumps(changed))
    with pytest.raises(recipes.ContractError, match='execution scope'):
        case.verify(output)
    (output / 'execution-scope.json').write_text(json.dumps(scope))
    prose = (output / 'CASE.md').read_text()
    (output / 'CASE.md').write_text(prose.replace('2760', '9999'))
    with pytest.raises(recipes.ContractError, match='runbook differs'):
        case.verify(output)
    (output / 'CASE.md').write_text(prose)
    assert case.verify(output)['valid']
    # Model an independently valid replacement handoff. Inner verification
    # alone cannot bind its runtime recipe/range to this selected case.
    original_load = case.handoff._load
    receipt = case.handoff.verify_handoff(output / 'handoff/handoff.json')
    alternate = json.loads(json.dumps(recipe))
    alternate['reproduction']['question'] = 'Another valid functional question'
    recipes.validate_recipe(alternate)
    with monkeypatch.context() as patch:
        patch.setattr(case.handoff, 'verify_handoff', lambda path: receipt)
        patch.setattr(case.handoff, '_load', lambda path:
            alternate if path == output / 'handoff/inputs/recipe.json' else original_load(path))
        with pytest.raises(recipes.ContractError, match='selected runtime recipe'):
            case.verify(output)
    alternate_manifest = original_load(output / 'handoff/handoff.json')
    alternate_manifest['input_bindings']['source_range']['path'] = str(tmp_path / 'other/source-range.json')
    with monkeypatch.context() as patch:
        patch.setattr(case.handoff, 'verify_handoff', lambda path: receipt)
        patch.setattr(case.handoff, '_load', lambda path:
            alternate_manifest if path == output / 'handoff/handoff.json' else original_load(path))
        with pytest.raises(recipes.ContractError, match='selected handoff source range'):
            case.verify(output)
    # Existing case evidence must survive an accidental second preparation.
    before = (output / 'verification.json').read_bytes()
    with pytest.raises(FileExistsError):
        case.prepare(root, output)
    assert (output / 'verification.json').read_bytes() == before


def test_case_refuses_output_inside_maintainer_source_before_mutation(source):
    root, _ = source
    with pytest.raises(recipes.ContractError, match='outside source'):
        case.prepare(root, root / 'case')
    assert not (root / 'case').exists()
