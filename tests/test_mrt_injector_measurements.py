'''Docker-free tests for bgpdump2 MRT injector instrumentation.

The fixtures are real `bgpdump2 --blaster` logs, captured from a two-injector
10,000-prefix run against a BIRD target on 2026-09-03.  `bgpdump2_blaster.log`
caught the walk in progress on one poll; `bgpdump2_blaster_one_poll.log` is the
injector whose whole walk landed between two lines of log.

`bgpdump2_blaster_io.log` is a third, from a single-injector 500,000-prefix run
on 2026-09-03 started with `-t io`: the only shape that carries blocked-write
evidence, and the reason it was run with one injector is that the log of a
second one is 23 MB of the target's echo.

Earlier polls are modelled by truncating those captures rather than by writing
plausible-looking log text, since the shapes that matter here -- a counter that
has not appeared yet, a session that is not up -- are exactly the ones an
invented fixture gets subtly wrong.
'''
import pytest

from bgpdump2 import (BlasterLogReader, Bgpdump2Tester,
                      parse_blaster_log, tester_offering)
from measurements import (
    EventKind,
    EventPhase,
    LifecycleEvent,
    TesterEventRecorder,
    TesterOffering,
    tester_metrics,
    unique_event,
)


IO_LOG = 'bgpdump2_blaster_io.log'


@pytest.fixture
def blaster_log(fixture_text):
    def _read(name='bgpdump2_blaster.log', lines=None):
        text = fixture_text(name)
        if lines is None:
            return text
        # Keep the trailing newline: a log being read while it is written ends
        # at a line boundary or mid-line, and both are worth testing.
        return ''.join(text.splitlines(keepends=True)[:lines])
    return _read


# --- the injector's own log -------------------------------------------------

def test_a_finished_injector_reports_its_whole_walk(blaster_log):
    parsed = parse_blaster_log(blaster_log())

    assert parsed['established'] is True
    assert parsed['peer'] == '10.10.255.254'
    assert parsed['walk_complete'] is True
    assert parsed['prefixes_sent'] == 10000
    assert parsed['updates_sent'] == 2288
    assert parsed['prefixes_withdrawn'] == 0
    assert parsed['ribs'] == ({
        'peer_index': 4,
        'peer_as': 57866,
        'ipv4_prefixes': 10000,
        'ipv6_prefixes': 0,
        'paths': 2287,
        'walk_time_s': 0.011314,
    },)


def test_prefix_counts_are_queue_side_and_octets_are_not(blaster_log):
    '''The mid-walk line is the evidence that these are different measurements.

    bgpdump2 counts a prefix when it encodes it into the session write buffer
    and an octet only when a write() to the socket succeeds.  This capture
    caught 9,981 prefixes encoded against 88 bytes on the wire.
    '''
    mid_walk = parse_blaster_log(blaster_log(lines=10))

    assert mid_walk['prefixes_sent'] == 9981
    assert mid_walk['octets_sent'] == 88
    assert mid_walk['walk_complete'] is False

    finished = parse_blaster_log(blaster_log())
    assert finished['octets_sent'] == 259226


def test_a_counter_that_has_not_been_logged_is_absent_not_zero(blaster_log):
    established = parse_blaster_log(blaster_log(lines=9))

    assert established['established'] is True
    assert established['prefixes_sent'] is None
    assert established['octets_sent'] is None
    # The RIB is loaded and its walk has started, so its size is known while
    # its walk time is not.
    assert established['ribs'][0]['ipv4_prefixes'] == 10000
    assert established['ribs'][0]['walk_time_s'] is None


def test_a_session_that_is_not_up_yet_says_so(blaster_log):
    connecting = parse_blaster_log(blaster_log(lines=5))

    assert connecting['state'] == 'opensent'
    assert connecting['established'] is False
    assert connecting['ribs'] == ()


def test_an_empty_log_is_read_without_inventing_a_session():
    parsed = parse_blaster_log('')

    assert parsed['established'] is False
    assert parsed['walk_complete'] is False
    assert parsed['prefixes_sent'] is None
    assert parsed['ribs'] == ()


def test_unstamped_and_half_written_lines_contribute_nothing(blaster_log):
    '''Two things a reader of a live log meets on every poll.

    bgpdump2 prints its option parsing before logging starts, and an
    incremental read can land in the middle of the line being written.  A
    parser that took either as a record would publish a wrong count, not fail.
    '''
    text = blaster_log(lines=12)
    assert text.startswith('peer_spec_index[1]:')

    truncated = text + 'Sep 03 00:16:11.362120 End-of-RIB, walk ti'
    parsed = parse_blaster_log(truncated)

    assert parsed['prefixes_sent'] == 10000
    assert parsed['ribs'][0]['walk_time_s'] is None


# --- blocked writes, when the injector was told to report them --------------

def test_the_write_lines_are_counted_by_what_they_mean(blaster_log):
    '''Three IO-class lines, only two of which are backpressure.

    `Partial write` is the socket taking part of the buffer and refusing the
    rest. `Write buffer full` is an encode pass finding no room in the 256KB
    session buffer, which is also the only place a write() that returned
    EAGAIN ever shows up -- bgpdump2 logs nothing for one. `Full write` is the
    ordinary case and is counted only because seeing one proves the class is
    on.
    '''
    parsed = parse_blaster_log(blaster_log(IO_LOG))

    assert parsed['io_traced'] is True
    assert parsed['full_writes'] == 28
    assert parsed['partial_writes'] == 13
    assert parsed['write_stalls'] == 2
    # The same capture's ordinary facts are unaffected by the extra lines.
    assert parsed['walk_complete'] is True
    assert parsed['prefixes_sent'] == 500000
    assert parsed['octets_sent'] == 7891005


def test_a_log_that_was_never_asked_reports_no_evidence_at_all(blaster_log):
    parsed = parse_blaster_log(blaster_log())

    assert parsed['io_traced'] is False
    assert parsed['partial_writes'] == 0

    offering = tester_offering(blaster_log())
    assert offering['blocked_writes'] is None
    assert offering['send_stalls'] is None


def test_never_blocked_and_never_asked_are_different_answers(blaster_log):
    '''The distinction the whole `io_traced` flag exists for.

    Both of these injectors have logged zero partial writes. One of them was
    reporting its writes and had none refused; the other was never told to
    report. Publishing 0 for the second would say the generator was never
    blocked on the strength of lines it was never asked to write.
    '''
    # Up to and including the first `Full write`, which is the session's OPEN.
    asked = tester_offering(blaster_log(IO_LOG, lines=5))
    assert asked['blocked_writes'] == 0
    assert asked['send_stalls'] == 0

    not_asked = tester_offering(blaster_log(IO_LOG, lines=4))
    assert not_asked['blocked_writes'] is None
    assert not_asked['send_stalls'] is None


def test_a_refused_write_is_counted_when_its_line_arrives(blaster_log):
    before_the_first_one = tester_offering(blaster_log(IO_LOG, lines=59))
    assert before_the_first_one['blocked_writes'] == 0

    after_it = tester_offering(blaster_log(IO_LOG, lines=60))
    assert after_it['blocked_writes'] == 1


def test_a_polled_injector_publishes_what_blocked_it(blaster_log):
    recorder = TesterEventRecorder(10.0, producer='mrt-injector0',
                                   sample_interval_s=1)

    def poll(at, lines=None):
        o = tester_offering(blaster_log(IO_LOG, lines=lines))
        recorder.observe(at, {'10.10.0.3': TesterOffering(
            established=o['established'], expected=500000,
            offered=o['offered'], send_complete=o['send_complete'],
            blocked_writes=o['blocked_writes'],
            send_stalls=o['send_stalls'])})

    # Still connecting, and no write line has appeared yet, so there is
    # nothing to say. One line later the session's OPEN is written and the
    # evidence becomes available at zero -- which is a real answer.
    poll(11.0, lines=4)
    assert recorder.backpressure == {
        'available': False,
        'reason': 'generator reported no blocked-write counter'}

    poll(12.0, lines=60)   # mid-walk, one refused write so far
    poll(13.0)             # finished

    assert recorder.backpressure == {'available': True,
                                     'max_blocked_writes': 13,
                                     'max_send_stalls': 2}
    complete = unique_event(recorder.events, EventKind.TESTER_COMPLETE)
    assert complete.details['backpressure']['max_blocked_writes'] == 13


def test_a_generator_with_no_counter_still_says_so(blaster_log):
    recorder = TesterEventRecorder(10.0, producer='mrt-injector0',
                                   sample_interval_s=1)
    o = tester_offering(blaster_log())
    recorder.observe(11.0, {'10.10.0.3': TesterOffering(
        established=o['established'], expected=10000, offered=o['offered'],
        send_complete=o['send_complete'],
        blocked_writes=o['blocked_writes'], send_stalls=o['send_stalls'])})

    assert recorder.backpressure['available'] is False


def test_blocked_write_counts_must_be_non_negative_integers():
    for field in ('blocked_writes', 'send_stalls'):
        with pytest.raises(ValueError):
            TesterOffering(established=True, expected=1, **{field: -1})
        with pytest.raises(ValueError):
            TesterOffering(established=True, expected=1, **{field: 1.5})


# --- the offering summary ---------------------------------------------------

def test_the_offering_carries_completion_and_both_counters(blaster_log):
    offering = tester_offering(blaster_log())

    assert offering['established'] is True
    assert offering['send_complete'] is True
    assert offering['offered'] == 10000
    assert offering['configured'] == 10000
    assert offering['octets_on_wire'] == 259226
    assert offering['walk_time_s'] == 0.011314


def test_an_injection_can_finish_inside_one_poll(blaster_log):
    '''Why the log is read at all, rather than the poll cadence trusted.

    This injector's whole 10,000-prefix walk took 1.03ms.  Polled at 1s it is
    an interval too short to resolve; bgpdump2 measured it itself.
    '''
    offering = tester_offering(blaster_log('bgpdump2_blaster_one_poll.log'))

    assert offering['send_complete'] is True
    assert offering['offered'] == 10000
    assert offering['walk_time_s'] == 0.001030


def test_completion_waits_for_the_line_that_carries_the_final_counters(
        blaster_log):
    '''`RIB walk complete` is logged before the counters it completes.

    bgpdump2 logs the marker, then the final `Sent ...` line, then End-of-RIB.
    A poll landing inside that group would otherwise report a completion whose
    counters are the mid-walk ones -- or, on this capture, a completion with no
    offered count at all, which cannot be placed on the injection timeline.
    '''
    log = 'bgpdump2_blaster_one_poll.log'
    marker_only = tester_offering(blaster_log(log, lines=10))
    assert marker_only['send_complete'] is False
    assert marker_only['offered'] is None

    counted = tester_offering(blaster_log(log, lines=11))
    assert counted['send_complete'] is False
    assert counted['offered'] == 10000

    finished = tester_offering(blaster_log(log, lines=12))
    assert finished['send_complete'] is True
    assert finished['offered'] == 10000


def test_a_walk_time_is_not_published_across_several_ribs(blaster_log):
    '''Sequential walks are not one interval.

    Each `End-of-RIB` line times its own RIB, so a session given several peer
    indexes has several walk times with gaps between them.  Adding them up
    would drop the gaps and publish the result as the playback duration.
    '''
    two_ribs = blaster_log() + blaster_log(lines=13).split('\n', 1)[1]
    offering = tester_offering(two_ribs)

    assert len(parse_blaster_log(two_ribs)['ribs']) == 2
    assert offering['walk_time_s'] is None
    # The table it loaded is still a sum over the RIBs it walked.
    assert offering['configured'] == 20000


# --- completion reported by the generator -----------------------------------

def test_a_generator_that_reports_completion_decides_it():
    '''MRT playback cannot judge completion by count.

    `-T` caps the table while the MRT file is read, so an injector ends up with
    whatever that peer's table holds.  Waiting for `offered >= expected` on the
    injector below would wait forever, though it has sent everything it has.
    '''
    short = TesterOffering(established=True, expected=10000, offered=9998,
                           send_complete=True)
    assert short.complete is True

    unfinished = TesterOffering(established=True, expected=10000, offered=9998)
    assert unfinished.complete is False


def test_a_generator_that_denies_completion_is_not_overruled_by_counts():
    still_going = TesterOffering(established=True, expected=10000,
                                 offered=10000, send_complete=False)

    assert still_going.complete is False


def test_reported_completion_still_needs_an_established_session():
    not_up = TesterOffering(established=False, expected=10000, offered=10000,
                            send_complete=True)

    assert not_up.complete is False


def test_send_complete_must_be_a_bool_or_absent():
    with pytest.raises(TypeError):
        TesterOffering(established=True, expected=1, send_complete='yes')


def test_count_based_completion_is_unchanged_when_none_is_reported():
    assert TesterOffering(established=True, expected=100, offered=100).complete
    assert not TesterOffering(established=True, expected=100, offered=99).complete
    # An unread session is still not a finished one.
    assert not TesterOffering(established=True, expected=100).complete


# --- the lifecycle a polled injector produces -------------------------------

def test_a_polled_injector_produces_the_lifecycle_from_its_log(blaster_log):
    recorder = TesterEventRecorder(10.0, producer='mrt-injector0',
                                   sample_interval_s=1)

    def poll(at, lines=None):
        offering = tester_offering(blaster_log(lines=lines))
        recorder.observe(at, {'10.10.0.3': TesterOffering(
            established=offering['established'],
            expected=10000,
            offered=offering['offered'],
            configured=offering['configured'],
            send_complete=offering['send_complete'])})

    poll(11.0, lines=5)    # connecting
    poll(12.0, lines=9)    # established, nothing encoded yet
    poll(13.0, lines=10)   # mid-walk
    poll(14.0)             # walk complete

    # The clock origin belongs to the controller; no tester emits its own, and
    # bench() merges them before deriving anything.
    origin = LifecycleEvent(EventKind.BENCH_CLOCK_STARTED, 10.0, 'controller',
                            EventPhase.SETUP)
    events = [origin] + list(recorder.events)
    kinds = [event.kind for event in recorder.events]
    assert kinds == [
        EventKind.TESTER_SESSION_READY,
        EventKind.TESTER_FIRST_UPDATE,
        EventKind.TESTER_LAST_UPDATE,
        EventKind.TESTER_COMPLETE,
    ]

    metrics = tester_metrics(events, 'mrt-injector0')
    assert metrics['tester_startup_s'] == 2.0
    assert metrics['injection_s'] == 1.0
    assert metrics['offered_prefixes'] == 10000
    # The poll that first saw a count had already seen 9,981 of them, so only
    # 19 prefixes are inside the measured interval. Publishing the rate without
    # that would read as a 10,000-prefix/s generator.
    assert metrics['offered_in_interval'] == 19


def test_a_walk_shorter_than_a_poll_is_still_accounted_for(blaster_log):
    '''The measurement's own limit, and the answer to it.

    This injector's entire 10,000-prefix walk took 1.03ms, so the first poll
    finds a session that is up, its whole table offered and its walk finished:
    first update and completion land together and the polled interval is 0.0.
    That is not an instant injection, it is one no poll can resolve -- and the
    generator's own two numbers are what say anything about it at all.
    '''
    recorder = TesterEventRecorder(10.0, producer='mrt-injector1',
                                   sample_interval_s=1)
    offering = tester_offering(blaster_log('bgpdump2_blaster_one_poll.log'))
    recorder.observe(11.0, {'10.10.0.4': TesterOffering(
        established=offering['established'],
        expected=10000,
        offered=offering['offered'],
        configured=offering['configured'],
        send_complete=offering['send_complete'],
        octets_on_wire=offering['octets_on_wire'],
        reported_send_duration_s=offering['walk_time_s'])})

    origin = LifecycleEvent(EventKind.BENCH_CLOCK_STARTED, 10.0, 'controller',
                            EventPhase.SETUP)
    metrics = tester_metrics([origin] + list(recorder.events), 'mrt-injector1')

    assert metrics['injection_s'] == 0.0
    assert metrics['injection_resolution_s'] == 1.0
    assert metrics['offered_rate_pps'] is None
    assert metrics['reported_injection_s'] == 0.001030
    assert metrics['octets_on_wire'] == 183852


def test_completion_is_held_until_an_update_has_been_observed():
    '''A reported completion must not sort before the first update.

    A generator can report that it finished on a poll whose counters were not
    legible. Recording that would leave `tester_complete` ahead of the
    `tester_first_update` a later poll finds, and deriving the injection
    interval from that stream raises out of finish_bench() -- killing a run
    that had already converged.
    '''
    recorder = TesterEventRecorder(0.0, 'mrt-injector0', sample_interval_s=1)
    recorder.observe(1.0, {'peer': TesterOffering(
        established=True, expected=10000, offered=None, send_complete=True)})

    assert unique_event(recorder.events, EventKind.TESTER_COMPLETE) is None

    recorder.observe(2.0, {'peer': TesterOffering(
        established=True, expected=10000, offered=10000, send_complete=True)})

    kinds = [event.kind for event in recorder.events]
    assert kinds == [
        EventKind.TESTER_SESSION_READY,
        EventKind.TESTER_FIRST_UPDATE,
        EventKind.TESTER_LAST_UPDATE,
        EventKind.TESTER_COMPLETE,
    ]
    origin = LifecycleEvent(EventKind.BENCH_CLOCK_STARTED, 0.0, 'controller',
                            EventPhase.SETUP)
    assert tester_metrics([origin] + list(recorder.events),
                          'mrt-injector0')['injection_s'] == 0.0


def test_an_injector_that_never_finishes_has_no_completion(blaster_log):
    recorder = TesterEventRecorder(10.0, producer='mrt-injector0',
                                   sample_interval_s=1)
    for at, lines in ((11.0, 9), (12.0, 10), (13.0, 10)):
        offering = tester_offering(blaster_log(lines=lines))
        recorder.observe(at, {'10.10.0.3': TesterOffering(
            established=offering['established'],
            expected=10000,
            offered=offering['offered'],
            send_complete=offering['send_complete'])})

    assert unique_event(recorder.events, EventKind.TESTER_COMPLETE) is None


# --- reading that log from the host ------------------------------------------

def injector(tmp_path, expected=10000, key='10.10.0.3'):
    '''A real Bgpdump2Tester whose container is never touched.

    Nothing here is stubbed: the injector's log is a bind-mounted file, so the
    poll the controller runs during a benchmark is exactly this one -- a read
    of `<host_dir>/bgpdump2.log`, with no `docker exec` in it at all.
    '''
    return Bgpdump2Tester('mrt-injector0', str(tmp_path), {
        'neighbors': {key: {'router-id': key, 'local-address': key,
                            'as': 1003, 'count': expected}}})


def blaster_log_path(tmp_path):
    return tmp_path / Bgpdump2Tester.LOG_NAME


def write_log(tmp_path, text, mode='a'):
    with open(blaster_log_path(tmp_path), mode) as f:
        f.write(text)


def test_facts_survive_the_poll_that_delivered_them(blaster_log, tmp_path):
    '''The walk time belongs to a `RIB for peer-index` line polls earlier.

    Reading only what was appended is what keeps a poll cheap, and parsing each
    appended chunk on its own would drop exactly this: `End-of-RIB` carries the
    generator's own measurement of a walk whose opening line is no longer in
    the text being read.
    '''
    reader = BlasterLogReader(str(blaster_log_path(tmp_path)))
    write_log(tmp_path, blaster_log(lines=9))

    first = reader.read()
    assert first['established'] is True
    assert first['ribs'][0]['ipv4_prefixes'] == 10000
    assert first['ribs'][0]['walk_time_s'] is None
    assert first['prefixes_sent'] is None

    write_log(tmp_path, ''.join(blaster_log().splitlines(keepends=True)[9:]))
    second = reader.read()

    assert second['walk_complete'] is True
    assert second['prefixes_sent'] == 10000
    assert second['ribs'][0]['walk_time_s'] == 0.011314
    assert second == parse_blaster_log(blaster_log())


def test_a_half_written_line_waits_for_its_newline(blaster_log, tmp_path):
    '''The blaster is writing while the controller reads.

    A partial line must not be consumed: the offset would move past it and the
    counters it carries would never be seen at all.
    '''
    reader = BlasterLogReader(str(blaster_log_path(tmp_path)))
    lines = blaster_log().splitlines(keepends=True)
    write_log(tmp_path, ''.join(lines[:12]) + lines[12][:20])

    assert reader.read()['ribs'][0]['walk_time_s'] is None

    write_log(tmp_path, lines[12][20:])

    assert reader.read()['ribs'][0]['walk_time_s'] == 0.011314


def test_a_log_that_cannot_be_read_is_not_a_silent_injector(tmp_path):
    '''"We could not ask" stays distinct from "it has sent nothing".

    offering_stats() turns the raised error into `tester_offering_error`, which
    is what puts `read_failures` in the run's artifact. Returning an empty
    reading instead would make a poll that never worked look like a generator
    that came up and stayed quiet.
    '''
    with pytest.raises(OSError):
        injector(tmp_path).get_offerings()


def test_a_replaced_log_does_not_carry_the_old_one_s_completion(blaster_log,
                                                                tmp_path):
    reader = BlasterLogReader(str(blaster_log_path(tmp_path)))
    write_log(tmp_path, blaster_log())
    assert reader.read()['walk_complete'] is True

    write_log(tmp_path, blaster_log(lines=9), mode='w')
    restarted = reader.read()

    assert restarted['walk_complete'] is False
    assert restarted['prefixes_sent'] is None


def test_a_new_log_that_is_not_smaller_is_still_a_new_log(blaster_log,
                                                          tmp_path):
    """A restarted injector's log can already be longer than the old offset.

    Size alone cannot see that: the reader would resume in the middle of the
    new file, never read the lines that open its session, and go on describing
    the previous log's session with whatever the tail of the new one adds. The
    inode is what distinguishes them, as it does in frr._get_EOR_from_log().

    The two fixtures are different injectors -- peer-index 4 and peer-index 3 --
    so a reader that carried the old facts across shows up as a session with
    two RIBs, which no bgperf injector has.
    """
    path = blaster_log_path(tmp_path)
    reader = BlasterLogReader(str(path))
    write_log(tmp_path, blaster_log(lines=9))
    assert [rib['peer_index'] for rib in reader.read()['ribs']] == [4]

    replacement = tmp_path / 'replacement'
    replacement.write_text(blaster_log('bgpdump2_blaster_one_poll.log'))
    replacement.replace(path)                 # longer than what was read
    restarted = reader.read()

    assert [rib['peer_index'] for rib in restarted['ribs']] == [3]
    assert restarted['prefixes_sent'] == 10000
    assert restarted['walk_complete'] is True


def test_the_poll_names_the_session_the_run_configured(blaster_log, tmp_path):
    write_log(tmp_path, blaster_log())

    offerings = injector(tmp_path, key='10.10.0.7').get_offerings()

    assert sorted(offerings) == ['10.10.0.7']
    offering = offerings['10.10.0.7']
    assert offering.established is True
    assert offering.offered == 10000
    assert offering.complete is True


def test_the_poll_carries_the_injectors_own_evidence(blaster_log, tmp_path):
    '''The two facts the controller cannot observe for itself.

    `octets` is counted on a successful write() while `offered` is counted at
    the encoder, so the pair says how much of what was encoded had reached the
    socket. `walk time` is the blaster's own measurement of the walk, which at
    MRT playback speeds is the only account of an injection that finished
    before the first poll looked.
    '''
    write_log(tmp_path, blaster_log())

    offering = injector(tmp_path).get_offerings()['10.10.0.3']

    assert offering.octets_on_wire == 259226
    assert offering.reported_send_duration_s == 0.011314


def test_an_injector_that_holds_less_than_asked_can_still_finish(blaster_log,
                                                                 tmp_path):
    '''`-T` caps the table as the MRT file is read, so an injector ends up with
    whatever that MRT peer's table has. Judged on counts, one that walked its
    whole RIB would never complete; its own report decides instead, and the
    shortfall stays visible as configured against expected.'''
    write_log(tmp_path, blaster_log())

    offering = injector(tmp_path, expected=25000).get_offerings()['10.10.0.3']

    assert offering.expected == 25000
    assert offering.configured == 10000
    assert offering.offered == 10000
    assert offering.complete is True


def test_an_injector_that_has_not_started_is_read_without_inventing_one(
        tmp_path):
    write_log(tmp_path, '')

    offering = injector(tmp_path).get_offerings()['10.10.0.3']

    assert offering.established is False
    assert offering.offered is None
    assert offering.complete is False


def test_blocked_write_evidence_is_absent_rather_than_zero(blaster_log,
                                                           tmp_path):
    '''bgpdump2 logs its writes only under `-t io`, which this run did not ask
    for. Reporting 0 would assert the injector was never blocked.'''
    write_log(tmp_path, blaster_log())

    offering = injector(tmp_path).get_offerings()['10.10.0.3']

    assert offering.tx_pending_bytes is None
    assert offering.pending_prefixes is None
    assert offering.blocked_writes is None
    assert offering.send_stalls is None


def test_an_injector_that_was_asked_reports_what_blocked_it(blaster_log,
                                                            tmp_path):
    write_log(tmp_path, blaster_log(IO_LOG))

    offering = injector(tmp_path, expected=500000).get_offerings()['10.10.0.3']

    assert offering.complete is True
    assert offering.blocked_writes == 13
    assert offering.send_stalls == 2


def test_a_write_read_across_two_polls_is_counted_once(blaster_log, tmp_path):
    '''These are the only facts here that accumulate rather than overwrite.

    Every other counter comes from a line that carries a running total, so
    re-reading one is harmless. These are incremented per line, so a reader
    that handed the same line over twice -- or fed a half-written one and then
    the whole one -- would report writes that never happened.
    '''
    poll = injector(tmp_path, expected=500000).get_offerings
    lines = blaster_log(IO_LOG).splitlines(keepends=True)

    # Through the first refused write, and no further.
    write_log(tmp_path, ''.join(lines[:63]))
    assert poll()['10.10.0.3'].blocked_writes == 1

    # A poll landing in the middle of the *next* refused write's line, which is
    # the case that would double-count if the half were taken as a record.
    assert lines[63].split(' ', 3)[3].startswith('Partial write')
    write_log(tmp_path, lines[63][:40])
    assert poll()['10.10.0.3'].blocked_writes == 1

    write_log(tmp_path, lines[63][40:] + ''.join(lines[64:]))
    offering = poll()['10.10.0.3']
    assert offering.blocked_writes == 13
    assert offering.send_stalls == 2


def test_bench_polls_this_generator():
    '''bench() polls only the generators that declare they can answer.'''
    assert Bgpdump2Tester.REPORTS_OFFERING is True


# --- asking for the IO log class, and what it costs -------------------------

class StubbedIndexInjector(Bgpdump2Tester):
    '''The injector, with only its two MRT-file lookups stood in for.

    `get_startup_cmd()` reads the MRT file through the container to pick a peer
    index and its ASN. Everything else it does is string assembly, which is
    what these tests are about.
    '''

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.target_ip = '10.10.255.254'

    def get_index_useful_neighbor(self, prefix_count):
        return 3

    def get_local_as(self, index):
        return 7018


def startup_cmd(tmp_path, **conf):
    tester = StubbedIndexInjector('mrt-injector0', str(tmp_path), dict(
        neighbors={'10.10.0.3': {'router-id': '10.10.0.3',
                                 'local-address': '10.10.0.3',
                                 'as': 1003, 'count': 10000}},
        **conf))
    return tester.get_startup_cmd()


def test_the_io_log_class_is_off_unless_the_run_asks_for_it(tmp_path):
    '''It is evidence that costs the measurement beside it.

    The class logs every BGP message the injector *receives*, and the target
    re-advertises to each tester what it learns from the others. Those lines
    arrive in the blaster's event loop while it is still walking, so they
    lengthen the walk it is timing: measured over three runs each on a
    2-injector 10,000-prefix run, the injector whose walk overlapped the echo
    reported 0.01122/0.01128/0.01125s without the flag and
    0.01763/0.01756/0.01751s with it.
    '''
    assert ' -t io ' not in startup_cmd(tmp_path)
    assert ' -t io ' not in startup_cmd(tmp_path, **{'trace-io': False})
    assert ' -t io ' in startup_cmd(tmp_path, **{'trace-io': True})


def trace_io_warning(capsys, tester_trace_io, testers):
    from argparse import Namespace
    import bgperf2
    bgperf2.warn_if_trace_io_reaches_no_generator(
        Namespace(tester_trace_io=tester_trace_io), {'testers': testers})
    return capsys.readouterr().out


BGPDUMP2_TESTER = {'mrt_injector': 'bgpdump2', 'trace-io': True}


def test_a_flag_that_reaches_a_bgpdump2_injector_says_nothing(capsys):
    assert trace_io_warning(capsys, True, [BGPDUMP2_TESTER]) == ''
    # And a run that never asked is not warned at either.
    assert trace_io_warning(capsys, False, [{'type': 'bird'}]) == ''


def test_a_flag_that_reaches_no_generator_is_said_out_loud(capsys):
    '''Every way the flag can be a no-op ends in the same artifact.

    `trace-io` is written only onto MRT testers and read only by bgpdump2, and
    a `-f` scenario bypasses the generator that writes it at all. Each of these
    finishes with `backpressure: available: false` carrying the same reason a
    genuinely mute generator gives, so without this the operator cannot tell
    'I asked and it could not answer' from 'nothing was asked'.
    '''
    for testers in (
            [{'type': 'bird', 'name': 'tester'}],            # -g bird
            [{'mrt_injector': 'gobgp', 'trace-io': True}],   # another injector
            [{'name': 'from-a-scenario-file'}],              # bench -f
            None,                                            # no testers key
    ):
        assert 'does nothing for this run' in trace_io_warning(
            capsys, True, testers)


def test_the_blaster_still_runs_line_buffered_either_way(tmp_path):
    '''Redirected stdout is block-buffered and nothing ends this process, so
    without stdbuf the log stays empty for the whole run.'''
    for conf in ({}, {'trace-io': True}):
        assert 'stdbuf -oL -eL /usr/local/sbin/bgpdump2 --blaster' \
            in startup_cmd(tmp_path, **conf)
