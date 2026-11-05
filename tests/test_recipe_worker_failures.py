"""Failed worker monitoring cannot publish successful terminal accounting."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import recipes
import recipe_diagnostics as diagnostics
import recipe_worker as worker


def worker_fixture(tmp_path, monkeypatch, *, failure=None, alive=False):
    recipe = recipes.read_document(Path(worker.__file__).parent / 'examples/recipes/synthetic-ipv4.recipe.json')
    (tmp_path / 'recipe.json').write_text(json.dumps(recipe))
    (tmp_path / 'diagnostic-options.json').write_text('{"mode":"basic"}')
    monkeypatch.setitem(sys.modules, 'docker', SimpleNamespace(APIClient=lambda **kw: object()))
    monkeypatch.setitem(sys.modules, 'bgperf2', SimpleNamespace())
    # main installs its private engine settings; restore the test runner's
    # original settings module after each isolated worker invocation.
    monkeypatch.setitem(sys.modules, 'settings', sys.modules.get('settings', SimpleNamespace()))
    monkeypatch.setattr(worker, 'scan_health', lambda *a: failure)
    monkeypatch.setattr(diagnostics, 'live_sample', lambda *a, **kw: None)
    monkeypatch.setattr(worker, 'execute', lambda *a, **kw: {'status': 'completed', 'reason': 'SIMULATED completion'})
    exits, threads = [], []
    def exit_process(code):
        exits.append(code)
        raise SystemExit(code)
    monkeypatch.setattr(worker.os, '_exit', exit_process)
    class Thread:
        def __init__(self, target, **kwargs):
            self.target, self.joined = target, []
            threads.append(self)
        def start(self):
            if not alive:
                try:
                    self.target()
                except BaseException:
                    pass  # A real daemon thread exits independently of main.
        def join(self, timeout):
            self.joined.append(timeout)
        def is_alive(self):
            return alive
    monkeypatch.setattr(worker.threading, 'Thread', Thread)
    return exits, threads


def test_optional_artifact_write_failure_cannot_silently_kill_health_monitor(tmp_path, monkeypatch):
    exits, threads = worker_fixture(tmp_path, monkeypatch)
    original = worker._write
    def fail_optional(path, value):
        if Path(path).name == 'live-diagnostics.json':
            raise OSError('SIMULATED transient diagnostic write failure')
        return original(path, value)
    monkeypatch.setattr(worker, '_write', fail_optional)
    worker.main([str(tmp_path), 'attempt'])
    result = json.loads((tmp_path / 'runtime.json').read_text())
    assert result['status'] == 'harness_failed'
    assert 'diagnostic write failure' in result['reason']
    assert exits == [0]


def test_watcher_failure_cannot_be_overwritten_by_later_bench_completion(tmp_path, monkeypatch):
    failure = {'status': 'experiment_failed', 'reason': 'SIMULATED stopped target'}
    worker_fixture(tmp_path, monkeypatch, failure=failure)
    worker.main([str(tmp_path), 'attempt'])
    assert json.loads((tmp_path / 'runtime.json').read_text()) == failure


def test_inflight_healthy_monitor_cannot_publish_late_work_or_extend_budget(tmp_path, monkeypatch):
    _, threads = worker_fixture(tmp_path, monkeypatch, alive=True)
    worker.main([str(tmp_path), 'attempt'])
    path = tmp_path / 'runtime.json'
    result, sealed = json.loads(path.read_text()), path.read_bytes()
    assert result['status'] == 'completed'
    assert threads[0].joined == [0]
    # A blocked SDK call returning after terminal publication must not write.
    threads[0].target()
    assert path.read_bytes() == sealed
    assert not (tmp_path / 'live-diagnostics.json').exists()


def test_monitor_error_survives_main_completion_during_failure_handoff(tmp_path, monkeypatch):
    real_thread, real_lock = worker.threading.Thread, worker.threading.Lock
    write_failed, handoff_gap, release = (worker.threading.Event() for _ in range(3))
    exits, _ = worker_fixture(tmp_path, monkeypatch)
    threads = []
    class Thread(real_thread):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            threads.append(self)
    class HandoffLock:
        def __init__(self):
            self.lock = real_lock()
            self.paused = False
        def __enter__(self):
            return self.lock.__enter__()
        def __exit__(self, *args):
            self.lock.__exit__(*args)
            if write_failed.is_set() and worker.threading.current_thread() is threads[0] and not self.paused:
                self.paused = True
                handoff_gap.set()
                assert release.wait(5)
    calls = []
    def lock():
        calls.append(True)
        # Event's internal lock is first; the terminal writer's lock is second.
        return HandoffLock() if len(calls) == 2 else real_lock()
    monkeypatch.setattr(worker.threading, 'Lock', lock)
    monkeypatch.setattr(worker.threading, 'Thread', Thread)
    original = worker._write
    def write(path, value):
        if Path(path).name == 'live-diagnostics.json':
            write_failed.set()
            raise OSError('SIMULATED failure before handoff')
        return original(path, value)
    monkeypatch.setattr(worker, '_write', write)
    def execute(*args, **kwargs):
        assert handoff_gap.wait(5)
        return {'status': 'completed', 'reason': 'SIMULATED completion during handoff'}
    monkeypatch.setattr(worker, 'execute', execute)
    try:
        worker.main([str(tmp_path), 'attempt'])
        path = tmp_path / 'runtime.json'
        sealed = path.read_bytes()
        assert json.loads(sealed)['status'] == 'harness_failed'
        assert 'before handoff' in json.loads(sealed)['reason']
    finally:
        release.set()
        threads[0].join(5)
    assert not threads[0].is_alive() and path.read_bytes() == sealed
    assert exits == []  # Late handoff observes already finalized failure.
