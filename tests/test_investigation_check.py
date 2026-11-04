"""CI decisions from explicitly SIMULATED, verified investigation evidence."""
import hashlib
import json
import shutil
import subprocess

import pytest

import recipe_investigation as investigation
import recipes
from test_investigation_prefixes import (
    BASE, CANDIDATE, package, pair, recipe, rehash, selected_report,
)


def answer(check, side, name):
    return next(row for row in check['attempts'][side]['correctness']['assertions']
                if row['name'] == name)


def snapshot(root):
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob('*') if path.is_file()}


def stopped_report(tmp_path, recipe, *, baseline_capture='correct', candidate_present=False):
    baseline = package(tmp_path / 'baseline', recipe, BASE, capture=baseline_capture)
    candidate = package(tmp_path / 'candidate', recipe, CANDIDATE) if candidate_present else None
    stop = {'schema': investigation.CONTROLLER_STOP_SCHEMA, 'attempt': 'candidate',
            'status': 'interrupted', 'exit_code': 143, 'reason': 'SIMULATED stopped controller'}
    output = tmp_path / 'report'
    report = investigation.write_investigation_report(
        baseline=baseline, candidate=candidate, controller_stop=stop,
        candidate_missing=None if candidate_present else {'status': stop['status'], 'reason': stop['reason']},
        output_dir=output, observer_prefixes=True)
    return report, output


def test_check_passes_only_selected_complete_pair_and_keeps_reproduction_separate(tmp_path, recipe):
    report, output = selected_report(tmp_path, recipe)
    check = investigation.check_investigation(output / 'investigation.json')
    assert check['schema'] == 'bgperf2/investigation-check/v1alpha1'
    assert check['verified'] is True and check['correctness_selected'] is True
    assert check['outcome'] == 'passed' and check['exit_code'] == 0
    assert check['reasons'] == []
    assert check['reproduction'] == report['assessment']
    assert check['controller_stop'] is None
    assert check['checked_attempts'] == ['baseline', 'candidate']
    assert check['recipe_sha256'] == recipes.recipe_sha256(recipe)
    for side in ('baseline', 'candidate'):
        attempt = check['attempts'][side]
        assert attempt['attempt_id'] == side and attempt['status'] == 'completed'
        assert len(attempt['correctness']['assertions']) == 6
        assert all(row['status'] == 'passed' for row in attempt['correctness']['assertions'])


def test_equal_count_wrong_prefix_set_is_failed_even_with_completed_reproduction(tmp_path, recipe):
    report, output = selected_report(tmp_path, recipe, capture='wrong')
    check = investigation.check_investigation(output / 'investigation.json')
    assert check['verified'] is True
    assert check['outcome'] == 'failed' and check['exit_code'] == 4
    assert check['reproduction'] == report['assessment']
    assert answer(check, 'candidate', 'observer.count')['status'] == 'passed'
    identity = answer(check, 'candidate', 'observer.prefixes')
    assert identity['status'] == 'failed'
    assert identity['observed']['missing_count'] == identity['observed']['unexpected_count'] == 1
    assert check['reasons']


@pytest.mark.parametrize('capture', ['legacy', 'missing', 'unavailable'])
def test_unmeasured_identity_is_inconclusive_not_failed_or_passed(tmp_path, recipe, capture):
    _, output = selected_report(tmp_path, recipe, capture=capture)
    check = investigation.check_investigation(output / 'investigation.json')
    assert check['outcome'] == 'inconclusive' and check['exit_code'] == 5
    assert answer(check, 'candidate', 'observer.count')['status'] == 'passed'
    assert answer(check, 'candidate', 'observer.prefixes')['status'] == 'unmeasured'
    assert check['reasons']


def test_unselected_report_does_not_pass_when_captured_prefixes_happen_to_exist(tmp_path, recipe):
    baseline, candidate = pair(tmp_path, recipe)
    output = tmp_path / 'report'
    investigation.write_investigation_report(baseline=baseline, candidate=candidate, output_dir=output)
    check = investigation.check_investigation(output / 'investigation.json')
    assert check['correctness_selected'] is False
    assert check['outcome'] == 'inconclusive' and check['exit_code'] == 5
    assert all(item['correctness'] is None for item in check['attempts'].values())
    assert check['reasons']


@pytest.mark.parametrize('baseline_present', [True, False])
def test_missing_originals_remain_inconclusive_with_original_reason(tmp_path, recipe, baseline_present):
    baseline = package(tmp_path / 'baseline', recipe, BASE) if baseline_present else None
    missing = {'status': 'inconclusive', 'reason': 'SIMULATED original absent; launch unknown'}
    output = tmp_path / 'report'
    investigation.write_investigation_report(baseline=baseline, candidate=None,
        baseline_missing=None if baseline_present else missing, candidate_missing=missing,
        observer_prefixes=True, output_dir=output)
    check = investigation.check_investigation(output / 'investigation.json')
    assert check['outcome'] == 'inconclusive' and check['exit_code'] == 5
    assert check['attempts']['candidate']['attempt_id'] is None
    assert check['attempts']['candidate']['reason'] == missing['reason']
    assert check['reasons']


def test_noncompleted_operation_cannot_pass_even_when_all_named_assertions_pass(tmp_path, recipe):
    _, output = selected_report(tmp_path, recipe, status='experiment_failed')
    check = investigation.check_investigation(output / 'investigation.json')
    assert check['attempts']['candidate']['status'] == 'experiment_failed'
    assert all(row['status'] == 'passed'
               for row in check['attempts']['candidate']['correctness']['assertions'])
    assert check['outcome'] == 'inconclusive' and check['exit_code'] == 5


@pytest.mark.parametrize('candidate_present', [False, True])
def test_controller_stop_prevents_pass_with_partial_or_completed_originals(tmp_path, recipe, candidate_present):
    report, output = stopped_report(tmp_path, recipe, candidate_present=candidate_present)
    check = investigation.check_investigation(output / 'investigation.json')
    assert check['outcome'] == 'inconclusive' and check['exit_code'] == 5
    assert check['controller_stop']['exit_code'] == 143
    assert check['reproduction'] == report['assessment']
    if candidate_present:
        assert all(item['status'] == 'completed' and item['correctness']['outcome'] == 'passed'
                   for item in check['attempts'].values())
    assert check['reasons']


@pytest.mark.parametrize('other_capture', ['unavailable', 'missing'])
def test_observed_failure_takes_precedence_over_other_side_unmeasured(tmp_path, recipe, other_capture):
    baseline = package(tmp_path / 'baseline', recipe, BASE, capture='wrong')
    candidate = package(tmp_path / 'candidate', recipe, CANDIDATE, capture=other_capture)
    output = tmp_path / 'report'
    investigation.write_investigation_report(baseline=baseline, candidate=candidate,
        observer_prefixes=True, output_dir=output)
    check = investigation.check_investigation(output / 'investigation.json')
    assert check['outcome'] == 'failed' and check['exit_code'] == 4
    assert answer(check, 'baseline', 'observer.prefixes')['status'] == 'failed'
    assert answer(check, 'candidate', 'observer.prefixes')['status'] == 'unmeasured'


@pytest.mark.parametrize('with_stop', [False, True])
def test_observed_failure_takes_precedence_over_absent_candidate_and_controller_stop(tmp_path, recipe, with_stop):
    if with_stop:
        _, output = stopped_report(tmp_path, recipe, baseline_capture='wrong')
    else:
        baseline = package(tmp_path / 'baseline', recipe, BASE, capture='wrong')
        output = tmp_path / 'report'
        investigation.write_investigation_report(baseline=baseline, candidate=None,
            candidate_missing={'status': 'inconclusive', 'reason': 'SIMULATED absent original'},
            observer_prefixes=True, output_dir=output)
    check = investigation.check_investigation(output / 'investigation.json')
    assert check['outcome'] == 'failed' and check['exit_code'] == 4
    assert check['attempts']['candidate']['attempt_id'] is None
    assert answer(check, 'baseline', 'observer.prefixes')['status'] == 'failed'
    assert bool(check['controller_stop']) is with_stop


@pytest.mark.parametrize('capture, expected_exit, expected_outcome', [
    ('correct', 0, 'passed'), ('wrong', 4, 'failed'), ('unavailable', 5, 'inconclusive')])
def test_public_cli_returns_ci_decision_without_subprocesses_or_evidence_changes(
        tmp_path, recipe, monkeypatch, capsys, capture, expected_exit, expected_outcome):
    _, output = selected_report(tmp_path, recipe, capture=capture)
    before = snapshot(tmp_path)
    def forbidden(*args, **kwargs):
        raise AssertionError('Check must not start a worker, build, probe or subprocess')
    monkeypatch.setattr(subprocess, 'run', forbidden)
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    assert recipes.main(['investigation-check', str(output / 'investigation.json')]) == expected_exit
    emitted = capsys.readouterr()
    check = json.loads(emitted.out)
    assert emitted.err == '' and check['verified'] is True
    assert check['outcome'] == expected_outcome and check['exit_code'] == expected_exit
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize('alteration', ['summary', 'prose', 'artifact'])
def test_integrity_refusal_returns_two_without_emitting_an_assertion_verdict(tmp_path, recipe, capsys, alteration):
    report, output = selected_report(tmp_path, recipe)
    if alteration == 'summary':
        report['correctness']['attempts']['candidate']['outcome'] = 'failed'
        (output / 'investigation.json').write_text(json.dumps(report))
    elif alteration == 'prose':
        with (output / 'REPORT.md').open('a') as stream:
            stream.write('\nSIMULATED unsupported acceptance claim\n')
    else:
        path = output / 'candidate/work/observer-prefixes.json'
        value = recipes.read_document(path)
        value['snapshot']['prefixes'][0] = '192.0.2.1/32'
        path.write_text(json.dumps(value))
    rehash(output)
    before = snapshot(tmp_path)
    assert recipes.main(['investigation-check', str(output / 'investigation.json')]) == 2
    emitted = capsys.readouterr()
    assert emitted.out == '' and emitted.err.startswith('investigation-check:')
    assert snapshot(tmp_path) == before


def test_relocation_and_rebuild_preserve_failed_ci_decision(tmp_path, recipe):
    _, output = selected_report(tmp_path, recipe, capture='wrong')
    moved = tmp_path / 'relocated'
    shutil.copytree(output, moved)
    rebuilt = tmp_path / 'rebuilt'
    investigation.rebuild_investigation_report(moved / 'investigation.json', output_dir=rebuilt)
    original = investigation.check_investigation(output / 'investigation.json')
    for root in (moved, rebuilt):
        current = investigation.check_investigation(root / 'investigation.json')
        assert current == original


def test_ci_failure_does_not_change_existing_status_or_verification_exit_contracts(tmp_path, recipe, capsys):
    report, output = selected_report(tmp_path, recipe, capture='wrong')
    manifest = output / 'investigation.json'
    assert recipes.main(['investigation-verify', str(manifest)]) == 0
    verification = json.loads(capsys.readouterr().out)
    assert verification == {'valid': True, 'schema': investigation.SCHEMA,
                            'files_verified': len(recipes.read_document(output / 'checksums.json')['files']),
                            'outcome': report['assessment']['outcome']}
    assert recipes.main(['investigation-status', str(manifest)]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status['schema'] == 'bgperf2/investigation-status/v1alpha1'
    assert status['attempts']['candidate']['correctness']['outcome'] == 'failed'
    assert recipes.main(['investigation-check', str(manifest)]) == 4
    assert json.loads(capsys.readouterr().out)['outcome'] == 'failed'


def test_candidate_check_can_pass_observed_fix_without_hiding_baseline_failure(tmp_path, recipe, capsys):
    baseline = package(tmp_path / 'baseline', recipe, BASE, capture='wrong')
    candidate = package(tmp_path / 'candidate', recipe, CANDIDATE)
    output = tmp_path / 'report'
    report = investigation.write_investigation_report(baseline=baseline, candidate=candidate,
        observer_prefixes=True, output_dir=output)
    manifest = output / 'investigation.json'
    assert recipes.main(['investigation-check', str(manifest)]) == 4
    both = json.loads(capsys.readouterr().out)
    assert both['checked_attempts'] == ['baseline', 'candidate'] and both['outcome'] == 'failed'
    assert recipes.main(['investigation-check', str(manifest), '--side', 'candidate']) == 0
    selected = json.loads(capsys.readouterr().out)
    assert selected['checked_attempts'] == ['candidate']
    assert selected['outcome'] == 'passed' and selected['exit_code'] == 0
    assert selected['reasons'] == [] and selected['reproduction'] == report['assessment']
    assert selected['attempts']['baseline']['correctness']['outcome'] == 'failed'
    assert answer(selected, 'baseline', 'observer.prefixes')['status'] == 'failed'
    assert selected['attempts']['candidate']['correctness']['outcome'] == 'passed'
    assert selected['attempts'] == both['attempts']


@pytest.mark.parametrize('unselected_capture', ['wrong', 'unavailable'])
def test_selected_baseline_pass_ignores_other_side_assertion_failure_or_unmeasured(
        tmp_path, recipe, unselected_capture):
    _, output = selected_report(tmp_path, recipe, capture=unselected_capture)
    manifest = output / 'investigation.json'
    baseline = investigation.check_investigation(manifest, side='baseline')
    assert baseline['checked_attempts'] == ['baseline']
    assert baseline['outcome'] == 'passed' and baseline['exit_code'] == 0
    assert baseline['reasons'] == []
    candidate = investigation.check_investigation(manifest, side='candidate')
    assert candidate['checked_attempts'] == ['candidate']
    assert candidate['exit_code'] == (4 if unselected_capture == 'wrong' else 5)


def test_missing_unselected_original_allows_selected_check_without_controller_stop(tmp_path, recipe):
    baseline = package(tmp_path / 'baseline', recipe, BASE)
    output = tmp_path / 'report'
    missing = {'status': 'inconclusive', 'reason': 'SIMULATED absent original'}
    investigation.write_investigation_report(baseline=baseline, candidate=None,
        candidate_missing=missing, observer_prefixes=True, output_dir=output)
    manifest = output / 'investigation.json'
    baseline_check = investigation.check_investigation(manifest, side='baseline')
    assert baseline_check['outcome'] == 'passed' and baseline_check['exit_code'] == 0
    assert baseline_check['reasons'] == [] and baseline_check['controller_stop'] is None
    assert baseline_check['attempts']['candidate']['attempt_id'] is None
    assert baseline_check['attempts']['candidate']['reason'] == missing['reason']
    candidate_check = investigation.check_investigation(manifest, side='candidate')
    assert candidate_check['outcome'] == 'inconclusive' and candidate_check['exit_code'] == 5
    assert candidate_check['checked_attempts'] == ['candidate']


def test_selected_candidate_can_pass_when_only_baseline_original_is_missing(tmp_path, recipe):
    candidate = package(tmp_path / 'candidate', recipe, CANDIDATE)
    output = tmp_path / 'report'
    investigation.write_investigation_report(baseline=None, candidate=candidate,
        baseline_missing={'status': 'inconclusive', 'reason': 'SIMULATED missing baseline'},
        observer_prefixes=True, output_dir=output)
    check = investigation.check_investigation(output / 'investigation.json', side='candidate')
    assert check['checked_attempts'] == ['candidate'] and check['exit_code'] == 0
    assert check['outcome'] == 'passed' and check['reasons'] == []
    assert check['attempts']['baseline']['attempt_id'] is None


@pytest.mark.parametrize('candidate_present', [False, True])
def test_report_controller_stop_prevents_selected_side_pass_even_when_other_side_stopped(
        tmp_path, recipe, candidate_present):
    _, output = stopped_report(tmp_path, recipe, candidate_present=candidate_present)
    check = investigation.check_investigation(output / 'investigation.json', side='baseline')
    assert check['attempts']['baseline']['correctness']['outcome'] == 'passed'
    assert check['checked_attempts'] == ['baseline']
    assert check['controller_stop']['attempt'] == 'candidate'
    assert check['outcome'] == 'inconclusive' and check['exit_code'] == 5
    assert check['reasons']


def test_selected_failure_still_takes_precedence_over_global_controller_stop(tmp_path, recipe):
    _, output = stopped_report(tmp_path, recipe, baseline_capture='wrong')
    check = investigation.check_investigation(output / 'investigation.json', side='baseline')
    assert check['checked_attempts'] == ['baseline']
    assert check['controller_stop'] is not None
    assert check['outcome'] == 'failed' and check['exit_code'] == 4
    assert answer(check, 'baseline', 'observer.prefixes')['status'] == 'failed'


def test_nonselected_failure_does_not_override_selected_inconclusive_controller_stop(tmp_path, recipe):
    _, output = stopped_report(tmp_path, recipe, baseline_capture='wrong', candidate_present=True)
    check = investigation.check_investigation(output / 'investigation.json', side='candidate')
    assert check['checked_attempts'] == ['candidate']
    assert check['attempts']['baseline']['correctness']['outcome'] == 'failed'
    assert check['attempts']['candidate']['correctness']['outcome'] == 'passed'
    assert check['controller_stop'] is not None
    assert check['outcome'] == 'inconclusive' and check['exit_code'] == 5


def test_side_selection_does_not_create_correctness_for_unselected_legacy_report(tmp_path, recipe):
    baseline, candidate = pair(tmp_path, recipe)
    output = tmp_path / 'report'
    investigation.write_investigation_report(baseline=baseline, candidate=candidate, output_dir=output)
    check = investigation.check_investigation(output / 'investigation.json', side='candidate')
    assert check['checked_attempts'] == ['candidate']
    assert check['correctness_selected'] is False
    assert check['outcome'] == 'inconclusive' and check['exit_code'] == 5


@pytest.mark.parametrize('invalid', ['all', None, True])
def test_invalid_side_refuses_before_any_report_verification(tmp_path, monkeypatch, invalid):
    def forbidden(*args, **kwargs):
        raise AssertionError('Invalid side must be refused before report verification')
    monkeypatch.setattr(investigation, 'investigation_status', forbidden)
    with pytest.raises(recipes.ContractError):
        investigation.check_investigation(tmp_path / 'absent/investigation.json', side=invalid)


def test_cli_invalid_side_refuses_without_json_or_report_inspection(tmp_path, monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        raise AssertionError('Invalid CLI side must not inspect the report')
    monkeypatch.setattr(investigation, 'investigation_status', forbidden)
    with pytest.raises(SystemExit) as error:
        recipes.main(['investigation-check', str(tmp_path / 'absent/investigation.json'),
                      '--side', 'all'])
    assert error.value.code == 2
    emitted = capsys.readouterr()
    assert emitted.out == '' and 'invalid choice' in emitted.err
