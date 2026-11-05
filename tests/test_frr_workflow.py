"""Public FRR role payloads survive all maintained modeled workflow stages."""
import json
from pathlib import Path
import re
import shutil
import socket
import subprocess

import pytest

import recipes
from scripts import frr_workflow_smoke as smoke


def read(path):
    return json.loads(path.read_text())


@pytest.fixture(scope='module')
def walked(tmp_path_factory):
    output = tmp_path_factory.mktemp('frr-workflow') / 'walkthrough'
    return output, smoke.run_smoke(output)


def test_target_and_fixed_other_roles_propagate_through_every_worker(walked):
    output, summary = walked
    recipe = read(output / 'recipe.json')
    assert recipe['resolved']['target']['name'] == 'frr_c'
    assert recipe['roles']['target']['adapter'] == 'frr_c'
    assert summary['target_adapter'] == 'frr_c'
    assert summary['status'] == 'passed' and summary['simulation']
    attempts = summary['attempts'] + summary['staged']['attempts']
    assert len(attempts) == 14
    assert len({item['id'] for item in attempts}) == len(attempts)
    for attempt in attempts:
        assert attempt['target']['name'] == 'frr_c'
        assert attempt['roles']['target']['adapter'] == 'frr_c'
        for role in ('generator', 'observer'):
            assert attempt['roles'][role] == recipe['roles'][role]
    assert {item['roles']['target']['image'] for item in attempts} == {
        smoke.BASELINE_IMAGE, smoke.CANDIDATE_IMAGE}
    assert read(output / 'baseline.json')['provenance']['source'] is None
    assert read(output / 'candidate.json')['provenance']['source'] is None


def test_six_assertions_and_investigation_keep_correctness_separate(walked):
    output, summary = walked
    assert len(read(output / 'assertions.json')['assertions']) == 6
    assertions = {item['name']: item for item in summary['assertions']['assertions']}
    assert assertions['observer.count']['status'] == 'failed'
    assert assertions['observer.prefixes']['status'] == 'failed'
    assert read(output / 'reproduction/result.json')['status'] == 'completed'
    report = read(output / 'return/investigation/investigation.json')
    assert report['correctness']['attempts']['baseline']['outcome'] == 'failed'
    assert report['correctness']['attempts']['candidate']['outcome'] == 'passed'
    assert recipes.main(['investigation-check', str(output / 'return/incomplete/investigation.json'),
                         '--side', 'candidate']) == 5
    assert report == read(output / 'investigation-rebuilt/investigation.json')


def test_comparison_and_minimization_keep_originals_and_frr_identity(walked):
    output, summary = walked
    report = read(output / 'return/comparison/comparison.json')
    assert len(report['attempts']) == 4 and report['plan']['observer_prefixes']
    assert report['correctness']['baseline']['failed'] == 2
    assert report['correctness']['candidate']['passed'] == 2
    assert report == read(output / 'comparison-rebuilt/comparison.json')
    assert summary['minimization']['confirmed']
    assert summary['minimization']['best']['routes'] == 2
    reduced = read(output / 'return/minimization/minimization.json')
    assert reduced == read(output / 'minimization-rebuilt/minimization.json')
    assert summary['attempts'][-1]['routes'] == 2
    assert summary['attempts'][-1]['selected_failure']
    assert summary['performance_policy'] == 'disabled'
    assert summary['qualification'] == 'not_assessed' and summary['calibration'] == 'deferred'


def test_staged_controller_assesses_each_original_and_requires_both_reviews(walked):
    output, summary = walked
    staged = summary['staged']
    assert staged['simulation'] and staged['status'] == 'complete'
    assert len(staged['attempts']) == 2
    assert all(item['capture_selected'] and not item['selected_failure'] for item in staged['attempts'])
    session = read(output / 'staged/session.json')
    assert session['stage'] == 'complete' and session['next_index'] == 2
    receipt, original = smoke.comparison_session.validate_review(output / 'staged/reviews/final.json', final=True)
    assert receipt == staged['final_review']
    report = read(output / 'return/staged/comparison.json')
    assert report == original == read(output / 'staged-rebuilt/comparison.json')
    assert report['correctness']['baseline']['passed'] == report['correctness']['candidate']['passed'] == 1
    assert all(len(item['assertions']['assertions']) == 6 for item in report['attempts'])
    refused = [row for row in read(output / 'commands.json')
               if row['arguments'][0] == 'comparison-step' and row['exit_code'] == 2]
    assert len(refused) == 3
    assert all(any(stage in row['stderr'] for stage in ('first_review', 'final_review', 'complete'))
               for row in refused)


def test_portable_receipts_links_and_tamper_refusal(walked, tmp_path, monkeypatch):
    output, _ = walked
    assert all(item['valid'] for item in read(output / 'verification.json').values())
    records = read(output / 'commands.json')
    assert records == [read(path) for path in sorted((output / 'commands').glob('*.json'))]
    assert records[-1]['arguments'][0] == 'comparison-verify' and records[-1]['exit_code'] == 2
    for relative in re.findall(r'\]\(([^)]+)\)', (output / 'REPORT.md').read_text()):
        assert (output / relative).is_file()
    relocated = tmp_path / 'relocated'
    shutil.copytree(output / 'return', relocated)
    monkeypatch.setattr(subprocess, 'Popen', smoke._forbidden)
    monkeypatch.setattr(socket.socket, '__init__', smoke._forbidden)
    monkeypatch.setattr(smoke.recipe_run, 'SubprocessBackend', smoke._forbidden)
    assert recipes.main(['investigation-verify', str(relocated / 'investigation/investigation.json')]) == 0
    assert recipes.main(['comparison-verify', str(relocated / 'comparison/comparison.json')]) == 0


def test_global_guard_covers_setup_and_execution(tmp_path, monkeypatch):
    def guarded(output):
        for argv in (['git', '--version'], ['docker', 'build', '.'], ['unexpected']):
            with pytest.raises(AssertionError, match='unmodelled'):
                subprocess.Popen(argv)
        with pytest.raises(AssertionError, match='unmodelled'):
            socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        with pytest.raises(AssertionError, match='unmodelled'):
            socket.create_connection(('example.invalid', 1))
        return {'guarded': True}
    monkeypatch.setattr(smoke, '_run_smoke', guarded)
    assert smoke.run_smoke(tmp_path / 'guard') == {'guarded': True}


def test_output_refusals_preserve_existing_files(tmp_path):
    existing = tmp_path / 'existing'
    existing.mkdir()
    sentinel = existing / 'keep'
    sentinel.write_text('retained')
    with pytest.raises(FileExistsError):
        smoke.run_smoke(existing)
    assert sentinel.read_text() == 'retained'
    with pytest.raises(recipes.ContractError, match='absolute'):
        smoke.run_smoke('relative')
    with pytest.raises(ValueError, match='outside'):
        smoke.run_smoke(smoke.ROOT / 'new-frr-output')
    alias = tmp_path / 'alias'
    alias.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(recipes.ContractError, match='symlinks'):
        smoke.run_smoke(alias / 'new')


def test_cli_from_another_directory(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    user_store = tmp_path / 'user-store'
    monkeypatch.setenv('BGPERF_ARTIFACT_STORE', str(user_store))
    assert smoke.main(['--output', str(tmp_path / 'standalone')]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['status'] == 'passed' and Path(result['index']).is_file()
    assert not user_store.exists()
