"""rustbgpd adapter semantics and refusal before destructive lifecycle steps."""
import json
from argparse import Namespace

import pytest
import toml

import base
import bgperf2
import contention
import run_lifecycle
from rustbgpd import RustBGPD, RustBGPDTarget, RustBGPDNeighborReadError, neighbor_counts


def row(**fields):
    return dict(address='10.0.0.3', state='Established', prefixes_received=100, **fields)


def test_counts_are_accepted_only_and_inactive_sessions_do_not_attest(tmp_path):
    rows = [row(), dict(address='10.0.0.4', state='Idle', prefixes_received=100),
            dict(address='10.0.0.5', state='Established', prefixes_received=100, retention_only=True)]
    received, accepted = neighbor_counts(json.dumps(rows))
    assert received == {} and accepted == {'10.0.0.3': 100}
    target = RustBGPDTarget(str(tmp_path), {})
    target.get_test_counts = lambda: ({'10.0.0.3': 100}, {'10.0.0.3': False})
    assert target.classify_neighbor_counts(received, accepted) == (
        {'10.0.0.3': False}, {'10.0.0.3': True})
    assert target.get_table_witness() is None


@pytest.mark.parametrize('text', ['bad', '{}', '[null]', json.dumps([row(), row()])] + [
    json.dumps([dict(row(), **change)]) for change in (
        {'address': '::1'}, {'address': None}, {'prefixes_received': True},
        {'prefixes_received': -1}, {'prefixes_received': '100'}, {'state': None},
        {'stale': True}, {'stale': 'false'}, {'retention_only': 'false'})])
def test_bad_observations_are_errors_never_zero(text):
    with pytest.raises(RustBGPDNeighborReadError):
        neighbor_counts(text)


def test_config_includes_generators_monitor_and_receivers(tmp_path):
    target = RustBGPDTarget(str(tmp_path), {'as': 64512, 'router-id': '10.0.0.1'})
    def peer(number):
        return {'router-id': f'10.0.0.{number}', 'as': 64512 + number}
    target.scenario_global_conf = {'testers': [{'neighbors': {'one': peer(3)}}],
                                   'monitor': peer(2), 'receivers': [peer(4)]}
    target.write_config()
    config = toml.load(tmp_path / target.CONFIG_FILE_NAME)
    assert config['global']['ebgp_requires_policy'] is True
    assert config['global']['runtime_state_dir'] == '/var/lib/rustbgpd'
    assert config['global']['telemetry'] == {'prometheus_addr': '127.0.0.1:9179', 'log_format': 'json'}
    assert config['policy']['import_chain'] == ['permit-all-import']
    assert config['policy']['export_chain'] == ['permit-all-export']
    assert all(policy['default_action'] == 'permit' for policy in config['policy']['definitions'].values())
    assert {n['address'] for n in config['neighbors']} == {'10.0.0.2', '10.0.0.3', '10.0.0.4'}
    assert all(n['families'] == ['ipv4_unicast'] for n in config['neighbors'])
    assert 'rustbgpd.toml' in target.get_startup_cmd()
    assert '> /root/config/rustbgpd.log 2>&1' in target.get_startup_cmd()


def test_release_wrapper_preserves_binary_and_disables_background_probes():
    recipe = RustBGPD.render_dockerfile('0.81.0')
    assert recipe.startswith('FROM ' + RustBGPD.RELEASE_IMAGE + '\n')
    assert 'USER root' in recipe and 'iproute2' in recipe
    assert 'chown root:root /var/lib/rustbgpd && chmod 0755 /var/lib/rustbgpd' in recipe
    assert 'ENTRYPOINT []' in recipe and 'HEALTHCHECK NONE' in recipe
    assert 'cargo' not in recipe and 'COPY' not in recipe
    with pytest.raises(ValueError):
        RustBGPD.resolve_ref('latest\nRUN bad')
    assert {'rustbgpd', 'rbgp'} <= contention.BGPERF_PROCESSES


def test_selected_release_reference_roundtrips_through_build_and_render(monkeypatch):
    built = []
    def capture(cls, dockerfile, force, tag, **kwargs):
        built.append((dockerfile, tag))
    monkeypatch.setattr(RustBGPD, 'build_dockerfile', classmethod(capture))
    RustBGPD.build_version('0.82.0')
    assert built[-1][0].startswith('FROM ghcr.io/lance0/rustbgpd:0.82.0\n')
    assert built[-1][1] == 'bgperf/rustbgpd:0.82.0'
    assert RustBGPD.render_dockerfile('0.82.0') == built[-1][0]


@pytest.mark.parametrize('banner,valid', [('rustbgpd 0.81.0', True),
    ('rustbgpd v0.81.0-test+abc', True), ('exec failed 0.81.0', False), ('', False)])
def test_version_parser_on_actual_target_mro(tmp_path, monkeypatch, banner, valid):
    target = RustBGPDTarget(str(tmp_path), {})
    monkeypatch.setattr(base.Container, 'exec_version_cmd', lambda *a, **k: banner)
    if valid:
        assert target.version_string() == banner
    else:
        assert target.version_string().startswith('UNKNOWN')


@pytest.mark.parametrize('fields', [dict(filter_test='transit'), dict(threads=4),
    dict(file='/must-not-read'), dict(target_config_file='/must-not-read')])
@pytest.mark.parametrize('entrypoint', ['bench', 'config', 'batch'])
@pytest.mark.parametrize('adapter', ['rustbgpd', 'holo', 'zebra-rs'])
def test_unsupported_controls_refuse_before_runtime_or_files(fields, entrypoint, adapter, tmp_path):
    if entrypoint == 'batch':
        test = dict(name='unsupported', neighbors=[1], prefixes=[1], filter_test=[None],
                    targets=[dict(name=adapter, **{k: v for k, v in fields.items() if k != 'filter_test'})])
        if 'filter_test' in fields:
            test['filter_test'] = [fields['filter_test']]
        with pytest.raises(SystemExit, match=adapter + ' supports'):
            bgperf2.check_batch_test(test)
    elif entrypoint == 'config':
        with pytest.raises(SystemExit, match=adapter + ' supports'):
            bgperf2.config(Namespace(target=adapter, **fields))
    else:
        from test_run_lifecycle import fake_run
        runtime, args, calls, _ = fake_run(tmp_path)
        args.target = adapter
        vars(args).update(fields)
        with pytest.raises(SystemExit, match=adapter + ' supports'):
            run_lifecycle.bench(runtime, args)
        assert calls == ['install_stop_handlers']
