'''The neighbour sampler, and the parser underneath it.

Both halves of one incident, reproduced on the campaign host and recorded here
so it cannot come back silently.

`gobgp neighbor -j` answers with its *error* JSON-encoded, so a failed read
parses cleanly into a `str`. Iterating a string yields characters, and
`neighbor['state']` on one raised "TypeError: string indices must be integers"
from inside `Container.neighbor_stats()`, whose loop had no `try/except`. The
thread died for the rest of the run, `neighbors_checked` froze at its last
value, `note_neighbors_checkpoint()` never fired, and `ConvergenceTracker`'s
CONVERGED gate -- which requires that checkpoint -- could never be satisfied.
The run was published FAILED after 2194s with the target holding all 5,000,000
routes and the monitor holding every one of them. Measured again with the read
guarded: the same cell converged in 133s, having hit the bad payload once.
'''
import queue
import sys
import time

import pytest

from conftest import REPO_ROOT  # noqa: F401

import gobgp
import monitor as monitor_module
import measurements as measurements_module
from base import Container


class FakeGoBGP(gobgp.GoBGPTarget):
    '''Just enough target to drive the parser: it is the payload under test.'''

    name = 'fake_target'

    def __init__(self, payload):
        self._payload = payload

    def local(self, cmd, **kwargs):
        return self._payload


@pytest.mark.parametrize('payload,described', [
    # The one that actually happened, and the reason this file exists.
    (b'"rpc error: code = Unavailable"', 'str'),
    (b'null', 'NoneType'),
    (b'{"neighbors": []}', 'dict'),
])
def test_a_non_list_payload_is_named_where_it_is_read(payload, described):
    with pytest.raises(gobgp.GoBGPNeighborReadError) as caught:
        gobgp.GoBGPTarget.get_neighbors_state(FakeGoBGP(payload))
    message = str(caught.value)
    assert described in message
    # and it quotes what came back, so the diagnosis does not need a re-run
    assert 'gobgp neighbor -j' in message


def test_a_non_dict_entry_is_named_rather_than_indexed():
    '''A string payload iterates as characters, which is how this became a
    TypeError three frames from the read.'''
    with pytest.raises(gobgp.GoBGPNeighborReadError) as caught:
        gobgp.GoBGPTarget.get_neighbors_state(FakeGoBGP(b'[1, 2]'))
    assert 'where a neighbour was expected' in str(caught.value)


def test_an_empty_read_is_not_an_empty_fleet():
    '''Falling through left the raw bytes in place, and bytes iterate as
    nothing -- so every peer silently vanished from that poll rather than the
    read being reported as failed.'''
    with pytest.raises(gobgp.GoBGPNeighborReadError):
        gobgp.GoBGPTarget.get_neighbors_state(FakeGoBGP(b''))


def test_an_empty_fleet_still_reads_cleanly():
    '''An actually-empty list is a legitimate answer and must not raise, or the
    guard would fail every run before its first session comes up.'''
    assert gobgp.GoBGPTarget.get_neighbors_state(FakeGoBGP(b'[]')) == ({}, {})


class FlakyTarget(Container):
    '''A target whose neighbour read fails once and then works.'''

    def __init__(self, failures):
        self.name = 'flaky'
        self.stop_monitoring = False
        self._remaining_failures = failures
        self.samples = 0

    def sample_target_state(self):
        if self._remaining_failures > 0:
            self._remaining_failures -= 1
            raise gobgp.GoBGPNeighborReadError('synthetic bad read')
        self.samples += 1
        return {'10.0.0.1': True}, {'10.0.0.1': True}, None


def _drain(target, want_messages, timeout_s=10.0):
    q = queue.Queue()
    target.neighbor_stats(q)
    seen = []
    deadline = time.monotonic() + timeout_s
    while len(seen) < want_messages and time.monotonic() < deadline:
        try:
            seen.append(q.get(timeout=0.25))
        except queue.Empty:
            continue
    target.stop_monitoring = True
    return seen


def test_the_sampler_survives_a_bad_read_and_keeps_sampling():
    '''The thread dying is what turned a converged run into a failed one, and
    nothing downstream could tell: the counts simply stopped moving.'''
    target = FlakyTarget(failures=1)
    seen = _drain(target, want_messages=2)
    assert target.samples >= 1, 'sampler did not recover from one bad read'
    assert any('neighbors_checked' in m for m in seen)


def test_a_bad_read_is_counted_and_named_rather_than_swallowed():
    '''Surviving quietly is the other half of the same bug: a sampler that
    fails every time still produces no checkpoint, and this is the only thing
    that distinguishes such a run from a slow daemon.'''
    target = FlakyTarget(failures=1)
    _drain(target, want_messages=2)
    assert target.neighbor_sample_failures == 1
    assert 'synthetic bad read' in (target.neighbor_sample_last_error or '')
    # the consecutive counter resets, so a later single failure reports again
    assert target.neighbor_sample_consecutive_failures == 0


def test_the_counters_start_clean_on_every_container():
    assert Container.neighbor_sample_failures == 0
    assert Container.neighbor_sample_consecutive_failures == 0
    assert Container.neighbor_sample_last_error is None


class FlakyMonitor(monitor_module.Monitor):
    '''A monitor whose read returns whatever payload the test hands it.'''

    def __init__(self, payloads):
        self.name = 'bgperf_monitor'
        self.monitor_for = 'fake_target'
        self.monitor_name = 'bgperf_monitor'
        self.stop_monitoring = False
        self.config = {'monitor': {'check-points': [10]}}
        self._payloads = list(payloads)
        self.reads = 0

    def local(self, cmd, **kwargs):
        self.reads += 1
        if self._payloads:
            return self._payloads.pop(0)
        return GOOD_MONITOR_PAYLOAD


GOOD_MONITOR_PAYLOAD = (
    b'[{"state": {"neighbor_address": "10.10.255.254"}, '
    b'"afi_safis": [{"state": {"accepted": 50}}]}]')

# The payload that actually happened. `json.loads(...)[0]` is 'r', which does
# not raise -- so the monitor's old `try` caught nothing and the assignment on
# the next line killed the thread.
BAD_MONITOR_PAYLOAD = b'"rpc error: code = Unavailable"'


def test_the_monitor_survives_the_payload_that_killed_the_target_sampler():
    '''The monitor reads the same command as the target and is the instrument
    every published timing comes from. Guarding only the target left this one
    open: `recved` freezes, and ConvergenceTracker fails the run as stuck with
    no target-side guard able to save it.'''
    mon = FlakyMonitor([BAD_MONITOR_PAYLOAD])
    q = queue.Queue()
    mon.stats(q, interval=0.05)
    got = None
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        try:
            got = q.get(timeout=0.25)
            break
        except queue.Empty:
            continue
    mon.stop_monitoring = True
    assert got is not None, 'monitor thread died on the bad payload'
    assert got['who'] == 'bgperf_monitor'
    assert mon.monitor_sample_failures == 1
    assert 'rpc error' in (mon.monitor_sample_last_error or '')


def test_a_failing_monitor_read_still_waits_its_interval():
    '''The old `continue` skipped the sleep, so a persistent failure spun
    `docker exec` as fast as the host allowed -- inside the container being
    measured, and invisible to `max foreign cpu %` because `gobgp` is in
    BGPERF_PROCESSES.'''
    mon = FlakyMonitor([BAD_MONITOR_PAYLOAD] * 500)
    mon.stats(q := queue.Queue(), interval=0.05)
    time.sleep(1.0)
    mon.stop_monitoring = True
    assert q.empty()
    # ~20 reads at a 0.05s interval; a spinning loop does thousands.
    assert mon.reads < 100, 'monitor spun instead of waiting: %d reads' % mon.reads


def test_a_list_of_non_neighbours_is_caught_before_it_is_indexed():
    '''Distinct from the payload above: a *list* passes the list check and only
    the per-entry check stops `info['who'] = ...` from raising. Mutation
    testing found this branch uncovered -- the string payload is rejected one
    check earlier, so it never exercised this one.'''
    mon = FlakyMonitor([b'[1, 2]'])
    q = queue.Queue()
    mon.stats(q, interval=0.05)
    got = None
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        try:
            got = q.get(timeout=0.25)
            break
        except queue.Empty:
            continue
    mon.stop_monitoring = True
    assert got is not None, 'monitor thread died on a list of non-neighbours'
    assert mon.monitor_sample_failures == 1
    assert 'where a neighbour was expected' in (mon.monitor_sample_last_error or '')


def test_an_empty_neighbour_list_is_a_failed_read_not_a_silent_skip():
    '''`payload[0]` on an empty list is an IndexError; it must be named rather
    than reached.'''
    mon = FlakyMonitor([b'[]'])
    q = queue.Queue()
    mon.stats(q, interval=0.05)
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline and mon.monitor_sample_failures == 0:
        time.sleep(0.05)
    mon.stop_monitoring = True
    assert mon.monitor_sample_failures >= 1
    assert 'not a list of neighbours' in (mon.monitor_sample_last_error or '')


def test_a_clean_run_keeps_the_document_it_has_always_written():
    import bgperf2

    class Clean(object):
        neighbor_sample_failures = 0
        monitor_sample_failures = 0

    assert bgperf2.sampler_read_failures(Clean(), Clean()) is None
    assert 'instrument' not in measurements_module.event_artifact([], 'converged')


def test_a_run_says_when_its_own_instruments_missed_reads():
    '''Surviving a bad read quietly replaces a loud failure with a silent gap
    in the evidence the verdict rests on. A target sampler that missed reads
    may have reached the neighbour checkpoint late -- which moves the assurance
    window from 5 samples to 20 and shows up nowhere else -- and a monitor that
    missed reads has gaps in the series every published timing comes from.'''
    import bgperf2

    class Target(object):
        neighbor_sample_failures = 2
        neighbor_sample_last_error = 'TypeError: string indices must be integers'

    class Mon(object):
        monitor_sample_failures = 1
        monitor_sample_last_error = 'MonitorReadError: rpc error'

    section = bgperf2.sampler_read_failures(Target(), Mon())
    assert section['target_neighbor_sampler']['failed_reads'] == 2
    assert section['monitor']['failed_reads'] == 1

    doc = measurements_module.event_artifact([], 'converged', instrument=section)
    assert doc['instrument']['monitor']['failed_reads'] == 1
    assert 'rpc error' in doc['instrument']['monitor']['last_error']


@pytest.mark.parametrize('payload', [
    b'"rpc error: code = Unavailable"',   # the payload this change set exists for
    b'null',
    b'[1, 2]',
    b'not json at all',
])
def test_wait_established_treats_a_bad_payload_as_not_yet_established(payload):
    '''The third read of `gobgp neighbor -j`, and the one most likely to meet
    that payload: it runs about a second after the container starts, when the
    RPC endpoint is least likely to be up. It is not in a sampler thread, so a
    TypeError here propagates out of bench() before any teardown and kills the
    whole batch cell.'''
    import contextlib
    import io

    class Flaky(monitor_module.Monitor):
        def __init__(self, bad):
            self._bad = bad
            self.reads = 0

        def local(self, cmd, **kwargs):
            self.reads += 1
            if self.reads < 3:
                return self._bad
            return b'{"state": {"session_state": "established"}}'

    mon = Flaky(payload)
    with contextlib.redirect_stdout(io.StringIO()):
        waited = monitor_module.Monitor.wait_established(mon, '10.0.0.1')
    assert waited == 2, 'a bad payload should read as "not established yet"'
