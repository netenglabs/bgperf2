"""Real inert Git preparation connects explicitly SIMULATED prefix stages."""
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess

import pytest

import recipe_bisection as bisection
from recipe_comparison_report import verify_comparison_report
from recipe_investigation import check_investigation, verify_investigation_report
from recipe_results import verify_result_package
import recipes
from scripts import prefix_workflow_smoke as smoke


def read(path):
    return json.loads(path.read_text())


def rows(answer):
    return {row['name']: row for row in answer['assertions']}


def paths(output):
    destinations = read(output / 'checkout/handoff/handoff.json')['destinations']
    return {name: Path(value) for name, value in destinations.items()}


@pytest.fixture(scope='module')
def walked(tmp_path_factory):
    output = tmp_path_factory.mktemp('prefix-workflow') / 'walkthrough'
    return output, smoke.run_smoke(output)


def test_actual_inert_git_and_prepared_handoff_are_the_executed_inputs(walked):
    output, summary = walked
    checkout = output / 'checkout'
    assert read(checkout / 'original-before.json') == read(checkout / 'original-after.json')
    assert read(output / 'source-before.json') == read(output / 'source-after.json')
    assert read(output / 'prepared-before.json') == read(output / 'prepared-after.json')
    assert summary['simulation'] is summary['real_local_git_preparation'] is True
    assert summary['original_source_preserved'] is summary['prepared_sources_preserved'] is True
    assert summary['status'] == 'passed'
    assert not (checkout / 'UNEXPECTED-HOOK-EXECUTION').exists()
    plan = read(checkout / 'prepared-range/bisection-plan.json')
    handoff_plan = read(checkout / 'handoff/inputs/bisection-plan.json')
    assert plan == handoff_plan and plan['predicate'] == 'prefix_assertions'
    assert len(plan['candidates']) == 4
    bisection.validate_plan(plan)  # Real commit proofs bind their actual first-parent chain.
    candidate = read(checkout / 'candidate-build-plan.json')
    assert candidate['source']['dirty'] is candidate['source']['include_dirty'] is True
    assert candidate['source']['commit'] == summary['baseline_revision']
    assert candidate['recipe_sha256'] == summary['recipe_sha256']
    graph = read(checkout / 'handoff/commands.json')
    executed = read(output / 'commands.json')
    for name in ('reproduce', 'investigate', 'plan_comparison'):
        step = next(item for item in graph['steps'] if item['id'] == name)
        assert '--observer-prefixes' in step['argv']
        assert any(row['arguments'] == step['argv'][2:] for row in executed)
    assert all(step['execution'] == 'not_requested' for step in graph['steps'])
    assert summary['performance_policy'] == 'disabled'
    assert summary['qualification'] == 'not_assessed' and summary['calibration'] == 'deferred'


def test_count_pass_identity_failure_candidate_ci_and_missing_evidence_are_distinct(walked):
    output, summary = walked
    returned = output / 'return'
    reproduction = read(returned / 'reproduction/result.json')
    assert reproduction['status'] == 'completed'
    assertion = rows(summary['reproduction_assertions'])
    assert assertion['observer.count']['status'] == 'passed'
    assert assertion['observer.count']['observed'] == 100
    identity = assertion['observer.prefixes']
    assert identity['status'] == 'failed'
    assert identity['observed']['missing_count'] == identity['observed']['unexpected_count'] == 1
    investigation = read(returned / 'investigation/investigation.json')
    assert investigation['correctness']['attempts']['baseline']['outcome'] == 'failed'
    assert investigation['correctness']['attempts']['candidate']['outcome'] == 'passed'
    assert check_investigation(returned / 'investigation/investigation.json')['exit_code'] == 4
    candidate = check_investigation(returned / 'investigation/investigation.json', side='candidate')
    assert candidate['exit_code'] == 0 and candidate['checked_attempts'] == ['candidate']
    missing = check_investigation(returned / 'incomplete/investigation.json', side='candidate')
    assert missing['exit_code'] == 5 and missing['attempts']['candidate']['attempt_id'] is None
    assert (summary['both_check'], summary['candidate_check'], summary['missing_candidate_check']) == (
        'failed', 'passed', 'inconclusive')


def test_repeated_comparison_keeps_four_originals_and_withholds_timing_deltas(walked):
    output, _ = walked
    report = read(output / 'return/comparison/comparison.json')
    assert report['plan']['observer_prefixes'] is True and report['plan']['repetitions'] == 2
    assert len(report['attempts']) == 4
    originals = [read(output / 'return/comparison' / attempt['package'])['attempt']['id']
                 for attempt in report['attempts']]
    assert len(set(originals)) == 4
    for attempt in report['attempts']:
        answers = rows(attempt['assertions'])
        assert answers['observer.count']['status'] == 'passed'
        assert answers['observer.count']['observed'] == 100
        expected = 'failed' if attempt['role'] == 'baseline' else 'passed'
        assert answers['observer.prefixes']['status'] == expected
    assert report['correctness']['baseline']['failed'] == report['correctness']['candidate']['passed'] == 2
    assert any('prefix' in item['code'] for item in report['confounders'])
    assert all(item['candidate_minus_baseline_median'] is None and item['reason']
               for item in report['descriptive_deltas']['timing'].values())
    assert report['performance']['policy'] == 'disabled'
    assert report['performance']['qualification'] == 'not_assessed' and report['performance']['reason']
    assert report == read(output / 'comparison-rebuilt/comparison.json')


def test_pending_original_recovery_and_fresh_confirmations_do_not_reuse_workers(walked):
    output, summary = walked
    session = paths(output)['session']
    pending = read(output / 'interruption/pending.json')
    status = read(output / 'interruption/status.json')
    recovered = read(output / 'interruption/recovery.json')
    original = session / 'results/t0003/result.json'
    assert status['conclusion']['state'] == 'recovery_required'
    assert status['trials_recorded'] == 2 and status['trials_reserved'] == 1
    assert recovered['request'] == pending
    assert recovered['observed']['source_attempt_id'] == read(original)['attempt']['id']
    assert hashlib.sha256(original.read_bytes()).hexdigest() == summary['interruption_original_sha256']
    assert not (session / 'pending.json').exists()
    attempts = summary['attempts']
    ids = [item['source_attempt_id'] for item in attempts]
    assert len(ids) == len(set(ids)) == 13
    assert ids.count(recovered['observed']['source_attempt_id']) == 1
    assert all(item['capture_selected'] for item in attempts)
    assert len(summary['builds']) == 6  # Two stage builds, four source-identity search cache entries.
    assert [item['index'] for item in attempts][-2:] == [1, 2]
    report = read(output / 'return/bisection/bisection.json')
    assert len(report['trials']) == 6
    assert report['conclusion'] == summary['conclusion']
    assert report['conclusion']['state'] == 'confirmed'
    assert report['conclusion']['last_observed_good'] == report['plan']['candidates'][1]['revision']
    assert report['conclusion']['first_observed_bad'] == report['plan']['candidates'][2]['revision']
    assert [item['request']['phase'] for item in report['trials']][-2:] == ['confirm-good', 'confirm-bad']
    for trial in report['trials']:
        answers = rows(trial['observed']['assertions'])
        assert answers['observer.count']['status'] == 'passed'
        assert answers['observer.prefixes']['status'] == ('failed' if trial['classification'] == 'bad' else 'passed')
    assert report == read(output / 'bisection-rebuilt/bisection.json')
    refused = [record for record in read(output / 'commands.json') if record['exit_code'] == 2]
    assert len(refused) == 2 and 'Pending trial requires explicit recovery' in refused[1]['stderr']


def test_relocated_reports_verify_with_runtime_forbidden_and_reject_rehashed_tamper(walked, tmp_path, monkeypatch):
    output, _ = walked
    relocated = tmp_path / 'relocated'
    shutil.copytree(output / 'return', relocated)
    monkeypatch.setattr(subprocess, 'Popen', smoke._forbidden)
    monkeypatch.setattr(socket.socket, '__init__', smoke._forbidden)
    monkeypatch.setattr(smoke.targets, '_git', smoke._forbidden)
    monkeypatch.setattr(smoke.targets, 'build_target', smoke._forbidden)
    monkeypatch.setattr(smoke.recipe_run, 'SubprocessBackend', smoke._forbidden)
    assert verify_result_package(relocated / 'reproduction/result.json')['valid']
    for name in ('investigation', 'incomplete'):
        assert verify_investigation_report(relocated / name / 'investigation.json')['valid']
    assert verify_comparison_report(relocated / 'comparison/comparison.json')['valid']
    for name in ('pending', 'bisection'):
        assert bisection.verify_report(relocated / name / 'bisection.json')['valid']
    path = relocated / 'comparison/REPORT.md'
    path.write_text('SIMULATED unsupported successful prefix verdict\n')
    checksums = read(relocated / 'comparison/checksums.json')
    for entry in checksums['files']:
        entry['sha256'] = hashlib.sha256((relocated / 'comparison' / entry['path']).read_bytes()).hexdigest()
    (relocated / 'comparison/checksums.json').write_text(json.dumps(checksums))
    with pytest.raises(recipes.ContractError):
        verify_comparison_report(relocated / 'comparison/comparison.json')


def test_readable_index_and_per_command_receipts_are_complete(walked):
    output, _ = walked
    text = (output / 'REPORT.md').read_text()
    assert 'SIMULATED' in text and 'no BIRD source' in text
    for relative in re.findall(r'\]\(([^)]+)\)', text):
        assert (output / relative).is_file(), relative
    records = read(output / 'commands.json')
    assert records == [read(path) for path in sorted((output / 'commands').glob('*.json'))]
    assert {'target-build', 'run', 'investigate', 'investigation-check', 'comparison-plan',
            'compare', 'step', 'recover', 'verify'} <= {item['arguments'][0] for item in records}
    assert all(item['valid'] for item in read(output / 'verification.json').values())


def test_setup_and_execution_guards_have_separate_process_boundaries(tmp_path, monkeypatch):
    def setup(output, predicate):
        assert predicate == 'prefix_assertions'
        for command in (['docker', 'build', '.'], ['python', '-c', 'pass'],
                        ['git', 'fetch', 'https://example.invalid/source'],
                        ['git', 'clone', 'https://example.invalid/source']):
            with pytest.raises(AssertionError, match='unmodelled'):
                subprocess.Popen(command)
        with pytest.raises(AssertionError, match='unmodelled'):
            socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        return {'setup_guarded': True}
    def execute(output):
        for command in (['git', '--version'], ['docker', 'inspect', 'fixture'], ['unexpected']):
            with pytest.raises(AssertionError, match='unmodelled'):
                subprocess.Popen(command)
        for action in (lambda: socket.create_connection(('example.invalid', 1)),
                       lambda: socket.socket(socket.AF_INET, socket.SOCK_DGRAM),
                       lambda: socket.socket.sendto(None, b'never sent', ('127.0.0.1', 1))):
            with pytest.raises(AssertionError, match='unmodelled'):
                action()
        return {'execution_guarded': True}
    monkeypatch.setattr(smoke.checkout, '_run_smoke', setup)
    monkeypatch.setattr(smoke, '_run_stages', execute)
    assert smoke.run_smoke(tmp_path / 'guarded') == {'execution_guarded': True}


def test_refuses_existing_relative_checkout_and_symlink_destinations(tmp_path):
    existing = tmp_path / 'existing'
    existing.mkdir()
    sentinel = existing / 'keep'
    sentinel.write_text('retained')
    with pytest.raises(FileExistsError):
        smoke.run_smoke(existing)
    assert list(existing.iterdir()) == [sentinel] and sentinel.read_text() == 'retained'
    with pytest.raises(recipes.ContractError, match='absolute'):
        smoke.run_smoke('relative')
    with pytest.raises(ValueError, match='outside'):
        smoke.run_smoke(smoke.ROOT / 'new-prefix-output')
    alias = tmp_path / 'alias'
    alias.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(recipes.ContractError, match='symlinks'):
        smoke.run_smoke(alias / 'new-prefix-output')


@pytest.mark.parametrize('entry', ['symlink', 'fifo'])
def test_preservation_snapshot_refuses_unexpected_special_entries(tmp_path, entry):
    root = tmp_path / 'inputs'
    root.mkdir()
    (root / 'regular').write_text('retained fixture')
    if entry == 'symlink':
        (root / 'unexpected').symlink_to(root / 'regular')
    else:
        os.mkfifo(root / 'unexpected')
    with pytest.raises(recipes.ContractError, match='Unexpected'):
        smoke._tree(root)


def test_cli_from_another_directory_and_no_test_fixture_imports(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert smoke.main(['--output', str(tmp_path / 'standalone')]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary['status'] == 'passed' and Path(summary['index']).is_file()
    for node in ast.walk(ast.parse(Path(smoke.__file__).read_text())):
        if isinstance(node, ast.ImportFrom):
            assert not (node.module or '').startswith(('test_', 'tests'))
        elif isinstance(node, ast.Import):
            assert all(not alias.name.startswith(('test_', 'tests')) for alias in node.names)
