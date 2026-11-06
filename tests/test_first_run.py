"""The documented first run works without private state or runtime access."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest

from scripts import first_run


@pytest.mark.parametrize('installed', [None, '0.0'])
def test_required_package_errors_explain_setup_before_creating_output(tmp_path, monkeypatch, capsys, installed):
    original = first_run.metadata.version

    def version(name):
        if name == 'pyyaml':
            if installed is None:
                raise first_run.metadata.PackageNotFoundError(name)
            return installed
        return original(name)

    monkeypatch.setattr(first_run.metadata, 'version', version)
    output = tmp_path / 'new'
    assert first_run.main(['--output', str(output)]) == 2
    error = capsys.readouterr().err
    assert 'pyyaml' in error and 'scripts/bootstrap.py' in error and 'venv/bin/python' in error
    assert not output.exists()


def test_wrong_python_explains_supported_interpreter(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(first_run.sys, 'version_info', (3, 13))
    assert first_run.main(['--output', str(tmp_path / 'new')]) == 2
    assert 'Python 3.14' in capsys.readouterr().err
    assert not (tmp_path / 'new').exists()


@pytest.mark.parametrize('kind', ['relative', 'inside', 'existing', 'parent_missing', 'symlink'])
def test_bad_output_is_actionable_and_preserves_existing_files(tmp_path, monkeypatch, capsys, kind):
    monkeypatch.setattr(first_run, 'check_environment', lambda: None)
    engine = tmp_path / 'engine'
    engine.mkdir()
    monkeypatch.setattr(first_run, 'ROOT', engine)
    keep = tmp_path / 'keep'
    keep.mkdir()
    marker = keep / 'marker'
    marker.write_bytes(b'preserve existing output')
    if kind == 'relative':
        output, expected = 'relative-output', 'absolute'
    elif kind == 'inside':
        output, expected = engine / 'output', 'outside'
    elif kind == 'existing':
        output, expected = keep, 'already exists'
    elif kind == 'parent_missing':
        output, expected = tmp_path / 'missing-parent/new', 'parent must already exist'
    else:
        link = tmp_path / 'link'
        link.symlink_to(keep, target_is_directory=True)
        output, expected = link / 'output', 'symlinks'
    assert first_run.main(['--output', str(output)]) == 2
    assert expected in capsys.readouterr().err
    assert marker.read_bytes() == b'preserve existing output'
    assert not (keep / 'output').exists()


def test_failed_example_retains_partial_output_and_restores_converter_binding(tmp_path, monkeypatch, capsys):
    from scripts import frr_source_smoke
    monkeypatch.setattr(first_run, 'check_environment', lambda: None)
    monkeypatch.setenv('BGPERF_PARQUET_PYTHON', '/unused/live-converter')

    def fail(output):
        assert 'BGPERF_PARQUET_PYTHON' not in os.environ
        output.mkdir()
        (output / 'partial').write_bytes(b'retained simulated output')
        raise RuntimeError('SIMULATED report failure')

    monkeypatch.setattr(frr_source_smoke, 'run_smoke', fail)
    output = tmp_path / 'partial-output'
    assert first_run.main(['--output', str(output)]) == 2
    assert 'SIMULATED report failure' in capsys.readouterr().err
    assert (output / 'partial').read_bytes() == b'retained simulated output'
    assert os.environ['BGPERF_PARQUET_PYTHON'] == '/unused/live-converter'


def test_actual_cli_from_other_directory_with_process_and_network_forbidden(tmp_path):
    guard = tmp_path / 'guard'
    guard.mkdir()
    marker = tmp_path / 'guard-loaded'
    (guard / 'sitecustomize.py').write_text('''
import os, pathlib, socket, subprocess
pathlib.Path(os.environ['FIRST_RUN_GUARD_MARKER']).write_text('loaded')
def forbidden(*args, **kwargs):
    raise AssertionError('Real subprocess or network forbidden in first-run example')
subprocess.Popen = forbidden
for name in ('__init__', 'connect', 'connect_ex', 'sendto'):
    setattr(socket.socket, name, forbidden)
socket.create_connection = forbidden
''')
    live_store = tmp_path / 'live-store'
    live_store.mkdir()
    (live_store / 'sentinel').write_bytes(b'unmodified live configuration')
    env = dict(os.environ, PYTHONPATH=str(guard), FIRST_RUN_GUARD_MARKER=str(marker),
               BGPERF_ARTIFACT_STORE=str(live_store), BGPERF_PARQUET_PYTHON=sys.executable)
    output = tmp_path / 'walkthrough'
    argv = [sys.executable, str(first_run.ROOT / 'scripts/first_run.py'), '--output', str(output)]
    result = subprocess.run(argv, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120)
    assert marker.read_text() == 'loaded'
    assert result.returncode == 0, result.stderr
    assert 'SIMULATED workflow completed' in result.stdout
    assert 'prefix identity failed as intended' in result.stdout
    assert 'Verified portable report packages: 8' in result.stdout
    assert str(output / 'REPORT.md') in result.stdout
    assert list(live_store.iterdir()) == [live_store / 'sentinel']
    assert (live_store / 'sentinel').read_bytes() == b'unmodified live configuration'
    summary = json.loads((output / 'smoke.json').read_text())
    assert summary['simulation'] and summary['performance_policy'] == 'disabled'
    assert summary['conclusion']['state'] == 'confirmed'
    assert summary['minimization']['best'] == {'peers': 1, 'routes': 2}
    assert all(row['valid'] for row in json.loads((output / 'verification.json').read_text()).values())
    for relative in re.findall(r'\]\(([^)]+)\)', (output / 'REPORT.md').read_text()):
        assert (output / relative).is_file()
    before = (output / 'smoke.json').read_bytes()
    repeated = subprocess.run(argv, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    assert repeated.returncode == 2 and 'already exists' in repeated.stderr
    assert (output / 'smoke.json').read_bytes() == before
