"""Bio-Routing native policy, source identity and explicitly unavailable gauges."""
import pytest
import yaml

import base
import contention
from bio_routing import BioRouting, BioRoutingTarget


def test_unregistered_library_metrics_are_not_native_route_witnesses(tmp_path, monkeypatch):
    # The selected cmd/bio-rd does not register the BGP metric collector;
    # ListSessions also returns unimplemented. Avoid polling unrelated HTTP
    # metrics or treating absent observations as per-neighbor zero gauges.
    def unexpected(*args, **kwargs):
        pytest.fail('unsupported counters must not start a runtime probe')
    monkeypatch.setattr(base.dckr, 'exec_create', unexpected)
    target = BioRoutingTarget(str(tmp_path), {})
    assert target.get_neighbors_state() == ({}, {})
    assert target.get_table_witness() is None


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
    assert all(p['advertise_ipv4_multiprotocol'] is True for p in group['neighbors'])
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
