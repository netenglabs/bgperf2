"""Gate wiring keeps safety probes fresh when validation is reusable."""
import importlib.util
from pathlib import Path
import sys


spec = importlib.util.spec_from_file_location('gate_receipt_wiring', Path(__file__).resolve().parents[1] / 'scripts/quality_gate.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def test_validate_runs_fresh_guard_and_bootstrap_before_receipted_suite(monkeypatch):
    calls = []
    monkeypatch.setattr(sys, 'argv', ['gate', 'validate'])
    monkeypatch.setattr(gate, 'guard', lambda: calls.append('guard'))
    monkeypatch.setattr(gate, 'git', lambda *a: calls.append(a))
    monkeypatch.setattr(gate, 'command', lambda *a, **kw: calls.append(a))
    monkeypatch.setattr(gate._checks, 'check', lambda *a, **kw: calls.append(('receipt', a, kw)))
    gate.main()
    assert calls[0] == 'guard'
    assert calls[1:3] == [('diff', '--check'), ('diff', '--cached', '--check')]
    assert calls[3][1:] == ('-I', gate.ROOT / 'scripts/bootstrap.py', '--check')
    assert calls[4][0] == 'receipt' and calls[4][1][1] == 'python-pure'


def test_sink_profile_cannot_be_satisfied_by_python_profile(monkeypatch):
    calls = []
    monkeypatch.setattr(sys, 'argv', ['gate', 'pre-push'])
    monkeypatch.setattr(gate, 'guard', lambda: calls.append('guard'))
    monkeypatch.setattr(gate, 'push_ranges', lambda stream: [('base', 'tip')])
    def git(*args):
        if args[0] == 'rev-parse':
            return 'head'
        if '--name-only' in args:
            return 'sink/main.go'
        return ''
    monkeypatch.setattr(gate, 'git', git)
    monkeypatch.setattr(gate, 'command', lambda *a, **kw: None)
    monkeypatch.setattr(gate._checks, 'check', lambda root, profile, *a, **kw: calls.append(profile))
    gate.main()
    assert calls == ['guard', 'python-pure', 'guard', 'sink-go-vet-race']
