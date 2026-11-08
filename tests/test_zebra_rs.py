"""zebra-rs native summary semantics and checksummed package preparation."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

import base
import contention
import zebra_rs
from zebra_rs import ZebraRS, ZebraRSTarget, ZebraNeighborReadError, neighbor_counts


def row(**fields):
    result = dict(neighbor='10.0.0.3', state='100', pfx_rcvd=100, pfx_sent=0)
    result.update(fields)
    return result


def response(peers):
    return json.dumps({'afi_safis': [{'afi_safi': 'IPv4 Unicast', 'peers': peers}]})


def test_decimal_state_is_established_and_count_is_received_only(tmp_path):
    received, accepted = neighbor_counts(response([row(), row(neighbor='10.0.0.4', state='Active')]))
    assert received == {'10.0.0.3': 100} and accepted == {}
    target = ZebraRSTarget(str(tmp_path), {})
    target.get_test_counts = lambda: ({'10.0.0.3': 100}, {'10.0.0.3': False})
    assert target.classify_neighbor_counts(received, accepted) == (
        {'10.0.0.3': True}, {'10.0.0.3': False})
    assert target.get_table_witness() is None


@pytest.mark.parametrize('text', ['bad', '{}', '[]', response([row(), row()])] + [
    response([row(**fields)]) for fields in (
        dict(neighbor=True), dict(neighbor='::1'), dict(state=None), dict(state='101'),
        dict(state='Established'), dict(pfx_rcvd=-1), dict(pfx_rcvd=True),
        dict(pfx_rcvd='100'), dict(interface='eth0'))])
def test_malformed_or_ambiguous_summary_is_not_zero(text):
    with pytest.raises(ZebraNeighborReadError):
        neighbor_counts(text)


def test_config_explicitly_permits_ipv4_for_every_session(tmp_path):
    target = ZebraRSTarget(str(tmp_path), {'as': 64512, 'router-id': '10.0.0.1'})
    def peer(number):
        return {'router-id': f'10.0.0.{number}', 'as': 64512 + number}
    target.scenario_global_conf = {'testers': [{'neighbors': {'a': peer(3)}}],
                                   'monitor': peer(2), 'receivers': [peer(4)]}
    target.write_config()
    config = yaml.safe_load((tmp_path / target.CONFIG_FILE_NAME).read_text())
    assert config['policy'][0]['entry'] == [{'number': 10, 'action': 'permit'}]
    bgp = config['router']['bgp']
    assert bgp['timer'] == {'adv-interval': {'ebgp': 1}}
    assert bgp['global'] == {'as': 64512, 'router-id': '10.0.0.1'}
    assert {peer['remote-address'] for peer in bgp['neighbor']} == {'10.0.0.2', '10.0.0.3', '10.0.0.4'}
    for peer in bgp['neighbor']:
        assert peer['enabled'] is True
        assert peer['afi-safi'] == [{'name': 'ipv4', 'enabled': True,
                                    'policy': {'in': 'BGPERF-PERMIT', 'out': 'BGPERF-PERMIT'}}]
    assert '--config-file /root/config/zebra-rs.yaml' in target.get_startup_cmd()
    assert '--vty-socket ' + target.VTY in target.get_startup_cmd()


def test_release_recipe_checks_hash_before_extraction_and_never_installs_services():
    recipe = ZebraRS.render_dockerfile('26.11.1')
    assert recipe.startswith('FROM ' + ZebraRS.RUNTIME_IMAGE)
    assert all(value in recipe for value in ZebraRS.PACKAGE_HASHES.values())
    assert recipe.index('sha256sum -c -') < recipe.index('dpkg-deb -x')
    assert 'dpkg -i' not in recipe and 'systemctl' not in recipe
    assert '/usr/local/share/bgperf-zebra-rs/package.deb' in recipe
    assert '/usr/bin/zebra-rs --version && /usr/bin/vtyctl --version' in recipe
    assert ZebraRS.resolve_ref('v26.11.1') == '26.11.1'
    with pytest.raises(ValueError, match='verified package hashes'):
        ZebraRS.render_dockerfile('26.11.2')
    assert {'zebra-rs', 'vtyctl'} <= contention.BGPERF_PROCESSES
    assert Path(ZebraRS.WAIT_BINARY).name in contention.BGPERF_PROCESSES
    assert 'ln -s /usr/bin/timeout ' + ZebraRS.WAIT_BINARY in recipe


@pytest.mark.parametrize('banner,valid', [('zebra-rs 26.11.1', True),
    ('exec error 26.11.1', False), ('zebra-rs 26.11.1: broken', False), ('', False)])
def test_banner_on_actual_target_mro(tmp_path, monkeypatch, banner, valid):
    target = ZebraRSTarget(str(tmp_path), {})
    monkeypatch.setattr(base.Container, 'exec_version_cmd', lambda *args, **kwargs: banner)
    value = target.version_string()
    assert value == banner if valid else value.startswith('UNKNOWN')


@pytest.mark.parametrize('exit_code', [0, 124, None])
def test_bounded_cli_checks_exit_even_if_output_is_valid(tmp_path, monkeypatch, exit_code):
    target = ZebraRSTarget(str(tmp_path), {})
    calls = []
    def create(**kwargs):
        calls.append(kwargs)
        return {'Id': 'exec'}
    client = SimpleNamespace(exec_create=create, exec_start=lambda *args, **kwargs: response([row()]).encode(),
                             exec_inspect=lambda identifier: {'ExitCode': exit_code})
    monkeypatch.setattr(zebra_rs, 'dckr', client)
    if exit_code == 0:
        assert target.get_neighbors_state() == ({'10.0.0.3': 100}, {})
    else:
        with pytest.raises(ZebraNeighborReadError, match='failed or exceeded'):
            target.get_neighbors_state()
    assert calls[0]['container'] == target.name
    assert calls[0]['cmd'][:3] == [ZebraRS.WAIT_BINARY, '--kill-after=1', '5']
