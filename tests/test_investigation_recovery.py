"""Controller stops preserve verified originals without inventing pair success."""
import copy
import hashlib
import json
from pathlib import Path
import shutil

import pytest

import recipes
from recipe_investigation import (CONTROLLER_STOP_SCHEMA, rebuild_investigation_report,
    run_investigation, verify_investigation_report, write_investigation_report)
from recipe_results import verify_result_package
from recipe_targets import supplied_target
from test_recipe_investigation import BASE, FIX, package, recipe, rehash_report


def stopped_case(tmp_path, recipe, *, side='baseline', stop='error', package_state='valid'):
    targets = [supplied_target(recipe, image, instrumentation=mode)
               for image, mode in ((BASE, 'optimized'), (FIX, 'debug'))]
    calls, originals = [], {}
    def execute(document, **kwargs):
        label = 'baseline' if kwargs['target']['image'] == BASE else 'candidate'
        calls.append(label)
        if label != side or package_state != 'absent':
            selected_recipe = copy.deepcopy(document)
            if label == side and package_state == 'wrong_recipe':
                selected_recipe['reproduction']['question'] += ' DIFFERENT QUESTION'
            image = kwargs['target']['image']
            if label == side and package_state == 'wrong_target':
                image = FIX if image == BASE else BASE
            source_root = (tmp_path / 'duplicate/fixture-baseline' if label == side and package_state == 'duplicate_id'
                           else tmp_path / ('fixture-' + label))
            source = package(source_root, selected_recipe, image,
                status='experiment_failed' if label == 'baseline' else 'completed',
                outcome='reproduced' if label == 'baseline' else 'not_reproduced')
            root = Path(kwargs['results_dir'])
            shutil.copytree(source.parent, root)
            if label == side and package_state == 'tampered':
                (root / 'work/console.log').write_text('SIMULATED unverified partial collection')
            elif label == side and package_state == 'malformed':
                (root / 'result.json').write_text('{SIMULATED incomplete package')
            originals[label] = {p.relative_to(root).as_posix(): p.read_bytes()
                                for p in root.rglob('*') if p.is_file()}
        if label == side:
            if stop == 'keyboard':
                raise KeyboardInterrupt('SIMULATED stop after package')
            if stop == 'term':
                raise SystemExit(143)
            raise OSError('SIMULATED controller failure after package')
        return recipes.read_document(root / 'result.json')
    result = run_investigation(recipe, baseline_target=targets[0], candidate_target=targets[1],
        workdir=tmp_path / 'work', results_dir=tmp_path / 'results',
        check=lambda *a, **k: {'status': 'checks_passed'}, run=execute)
    return result, recipes.read_document(result['report']), calls, originals


@pytest.mark.parametrize('side', ['baseline', 'candidate'])
@pytest.mark.parametrize('stop,exit_code', [('error', 3), ('keyboard', 130), ('term', 143)])
def test_stop_after_verified_package_retains_exact_original_and_withholds_pair(
        tmp_path, recipe, side, stop, exit_code):
    result, report, calls, originals = stopped_case(tmp_path, recipe, side=side, stop=stop)
    assert calls == (['baseline'] if side == 'baseline' else ['baseline', 'candidate'])
    assert result['exit_code'] == exit_code and report['assessment']['outcome'] == 'inconclusive'
    attempt = report['attempts'][side]
    assert attempt['availability'] == 'present'
    assert attempt['status'] == ('experiment_failed' if side == 'baseline' else 'completed')
    assert attempt['reproduction']['outcome'] == ('reproduced' if side == 'baseline' else 'not_reproduced')
    if side == 'baseline':
        assert report['attempts']['candidate']['status'] == 'not_run'
    root = Path(result['report']).parent
    control = recipes.read_document(root / report['controller_stop']['path'])
    assert control == dict(schema=CONTROLLER_STOP_SCHEMA, attempt=side, exit_code=exit_code,
                          status='harness_failed' if stop == 'error' else 'interrupted', reason=control['reason'])
    assert control['reason'] and 'Controller stop' in (root / 'REPORT.md').read_text()
    checksums = recipes.read_document(root / 'checksums.json')
    assert any(row['path'] == 'controller-stop.json' for row in checksums['files'])
    assert report['controller_stop']['sha256'] == hashlib.sha256((root / 'controller-stop.json').read_bytes()).hexdigest()
    for label, contents in originals.items():
        for relative, data in contents.items():
            assert (tmp_path / 'results' / label / relative).read_bytes() == data
            assert (root / label / relative).read_bytes() == data
        assert verify_result_package(root / label / 'result.json')['valid']
    assert verify_investigation_report(result['report'])['valid']


@pytest.mark.parametrize('side', ['baseline', 'candidate'])
@pytest.mark.parametrize('package_state', ['absent', 'tampered', 'malformed', 'wrong_recipe', 'wrong_target'])
def test_unverified_or_unselected_partial_package_is_retained_but_not_bundled(
        tmp_path, recipe, side, package_state):
    result, report, calls, originals = stopped_case(tmp_path, recipe, side=side, package_state=package_state)
    assert calls == (['baseline'] if side == 'baseline' else ['baseline', 'candidate'])
    assert result['exit_code'] == 3 and report['assessment']['outcome'] == 'inconclusive'
    attempt = report['attempts'][side]
    assert attempt['availability'] == 'missing' and attempt['status'] == 'harness_failed'
    if package_state != 'absent':
        assert 'Existing selected package retained at ' in attempt['reason']
        assert 'unavailable for reporting' in attempt['reason']
        for relative, data in originals[side].items():
            assert (tmp_path / 'results' / side / relative).read_bytes() == data
    assert not (Path(result['report']).parent / side).exists()
    assert verify_investigation_report(result['report'])['valid']


@pytest.mark.parametrize('side,package_state,stop', [
    ('baseline', 'valid', 'term'), ('candidate', 'valid', 'error'),
    ('baseline', 'absent', 'keyboard'), ('candidate', 'absent', 'error')])
def test_public_rebuild_preserves_packages_missing_reasons_and_controller_stop(
        tmp_path, recipe, capsys, side, package_state, stop):
    result, report, calls, originals = stopped_case(tmp_path, recipe, side=side,
        package_state=package_state, stop=stop)
    root = Path(result['report']).parent
    before = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*') if p.is_file()}
    output = tmp_path / 'rebuilt'
    assert recipes.main(['investigation-rebuild', result['report'], '--output-dir', str(output)]) == 0
    assert json.loads(capsys.readouterr().out) == report
    assert recipes.read_document(output / 'investigation.json') == report
    assert {p.relative_to(output).as_posix(): p.read_bytes() for p in output.rglob('*') if p.is_file()} == before
    assert {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*') if p.is_file()} == before
    assert verify_investigation_report(output / 'investigation.json')['valid']
    assert calls == (['baseline'] if side == 'baseline' else ['baseline', 'candidate'])


def test_legacy_report_and_raw_report_cli_remain_unchanged(tmp_path, recipe, capsys):
    baseline = package(tmp_path / 'baseline', recipe, BASE, status='experiment_failed', outcome='reproduced')
    candidate = package(tmp_path / 'candidate', recipe, FIX)
    original = tmp_path / 'report'
    assert recipes.main(['investigation-report', '--baseline', str(baseline), '--candidate', str(candidate),
                         '--output-dir', str(original)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert 'controller_stop' not in report and not (original / 'controller-stop.json').exists()
    assert report['assessment']['outcome'] == 'baseline_reproduced_candidate_not_reproduced'
    assert verify_investigation_report(original / 'investigation.json')['valid']
    assert rebuild_investigation_report(original / 'investigation.json', output_dir=tmp_path / 'rebuilt') == report


def test_public_rebuild_verifies_source_before_creating_destination(tmp_path, recipe, capsys):
    result, report, _, _ = stopped_case(tmp_path, recipe)
    root = Path(result['report']).parent
    (root / 'baseline/work/console.log').write_text('SIMULATED changed evidence')
    output = tmp_path / 'refused'
    assert recipes.main(['investigation-rebuild', result['report'], '--output-dir', str(output)]) == 2
    assert 'checksum' in capsys.readouterr().err and not output.exists()


def test_both_missing_rebuild_cannot_write_inside_source_report(tmp_path, recipe):
    result, report, _, _ = stopped_case(tmp_path, recipe, package_state='absent')
    assert all(item['availability'] == 'missing' for item in report['attempts'].values())
    output = Path(result['report']).parent / 'nested'
    with pytest.raises(recipes.ContractError, match='nonnested'):
        rebuild_investigation_report(result['report'], output_dir=output)
    assert not output.exists()


def test_recovered_package_cannot_bypass_distinct_original_identity_guard(tmp_path, recipe):
    with pytest.raises(recipes.ContractError, match='distinct original attempt'):
        stopped_case(tmp_path, recipe, side='candidate', package_state='duplicate_id')
    assert not (tmp_path / 'results/report').exists()
    for label in ('baseline', 'candidate'):
        assert verify_result_package(tmp_path / 'results' / label / 'result.json')['valid']


@pytest.mark.parametrize('change', [dict(schema='unsupported'), dict(attempt='third'),
    dict(status='completed'), dict(status='interrupted', exit_code=3), dict(exit_code=True),
    dict(exit_code=0), dict(reason=''), dict(extra='unsupported')])
def test_malformed_controller_stop_refused_before_report_creation(tmp_path, change):
    control = dict(schema=CONTROLLER_STOP_SCHEMA, attempt='baseline', status='harness_failed',
                   exit_code=3, reason='SIMULATED controller failed')
    control.update(change)
    output = tmp_path / 'report'
    with pytest.raises(recipes.ContractError):
        write_investigation_report(baseline=None, output_dir=output, controller_stop=control)
    assert not output.exists()


@pytest.mark.parametrize('change', ['unbound_stop', 'stop_bytes', 'invalid_stop', 'missing_checksum', 'unsafe_reference', 'assessment', 'wrong_side'])
def test_controller_evidence_and_inconclusive_assessment_are_independently_verified(tmp_path, recipe, change):
    result, report, _, _ = stopped_case(tmp_path, recipe, side='candidate')
    root = Path(result['report']).parent
    manifest = root / 'investigation.json'
    stop_path = root / 'controller-stop.json'
    if change == 'unbound_stop':
        report.pop('controller_stop')
    elif change in ('stop_bytes', 'invalid_stop', 'wrong_side'):
        control = recipes.read_document(stop_path)
        control['reason'] += ' CHANGED'
        if change == 'invalid_stop':control['exit_code'] = 0
        if change == 'wrong_side':control['attempt'] = 'baseline'
        stop_path.write_text(json.dumps(control))
        if change in ('invalid_stop', 'wrong_side'):
            report['controller_stop']['sha256'] = hashlib.sha256(stop_path.read_bytes()).hexdigest()
    elif change == 'unsafe_reference':
        report['controller_stop']['path'] = '../foreign-controller.json'
    elif change == 'assessment':
        report['assessment']['outcome'] = 'baseline_reproduced_candidate_not_reproduced'
    manifest.write_text(json.dumps(report))
    rehash_report(root)
    if change == 'missing_checksum':
        path = root / 'checksums.json'
        checksums = recipes.read_document(path)
        checksums['files'] = [item for item in checksums['files'] if item['path'] != 'controller-stop.json']
        path.write_text(json.dumps(checksums))
    with pytest.raises(recipes.ContractError):
        verify_investigation_report(manifest)
