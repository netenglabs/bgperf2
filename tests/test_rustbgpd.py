'''The rustbgpd target's config writer and version guard.

The daemon takes a hand-written TOML config rather than anything bgperf2 can
generate from a template, so what it emits -- and what it refuses to emit -- is
worth pinning. Targets are built with object.__new__ so no container is made.
'''
import pytest

from base import VersionUnavailable
from rustbgpd import RustBGPd, RustBGPdTarget


@pytest.fixture(autouse=True)
def no_ambient_event_history_switch(monkeypatch):
    '''The switch is read from the environment, so a shell that already has it
    set must not decide what these tests assert.'''
    monkeypatch.delenv('RUSTBGPD_EVENT_HISTORY_OFF', raising=False)


SCENARIO = {
    'testers': [{'neighbors': {
        '10.10.0.3': {'as': 1003, 'local-address': '10.10.0.3', 'filter': {'in': []}},
        '10.10.0.4': {'as': 1004, 'local-address': '10.10.0.4', 'filter': {'in': []}},
    }}],
    'monitor': {'as': 1001, 'local-address': '10.10.0.2'},
    'policy': {},
}


def write(tmp_path, scenario=None, conf=None, monkeypatch=None, env=None):
    '''Write a config for `scenario` into tmp_path and return its text.'''
    target = object.__new__(RustBGPdTarget)
    target.host_dir = str(tmp_path)
    target.conf = conf if conf is not None else {'as': 1000, 'router-id': '10.10.255.254'}
    target.scenario_global_conf = SCENARIO if scenario is None else scenario
    for name, value in (env or {}).items():
        monkeypatch.setenv(name, value)
    target.write_config()
    return (tmp_path / RustBGPdTarget.CONFIG_FILE_NAME).read_text()


class TestWriteConfig:
    def test_every_tester_neighbor_and_the_monitor_is_configured(self, tmp_path):
        config = write(tmp_path)
        for addr in ('10.10.0.3', '10.10.0.4', '10.10.0.2'):
            assert 'address = "{0}"'.format(addr) in config
        assert config.count('[[neighbors]]') == 3

    def test_no_grpc_security_block(self, tmp_path):
        '''The daemon grants local-operator authorization implicitly on its
        owner-only default unix socket, which is all rbgp needs from inside the
        container. The `[security.grpc] enforcement = "legacy"` escape hatch an
        earlier version of this target wrote was removed in rustbgpd v0.63.0 --
        a config carrying it is rejected at startup, so the bench never comes
        up.
        '''
        assert 'security.grpc' not in write(tmp_path)

    def test_event_history_is_left_at_the_daemon_default(self, tmp_path):
        assert '[event_history]' not in write(tmp_path)

    def test_event_history_off_is_written_out_explicitly(self, tmp_path, monkeypatch):
        config = write(tmp_path, monkeypatch=monkeypatch,
                       env={'RUSTBGPD_EVENT_HISTORY_OFF': '1'})
        assert '[event_history]\nenabled = false' in config


class TestUnsupportedPolicy:
    '''This target writes no policy at all, so a filter run would otherwise
    produce an unfiltered measurement filed under a filter label.
    '''
    def test_filter_test_is_refused(self, tmp_path):
        conf = {'as': 1000, 'router-id': '10.10.255.254', 'filter_test': 'transit'}
        with pytest.raises(NotImplementedError, match='target.filter_test'):
            write(tmp_path, conf=conf)

    def test_generated_policy_definitions_are_refused(self, tmp_path):
        scenario = dict(SCENARIO, policy={'p1': {'match': []}})
        with pytest.raises(NotImplementedError, match='policy'):
            write(tmp_path, scenario=scenario)

    def test_per_neighbor_filter_assignment_is_refused(self, tmp_path):
        scenario = dict(SCENARIO, testers=[{'neighbors': {
            '10.10.0.3': {'as': 1003, 'local-address': '10.10.0.3', 'filter': {'in': ['p1']}},
        }}])
        with pytest.raises(NotImplementedError, match='10.10.0.3'):
            write(tmp_path, scenario=scenario)

    def test_an_empty_filter_assignment_is_not_a_policy(self, tmp_path):
        '''bgperf2 always writes a `filter` key; it is empty unless one of the
        --*-list-num options asked for a policy. Refusing on the key rather
        than its contents would reject every plain run.
        '''
        assert write(tmp_path)


class TestVersion:
    def test_the_daemon_banner_is_accepted(self, monkeypatch):
        monkeypatch.setattr('base.Container.exec_version_cmd',
                            lambda self, stderr=False: 'rustbgpd 0.66.0\n')
        probe = object.__new__(RustBGPd)
        assert probe.exec_version_cmd() == 'rustbgpd 0.66.0'

    @pytest.mark.parametrize('output', [
        '',
        'OCI runtime exec failed: exec: "rustbgpd": executable file not found in $PATH',
        'rbgp 0.66.0',
    ])
    def test_anything_else_is_not_a_version(self, monkeypatch, output):
        '''Recording the container's own error text as a version makes the row
        it lands in quietly unreproducible; version_string() turns this into an
        explicit UNKNOWN instead.
        '''
        monkeypatch.setattr('base.Container.exec_version_cmd',
                            lambda self, stderr=False: output)
        probe = object.__new__(RustBGPd)
        with pytest.raises(VersionUnavailable):
            probe.exec_version_cmd()
