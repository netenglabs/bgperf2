"""A copied result cannot stand in for a second original observation."""
import hashlib
import json
import shutil

import pytest

import recipes
from recipe_investigation import write_investigation_report, verify_investigation_report
from recipe_results import verify_result_package
from test_recipe_investigation import BASE, FIX, package, recipe, rehash_report


@pytest.mark.parametrize('reuse', ['same_path', 'copied_package', 'different_bytes_same_id'])
def test_duplicate_original_attempts_refused_before_creating_report(tmp_path, recipe, reuse):
    baseline = package(tmp_path / 'baseline', recipe, BASE)
    if reuse == 'same_path':
        candidate = baseline
    elif reuse == 'copied_package':
        shutil.copytree(baseline.parent, tmp_path / 'copy')
        candidate = tmp_path / 'copy/result.json'
    else:
        # Root basename supplies the fixture ID. Different payloads still reuse it.
        candidate = package(tmp_path / 'other/baseline', recipe, FIX,
                            status='experiment_failed', outcome='reproduced')
        assert candidate.read_bytes() != baseline.read_bytes()
    before = [path.read_bytes() for path in (baseline, candidate)]
    output = tmp_path / 'report'
    with pytest.raises(recipes.ContractError, match='distinct original attempt'):
        write_investigation_report(baseline=baseline, candidate=candidate, output_dir=output)
    assert not output.exists()
    assert [path.read_bytes() for path in (baseline, candidate)] == before


def test_same_image_with_distinct_original_attempts_is_a_valid_pair(tmp_path, recipe):
    baseline = package(tmp_path / 'first', recipe, BASE)
    candidate = package(tmp_path / 'second', recipe, BASE)
    output = tmp_path / 'report'
    report = write_investigation_report(baseline=baseline, candidate=candidate, output_dir=output)
    assert report['assessment']['outcome'] == 'same_observed_reproduction'
    assert verify_investigation_report(output / 'investigation.json')['valid']


def test_resealed_report_cannot_reuse_a_bundled_original_identity(tmp_path, recipe):
    baseline = package(tmp_path / 'first', recipe, BASE)
    candidate = package(tmp_path / 'second', recipe, BASE)
    output = tmp_path / 'report'
    write_investigation_report(baseline=baseline, candidate=candidate, output_dir=output)
    result_path = output / 'candidate/result.json'
    result = json.loads(result_path.read_text())
    result['attempt']['id'] = json.loads(baseline.read_text())['attempt']['id']
    summary = output / 'candidate/SUMMARY.txt'
    summary.write_text(summary.read_text().replace('Attempt: second\n', 'Attempt: first\n'))
    for artifact in result['artifacts']:
        if artifact['path'] == 'SUMMARY.txt':
            artifact['sha256'] = hashlib.sha256(summary.read_bytes()).hexdigest()
    result_path.write_text(json.dumps(result))
    assert verify_result_package(result_path)['valid']
    manifest = output / 'investigation.json'
    report = json.loads(manifest.read_text())
    report['attempts']['candidate']['result_sha256'] = hashlib.sha256(result_path.read_bytes()).hexdigest()
    manifest.write_text(json.dumps(report))
    rehash_report(output)
    with pytest.raises(recipes.ContractError, match='distinct original attempt'):
        verify_investigation_report(manifest)


def test_public_report_command_refuses_reusing_one_attempt(tmp_path, recipe, capsys):
    source = package(tmp_path / 'source', recipe, BASE)
    output = tmp_path / 'report'
    code = recipes.main(['investigation-report', '--baseline', str(source), '--candidate', str(source),
                         '--output-dir', str(output)])
    assert code == 2
    assert 'distinct original attempt' in capsys.readouterr().err
    assert not output.exists()
