"""Recipe isolation and lifecycle bridge exercised with owned fake runtimes."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import recipes
import recipe_run
import recipe_worker


def recipe():
    return recipes.read_document(Path(__file__).parents[1] / 'examples/recipes/synthetic-ipv4.recipe.json')


def test_refusal_creates_nothing(tmp_path):
    result = recipe_run.run_recipe(recipe(), workdir=tmp_path / 'work', results_dir=tmp_path / 'results',
                                   check=lambda *a, **k: {'status': 'refused'},
                                   backend=SimpleNamespace(execute=lambda *a: pytest.fail('runtime called')))
    assert result['status'] == 'setup_refused'
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('timeout', [0, -1, True, float('nan'), float('inf')])
def test_invalid_budget_before_probes(tmp_path, timeout):
    with pytest.raises(recipes.ContractError):
        recipe_run.run_recipe(recipe(), workdir=tmp_path / 'work', results_dir=tmp_path / 'results', timeout=timeout,
                              check=lambda *a, **k: pytest.fail('probed'))


def test_attempt_package_and_preservation(tmp_path):
    class Backend:
        def execute(self, document, work, attempt, timeout):
            assert attempt.startswith('bgperf_recipe_')
            outcome = {'status': 'completed', 'reason': 'Fixture completed'}
            (work / 'runtime.json').write_text(json.dumps(outcome))
            (work / 'scenario.yaml').write_text('fixture')
            return outcome
    kwargs = dict(workdir=tmp_path / 'work', results_dir=tmp_path / 'results', backend=Backend(),
                  check=lambda *a, **k: {'status': 'checks_passed'})
    result = recipe_run.run_recipe(recipe(), **kwargs)
    assert result['status'] == 'completed'
    from recipe_results import verify_result_package
    assert verify_result_package(tmp_path / 'results' / 'result.json')['valid']
    with pytest.raises(recipes.ContractError, match='already exist'):
        recipe_run.run_recipe(recipe(), **kwargs)


def test_owned_docker_rejects_foreign_removal_and_unselected_images():
    calls = []
    client = SimpleNamespace(inspect_container=lambda key: {'Id': key, 'Config': {'Labels': {}}},
                             remove_container=lambda *a, **k: calls.append(a))
    runtime = recipe_worker.OwnedDocker(client, 'attempt', ['sha256:a'])
    with pytest.raises(RuntimeError, match='unselected'):
        runtime.create_container(image='latest', name='attempt_target')
    with pytest.raises(RuntimeError, match='foreign'):
        runtime.remove_container('foreign', force=True)
    assert not calls


def test_owned_docker_labels_and_tracks_started_names():
    calls = []
    client = SimpleNamespace(create_container=lambda **kwargs: calls.append(kwargs) or {'Id': 'id'},
                             start=lambda **kwargs: calls.append(kwargs))
    runtime = recipe_worker.OwnedDocker(client, 'attempt', ['sha256:a'])
    runtime.create_container(image='sha256:a', name='attempt_target')
    runtime.start(container='attempt_target')
    assert calls[0]['labels'] == {recipe_run.OWNER_LABEL: 'attempt'}
    assert runtime.started == {'id': 'attempt_target'}


def test_actual_adapter_constructor_pins_all_three_roles(tmp_path):
    import bgperf2
    classes = [bgperf2.TARGET_CLASSES['bird'], bgperf2.BIRDTester, bgperf2.MONITOR_CLASSES['sink']]
    for index, adapter in enumerate(classes):
        selected = recipe_worker.scoped_adapter(adapter, 'sha256:' + str(index) * 64, 'attempt')
        args = (str(tmp_path / str(index)), {})
        if index == 1:
            args = ('tester0', *args)
        instance = selected(*args)
        assert instance.image == 'sha256:' + str(index) * 64
        assert instance.name.startswith('attempt_')
        assert selected.require_image() == instance.image


@pytest.mark.parametrize('pin', [None, 'target=0,monitor=1,testers=2-3'])
@pytest.mark.parametrize('capture_prefixes', [False, True])
def test_worker_uses_existing_lifecycle_with_queued_observations(tmp_path, monkeypatch, pin, capture_prefixes):
    from test_run_lifecycle import fake_run
    from test_recipes import source, export
    import bgperf2
    runtime, args, calls, components = fake_run(tmp_path)
    # The worker selects sink, but adapter fixture observations retain existing
    # queue/convergence behavior. No Docker client is consulted.
    component = runtime.MONITOR_CLASSES['gobgp']
    if capture_prefixes:
        class CapturingMonitor(component):
            guest_dir = '/root/config'
            def __init__(self, host_dir, conf):
                super().__init__(host_dir, conf)
                self.host_dir = host_dir
                Path(host_dir).mkdir(parents=True, exist_ok=True)
        component = CapturingMonitor
    runtime.MONITOR_CLASSES = {'sink': component}
    parser = bgperf2.create_args_parser()
    def parse(argv):
        args.__dict__.update(vars(parser.parse_args(argv)))
        return args
    runtime.create_args_parser = lambda: SimpleNamespace(parse_args=parse)
    args.monitor = 'sink'
    args.bench_name = 'attempt'
    args.dir = str(tmp_path / 'work')
    runtime.dckr = SimpleNamespace(networks=lambda **kw: [])
    network_calls = [0]
    def networks(**kwargs):
        network_calls[0] += 1
        return [] if network_calls[0] == 1 else [{'Name': 'attempt-br'}]
    runtime.dckr.networks = networks
    runtime.capture_tool_revision = lambda: None
    runtime.TARGET_CLASSES['bird'].CONTAINER_NAME = 'target'
    # Prefix fixture names in samples exactly as the selected adapters do.
    old_queue = runtime.Queue
    def queue():
        result = old_queue()
        for item in result.messages:
            if item['who'] in ('target', 'bgperf_monitor'):
                item['who'] = 'attempt_' + item['who']
        return result
    runtime.Queue = queue
    monkeypatch.setattr(bgperf2, 'host_cpus', lambda: frozenset(range(4)))
    path, test = source(tmp_path, neighbors=[1], prefixes=[10], **({'pin': pin} if pin else {}))
    document = export(path, test)
    (tmp_path / 'work').mkdir(exist_ok=True)
    import recipe_prefixes
    captures = []
    def capture(path, document):
        # The legacy lifecycle must finish and emit its events before capture.
        assert list((tmp_path / 'work/artifacts').glob('*.events.json'))
        captures.append(path)
        return {'fixture': 'post-measurement capture'}
    monkeypatch.setattr(recipe_prefixes, 'capture', capture)
    if capture_prefixes:
        (tmp_path / 'work/diagnostic-options.json').write_text(json.dumps({
            'mode': 'none', 'observer_prefixes': True}))
    outcome = recipe_worker.execute(document, tmp_path / 'work', 'attempt', runtime)
    assert outcome['status'] == 'completed'
    assert 'remove_target_containers' not in calls
    assert 'remove_old_containers' not in calls
    assert all(item.name.startswith('attempt_') for item in components)
    assert {item.image for item in components} == {item['image'] for item in document['roles'].values()}
    assert args.pin == pin
    assert captures == ([tmp_path/'work/attempt/monitor/prefixes.sock'] if capture_prefixes else [])
    assert (tmp_path/'work/observer-prefixes.json').exists() == capture_prefixes
    expected = {'target': '0', 'monitor': '1', 'testers': '2-3'} if pin else {}
    for item in components:
        role = 'monitor' if item.name.endswith('monitor') else 'target' if item.name.endswith('target') else 'testers'
        assert item.cpuset == expected.get(role)
    event = json.loads(next((tmp_path / 'work/artifacts').glob('*.events.json')).read_text())
    assert event['run']['pin'] == (expected if pin else None)


@pytest.mark.parametrize('failure,status,exit_code', [
    ('timeout', 'inconclusive', None), ('interrupt', 'interrupted', 130),
    ('term', 'interrupted', 143), ('bad_worker', 'harness_failed', None)])
def test_worker_supervision_preserves_partial_evidence(tmp_path, monkeypatch, failure, status, exit_code):
    import signal
    import subprocess
    work = tmp_path / 'work'
    work.mkdir()
    killed = []
    class Process:
        pid = 3456
        returncode = None
        def wait(self, timeout):
            if self.returncode is None:
                if failure == 'timeout':
                    raise subprocess.TimeoutExpired('worker', timeout)
                if failure == 'interrupt':
                    raise KeyboardInterrupt()
                if failure == 'term':
                    raise SystemExit(143)
                self.returncode = 1
            return self.returncode
        def poll(self):
            return self.returncode
    process = Process()
    def killpg(pid, signum):
        killed.append((pid, signum))
        process.returncode = -9
    monkeypatch.setattr(recipe_run.subprocess, 'Popen', lambda *a, **k: process)
    monkeypatch.setattr(recipe_run.os, 'killpg', killpg)
    monkeypatch.setattr(recipe_run, '_cleanup', lambda *a: [])
    outcome = recipe_run.SubprocessBackend().execute(recipe(), work, 'attempt', 0.01)
    assert outcome['status'] == status
    assert outcome.get('exit_code') == exit_code
    assert (work / 'runtime.json').is_file()
    assert (work / 'console.log').is_file()
    assert killed and all(value == (3456, signal.SIGKILL) for value in killed)
    budget = json.loads((work / 'execution-budget.json').read_text())
    assert budget['scope'] == 'worker' and budget['timeout_seconds'] == 0.01
    assert budget['elapsed_seconds'] >= 0
    if failure == 'timeout':
        assert budget['completed_within_budget'] is False
    elif failure in ('interrupt', 'term'):
        assert budget['completed_within_budget'] is None


def test_worker_budget_excludes_collection_and_cleanup(tmp_path, monkeypatch):
    class Process:
        pid = 34
        returncode = 0
        def wait(self, timeout):
            recipe_run._write(tmp_path / 'runtime.json', {'status': 'completed', 'reason': 'done'})
        def poll(self):
            return 0
    clock = iter([10.0, 12.0])
    monkeypatch.setattr(recipe_run.time, 'monotonic', lambda: next(clock))
    monkeypatch.setattr(recipe_run.subprocess, 'Popen', lambda *a, **k: Process())
    monkeypatch.setattr(recipe_run.os, 'killpg', lambda *a: None)
    monkeypatch.setattr(recipe_run, '_cleanup', lambda *a: [])
    import recipe_diagnostics
    monkeypatch.setattr(recipe_diagnostics, 'stage', lambda *a, **k: None)
    monkeypatch.setattr(recipe_diagnostics, 'collect_diagnostics', lambda *a, **k: {'errors': []})
    assert recipe_run.SubprocessBackend().execute(recipe(), tmp_path, 'attempt', 3)['status'] == 'completed'
    budget = json.loads((tmp_path / 'execution-budget.json').read_text())
    assert budget == {'schema': 'bgperf2/execution-budget/v1alpha1', 'scope': 'worker',
                      'started_monotonic_s': 10, 'ended_monotonic_s': 12,
                      'timeout_seconds': 3, 'elapsed_seconds': 2, 'completed_within_budget': True}


def test_cleanup_discovers_ids_and_rechecks_labels(monkeypatch):
    calls = []
    def command(argv, **kwargs):
        calls.append(argv)
        if 'inspect' in argv:
            return json.dumps([{'Config': {'Labels': {recipe_run.OWNER_LABEL: 'foreign'}}}])
        if 'ps' in argv:
            return 'container-id\n'
        return ''
    monkeypatch.setattr(recipe_run.preflight, 'run_command', command)
    errors = recipe_run._cleanup('attempt', {})
    assert errors and 'ownership changed' in errors[0]
    assert all('rm' not in command for command in calls)


@pytest.mark.parametrize('failure', ['inspect', 'ownership', 'remove'])
@pytest.mark.parametrize('kind', ['container', 'network'])
def test_cleanup_continues_with_other_owned_resources_after_one_failure(monkeypatch, failure, kind):
    removed = []
    def command(argv, **kwargs):
        if 'inspect' in argv:
            identifier = argv[-1]
            if identifier == 'bad' and failure == 'inspect':
                raise recipe_run.preflight.ProbeError('container disappeared during inspection')
            owner = 'foreign' if identifier == 'bad' and failure == 'ownership' else 'attempt'
            return json.dumps([{'Config': {'Labels': {recipe_run.OWNER_LABEL: owner}},
                                'Labels': {recipe_run.OWNER_LABEL: owner}}])
        if 'rm' in argv:
            if argv[-1] == 'bad' and failure == 'remove':
                raise recipe_run.preflight.ProbeError('container removal failed')
            removed.append(argv[-1])
            return ''
        listed_kind = 'container' if 'ps' in argv else 'network'
        return 'bad good' if listed_kind == kind else 'other'
    monkeypatch.setattr(recipe_run.preflight, 'run_command', command)
    errors = recipe_run._cleanup('attempt', {})
    assert errors and len(errors) == 1
    assert removed == (['good', 'other'] if kind == 'container' else ['other', 'good'])


def test_worker_returning_after_observed_budget_is_inconclusive(tmp_path, monkeypatch):
    class Process:
        pid = 34
        returncode = 0
        def wait(self, timeout):
            recipe_run._write(tmp_path / 'runtime.json', {'status': 'completed', 'reason': 'done'})
        def poll(self):
            return 0
    clock = iter([10.0, 14.0])
    monkeypatch.setattr(recipe_run.time, 'monotonic', lambda: next(clock))
    monkeypatch.setattr(recipe_run.subprocess, 'Popen', lambda *a, **k: Process())
    monkeypatch.setattr(recipe_run.os, 'killpg', lambda *a: None)
    monkeypatch.setattr(recipe_run, '_cleanup', lambda *a: [])
    import recipe_diagnostics
    monkeypatch.setattr(recipe_diagnostics, 'stage', lambda *a, **k: None)
    monkeypatch.setattr(recipe_diagnostics, 'collect_diagnostics', lambda *a, **k: {'errors': []})
    outcome = recipe_run.SubprocessBackend().execute(recipe(), tmp_path, 'attempt', 3)
    assert outcome['status'] == 'inconclusive'
    budget = json.loads((tmp_path / 'execution-budget.json').read_text())
    assert budget['elapsed_seconds'] == 4 and budget['completed_within_budget'] is False


def test_cleanup_failure_changes_completed_status(tmp_path, monkeypatch):
    class Process:
        pid = 34
        returncode = 0
        def wait(self, timeout):
            recipe_run._write(tmp_path / 'runtime.json', {'status': 'completed', 'reason': 'done'})
        def poll(self):
            return 0
    monkeypatch.setattr(recipe_run.subprocess, 'Popen', lambda *a, **k: Process())
    monkeypatch.setattr(recipe_run.os, 'killpg', lambda *a: None)
    monkeypatch.setattr(recipe_run, '_cleanup', lambda *a: ['cannot remove owned container'])
    outcome = recipe_run.SubprocessBackend().execute(recipe(), tmp_path, 'attempt', 1)
    assert outcome['status'] == 'harness_failed'
    assert outcome['cleanup_errors']


@pytest.mark.parametrize('role,state,status,reproduced', [
    ('bgperf_bird_target', {'Running': False, 'ExitCode': 139}, 'experiment_failed', True),
    ('bgperf_bird_target', {'Running': False, 'ExitCode': 0}, 'experiment_failed', False),
    ('bgperf_monitor', {'Running': False, 'ExitCode': 1}, 'inconclusive', False),
    ('bgperf_bird_tester_0', {'Running': False, 'ExitCode': 1}, 'experiment_failed', False),
    ('bgperf_bird_target', {'Running': True, 'ExitCode': 139}, None, False),
    ('bgperf_bird_target', {}, None, False)])
def test_observed_role_health_status_and_crash_witness(role, state, status, reproduced):
    outcome = recipe_worker.health_outcome('attempt_' + role, state, 'target_crash')
    if status is None:
        assert outcome is None
    else:
        assert outcome['status'] == status
        assert (outcome.get('reproduction', {}).get('outcome') == 'reproduced') is reproduced


def test_unreadable_container_health_does_not_attest_crash():
    owned = SimpleNamespace(started={'id': 'attempt_bgperf_bird_target'},
                            client=SimpleNamespace(inspect_container=lambda key: {}))
    assert recipe_worker.scan_health(owned, 'target_crash') is None


def test_backend_collection_exception_retains_partial_package(tmp_path):
    class Backend:
        def execute(self, document, work, attempt, timeout):
            (work / 'partial.log').write_text('partial evidence')
            raise OSError('collector unavailable')
    result = recipe_run.run_recipe(recipe(), workdir=tmp_path / 'work', results_dir=tmp_path / 'results',
                                   check=lambda *a, **k: {'status': 'checks_passed'}, backend=Backend())
    assert result['status'] == 'harness_failed'
    assert (tmp_path / 'results/work/partial.log').read_text() == 'partial evidence'
