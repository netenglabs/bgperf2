"""Receive timing never inherits observer convergence or incomplete fleet success."""
import copy
import json
from types import SimpleNamespace

import pytest
import recipes
import recipe_receive_loading as loading
from test_recipe_receive import fixture


def source():
    recipe, expected, rib = fixture()
    completion = {'monotonic_s': 12.0, 'details': {'poll_resolution_s': 1},
                  'event': 'tester_complete', 'counters': {
                      'sessions': 2, 'sessions_measured': 2, 'configured_prefixes': 16,
                      'expected_prefixes': 16, 'offered_prefixes': 16}}
    return recipe, expected, rib, completion


def test_capacity_selection_keeps_qualification_bounds_separate():
    recipe, _, _, _ = source()
    recipe['resolved']['prefixes_per_peer'] = 2048
    loading.validate_selection(recipe, True)
    from recipe_receive import validate_selection
    with pytest.raises(recipes.ContractError): validate_selection(recipe, True)
    for field, value in [('prefixes_per_peer', 2049), ('filter', 'as-path')]:
        changed = copy.deepcopy(recipe)
        changed['resolved'][field] = value
        with pytest.raises(recipes.ContractError): loading.validate_selection(changed, True)


def test_missing_retired_or_partial_fleet_refuses():
    _, expected, _, completion = source()
    event = SimpleNamespace(to_dict=lambda: completion)
    recorder = SimpleNamespace(complete=True, events=[event])
    assert loading.generator_witness({'owned': recorder}, {}, expected)[1] == completion
    for recorders, errors in [({}, {}), ({'owned': recorder}, {'owned': 'retired'})]:
        with pytest.raises(ValueError): loading.generator_witness(recorders, errors, expected)
    completion['counters']['offered_prefixes'] = 8
    with pytest.raises(ValueError): loading.generator_witness({'owned': recorder}, {}, expected)


@pytest.mark.parametrize('case', ['exact', 'partial', 'malformed', 'late', 'regression', 'http', 'peer'])
def test_readiness_requires_two_consecutive_exact_bounded_reads(case):
    _, expected, rib, completion = source()
    now, calls, sleeps = [12.0], [], []
    def query(name, uri):
        calls.append(name)
        start = now[0]
        now[0] += 0.03
        if name == 'neighbors':
            data = {p['address']: {'fsm_state': 'Established', 'asn': p['asn'],
                                  'remote_ip': p['address']} for p in expected['peers']}
            if case == 'peer': data.clear()
        else:
            data = copy.deepcopy(rib)
            if case == 'http': raise ValueError('HTTP failed')
            if case == 'malformed': data = []
            if case == 'late': now[0] = 200
            if case == 'partial' or case == 'regression' and name == 'imported-2':
                data.pop(next(iter(data)))
        return {'name': name, 'body': json.dumps(data).encode(),
                'started_monotonic_s': start, 'completed_monotonic_s': now[0]}
    def sleep(seconds):
        sleeps.append(seconds)
        now[0] += seconds
    receipt = loading.observe(expected, {'monotonic_s': 10, 'utc': 'source-bound'},
                              completion, query, deadline=130, clock=lambda: now[0], sleep=sleep)
    assert all('body' not in q for q in receipt['queries'])
    if case in ('exact', 'regression'):
        assert receipt['status'] == 'passed'
        assert receipt['timing']['release_to_generator_completion_s'] == 2
        assert receipt['timing']['release_to_first_exact_snapshot_s'] > 2
        assert len(sleeps) == (1 if case == 'exact' else 3)
    else:
        assert receipt['status'] == ('failed' if case == 'partial' else 'unmeasured')
        assert receipt['timing'] is None
    if case == 'partial': assert len(calls) == loading.MAX_SNAPSHOTS + 1


def test_generator_clock_before_release_withholds_time():
    _, expected, _, completion = source()
    receipt = loading.observe(expected, {'monotonic_s': 13}, completion,
                              lambda *a: pytest.fail('must not query'), deadline=130, clock=lambda: 14)
    assert receipt['status'] == 'unmeasured' and receipt['timing'] is None


@pytest.mark.parametrize('failure', [False, True])
def test_separate_lifecycle_has_no_transit_row_and_stops_samplers(tmp_path, failure):
    from test_run_lifecycle import fake_run
    import run_lifecycle
    runtime, args, calls, components = fake_run(tmp_path)
    def loading_hook(**kwargs):
        assert calls.index('release') < calls.index('launch')
        assert kwargs['release']['monotonic_s'] == 100
        assert not runtime.controller_stop.is_set()
        if failure:
            raise ValueError('modeled receipt failure')
    runtime.receive_loading = loading_hook
    runtime.receive_loading_release = lambda release: calls.append("release")
    runtime.ConvergenceTracker = lambda **kw: pytest.fail('receive must not enter transit tracker')
    if failure:
        with pytest.raises(ValueError, match='modeled receipt failure'): run_lifecycle.bench(runtime, args)
    else:
        assert run_lifecycle.bench(runtime, args) is None
    assert runtime.controller_stop.is_set()
    assert all(c.stop_monitoring for c in components)
    assert 'join' in calls and 'graphs' not in calls
    assert (tmp_path / 'work/receive-role-cpu.json').is_file()


def test_loading_cli_dispatch_and_exclusive_options(tmp_path, monkeypatch):
    import sys
    from test_recipes import source, export, ROLES
    from recipe_run import run_recipe
    path, test = source(tmp_path, neighbors=[2], prefixes=[8], targets=[{'name': 'maghemite'}])
    roles = copy.deepcopy(ROLES)
    roles['target']['adapter'] = 'maghemite'
    recipe = export(path, test, roles=roles)
    document = tmp_path / 'recipe.json'
    document.write_text(json.dumps(recipe))
    for option in ('maghemite_receive', 'observer_prefixes', 'pre_replay_gate'):
        with pytest.raises(recipes.ContractError, match='separate selection'):
            run_recipe(recipe, workdir='/unused-work', results_dir='/unused-results',
                       maghemite_loading=True, **{option: True})
    calls = []
    monkeypatch.setitem(sys.modules, 'recipe_run', SimpleNamespace(
        run_recipe=lambda document, **kw: calls.append(kw) or {'status': 'inconclusive', 'exit_code': 5}))
    assert recipes.main(['run', str(document), '--workdir', '/unused-work',
                         '--results-dir', '/unused-results', '--maghemite-loading']) == 5
    assert calls[0]['maghemite_loading'] is True
