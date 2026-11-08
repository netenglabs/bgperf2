"""Maghemite native API requests, startup response checks and frozen build."""
import json
import os
import subprocess

import pytest

import base
import bgperf2
import contention
from maghemite import Maghemite, MaghemiteTarget


def target_with_peers(tmp_path):
    target = MaghemiteTarget(str(tmp_path), {'as': 64512, 'router-id': '192.0.2.1',
                                           'local-address': '10.0.0.1/24'})
    def peer(n):
        return {'as': 64512 + n, 'router-id': f'192.0.2.{n}', 'local-address': f'10.0.0.{n}/24'}
    target.scenario_global_conf = {'testers': [{'neighbors': {'a': peer(3)}}],
                                   'monitor': peer(2), 'receivers': [peer(4)]}
    return target


def test_native_router_and_bulk_peers_keep_identity_and_transport_distinct(tmp_path):
    target = target_with_peers(tmp_path)
    target.write_config()
    router = json.loads((tmp_path / target.CONFIG_FILE_NAME).read_text())
    assert router == {'asn': 64512, 'id': 3221225985, 'listen': '0.0.0.0:179', 'graceful_shutdown': False}
    request = json.loads((tmp_path / target.PEERS_FILE_NAME).read_text())
    assert request['asn'] == 64512 and request['originate'] == []
    assert request['checker'] is request['shaper'] is None
    assert request['unnumbered_peers'] == {}
    peers = request['peers']['bgperf']
    assert {p['host'] for p in peers} == {'10.0.0.2:179', '10.0.0.3:179', '10.0.0.4:179'}
    assert {p['remote_asn'] for p in peers} == {64514, 64515, 64516}
    for peer in peers:
        assert peer['src_addr'] == '10.0.0.1' and peer['src_port'] is None
        assert peer['ipv4_unicast'] == {'nexthop': None, 'import_policy': 'NoFiltering', 'export_policy': 'NoFiltering'}
        assert peer['ipv6_unicast'] is None
        assert peer['hold_time'] == 6 and peer['keepalive'] == 2
        assert peer['connect_retry'] == 5 and peer['resolution'] == 100
        assert peer['enforce_first_as'] is True
    # Reusing the work directory with fewer peers cannot load stale JSON files.
    target.scenario_global_conf['testers'] = []
    target.scenario_global_conf['receivers'] = []
    target.write_config()
    request = json.loads((tmp_path / target.PEERS_FILE_NAME).read_text())
    assert len(request['peers']['bgperf']) == 1
    assert '*' not in target.get_startup_cmd()


def test_startup_uses_versioned_bounded_native_api_without_hardware_bypass(tmp_path):
    script = target_with_peers(tmp_path).get_startup_cmd()
    assert 'api-version: 13.0.0' in script
    assert '--admin-addr 127.0.0.1' in script and '--bgp-dispatcher-addr 0.0.0.0:179' in script
    assert '--no-bgp-dispatcher' not in script and '--mgs-addr' not in script
    assert '--max-time 1' in script and '"$attempts" -ge 40' in script
    assert script.count('--max-time 10') == 2
    assert 'kill -0 "$daemon_pid"' in script and 'wait "$daemon_pid"' in script
    assert script.index('/bgp/config/router)') < script.index('/bgp/omicron/apply)')
    assert script.count('[ "$status" = 204 ] || exit 1') == 2


@pytest.mark.parametrize('http_status,client_exit,expected', [('204', 0, 0), ('201', 0, 1), ('500', 0, 1), ('204', 7, 7)])
def test_startup_checks_actual_configuration_response_and_client_exit(tmp_path, http_status, client_exit, expected):
    daemon = tmp_path / 'fake-mgd'
    daemon.write_text('#!/bin/sh\nexec /bin/sleep 0.2\n')
    daemon.chmod(0o755)
    client = tmp_path / 'fake-client'
    calls = tmp_path / 'calls'
    client.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$MAG_TEST_CALLS"\n'
                      'case "$*" in *--write-out*) printf "%s" "$MAG_TEST_STATUS"; exit "$MAG_TEST_EXIT";; '
                      '*) printf "[]";; esac\n')
    client.chmod(0o755)
    target = target_with_peers(tmp_path)
    target.DAEMON_BINARY, target.HTTP_BINARY, target.guest_dir = str(daemon), str(client), str(tmp_path)
    script = tmp_path / 'start.sh'
    script.write_text(target.get_startup_cmd())
    env = dict(os.environ, MAG_TEST_CALLS=str(calls), MAG_TEST_STATUS=http_status, MAG_TEST_EXIT=str(client_exit))
    result = subprocess.run(['/bin/sh', str(script)], env=env, capture_output=True, timeout=5)
    assert result.returncode == expected
    requests = calls.read_text().splitlines()
    assert len(requests) == (3 if expected == 0 else 2)
    assert all('api-version: 13.0.0' in line for line in requests)


def test_declared_but_unupdated_prefix_atomics_are_not_route_gauges(tmp_path, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail('unavailable prefix gauges must not trigger a runtime read')
    monkeypatch.setattr(base.dckr, 'exec_create', unexpected)
    target = target_with_peers(tmp_path)
    assert target.get_neighbors_state() == ({}, {})
    assert target.get_table_witness() is None


def test_normal_source_build_is_locked_and_keeps_default_features():
    recipe = Maghemite.render_dockerfile(Maghemite.DEFAULT_REF)
    assert Maghemite.BUILDER_IMAGE in recipe and Maghemite.RUNTIME_IMAGE in recipe
    assert 'git checkout ' + Maghemite.DEFAULT_REF in recipe
    assert 'cargo build --locked --release -p mgd' in recipe
    assert 'ENV RUSTUP_TOOLCHAIN=1.97.1' in recipe
    assert '--no-default-features' not in recipe
    assert '/src/Cargo.lock /src/rust-toolchain.toml /src/LICENSE' in recipe
    assert 'cargo tree --locked -p mgd' in recipe
    assert Maghemite.resolve_ref(None) == Maghemite.DEFAULT_REF
    assert {'mgd', 'bgperf-mg-http'} <= contention.BGPERF_PROCESSES
    assert len(Maghemite.HTTP_BINARY.rsplit('/', 1)[-1]) <= 15
    for value in ('0.1.0', 'latest', '277f4368d7b6', 'main\nRUN bad'):
        with pytest.raises(ValueError):
            Maghemite.resolve_ref(value)


def test_source_commit_is_selectable_without_claiming_a_native_release_banner():
    ref = Maghemite.DEFAULT_REF
    assert Maghemite.image_tag(ref) == 'bgperf/maghemite:' + ref
    assert Maghemite.resolve_ref(ref) == ref
    assert not bgperf2.expect_version_in_banner(Maghemite, ref)
    assert not bgperf2.version_matches('mgd 0.1.0', ref, ref)


@pytest.mark.parametrize('banner,valid', [('mgd 0.1.0', True), ('mgd 0.1.0-dev', True),
    ('exec failed: mgd 0.1.0', False), ('', False), (Maghemite.DEFAULT_REF, False)])
def test_package_version_is_observed_without_inventing_source_identity(tmp_path, monkeypatch, banner, valid):
    target = target_with_peers(tmp_path)
    monkeypatch.setattr(base.Container, 'exec_version_cmd', lambda *a, **k: banner)
    value = target.version_string()
    assert value == banner if valid else value.startswith('UNKNOWN')
