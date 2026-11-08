"""Existing OpenBGPD/RustyBGP adapters through bounded supplied-image recipes."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import bgperf2
import recipes
import recipe_assertions as assertions
import recipe_bisection as bisection
import recipe_diagnostics as diagnostics
import recipe_source_range as ranges
import recipe_targets as targets
import recipe_worker as worker


ADAPTERS = ('openbgp', 'rustybgp', 'rustbgpd', 'holo', 'zebra-rs')
IMAGE = 'sha256:' + '9' * 64


def document(adapter, **target_fields):
    test = dict(name='supplied', neighbors=[2], prefixes=[100], filter_test=[None],
                monitor='sink', targets=[dict(name=adapter, **target_fields)])
    source = json.dumps({'tests': [test]})
    recipes._source_tests(source)
    cells = bgperf2.expand_batch_cells(test, bgperf2.expand_target_versions(test['targets']))
    key = bgperf2.batch_cell_key(bgperf2.batch_cell_id(test['name'], cells[0]))
    roles = {role: dict(adapter=name, image='sha256:' + digit * 64)
             for role, name, digit in [('target', adapter, '9'), ('generator', 'bird', '2'), ('observer', 'sink', '3')]}
    return recipes._recipe(source, test['name'], key, 'a' * 40, roles,
                           'Do two peers deliver exactly 200 distinct prefixes?', 'experiment_completed')


@pytest.mark.parametrize('adapter', ADAPTERS)
def test_roundtrip_export_and_assertion_expectations(adapter, tmp_path):
    recipe = document(adapter, version='selected-release')
    source = tmp_path / 'source.yaml'
    source.write_text(recipe['source']['text'])
    exported = recipes.export_recipe(source, 'supplied', recipe['selection']['cell_key'],
        engine_revision='a' * 40, roles=recipe['roles'], question=recipe['reproduction']['question'])
    assert exported == recipes.validate_recipe(copy.deepcopy(recipe))
    spec = assertions.default_assertions(exported, include_prefixes=True)
    count = next(row for row in spec['assertions'] if row['name'] == 'observer.count')
    prefixes = next(row for row in spec['assertions'] if row['name'] == 'observer.prefixes')
    assert count['expected'] == prefixes['expected']['count'] == 200
    assert prefixes['expected']['first'] == '100.0.0.0/32'
    substitute = targets.supplied_target(recipe, 'sha256:' + '8' * 64, label='candidate')
    changed = targets.effective_roles(recipe, substitute)
    assert changed['target'] == dict(adapter=adapter, image='sha256:' + '8' * 64)
    assert all(changed[role] == recipe['roles'][role] for role in ('generator', 'observer'))


@pytest.mark.parametrize('adapter', ADAPTERS)
def test_actual_adapter_config_startup_and_target_role_preserved(adapter, tmp_path):
    actual = bgperf2.TARGET_CLASSES[adapter]
    conf = {'as': 64512, 'router-id': '10.0.0.1'}
    plain = actual(str(tmp_path / 'plain'), conf)
    scoped = worker.scoped_adapter(actual, IMAGE, 'attempt', role='target',
                                   capture_exit=True, target_adapter=adapter)
    selected = scoped(str(tmp_path / 'scoped'), conf)
    assert selected.name == 'attempt_' + actual.CONTAINER_NAME
    assert selected.image == scoped.require_image() == IMAGE
    assert diagnostics.role_for_name(selected.name) == 'target'
    assert selected.get_startup_cmd() == plain.get_startup_cmd()
    assert 'recipe-bird-exit' not in selected.get_startup_cmd()
    for item in (plain, selected):
        item.scenario_neighbors = lambda **kwargs: []
        item.scenario_global_conf = {'policy': {}}
        Path(item.host_dir).mkdir(parents=True, exist_ok=True)
        item.write_config()
    assert (Path(plain.host_dir) / plain.CONFIG_FILE_NAME).read_bytes() == (
        Path(selected.host_dir) / selected.CONFIG_FILE_NAME).read_bytes()


@pytest.mark.parametrize('adapter', ADAPTERS)
def test_container_failure_is_not_a_daemon_crash_witness(adapter):
    name = 'attempt_' + bgperf2.TARGET_CLASSES[adapter].CONTAINER_NAME
    outcome = worker.health_outcome(name, {'Running': False, 'ExitCode': 139}, 'target_crash')
    assert outcome['status'] == 'experiment_failed'
    assert 'reproduction' not in outcome


@pytest.mark.parametrize('adapter', ADAPTERS)
@pytest.mark.parametrize('explicit', [False, True])
def test_live_diagnostics_attribute_memory_without_bird_probe(adapter, explicit):
    name = 'attempt_' + bgperf2.TARGET_CLASSES[adapter].CONTAINER_NAME
    owned = SimpleNamespace(started={'id': name})
    client = SimpleNamespace(stats=lambda *args, **kwargs: {'memory_stats': {'usage': 321}},
                             top=lambda *args, **kwargs: pytest.fail('BIRD process probe'))
    previous = {'bird_seen': ['id']}
    kwargs = dict(target_adapter=adapter) if explicit else {}
    assert diagnostics.live_sample(client, owned, previous, expected='experiment_completed',
        exit_reader=lambda: pytest.fail('BIRD exit witness'), **kwargs) is None
    assert previous['sampled_peak_bytes'] == {'target': 321}
    assert previous['samples'][0]['bird_process_present'] is None
    assert previous['unsupported']


@pytest.mark.parametrize('adapter', ADAPTERS)
def test_final_diagnostics_preserve_role_and_capability_limits(adapter, tmp_path):
    identifier = 'b' * 64
    name = 'attempt_' + bgperf2.TARGET_CLASSES[adapter].CONTAINER_NAME
    def command(argv, **kwargs):
        if 'ps' in argv:
            text = identifier
        elif 'inspect' in argv:
            text = json.dumps([{'Id': identifier, 'Name': '/' + name,
                'Config': {'Labels': {'bgperf2.recipe.attempt': 'attempt'}},
                'State': {'Running': True, 'Pid': 321}}])
        else:
            text = 'bounded daemon output'
        return dict(text=text, truncated=False, captured_bytes=len(text))
    result = diagnostics.collect_diagnostics(tmp_path, 'attempt', {}, command=command,
        target_adapter=adapter, memory_reader=lambda pid: {'ending_bytes': 123})
    assert result['containers'][0]['role'] == 'target'
    assert result['memory']['target']['ending_bytes'] == 123
    assert result['capabilities']['bird_daemon_exit'] is False
    assert result['capabilities']['bird_process_presence'] is False


@pytest.mark.parametrize('adapter', ADAPTERS)
def test_unsupported_crash_and_threads_refuse(adapter):
    recipe = document(adapter)
    recipe['reproduction']['expected_outcome'] = 'target_crash'
    with pytest.raises(recipes.ContractError, match='target_crash'):
        recipes.validate_recipe(recipe)
    with pytest.raises(recipes.ContractError, match='thread'):
        document(adapter, threads=4)


@pytest.mark.parametrize('adapter', ADAPTERS)
def test_source_build_and_range_refuse_before_source_or_host_probes(adapter, monkeypatch):
    recipe = document(adapter)
    monkeypatch.setattr(targets, '_snapshot', lambda *args, **kwargs: pytest.fail('source snapshot'))
    monkeypatch.setattr(ranges, 'LocalGit', lambda *args, **kwargs: pytest.fail('Git probe'))
    with pytest.raises(recipes.ContractError, match='source builds.*unsupported'):
        targets.plan_source_build(recipe, '/must-not-open', 'b' * 40,
            toolchain_image=IMAGE, runtime_image=IMAGE)
    with pytest.raises(recipes.ContractError, match='source builds.*unsupported'):
        ranges.prepare_range(recipe, source_root='/must-not-open', good='a' * 40,
            bad='b' * 40, toolchain_image=IMAGE, runtime_image=IMAGE, output_dir='/must-not-create')
    def forbidden():
        pytest.fail('Candidate plans iterated before refusal')
        yield
    with pytest.raises(recipes.ContractError, match='source builds.*unsupported'):
        bisection.make_plan(recipe, forbidden(), forbidden(), predicate='assertions', max_trials=4)


@pytest.mark.parametrize('adapter', ADAPTERS)
def test_forged_local_source_identity_refuses_cleanly(adapter):
    recipe = document(adapter)
    target = targets.supplied_target(recipe, IMAGE, label='unsupported-build')
    target['provenance']['kind'] = 'local_source'
    with pytest.raises(recipes.ContractError, match='source builds.*unsupported'):
        targets.validate_target(target, recipe)
    forged = dict.fromkeys(('schema', 'recipe', 'recipe_sha256', 'source_root', 'source',
        'toolchain_image', 'runtime_image', 'instrumentation', 'cflags', 'configure_flags',
        'build_recipe', 'network', 'requirements', 'limits'))
    forged.update(schema=targets.BUILD_SCHEMA, recipe=recipe)
    with pytest.raises(recipes.ContractError, match='source builds.*unsupported'):
        targets.validate_build_plan(forged)


@pytest.mark.parametrize('adapter', ADAPTERS)
def test_worker_reuses_existing_lifecycle_and_preserves_raw_evidence(adapter, tmp_path):
    from test_run_lifecycle import fake_run
    engine, _, calls, components = fake_run(tmp_path)
    engine.TARGET_CLASSES = {adapter: engine.TARGET_CLASSES['bird']}
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
    base = document(adapter)
    source = json.loads(base['source']['text'])
    source['tests'][0].update(neighbors=[1], prefixes=[10])  # Existing lifecycle fixture's workload.
    text = json.dumps(source)
    test = recipes._source_tests(text)[0]
    cell = bgperf2.expand_batch_cells(test, bgperf2.expand_target_versions(test['targets']))[0]
    key = bgperf2.batch_cell_key(bgperf2.batch_cell_id(test['name'], cell))
    selected = recipes._recipe(text, test['name'], key, base['engine']['revision'],
                               base['roles'], 'Modeled lifecycle only.', 'experiment_completed')
    work = tmp_path / 'work'
    work.mkdir()
    result = worker.execute(selected, work, 'attempt', engine)
    assert result['status'] == 'completed'
    assert calls.index('establish') < calls.index('launch')
    assert engine.controller_stop.is_set() and all(component.stop_monitoring for component in components)
    events = json.loads((work / 'raw-events.json').read_text())['events']
    assert events[-1]['event'] == 'convergence_confirmed'
    assert 'monitor_received' in (work / 'raw-samples.csv').read_text()
    assert (work / 'stats.csv').is_file()
