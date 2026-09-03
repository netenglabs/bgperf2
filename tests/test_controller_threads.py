'''The controller sampling threads have to stop when a run ends.

batch() calls bench() in-process once per cell, so a thread that never exits is
not a tidiness problem: a 40-run batch would finish with 40 mpstat loops, 40
`free` loops and 40 `ps` loops still polling, and bgperf would be generating the
very host contention it reports. finish_bench() used to assign a module-level
bool without `global`, which made the assignment a no-op and left every thread
running for the life of the process.

Only the `ps`-based sampler is exercised here -- `free` and `mpstat` add an
external dependency without testing anything different about the shutdown path.
'''
import queue
import threading
import time

import bgperf2
from base import Tester
from measurements import TesterOffering


def test_foreign_cpu_thread_samples_then_stops():
    q = queue.Queue()
    before = threading.active_count()

    bgperf2.controller_stop.clear()
    bgperf2.controller_foreign_cpu(q, interval=0.05)

    deadline = time.time() + 5
    while q.empty() and time.time() < deadline:
        time.sleep(0.01)
    assert not q.empty(), 'sampler produced nothing'

    sample = q.get()
    assert sample['who'] == 'controller'
    assert 'foreign_cpu' in sample

    bgperf2.controller_stop.set()
    deadline = time.time() + 5
    while threading.active_count() > before and time.time() < deadline:
        time.sleep(0.01)
    assert threading.active_count() == before, 'sampler thread outlived the run'


def test_a_second_run_gets_a_working_sampler():
    '''The stop flag is cleared per run, so run N+1 still collects samples.

    A flag that is only ever set would leave every later cell of a batch with a
    sampler that exits immediately and a contention column stuck at 0.
    '''
    before = threading.active_count()
    bgperf2.controller_stop.set()          # as finish_bench() leaves it

    q = queue.Queue()
    bgperf2.controller_stop.clear()        # as bench() does on the next run
    bgperf2.controller_foreign_cpu(q, interval=0.05)

    deadline = time.time() + 5
    while q.empty() and time.time() < deadline:
        time.sleep(0.01)
    assert not q.empty(), 'second run collected no samples'

    bgperf2.controller_stop.set()
    deadline = time.time() + 5
    while threading.active_count() > before and time.time() < deadline:
        time.sleep(0.01)


class FakeTester(Tester):
    '''A tester whose containers are not there, only its poll loop.'''

    CONTAINER_NAME_PREFIX = 'fake_tester_'
    GUEST_DIR = '/root/config'
    REPORTS_OFFERING = True

    def get_offerings(self):
        return {'p1': TesterOffering(established=True, expected=1, offered=1)}


def test_tester_offering_thread_samples_then_stops(tmp_path):
    '''The generator poll execs into containers, so a loop that outlives its
    run keeps doing that for every later batch cell.'''
    before = threading.active_count()
    bgperf2.controller_stop.clear()
    tester = FakeTester('1', str(tmp_path), {}, 'bgperf/bird')
    q = queue.Queue()

    tester.offering_stats(q, bgperf2.controller_stop, interval=0.05)

    deadline = time.time() + 5
    while q.empty() and time.time() < deadline:
        time.sleep(0.01)
    assert not q.empty(), 'tester poll produced nothing'
    sample = q.get()
    assert sample['who'] == 'fake_tester_1'
    assert 'tester_offering' in sample
    assert 'monotonic_s' in sample

    bgperf2.controller_stop.set()
    deadline = time.time() + 5
    while threading.active_count() > before and time.time() < deadline:
        time.sleep(0.01)
    assert threading.active_count() == before, 'tester poll outlived the run'


def test_a_tester_poll_stops_when_its_own_container_is_done(tmp_path):
    '''finish_bench() sets stop_monitoring on the containers as well, so the
    poll cannot race the teardown it is exec'ing into.'''
    before = threading.active_count()
    bgperf2.controller_stop.clear()
    tester = FakeTester('2', str(tmp_path), {}, 'bgperf/bird')
    q = queue.Queue()

    tester.offering_stats(q, bgperf2.controller_stop, interval=0.05)
    deadline = time.time() + 5
    while q.empty() and time.time() < deadline:
        time.sleep(0.01)
    tester.stop_monitoring = True

    deadline = time.time() + 5
    while threading.active_count() > before and time.time() < deadline:
        time.sleep(0.01)
    assert threading.active_count() == before, 'tester poll outlived its container'
    bgperf2.controller_stop.set()


class SlowReadTester(FakeTester):
    '''A tester whose read costs real time, the way a real exec does.'''

    CONTAINER_NAME_PREFIX = 'slow_tester_'
    READ_S = 0.12

    def get_offerings(self):
        time.sleep(self.READ_S)
        return super().get_offerings()


def poll_gaps(tester, interval, samples, timeout=10):
    '''Run the poll loop until `samples` samples land, and return their gaps.'''
    bgperf2.controller_stop.clear()
    q = queue.Queue()
    stamps = []
    tester.offering_stats(q, bgperf2.controller_stop, interval=interval)
    deadline = time.time() + timeout
    try:
        while len(stamps) < samples and time.time() < deadline:
            try:
                stamps.append(q.get(timeout=0.05)['monotonic_s'])
            except queue.Empty:
                pass
    finally:
        bgperf2.controller_stop.set()
    assert len(stamps) == samples, 'tester poll produced too few samples'
    return [b - a for a, b in zip(stamps, stamps[1:])]


def test_the_poll_waits_to_a_deadline_rather_than_after_the_read(tmp_path):
    '''Sleeping a whole interval after the read makes the cadence read+interval.

    Every event the recorder publishes carries the resolution of its poll, and
    that is what qualifies an injection of 0.0s as unresolved rather than
    instant -- so a cadence wider than the one asked for must not be spent
    silently on the read.
    '''
    tester = SlowReadTester('1', str(tmp_path), {}, 'bgperf/bird')
    interval = 0.2

    gaps = poll_gaps(tester, interval, samples=3)

    # Sleeping after the read would put every gap at ~0.32s.
    assert min(gaps) < interval + SlowReadTester.READ_S / 2


def test_a_read_that_overruns_the_interval_still_waits(tmp_path):
    '''The loop must not become the contention the run would then report.

    Chasing the deadline when the read is slower than the interval would poll
    back-to-back and leave the controller inside a container continuously. The
    achieved cadence is recorded instead -- see TesterEventRecorder, which
    derives each event's resolution from the sample timestamps.
    '''
    tester = SlowReadTester('2', str(tmp_path), {}, 'bgperf/bird')
    interval = 0.05

    gaps = poll_gaps(tester, interval, samples=3)

    # Polling back-to-back would put every gap at the read time alone.
    assert min(gaps) > SlowReadTester.READ_S + interval / 2
