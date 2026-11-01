"""One modeled history connects the public recipe, investigation and search CLIs."""
import ast
import hashlib
import json
from pathlib import Path
import re
import shutil
import socket
import subprocess

import pytest

import recipes
import recipe_bisection as bisection
from recipe_investigation import verify_investigation_report
from recipe_results import verify_result_package
from scripts import maintainer_smoke as smoke


@pytest.fixture(scope='module')
def walked(tmp_path_factory):
    output = tmp_path_factory.mktemp('maintainer') / 'walkthrough'
    return output, smoke.run_smoke(output)


def read(path):
    return json.loads(path.read_text())


def test_one_recipe_and_target_history_connect_all_stages(walked):
    output, summary = walked
    recipe = read(output/'recipe.json')
    reproduction = read(output/'reproduction/result.json')
    investigation = read(output/'return/investigation/investigation.json')
    boundary = read(output/'return/bisection/bisection.json')
    assert summary['simulation'] is True and summary['status'] == 'passed'
    assert recipe['reproduction']['expected_outcome'] == summary['predicate'] == 'target_crash'
    assert summary['recipe_sha256'] == recipes.recipe_sha256(recipe)
    assert {reproduction['recipe_sha256'], investigation['recipe_sha256'],
            recipes.recipe_sha256(boundary['plan']['recipe'])} == {summary['recipe_sha256']}
    assert reproduction['status'] == 'experiment_failed'
    assert reproduction['reproduction']['outcome'] == 'reproduced'
    assert investigation['assessment']['outcome'] == 'baseline_reproduced_candidate_not_reproduced'
    baseline, candidate = (investigation['attempts'][side] for side in ('baseline','candidate'))
    assert baseline['target'] == read(output/'build-baseline/target.json')
    assert candidate['target'] == read(output/'build-candidate/target.json')
    assert baseline['target']['provenance']['source']['commit'] == summary['baseline_revision']
    assert candidate['target']['provenance']['source']['commit'] == summary['candidate_revision']
    assert baseline['target'] == boundary['trials'][1]['observed']['target']
    assert candidate['target'] == boundary['trials'][-2]['observed']['target']
    for role in ('generator','observer'):
        assert baseline['effective_roles'][role] == candidate['effective_roles'][role] == recipe['roles'][role]
    assert 'rollback' in summary['candidate_meaning']
    assert summary['performance_policy'] == 'disabled'
    assert summary['qualification'] == 'not_assessed' and summary['calibration'] == 'deferred'
    assert boundary['performance'] == {'policy':'disabled','qualification':'not_assessed'}


def test_interrupted_result_is_recovered_without_repeating_the_worker(walked):
    output, summary = walked
    before = read(output/'interruption/status.json')
    after = read(output/'interruption/status-after.json')
    recovered = read(output/'interruption/recovery.json')
    original = output/'session/results/t0003/result.json'
    pending = read(output/'interruption/pending.json')
    assert before['conclusion']['state'] == 'recovery_required'
    assert before['trials_recorded'] == 2 and before['trials_reserved'] == 1
    assert before['pending'] == pending
    assert after['pending'] is None and after['trials_recorded'] == 3
    assert recovered['classification'] == 'bad' and recovered['request'] == pending
    original_id = read(original)['attempt']['id']
    assert recovered['observed']['source_attempt_id'] == original_id
    assert summary['interruption_original_sha256'] == hashlib.sha256(original.read_bytes()).hexdigest()
    ids = [attempt['source_attempt_id'] for attempt in summary['attempts']]
    assert len(ids) == len(set(ids)) == 11
    assert ids.count(original_id) == 1
    paused = read(output/'return/pending/bisection.json')
    assert paused['conclusion']['state'] == 'recovery_required' and len(paused['trials']) == 2
    commands = read(output/'commands.json')
    refusals = [record for record in commands if record['exit_code'] == 2]
    assert len(refusals) == 2
    assert 'SIMULATED controller interruption' in refusals[0]['stderr']
    assert 'Pending trial requires explicit recovery' in refusals[1]['stderr']
    assert not (output/'session/pending.json').exists()


def test_boundary_uses_fresh_confirmations_and_matches_rebuilt_report(walked):
    output, summary = walked
    report = read(output/'return/bisection/bisection.json')
    assert report['conclusion'] == summary['conclusion']
    assert summary['conclusion']['state'] == 'confirmed'
    assert summary['conclusion']['last_observed_good'] == report['plan']['candidates'][3]['revision']
    assert summary['conclusion']['first_observed_bad'] == report['plan']['candidates'][4]['revision']
    assert [trial['request']['phase'] for trial in report['trials']][-2:] == ['confirm-good','confirm-bad']
    assert [attempt['index'] for attempt in summary['attempts']][-2:] == [3,4]
    assert len(summary['builds']) == 7  # two stage builds and five cached search builds
    assert report == read(output/'bisection-rebuilt/bisection.json')
    for trial in report['trials']:
        assert verify_result_package(output/'return/bisection'/trial['result'])['valid'] is True
        samples = read((output/'return/bisection'/trial['result']).parent/'work/live-diagnostics.json')['samples']
        assert samples[0]['bird_process_present'] is True
        if trial['classification'] == 'bad':
            assert samples[-1]['bird_process_present'] is False
            assert samples[-1]['daemon_exit_code'] == 139


def test_investigation_rebuild_retains_controller_stop_and_unrun_candidate(walked):
    output, _ = walked
    for source, rebuilt in ((output/'investigation/report',output/'investigation-rebuilt'),
            (output/'investigation-stopped/report',output/'investigation-stopped-rebuilt')):
        assert read(source/'investigation.json') == read(rebuilt/'investigation.json')
    stopped = read(output/'return/investigation-stopped/investigation.json')
    assert stopped['assessment']['outcome'] == 'inconclusive'
    assert stopped['attempts']['baseline']['status'] == 'experiment_failed'
    assert stopped['attempts']['baseline']['availability'] == 'present'
    assert stopped['attempts']['candidate']['status'] == 'not_run'
    assert stopped['attempts']['candidate']['reason']
    stop = read(output/'return/investigation-stopped'/stopped['controller_stop']['path'])
    assert stop['status'] == 'interrupted' and stop['exit_code'] == 143
    assert stop['attempt'] == 'baseline'
    commands = read(output/'commands.json')
    assert len([row for row in commands if row['arguments'][0]=='investigation-rebuild']) == 2


def test_return_evidence_verifies_after_relocation_without_runtime(walked, tmp_path, monkeypatch):
    output, _ = walked
    relocated = tmp_path/'portable'
    shutil.copytree(output/'return',relocated)
    monkeypatch.setattr(subprocess,'Popen',smoke._forbidden)
    monkeypatch.setattr(socket.socket,'__init__',smoke._forbidden)
    monkeypatch.setattr(smoke.targets,'_git',smoke._forbidden)
    monkeypatch.setattr(smoke.targets,'build_target',smoke._forbidden)
    monkeypatch.setattr(smoke.recipe_run,'SubprocessBackend',smoke._forbidden)
    assert verify_result_package(relocated/'reproduction/result.json')['valid'] is True
    assert verify_investigation_report(relocated/'investigation/investigation.json')['valid'] is True
    assert verify_investigation_report(relocated/'investigation-stopped/investigation.json')['valid'] is True
    for name in ('pending','bisection'):
        assert bisection.verify_report(relocated/name/'bisection.json')['valid'] is True
    (relocated/'bisection/REPORT.md').write_text('Changed human conclusion\n')
    with pytest.raises(recipes.ContractError):
        bisection.verify_report(relocated/'bisection/bisection.json')


def test_human_index_links_retained_stages_and_command_transcripts(walked):
    output, _ = walked
    text = (output/'REPORT.md').read_text()
    assert 'SIMULATED' in text and 'rollback' in text
    for relative in re.findall(r'\]\(([^)]+)\)',text):
        assert (output/relative).is_file(),relative
    records = read(output/'commands.json')
    assert records == [read(path) for path in sorted((output/'commands').glob('*.json'))]
    assert {'export','run','investigate','step','recover','report','verify'} <= {
        record['arguments'][0] for record in records}
    assert all(record['valid'] for record in read(output/'verification.json').values())


def test_guards_cover_setup_and_unmodelled_commands(tmp_path, monkeypatch):
    def probe(output):
        for action in (lambda:subprocess.Popen(['unexpected']),
                       lambda:socket.create_connection(('example.invalid',1)),
                       lambda:socket.socket(socket.AF_INET,socket.SOCK_DGRAM),
                       lambda:socket.socket.sendto(None,b'never sent',('127.0.0.1',1))):
            with pytest.raises(AssertionError,match='unmodelled'):
                action()
        return {'simulation':True}
    monkeypatch.setattr(smoke,'_run_smoke',probe)
    assert smoke.run_smoke(tmp_path/'guard') == {'simulation':True}
    recipe = read(smoke.ROOT/'examples/recipes/synthetic-ipv4.recipe.json')
    host = smoke.BisectionHost(recipe)
    with pytest.raises(AssertionError,match='unmodelled'):
        host.command(['docker','pull','unselected:latest'])


def test_refuses_existing_relative_checkout_and_symlink_outputs(tmp_path):
    existing = tmp_path/'existing'
    existing.mkdir()
    sentinel = existing/'keep'
    sentinel.write_text('untouched')
    with pytest.raises(FileExistsError):
        smoke.run_smoke(existing)
    assert list(existing.iterdir()) == [sentinel] and sentinel.read_text() == 'untouched'
    with pytest.raises(ValueError,match='absolute'):
        smoke.run_smoke('relative')
    with pytest.raises(ValueError,match='outside'):
        smoke.run_smoke(smoke.ROOT/'new-artifacts')
    alias = tmp_path/'alias'
    alias.symlink_to(tmp_path,target_is_directory=True)
    with pytest.raises(ValueError,match='symlinks'):
        smoke.run_smoke(alias/'new-artifacts')


def test_entrypoint_works_from_another_directory_and_imports_no_tests(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert smoke.main(['--output',str(tmp_path/'standalone')]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert Path(summary['index']).is_file()
    assert summary['status'] == 'passed'
    for node in ast.walk(ast.parse(Path(smoke.__file__).read_text())):
        if isinstance(node,ast.ImportFrom):
            assert not (node.module or '').startswith(('test_','tests'))
        elif isinstance(node,ast.Import):
            assert all(not alias.name.startswith(('test_','tests')) for alias in node.names)
