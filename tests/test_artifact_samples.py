"""Exercise the real optional Parquet converter in an isolated environment."""
import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest
from artifact_samples import COLUMNS, maybe_convert

ROOT = Path(__file__).resolve().parents[1]


def test_export_failure_is_explicit_and_keeps_original_csv(tmp_path, monkeypatch):
    monkeypatch.setenv('BGPERF_PARQUET_PYTHON', str(tmp_path / 'missing-python'))
    source = tmp_path / 'raw-samples.csv'
    source.write_text('original evidence')
    maybe_convert(tmp_path)
    assert source.read_text() == 'original evidence'
    assert json.loads((tmp_path / 'parquet-export.json').read_text())['status'] == 'unavailable'


def test_real_parquet_preserves_values_nulls_and_provenance(tmp_path, monkeypatch):
    python = os.environ.get('BGPERF_TEST_PARQUET_PYTHON')
    if not python:
        pytest.skip('Set BGPERF_TEST_PARQUET_PYTHON to a separate pinned PyArrow environment')
    monkeypatch.setenv('BGPERF_PARQUET_PYTHON', python)
    # Simulate a store/work volume boundary for parent-process publication.
    original_link = os.link
    def same_volume_link(source, target, *args, **kwargs):
        if Path(source).parent != Path(target).parent:
            import errno
            raise OSError(errno.EXDEV, 'cross-device link')
        return original_link(source, target, *args, **kwargs)
    monkeypatch.setattr(os, 'link', same_volume_link)
    source = tmp_path / 'raw-samples.csv'
    with source.open('w', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(COLUMNS)
        writer.writerows([[0, 12.5, '100.0', 0, 0, 88.5, '512.0'], [1, None, None, 100, 2, None, None]])
    raw = source.read_bytes()
    maybe_convert(tmp_path)
    report = json.loads((tmp_path / 'parquet-export.json').read_text())
    assert report['status'] == 'exported'
    assert report['rows'] == 2
    assert report['source_sha256'] == hashlib.sha256(raw).hexdigest()
    code = "import pyarrow.parquet as p,json,sys; t=p.read_table(sys.argv[1]); print(json.dumps(t.to_pylist()))"
    proc = subprocess.run([python, '-I', '-c', code, str(tmp_path / 'raw-samples.parquet')],
                          capture_output=True, text=True, check=True)
    rows = json.loads(proc.stdout)
    assert rows[0] == dict(zip(COLUMNS, [0, 12.5, 100, 0, 0, 88.5, 512]))
    assert rows[1]['monitor_received'] == 100
    assert rows[1]['target_memory_bytes'] is None
    assert rows[1]['target_cpu_percent'] is None
    assert source.read_bytes() == raw


def test_timeout_staging_is_not_captured_as_evidence(tmp_path, monkeypatch):
    import artifact_samples
    work = tmp_path / 'work'; work.mkdir()
    (work / 'raw-samples.csv').write_text('source evidence')
    monkeypatch.setenv('BGPERF_ARTIFACT_STORE', str(tmp_path / 'store'))
    monkeypatch.setenv('BGPERF_PARQUET_PYTHON', str(Path(os.sys.executable)))
    def timeout(argv, **kwargs):
        target = Path(argv[argv.index('--output') + 1])
        assert target.parent != work
        assert tmp_path / 'store/staging' in target.parents
        assert kwargs['pass_fds']
        target.write_bytes(b'partial parquet')
        (target.parent / '.parquet-pending').write_bytes(b'partial')
        raise subprocess.TimeoutExpired(argv, 120)
    monkeypatch.setattr(artifact_samples.subprocess, 'run', timeout)
    assert maybe_convert(work)['status'] == 'unavailable'
    assert not list(tmp_path.glob('.parquet-export-*'))
    assert not (work / 'raw-samples.parquet').exists()
    assert not list((tmp_path / 'store/staging').glob('.parquet-export-*'))


def test_receipt_failure_does_not_abort_result_collection(tmp_path, monkeypatch):
    import artifact_store
    (tmp_path / 'raw-samples.csv').write_text('source evidence')
    monkeypatch.setenv('BGPERF_PARQUET_PYTHON', str(tmp_path / 'missing'))
    monkeypatch.setattr(artifact_store, 'publish', lambda *a: (_ for _ in ()).throw(OSError('disk full')))
    assert maybe_convert(tmp_path)['status'] == 'unavailable'
