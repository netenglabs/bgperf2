"""Prefix identity distinguishes equal counts without a daemon or network."""
import copy
import ipaddress
import json
from pathlib import Path

import pytest

import recipe_prefixes as prefixes
import recipes
from recipe_assertions import default_assertions, evaluate_assertions
from test_recipe_assertions import evidence, package, by_capability


@pytest.fixture
def recipe():
    return recipes.read_document(Path(__file__).parents[1] / 'examples/recipes/synthetic-ipv4.recipe.json')


def captured(recipe):
    first = int(ipaddress.IPv4Address('100.0.0.0'))
    values = [str(ipaddress.IPv4Address(first + n)) + '/32'
              for n in range(prefixes.expected_count(recipe))]
    return {'schema': prefixes.CAPTURE_SCHEMA, 'recipe_sha256': recipes.recipe_sha256(recipe),
            'status': 'collected', 'phase': 'post_measurement', 'requested_ns': 14_100_000_000,
            'completed_ns': 14_300_000_000, 'reason': None,
            'snapshot': {'schema': prefixes.SCHEMA, 'status': 'complete',
                'monotonic_ns': 14_200_000_000, 'connection_id': 1, 'updates': 10,
                'accepted_count': len(values), 'prefixes': values, 'reason': None}}


def check(tmp_path, recipe, receipt, *, selection=True, files=None):
    files = copy.deepcopy(files or evidence(recipe))
    if receipt is not None:
        files['observer-prefixes.json'] = receipt
    if selection:
        files['observer-prefix-selection.json'] = {
            'recipe_sha256': recipes.recipe_sha256(recipe), 'enabled': True,
            'phase': 'post_measurement', 'max_prefixes': prefixes.MAX_PREFIXES}
    spec = default_assertions(recipe, include_prefixes=True)
    return evaluate_assertions(spec, recipe, package(tmp_path, recipe, files))


def test_same_count_wrong_prefix_fails_identity_only(tmp_path, recipe):
    receipt = captured(recipe)
    receipt['snapshot']['prefixes'][0] = '192.0.2.1/32'
    answers = by_capability(check(tmp_path, recipe, receipt))
    assert answers['observer_route_count']['status'] == 'passed'
    identity = answers['observer_prefix_identity']
    assert identity['status'] == 'failed'
    assert identity['observed']['missing_count'] == 1
    assert identity['observed']['unexpected_count'] == 1
    assert identity['observed']['missing_sample'] == ['100.0.0.0/32']
    assert identity['observed']['unexpected_sample'] == ['192.0.2.1/32']
    assert all(len(w['sha256']) == 64 for w in identity['evidence'])


def test_complete_set_order_independent_and_explicit_deadline(tmp_path, recipe):
    receipt = captured(recipe)
    receipt['snapshot']['prefixes'].reverse()
    result = check(tmp_path, recipe, receipt)
    assert result['outcome'] == 'passed'
    assert by_capability(result)['observer_prefix_identity']['deadline'] == {'kind': 'post_measurement_snapshot'}
    assert len(default_assertions(recipe)['assertions']) == 5


@pytest.mark.parametrize('mutation', ['missing', 'no_selection', 'duplicate', 'ipv6', 'noncanonical',
    'count', 'bool', 'session', 'status', 'oversize', 'clock', 'late', 'before_measurement',
    'budget', 'no_events', 'wrong_recipe'])
def test_bad_or_missing_identity_never_passes(tmp_path, recipe, mutation):
    receipt = captured(recipe)
    snap = receipt['snapshot']
    files = evidence(recipe)
    if mutation == 'missing':
        receipt = None
    elif mutation == 'duplicate':
        snap['prefixes'][-1] = snap['prefixes'][0]
    elif mutation == 'ipv6':
        snap['prefixes'][0] = '::/0'
    elif mutation == 'noncanonical':
        snap['prefixes'][0] = '100.0.0.1/24'
    elif mutation == 'count':
        snap['accepted_count'] += 1
    elif mutation == 'bool':
        snap['updates'] = True
    elif mutation == 'session':
        snap['connection_id'] = 0
    elif mutation == 'status':
        snap['status'] = 'unavailable'
    elif mutation == 'oversize':
        snap['prefixes'] = ['100.0.0.0/32'] * (prefixes.MAX_PREFIXES + 1)
        snap['accepted_count'] = len(snap['prefixes'])
    elif mutation == 'clock':
        snap['monotonic_ns'] = receipt['completed_ns'] + 1
    elif mutation == 'late':
        receipt['completed_ns'] = 18_000_000_000
    elif mutation == 'before_measurement':
        receipt['requested_ns'] = 13_000_000_000
    elif mutation == 'budget':
        files.pop('execution-budget.json')
    elif mutation == 'no_events':
        files.pop('raw-events.json')
    elif mutation == 'wrong_recipe':
        receipt['recipe_sha256'] = '0' * 64
    answer = by_capability(check(tmp_path, recipe, receipt, files=files,
                                 selection=mutation != 'no_selection'))['observer_prefix_identity']
    assert answer['status'] == 'unmeasured'
    assert answer['observed'] is None


@pytest.mark.parametrize('change', ['missing', 'extra', 'different_length'])
def test_complete_different_sets_fail(tmp_path, recipe, change):
    receipt = captured(recipe)
    values = receipt['snapshot']['prefixes']
    if change == 'missing':
        values.pop()
    elif change == 'extra':
        values.append('192.0.2.1/32')
    else:
        values[0] = '100.0.0.0/24'
    receipt['snapshot']['accepted_count'] = len(values)
    assert by_capability(check(tmp_path, recipe, receipt))['observer_prefix_identity']['status'] == 'failed'


def test_verified_evidence_mutation_is_rejected(tmp_path, recipe):
    from recipe_results import verify_result_package
    receipt = captured(recipe)
    check(tmp_path, recipe, receipt)
    (tmp_path / 'result/work/observer-prefixes.json').write_text('{}')
    with pytest.raises(recipes.ContractError):
        verify_result_package(tmp_path / 'result/result.json')


@pytest.mark.parametrize('reply', [b'{', b'[]', b'null', b''])
def test_transport_partial_or_invalid_reply_never_attests(tmp_path, monkeypatch, recipe, reply):
    class Client:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def settimeout(self, value): pass
        def connect(self, value): pass
        def recv(self, size):
            nonlocal reply
            value, reply = reply, b''
            return value
    monkeypatch.setattr(prefixes.socket, 'socket', lambda *a: Client())
    receipt = prefixes.capture(tmp_path/'socket', recipe)
    with pytest.raises((ValueError, TypeError)):
        prefixes.inspect(receipt, recipe)


def test_transport_deadline_and_output_bound(tmp_path, monkeypatch, recipe):
    class Client:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def settimeout(self, value): pass
        def connect(self, value): pass
        def recv(self, size): return b'x' * size
    monkeypatch.setattr(prefixes.socket, 'socket', lambda *a: Client())
    assert '4 MiB' in prefixes.capture(tmp_path/'socket', recipe)['reason']
    monkeypatch.setattr(Client, 'connect', lambda *a: (_ for _ in ()).throw(TimeoutError('fixture timeout')))
    assert prefixes.capture(tmp_path/'socket', recipe)['status'] == 'unavailable'


def test_transport_supports_long_host_work_paths(tmp_path, recipe):
    import os
    import socket
    import threading
    import time
    directory = tmp_path / ('deep-work-root-' * 12) / 'monitor'
    directory.mkdir(parents=True)
    descriptor = os.open(directory, os.O_DIRECTORY | os.O_RDONLY)
    path = directory / prefixes.SOCKET_NAME
    assert len(str(path)) > 108
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            listener.bind(f'/proc/self/fd/{descriptor}/{prefixes.SOCKET_NAME}')
            listener.listen(1)
            listener.settimeout(2)
            def serve():
                with listener.accept()[0] as client:
                    snapshot = captured(recipe)['snapshot']
                    snapshot['monotonic_ns'] = time.monotonic_ns()
                    client.sendall(json.dumps(snapshot).encode())
            thread = threading.Thread(target=serve)
            thread.start()
            try:
                receipt = prefixes.capture(path, recipe)
            finally:
                thread.join(timeout=3)
            assert not thread.is_alive()
            assert receipt['status'] == 'collected'
            assert prefixes.inspect(receipt, recipe)['missing_count'] == 0
    finally:
        os.close(descriptor)


def test_expected_prefixes_match_actual_mako_generator(recipe):
    import bgperf2
    from mako.template import Template
    total = prefixes.expected_count(recipe)
    rendered = Template(bgperf2.gen_mako_macro() + '${" ".join(gen_paths(' + str(total) + '))}').render()
    assert rendered.split() == captured(recipe)['snapshot']['prefixes']


def test_capture_selection_refuses_large_recipes_before_probes(tmp_path, monkeypatch, recipe):
    import recipe_run
    monkeypatch.setattr(prefixes, 'MAX_PREFIXES', 1)
    with pytest.raises(recipes.ContractError, match='100000'):
        recipe_run.run_recipe(recipe, workdir=tmp_path/'work', results_dir=tmp_path/'results',
            observer_prefixes=True, check=lambda *a, **k: pytest.fail('probed'))
    assert list(tmp_path.iterdir()) == []


def test_cli_exports_only_selected_identity(tmp_path, recipe, capsys):
    path = tmp_path/'recipe.json'
    path.write_text(json.dumps(recipe))
    assert recipes.main(['assertions-export', str(path), '--capability', 'observer_prefix_identity']) == 0
    spec = json.loads(capsys.readouterr().out)
    assert [a['capability'] for a in spec['assertions']] == ['observer_prefix_identity']


def test_observer_startup_option_is_explicit_and_default_compatible(tmp_path):
    import bgperf2
    from recipe_worker import scoped_adapter
    adapter = bgperf2.MONITOR_CLASSES['sink']
    instances = []
    for enabled in (False, True):
        selected = scoped_adapter(adapter, 'sha256:'+'1'*64, 'attempt',
                                  role='observer', capture_prefixes=enabled)
        instance = selected(str(tmp_path), {'as': 100, 'router-id': '192.0.2.1',
                                            'local-address': '192.0.2.1'})
        instance.config = {'target': {'as': 200, 'local-address': '192.0.2.2'}}
        instances.append(instance)
    old, new = [instance.get_startup_cmd() for instance in instances]
    assert '-snapshot-socket' not in old
    assert new.replace('-snapshot-socket /root/config/prefixes.sock ', '') == old


def test_cli_forwards_capture_selection(tmp_path, recipe, monkeypatch):
    import recipe_run
    path = tmp_path/'recipe.json'
    path.write_text(json.dumps(recipe))
    observed = []
    monkeypatch.setattr(recipe_run, 'run_recipe', lambda *a, **kw: observed.append(kw) or {'exit_code': 0})
    assert recipes.main(['run', str(path), '--workdir', str(tmp_path/'work'),
                         '--results-dir', str(tmp_path/'results'), '--observer-prefixes']) == 0
    assert observed[0]['observer_prefixes'] is True
