'''Docker-free tests for BIRD generator instrumentation.

Two layers meet here.  `bird.parse_protocols`/`tester_offering` read what the
generator says about itself, and `measurements.TesterEventRecorder` turns those
polls into the lifecycle vocabulary.  Both are exercised against real captures
from `bgperf/bird:latest` (2.19) and `bgperf/bird:3.3.2`, because the CLI format
differs between the two series that `prepare` builds.
'''
import pytest

from bird import (SESSION_MARKER, parse_protocols, split_session_output,
                  tester_offering)
from tester import BIRDTester
from measurements import (
    EventKind,
    EventOrderError,
    EventPhase,
    LifecycleEvent,
    MeasurementEventError,
    TesterEventRecorder,
    TesterOffering,
    tester_metrics,
)


# --- the generator's own CLI ------------------------------------------------

def test_bird2_tester_reports_what_it_offered(fixture_text):
    offering = tester_offering(
        fixture_text('bird2_tester_show_protocols_all.txt'))

    assert offering['established'] is True
    assert offering['sessions'] == 1
    # 100 prefixes configured as static routes, all exported to the peer.
    assert offering['offered'] == 100
    assert offering['exported'] == 100
    assert offering['configured'] == 100


def test_bird3_accepted_is_read_by_name_not_position(fixture_text):
    '''The regression the parser exists for.

    BIRD 3 inserts 'RX limit' and 'limit' into the route-change-stats table, so
    the column that is `accepted` on 2.19 is `RX limit` on 3.3.2.  A positional
    read does not raise -- it returns a different, plausible number.
    '''
    protocols = parse_protocols(fixture_text('bird3_show_protocols_all.txt'))
    stats = protocols['dynbgp1']['channels']['ipv4']['stats']['Export updates']

    assert stats['accepted'] == 200
    assert 'RX limit' in stats
    # BIRD prints '---' where a counter does not apply; that is absent
    # evidence, not zero.
    assert stats['RX limit'] is None


def test_both_bird_series_parse_the_same_way(fixture_text):
    two = parse_protocols(fixture_text('bird2_tester_show_protocols_all.txt'))
    three = parse_protocols(fixture_text('bird3_show_protocols_all.txt'))

    assert two['bgp1']['bgp_state'] == 'Established'
    assert two['bgp1']['neighbor_address'] == '10.10.255.254'
    assert three['dynbgp1']['bgp_state'] == 'Established'
    assert three['dynbgp1']['neighbor_address'] == '10.10.0.2'
    assert two['bgp1']['channels']['ipv4']['routes']['exported'] == 100
    assert three['dynbgp1']['channels']['ipv4']['routes']['exported'] == 200


def test_only_bird3_exposes_blocked_write_evidence(fixture_text):
    two = tester_offering(fixture_text('bird2_tester_show_protocols_all.txt'))
    three = parse_protocols(fixture_text('bird3_show_protocols_all.txt'))

    # 2.19 has no TX-pending field at all, so the answer is 'unknown', which
    # must stay distinguishable from 'measured, and it was zero'.
    assert two['tx_pending_bytes'] is None
    assert three['dynbgp1']['tx_pending_bytes'] == 0
    assert three['dynbgp1']['channels']['ipv4']['pending_prefixes'] == 0


def test_non_bgp_protocols_are_not_counted_as_sessions(fixture_text):
    protocols = parse_protocols(
        fixture_text('bird2_tester_show_protocols_all.txt'))

    assert protocols['device1']['proto'] == 'Device'
    assert protocols['static1']['proto'] == 'Static'
    # The static protocol also has an ipv4 channel with export counters; only
    # the BGP session's counters describe what reached the peer.
    assert tester_offering(
        fixture_text('bird2_tester_show_protocols_all.txt'))['sessions'] == 1


def test_a_filtered_channel_shifts_the_routes_line():
    '''`Routes:` gains a `filtered` term when the channel has a filter.'''
    text = '''bgp1       BGP        ---        up     20:53:11.819  Established
  BGP state:          Established
  Channel ipv4
    Routes:         3 imported, 7 filtered, 11 exported, 3 preferred
'''
    routes = parse_protocols(text)['bgp1']['channels']['ipv4']['routes']

    assert routes == {'imported': 3, 'filtered': 7, 'exported': 11,
                      'preferred': 3}


def test_a_stats_row_that_does_not_match_its_header_is_skipped():
    '''A row with the wrong width means an unrecognised format.

    Zipping it against the header anyway would publish a real number under the
    wrong name, which nothing downstream could detect.
    '''
    text = '''bgp1       BGP        ---        up     20:53:11.819  Established
  Channel ipv4
    Route change stats:     received   rejected   accepted
      Export updates:              1          2          3          4
'''
    assert parse_protocols(text)['bgp1']['channels']['ipv4']['stats'] == {}


def test_the_banner_and_table_header_are_not_protocols():
    text = '''BIRD 2.19.0 ready.
Name       Proto      Table      State  Since         Info
device1    Device     ---        up     20:53:10.965
'''
    assert list(parse_protocols(text)) == ['device1']


def test_channels_are_kept_apart():
    text = '''bgp1       BGP        ---        up     20:53:11.819  Established
  Channel ipv4
    Routes:         1 imported, 2 exported, 1 preferred
  Channel ipv6
    Routes:         30 imported, 40 exported, 30 preferred
'''
    channels = parse_protocols(text)['bgp1']['channels']

    assert channels['ipv4']['routes']['exported'] == 2
    assert channels['ipv6']['routes']['exported'] == 40
    assert tester_offering(text, channel='ipv6')['exported'] == 40


def test_unreadable_output_reports_no_evidence_rather_than_zero():
    offering = tester_offering('')

    assert offering['established'] is False
    assert offering['offered'] is None
    assert offering['configured'] is None


# --- polls to lifecycle events ----------------------------------------------

def offering(established=True, expected=100, offered=0, **kwargs):
    return TesterOffering(established=established, expected=expected,
                          offered=offered, **kwargs)


def kinds(recorder):
    return [event.kind for event in recorder.events]


def metrics(recorder, origin_s=0.0, producer='tester'):
    '''tester_metrics over the recorder's events plus the controller's origin.

    bench() merges the monitor and tester recorders before deriving anything;
    the origin belongs to the controller and no tester emits its own.
    '''
    origin = LifecycleEvent(EventKind.BENCH_CLOCK_STARTED, origin_s,
                            'controller', EventPhase.SETUP)
    return tester_metrics([origin] + list(recorder.events), producer)


def test_readiness_waits_for_the_last_session_not_the_first():
    r = TesterEventRecorder(0.0, 'tester', sample_interval_s=1.0)

    r.observe(1.0, {'a': offering(established=True),
                    'b': offering(established=False)})
    assert EventKind.TESTER_SESSION_READY not in kinds(r)

    r.observe(2.0, {'a': offering(established=True),
                    'b': offering(established=True)})
    ready = [e for e in r.events if e.kind == EventKind.TESTER_SESSION_READY]
    assert len(ready) == 1
    assert ready[0].monotonic_s == 2.0


def test_startup_is_measured_from_the_bench_clock():
    r = TesterEventRecorder(0.0, 'tester')
    r.observe(3.0, {'a': offering()})

    assert metrics(r)['tester_startup_s'] == 3.0


def test_metrics_reject_events_with_no_bench_clock():
    '''A tester recorder alone has no origin; deriving from it is a wiring
    mistake, and a null startup interval would hide it.'''
    r = TesterEventRecorder(0.0, 'tester')
    r.observe(1.0, {'a': offering(offered=100)})

    with pytest.raises(MeasurementEventError):
        tester_metrics(r.events, 'tester')


def test_completion_waits_for_the_slowest_session():
    '''One finished peer must not report the whole generator complete.'''
    r = TesterEventRecorder(0.0, 'tester', sample_interval_s=1.0)

    r.observe(1.0, {'a': offering(offered=100), 'b': offering(offered=40)})
    assert EventKind.TESTER_COMPLETE not in kinds(r)

    r.observe(2.0, {'a': offering(offered=100), 'b': offering(offered=100)})
    complete = [e for e in r.events if e.kind == EventKind.TESTER_COMPLETE]
    assert len(complete) == 1
    assert complete[0].monotonic_s == 2.0
    assert complete[0].counters['offered_prefixes'] == 200
    assert complete[0].counters['expected_prefixes'] == 200


def test_a_stalled_peer_leaves_the_run_without_an_injection_interval():
    r = TesterEventRecorder(0.0, 'tester')
    for t in range(1, 6):
        r.observe(float(t), {'a': offering(offered=100),
                             'b': offering(offered=40)})

    m = metrics(r)
    # No completion evidence, so no injection interval and no rate -- not a
    # value derived from when the monitor happened to stop changing.
    assert m['injection_s'] is None
    assert m['offered_prefixes'] is None
    assert m['offered_rate_pps'] is None


def test_injection_runs_from_first_update_to_completion():
    r = TesterEventRecorder(0.0, 'tester', sample_interval_s=1.0)
    r.observe(1.0, {'a': offering(offered=0)})
    r.observe(2.0, {'a': offering(offered=30)})
    r.observe(3.0, {'a': offering(offered=60)})
    r.observe(6.0, {'a': offering(offered=100)})

    m = metrics(r)
    assert m['injection_s'] == 4.0
    assert m['offered_prefixes'] == 100
    # 30 prefixes were already on the wire when the first poll saw a nonzero
    # count, so only 70 crossed the measured window. Dividing the running total
    # by it would report 25 pps for a generator that managed 17.5.
    assert m['offered_rate_pps'] == pytest.approx(17.5)


def test_an_injection_shorter_than_one_poll_has_no_rate():
    '''0.0s is an unresolved interval, not an infinite send rate.'''
    r = TesterEventRecorder(0.0, 'tester', sample_interval_s=1.0)
    r.observe(1.0, {'a': offering(offered=100)})

    m = metrics(r)
    assert m['injection_s'] == 0.0
    assert m['offered_rate_pps'] is None


def test_a_first_update_needs_a_nonzero_count():
    r = TesterEventRecorder(0.0, 'tester')
    r.observe(1.0, {'a': offering(offered=0)})

    assert EventKind.TESTER_FIRST_UPDATE not in kinds(r)


def test_unreadable_counters_are_never_read_as_completion():
    r = TesterEventRecorder(0.0, 'tester')
    r.observe(1.0, {'a': TesterOffering(established=True, expected=100,
                                        offered=None)})

    assert EventKind.TESTER_FIRST_UPDATE not in kinds(r)
    assert EventKind.TESTER_COMPLETE not in kinds(r)


def test_the_last_update_is_the_last_increase_and_appears_once():
    r = TesterEventRecorder(0.0, 'tester')
    r.observe(1.0, {'a': offering(offered=10)})
    r.observe(2.0, {'a': offering(offered=50)})
    r.observe(3.0, {'a': offering(offered=50)})
    r.observe(4.0, {'a': offering(offered=50)})

    last = [e for e in r.events if e.kind == EventKind.TESTER_LAST_UPDATE]
    assert len(last) == 1
    assert last[0].monotonic_s == 2.0


def test_events_come_back_in_monotonic_order():
    r = TesterEventRecorder(0.0, 'tester')
    r.observe(1.0, {'a': offering(established=False, offered=0)})
    r.observe(2.0, {'a': offering(offered=10)})
    r.observe(3.0, {'a': offering(offered=100)})

    times = [e.monotonic_s for e in r.events]
    assert times == sorted(times)
    assert kinds(r) == [
        EventKind.TESTER_SESSION_READY,
        EventKind.TESTER_FIRST_UPDATE,
        EventKind.TESTER_LAST_UPDATE,
        EventKind.TESTER_COMPLETE,
    ]


def test_every_tester_event_records_the_poll_resolution():
    r = TesterEventRecorder(0.0, 'tester', sample_interval_s=0.5)
    r.observe(1.0, {'a': offering(offered=100)})

    assert all(e.details['sample_interval_s'] == 0.5 for e in r.events)


def test_a_first_poll_is_only_as_sharp_as_the_time_since_the_clock_started():
    '''Everything the generator did before the instrument arrived is invisible.

    bgpdump2's whole 10,000-prefix walk takes about a millisecond, so its
    first_update and complete land on the same first poll. What bounds that is
    not the cadence -- there has been no previous poll -- it is the whole
    interval since the run's clock started.
    '''
    r = TesterEventRecorder(0.0, 'tester', sample_interval_s=1.0)
    r.observe(4.0, {'a': offering(offered=100)})

    assert all(e.details['poll_resolution_s'] == 4.0 for e in r.events)
    m = metrics(r)
    assert m['startup_resolution_s'] == 4.0
    assert m['injection_resolution_s'] == 4.0


def test_the_resolution_is_the_gap_achieved_not_the_cadence_asked_for():
    '''A poll costs a read before it waits, so the real cadence is wider.

    Publishing the nominal interval understates the resolution by the cost of
    the read -- the one direction that matters, since this number is what says
    a 0.0s injection is unresolved rather than instant.
    '''
    r = TesterEventRecorder(0.0, 'tester', sample_interval_s=1.0)
    r.observe(1.0, {'a': offering(established=False, offered=0)})
    r.observe(2.6, {'a': offering(offered=100)})

    by_kind = {e.kind: e for e in r.events}
    assert by_kind[EventKind.TESTER_SESSION_READY] \
        .details['poll_resolution_s'] == pytest.approx(1.6)
    assert by_kind[EventKind.TESTER_COMPLETE] \
        .details['poll_resolution_s'] == pytest.approx(1.6)
    # The nominal cadence is still recorded beside it: it is what the loop was
    # asked for, and the gap is what it managed.
    assert by_kind[EventKind.TESTER_COMPLETE].details['sample_interval_s'] == 1.0


def test_a_gap_shorter_than_the_requested_cadence_does_not_sharpen_it():
    '''The requested interval is a floor on the resolution, never beaten.

    The loop stamps a sample, reads, and only then waits, so it cannot look
    twice inside one interval. A synthetic stream that appears to is reported
    at the cadence asked for rather than at a sharpness no real poll has.
    '''
    r = TesterEventRecorder(0.0, 'tester', sample_interval_s=1.0)
    r.observe(5.0, {'a': offering(offered=10)})
    r.observe(5.1, {'a': offering(offered=100)})

    complete = [e for e in r.events
                if e.kind == EventKind.TESTER_COMPLETE][0]
    assert complete.details['poll_resolution_s'] == 1.0


def test_the_published_resolution_is_the_coarsest_bounding_poll():
    '''An interval is only as sharp as the wider of the two polls bounding it.'''
    r = TesterEventRecorder(0.0, 'tester', sample_interval_s=1.0)
    r.observe(1.0, {'a': offering(established=False, offered=0)})
    r.observe(2.0, {'a': offering(offered=10)})
    r.observe(5.5, {'a': offering(offered=100)})

    assert metrics(r)['injection_resolution_s'] == pytest.approx(3.5)


def test_a_late_first_poll_does_not_widen_the_injection_bound():
    '''Each interval is qualified by the polls that bound it, not by the worst.

    The bench clock starts before the testers are launched, so the first poll
    is many seconds after the origin and `tester_session_ready` carries all of
    it. That is the honest bound on `tester_startup_s` and says nothing about
    an injection two ordinary polls later -- the usual BIRD shape, where the
    sessions are up before the first export is counted.
    '''
    r = TesterEventRecorder(0.0, 'tester', sample_interval_s=1.0)
    r.observe(30.0, {'a': offering(offered=0)})
    r.observe(31.0, {'a': offering(offered=0)})
    r.observe(32.0, {'a': offering(offered=100)})

    m = metrics(r)
    assert m['startup_resolution_s'] == 30.0
    assert m['injection_resolution_s'] == 1.0


def test_a_hand_built_stream_carries_no_resolution_rather_than_a_default():
    '''Events not produced by a recorder state nothing about how they were seen.'''
    events = [
        LifecycleEvent(EventKind.BENCH_CLOCK_STARTED, 0.0, 'controller',
                       EventPhase.SETUP),
        LifecycleEvent(EventKind.TESTER_FIRST_UPDATE, 1.0, 'tester',
                       EventPhase.INJECTION, counters={'offered_prefixes': 1}),
        LifecycleEvent(EventKind.TESTER_COMPLETE, 3.0, 'tester',
                       EventPhase.INJECTION, counters={'offered_prefixes': 9}),
    ]

    m = tester_metrics(events, 'tester')
    assert m['injection_resolution_s'] is None
    assert m['startup_resolution_s'] is None


# --- backpressure ------------------------------------------------------------

def test_a_generator_with_no_counter_records_unavailable_not_zero():
    r = TesterEventRecorder(0.0, 'tester')
    r.observe(1.0, {'a': offering(offered=100)})

    assert r.backpressure['available'] is False
    assert 'reason' in r.backpressure
    assert 'max_tx_pending_bytes' not in r.backpressure
    complete = [e for e in r.events if e.kind == EventKind.TESTER_COMPLETE][0]
    assert complete.details['backpressure']['available'] is False


def test_reported_blocked_writes_are_kept_at_their_maximum():
    r = TesterEventRecorder(0.0, 'tester')
    r.observe(1.0, {'a': offering(offered=10, tx_pending_bytes=4096,
                                  pending_prefixes=7)})
    r.observe(2.0, {'a': offering(offered=100, tx_pending_bytes=0,
                                  pending_prefixes=0)})

    assert r.backpressure == {'available': True,
                              'max_tx_pending_bytes': 4096,
                              'max_pending_prefixes': 7}


# --- what the generator says about itself -------------------------------------

def test_a_generator_that_measures_its_own_send_publishes_it_beside_the_polled_one():
    """A self-measured send is evidence a poll cannot supply, not a better
    version of the polled interval: a different clock and the generator's own
    definition of sending. Both are published, and neither replaces the
    other."""
    r = TesterEventRecorder(0.0, 'tester', sample_interval_s=1.0)
    r.observe(1.0, {'a': offering(offered=100, octets_on_wire=2600,
                                  reported_send_duration_s=0.001030)})

    m = metrics(r)
    assert m['reported_injection_s'] == 0.001030
    assert m['octets_on_wire'] == 2600
    # The whole table was already offered when the instrument first looked, so
    # the polled interval is 0.0 and says only 'inside one look'. That is the
    # case the generator's own number exists to resolve.
    assert m['injection_s'] == 0.0
    assert m['offered_rate_pps'] is None


def test_the_generators_own_duration_is_the_slowest_session_not_their_sum():
    """Two sessions send at the same time, so their durations do not add. The
    longest is the pessimistic answer, matching how everything else here
    aggregates -- and it stays a lower bound on the container's whole send
    span, since sessions that started apart span more than the longer one."""
    r = TesterEventRecorder(0.0, 'tester', sample_interval_s=1.0)
    r.observe(1.0, {'a': offering(offered=100, reported_send_duration_s=0.25),
                    'b': offering(offered=100, reported_send_duration_s=1.5)})

    assert metrics(r)['reported_injection_s'] == 1.5


def test_a_send_duration_from_only_some_sessions_is_not_published():
    """One session's walk is not the container's send. Publishing the only
    number that was legible would report the fastest peer's duration as the
    generator's, which is the failure this class aggregates to avoid."""
    r = TesterEventRecorder(0.0, 'tester', sample_interval_s=1.0)
    r.observe(1.0, {'a': offering(offered=100, reported_send_duration_s=0.25),
                    'b': offering(offered=100)})

    assert metrics(r)['reported_injection_s'] is None


def test_a_send_duration_is_not_carried_over_from_an_earlier_poll():
    '''Found in review. The completion event says what was true at the poll
    that saw completion, so its evidence has to come from that poll. A
    duration held on the recorder from an earlier, fully legible look would be
    published against a poll that could not read it -- one event carrying two
    polls' evidence, and the rule above ("not from only some sessions") broken
    across time instead of within one look.'''
    r = TesterEventRecorder(0.0, 'tester', sample_interval_s=1.0)
    # Both sessions report, but completion is held: no update seen yet.
    r.observe(1.0, {'a': offering(offered=None, reported_send_duration_s=0.25),
                    'b': offering(offered=None, reported_send_duration_s=1.5)})
    # Now they complete, with only one session's duration legible.
    r.observe(2.0, {'a': offering(offered=100, reported_send_duration_s=0.25),
                    'b': offering(offered=100)})

    assert EventKind.TESTER_COMPLETE in kinds(r)
    assert metrics(r)['reported_injection_s'] is None


def test_wire_side_octets_are_summed_only_when_every_session_answered():
    """Same rule as the prefix counts, for the same reason: a total covering
    only the sessions that answered reads as a small transfer rather than as a
    partial reading, and nothing downstream could tell those apart."""
    r = TesterEventRecorder(0.0, 'tester', sample_interval_s=1.0)
    r.observe(1.0, {'a': offering(offered=100, octets_on_wire=2600),
                    'b': offering(offered=100, octets_on_wire=1400)})
    assert metrics(r)['octets_on_wire'] == 4000

    partial = TesterEventRecorder(0.0, 'tester', sample_interval_s=1.0)
    partial.observe(1.0, {'a': offering(offered=100, octets_on_wire=2600),
                          'b': offering(offered=100)})
    assert metrics(partial)['octets_on_wire'] is None


def test_the_generators_own_evidence_is_read_at_completion():
    """Both numbers are read from the poll that saw completion -- the octets
    are the count that pairs with `offered_prefixes`, off the same line of the
    generator's counters. Without a completion there is nothing to pair them
    with, and neither is published."""
    r = TesterEventRecorder(0.0, 'tester', sample_interval_s=1.0)
    r.observe(1.0, {'a': offering(offered=40, octets_on_wire=1000,
                                  reported_send_duration_s=0.5)})

    m = metrics(r)
    assert EventKind.TESTER_COMPLETE not in kinds(r)
    assert m['reported_injection_s'] is None
    assert m['octets_on_wire'] is None

    r.observe(2.0, {'a': offering(offered=100, octets_on_wire=2600,
                                  reported_send_duration_s=0.5)})
    assert metrics(r)['octets_on_wire'] == 2600


# --- rejected input ----------------------------------------------------------

def test_samples_must_move_forward():
    r = TesterEventRecorder(10.0, 'tester')
    r.observe(11.0, {'a': offering()})

    with pytest.raises(EventOrderError):
        r.observe(10.5, {'a': offering()})


def test_a_sample_cannot_precede_the_bench_clock():
    r = TesterEventRecorder(10.0, 'tester')

    with pytest.raises(EventOrderError):
        r.observe(9.0, {'a': offering()})


def test_a_sample_needs_at_least_one_session():
    r = TesterEventRecorder(0.0, 'tester')

    with pytest.raises(MeasurementEventError):
        r.observe(1.0, {})


def test_counts_must_be_non_negative_integers():
    with pytest.raises(ValueError):
        TesterOffering(established=True, expected=-1)
    with pytest.raises(ValueError):
        TesterOffering(established=True, expected=1, offered=-5)
    with pytest.raises(TypeError):
        TesterOffering(established='yes', expected=1)
    with pytest.raises(ValueError):
        TesterOffering(established=True, expected=1, octets_on_wire=-1)


def test_a_self_measured_send_duration_must_be_a_non_negative_number():
    '''The only field here that is not a count. A negative or non-finite one
    is a parse that went wrong, and it would be published as a measurement.'''
    for bad in (-0.5, float('nan'), float('inf'), '1.0', True):
        with pytest.raises((ValueError, TypeError)):
            TesterOffering(established=True, expected=1,
                           reported_send_duration_s=bad)
    assert TesterOffering(established=True, expected=1,
                          reported_send_duration_s=0).reported_send_duration_s \
        == 0.0


# --- defects found in review -------------------------------------------------

def test_a_partial_read_is_not_published_as_a_shortfall():
    '''One session unreadable must not produce `50 of 200 offered`.

    Summing only the sessions that answered against an `expected` covering all
    of them looks exactly like a generator that fell behind, and nothing
    downstream could tell the difference.
    '''
    r = TesterEventRecorder(0.0, 'tester')
    r.observe(1.0, {'a': offering(offered=50),
                    'b': TesterOffering(established=True, expected=100,
                                        offered=None)})

    assert EventKind.TESTER_FIRST_UPDATE not in kinds(r)
    assert EventKind.TESTER_COMPLETE not in kinds(r)

    r.observe(2.0, {'a': offering(offered=50), 'b': offering(offered=50)})
    first = [e for e in r.events if e.kind == EventKind.TESTER_FIRST_UPDATE][0]
    assert first.counters['offered_prefixes'] == 100
    assert first.counters['sessions_measured'] == 2


def test_events_record_how_many_sessions_were_legible():
    r = TesterEventRecorder(0.0, 'tester')
    r.observe(1.0, {'a': offering(established=True, offered=0),
                    'b': TesterOffering(established=True, expected=100,
                                        offered=None)})

    ready = [e for e in r.events if e.kind == EventKind.TESTER_SESSION_READY][0]
    assert ready.counters['sessions'] == 2
    assert ready.counters['sessions_measured'] == 1
    assert 'offered_prefixes' not in ready.counters


def test_a_generator_with_nothing_to_send_never_reports_completion():
    '''`expected == 0` used to satisfy `offered >= expected` on the first
    poll, emitting tester_complete before the session was even up.'''
    r = TesterEventRecorder(0.0, 'tester')
    r.observe(1.0, {'a': TesterOffering(established=False, expected=0,
                                        offered=0)})

    assert kinds(r) == []


def test_completion_needs_an_established_session():
    r = TesterEventRecorder(0.0, 'tester')
    r.observe(1.0, {'a': offering(established=False, offered=100)})

    assert EventKind.TESTER_COMPLETE not in kinds(r)


def test_a_queue_depth_alone_still_counts_as_backpressure_evidence():
    '''BIRD reports TX-pending bytes and pending prefixes from different parts
    of the output, so one can be present without the other.'''
    r = TesterEventRecorder(0.0, 'tester')
    r.observe(1.0, {'a': offering(offered=10, pending_prefixes=5000)})

    assert r.backpressure == {'available': True, 'max_pending_prefixes': 5000}


def test_a_broken_clock_origin_is_rejected():
    '''NaN compares false against everything, so it would silently disable the
    "sample precedes bench_clock_started" guard.'''
    with pytest.raises(ValueError):
        TesterEventRecorder(float('nan'), 'tester')
    with pytest.raises(ValueError):
        TesterEventRecorder(float('inf'), 'tester')


def test_a_dynamic_neighbor_template_is_not_a_session(fixture_text):
    '''`protocol bgp everything { neighbor range ... }` sits in Passive for the
    whole run. Counting it means the generator never reports itself ready.'''
    offering_state = tester_offering(
        fixture_text('bird3_show_protocols_all.txt'))

    assert offering_state['sessions'] == 3
    assert offering_state['established'] is True


def test_a_session_that_is_not_up_yet_still_counts():
    '''The opposite hazard: dropping a peer that has not come up would let the
    fast ones declare the generator ready.'''
    text = '''bgp1       BGP        ---        up     20:53:11.819  Established
  BGP state:          Established
    Neighbor address: 10.0.0.1
bgp2       BGP        ---        down   20:53:11.819  Error: Invalid next hop
  BGP state:          Down
    Neighbor address: 10.0.0.2
'''
    state = tester_offering(text)

    assert state['sessions'] == 2
    assert state['established'] is False


def test_the_rate_covers_only_the_interval_it_is_divided_by():
    '''Numerator and denominator must describe the same window.'''
    r = TesterEventRecorder(0.0, 'tester', sample_interval_s=1.0)
    r.observe(1.0, {'a': offering(expected=1000, offered=900)})
    r.observe(2.0, {'a': offering(expected=1000, offered=1000)})

    # 900 were already sent before the window opened; 100 crossed it in 1s.
    assert metrics(r)['offered_rate_pps'] == pytest.approx(100.0)


def test_a_dropped_session_is_rejected_rather_than_silently_completing():
    '''Omitting a key would let `all(complete)` pass over the survivors.'''
    r = TesterEventRecorder(0.0, 'tester')
    r.observe(1.0, {'a': offering(offered=10), 'b': offering(offered=0)})

    with pytest.raises(MeasurementEventError):
        r.observe(2.0, {'a': offering(offered=100)})

    assert EventKind.TESTER_COMPLETE not in kinds(r)


def test_a_new_session_appearing_later_is_rejected_too():
    r = TesterEventRecorder(0.0, 'tester')
    r.observe(1.0, {'a': offering(offered=10)})

    with pytest.raises(MeasurementEventError):
        r.observe(2.0, {'a': offering(offered=100), 'b': offering(offered=0)})


def test_polling_past_completion_cannot_reorder_the_last_update():
    '''The monitor decides when a run ends, so the tester keeps being polled
    after it finishes. A cumulative counter that moves again must not produce a
    `tester_last_update` sorted after `tester_complete`.'''
    r = TesterEventRecorder(0.0, 'tester')
    r.observe(1.0, {'a': offering(offered=100)})
    r.observe(2.0, {'a': offering(offered=140)})

    assert kinds(r) == [
        EventKind.TESTER_SESSION_READY,
        EventKind.TESTER_FIRST_UPDATE,
        EventKind.TESTER_LAST_UPDATE,
        EventKind.TESTER_COMPLETE,
    ]
    last = [e for e in r.events if e.kind == EventKind.TESTER_LAST_UPDATE][0]
    complete = [e for e in r.events if e.kind == EventKind.TESTER_COMPLETE][0]
    assert last.monotonic_s <= complete.monotonic_s


def test_the_table_the_generator_loaded_is_recorded_beside_the_expected_one():
    '''`configured` cross-checks that the generator got the workload it was
    given; it is never the yardstick completion is judged against.'''
    r = TesterEventRecorder(0.0, 'tester')
    r.observe(1.0, {'a': TesterOffering(established=True, expected=100,
                                        offered=100, configured=100)})

    complete = [e for e in r.events if e.kind == EventKind.TESTER_COMPLETE][0]
    assert complete.counters['expected_prefixes'] == 100
    assert complete.counters['configured_prefixes'] == 100


def test_an_unreadable_table_size_is_simply_absent():
    r = TesterEventRecorder(0.0, 'tester')
    r.observe(1.0, {'a': offering(offered=100)})

    complete = [e for e in r.events if e.kind == EventKind.TESTER_COMPLETE][0]
    assert 'configured_prefixes' not in complete.counters


def test_a_session_level_queue_depth_survives_an_unreadable_channel():
    '''`TX pending` is printed in the session block, not the channel block.'''
    text = '''bgp1  BGP  ---  up  20:53:11.819  Established
  BGP state:          Established
    Neighbor address: 10.0.0.1
    TX pending:       99999 bytes
'''
    assert tester_offering(text)['tx_pending_bytes'] == 99999


def test_a_session_whose_channel_is_down_is_not_summed_away(fixture_text):
    """A DOWN channel prints no `Routes:` and no stats at all.

    Summing the sessions that did answer gives a number indistinguishable from
    a generator that fell behind, against an `expected` that still covers the
    unread one. The guard belongs here, not only in the recorder.
    """
    text = '''bgp1       BGP        ---        up     20:53:11.819  Established
  BGP state:          Established
    Neighbor address: 10.0.0.1
  Channel ipv4
    State:          UP
    Routes:         0 imported, 100 exported, 0 preferred
    Route change stats:     received   rejected   filtered    ignored   accepted
      Export updates:            100          0          0        ---        100
bgp2       BGP        ---        start  20:53:11.819  Connect
  BGP state:          Connect
    Neighbor address: 10.0.0.2
  Channel ipv4
    State:          DOWN
    Table:          master4
'''
    state = tester_offering(text)

    assert state['sessions'] == 2
    assert state['sessions_measured'] == 1
    assert state['offered'] is None
    assert state['exported'] is None


def test_a_partly_unreadable_static_table_reports_no_configured_size():
    text = '''static1    Static     master4    up     20:53:10.965
  Channel ipv4
    Routes:         100 imported, 0 exported, 100 preferred
static2    Static     master4    up     20:53:10.965
  Channel ipv4
    State:          DOWN
'''
    assert tester_offering(text)['configured'] is None


def test_a_counter_reset_mid_run_yields_no_rate_rather_than_a_negative_one():
    """BIRD clears a protocol's route-change stats when it restarts, so the
    count at completion can be below the count at the first update."""
    r = TesterEventRecorder(0.0, 'tester', sample_interval_s=1.0)
    r.observe(1.0, {'a': offering(expected=100, offered=90)})
    r.observe(2.0, {'a': offering(expected=100, offered=100)})
    # Rebuild the pair by hand: a real reset would be caught by the recorder's
    # own monotonic bookkeeping, but tester_metrics must not trust its inputs.
    events = [e for e in r.events]
    first = [e for e in events if e.kind == EventKind.TESTER_FIRST_UPDATE][0]
    complete = [e for e in events if e.kind == EventKind.TESTER_COMPLETE][0]
    swapped = [
        LifecycleEvent(EventKind.BENCH_CLOCK_STARTED, 0.0, 'controller',
                       EventPhase.SETUP),
        LifecycleEvent(first.kind, first.monotonic_s, 'tester', first.phase,
                       counters={'offered_prefixes': 500}),
        complete,
    ]

    m = tester_metrics(swapped, 'tester')
    assert m['offered_rate_pps'] is None


# --- reading the running containers ------------------------------------------

class StubbedBIRDTester(BIRDTester):
    '''A BIRD tester whose container reads are canned.

    Only `local()` is replaced, so the command that would be exec'd and the
    parsing of its reply are the real ones.
    '''

    def __init__(self, host_dir, conf, reply=''):
        super().__init__('t1', str(host_dir), conf, image='bgperf/bird')
        self._reply = reply
        self.execs = []

    def local(self, cmd, **kwargs):
        self.execs.append(cmd)
        if isinstance(self._reply, Exception):
            raise self._reply
        return self._reply.encode('utf-8')


def peers(*ids, paths=100):
    return {'neighbors': {i: {'router-id': i, 'paths': ['10.0.0.0/32'] * paths}
                          for i in ids}}


def sessions_reply(*bodies):
    return ''.join('{0}{1}\n{2}\n'.format(SESSION_MARKER, key, text)
                   for key, text in bodies)


def test_sections_are_split_on_their_marker():
    text = sessions_reply(('10.0.0.1', 'first'), ('10.0.0.2', 'second\nmore'))

    assert split_session_output(text) == {
        '10.0.0.1': 'first',
        '10.0.0.2': 'second\nmore',
    }


def test_output_before_the_first_marker_belongs_to_no_session():
    '''A shell that greets before the loop starts must not have its banner
    parsed as the first peer's answer.'''
    text = 'noise from the shell\n' + sessions_reply(('10.0.0.1', 'first'))

    assert split_session_output(text) == {'10.0.0.1': 'first'}


def test_one_poll_covers_every_configured_peer(tmp_path, fixture_text):
    capture = fixture_text('bird2_tester_show_protocols_all.txt')
    tester = StubbedBIRDTester(
        tmp_path, peers('10.0.0.1', '10.0.0.2'),
        sessions_reply(('10.0.0.1', capture), ('10.0.0.2', capture)))

    offerings = tester.get_offerings()

    assert sorted(offerings) == ['10.0.0.1', '10.0.0.2']
    assert all(o.established for o in offerings.values())
    assert [o.offered for o in offerings.values()] == [100, 100]


def test_the_poll_is_one_exec_however_many_peers(tmp_path, fixture_text):
    '''One docker exec per poll, not one per peer: at 50 peers the per-exec
    cost overruns the poll interval and the controller becomes the contention
    the run then reports.'''
    tester = StubbedBIRDTester(tmp_path, peers('10.0.0.1', '10.0.0.2', '10.0.0.3'))

    tester.get_offerings()

    assert len(tester.execs) == 1
    command = tester.execs[0]
    assert command[:2] == ['sh', '-c']
    # Each peer's own control socket is named; a bare `birdc` in a tester
    # container reaches no daemon at all.
    for key in ('10.0.0.1', '10.0.0.2', '10.0.0.3'):
        assert '{0}/{1}.ctl'.format(tester.guest_dir, key) in command[2]
        assert SESSION_MARKER + key in command[2]


def test_a_peer_that_did_not_answer_is_still_polled(tmp_path, fixture_text):
    '''Dropping the peer instead would change the session key set, and the
    recorder would then reject every later poll -- losing the run's tester
    evidence because one socket was slow to appear.'''
    capture = fixture_text('bird2_tester_show_protocols_all.txt')
    tester = StubbedBIRDTester(tmp_path, peers('10.0.0.1', '10.0.0.2'),
                               sessions_reply(('10.0.0.1', capture)))

    offerings = tester.get_offerings()

    assert sorted(offerings) == ['10.0.0.1', '10.0.0.2']
    silent = offerings['10.0.0.2']
    assert silent.offered is None
    assert silent.established is False
    assert silent.expected == 100
    assert silent.complete is False


def test_a_failed_exec_is_raised_rather_than_read_as_a_silent_generator(
        tmp_path):
    '''"We could not ask" has to stay distinct from "nobody answered".

    offering_stats() records a raised failure as `tester_offering_error`, which
    is what puts `read_failures` in the artifact. Swallowing it here reported
    every peer as not established instead, so a run whose polls all failed
    produced the same artifact as a run whose generator never came up -- and
    that error path could never fire for the only generator that has one.
    '''
    tester = StubbedBIRDTester(tmp_path, peers('10.0.0.1', '10.0.0.2'),
                               RuntimeError('container is not running'))

    with pytest.raises(RuntimeError):
        tester.get_offerings()


def test_expected_comes_from_the_configuration_not_the_generator(tmp_path,
                                                                 fixture_text):
    '''The capture is a generator that loaded 100 routes. Configured for 200,
    it is half-loaded, and judging it against its own report would call that
    complete.'''
    capture = fixture_text('bird2_tester_show_protocols_all.txt')
    tester = StubbedBIRDTester(tmp_path, peers('10.0.0.1', paths=200),
                               sessions_reply(('10.0.0.1', capture)))

    offering = tester.get_offerings()['10.0.0.1']

    assert offering.expected == 200
    assert offering.configured == 100
    assert offering.offered == 100
    assert offering.complete is False


def test_a_generator_that_cannot_report_backpressure_is_not_polled_for_it(tmp_path,
                                                                          fixture_text):
    '''BIRD 2.19 has no TX-pending field, and the synthetic tester image is
    2.19. Recording 0 would assert the generator was never blocked.'''
    capture = fixture_text('bird2_tester_show_protocols_all.txt')
    tester = StubbedBIRDTester(tmp_path, peers('10.0.0.1'),
                               sessions_reply(('10.0.0.1', capture)))

    offering = tester.get_offerings()['10.0.0.1']

    assert offering.tx_pending_bytes is None
    assert offering.pending_prefixes is None


def test_the_share_of_the_table_the_rate_covers_is_published_with_it():
    '''BIRD 2.19 counts an export when the route is handed to the BGP
    protocol, not when it reaches the wire, so a 1M-prefix table is already
    fully offered at the first poll. Measured at 0.2s that real run reported
    21452 prefixes/s -- the slope of the last few thousand prefixes, not the
    generator's send rate. The rate is only safe to read beside the share of
    the table it covers.'''
    r = TesterEventRecorder(0.0, 'tester', sample_interval_s=0.2)
    r.observe(1.0, {'a': offering(expected=1_000_000, offered=993_564)})
    r.observe(1.3, {'a': offering(expected=1_000_000, offered=1_000_000)})

    m = metrics(r)
    assert m['offered_prefixes'] == 1_000_000
    assert m['offered_in_interval'] == 6_436
    assert m['offered_rate_pps'] == pytest.approx(6_436 / 0.3)


def test_a_table_offered_before_the_first_poll_covers_none_of_the_interval():
    '''The 1s-poll form of the same run: the whole table is there when the
    instrument first looks, so nothing at all was measured arriving.'''
    r = TesterEventRecorder(0.0, 'tester', sample_interval_s=1.0)
    r.observe(1.9, {'a': offering(expected=1_000_000, offered=1_000_000)})

    m = metrics(r)
    assert m['offered_prefixes'] == 1_000_000
    assert m['injection_s'] == 0.0
    assert m['offered_in_interval'] == 0
    assert m['offered_rate_pps'] is None
