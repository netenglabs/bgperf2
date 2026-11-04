# Copyright (C) 2026 bgperf2 contributors. Apache-2.0.
"""Public CLI boundaries and guarded modeled minimization workflow."""
import json
from pathlib import Path
from unittest.mock import patch

import pytest

import minimization_cli


ROOT = Path(__file__).resolve().parent.parent


def test_parser_defaults_require_explicit_execution():
    args = minimization_cli.parser().parse_args(['step', '/session'])
    assert args.execute is False
    args = minimization_cli.parser().parse_args(['plan', '/recipe', '--assertion',
                                               'observer.count', '-o', '/plan'])
    assert (args.dimension, args.max_trials, args.timeout) == (None, 20, 120)


@pytest.mark.parametrize('extra', [['--max-trials', 'true'], ['--dimension', 'prefixes'],
                                  ['--min-peers', '1.5'], ['--execute']])
def test_parser_rejects_mistyped_plan_fields(extra):
    with pytest.raises(SystemExit) as error:
        minimization_cli.parser().parse_args(['plan', '/recipe', '--assertion',
                                             'observer.count', '-o', '/plan', *extra])
    assert error.value.code == 2


def test_cli_plan_errors_are_machine_failure_and_preserve_existing_output(tmp_path, capsys):
    recipe = ROOT / 'examples/recipes/synthetic-ipv4.recipe.json'
    output = tmp_path / 'plan.json'
    assert minimization_cli.main(['plan', str(recipe), '--assertion', 'observer.count',
                                  '--timeout', 'nan', '-o', str(output)]) == 2
    assert not output.exists()
    output.write_text('retained evidence\n')
    assert minimization_cli.main(['plan', str(recipe), '--assertion', 'observer.count',
                                  '-o', str(output)]) == 2
    assert output.read_text() == 'retained evidence\n'


def test_step_default_dispatch_never_requests_execution(capsys):
    import recipe_minimization_session as sessions
    with patch.object(sessions, 'step_session', return_value={'phase': 'baseline'}) as step:
        assert minimization_cli.main(['step', '/session']) == 0
    step.assert_called_once_with('/session', execute=False)
    assert json.loads(capsys.readouterr().out)['phase'] == 'baseline'


def test_known_pre_execution_refusal_is_nonzero_with_inspectable_json(capsys):
    import recipe_minimization_session as sessions
    with patch.object(sessions, 'step_session', return_value={
            'state': 'operational_refused', 'confirmed': False,
            'recovery_instruction': 'Fix prerequisites and initialize a fresh session.'}):
        assert minimization_cli.main(['step', '/session', '--execute']) == 2
    status = json.loads(capsys.readouterr().out)
    assert status['state'] == 'operational_refused' and status['confirmed'] is False


def test_public_cli_reduces_both_dimensions_and_confirms_fresh_original(tmp_path, monkeypatch, capsys):
    import recipe_run
    from test_minimization_core import original_recipe
    from test_minimization_session import fake_runner
    recipe = tmp_path / 'recipe.json'
    recipe.write_text(json.dumps(original_recipe(peers=4, routes=8)))
    plan, root = tmp_path / 'plan.json', tmp_path / 'session'
    run, calls = fake_runner(tmp_path)
    monkeypatch.setattr(recipe_run, 'run_recipe', run)

    def command(*arguments):
        assert minimization_cli.main(list(map(str, arguments))) == 0
        return json.loads(capsys.readouterr().out)

    command('plan', recipe, '--assertion', 'experiment.complete', '--max-trials', '6', '-o', plan)
    command('init', plan, '--workdir', tmp_path / 'work', '--results-dir', root)
    status = command('status', root)
    for _ in range(6):
        if status['next'] is None:
            break
        status = command('step', root, '--execute')
    assert status['conclusion'] == 'confirmed_smaller'
    assert status['best'] == {'peers': 1, 'routes': 1}
    assert len(calls) == 4
    assert calls[0]['resolved']['neighbors'] == 4
    assert calls[1]['resolved']['neighbors'] == 1
    records = [json.loads(path.read_text()) for path in sorted((root / 'trials').iterdir())]
    assert records[-1]['request']['phase'] == 'confirmation'
    assert len({row['assessment']['attempt_id'] for row in records}) == 4


def test_guarded_public_walkthrough(tmp_path):
    from scripts.minimization_smoke import run_smoke
    summary = run_smoke(tmp_path / 'walkthrough')
    assert summary['simulation'] is True
    assert summary['status'] == 'passed'
    reduction = summary['cases']['reduction']
    assert reduction['status']['confirmed'] is True
    assert reduction['status']['best']['routes'] == 2
    assert len({attempt['attempt_id'] for attempt in reduction['attempts']}) == len(reduction['attempts'])
    assert summary['cases']['failed-confirmation']['status']['confirmed'] is False
    assert summary['cases']['inconclusive']['status']['confirmed'] is False
