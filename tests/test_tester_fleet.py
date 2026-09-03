'''Docker-free tests for the across-generator aggregate.

A full-internet MRT run drives ten injector containers.  Each one already
reports its own lifecycle; what the run as a whole needs is a single statement
of whether the workload was offered at all, taken so that no generator can
answer on another's behalf.
'''
import pytest

import bgperf2
from measurements import (
    EventKind,
    EventPhase,
    LifecycleEvent,
    MeasurementEventError,
    TesterEventRecorder,
    TesterOffering,
    event_artifact,
    tester_fleet_metrics,
)


ORIGIN = LifecycleEvent(EventKind.BENCH_CLOCK_STARTED, 0.0, 'controller',
                        EventPhase.SETUP)


def injector(producer, polls, interval=1.0):
    '''One generator container polled with a single session.

    `polls` is a sequence of (monotonic_s, TesterOffering keyword) pairs, the
    shape both real generators produce: one session per bgpdump2 injector, and
    one per neighbour for BIRD.
    '''
    recorder = TesterEventRecorder(0.0, producer, sample_interval_s=interval)
    for at, fields in polls:
        fields = dict(fields)
        fields.setdefault('established', True)
        fields.setdefault('expected', 100)
        recorder.observe(at, {'s': TesterOffering(**fields)})
    return recorder


def fleet(*recorders):
    events = [ORIGIN]
    for recorder in recorders:
        events.extend(recorder.events)
    return tester_fleet_metrics(events, [r.producer for r in recorders])


def test_the_fleet_injection_spans_the_slowest_generator():
    '''Not the sum of the intervals, and not the first generator's.

    The injectors send at the same time, so their intervals overlap and adding
    them would invent time nobody spent sending. The span runs from the
    earliest first update to the last completion.
    '''
    fast = injector('a', [(1.0, dict(offered=0)),
                          (2.0, dict(offered=50)),
                          (3.0, dict(offered=100))])
    slow = injector('b', [(1.0, dict(offered=0)),
                          (2.0, dict(offered=20)),
                          (5.0, dict(offered=100))])

    m = fleet(fast, slow)

    assert m['testers'] == 2
    assert m['testers_complete'] == 2
    assert m['incomplete_testers'] == []
    assert m['first_update_s'] == 2.0
    assert m['complete_s'] == 5.0
    assert m['injection_s'] == 3.0


def test_a_generator_that_never_finished_is_named_not_averaged_away():
    '''The failure this aggregate exists for.

    One injector of ten that never reported completion means the workload was
    never fully offered. An interval bounded by the nine that did finish would
    describe a run that did not happen, and it would look entirely ordinary.
    '''
    done = injector('a', [(1.0, dict(offered=0)),
                          (2.0, dict(offered=100))])
    stalled = injector('b', [(1.0, dict(offered=0)),
                             (2.0, dict(offered=20)),
                             (3.0, dict(offered=20))])

    m = fleet(done, stalled)

    assert m['testers_complete'] == 1
    assert m['incomplete_testers'] == ['b']
    assert m['injection_s'] is None
    assert m['complete_s'] is None
    # And the count that did arrive is not published as the fleet's offering:
    # 100 of an expected 200 would read as a workload 50% short rather than as
    # a generator that never finished.
    assert m['offered_prefixes'] is None
    assert m['offered_rate_pps'] is None


def test_the_fleet_is_ready_when_its_last_generator_is():
    late = injector('b', [(1.0, dict(established=False, offered=None)),
                          (4.0, dict(offered=0)),
                          (5.0, dict(offered=100))])
    early = injector('a', [(1.0, dict(offered=0)),
                           (2.0, dict(offered=100))])

    m = fleet(early, late)

    assert m['tester_startup_s'] == 4.0
    # Bounded by the poll that found the last generator ready -- 3s after the
    # previous look at it, not the 1s cadence the loop asked for.
    assert m['startup_resolution_s'] == 3.0


def test_a_generator_that_never_came_up_leaves_startup_unmeasured():
    up = injector('a', [(1.0, dict(offered=0)), (2.0, dict(offered=100))])
    never = injector('b', [(1.0, dict(established=False, offered=None)),
                           (2.0, dict(established=False, offered=None))])

    m = fleet(up, never)

    assert m['tester_startup_s'] is None
    assert m['startup_resolution_s'] is None
    assert m['incomplete_testers'] == ['b']


def test_counts_are_summed_and_the_rate_uses_the_fleet_span():
    '''The rate divides by the span the generators shared, so it is lower than
    any per-generator slope -- the conservative direction, and the only one a
    fleet number can safely take.'''
    fast = injector('a', [(1.0, dict(offered=0)),
                          (2.0, dict(offered=50)),
                          (3.0, dict(offered=100))])
    slow = injector('b', [(1.0, dict(offered=0)),
                          (2.0, dict(offered=20)),
                          (5.0, dict(offered=100))])

    m = fleet(fast, slow)

    assert m['offered_prefixes'] == 200
    # 50 of a's table and 80 of b's crossed their own measured intervals; what
    # each had already offered when its first poll landed is outside both.
    assert m['offered_in_interval'] == 130
    assert m['offered_rate_pps'] == pytest.approx(130 / 3.0)


def test_an_unreadable_count_refuses_the_total_but_keeps_the_interval():
    '''A generator can report its own completion on a poll whose counters were
    not legible. The interval is still real; the total is not.'''
    counted = injector('a', [(1.0, dict(offered=0)),
                             (2.0, dict(offered=100))])
    uncounted = injector('b', [(1.0, dict(offered=0)),
                               (2.0, dict(offered=10)),
                               (3.0, dict(offered=None, send_complete=True))])

    m = fleet(counted, uncounted)

    assert m['incomplete_testers'] == []
    assert m['injection_s'] == 1.0
    assert m['offered_prefixes'] is None
    assert m['offered_in_interval'] is None
    assert m['offered_rate_pps'] is None


def test_the_generators_own_durations_are_not_added_up():
    '''They ran at the same time. The longest is a lower bound on the fleet's
    send span; the sum is a number nothing measured.'''
    quick = injector('a', [(1.0, dict(offered=100, send_complete=True,
                                      reported_send_duration_s=0.001017))])
    slower = injector('b', [(1.0, dict(offered=100, send_complete=True,
                                       reported_send_duration_s=0.011280))])

    assert fleet(quick, slower)['reported_injection_s'] == 0.011280


def test_one_silent_generator_withholds_the_fleet_wire_evidence():
    reports = injector('a', [(1.0, dict(offered=100, send_complete=True,
                                        octets_on_wire=183_852,
                                        reported_send_duration_s=0.001))])
    silent = injector('b', [(1.0, dict(offered=100, send_complete=True))])

    m = fleet(reports, silent)

    assert m['octets_on_wire'] is None
    assert m['reported_injection_s'] is None


def test_wire_side_octets_are_summed_when_every_generator_reports():
    a = injector('a', [(1.0, dict(offered=100, send_complete=True,
                                  octets_on_wire=183_852))])
    b = injector('b', [(1.0, dict(offered=100, send_complete=True,
                                  octets_on_wire=259_226))])

    assert fleet(a, b)['octets_on_wire'] == 443_078


def test_a_fleet_summary_needs_the_controller_clock():
    r = injector('a', [(1.0, dict(offered=100))])

    with pytest.raises(MeasurementEventError):
        tester_fleet_metrics(r.events, ['a'])


def test_a_run_with_no_generator_has_no_fleet_to_summarise():
    with pytest.raises(MeasurementEventError):
        tester_fleet_metrics([ORIGIN], [])


def test_the_artifact_carries_the_fleet_beside_the_sections():
    a = injector('a', [(1.0, dict(offered=0)), (2.0, dict(offered=100))])
    b = injector('b', [(1.0, dict(offered=0)), (4.0, dict(offered=100))])
    events = [ORIGIN] + list(a.events) + list(b.events)

    doc = event_artifact(events, 'converged',
                         testers={'a': {}, 'b': {}})

    assert sorted(doc['testers']) == ['a', 'b']
    assert doc['tester_fleet']['injection_s'] == 2.0
    assert doc['tester_fleet']['testers_complete'] == 2


def test_a_failed_run_still_reports_which_generators_finished():
    a = injector('a', [(1.0, dict(offered=0)), (2.0, dict(offered=100))])
    b = injector('b', [(1.0, dict(offered=0)), (2.0, dict(offered=20))])

    doc = event_artifact([ORIGIN] + list(a.events) + list(b.events),
                         'failed', testers={'a': {}, 'b': {}})

    assert doc['tester_fleet']['incomplete_testers'] == ['b']


def test_the_printed_summary_names_the_generators_that_did_not_finish(capsys):
    a = injector('a', [(1.0, dict(offered=0)), (2.0, dict(offered=100))])
    b = injector('b', [(1.0, dict(offered=0)), (2.0, dict(offered=20))])
    events = [ORIGIN] + list(a.events) + list(b.events)

    bgperf2.print_tester_metrics(events, ['a', 'b'])

    printed = capsys.readouterr().out
    assert 'all 2 generators: 1 reported completion' in printed
    assert 'no completion from b' in printed


def test_the_printed_summary_reports_the_fleet_rate(capsys):
    a = injector('a', [(1.0, dict(offered=0)),
                       (2.0, dict(offered=50)),
                       (3.0, dict(offered=100))])
    b = injector('b', [(1.0, dict(offered=0)),
                       (2.0, dict(offered=20)),
                       (5.0, dict(offered=100))])

    bgperf2.print_tester_metrics([ORIGIN] + list(a.events) + list(b.events),
                                 ['a', 'b'])

    printed = capsys.readouterr().out
    assert 'all 2 generators' in printed
    assert 'offered 200 prefixes, 130 of them in the measured 3.0s' in printed


def test_a_span_nothing_crossed_is_not_a_fleet_rate_of_zero(capsys):
    '''The MRT shape, and the reason this branch exists.

    Two injectors whose sub-millisecond walks were both over before their own
    first poll still complete at different polls, so the fleet span is real
    and none of the table is inside it. `0 prefixes/s` would report ten
    injectors that delivered everything instantly as ten that sent nothing.
    '''
    a = injector('a', [(1.0, dict(offered=100, send_complete=True))])
    # An injector holding less than the run asked for: `-T` caps the table
    # while the MRT file is read, so its own report is the only completion
    # there is, and it lands a poll after its count was already final.
    b = injector('b', [(1.0, dict(expected=200, offered=100)),
                       (4.0, dict(expected=200, offered=100,
                                  send_complete=True))])

    events = [ORIGIN] + list(a.events) + list(b.events)
    m = tester_fleet_metrics(events, ['a', 'b'])
    assert m['injection_s'] == 3.0
    assert m['offered_in_interval'] == 0
    assert m['offered_rate_pps'] is None

    bgperf2.print_tester_metrics(events, ['a', 'b'])
    printed = capsys.readouterr().out
    assert 'prefixes/s' not in printed
    assert 'none of them inside the 3.0s' in printed


def test_one_generator_gets_no_fleet_line(capsys):
    '''It would restate the line above it, word for word and less precisely.'''
    a = injector('a', [(1.0, dict(offered=0)), (2.0, dict(offered=100))])

    bgperf2.print_tester_metrics([ORIGIN] + list(a.events), ['a'])

    assert 'generators' not in capsys.readouterr().out
