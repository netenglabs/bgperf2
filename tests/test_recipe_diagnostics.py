"""Owned diagnostics retain bounded partial evidence without changing measurements."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import recipe_diagnostics as diagnostics
import recipe_preflight as preflight
import recipe_run
import recipes


ROOT = Path(__file__).resolve().parents[1]
CID = 'a' * 64


def recipe():
    return recipes.read_document(ROOT / 'examples/recipes/synthetic-ipv4.recipe.json')


def command_fixture(*, foreign=False, log_error=False, truncated=False):
    calls = []
    def command(argv, **kwargs):
        calls.append((argv, kwargs))
        assert kwargs['timeout'] <= 3
        assert kwargs['max_bytes'] == diagnostics.MAX_BYTES
        if 'ps' in argv:
            text = CID + '\n'
        elif 'inspect' in argv:
            text = json.dumps([{'Id': CID, 'Name': '/attempt_bgperf_bird_target',
                'Image': 'sha256:' + '1' * 64,
                'Config': {'Labels': {recipe_run.OWNER_LABEL: 'foreign' if foreign else 'attempt'}, 'Env': ['SECRET=never copy']},
                'State': {'Running': True, 'ExitCode': 0, 'OOMKilled': False, 'Pid': 123, 'Secret': 'never copy'}}])
        elif 'logs' in argv:
            if log_error:
                raise preflight.ProbeError('log reader unavailable')
            text = 'bounded target output\n'
        else:
            pytest.fail('unmodeled command')
        return {'text': text, 'truncated': truncated if 'logs' in argv else False,
                'captured_bytes': len(text.encode())}
    return command, calls


def test_scoped_collection_records_memory_boundaries_and_no_environment(tmp_path):
    command, calls = command_fixture(truncated=True)
    result = diagnostics.collect_diagnostics(tmp_path, 'attempt', {}, command=command,
        memory_reader=lambda pid: {'peak_bytes': 120, 'ending_bytes': 100, 'anon_bytes': 70, 'file_backed_bytes': 30})
    assert result['status'] == 'collected'
    assert result['memory']['target']['peak_bytes'] == 120
    assert result['memory']['target']['ending_bytes'] == 100
    assert result['memory']['target']['daemon_process_rss_bytes'] is None
    assert 'including file-backed/cache' in result['memory']['target']['accounting']
    assert result['containers'][0]['log']['truncated'] is True
    assert 'never copy' not in json.dumps(result)
    assert (tmp_path / ('diagnostic-logs/' + CID + '.log')).read_text() == 'bounded target output\n'
    assert calls[0][0][-1] == 'label=bgperf2.recipe.attempt=attempt'
    assert all('exec' not in argv and 'rm' not in argv for argv, _ in calls)


def test_foreign_label_refuses_all_container_probes_beyond_inspection(tmp_path):
    command, calls = command_fixture(foreign=True)
    result = diagnostics.collect_diagnostics(tmp_path, 'attempt', {}, command=command,
        memory_reader=lambda pid: pytest.fail('foreign memory read'))
    assert result['status'] == 'partial'
    assert not result['containers']
    assert all('logs' not in argv for argv, _ in calls)
    assert 'ownership' in result['errors'][0]


def test_collection_failure_keeps_state_and_memory(tmp_path):
    command, _ = command_fixture(log_error=True)
    result = diagnostics.collect_diagnostics(tmp_path, 'attempt', {}, command=command,
        memory_reader=lambda pid: {'peak_bytes': 80, 'ending_bytes': 60})
    assert result['status'] == 'partial'
    assert result['containers'][0]['state']['Running'] is True
    assert result['memory']['target']['ending_bytes'] == 60
    assert result['containers'][0]['log'] is None
    assert (tmp_path / 'diagnostics.json').is_file()


def test_unavailable_memory_is_unknown_not_zero(tmp_path):
    command, _ = command_fixture()
    def unreadable(pid):
        raise OSError('cgroup was removed')
    result = diagnostics.collect_diagnostics(tmp_path, 'attempt', {}, command=command, memory_reader=unreadable)
    memory = result['memory']['target']
    assert memory['peak_bytes'] is None and memory['ending_bytes'] is None
    assert memory['reason'] == 'cgroup was removed'


def test_early_timeout_with_no_containers_preserves_explicit_missing(tmp_path):
    result = diagnostics.collect_diagnostics(tmp_path, 'attempt', {},
        command=lambda *a, **k: {'text': '', 'captured_bytes': 0, 'truncated': False})
    assert result['status'] == 'collected'
    assert result['missing']
    assert result['memory']['target']['ending_bytes'] is None


def test_optional_diagnostics_none_never_probes(tmp_path):
    result = diagnostics.collect_diagnostics(tmp_path, 'attempt', {}, mode='none',
        command=lambda *a, **k: pytest.fail('probed'))
    assert result['status'] == 'disabled'
    assert result['memory']['target']['peak_bytes'] is None


def live_client(present=True, usage=100):
    return SimpleNamespace(stats=lambda *a, **k: {'memory_stats': {'usage': usage}},
        top=lambda *a, **k: {'Titles': ['PID', 'COMMAND'],
                            'Processes': [['7', 'bird']] if present else [['1', 'bash']]})


def test_bird_process_disappearance_requires_prior_observed_presence():
    owned = SimpleNamespace(started={'id': 'attempt_bgperf_bird_target'})
    state = {}
    assert diagnostics.live_sample(live_client(False), owned, state, expected='target_crash') is None
    assert diagnostics.live_sample(live_client(True), owned, state, expected='target_crash') is None
    result = diagnostics.live_sample(live_client(False), owned, state, expected='target_crash')
    assert result['status'] == 'experiment_failed'
    assert result['reproduction']['outcome'] == 'inconclusive'
    assert result['reproduction']['evidence'] == ['work/live-diagnostics.json']


@pytest.mark.parametrize('code,outcome', [(139, 'reproduced'), (0, 'not_reproduced')])
def test_captured_daemon_exit_separates_crash_from_clean_exit(code, outcome):
    owned = SimpleNamespace(started={'id': 'attempt_bgperf_bird_target'})
    state = {}
    diagnostics.live_sample(live_client(True), owned, state, expected='target_crash')
    result = diagnostics.live_sample(live_client(False), owned, state,
                                     expected='target_crash', exit_reader=lambda: code)
    assert result['reproduction']['outcome'] == outcome
    assert state['samples'][-1]['daemon_exit_code'] == code


def test_fixed_exit_witness_refuses_symlink_and_oversized_file(tmp_path):
    source = tmp_path / 'exit.json'
    source.write_text('{"exit_code":139}')
    assert diagnostics.read_bird_exit(tmp_path, 'exit.json') == 139
    (tmp_path / 'alias.json').symlink_to(source)
    assert diagnostics.read_bird_exit(tmp_path, 'alias.json') is None
    source.write_text(' ' * 4097 + '{"exit_code":139}')
    assert diagnostics.read_bird_exit(tmp_path, 'exit.json') is None


def test_fixed_startup_capture_follows_existing_foreground_command():
    import recipe_worker
    class Adapter:
        guest_dir = '/root/config'
        def __init__(self):
            self.name = 'bgperf_bird_target'
        def get_startup_cmd(self):
            return '#!/bin/bash\nbird -d > /root/config/bird.log 2>&1'
    selected = recipe_worker.scoped_adapter(Adapter, 'sha256:fixture', 'attempt',
                                           role='target', capture_exit=True)
    command = selected().get_startup_cmd()
    assert command.startswith(Adapter().get_startup_cmd())
    assert 'bgperf_bird_exit_status=$?' in command
    assert '/root/config/recipe-bird-exit.json' in command


def test_failed_process_read_never_attests_disappearance():
    owned = SimpleNamespace(started={'id': 'attempt_bgperf_bird_target'})
    state = {}
    diagnostics.live_sample(live_client(True), owned, state, expected='target_crash')
    client = live_client(False)
    client.top = lambda *a, **k: (_ for _ in ()).throw(OSError('Docker unavailable'))
    assert diagnostics.live_sample(client, owned, state, expected='target_crash') is None
    assert state['samples'][-1]['bird_process_present'] is None
    assert state['samples'][-1]['errors']


def test_bounded_live_series_preserves_peak_before_dropped_samples():
    owned = SimpleNamespace(started={'id': 'attempt_bgperf_bird_target'})
    state = {}
    diagnostics.live_sample(live_client(usage=999), owned, state, expected='target_crash')
    for _ in range(diagnostics.LIVE_SAMPLE_LIMIT + 5):
        diagnostics.live_sample(live_client(usage=10), owned, state, expected='target_crash')
    assert len(state['samples']) == diagnostics.LIVE_SAMPLE_LIMIT
    assert state['sampled_peak_bytes']['target'] == 999
    assert state['dropped_samples'] == 6


def test_stage_records_do_not_redefine_measurement_boundaries(tmp_path):
    diagnostics.stage(tmp_path, 'setup')
    diagnostics.stage(tmp_path, 'observation')
    diagnostics.stage(tmp_path, 'collection', reason='partial evidence')
    result = json.loads((tmp_path / 'stages.json').read_text())
    assert [event['stage'] for event in result['events']] == ['setup', 'observation', 'collection']
    assert result['current_stage'] == 'collection'
    assert 'not benchmark measurement boundaries' in result['clock']


def test_override_preflight_checks_effective_target_only(tmp_path, monkeypatch):
    from recipe_targets import supplied_target
    document = recipe()
    target = supplied_target(document, 'sha256:' + '9' * 64)
    calls = []
    monkeypatch.setattr(preflight, 'runtime_prerequisites', lambda *a: ({}, 'unix:///socket', True))
    monkeypatch.setattr(preflight, '_image', lambda report, role, image, *a: calls.append((role, image)))
    monkeypatch.setattr(preflight, '_capacity', lambda *a: None)
    monkeypatch.setattr(preflight, '_destination', lambda report, name, path, mounts: Path(path))
    result = preflight.check_recipe(document, workdir=tmp_path / 'work', results_dir=tmp_path / 'results', target=target)
    assert dict(calls) == {'target': target['image'], 'generator': document['roles']['generator']['image'],
                           'observer': document['roles']['observer']['image']}
    assert result['roles']['target']['image'] == target['image']


def test_invalid_override_refused_before_probes(tmp_path, monkeypatch):
    from recipe_targets import supplied_target
    document = recipe()
    target = supplied_target(document, 'sha256:' + '9' * 64)
    target['recipe_sha256'] = '0' * 64
    monkeypatch.setattr(preflight, 'runtime_prerequisites', lambda *a: pytest.fail('probed'))
    with pytest.raises(ValueError):
        preflight.check_recipe(document, workdir=tmp_path / 'work', results_dir=tmp_path / 'results', target=target)


def test_run_override_preserves_base_and_fixed_roles_in_package(tmp_path):
    from recipe_targets import supplied_target
    document = recipe()
    original = copy.deepcopy(document)
    target = supplied_target(document, 'sha256:' + '9' * 64, instrumentation='debug')
    class Backend:
        def execute(self, passed, work, attempt, timeout):
            assert passed == original
            assert json.loads((work / 'target.json').read_text()) == target
            selection = json.loads((work / 'target-selection.json').read_text())
            assert selection['roles']['target']['image'] == target['image']
            assert selection['roles']['generator'] == document['roles']['generator']
            assert selection['roles']['observer'] == document['roles']['observer']
            outcome = {'status': 'completed', 'reason': 'controlled completion'}
            (work / 'runtime.json').write_text(json.dumps(outcome))
            return outcome
    result = recipe_run.run_recipe(document, workdir=tmp_path / 'work', results_dir=tmp_path / 'results',
        target=target, backend=Backend(), check=lambda *a, **k: {'status': 'checks_passed'})
    assert result['status'] == 'completed'
    assert json.loads((tmp_path / 'results/recipe.json').read_text()) == original
    assert document == original
    assert (tmp_path / 'results/work/target.json').is_file()


def test_bounded_probe_caps_actual_child_output():
    import sys
    result = diagnostics.bounded_probe(
        [sys.executable, '-c', 'import os; os.write(1, b"x" * 1000000)'],
        env=preflight._environment(), timeout=3, max_bytes=32)
    assert result['truncated'] is True
    assert result['captured_bytes'] == 32
    assert len(result['text']) == 32


def test_bounded_probe_stops_actual_child_on_deadline():
    import sys
    with pytest.raises(preflight.ProbeError, match='deadline'):
        diagnostics.bounded_probe([sys.executable, '-c', 'import time; time.sleep(2)'],
                                   env=preflight._environment(), timeout=0.01)


def test_failed_final_collector_preserves_supported_crash_and_all_evidence(tmp_path, monkeypatch):
    work = tmp_path / 'work'
    class Process:
        pid = 12345
        returncode = 0
        def wait(self, timeout):
            (work / 'partial.log').write_text('target crash evidence')
            recipe_run._write(work / 'runtime.json', {
                'status': 'experiment_failed', 'reason': 'target exit witnessed',
                'reproduction': {'outcome': 'reproduced', 'reason': 'target exit',
                                 'evidence': ['work/runtime.json']}})
        def poll(self):
            return 0
    monkeypatch.setattr(recipe_run.subprocess, 'Popen', lambda *a, **k: Process())
    monkeypatch.setattr(recipe_run.os, 'killpg', lambda *a: None)
    monkeypatch.setattr(recipe_run, '_cleanup', lambda *a: [])
    def fail(*args, **kwargs):
        raise OSError('final collector broken')
    monkeypatch.setattr(diagnostics, 'collect_diagnostics', fail)
    document = recipe()
    document['reproduction']['expected_outcome'] = 'target_crash'
    result = recipe_run.run_recipe(document, workdir=work, results_dir=tmp_path / 'results',
        backend=recipe_run.SubprocessBackend(diagnostics='basic'),
        check=lambda *a, **k: {'status': 'checks_passed'})
    assert result['status'] == 'harness_failed'
    assert result['reproduction']['outcome'] == 'reproduced'
    assert (tmp_path / 'results/work/partial.log').read_text() == 'target crash evidence'
    stored = json.loads((tmp_path / 'results/work/runtime.json').read_text())
    assert stored['experiment_status_before_collection'] == 'experiment_failed'
    report = json.loads((tmp_path / 'results/work/diagnostics.json').read_text())
    assert report['errors'] and report['memory']['target']['peak_bytes'] is None
    events = json.loads((tmp_path / 'results/work/stages.json').read_text())['events']
    assert [event['stage'] for event in events] == ['setup', 'collection', 'cleanup', 'terminal']


def test_malformed_container_identifier_never_becomes_a_path(tmp_path):
    calls = []
    def command(argv, **kwargs):
        calls.append(argv)
        return {'text': '../../escape\n', 'truncated': False, 'captured_bytes': 13}
    result = diagnostics.collect_diagnostics(tmp_path, 'attempt', {}, command=command)
    assert result['status'] == 'partial'
    assert len(calls) == 1
    assert 'Malformed full container ID' in result['errors'][0]
    assert not (tmp_path / 'diagnostic-logs').exists()


def test_stage_record_failure_cannot_skip_cleanup_or_handler_restoration(tmp_path, monkeypatch):
    import signal
    class Process:
        pid = 321
        returncode = 0
        def wait(self, timeout):
            recipe_run._write(tmp_path / 'runtime.json', {'status': 'completed', 'reason': 'done'})
        def poll(self):
            return 0
    original_stage = diagnostics.stage
    def broken_stage(work, name, **kwargs):
        if name == 'setup':
            return original_stage(work, name, **kwargs)
        raise OSError('stage storage unavailable')
    monkeypatch.setattr(diagnostics, 'stage', broken_stage)
    monkeypatch.setattr(recipe_run.subprocess, 'Popen', lambda *a, **k: Process())
    monkeypatch.setattr(recipe_run.os, 'killpg', lambda *a: None)
    cleaned = []
    monkeypatch.setattr(recipe_run, '_cleanup', lambda *a: cleaned.append(True) or [])
    previous = (signal.getsignal(signal.SIGINT), signal.getsignal(signal.SIGTERM))
    result = recipe_run.SubprocessBackend().execute(recipe(), tmp_path, 'attempt', 1)
    assert cleaned == [True]
    assert result['status'] == 'harness_failed'
    assert result['diagnostic_errors']
    assert previous == (signal.getsignal(signal.SIGINT), signal.getsignal(signal.SIGTERM))


@pytest.mark.parametrize('failure', ['graphs', 'provenance'])
def test_existing_lifecycle_collection_failure_preserves_raw_observations(tmp_path, failure):
    import recipe_worker
    from test_run_lifecycle import fake_run
    engine, args, calls, components = fake_run(tmp_path)
    engine.MONITOR_CLASSES = {'sink': engine.MONITOR_CLASSES['gobgp']}
    engine.create_args_parser = lambda: SimpleNamespace(parse_args=lambda argv: args)
    args.monitor = 'sink'
    args.bench_name = 'attempt'
    args.dir = str(tmp_path / 'work')
    network_calls = [0]
    def networks(**kwargs):
        network_calls[0] += 1
        return [] if network_calls[0] == 1 else [{'Name': 'attempt-br'}]
    engine.dckr = SimpleNamespace(networks=networks)
    engine.capture_tool_revision = lambda: None
    original_queue = engine.Queue
    def queue():
        result = original_queue()
        for item in result.messages:
            if item['who'] in ('target', 'bgperf_monitor'):
                item['who'] = 'attempt_' + item['who']
        return result
    engine.Queue = queue
    def fail(*args, **kwargs):
        raise RuntimeError('controlled final ' + failure + ' failure')
    if failure == 'graphs':
        engine.create_bench_graphs = fail
    else:
        engine.collect_provenance = fail
    work = tmp_path / 'work'
    work.mkdir(exist_ok=True)
    with pytest.raises(RuntimeError, match='controlled final'):
        recipe_worker.execute(recipe(), work, 'attempt', engine)
    lines = (work / 'raw-samples.csv').read_text().splitlines()
    assert len(lines) > 1
    assert 'monitor_received' in lines[0]
    assert json.loads((work / 'raw-events.json').read_text())['events']
    assert 'not every raw observation' in json.loads((work / 'raw-samples.metadata.json').read_text())['scope']
    assert engine.controller_stop.is_set()
    if failure == 'graphs':
        assert (work / 'partial-stats.csv').is_file()


def test_early_bird_startup_exit_is_actionable_without_attesting_crash():
    owned = SimpleNamespace(started={'id': 'attempt_bgperf_bird_target'})
    state = {}
    result = diagnostics.live_sample(live_client(False), owned, state,
                                     expected='target_crash', exit_reader=lambda: 127)
    assert result['status'] == 'experiment_failed'
    assert 'startup command ended' in result['reason']
    assert result['reproduction']['outcome'] == 'inconclusive'
    assert state['samples'][-1]['daemon_exit_code'] == 127


def test_host_snapshot_has_explicit_identity_without_subprocess_or_privileged_ids(monkeypatch):
    import io
    import sys
    monkeypatch.setattr(diagnostics.os, 'uname', lambda: SimpleNamespace(
        nodename='controlled-host', sysname='Linux', release='fixture-kernel',
        version='fixture build', machine='x86_64'))
    monkeypatch.setattr(diagnostics.os, 'cpu_count', lambda: 8)
    monkeypatch.setattr(diagnostics.os, 'sched_getaffinity', lambda pid: {2, 3})
    reads = []
    def read(path, *args, **kwargs):
        reads.append(str(path))
        if str(path) == '/proc/cpuinfo':
            return io.StringIO('model name\t: Controlled CPU\n')
        if str(path) == '/proc/sys/kernel/random/boot_id':
            return io.StringIO('11111111-2222-3333-4444-555555555555\n')
        pytest.fail('unexpected host file: ' + str(path))
    monkeypatch.setattr(Path, 'open', read)
    monkeypatch.setattr(diagnostics.subprocess, 'Popen', lambda *a, **k: pytest.fail('subprocess'))
    result = diagnostics.host_snapshot()
    assert result['hostname'] == 'controlled-host'
    assert result['kernel_release'] == 'fixture-kernel'
    assert result['architecture'] == 'x86_64'
    assert result['cpu_count'] == 8 and result['cpu_affinity'] == [2, 3]
    assert result['cpu_model'] == 'Controlled CPU'
    assert result['boot_id'] == '11111111-2222-3333-4444-555555555555'
    assert result['python_version'] == list(sys.version_info[:3])
    assert result['unavailable'] == {}
    assert set(reads) == {'/proc/cpuinfo', '/proc/sys/kernel/random/boot_id'}
    assert 'environment' not in result and 'machine_id' not in result


def test_host_snapshot_preserves_unknowns_without_substitution(monkeypatch):
    def unavailable(*args, **kwargs):
        raise OSError('fixture unavailable')
    monkeypatch.setattr(diagnostics.os, 'uname', unavailable)
    monkeypatch.setattr(diagnostics.os, 'cpu_count', lambda: None)
    monkeypatch.setattr(diagnostics.os, 'sched_getaffinity', unavailable)
    monkeypatch.setattr(Path, 'open', unavailable)
    result = diagnostics.host_snapshot()
    assert all(result[key] is None for key in ('hostname', 'operating_system', 'kernel_release',
               'kernel_version', 'architecture', 'cpu_count', 'cpu_affinity', 'cpu_model', 'boot_id'))
    assert set(result['unavailable']) == {'uname', 'cpu_count', 'cpu_affinity', 'cpu_model', 'boot_id'}


def test_host_identity_precedes_worker_and_survives_failure(tmp_path, monkeypatch):
    snapshot = {'schema': 'bgperf2/host/v1alpha1', 'hostname': 'controlled-host',
                'kernel_release': 'fixture-kernel', 'architecture': 'fixture-arch'}
    monkeypatch.setattr(diagnostics, 'host_snapshot', lambda: snapshot)
    class Backend:
        def execute(self, document, work, attempt, timeout):
            assert json.loads((work / 'host.json').read_text()) == snapshot
            (work / 'partial.log').write_text('retained failure')
            raise OSError('controlled collector failure')
    result = recipe_run.run_recipe(recipe(), workdir=tmp_path / 'work', results_dir=tmp_path / 'results',
        backend=Backend(), check=lambda *a, **k: {'status': 'checks_passed'})
    assert result['status'] == 'harness_failed'
    assert json.loads((tmp_path / 'results/work/host.json').read_text()) == snapshot
    host = next(item for item in result['artifacts'] if item['path'] == 'work/host.json')
    assert host['availability'] == 'present' and host['sha256']


@pytest.mark.parametrize('malformed', [None, [], 'not an object', {'State': None}, {'Config': None}])
def test_later_malformed_inspection_retains_prior_container_observations(tmp_path, malformed):
    first, second = 'a' * 64, 'b' * 64
    def command(argv, **kwargs):
        if 'ps' in argv:
            value = first + '\n' + second
        elif 'inspect' in argv:
            item = {'Id': argv[-1], 'Name': '/attempt_bird_target',
                    'Config': {'Labels': {recipe_run.OWNER_LABEL: 'attempt'}},
                    'State': {'Running': True, 'Pid': 123}}
            if argv[-1] == second:
                item = dict(item, **malformed) if isinstance(malformed, dict) else malformed
            value = json.dumps([item])
        else:
            value = 'SIMULATED retained log'
        return {'text': value, 'truncated': False, 'captured_bytes': len(value)}
    result = diagnostics.collect_diagnostics(tmp_path, 'attempt', {}, command=command,
        memory_reader=lambda pid: {'ending_bytes': 123})
    assert result['status'] == 'partial'
    assert len(result['containers']) == 1 and result['containers'][0]['id'] == first
    assert result['containers'][0]['memory']['ending_bytes'] == 123
    assert result['errors'] and second in result['errors'][0]
    assert json.loads((tmp_path / 'diagnostics.json').read_text()) == result
