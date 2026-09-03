'''Docker-free tests for the interval after the workload was fully offered.

`post_injection_tail_s` is the run's answer to the question the legacy
`testers (s)` column was read as answering: once the generators had handed over
everything they were configured to send, how much longer did the target and
monitor take?  It spans two producers, so it is signed -- a run whose monitor
reached its check-point while the generators were still finishing overlapped,
and that is a result rather than a fault.
'''
import pytest

import bgperf2
from measurements import (
    EventKind,
    EventPhase,
    LifecycleEvent,
    MonitorEventRecorder,
    TesterEventRecorder,
    TesterOffering,
    event_artifact,
    tester_fleet_metrics,
    tester_metrics,
)


def monitor(samples, interval=1.0, required_at=None):
    '''A monitor stream, including the run's one clock origin at t=0.'''
    recorder = MonitorEventRecorder(0.0, producer='bgperf_monitor',
                                    sample_interval_s=interval)
    for at, accepted in samples:
        recorder.observe(at, accepted,
                         required_reached=required_at is not None
                         and at >= required_at)
    return recorder


def injector(producer, polls, interval=1.0):
    '''One generator container driving a single session.'''
    recorder = TesterEventRecorder(0.0, producer, sample_interval_s=interval)
    for at, fields in polls:
        fields = dict(fields)
        fields.setdefault('established', True)
        fields.setdefault('expected', 100)
        recorder.observe(at, {'s': TesterOffering(**fields)})
    return recorder


def stream(monitor_recorder, *tester_recorders):
    events = list(monitor_recorder.events)
    for recorder in tester_recorders:
        events.extend(recorder.events)
    return events


def test_a_target_still_working_after_the_load_was_delivered():
    m = monitor([(float(at), 20 * at) for at in range(1, 7)],
                required_at=6.0)
    t = injector('a', [(1.0, dict(offered=0)),
                       (2.0, dict(offered=50)),
                       (3.0, dict(offered=100))])

    measured = tester_metrics(stream(m, t), 'a')

    assert measured['injection_s'] == 1.0
    assert measured['post_injection_tail_s'] == 3.0
    assert measured['post_injection_tail_resolution_s'] == 1.0


def test_an_overlap_is_reported_as_a_negative_tail_not_as_zero():
    '''The ordinary shape when the check-point sits below the full table.

    Clamping it would publish a run where the target was never the thing being
    waited for as one with an instant tail -- the same number a run that
    converged the moment its generators finished would get.
    '''
    m = monitor([(1.0, 0), (2.0, 100), (3.0, 100)], required_at=2.0)
    t = injector('a', [(1.0, dict(offered=0)),
                       (3.0, dict(offered=50)),
                       (6.0, dict(offered=100))])

    measured = tester_metrics(stream(m, t), 'a')

    assert measured['post_injection_tail_s'] == -4.0


def test_a_generator_that_never_completed_has_no_tail():
    '''And it is not measured from the last update instead.

    `tester_last_update` is the last increase that was *observed*, not the end
    of the workload, so a tail derived from it would be a plausible number for
    exactly the runs where the generator is under suspicion.
    '''
    m = monitor([(1.0, 0), (2.0, 60), (5.0, 100)], required_at=5.0)
    t = injector('a', [(1.0, dict(offered=0)), (2.0, dict(offered=60))])

    measured = tester_metrics(stream(m, t), 'a')

    assert measured['injection_s'] is None
    assert measured['post_injection_tail_s'] is None
    assert measured['post_injection_tail_resolution_s'] is None


def test_a_run_that_never_reached_the_required_count_has_no_tail():
    m = monitor([(1.0, 0), (2.0, 60), (3.0, 60)])
    t = injector('a', [(1.0, dict(offered=0)),
                       (2.0, dict(offered=50)),
                       (3.0, dict(offered=100))])

    measured = tester_metrics(stream(m, t), 'a')

    assert measured['injection_s'] == 1.0
    assert measured['post_injection_tail_s'] is None
    assert measured['post_injection_tail_resolution_s'] is None


def test_the_tail_is_only_as_sharp_as_the_wider_of_its_two_polls():
    '''One end is a generator poll and the other a monitor poll, and they are
    two loops. The coarser of them bounds the interval.'''
    m = monitor([(1.0, 0), (6.5, 100)], required_at=6.5)
    t = injector('a', [(1.0, dict(offered=0)), (2.0, dict(offered=100))])

    measured = tester_metrics(stream(m, t), 'a')

    assert measured['post_injection_tail_s'] == 4.5
    # The monitor's look was 5.5s wide; the generator's was the 1s floor.
    assert measured['post_injection_tail_resolution_s'] == 5.5


def test_the_fleet_tail_starts_at_the_slowest_generator():
    '''A tail measured from the first generator to finish would charge the
    target with the time it spent waiting for the other injectors.'''
    m = monitor([(1.0, 0), (8.0, 200)], required_at=8.0)
    a = injector('a', [(1.0, dict(offered=0)), (2.0, dict(offered=100))])
    b = injector('b', [(1.0, dict(offered=0)), (5.0, dict(offered=100))])

    fleet = tester_fleet_metrics(stream(m, a, b), ['a', 'b'])

    assert fleet['complete_s'] == 5.0
    assert fleet['post_injection_tail_s'] == 3.0


def test_one_incomplete_generator_leaves_the_fleet_tail_unmeasured():
    m = monitor([(1.0, 0), (8.0, 200)], required_at=8.0)
    a = injector('a', [(1.0, dict(offered=0)), (2.0, dict(offered=100))])
    b = injector('b', [(1.0, dict(offered=0)), (5.0, dict(offered=20))])

    fleet = tester_fleet_metrics(stream(m, a, b), ['a', 'b'])

    assert fleet['incomplete_testers'] == ['b']
    assert fleet['post_injection_tail_s'] is None
    assert fleet['post_injection_tail_resolution_s'] is None


def test_both_artifact_sections_carry_the_tail():
    m = monitor([(1.0, 0), (4.0, 200)], required_at=4.0)
    a = injector('a', [(1.0, dict(offered=0)), (2.0, dict(offered=100))])
    b = injector('b', [(1.0, dict(offered=0)), (3.0, dict(offered=100))])

    doc = event_artifact(stream(m, a, b), 'converged',
                         testers={'a': {}, 'b': {}})

    assert doc['testers']['a']['post_injection_tail_s'] == 2.0
    assert doc['testers']['b']['post_injection_tail_s'] == 1.0
    assert doc['tester_fleet']['post_injection_tail_s'] == 1.0


def printed_tail(capsys, events, producers):
    bgperf2.print_post_injection_tail(events, producers)
    return capsys.readouterr().out


def test_a_measured_tail_is_printed_as_a_tail(capsys):
    m = monitor([(float(at), 20 * at) for at in range(1, 6)],
                required_at=5.0)
    t = injector('a', [(1.0, dict(offered=0)), (2.0, dict(offered=100))])

    printed = printed_tail(capsys, stream(m, t), ['a'])

    assert 'post-injection tail: 3.0s from the last generator finishing' \
        in printed


def test_an_overlap_is_not_printed_as_a_tail(capsys):
    m = monitor([(1.0, 0), (2.0, 100), (3.0, 100)], required_at=2.0)
    t = injector('a', [(1.0, dict(offered=0)),
                       (3.0, dict(offered=50)),
                       (6.0, dict(offered=100))])

    printed = printed_tail(capsys, stream(m, t), ['a'])

    assert 'post-injection tail: none' in printed
    assert 'reached the required count 4.0s before the last generator' \
        in printed


def test_a_tail_inside_one_poll_is_not_printed_as_a_duration(capsys):
    '''Both ends come from 1s loops, so a tail of 0.0s says the two events
    landed within one look of each other, not that the target was instant.'''
    m = monitor([(1.0, 0), (2.0, 100)], required_at=2.0)
    t = injector('a', [(1.0, dict(offered=0)), (2.0, dict(offered=100))])

    printed = printed_tail(capsys, stream(m, t), ['a'])

    assert 'not resolved at the 1.0s poll resolution' in printed
    assert '0.0s' not in printed


def test_a_tail_the_width_of_one_poll_is_not_resolved_either(capsys):
    '''The comparison is inclusive. Each end could have happened anywhere
    inside its own look, so a tail exactly one look wide is not
    distinguishable from no tail at all.'''
    m = monitor([(1.0, 0), (2.0, 60), (3.0, 100)], required_at=3.0)
    t = injector('a', [(1.0, dict(offered=0)), (2.0, dict(offered=100))])

    measured = tester_metrics(stream(m, t), 'a')
    assert measured['post_injection_tail_s'] == 1.0
    assert measured['post_injection_tail_resolution_s'] == 1.0

    assert 'not resolved at the 1.0s poll resolution' in printed_tail(
        capsys, stream(m, t), ['a'])


def test_an_unmeasured_tail_says_which_end_was_missing(capsys):
    m = monitor([(1.0, 0), (5.0, 100)], required_at=5.0)
    stalled = injector('a', [(1.0, dict(offered=0)), (2.0, dict(offered=60))])
    assert 'a generator has no completed injection' in printed_tail(
        capsys, stream(m, stalled), ['a'])

    failed = monitor([(1.0, 0), (5.0, 60)])
    done = injector('a', [(1.0, dict(offered=0)), (2.0, dict(offered=100))])
    assert 'the monitor never reached the required count' in printed_tail(
        capsys, stream(failed, done), ['a'])


def test_the_missing_end_is_not_named_as_a_missing_completion(capsys):
    '''`incomplete_testers` holds a generator with no *bounded* injection,
    which is a missing first update as well as a missing completion. Reporting
    it as "no completion" would name the wrong end for a generator that
    reported one and was never observed to offer anything.'''
    m = monitor([(1.0, 0), (5.0, 100)], required_at=5.0)
    complete_without_updates = [
        LifecycleEvent(EventKind.TESTER_SESSION_READY, 1.0, 'a',
                       EventPhase.SETUP),
        LifecycleEvent(EventKind.TESTER_COMPLETE, 2.0, 'a',
                       EventPhase.INJECTION),
    ]
    events = list(m.events) + complete_without_updates

    assert tester_fleet_metrics(events, ['a'])['incomplete_testers'] == ['a']
    printed = printed_tail(capsys, events, ['a'])
    assert 'a generator has no completed injection' in printed
    assert 'no generator completion' not in printed


def test_the_tail_is_printed_once_for_a_fleet_not_once_per_generator(capsys):
    m = monitor([(float(at), 25 * at) for at in range(1, 9)], required_at=8.0)
    a = injector('a', [(1.0, dict(offered=0)), (2.0, dict(offered=100))])
    b = injector('b', [(float(at), dict(offered=20 * at))
                       for at in range(1, 5)] + [(5.0, dict(offered=100))])

    bgperf2.print_tester_metrics(stream(m, a, b), ['a', 'b'])

    printed = capsys.readouterr().out
    assert printed.count('post-injection tail') == 1
    assert 'post-injection tail: 3.0s' in printed
