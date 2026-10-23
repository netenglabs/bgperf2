"""Drive the extracted orchestration with queued samples and no host runtime."""
import inspect
import json
import subprocess
import sys
import threading
from collections import deque
from types import SimpleNamespace

import pytest

import bgperf2
import run_lifecycle


def fake_run(tmp_path, accepted=10, stopped=False):
    args = bgperf2.create_args_parser().parse_args([
        '-d', str(tmp_path / 'work'), 'bench', '-n', '1', '-p', '10',
        '--monitor', 'gobgp', '--results-dir', str(tmp_path / 'results')])
    calls, components = [], []
    runtime = SimpleNamespace(**vars(bgperf2))
    runtime.controller_stop = threading.Event()
    runtime.controller_stop.set()  # A previous cell has finished.
    runtime.stop_signal = bgperf2.StopSignal()
    if stopped:
        runtime.stop_signal.request('fake operator stop')

    class Component:
        REPORTS_OFFERING = False
        stop_monitoring = False

        def __init__(self, directory, config, image=None):
            self.name = 'bgperf_monitor' if directory.endswith('/monitor') else 'target'
            components.append(self)

        @classmethod
        def require_image(cls):
            calls.append('image')

        def run(self, *args):
            calls.append('start ' + self.name)

        def wait_established(self, *args):
            calls.append('establish')
            return 3

        def stats(self, *args, **kwargs):
            calls.append('sample ' + self.name)

        def neighbor_stats(self, *args):
            calls.append('neighbors')

    class Generator(Component):
        def __init__(self, name, directory, config):
            self.name, self.host_dir = name, directory
            components.append(self)

        def launch(self):
            calls.append('launch')

        @staticmethod
        def find_errors(*args):
            calls.append('scan errors')
            return 0

        @staticmethod
        def find_timeouts(*args):
            calls.append('scan timeouts')
            return 0

    class Samples:
        def __init__(self):
            self.messages = deque([
                {'who': 'target', 'neighbors_checked': {'peer': accepted > 0}},
                {'who': 'target', 'cpu': 12, 'mem': 1024},
                {'who': 'controller', 'free': 32 * 1024**3},
                {'who': 'controller', 'idle': 90},
            ] + [
                {'who': 'bgperf_monitor', 'monotonic_s': 100 + second,
                 'checked': accepted >= 9,
                 'afi_safis': [{'state': {'accepted': accepted}}]}
                for second in range(1, 25)
            ])

        def get(self):
            assert self.messages, 'the observation loop did not terminate'
            return self.messages.popleft()

    for name in ('remove_target_containers', 'remove_old_containers',
                 'warn_if_machine_is_busy', 'warn_if_log_dir_is_in_ram',
                 'warn_if_log_dir_is_short_on_space',
                 'warn_if_trace_io_reaches_no_generator',
                 'controller_idle_percent', 'controller_memory_free',
                 'controller_foreign_cpu', 'install_stop_handlers', 'rm_line'):
        setattr(runtime, name, lambda *a, _name=name, **k: calls.append(_name))
    runtime.MONITOR_CLASSES = {'gobgp': Component}
    runtime.TARGET_CLASSES = {'bird': Component}
    runtime.BIRDTester = Generator
    runtime.target_image = lambda *a: 'fake/bird'
    runtime.host_cpus = lambda: frozenset(range(4))
    runtime.get_ctn_names = lambda: []
    runtime.gc_thresh3 = lambda: 1024
    runtime.dckr = SimpleNamespace(networks=lambda **k: [{'Name': 'bgperf2-br'}])
    runtime.get_hardware_info = lambda: (4, 64 * 1024**3)
    runtime.role_cpu_members = lambda *a, **k: ({}, {})
    runtime.controller_role_cpu = lambda *a: SimpleNamespace(
        join=lambda **k: calls.append('join'), is_alive=lambda: False)
    runtime.Queue = Samples
    runtime.time = SimpleNamespace(time=lambda: 1000, monotonic=lambda: 100,
                                   sleep=lambda seconds: None)
    runtime.finish_bench = lambda *a, **k: run_lifecycle.finish_bench(runtime, *a, **k)
    runtime.abandon_run = lambda *a, **k: run_lifecycle.abandon_run(runtime, *a, **k)

    def collect(*args):
        calls.append('provenance')
        return {'target': {'version': 'fake', 'image': 'fake/bird'},
                'monitor': {'version': 'fake'}, 'testers': []}

    runtime.collect_provenance = collect
    runtime.create_bench_graphs = lambda *a, **k: calls.append('graphs')
    runtime.write_provenance = lambda *a: calls.append('manifest')
    return runtime, args, calls, components


@pytest.mark.parametrize('accepted, failed', [(10, False), (0, True)])
def test_queued_run_publishes_verdict_and_stops_samplers(tmp_path, accepted, failed):
    runtime, args, calls, components = fake_run(tmp_path, accepted)
    row = run_lifecycle.bench(runtime, args)
    artifact = json.loads(next((tmp_path / 'results').glob('*.events.json')).read_text())
    assert bgperf2.row_failed(row) is failed
    assert artifact['status'] == ('failed' if failed else 'converged')
    assert row[6] == accepted
    assert len(row) == len(bgperf2.stats_header().split(','))
    assert runtime.controller_stop.is_set()
    assert all(component.stop_monitoring for component in components)
    assert calls.index('remove_target_containers') < calls.index('warn_if_machine_is_busy')
    assert calls.index('establish') < calls.index('launch')
    assert calls.index('join') < calls.index('scan errors') < calls.index('provenance')
    assert calls[-2:] == ['graphs', 'manifest']
    if failed:
        assert 'monitor_first_prefix' not in [event['event'] for event in artifact['events']]
    else:
        assert artifact['events'][-1]['event'] == 'convergence_confirmed'
        assert row[8] == 2  # Existing short assurance-window subtraction.


def test_stop_keeps_containers_and_records_no_row(tmp_path):
    runtime, args, calls, components = fake_run(tmp_path, stopped=True)
    with pytest.raises(bgperf2.StopRequested, match='fake operator stop'):
        run_lifecycle.bench(runtime, args)
    assert runtime.controller_stop.is_set()
    assert all(component.stop_monitoring for component in components)
    assert 'provenance' not in calls
    assert 'graphs' not in calls
    assert calls.count('remove_target_containers') == 1  # Entry cleanup only.
    assert not (tmp_path / 'results').exists()


def test_compatibility_entry_points_keep_signatures():
    for name in ('bench', 'finish_bench', 'abandon_run'):
        public = inspect.signature(getattr(bgperf2, name))
        extracted = inspect.signature(getattr(run_lifecycle, name))
        assert list(extracted.parameters)[0] == 'runtime'
        assert list(public.parameters.values()) == list(extracted.parameters.values())[1:]


def test_lifecycle_import_does_not_initialize_the_engine_or_docker():
    subprocess.run([sys.executable, '-c',
                    'import sys; import run_lifecycle; '
                    'assert "bgperf2" not in sys.modules; '
                    'assert "settings" not in sys.modules; '
                    'assert "docker" not in sys.modules'],
                   cwd=bgperf2.REPO_ROOT, check=True)
