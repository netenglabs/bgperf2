"""Verified search progress stays offline and never reconciles reserved work."""
import json
import subprocess

import pytest

import recipe_bisection as bisection
from test_recipe_bisection import fixture_plan, fake_backends


def session(tmp_path, **kwargs):
    plan = fixture_plan(tmp_path, **kwargs)
    path = tmp_path / 'session'
    bisection.initialize(plan, path)
    return path, plan


def files(path):
    # The existing session coordination lock may be created on first inspection.
    return {p.relative_to(path).as_posix(): p.read_bytes() for p in path.rglob('*')
            if p.is_file() and p.name != 'session.lock'}


def test_new_session_status_and_both_cli_formats_are_offline(tmp_path, monkeypatch, capsys):
    path, plan = session(tmp_path)
    before = files(path)

    def forbidden(*args, **kwargs):
        pytest.fail('Status invoked a build, worker or subprocess')

    monkeypatch.setattr(bisection, 'step', forbidden)
    monkeypatch.setattr(bisection, 'run_search', forbidden)
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    status = bisection.session_status(path)
    assert status['trials_recorded'] == status['trials_reserved'] == 0
    assert status['trials_remaining'] == status['max_trials'] == 32
    assert status['conclusion'] == bisection.request(plan, [])
    assert status['counts'] == dict(good=0, bad=0, skipped=0, ambiguous=0)
    assert bisection.main(['status', str(path)]) == 0
    text = capsys.readouterr().out
    assert 'State: trial_required' in text and '0/32 recorded' in text
    assert plan['candidates'][0]['revision'] in text and 'not started' in text
    assert bisection.main(['status', str(path), '--json']) == 0
    assert json.loads(capsys.readouterr().out) == status
    assert files(path) == before


@pytest.mark.parametrize('already_recorded', [False, True])
def test_status_retains_pending_markers_and_counts_reserved_budget(tmp_path, already_recorded):
    path, plan = session(tmp_path)
    selected = bisection.next_trial(path)
    if already_recorded:
        _, _, build, run = fake_backends(tmp_path, plan)
        bisection.step(path, build=build, run=run)
    bisection.write(path / 'pending.json', selected)
    before = files(path)
    status = bisection.session_status(path)
    assert status['conclusion']['state'] == 'recovery_required'
    assert status['pending'] == selected
    assert status['pending_already_recorded'] is already_recorded
    assert status['trials_reserved'] == int(not already_recorded)
    assert status['trials_remaining'] == 31
    assert status['trials_recorded'] == int(already_recorded)
    text = bisection.render_status(status)
    assert 'Reserved trial: 1' in text and 'Next trial:' not in text
    assert ('already recorded' in text) is already_recorded
    assert files(path) == before


def test_mismatched_pending_marker_is_refused_without_repair(tmp_path):
    path, _ = session(tmp_path)
    selected = bisection.next_trial(path)
    selected['revision'] = 'f' * 40
    bisection.write(path / 'pending.json', selected)
    before = files(path)
    with pytest.raises(bisection.recipes.ContractError, match='pending status'):
        bisection.session_status(path)
    assert files(path) == before


def test_boolean_trial_number_cannot_impersonate_a_recorded_reservation(tmp_path):
    path, plan = session(tmp_path)
    selected = bisection.next_trial(path)
    _, _, build, run = fake_backends(tmp_path, plan)
    bisection.step(path, build=build, run=run)
    selected['trial'] = True
    bisection.write(path / 'pending.json', selected)
    before = files(path)
    with pytest.raises(bisection.recipes.ContractError, match='pending status'):
        bisection.session_status(path)
    assert files(path) == before


@pytest.mark.parametrize('options,state', [({}, 'confirmed'), ({'skips': (4,)}, 'unresolved'),
    ({'unstable': True}, 'unresolved'), ({'ambiguous': (4,)}, 'trial_required')])
def test_status_reports_verified_boundary_and_nondecisive_trials(tmp_path, options, state):
    path, plan = session(tmp_path)
    _, _, build, run = fake_backends(tmp_path, plan, **options)
    bisection.run_search(path, build=build, run=run)
    before = files(path)
    status = bisection.session_status(path)
    assert status['conclusion']['state'] == state
    assert status['counts'] == {kind: sum(t['classification'] == kind for t in status['trials'])
                                for kind in ('good', 'bad', 'skipped', 'ambiguous')}
    text = bisection.render_status(status)
    if state == 'confirmed':
        assert 'Last observed good: ' + plan['candidates'][3]['revision'] in text
        assert 'First observed bad: ' + plan['candidates'][4]['revision'] in text
        assert [t['phase'] for t in status['trials'][-2:]] == ['confirm-good', 'confirm-bad']
        assert 'Failed assertions:' in text
    if options.get('skips'):
        assert status['counts']['skipped'] == 1
        assert len(status['conclusion']['possible_first_bad']) == 2
        assert any(t['evidence'].startswith('failures/') for t in status['trials'])
    if options.get('ambiguous'):
        assert status['counts']['ambiguous'] == 1
        assert status['trials'][-1]['experiment_status'] == 'harness_failed'
        assert 'not started' in text
    assert all((path / t['evidence']).is_file() for t in status['trials'])
    assert status['performance'] == dict(qualification='not_assessed', policy='disabled')
    assert files(path) == before


def test_exhausted_budget_is_not_presented_as_a_next_trial(tmp_path):
    path, plan = session(tmp_path, budget=4)
    _, _, build, run = fake_backends(tmp_path, plan)
    bisection.run_search(path, build=build, run=run)
    status = bisection.session_status(path)
    assert status['conclusion']['state'] == 'budget_exhausted'
    assert status['trials_remaining'] == 0
    assert 'Next trial:' not in bisection.render_status(status)


def test_changed_evidence_cannot_produce_status(tmp_path):
    path, plan = session(tmp_path)
    _, _, build, run = fake_backends(tmp_path, plan)
    bisection.step(path, build=build, run=run)
    result = path / 'evidence/t0001/result.json'
    document = json.loads(result.read_text())
    document['status'] = 'experiment_failed'
    result.write_text(json.dumps(document))
    with pytest.raises((ValueError, bisection.recipes.ContractError)):
        bisection.session_status(path)


def test_human_status_escapes_control_characters(tmp_path):
    path, plan = session(tmp_path)
    status = bisection.session_status(path)
    status['conclusion'] = dict(state='unresolved', reason='build\x1b[31m\nfailed')
    text = bisection.render_status(status)
    assert '\x1b' not in text and r'\x1b' in text and r'\nfailed' in text
