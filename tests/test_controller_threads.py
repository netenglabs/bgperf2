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
from measurements import ExportEventRecorder, TesterOffering


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
    '''A tester whose containers are not there, only its poll loop.

    Mid-run on purpose: the loop ends itself once the generator reports the
    whole table offered, so a fake that answers 'finished' on its first poll
    would make every shutdown test below pass without testing a shutdown.
    '''

    CONTAINER_NAME_PREFIX = 'fake_tester_'
    GUEST_DIR = '/root/config'
    REPORTS_OFFERING = True

    def get_offerings(self):
        return {'p1': TesterOffering(established=True, expected=100, offered=1)}


class FinishedTester(FakeTester):
    '''A generator that has offered its whole configured table.'''

    CONTAINER_NAME_PREFIX = 'finished_tester_'

    def get_offerings(self):
        return {'p1': TesterOffering(established=True, expected=100,
                                     offered=100)}


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


def test_a_finished_generator_is_not_polled_for_the_rest_of_the_run(tmp_path):
    '''One poll of a BIRD tester is a `docker exec` running a `birdc` per
    configured peer. Polling on until the monitor converges spends that on a
    generator with nothing left to say -- and `birdc` is in
    contention.BGPERF_PROCESSES, so it is the one load `max foreign cpu %`
    cannot report.
    '''
    before = threading.active_count()
    bgperf2.controller_stop.clear()
    tester = FinishedTester('1', str(tmp_path), {}, 'bgperf/bird')
    q = queue.Queue()

    try:
        tester.offering_stats(q, bgperf2.controller_stop, interval=0.05)

        deadline = time.time() + 5
        while threading.active_count() > before and time.time() < deadline:
            time.sleep(0.01)
        assert threading.active_count() == before, \
            'the poll kept asking a generator that had finished'
    finally:
        bgperf2.controller_stop.set()

    # The poll that ends the loop still carries the completion evidence: the
    # sample is queued before the loop looks at it.
    assert not q.empty(), 'the final poll was dropped rather than reported'
    assert 'tester_offering' in q.get()


def test_a_raising_describer_costs_the_description_and_not_the_batch(monkeypatch):
    '''`publish_batch_summary()` wraps the summariser for the reason
    `write_event_artifact()` catches its own findings -- the rows are already
    on disk -- but the call that *describes* the document sat outside that
    guard. A raise there aborts batch() after the CSV is written and before
    create_batch_graphs() and every remaining test in the yaml, costing more
    rows than the summariser ever could.

    It reports its own line rather than `summary unavailable`, which would be
    false: the document is on disk and only the description failed.
    '''
    monkeypatch.setattr(bgperf2, 'summarize_batch',
                        lambda *a, **k: {'cells': [], 'repetitions': 1})
    monkeypatch.setattr(bgperf2, 'write_batch_summary', lambda *a, **k: None)

    def explode(*args, **kwargs):
        raise KeyError('rival_cell')
    monkeypatch.setattr(bgperf2, 'describe_batch_summary', explode)

    lines = bgperf2.publish_batch_summary('sum.json', 'sum', [], {}, 1)
    assert len(lines) == 1
    assert 'summary unavailable' not in lines[0]
    assert 'describing it raised' in lines[0]
    assert 'KeyError' in lines[0]


class UnfinishedReceiver:
    '''A receiver that never gets the whole table, so its poll cannot stop.

    Mid-run on purpose, for the reason `FakeTester` is: a receiver that
    answered "I have it all" on the first round would end the loop by itself
    and make every shutdown assertion below pass without a shutdown.
    '''

    READ_S = 0.0

    def __init__(self, name='bgperf_receiver0'):
        self.name = name
        self.reads = 0

    def accepted_prefixes(self):
        self.reads += 1
        time.sleep(self.READ_S)
        return 1


def an_export_recorder(receivers, interval=0.05):
    return ExportEventRecorder(time.monotonic(), [r.name for r in receivers],
                               100, sample_interval_s=interval)


def wait_for_a_round(receivers, recorder=None, timeout=5):
    '''Wait for a round to have been read, and recorded when asked.

    The two are not the same instant: a round reads every receiver and only
    then records, so a test that watched the reads alone would race the write
    it is about to assert on.
    '''
    deadline = time.time() + timeout
    while time.time() < deadline:
        read = all(r.reads >= 1 for r in receivers)
        recorded = recorder is None or any(
            value is not None for value in recorder.accepted.values())
        if read and recorded:
            return True
        time.sleep(0.01)
    return False


def test_export_thread_samples_then_stops():
    '''The export poll execs into containers too, once per receiver per round,
    so a loop that outlives its cell keeps doing that for every later one.'''
    before = threading.active_count()
    bgperf2.controller_stop.clear()
    receivers = [UnfinishedReceiver()]
    export = an_export_recorder(receivers)

    bgperf2.controller_export_stats(
        receivers, export, {}, {}, bgperf2.controller_stop, 0.05)

    assert wait_for_a_round(receivers, export), 'export poll recorded nothing'
    assert export.accepted == {'bgperf_receiver0': 1}

    bgperf2.controller_stop.set()
    deadline = time.time() + 5
    while threading.active_count() > before and time.time() < deadline:
        time.sleep(0.01)
    assert threading.active_count() == before, 'export poll outlived the run'


def test_the_export_poll_ends_when_the_delivery_window_closes():
    """The window is the delivery of the table, and the poll stops with it.

    `churn_phase()` and `policy_reload_phase()` take the queue over after
    convergence and skip anything that is not a monitor sample, so a round
    landing during a burst would be dropped -- publishing a receiver that
    crossed the check-point in it as one that was never served -- while the
    poll went on exec'ing into containers throughout the interval whose cost
    was being measured.
    """
    before = threading.active_count()
    bgperf2.controller_stop.clear()
    delivery = threading.Event()
    receivers = [UnfinishedReceiver()]

    bgperf2.controller_export_stats(
        receivers, an_export_recorder(receivers), {}, {},
        bgperf2.controller_stop, 0.05, delivery_stop=delivery)
    assert wait_for_a_round(receivers), 'export poll read nothing'

    delivery.set()
    deadline = time.time() + 5
    while threading.active_count() > before and time.time() < deadline:
        time.sleep(0.01)
    assert threading.active_count() == before, \
        'export poll outlived the delivery it measures'


def test_the_export_poll_survives_a_controller_event_the_next_cell_clears():
    """`controller_stop` is cleared at the top of every batch cell, so a round
    still in flight when a cell ends could find it clear again and poll on
    against containers that are gone. The delivery event is per run and never
    cleared, which is what closes that window."""
    before = threading.active_count()
    bgperf2.controller_stop.clear()
    delivery = threading.Event()
    receivers = [UnfinishedReceiver()]

    bgperf2.controller_export_stats(
        receivers, an_export_recorder(receivers), {}, {},
        bgperf2.controller_stop, 0.05, delivery_stop=delivery)
    wait_for_a_round(receivers)

    delivery.set()                          # as bench() does at convergence
    bgperf2.controller_stop.clear()         # as the next cell does
    deadline = time.time() + 5
    while threading.active_count() > before and time.time() < deadline:
        time.sleep(0.01)
    assert threading.active_count() == before, \
        'export poll survived into the next cell'


class StampingReceiver(UnfinishedReceiver):
    '''A receiver whose read costs real time and records when it happened.'''

    READ_S = 0.12

    def __init__(self, name='bgperf_receiver0'):
        super().__init__(name)
        self.stamps = []

    def accepted_prefixes(self):
        self.stamps.append(time.monotonic())
        return super().accepted_prefixes()


def export_poll_gaps(receivers, interval, samples, timeout=10):
    '''Run the export loop until `samples` rounds land, and return their gaps.'''
    bgperf2.controller_stop.clear()
    bgperf2.controller_export_stats(
        receivers, an_export_recorder(receivers, interval), {}, {},
        bgperf2.controller_stop, interval)
    deadline = time.time() + timeout
    try:
        while len(receivers[0].stamps) < samples and time.time() < deadline:
            time.sleep(0.01)
    finally:
        bgperf2.controller_stop.set()
    stamps = receivers[0].stamps[:samples]
    assert len(stamps) == samples, 'export poll produced too few rounds'
    return [b - a for a, b in zip(stamps, stamps[1:])]


def test_the_export_poll_waits_to_a_deadline_rather_than_after_the_round():
    '''A round is one exec per receiver, so sleeping a whole interval after it
    makes the cadence round+interval while every event claims the nominal one
    -- and that claim is what says whether an export interval was resolved.'''
    gaps = export_poll_gaps([StampingReceiver()], 0.2, samples=3)

    assert min(gaps) < 0.2 + StampingReceiver.READ_S / 2


def test_the_export_poll_duty_is_capped_below_the_cadence_too():
    """The floor applies on every round, not only on one that overran. Four
    receivers at a 200ms read give a 0.8s round inside a 1s cadence -- 80% of
    the window spent inside containers without ever tripping an overrun, in a
    load `max foreign cpu %` cannot see."""
    interval = 0.3
    receivers = [StampingReceiver('bgperf_receiver0'),
                 StampingReceiver('bgperf_receiver1')]
    round_s = 2 * StampingReceiver.READ_S      # 0.24s, inside the cadence

    gaps = export_poll_gaps(receivers, interval, samples=3)

    assert round_s < interval, 'this test must not exercise the overrun branch'
    assert min(gaps) >= round_s * bgperf2.EXPORT_POLL_MAX_DUTY * 0.9


def test_an_export_round_that_overruns_waits_at_least_as_long_as_it_took():
    '''The instrument runs inside the window it measures, in a load
    `max foreign cpu %` cannot see -- `gobgp` is in `BGPERF_PROCESSES` -- and
    nothing bounds the receiver count. So a round that overruns the cadence
    waits at least its own duration: the poll can never spend more than
    `EXPORT_POLL_MAX_DUTY` of its time inside containers, whatever the fan-out.
    What that costs is resolution, which every interval publishes.'''
    interval = 0.05
    receivers = [StampingReceiver('bgperf_receiver0'),
                 StampingReceiver('bgperf_receiver1')]
    round_s = 2 * StampingReceiver.READ_S

    gaps = export_poll_gaps(receivers, interval, samples=3)

    # Round plus a wait at least as long as the round: a duty cycle of 1 in 2,
    # not the round plus a fixed 0.05s that would leave it at 5 in 6.
    assert min(gaps) >= round_s * bgperf2.EXPORT_POLL_MAX_DUTY * 0.9

    assert min(gaps) >= interval
