"""Holo native API mapping, transactional config and pinned source recipe."""
import copy
import json

import pytest
import toml

import base
import contention
from holo import Holo, HoloTarget, HoloNeighborReadError, neighbor_counts


def state_row(**fields):
    # Structure and semantics from Holo 947daeb's BGP conformance state and
    # northbound/state.rs: installed counts Adj-RIB-In post-policy paths.
    row = {'remote-address': '10.0.0.3', 'session-state': 'established',
           'afi-safis': {'afi-safi': [{'name': 'iana-bgp-types:ipv4-unicast',
                                      'prefixes': {'received': 4, 'installed': 3, 'sent': 2}}]}}
    row.update(fields)
    return row


def response(rows):
    tree = {'ietf-routing:routing': {'control-plane-protocols': {'control-plane-protocol': [
        {'name': 'bgperf', 'type': 'ietf-bgp:bgp', 'ietf-bgp:bgp': {'neighbors': {'neighbor': rows}}}]}}}
    return json.dumps({'data': {'dataString': json.dumps(tree)}})


def test_native_received_and_installed_have_distinct_meanings(tmp_path):
    received, accepted = neighbor_counts(response([state_row()]))
    assert received == {'10.0.0.3': 4} and accepted == {'10.0.0.3': 3}
    target = HoloTarget(str(tmp_path), {})
    assert target.get_table_witness() is None
    assert neighbor_counts(response([state_row(**{'session-state': 'idle'})])) == ({}, {})


@pytest.mark.parametrize('text', ['bad', '{}', '[]', response([state_row(), state_row()]),
    response([state_row(**{'remote-address': '::1'})]),
    response([state_row(**{'session-state': None})]),
    response([state_row(**{'afi-safis': {}})])])
def test_unavailable_or_invalid_state_is_never_zero(text):
    with pytest.raises(HoloNeighborReadError):
        neighbor_counts(text)


@pytest.mark.parametrize('value', [None, -1, True, '3'])
@pytest.mark.parametrize('field', ['received', 'installed'])
def test_counter_types_are_strict(field, value):
    row = state_row()
    row['afi-safis']['afi-safi'][0]['prefixes'][field] = value
    with pytest.raises(HoloNeighborReadError):
        neighbor_counts(response([row]))


def test_duplicate_family_does_not_double_count():
    row = state_row()
    row['afi-safis']['afi-safi'].append(copy.deepcopy(row['afi-safis']['afi-safi'][0]))
    with pytest.raises(HoloNeighborReadError):
        neighbor_counts(response([row]))


def test_bootstrap_and_transaction_describe_all_sessions(tmp_path):
    target = HoloTarget(str(tmp_path), {'as': 64512, 'router-id': '10.0.0.1'})
    peer = lambda number: {'router-id': f'10.0.0.{number}', 'as': 64512 + number}
    target.scenario_global_conf = {'testers': [{'neighbors': {'a': peer(3)}}],
                                   'monitor': peer(2), 'receivers': [peer(4)]}
    target.write_config()
    boot = toml.load(tmp_path / target.CONFIG_FILE_NAME)
    assert boot['user'] == boot['group'] == 'root'
    assert boot['plugins']['grpc']['address'] == '127.0.0.1:50051'
    assert boot['plugins']['gnmi']['enabled'] is False
    assert boot['logging']['stdout']['enabled'] is True
    request = json.loads((tmp_path / 'holo-commit.json').read_text())
    assert request['operation'] == 'REPLACE'
    tree = json.loads(request['config']['data_string'])
    protocol = tree['ietf-routing:routing']['control-plane-protocols']['control-plane-protocol'][0]
    bgp = protocol['ietf-bgp:bgp']
    assert bgp['global']['as'] == 64512
    assert {row['remote-address'] for row in bgp['neighbors']['neighbor']} == {'10.0.0.2', '10.0.0.3', '10.0.0.4'}
    for row in bgp['neighbors']['neighbor']:
        family = row['afi-safis']['afi-safi'][0]
        assert family['name'] == 'iana-bgp-types:ipv4-unicast'
        assert set(family['apply-policy'].values()) == {'accept-route'}
    script = target.get_startup_cmd()
    assert script.index('holod -c') < script.index('Northbound/Capabilities') < script.index('Northbound/Commit')
    assert '-max-time 1' in script and '"$attempts" -ge 40' in script
    assert '-max-time 10 -d @' in script
    assert 'ulimit -n 65536 || true' in script
    assert 'set -eu' in script and 'kill -0 "$daemon_pid"' in script
    assert 'holo-commit.log 2>&1' in script and 'wait "$daemon_pid"' in script


def test_live_attachment_interface_is_written_before_daemon_launch(tmp_path, monkeypatch):
    target = HoloTarget(str(tmp_path), {'as': 64512, 'router-id': '10.0.0.1'})
    scenario = {'testers': [], 'monitor': {'router-id': '10.0.0.2', 'as': 64513}}
    calls = []
    def attach(self, network):
        calls.append('attach')
        assert network == 'selected-br'
        self.dev = 'eth1'  # Docker's default bridge got eth0.
        return 'container'
    def launch(self, stream=False, detach=False):
        calls.append('launch')
        assert detach is True
        request = json.loads((tmp_path / 'holo-commit.json').read_text())
        tree = json.loads(request['config']['data_string'])
        assert tree['ietf-interfaces:interfaces']['interface'][0]['name'] == 'eth1'
    monkeypatch.setattr(base.Container, 'run', attach)
    monkeypatch.setattr(base.Container, 'exec_startup_cmd', launch)
    assert target.run(scenario, 'selected-br') == 'container'
    assert calls == ['attach', 'launch']


def test_source_recipe_is_locked_and_preserves_attribution():
    recipe = Holo.render_dockerfile('0.9.0')
    for image in (Holo.BUILDER_IMAGE, Holo.RUNTIME_IMAGE, Holo.CLIENT_IMAGE):
        assert '@sha256:' in image and image in recipe
    assert 'git checkout ' + Holo.DEFAULT_REF in recipe
    assert 'cargo build --locked --release -p holo-daemon' in recipe
    assert '/src/Cargo.lock /src/LICENSE /src/proto/holo.proto' in recipe
    assert '/usr/local/share/holo/source-id' in recipe
    assert {'holod', 'grpcurl'} <= contention.BGPERF_PROCESSES
    assert Holo.resolve_ref('v0.9.0') == Holo.DEFAULT_REF
    assert Holo.resolve_ref('0.10.0') == Holo.resolve_ref('v0.10.0') == 'v0.10.0'
    with pytest.raises(ValueError):
        Holo.resolve_ref('main\nRUN bad')


@pytest.mark.parametrize('banner,valid', [('Holo routing daemon 0.9.0 (' + '9' * 40 + ')', True),
    ('holod 0.9.0', True), ('exec failed: 0.9.0', False), ('', False)])
def test_version_parser_uses_daemon_banner(tmp_path, monkeypatch, banner, valid):
    target = HoloTarget(str(tmp_path), {})
    monkeypatch.setattr(base.Container, 'exec_version_cmd', lambda *args, **kwargs: banner)
    observed = target.version_string()
    assert observed == banner if valid else observed.startswith('UNKNOWN')
