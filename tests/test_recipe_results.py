"""Result packages preserve evidence and verify actual bytes without Docker."""
import copy
import hashlib
import json
import os
from pathlib import Path

import pytest

import recipes
from recipe_results import verify_result_package, write_result_package

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def recipe():
    return recipes.read_document(ROOT / 'examples/recipes/synthetic-ipv4.recipe.json')


def package(tmp_path, recipe, **kwargs):
    work = tmp_path / 'source'
    work.mkdir(exist_ok=True)
    (work / 'runtime.json').write_text(json.dumps({'status': kwargs.get('status', 'completed')}))
    (work / 'scenario.yaml').write_text('neighbors: []\n')
    (work / 'target.log').write_text('target evidence\n')
    (work / 'x.events.json').write_text('{}\n')
    (work / 'x.provenance.json').write_text('{}\n')
    (work / 'x.csv').write_text('value\n1\n')
    result = tmp_path / 'result'
    return write_result_package(recipe, results_dir=result, workdir=work,
                                attempt_id='attempt-001', status=kwargs.pop('status', 'completed'),
                                reason='runtime observation', **kwargs)


def test_complete_round_trip_keeps_every_file_and_verifies_recipe(tmp_path, recipe):
    document = package(tmp_path, recipe)
    assert document['status'] == 'completed'
    assert document['reproduction']['outcome'] == 'reproduced'
    assert document['comparison']['qualification'] == 'not_assessed'
    assert {item['kind'] for item in document['artifacts']} == set(recipes.ARTIFACT_KINDS)
    report = verify_result_package(tmp_path / 'result/result.json')
    assert report['valid']
    assert report['artifacts_verified'] == 8
    assert (tmp_path / 'source/target.log').read_bytes() == (tmp_path / 'result/work/target.log').read_bytes()
    assert (tmp_path / 'result/recipe.json').read_text() == recipes.canonical_json(recipe) + '\n'


@pytest.mark.parametrize('status', ['setup_refused', 'harness_failed', 'experiment_failed', 'interrupted', 'inconclusive'])
def test_partial_results_keep_available_evidence_and_missing_observations_unknown(tmp_path, recipe, status):
    document = package(tmp_path, recipe, status=status)
    assert document['reproduction']['outcome'] == 'inconclusive'
    assert document['exit_code'] in recipes.RESULT_EXIT_CODES[status]
    assert verify_result_package(tmp_path / 'result/result.json')['valid']


def test_noncompletion_witness_does_not_decide_reproduction(tmp_path, recipe):
    work = tmp_path / 'source'
    work.mkdir()
    result = write_result_package(recipe, results_dir=tmp_path / 'result', workdir=work,
                                  attempt_id='x', status='completed', reason='missing evidence')
    assert result['reproduction']['outcome'] == 'inconclusive'
    assert all(item['availability'] == 'missing' for item in result['artifacts'] if item['kind'] != 'other')


def test_completed_does_not_reproduce_crash(tmp_path, recipe):
    recipe['reproduction']['expected_outcome'] = 'target_crash'
    assert package(tmp_path, recipe)['reproduction']['outcome'] == 'not_reproduced'


def test_explicit_crash_can_survive_failed_experiment(tmp_path, recipe):
    recipe['reproduction']['expected_outcome'] = 'target_crash'
    reproduction = {'outcome': 'reproduced', 'reason': 'target exit witnessed',
                    'evidence': ['work/runtime.json']}
    result = package(tmp_path, recipe, status='experiment_failed', reproduction=reproduction)
    assert result['status'] == 'experiment_failed'
    assert result['reproduction']['outcome'] == 'reproduced'


@pytest.mark.parametrize('entry', ['file', 'directory', 'fifo'])
def test_unsafe_sources_are_omitted_and_collection_failure_is_explicit(tmp_path, recipe, entry):
    work = tmp_path / 'source'
    work.mkdir()
    secret = tmp_path / 'secret'
    secret.write_text('must not be copied')
    if entry == 'fifo':
        os.mkfifo(work / 'unsafe')
    else:
        (work / 'unsafe').symlink_to(secret if entry == 'file' else tmp_path, target_is_directory=entry == 'directory')
    result = package(tmp_path, recipe)
    assert result['status'] == 'harness_failed'
    assert result['exit_code'] == 3
    assert not (tmp_path / 'result/work/unsafe').exists()
    assert (tmp_path / 'result/collection-errors.json').exists()
    assert verify_result_package(tmp_path / 'result/result.json')['valid']


@pytest.mark.parametrize('mutation', ['changed', 'missing', 'symlink', 'parent_symlink'])
def test_verification_refuses_changed_missing_or_symlink_evidence(tmp_path, recipe, mutation):
    package(tmp_path, recipe)
    artifact = tmp_path / 'result/work/target.log'
    if mutation == 'changed':
        artifact.write_text('changed')
    elif mutation == 'missing':
        artifact.unlink()
    elif mutation == 'symlink':
        artifact.unlink()
        artifact.symlink_to(tmp_path / 'source/target.log')
    else:
        (tmp_path / 'result/work').rename(tmp_path / 'old-work')
        (tmp_path / 'result/work').symlink_to(tmp_path / 'old-work', target_is_directory=True)
    with pytest.raises(recipes.ContractError):
        verify_result_package(tmp_path / 'result/result.json')


def test_verifier_checks_recipe_binding_even_if_file_hash_was_changed(tmp_path, recipe):
    package(tmp_path, recipe)
    path = tmp_path / 'result/recipe.json'
    changed = copy.deepcopy(recipe)
    changed['reproduction']['question'] = 'different question'
    path.write_text(json.dumps(changed))
    manifest_path = tmp_path / 'result/result.json'
    manifest = json.loads(manifest_path.read_text())
    next(a for a in manifest['artifacts'] if a['path'] == 'recipe.json')['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(recipes.ContractError, match='canonical recipe'):
        verify_result_package(manifest_path)


def test_never_overwrites_prior_package(tmp_path, recipe):
    package(tmp_path, recipe)
    original = (tmp_path / 'result/result.json').read_bytes()
    with pytest.raises(recipes.ContractError, match='already exists'):
        write_result_package(recipe, results_dir=tmp_path / 'result', workdir=tmp_path / 'source',
                             attempt_id='replacement', status='harness_failed', reason='retry')
    assert (tmp_path / 'result/result.json').read_bytes() == original


def test_missing_work_is_packaged_as_collection_failure(tmp_path, recipe):
    result = write_result_package(recipe, results_dir=tmp_path / 'result', workdir=tmp_path / 'missing',
                                  attempt_id='x', status='harness_failed', reason='runtime failed')
    assert result['status'] == 'harness_failed'
    assert verify_result_package(tmp_path / 'result/result.json')['valid']


@pytest.mark.parametrize('entry', ['regular', 'symlink_directory', 'fifo', 'root_symlink'])
def test_verification_refuses_unlisted_or_unsafe_package_entries(tmp_path, recipe, entry):
    package(tmp_path, recipe)
    root = tmp_path / 'result'
    if entry == 'regular':
        (root / 'unlisted.txt').write_text('extra evidence')
    elif entry == 'symlink_directory':
        (root / 'unlisted').symlink_to(tmp_path / 'source', target_is_directory=True)
    elif entry == 'fifo':
        os.mkfifo(root / 'unlisted')
    else:
        root.rename(tmp_path / 'old-result')
        root.symlink_to(tmp_path / 'old-result', target_is_directory=True)
    with pytest.raises(recipes.ContractError):
        verify_result_package(root / 'result.json')


def test_unreadable_tree_records_collection_error(tmp_path, recipe, monkeypatch):
    import recipe_results
    walk = os.walk
    def fail_source(top, **kwargs):
        if Path(top).name == 'source':
            kwargs['onerror'](PermissionError('directory unreadable'))
            return iter(())
        return walk(top, **kwargs)
    monkeypatch.setattr(recipe_results.os, 'walk', fail_source)
    document = package(tmp_path, recipe)
    assert document['status'] == 'harness_failed'
    assert 'directory unreadable' in (tmp_path / 'result/collection-errors.json').read_text()


def test_missing_reproduction_evidence_degrades_to_inconclusive(tmp_path, recipe):
    result = package(tmp_path, recipe, status='experiment_failed', reproduction={
        'outcome': 'reproduced', 'reason': 'lost crash witness', 'evidence': ['work/absent.json']})
    assert result['reproduction']['outcome'] == 'inconclusive'
    assert verify_result_package(tmp_path / 'result/result.json')['valid']


def test_fifo_manifest_refused_without_read(tmp_path):
    os.mkfifo(tmp_path / 'result.json')
    with pytest.raises(recipes.ContractError, match='regular file'):
        verify_result_package(tmp_path / 'result.json')


def test_existing_engine_versions_artifact_is_provenance(tmp_path, recipe):
    work = tmp_path / 'source'
    work.mkdir()
    (work / 'bird.versions.json').write_text('{}')
    result = package(tmp_path, recipe)
    artifact = next(item for item in result['artifacts'] if item['path'] == 'work/bird.versions.json')
    assert artifact['kind'] == 'provenance'


def test_non_directory_work_root_is_refused(tmp_path, recipe):
    work = tmp_path / 'source'
    work.write_text('not a tree')
    with pytest.raises(recipes.ContractError, match='directory'):
        write_result_package(recipe, results_dir=tmp_path / 'result', workdir=work,
                             attempt_id='x', status='harness_failed', reason='bad root')
    assert not (tmp_path / 'result').exists()


def test_runtime_socket_is_omitted_without_opening_or_contacting_it(tmp_path, recipe, monkeypatch):
    import socket
    import recipe_results

    work = tmp_path / 'source'
    work.mkdir()
    control = work / 'bird.ctl'
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as endpoint:
        endpoint.bind(str(control))
        control.chmod(0)
        original_open = recipe_results.os.open
        def refuse_socket_open(path, *args, **kwargs):
            assert str(path) != control.name, 'runtime endpoint must not be opened'
            return original_open(path, *args, **kwargs)
        monkeypatch.setattr(recipe_results.os, 'open', refuse_socket_open)
        monkeypatch.setattr(socket.socket, 'connect', lambda *a, **k: pytest.fail('socket contacted'))
        result = package(tmp_path, recipe)
    assert result['status'] == 'completed'
    assert result['reproduction']['outcome'] == 'reproduced'
    assert control.is_socket()  # Original runtime work is retained unchanged.
    assert not (tmp_path / 'result/work/bird.ctl').exists()
    omissions = json.loads((tmp_path / 'result/collection-omissions.json').read_text())
    assert omissions == {'omissions': [{
        'path': 'work/bird.ctl', 'type': 'unix_socket',
        'reason': 'Runtime Unix-domain sockets are not portable evidence files; not read or copied.'}]}
    assert not (tmp_path / 'result/collection-errors.json').exists()
    reference = next(item for item in result['artifacts'] if item['path'] == 'collection-omissions.json')
    assert reference['kind'] == 'other'
    assert reference['availability'] == 'present'
    assert verify_result_package(tmp_path / 'result/result.json')['valid']


def test_socket_omission_does_not_hide_symlink_fifo_or_read_failure(tmp_path, recipe, monkeypatch):
    import socket
    import recipe_results

    work = tmp_path / 'source'
    work.mkdir()
    control = work / 'bird.ctl'
    endpoint = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        endpoint.bind(str(control))
        (work / 'socket-link').symlink_to(control)
        os.mkfifo(work / 'pipe')
        (work / 'unreadable.log').write_text('unreadable regular evidence')
        original_open = recipe_results.os.open
        def refuse_regular_read(path, *args, **kwargs):
            if str(path) == 'unreadable.log':
                raise PermissionError('regular artifact unreadable')
            return original_open(path, *args, **kwargs)
        monkeypatch.setattr(recipe_results.os, 'open', refuse_regular_read)
        result = package(tmp_path, recipe)
    finally:
        endpoint.close()
    assert result['status'] == 'harness_failed'
    errors = json.loads((tmp_path / 'result/collection-errors.json').read_text())['errors']
    assert len(errors) == 3
    assert any('socket-link' in error for error in errors)
    assert any('pipe' in error for error in errors)
    assert any('regular artifact unreadable' in error for error in errors)
    assert len(json.loads((tmp_path / 'result/collection-omissions.json').read_text())['omissions']) == 1
    assert verify_result_package(tmp_path / 'result/result.json')['valid']


def test_verification_still_refuses_socket_inserted_into_package(tmp_path, recipe):
    import socket

    package(tmp_path, recipe)
    artifact = tmp_path / 'result/work/target.log'
    artifact.unlink()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as endpoint:
        endpoint.bind(str(artifact))
        with pytest.raises(recipes.ContractError, match='Unix-domain socket'):
            verify_result_package(tmp_path / 'result/result.json')


def test_regular_control_named_file_is_preserved_as_evidence(tmp_path, recipe):
    work = tmp_path / 'source'
    work.mkdir()
    (work / 'bird.ctl').write_text('regular diagnostic data')
    result = package(tmp_path, recipe)
    assert result['status'] == 'completed'
    assert (tmp_path / 'result/work/bird.ctl').read_text() == 'regular diagnostic data'
    assert not (tmp_path / 'result/collection-omissions.json').exists()
    assert verify_result_package(tmp_path / 'result/result.json')['valid']
