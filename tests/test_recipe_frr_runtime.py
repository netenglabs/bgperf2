"""Supplied FRR runtime dispatch and conservative diagnostics, without Docker."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import bgperf2
from frr_compiled import FRRoutingCompiledTarget
import recipe_diagnostics as diagnostics
import recipe_worker as worker
import recipes


FRR_NAME = 'attempt_bgperf_frrouting_compiled_target'
IMAGE = 'sha256:' + '9' * 64


def document_for(adapter):
    base = recipes.read_document(Path(__file__).parents[1] / 'examples/recipes/synthetic-ipv4.recipe.json')
    text = base['source']['text'].replace('name: bird', 'name: ' + adapter)
    roles = copy.deepcopy(base['roles'])
    roles['target'] = {'adapter': adapter, 'image': IMAGE}
    test = recipes._source_tests(text)[0]
    cell = bgperf2.expand_batch_cells(test, bgperf2.expand_target_versions(test['targets']))[0]
    key = bgperf2.batch_cell_key(bgperf2.batch_cell_id(test['name'], cell))
    return recipes._recipe(text, test['name'], key, base['engine']['revision'],
                           roles, 'Does the supplied target complete? ', 'experiment_completed')


@pytest.mark.parametrize('adapter_keyword', [{}, {'target_adapter': 'frr_c'}])
def test_scoped_actual_frr_preserves_constructor_startup_and_config(tmp_path, adapter_keyword):
    conf = {'as': 64512, 'router-id': '10.0.0.1'}
    plain = FRRoutingCompiledTarget(str(tmp_path / 'plain'), conf)
    selected = worker.scoped_adapter(FRRoutingCompiledTarget, IMAGE, 'attempt',
                                    role='target', capture_exit=True, **adapter_keyword)
    target = selected(str(tmp_path / 'attempt/frr_c'), conf)
    assert target.name == FRR_NAME
    assert target.host_dir == str(tmp_path / 'attempt/frr_c')
    assert target.image == selected.require_image() == IMAGE
    assert target.guest_dir == '/root/config'
    assert target.get_startup_cmd() == plain.get_startup_cmd()
    assert '/usr/lib/frr/bgpd ' in target.get_startup_cmd()
    assert 'recipe-bird-exit' not in target.get_startup_cmd()
    for adapter in (plain, target):
        adapter.scenario_neighbors = lambda **kwargs: []
        adapter.scenario_global_conf = {}
        adapter.write_config()
    assert (Path(target.host_dir) / 'bgpd.conf').read_bytes() == (Path(plain.host_dir) / 'bgpd.conf').read_bytes()


@pytest.mark.parametrize('adapter', ['bird', 'frr_c'])
def test_execute_dispatches_selected_adapter_and_fixed_roles(tmp_path, monkeypatch, adapter):
    document = document_for(adapter)
    engine = SimpleNamespace(**vars(bgperf2))
    engine.dckr = SimpleNamespace(networks=lambda **kwargs: [])
    engine.capture_tool_revision = lambda: None
    engine.stats_header = lambda: 'observed'
    engine.row_failed = lambda row: False
    (tmp_path / 'diagnostic-options.json').write_text('{"mode":"basic"}')
    def bench(runtime, args):
        assert args.target == adapter and args.image == IMAGE
        assert args.monitor == 'sink' and args.tester_type == 'bird'
        assert args.threads is None
        assert set(runtime.TARGET_CLASSES) == {adapter}
        assert issubclass(runtime.TARGET_CLASSES[adapter], engine.TARGET_CLASSES[adapter])
        assert runtime.TARGET_CLASSES[adapter].require_image() == IMAGE
        assert runtime.BIRDTester.require_image() == document['roles']['generator']['image']
        assert runtime.MONITOR_CLASSES['sink'].require_image() == document['roles']['observer']['image']
        return [1]
    monkeypatch.setattr('run_lifecycle.bench', bench)
    assert worker.execute(document, tmp_path, 'attempt', engine)['status'] == 'completed'
    assert (tmp_path / 'stats.csv').read_text() == 'observed\n1\n'


@pytest.mark.parametrize('state', [{'Running': True}, {}, {'Running': None}])
def test_frr_health_never_infers_failure_from_missing_or_running_state(state):
    assert worker.health_outcome(FRR_NAME, state, 'target_crash') is None


def test_frr_stopped_container_is_failure_without_daemon_crash_witness():
    result = worker.health_outcome(FRR_NAME, {'Running': False, 'ExitCode': 139}, 'target_crash')
    assert result['status'] == 'experiment_failed'
    assert 'reproduction' not in result
    assert worker.health_outcome('attempt_bgperf_bird_target',
        {'Running': False, 'ExitCode': 139}, 'target_crash')['reproduction']['outcome'] == 'reproduced'


@pytest.mark.parametrize('adapter_keyword', [{}, {'target_adapter': 'frr_c'}])
def test_frr_live_memory_skips_bird_probe_and_exit_evidence(adapter_keyword):
    owned = SimpleNamespace(started={'id': FRR_NAME})
    client = SimpleNamespace(stats=lambda *args, **kwargs: {'memory_stats': {'usage': 123}},
                             top=lambda *args, **kwargs: pytest.fail('BIRD process probe on FRR'))
    previous = {'bird_seen': ['id']}
    for _ in range(2):
        assert diagnostics.live_sample(client, owned, previous, expected='target_crash',
            exit_reader=lambda: pytest.fail('BIRD exit file on FRR'), **adapter_keyword) is None
    assert previous['sampled_peak_bytes'] == {'target': 123}
    assert previous['samples'][-1]['bird_process_present'] is None
    assert 'daemon_exit_code' not in previous['samples'][-1]
    assert previous['unsupported']
    assert diagnostics.role_for_name('attempt_bgperf_bird_tester_0') == 'generator'
    assert diagnostics.role_for_name('attempt_bgperf_monitor') == 'observer'


def test_frr_final_diagnostics_retains_target_memory_and_capability_limits(tmp_path):
    identifier = 'a' * 64
    def command(argv, **kwargs):
        if 'ps' in argv:
            text = identifier
        elif 'inspect' in argv:
            text = json.dumps([{'Id': identifier, 'Name': '/' + FRR_NAME,
                'Config': {'Labels': {'bgperf2.recipe.attempt': 'attempt'}},
                'State': {'Running': True, 'Pid': 321}}])
        else:
            text = 'bounded FRR output'
        return {'text': text, 'truncated': False, 'captured_bytes': len(text)}
    result = diagnostics.collect_diagnostics(tmp_path, 'attempt', {}, command=command,
        target_adapter='frr_c', memory_reader=lambda pid: {'ending_bytes': 321})
    assert result['containers'][0]['role'] == 'target'
    assert result['memory']['target']['ending_bytes'] == 321
    assert result['capabilities']['bird_daemon_exit'] is False
    assert result['capabilities']['bird_process_presence'] is False
    assert result['unsupported']


def test_frr_unavailable_final_containers_keep_unsupported_daemon_witnesses(tmp_path):
    result = diagnostics.collect_diagnostics(tmp_path, 'attempt', {}, target_adapter='frr_c',
        command=lambda *args, **kwargs: {'text': '', 'truncated': False, 'captured_bytes': 0})
    assert result['containers'] == []
    assert result['memory']['target']['ending_bytes'] is None
    assert result['capabilities']['bird_daemon_exit'] is False
    assert result['unsupported']


def test_frr_worker_keeps_existing_lifecycle_observation_and_raw_evidence(tmp_path):
    from test_run_lifecycle import fake_run
    engine, _, calls, components = fake_run(tmp_path)
    engine.TARGET_CLASSES = {'frr_c': engine.TARGET_CLASSES['bird']}
    engine.MONITOR_CLASSES = {'sink': engine.MONITOR_CLASSES['gobgp']}
    network_calls = []
    def networks(**kwargs):
        network_calls.append(kwargs)
        return [] if len(network_calls) == 1 else [{'Name': 'attempt-br'}]
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
    work = tmp_path / 'work'
    work.mkdir()
    document = document_for('frr_c')
    # Match the modeled lifecycle's ten offered routes; identities are rebuilt.
    text = document['source']['text'].replace('prefixes: [100]', 'prefixes: [10]')
    test = recipes._source_tests(text)[0]
    cell = bgperf2.expand_batch_cells(test, bgperf2.expand_target_versions(test['targets']))[0]
    key = bgperf2.batch_cell_key(bgperf2.batch_cell_id(test['name'], cell))
    document = recipes._recipe(text, test['name'], key, document['engine']['revision'],
                               document['roles'], 'Modeled lifecycle only.', 'experiment_completed')
    result = worker.execute(document, work, 'attempt', engine)
    assert result['status'] == 'completed'
    assert all(component.stop_monitoring for component in components)
    assert calls.index('establish') < calls.index('launch')
    assert engine.controller_stop.is_set()
    events = json.loads((work / 'raw-events.json').read_text())['events']
    assert events[-1]['event'] == 'convergence_confirmed'
    assert 'monitor_received' in (work / 'raw-samples.csv').read_text()
    assert (work / 'stats.csv').is_file()
