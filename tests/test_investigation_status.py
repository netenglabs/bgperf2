"""Read-only status of explicitly SIMULATED sealed investigation evidence."""
import hashlib
import json
import shutil
import subprocess

import pytest

import recipe_investigation as investigation
import recipes
import test_investigation_prefixes as prefix_fixtures
from test_investigation_prefixes import (
    BASE, package, pair, recipe, rehash, selected_report,
)


def assertion(status, side, name):
    return next(row for row in status['attempts'][side]['correctness']['assertions']
                if row['name'] == name)


def snapshot(root):
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob('*') if path.is_file()}


def test_status_separates_integrity_reproduction_and_correctness(tmp_path, recipe):
    report, output = selected_report(tmp_path, recipe)
    status = investigation.investigation_status(output / 'investigation.json')
    assert status['schema'] == 'bgperf2/investigation-status/v1alpha1'
    assert status['verified'] is True and status['files_verified'] > 0
    assert status['recipe_sha256'] == recipes.recipe_sha256(recipe)
    assert status['reproduction'] == report['assessment']
    assert status['controller_stop'] is None and status['correctness_selected'] is True
    for side in ('baseline', 'candidate'):
        attempt = status['attempts'][side]
        assert attempt['availability'] == 'present' and attempt['status'] == 'completed'
        assert attempt['attempt_id'] == side
        assert attempt['correctness']['outcome'] == 'passed'
        assert len(attempt['correctness']['assertions']) == 6
        assert assertion(status, side, 'observer.count')['observed'] == 100
        identity = assertion(status, side, 'observer.prefixes')
        assert identity['observed']['observed_count'] == 100
        assert identity['observed']['missing_count'] == identity['observed']['unexpected_count'] == 0


def test_verified_status_does_not_turn_equal_count_mismatch_into_success(tmp_path, recipe):
    report, output = selected_report(tmp_path, recipe, capture='wrong')
    status = investigation.investigation_status(output / 'investigation.json')
    assert status['verified'] is True
    assert status['reproduction'] == report['assessment']
    assert status['attempts']['candidate']['correctness']['outcome'] == 'failed'
    assert assertion(status, 'candidate', 'observer.count')['status'] == 'passed'
    identity = assertion(status, 'candidate', 'observer.prefixes')
    assert identity['status'] == 'failed'
    assert identity['observed']['missing_sample'] == ['100.0.0.0/32']
    assert identity['observed']['unexpected_sample'] == ['192.0.2.1/32']


@pytest.mark.parametrize('capture', ['legacy', 'missing', 'unavailable'])
def test_selected_status_preserves_unmeasured_capture(tmp_path, recipe, capture):
    _, output = selected_report(tmp_path, recipe, capture=capture)
    status = investigation.investigation_status(output / 'investigation.json')
    assert status['correctness_selected'] is True
    assert status['attempts']['candidate']['correctness']['outcome'] == 'inconclusive'
    assert assertion(status, 'candidate', 'observer.count')['status'] == 'passed'
    identity = assertion(status, 'candidate', 'observer.prefixes')
    assert identity['status'] == 'unmeasured' and identity['observed'] is None
    assert identity['reason']


def test_unselected_legacy_report_does_not_infer_correctness_from_capture(tmp_path, recipe):
    baseline, candidate = pair(tmp_path, recipe)
    output = tmp_path / 'report'
    investigation.write_investigation_report(baseline=baseline, candidate=candidate,
                                              output_dir=output)
    status = investigation.investigation_status(output / 'investigation.json')
    assert status['correctness_selected'] is False
    assert all(item['correctness'] is None for item in status['attempts'].values())
    assert status['attempts']['baseline']['attempt_id'] == 'baseline'


@pytest.mark.parametrize('baseline_present', [True, False])
def test_missing_attempts_keep_original_reason_and_no_invented_identity(tmp_path, recipe, baseline_present):
    baseline = package(tmp_path / 'baseline', recipe, BASE) if baseline_present else None
    missing = {'status': 'inconclusive', 'reason': 'SIMULATED unknown launch; original absent'}
    output = tmp_path / 'report'
    investigation.write_investigation_report(baseline=baseline, candidate=None,
        baseline_missing=None if baseline_present else missing, candidate_missing=missing,
        output_dir=output, observer_prefixes=True)
    status = investigation.investigation_status(output / 'investigation.json')
    for side in ('candidate',) if baseline_present else ('baseline', 'candidate'):
        item = status['attempts'][side]
        assert item['availability'] == 'missing' and item['status'] == 'inconclusive'
        assert item['attempt_id'] is None and item['reason'] == missing['reason']
        assert item['correctness']['outcome'] == 'inconclusive'
        assert item['correctness']['assertions'] == []


def test_controller_stop_is_visible_even_when_available_side_passes(tmp_path, recipe):
    baseline = package(tmp_path / 'baseline', recipe, BASE)
    stopped = {'schema': investigation.CONTROLLER_STOP_SCHEMA, 'attempt': 'candidate',
               'status': 'interrupted', 'exit_code': 143, 'reason': 'SIMULATED controller TERM'}
    output = tmp_path / 'report'
    investigation.write_investigation_report(baseline=baseline, candidate=None,
        candidate_missing={'status': stopped['status'], 'reason': stopped['reason']},
        controller_stop=stopped, output_dir=output, observer_prefixes=True)
    status = investigation.investigation_status(output / 'investigation.json')
    assert status['controller_stop'] == stopped
    assert status['reproduction']['outcome'] == 'inconclusive'
    assert status['attempts']['baseline']['correctness']['outcome'] == 'passed'
    assert status['attempts']['candidate']['status'] == 'interrupted'
    assert status['attempts']['candidate']['correctness']['assertions'] == []


@pytest.mark.parametrize('alteration', ['summary', 'prose', 'artifact'])
def test_status_refuses_tampered_evidence_before_emitting_summary(tmp_path, recipe, alteration):
    report, output = selected_report(tmp_path, recipe)
    if alteration == 'summary':
        report['correctness']['attempts']['candidate']['outcome'] = 'failed'
        (output / 'investigation.json').write_text(json.dumps(report))
    elif alteration == 'prose':
        with (output / 'REPORT.md').open('a') as stream:
            stream.write('\nSIMULATED unsupported assertion pass\n')
    else:
        path = output / 'candidate/work/observer-prefixes.json'
        receipt = recipes.read_document(path)
        receipt['snapshot']['prefixes'][0] = '192.0.2.1/32'
        path.write_text(json.dumps(receipt))
    rehash(output)
    with pytest.raises(recipes.ContractError):
        investigation.investigation_status(output / 'investigation.json')


def test_relocated_and_rebuilt_status_keeps_original_ids_and_mismatch(tmp_path, recipe):
    _, output = selected_report(tmp_path, recipe, capture='wrong')
    moved = tmp_path / 'relocated'
    shutil.copytree(output, moved)
    rebuilt = tmp_path / 'rebuilt'
    investigation.rebuild_investigation_report(moved / 'investigation.json', output_dir=rebuilt)
    original = investigation.investigation_status(output / 'investigation.json')
    for root in (moved, rebuilt):
        current = investigation.investigation_status(root / 'investigation.json')
        assert current['attempts'] == original['attempts']
        assert current['reproduction'] == original['reproduction']


def test_reordered_attempt_keys_keep_each_original_id_bound_to_its_side(tmp_path, recipe):
    report, output = selected_report(tmp_path, recipe, capture='wrong')
    report['attempts'] = {side: report['attempts'][side] for side in ('candidate', 'baseline')}
    (output / 'investigation.json').write_text(json.dumps(report))
    (output / 'REPORT.md').write_text(investigation._render(report, None))
    rehash(output)
    status = investigation.investigation_status(output / 'investigation.json')
    assert status['attempts']['baseline']['attempt_id'] == 'baseline'
    assert status['attempts']['candidate']['attempt_id'] == 'candidate'
    assert status['attempts']['baseline']['correctness']['outcome'] == 'passed'
    assert status['attempts']['candidate']['correctness']['outcome'] == 'failed'


@pytest.mark.parametrize('form', ['json', 'text'])
def test_public_cli_is_read_only_without_subprocesses(tmp_path, recipe, monkeypatch, capsys, form):
    _, output = selected_report(tmp_path, recipe, capture='wrong')
    before = snapshot(tmp_path)
    def forbidden(*args, **kwargs):
        raise AssertionError('Status must not start a subprocess, worker, build or probe')
    monkeypatch.setattr(subprocess, 'run', forbidden)
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    args = ['investigation-status', str(output / 'investigation.json')]
    if form == 'text':
        args.extend(['--format', 'text'])
    assert recipes.main(args) == 0
    printed = capsys.readouterr().out
    if form == 'json':
        status = json.loads(printed)
        assert status['verified'] is True
        assert status['attempts']['candidate']['correctness']['outcome'] == 'failed'
    else:
        assert 'observer.count' in printed and 'observer.prefixes' in printed
        assert 'candidate' in printed and 'baseline' in printed
        assert 'failed' in printed and 'passed' in printed
    assert snapshot(tmp_path) == before


def test_text_unselected_and_unmeasured_are_not_rendered_as_pass(tmp_path, recipe):
    baseline, candidate = pair(tmp_path, recipe)
    output = tmp_path / 'unselected'
    investigation.write_investigation_report(baseline=baseline, candidate=candidate,
                                              output_dir=output)
    status = investigation.investigation_status(output / 'investigation.json')
    text = investigation.render_investigation_status(status)
    assert 'not selected' in text.lower()
    _, selected = selected_report(tmp_path / 'selected', recipe, capture='unavailable')
    text = investigation.render_investigation_status(
        investigation.investigation_status(selected / 'investigation.json'))
    assert 'unmeasured' in text and 'inconclusive' in text


def test_text_escapes_terminal_controls_in_preserved_missing_reason(tmp_path):
    reason = 'SIMULATED\x1b[31m terminal\nnew line\tand tab'
    output = tmp_path / 'report'
    investigation.write_investigation_report(baseline=None, candidate=None,
        baseline_missing={'status': 'inconclusive', 'reason': reason},
        candidate_missing={'status': 'inconclusive', 'reason': reason}, output_dir=output)
    status = investigation.investigation_status(output / 'investigation.json')
    assert status['attempts']['candidate']['reason'] == reason
    text = investigation.render_investigation_status(status)
    assert '\x1b' not in text and '\t' not in text
    assert 'SIMULATED' in text


def test_text_summarizes_health_and_prefix_differences_without_raw_state(tmp_path, recipe, monkeypatch):
    original_evidence = prefix_fixtures.evidence
    def evidence_with_times(recipe):
        files = original_evidence(recipe)
        for item in files['diagnostics.json']['containers']:
            item['state'].update(Status='running', StartedAt='2026-11-03T22:59:18Z')
        return files
    monkeypatch.setattr(prefix_fixtures, 'evidence', evidence_with_times)
    _, output = selected_report(tmp_path, recipe, capture='wrong')
    status = investigation.investigation_status(output / 'investigation.json')
    text = investigation.render_investigation_status(status)
    assert 'target=running' in text and 'generator=running' in text and 'observer=running' in text
    assert 'observed_count=100' in text and 'missing_count=1' in text and 'unexpected_count=1' in text
    assert '100.0.0.0/32' in text and '192.0.2.1/32' in text
    assert 'StartedAt' not in text and '2026-11-03T22:59:18Z' not in text
    assert 'snapshot_monotonic_ns' not in text and 'OOMKilled' not in text
    health = assertion(status, 'candidate', 'roles.healthy')
    assert health['observed'][0]['state']['StartedAt'] == '2026-11-03T22:59:18Z'


@pytest.mark.parametrize('missing_state', [None, []])
@pytest.mark.parametrize('form', ['json', 'text'])
def test_failed_health_with_other_missing_state_remains_reportable(tmp_path, recipe, monkeypatch,
                                                                 capsys, missing_state, form):
    original_evidence = prefix_fixtures.evidence
    def evidence_with_partial_failure(recipe):
        files = original_evidence(recipe)
        by_role = {item['role']: item for item in files['diagnostics.json']['containers']}
        by_role['target']['state'].update(Running=False, Status='exited')
        by_role['generator']['state'] = missing_state
        by_role['observer']['state']['Status'] = 'running'
        return files
    monkeypatch.setattr(prefix_fixtures, 'evidence', evidence_with_partial_failure)
    _, output = selected_report(tmp_path, recipe)
    assert investigation.verify_investigation_report(output / 'investigation.json')['valid'] is True
    assert recipes.main(['investigation-status', str(output / 'investigation.json'),
                         '--format', form]) == 0
    printed = capsys.readouterr().out
    if form == 'json':
        status = json.loads(printed)
        assert status['verified'] is True
        assert status['attempts']['candidate']['correctness']['outcome'] == 'failed'
        health = assertion(status, 'candidate', 'roles.healthy')
        assert health['status'] == 'failed'
        by_role = {item['role']: item['state'] for item in health['observed']}
        assert by_role['target']['Running'] is False
        assert by_role['generator'] == missing_state
    else:
        assert 'roles.healthy: failed' in printed
        assert 'target=exited' in printed and 'generator=unknown' in printed
        assert 'Correctness: failed' in printed
