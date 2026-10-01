'''The sink as the run's monitor (measurement plan Phase 7a, third change set).

`SinkMonitor` puts the sample `SinkLogReader` makes onto the run's stats queue
through the same loop the GoBGP monitor uses, and waits for the session from
the log's S lines. These cover what it adds over the reader: the role's MRO,
the startup script it writes, the loop's handling of a sample and of a refused
one, and an establishment wait that ends rather than hangs.
'''

import contextlib
import io
import os
import queue
import time

import pytest

from conftest import REPO_ROOT  # noqa: F401

import base
import bgperf2
import monitor as monitor_module
from monitor import SessionUnavailable, SinkMonitor
from sink import SINK_LOG_FORMAT, Sink

HEADER = ('V {0} {1} 0.1.0 (src c47b36384df1) gobgp/v4 v4.9.0 go1.25.14\n'
          'B {0} 1759300000000000000\n')

CONF = {
    'monitor': {'as': 1001, 'router-id': '10.10.0.2',
                'local-address': '10.10.0.2', 'check-points': [100]},
    'target': {'as': 1000, 'local-address': '10.10.0.1'},
}


def make(tmp_path):
    mon = SinkMonitor(str(tmp_path / 'monitor'), CONF['monitor'])
    mon.config = CONF
    mon.monitor_for = 'bird'
    return mon


def write_log(mon, text):
    with open(os.path.join(mon.host_dir, mon.LOG_NAME), 'a') as f:
        f.write(text)


def now_ns():
    return time.monotonic_ns()


def test_the_role_is_the_monitor_and_the_daemon_is_the_sink(tmp_path):
    mon = make(tmp_path)
    assert mon.name == 'bgperf_monitor'
    assert mon.image == 'bgperf/sink'
    # The rustybgp trap: through Monitor the version would be parsed by
    # GoBGP's parser. It must be the sink's own.
    assert SinkMonitor.exec_version_cmd is Sink.exec_version_cmd
    assert SinkMonitor.get_version_cmd is Sink.get_version_cmd
    assert monitor_module.GoBGP not in SinkMonitor.__mro__
    # verify probes it as the class that runs it
    assert bgperf2.MONITOR_CLASSES['sink'] is SinkMonitor
    assert bgperf2.MONITOR_CLASSES['gobgp'] is bgperf2.Monitor


def test_its_version_is_read_through_the_sinks_parser(monkeypatch, tmp_path):
    mon = make(tmp_path)
    monkeypatch.setattr(base.Container, 'exec_version_cmd',
                        lambda self, stderr=False:
                        'bgperf-sink 0.1.0 (src c47b36384df1) gobgp/v4 v4.9.0 go1.25.14\n')
    assert mon.version_string() == \
        '0.1.0 (src c47b36384df1; gobgp/v4 v4.9.0; go1.25.14)'


def test_the_startup_script_is_the_monitor_configuration(tmp_path):
    script = make(tmp_path).get_startup_cmd()
    for flag in ('-local-as 1001', '-peer-as 1000', '-router-id 10.10.0.2',
                 '-local-address 10.10.0.2', '-peer-address 10.10.0.1',
                 # the GoBGP monitor's connect-retry
                 '-connect-retry 10s',
                 '-log /root/config/sink.log'):
        assert flag in script
    # exec, so the sink is the process the container's start.sh became and
    # nothing sits between it and its signals.
    assert '\nexec /usr/local/bin/bgperf-sink ' in script


def test_run_removes_a_previous_log_before_the_sink_starts(monkeypatch, tmp_path):
    '''Under -r/--repeat the directory survives, and the log is appended to:
    an old run's lines would read as an earlier process of this one.'''
    mon = make(tmp_path)
    write_log(mon, HEADER.format(1, SINK_LOG_FORMAT) + 'C 2 5000 9 0\n')
    started = []
    monkeypatch.setattr(base.Container, 'run', lambda self, net='': 'ctn')

    def exec_startup_cmd(self, stream=False, detach=False):
        started.append(os.path.exists(os.path.join(self.host_dir, self.LOG_NAME)))
    monkeypatch.setattr(SinkMonitor, 'exec_startup_cmd', exec_startup_cmd)
    assert mon.run(CONF, 'net') == 'ctn'
    assert started == [False]
    assert mon.reader.log.lines == 0


def poll_one(mon, interval=0.02, timeout=5.0):
    q = queue.Queue()
    mon.stats(q, interval=interval)
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            try:
                return q.get(timeout=0.1)
            except queue.Empty:
                continue
        return None
    finally:
        mon.stop_monitoring = True


def test_a_sample_reaches_the_queue_shaped_as_the_gobgp_poll(tmp_path):
    mon = make(tmp_path)
    t = now_ns()
    write_log(mon, HEADER.format(t, SINK_LOG_FORMAT)
              + 'S {0} established outbound 1 10.10.0.1:179\n'.format(t)
              + 'C {0} 150 3 0\n'.format(t))
    got = poll_one(mon)
    assert got is not None
    assert got['who'] == 'bgperf_monitor'
    assert got['afi_safis'][0]['state']['accepted'] == 150
    assert got['state']['session_state'] == 'established'
    # past the check-point of 100
    assert got['checked'] is True
    assert 'monotonic_s' in got and 'time' in got
    assert got['sink']['count_ns'] == t
    assert mon.monitor_sample_failures == 0


def test_below_the_check_point_is_not_checked(tmp_path):
    mon = make(tmp_path)
    t = now_ns()
    write_log(mon, HEADER.format(t, SINK_LOG_FORMAT) + 'C {0} 99 1 0\n'.format(t))
    got = poll_one(mon)
    assert got['checked'] is False


def test_a_stopped_sink_is_a_failed_read_not_a_count(tmp_path, capsys):
    mon = make(tmp_path)
    # Ten seconds old by the host's clock: past three heartbeats.
    t = now_ns() - 10 * 10**9
    write_log(mon, HEADER.format(t, SINK_LOG_FORMAT) + 'C {0} 150 3 0\n'.format(t))
    got = poll_one(mon, timeout=0.5)
    assert got is None
    assert mon.monitor_sample_failures >= 1
    assert 'the sink has stopped' in mon.monitor_sample_last_error
    assert 'monitor read for bird failed' in capsys.readouterr().err


def test_a_missing_log_is_a_failed_read(tmp_path):
    mon = make(tmp_path)
    assert poll_one(mon, timeout=0.3) is None
    assert 'FileNotFoundError' in mon.monitor_sample_last_error


def wait(mon):
    with contextlib.redirect_stdout(io.StringIO()):
        return mon.wait_established('10.10.0.1')


@pytest.fixture
def no_sleep(monkeypatch):
    slept = []
    monkeypatch.setattr(monitor_module.time, 'sleep', lambda s: slept.append(s))
    return slept


def test_wait_returns_once_the_log_says_established(tmp_path, no_sleep):
    mon = make(tmp_path)
    t = now_ns()
    write_log(mon, HEADER.format(t, SINK_LOG_FORMAT)
              + 'S {0} established inbound 1 10.10.0.1:40000\n'.format(t))
    assert wait(mon) == 0


def test_wait_waits_for_a_sink_that_has_not_written_yet(tmp_path, monkeypatch):
    mon = make(tmp_path)
    calls = []

    def sleep(s):
        calls.append(s)
        if len(calls) == 2:
            t = now_ns()
            write_log(mon, HEADER.format(t, SINK_LOG_FORMAT))
        if len(calls) == 3:
            write_log(mon, 'S {0} established outbound 1 x\n'.format(now_ns()))
    monkeypatch.setattr(monitor_module.time, 'sleep', sleep)
    assert wait(mon) == 3


def test_wait_does_not_end_on_a_lost_connection_for_another_session(tmp_path, no_sleep):
    '''A down for a connection the sink never held is not the session.'''
    mon = make(tmp_path)
    t = now_ns()
    write_log(mon, HEADER.format(t, SINK_LOG_FORMAT)
              + 'S {0} established inbound 2 x\n'.format(t)
              + 'S {0} down outbound 1 collision\n'.format(t))
    assert wait(mon) == 0


def test_wait_ends_on_a_sink_that_never_started(tmp_path, no_sleep):
    mon = make(tmp_path)
    mon.START_GRACE_S = 3
    with open(os.path.join(mon.host_dir, mon.STDERR_NAME), 'w') as f:
        f.write('flag provided but not defined: -bogus\n')
    with pytest.raises(SessionUnavailable) as caught:
        wait(mon)
    assert 'never started' in str(caught.value)
    assert '-bogus' in str(caught.value)
    assert len(no_sleep) == 3


def test_wait_ends_on_a_malformed_log_rather_than_retrying_it(tmp_path, no_sleep):
    mon = make(tmp_path)
    write_log(mon, HEADER.format(now_ns(), SINK_LOG_FORMAT) + 'C x 1 1 0\n')
    with pytest.raises(SessionUnavailable) as caught:
        wait(mon)
    assert 'malformed' in str(caught.value)
    assert no_sleep == []


def test_wait_ends_on_a_sink_that_stopped_before_establishing(tmp_path, no_sleep):
    mon = make(tmp_path)
    write_log(mon, HEADER.format(now_ns() - 10 * 10**9, SINK_LOG_FORMAT))
    with pytest.raises(SessionUnavailable) as caught:
        wait(mon)
    assert 'the sink has stopped' in str(caught.value)


def test_wait_keeps_waiting_on_an_idle_session(tmp_path, monkeypatch):
    '''Idle is what the GoBGP wait retried too: a target not up yet.'''
    mon = make(tmp_path)
    calls = []

    def sleep(s):
        calls.append(s)
        # keep the log fresh with heartbeats while idle
        write_log(mon, 'H {0} 0 0 0\n'.format(now_ns()))
        if len(calls) == 4:
            write_log(mon, 'S {0} established inbound 1 x\n'.format(now_ns()))
    monkeypatch.setattr(monitor_module.time, 'sleep', sleep)
    write_log(mon, HEADER.format(now_ns(), SINK_LOG_FORMAT))
    assert wait(mon) == 4


from monitor import Receiver, SinkReceiver

RECEIVER_CONF = {'as': 1002, 'router-id': '10.10.0.9',
                 'local-address': '10.10.0.9'}


def make_receiver(tmp_path, index=3):
    r = SinkReceiver(index, str(tmp_path / 'receiver{0}'.format(index)),
                     RECEIVER_CONF)
    r.config = CONF
    return r


def test_a_sink_receiver_is_a_receiver_by_name_and_session(tmp_path):
    r = make_receiver(tmp_path)
    assert r.name == 'bgperf_receiver3'
    assert r.name.startswith(Receiver.CONTAINER_NAME_PREFIX)
    assert r.image == 'bgperf/sink'
    script = r.get_startup_cmd()
    # its own AS and address, peered with the target
    assert '-local-as 1002' in script and '-local-address 10.10.0.9' in script
    assert '-peer-address 10.10.0.1' in script


def test_a_sink_receiver_is_never_polled_as_the_instrument(tmp_path):
    with pytest.raises(NotImplementedError, match='not an instrument'):
        make_receiver(tmp_path).stats(queue.Queue())


def test_a_sink_receiver_reads_its_count_from_its_log(tmp_path):
    r = make_receiver(tmp_path)
    t = now_ns()
    write_log(r, HEADER.format(t, SINK_LOG_FORMAT) + 'C {0} 4321 7 0\n'.format(t))
    assert r.accepted_prefixes() == 4321


def test_an_unreadable_receiver_raises_rather_than_reading_zero(tmp_path):
    r = make_receiver(tmp_path)
    with pytest.raises(FileNotFoundError):
        r.accepted_prefixes()
    write_log(r, HEADER.format(now_ns() - 10 * 10**9, SINK_LOG_FORMAT))
    from sink import SinkLogError
    with pytest.raises(SinkLogError, match='stopped'):
        r.accepted_prefixes()
