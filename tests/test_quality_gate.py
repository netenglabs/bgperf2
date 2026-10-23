"""Exercise hook refusals and outgoing-ref selection without runtime access."""
import importlib.util
import io
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('quality_gate_under_test', ROOT / 'scripts/quality_gate.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def test_running_measurement_refuses(monkeypatch):
    monkeypatch.setattr(gate.Path, 'read_text', lambda self: '')
    monkeypatch.setattr(gate.Path, 'glob', lambda self, pattern: [])
    monkeypatch.setattr(gate, 'command', lambda *a, **kw: subprocess.CompletedProcess(a, 0, 'bgperf_bird_target\n'))
    with pytest.raises(ValueError, match='running containers'):
        gate.guard()


def test_remote_docker_refuses_without_contact(monkeypatch):
    monkeypatch.setattr(gate.Path, 'read_text', lambda self: '')
    monkeypatch.setattr(gate.Path, 'glob', lambda self, pattern: [])
    monkeypatch.setenv('DOCKER_HOST', 'ssh://forbidden')
    monkeypatch.setattr(gate, 'command', lambda *a, **kw: pytest.fail('contacted Docker'))
    with pytest.raises(ValueError, match='local unix'):
        gate.guard()


def test_unreadable_probe_refuses(monkeypatch):
    monkeypatch.setattr(gate.Path, 'read_text', lambda self: '')
    monkeypatch.setattr(gate.Path, 'glob', lambda self, pattern: [])
    def fail(*a, **kw):
        raise subprocess.CalledProcessError(1, a)
    monkeypatch.setattr(gate, 'command', fail)
    with pytest.raises(subprocess.CalledProcessError):
        gate.guard()


def test_held_batch_lock_refuses_before_docker(monkeypatch):
    monkeypatch.setattr(gate.Path, 'glob', lambda self, pattern: [Path('/proc/123')])
    monkeypatch.setattr(gate.Path, 'stat', lambda self: type('Stat', (), {'st_uid': gate.os.getuid()})())
    monkeypatch.setattr(gate.Path, 'read_text', lambda self: 'lock: 1: FLOCK ADVISORY WRITE 123 00:01:123 0 EOF\n')
    monkeypatch.setattr(gate.Path, 'iterdir', lambda self: [self / '9'])
    monkeypatch.setattr(gate.os, 'readlink', lambda p: '/any/results/batch-driver.lock')
    monkeypatch.setattr(gate, 'command', lambda *a, **kw: pytest.fail('contacted Docker'))
    with pytest.raises(ValueError, match='held batch lock'):
        gate.guard()


def test_push_ranges_new_update_delete(monkeypatch):
    zero = '0' * 40
    monkeypatch.setattr(gate, 'command', lambda *args, **kw: subprocess.CompletedProcess(args, 0, 'empty-tree\n'))
    data = io.StringIO(f'refs/heads/new abc refs/heads/new {zero}\n'
                       'refs/heads/main def refs/heads/main abc\n'
                       f'(delete) {zero} refs/heads/old abc\n')
    assert list(gate.push_ranges(data)) == [('empty-tree', 'abc'), ('abc', 'def')]


def test_failed_suite_stops_gate(monkeypatch):
    monkeypatch.setattr(gate, 'guard', lambda: None)
    monkeypatch.setattr(gate, 'git', lambda *a: '')
    monkeypatch.setattr(sys, 'argv', ['gate', 'pre-commit'])
    calls = []
    def run(*args, **kw):
        calls.append(args)
        if 'pytest' in args:
            raise subprocess.CalledProcessError(1, args)
    monkeypatch.setattr(gate, 'command', run)
    with pytest.raises(subprocess.CalledProcessError):
        gate.main()
    assert any('pytest' in call for call in calls)


def test_docker_context_cannot_redirect_sink(monkeypatch):
    monkeypatch.setenv('DOCKER_CONTEXT', 'forbidden-remote')
    monkeypatch.delenv('DOCKER_HOST', raising=False)
    env = gate.local_docker_environment()
    assert 'DOCKER_CONTEXT' not in env
    assert env['DOCKER_HOST'] == 'unix:///var/run/docker.sock'


@pytest.mark.parametrize('dirty,tip,message', [
    ('', 'other', 'checked-out HEAD'),
    (' M module.py', 'head', 'clean working'),
])
def test_push_refuses_untested_code(monkeypatch, dirty, tip, message):
    monkeypatch.setattr(gate, 'guard', lambda: None)
    monkeypatch.setattr(sys, 'argv', ['gate', 'pre-push'])
    monkeypatch.setattr(sys, 'stdin', io.StringIO('refs/heads/a '+tip+' refs/heads/a old\n'))
    def git(*args):
        if args[0] == 'rev-parse':
            return (tip if len(args) > 1 and args[1].endswith('^{commit}') else 'head') + '\n'
        if args[0] == 'status':
            return dirty
        return ''
    monkeypatch.setattr(gate, 'git', git)
    monkeypatch.setattr(gate, 'command', lambda *a, **kw: pytest.fail('ran tests before refusal'))
    with pytest.raises(ValueError, match=message):
        gate.main()


def test_pure_suite_clears_optional_engine_binding(monkeypatch):
    monkeypatch.setattr(gate, 'guard', lambda: None)
    monkeypatch.setattr(gate, 'git', lambda *a: '')
    monkeypatch.setattr(sys, 'argv', ['gate', 'pre-commit'])
    monkeypatch.setenv('BGPERF_ENGINE_ROOT', '/explicit/engine')
    environments = []
    def run(*args, **kw):
        if 'pytest' in args:
            environments.append(kw['env'])
    monkeypatch.setattr(gate, 'command', run)
    gate.main()
    assert len(environments) == 1
    assert 'BGPERF_ENGINE_ROOT' not in environments[0]
