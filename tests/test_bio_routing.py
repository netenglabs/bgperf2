"""Bio-Routing native stored-path metrics, IPv4 policy and source identity."""
import json

import pytest
import yaml

import base
import contention
from bio_routing import BioRouting, BioRoutingTarget, BioNeighborReadError, neighbor_counts


def metric(name, value, **labels):
    fields = dict(peer_ip='10.0.0.3', local_asn='64512', peer_asn='64513', vrf='main')
    if name == 'bio_bgp_route_received_count':
        fields.update(afi='1', safi='1')
    fields.update(labels)
    return name + '{' + ','.join(k + '=' + json.dumps(v) for k, v in fields.items()) + '} ' + str(value)


def metrics(count=100, state=6, **labels):
    return '\n'.join([metric('bio_bgp_state', state, **labels),
                      metric('bio_bgp_route_received_count', count, **labels)])


def test_native_count_is_received_snapshot_not_update_or_accepted_count(tmp_path):
    text = '# TYPE bio_bgp_route_received_count counter\n' + metrics(100)
    text += '\n' + metric('bio_bgp_update_received_count', 99999)
    text += '\n' + metric('bio_bgp_route_accepted_count', 77, afi='1', safi='1')
    assert neighbor_counts(text) == ({'10.0.0.3': 100}, {})
    assert neighbor_counts(metrics(2)) == ({'10.0.0.3': 2}, {})  # May decrease: a stored-path snapshot.
    assert neighbor_counts(metrics(0)) == ({'10.0.0.3': 0}, {})
    assert BioRoutingTarget(str(tmp_path), {}).get_table_witness() is None


@pytest.mark.parametrize('state', range(6))
def test_inactive_session_does_not_attest_current_delivery(state):
    assert neighbor_counts(metrics(100, state)) == ({}, {})


def test_label_order_and_exponent_number_do_not_change_meaning():
    text = ('bio_bgp_state{vrf="main",peer_asn="64513",local_asn="64512",peer_ip="10.0.0.3"} 6\n'
            'bio_bgp_route_received_count{safi="1",afi="1",vrf="main",peer_ip="10.0.0.3",'
            'peer_asn="64513",local_asn="64512"} 1e2')
    assert neighbor_counts(text) == ({'10.0.0.3': 100}, {})


@pytest.mark.parametrize('value', ['NaN', '+Inf', '-Inf', '-1', '0.5', '9007199254740993', 'bad'])
def test_invalid_or_imprecise_native_count_is_not_zero(value):
    with pytest.raises(BioNeighborReadError):
        neighbor_counts(metrics(value))


@pytest.mark.parametrize('text', [
    metric('bio_bgp_state', 6),  # Established but no IPv4 path snapshot.
    metric('bio_bgp_route_received_count', 100),
    metrics() + '\n' + metric('bio_bgp_state', 6),
    metrics() + '\n' + metric('bio_bgp_route_received_count', 100),
    metrics() + '\n' + metrics(peer_asn='64514'),
    metrics(state=7),
    metrics(local_asn='0'),
    metrics(peer_asn='4294967296'),
    metrics(peer_ip='invalid'),
    metrics().replace('vrf="main"', 'vrf="main",vrf="main"'),
    metrics().replace('vrf="main"', 'vrf="main",'),
    metrics().replace('vrf="main"', 'vrf="main",unknown="label"'),
    'bio_bgp_state 6',
    'bio_bgp_state{bad} 6',
    metrics().replace('} 100', '} 100 trailing'),
])
def test_missing_duplicate_or_malformed_observations_refuse(text):
    with pytest.raises(BioNeighborReadError):
        neighbor_counts(text)


def test_other_vrf_family_and_ipv6_do_not_enter_ipv4_checkpoint():
    assert neighbor_counts(metrics(vrf='other')) == ({}, {})
    assert neighbor_counts(metrics(peer_ip='2001:db8::3')) == ({}, {})
    assert neighbor_counts(metrics() + '\n' + metric('bio_bgp_route_received_count', 999, afi='2')) == (
        {'10.0.0.3': 100}, {})


def test_yaml_policy_covers_all_sessions_and_uses_local_address(tmp_path):
    target = BioRoutingTarget(str(tmp_path), {'as': 64512, 'router-id': '192.0.2.1',
                                            'local-address': '10.0.0.1/24'})
    peer = lambda n: {'router-id': f'192.0.2.{n}', 'local-address': f'10.0.0.{n}/24', 'as': 64512 + n}
    target.scenario_global_conf = {'testers': [{'neighbors': {'a': peer(3)}}],
                                   'monitor': peer(2), 'receivers': [peer(4)]}
    target.write_config()
    config = yaml.safe_load((tmp_path / target.CONFIG_FILE_NAME).read_text())
    assert config['routing_options'] == {'autonomous_system': 64512, 'router_id': '192.0.2.1'}
    policy = config['policy_options']['policy_statements'][0]
    assert policy['terms'] == [{'name': 'all', 'then': {'accept': True}}]
    group, = config['protocols']['bgp']['groups']
    assert group['local_address'] == '10.0.0.1'
    assert group['import'] == group['export'] == [policy['name']]
    assert group['ipv4'] == {} and 'ipv6' not in group
    assert group['passive'] is False and 'route_server_client' not in group
    assert {p['peer_address'] for p in group['neighbors']} == {'10.0.0.2', '10.0.0.3', '10.0.0.4'}
    assert '-config.file /root/config/bio-rd.yaml' in target.get_startup_cmd()


def test_source_build_is_pinned_and_version_gap_stays_explicit(tmp_path):
    recipe = BioRouting.render_dockerfile('0.1.10')
    assert BioRouting.BUILDER_IMAGE in recipe and BioRouting.RUNTIME_IMAGE in recipe
    assert 'git checkout ' + BioRouting.DEFAULT_REF in recipe
    assert 'GOTOOLCHAIN=local CGO_ENABLED=0' in recipe
    assert 'go build -mod=readonly -trimpath' in recipe
    assert 'go version -m /tmp/bio-rd' in recipe
    assert 'dpkg --compare-versions "$curl_version" ge 8.4.0' in recipe
    assert '/usr/local/share/bio-routing/http-client.txt' in recipe
    assert '/src/go.mod /src/go.sum /src/LICENSE' in recipe
    assert {'bio-rd', 'bgperf-bio-http'} <= contention.BGPERF_PROCESSES
    assert len(BioRouting.HTTP_BINARY.rsplit('/', 1)[-1]) <= 15
    assert BioRouting.resolve_ref('v0.1.10') == BioRouting.DEFAULT_REF
    with pytest.raises(ValueError):
        BioRouting.resolve_ref('main\nRUN bad')
    assert BioRoutingTarget(str(tmp_path), {}).version_string().startswith('UNKNOWN (no version command')


@pytest.mark.parametrize('exit_code', [0, 1, 28, None])
def test_metrics_http_is_bounded_and_failed_exit_is_not_parsed(tmp_path, monkeypatch, exit_code):
    calls = []
    def create(**kwargs):
        calls.append(kwargs)
        return {'Id': 'owned-exec'}
    monkeypatch.setattr(base.dckr, 'exec_create', create)
    monkeypatch.setattr(base.dckr, 'exec_start', lambda *a, **k: metrics().encode())
    monkeypatch.setattr(base.dckr, 'exec_inspect', lambda *a, **k: {'ExitCode': exit_code})
    target = BioRoutingTarget(str(tmp_path), {})
    if exit_code == 0:
        assert target.get_neighbors_state() == ({'10.0.0.3': 100}, {})
    else:
        with pytest.raises(BioNeighborReadError):
            target.get_neighbors_state()
    argv = calls[0]['cmd']
    assert argv[0] == BioRouting.HTTP_BINARY
    assert argv[argv.index('--max-time') + 1] == '5'
    assert argv[argv.index('--max-filesize') + 1] == '8388608'
    assert argv[-1] == 'http://127.0.0.1:55667/metrics'
