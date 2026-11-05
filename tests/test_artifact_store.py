"""Immutable storage, concurrent publication, integrity and safe reclamation."""
import hashlib
import io
import json
import multiprocessing
import os
from pathlib import Path
import sqlite3
import time

import pytest

from artifact_store import (CATALOG, Store, StorageError, capture_tree,
                            export_tree, load_catalog, reclaim, verify_tree)
from recipe_results import write_result_package, verify_result_package
import recipes


def writer(root):
    Store(root).put(io.BytesIO(b'identical concurrent evidence' * 10000))


def old(path):
    stamp = time.time() - 90000
    os.utime(path, (stamp, stamp))


def test_concurrent_writers_publish_one_valid_object(tmp_path):
    context = multiprocessing.get_context('spawn')
    workers = [context.Process(target=writer, args=(str(tmp_path / 'store'),)) for _ in range(4)]
    for process in workers:
        process.start()
    for process in workers:
        process.join(30)
        assert process.exitcode == 0
    assert len(list((tmp_path / 'store/objects').glob('*/*.zst'))) == 1
    assert not list((tmp_path / 'store/staging').iterdir())
    writer(str(tmp_path / 'store'))  # also verifies existing object on reuse


def test_capture_reclaim_export_and_repeat_reports_store_one_copy(tmp_path):
    store = Store(tmp_path / 'store')
    source = tmp_path / 'work'
    source.mkdir()
    large = b'route evidence\n' * 100000
    (source / 'peer.log').write_bytes(large)
    (source / 'scenario.yaml').write_text('small: retained\n')
    first = tmp_path / 'attempt'
    capture_tree(source, first, store)
    assert not (first / 'peer.log').exists()
    assert (first / 'scenario.yaml').is_file()
    for i in range(5):
        capture_tree(first, tmp_path / f'report-{i}', store)
    assert len(list(store.root.glob('objects/*/*.zst'))) == 1
    assert verify_tree(tmp_path / 'report-4')['stored_files_verified'] == 1
    assert reclaim(source, first)['removed'] == ['peer.log']
    assert (source / 'scenario.yaml').is_file()
    export_tree(first, tmp_path / 'export')
    assert (tmp_path / 'export/peer.log').read_bytes() == large


def test_gc_only_collects_old_orphans_and_rebuilds_index(tmp_path):
    store = Store(tmp_path / 'store')
    source = tmp_path / 'work'
    source.mkdir()
    (source / 'peer.conf').write_bytes(b'a' * (1024 * 1024))
    capture_tree(source, tmp_path / 'attempt', store)
    for obj in store.root.glob('objects/*/*.zst'):
        old(obj)
    orphan = store.put(io.BytesIO(b'unreferenced data'))
    old(store.object_path(orphan))
    recent = store.put(io.BytesIO(b'recent unpublished object'))
    staging = store.root / 'staging/.pending-crashed'
    staging.write_bytes(b'partial')
    old(staging)
    converter = store.root / 'staging/.parquet-export-crashed'
    converter.mkdir()
    (converter / 'partial.parquet').write_bytes(b'partial converter bytes')
    old(converter)
    report = store.maintain()
    assert report['orphan_objects'] == [str(store.object_path(orphan))]
    assert store.object_path(orphan).exists()
    report = store.maintain(apply=True)
    assert report['evidence_expired'] == 0
    assert report['objects_verified'] == 1
    assert not store.object_path(orphan).exists()
    assert not staging.exists()
    assert not converter.exists()
    assert store.object_path(recent).exists()
    assert verify_tree(tmp_path / 'attempt')['valid']
    with sqlite3.connect(store.root / 'index.sqlite') as db:
        assert db.execute('select count(*) from objects').fetchone()[0] == 2
        assert db.execute('select count(*) from packages').fetchone()[0] == 1
    assert store.maintain(apply=True)['orphan_objects'] == []


def test_corrupt_object_refuses_read_reuse_reclaim_and_gc(tmp_path):
    store = Store(tmp_path / 'store')
    source = tmp_path / 'work'
    source.mkdir()
    raw = b'z' * (1024 * 1024)
    (source / 'peer.log').write_bytes(raw)
    capture_tree(source, tmp_path / 'attempt', store)
    ref = load_catalog(tmp_path / 'attempt')['files']['peer.log']
    store.object_path(ref).write_bytes(b'broken zstd frame')
    for action in (lambda: verify_tree(tmp_path / 'attempt'),
                   lambda: store.put(io.BytesIO(raw)),
                   lambda: reclaim(source, tmp_path / 'attempt'),
                   lambda: store.maintain(apply=True)):
        with pytest.raises((StorageError, OSError)):
            action()
    assert (source / 'peer.log').read_bytes() == raw


def test_changed_work_retained_and_unsafe_paths_refused(tmp_path):
    store = Store(tmp_path / 'store')
    source = tmp_path / 'work'
    source.mkdir()
    (source / 'peer.conf').write_bytes(b'c' * (1024 * 1024))
    capture_tree(source, tmp_path / 'attempt', store)
    (source / 'peer.conf').write_bytes(b'new evidence')
    with pytest.raises(StorageError, match='changed'):
        reclaim(source, tmp_path / 'attempt')
    assert (source / 'peer.conf').read_bytes() == b'new evidence'
    (source / 'alias').symlink_to(tmp_path / 'attempt', target_is_directory=True)
    with pytest.raises(StorageError, match='Symlink'):
        capture_tree(source, tmp_path / 'refused', store)
    with pytest.raises(StorageError):
        capture_tree(source, source / 'nested', store)


def test_missing_rooted_object_prevents_gc_of_other_orphans(tmp_path):
    store = Store(tmp_path / 'store')
    source = tmp_path / 'work'
    source.mkdir()
    (source / 'peer.log').write_bytes(b'q' * (1024 * 1024))
    capture_tree(source, tmp_path / 'attempt', store)
    ref = load_catalog(tmp_path / 'attempt')['files']['peer.log']
    orphan = store.put(io.BytesIO(b'orphan'))
    old(store.object_path(orphan))
    store.object_path(ref).unlink()
    with pytest.raises(StorageError, match='missing'):
        store.maintain(apply=True)
    assert store.object_path(orphan).exists()


def test_malformed_root_record_refuses_cleanly_before_any_gc(tmp_path):
    store = Store(tmp_path / 'store')
    orphan = store.put(io.BytesIO(b'orphan'))
    old(store.object_path(orphan))
    raw = json.dumps({'schema': 'bgperf2/artifact-store/v1'}).encode()
    (store.root / 'roots' / (hashlib.sha256(raw).hexdigest() + '.json')).write_bytes(raw)
    with pytest.raises(StorageError, match='Invalid root record'):
        store.maintain(apply=True)
    assert store.object_path(orphan).exists()


def test_result_schema_and_portable_export_survive_without_original_store(tmp_path, monkeypatch):
    monkeypatch.setenv('BGPERF_ARTIFACT_STORE', str(tmp_path / 'store'))
    recipe = recipes.read_document(Path(__file__).parents[1] / 'examples/recipes/synthetic-ipv4.recipe.json')
    work = tmp_path / 'work'
    work.mkdir()
    raw = b'configuration\n' * 100000
    (work / 'peer.conf').write_bytes(raw)
    result = write_result_package(recipe, results_dir=tmp_path / 'result', workdir=work,
                                  attempt_id='stored', status='experiment_failed', reason='controlled')
    assert result['status'] == 'experiment_failed'
    assert verify_result_package(tmp_path / 'result/result.json')['valid']
    assert not (tmp_path / 'result/work/peer.conf').exists()
    export_tree(tmp_path / 'result', tmp_path / 'portable')
    assert not (tmp_path / 'portable' / CATALOG).exists()
    os.rename(tmp_path / 'store', tmp_path / 'absent-store')
    assert verify_result_package(tmp_path / 'portable/result.json')['valid']
    assert (tmp_path / 'portable/work/peer.conf').read_bytes() == raw
    with pytest.raises(recipes.ContractError):
        verify_result_package(tmp_path / 'result/result.json')


def test_unlisted_catalog_reference_is_not_silently_accepted(tmp_path, monkeypatch):
    monkeypatch.setenv('BGPERF_ARTIFACT_STORE', str(tmp_path / 'store'))
    recipe = recipes.read_document(Path(__file__).parents[1] / 'examples/recipes/synthetic-ipv4.recipe.json')
    work = tmp_path / 'work'; work.mkdir()
    write_result_package(recipe, results_dir=tmp_path / 'result', workdir=work,
                         attempt_id='x', status='interrupted', reason='controlled')
    path = tmp_path / 'result' / CATALOG
    data = json.loads(path.read_text())
    data['files']['not-in-result'] = Store(tmp_path / 'store').put(io.BytesIO(b'other'))
    path.write_text(json.dumps(data))
    with pytest.raises(recipes.ContractError, match='Unlisted stored'):
        verify_result_package(tmp_path / 'result/result.json')


def test_compound_capture_refuses_instead_of_losing_nested_object_roots(tmp_path):
    store = Store(tmp_path / 'store')
    source = tmp_path / 'work'; source.mkdir()
    (source / 'peer.log').write_bytes(b'r' * (1024 * 1024))
    capture_tree(source, tmp_path / 'report/attempt', store)
    with pytest.raises(StorageError, match='individual stored packages'):
        capture_tree(tmp_path / 'report', tmp_path / 'other', store)
    assert not (tmp_path / 'other').exists()
    export_tree(tmp_path / 'report', tmp_path / 'portable-report')
    assert (tmp_path / 'portable-report/attempt/peer.log').read_bytes() == b'r' * (1024 * 1024)


def test_legacy_result_paths_with_parent_components_still_verify(tmp_path):
    recipe = recipes.read_document(Path(__file__).parents[1] / 'examples/recipes/synthetic-ipv4.recipe.json')
    work = tmp_path / 'work'; work.mkdir()
    write_result_package(recipe, results_dir=tmp_path / 'result', workdir=work,
                         attempt_id='legacy', status='interrupted', reason='controlled')
    assert verify_result_package(tmp_path / 'work/../result/result.json')['valid']
    alias = tmp_path / 'alias'
    alias.symlink_to(tmp_path, target_is_directory=True)
    assert verify_result_package(alias / 'result/result.json')['valid']


def test_storage_collection_error_still_publishes_partial_result(tmp_path, monkeypatch):
    monkeypatch.setenv('BGPERF_ARTIFACT_STORE', str(tmp_path / 'store'))
    monkeypatch.setattr(Store, '_put', lambda *a: (_ for _ in ()).throw(StorageError('Source changed')))
    recipe = recipes.read_document(Path(__file__).parents[1] / 'examples/recipes/synthetic-ipv4.recipe.json')
    work = tmp_path / 'work'; work.mkdir()
    (work / 'peer.log').write_bytes(b'partial\n' * 150000)
    document = write_result_package(recipe, results_dir=tmp_path / 'result', workdir=work,
                                    attempt_id='partial', status='completed', reason='controlled')
    assert document['status'] == 'harness_failed'
    assert (work / 'peer.log').is_file()
    assert (tmp_path / 'result/collection-errors.json').is_file()
    assert verify_result_package(tmp_path / 'result/result.json')['valid']


def test_bisection_transport_inventory_is_rebuilt_on_export(tmp_path):
    source = tmp_path / 'source'; source.mkdir()
    (source / 'peer.log').write_bytes(b'raw\n' * 300000)
    root = tmp_path / 'report'
    capture_tree(source, root / 'evidence/trial', Store(tmp_path / 'store'))
    (root / 'bisection.json').write_text('{"scope":"transport inventory fixture"}')
    files = [{'path': p.relative_to(root).as_posix(), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
             for p in root.rglob('*') if p.is_file()]
    (root / 'checksums.json').write_text(json.dumps({'files': files}))
    export_tree(root, tmp_path / 'portable')
    expected = {p.relative_to(tmp_path / 'portable').as_posix() for p in (tmp_path / 'portable').rglob('*')
                if p.is_file() and p.name != 'checksums.json'}
    manifest = json.loads((tmp_path / 'portable/checksums.json').read_text())
    assert set(manifest) == {'files'}
    assert {item['path'] for item in manifest['files']} == expected


def test_unconfigured_report_copy_does_not_write_to_source_store(tmp_path, monkeypatch):
    from recipe_investigation import _copy_package
    monkeypatch.setenv('BGPERF_ARTIFACT_STORE', str(tmp_path / 'store'))
    recipe = recipes.read_document(Path(__file__).parents[1] / 'examples/recipes/synthetic-ipv4.recipe.json')
    work = tmp_path / 'work'; work.mkdir()
    raw = b'logs\n' * 300000
    (work / 'peer.log').write_bytes(raw)
    result = write_result_package(recipe, results_dir=tmp_path / 'result', workdir=work,
                                  attempt_id='readonly', status='interrupted', reason='controlled')
    monkeypatch.delenv('BGPERF_ARTIFACT_STORE')
    monkeypatch.setattr(Store, 'locked', lambda *a: pytest.fail('report attempted to mutate source store'))
    _copy_package(tmp_path / 'result/result.json', result, tmp_path / 'report')
    assert (tmp_path / 'report/work/peer.log').read_bytes() == raw
    assert not (tmp_path / 'report' / CATALOG).exists()
    assert verify_result_package(tmp_path / 'report/result.json')['valid']
