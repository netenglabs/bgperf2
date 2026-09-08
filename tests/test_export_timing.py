'''Export timing: what the target's other sessions were served, and when.

`--receivers N` gave a run more than one export session; until now nothing
measured them. The monitor is one export session and what it observes is the
run's convergence, so a `--receivers 20` run and a `--receivers 0` run differed
in exactly one published number -- `elapsed (s)` -- with the cost of the
fan-out inside it, indistinguishable from a slow target. That is the
end-to-end collapse Phase 5A's last work item is about: ingress is measured at
the generators, convergence at the monitor, and export nowhere.

The rules that hold this up are the ones the generator poll already states,
reached from the other end of the run: every configured receiver appears in
every poll (so the ones that answer cannot satisfy "the fan-out has the
table"), an unreadable receiver is not a receiver holding nothing, an interval
is only as sharp as the polls bounding it, and the fan-out is served when its
*slowest* receiver has the table.
'''
import pytest

from measurements import (
    EVENT_PHASE,
    natural_key,
    EventKind,
    EventOrderError,
    EventPhase,
    ExportEventRecorder,
    LifecycleEvent,
    MeasurementEventError,
    event_artifact,
    export_metrics,
    export_poll_can_stop,
)

RECEIVERS = ('bgperf_receiver0', 'bgperf_receiver1')
REQUIRED = 100


def event(kind, timestamp, producer='controller', **kwargs):
    return LifecycleEvent(kind, timestamp, producer, EVENT_PHASE[kind],
                          **kwargs)


def origin(timestamp=0.0):
    return event(EventKind.BENCH_CLOCK_STARTED, timestamp)


def recorder(receivers=RECEIVERS, required=REQUIRED, started=0.0,
             interval=1.0):
    return ExportEventRecorder(started, receivers, required,
                               sample_interval_s=interval)


def drive(polls, receivers=RECEIVERS, required=REQUIRED, started=0.0,
          interval=1.0):
    '''Run a recorder over `(timestamp, {receiver: accepted})` polls.'''
    export = recorder(receivers, required, started, interval)
    for timestamp, accepted in polls:
        export.observe(timestamp, accepted)
    return export


def measured(export, extra_events=(), receivers=None):
    events = [origin()] + list(export.events) + list(extra_events)
    return export_metrics(events, receivers or export.receivers)


# --- the vocabulary -------------------------------------------------------


def test_export_events_are_their_own_phase():
    '''A receiver's first prefix is not the monitor's, at any level.

    Sharing the convergence phase would put several first-prefix intervals
    under one heading with nothing saying which of them the row's `elapsed (s)`
    came from -- the reason churn and the policy reload have phases of their
    own.
    '''
    assert EVENT_PHASE[EventKind.RECEIVER_FIRST_PREFIX] is EventPhase.EXPORT
    assert EVENT_PHASE[EventKind.RECEIVER_TABLE_REACHED] is EventPhase.EXPORT
    assert EVENT_PHASE[EventKind.MONITOR_FIRST_PREFIX] is EventPhase.CONVERGENCE


def test_the_recorder_does_not_stamp_a_second_clock_origin():
    '''There is exactly one `bench_clock_started` in a run.

    The monitor recorder owns it. A second would make every `unique_event()`
    lookup against the merged stream ambiguous, which is a `DuplicateEventError`
    out of the artifact builder on a run that had already converged.
    '''
    export = drive([(1.0, {r: 0 for r in RECEIVERS})])

    assert [e.kind for e in export.events] == []


# --- one poll round -------------------------------------------------------


def test_each_receiver_reports_its_own_first_prefix_and_table():
    export = drive([
        (1.0, {'bgperf_receiver0': 0, 'bgperf_receiver1': 0}),
        (2.0, {'bgperf_receiver0': 40, 'bgperf_receiver1': 0}),
        (3.0, {'bgperf_receiver0': 100, 'bgperf_receiver1': 60}),
        (4.0, {'bgperf_receiver0': 100, 'bgperf_receiver1': 100}),
    ])
    sessions = measured(export)['sessions']

    assert sessions['bgperf_receiver0']['first_prefix_s'] == 2.0
    assert sessions['bgperf_receiver0']['table_reached_s'] == 3.0
    assert sessions['bgperf_receiver1']['first_prefix_s'] == 3.0
    assert sessions['bgperf_receiver1']['table_reached_s'] == 4.0


def test_an_event_fires_once_however_the_count_moves_afterwards():
    export = drive([
        (1.0, {r: 100 for r in RECEIVERS}),
        (2.0, {r: 40 for r in RECEIVERS}),
        (3.0, {r: 100 for r in RECEIVERS}),
    ])
    reached = [e for e in export.events
               if e.kind is EventKind.RECEIVER_TABLE_REACHED]

    assert [e.monotonic_s for e in reached] == [1.0, 1.0]


def test_every_configured_receiver_must_appear_in_every_poll():
    '''The generator poll's rule, and here it is what stops the receivers that
    happen to answer from satisfying "the whole fan-out has the table".'''
    export = recorder()
    export.observe(1.0, {r: 10 for r in RECEIVERS})

    with pytest.raises(MeasurementEventError):
        export.observe(2.0, {'bgperf_receiver0': 100})


def test_an_unread_receiver_is_not_a_receiver_holding_nothing():
    export = drive([
        (1.0, {'bgperf_receiver0': 100, 'bgperf_receiver1': None}),
    ])
    sessions = measured(export)['sessions']

    assert sessions['bgperf_receiver0']['table_reached_s'] == 1.0
    assert sessions['bgperf_receiver1']['first_prefix_s'] is None
    assert export.accepted['bgperf_receiver1'] is None


def test_a_failed_read_does_not_erase_what_was_already_observed():
    export = drive([
        (1.0, {'bgperf_receiver0': 40, 'bgperf_receiver1': 40}),
        (2.0, {'bgperf_receiver0': 60, 'bgperf_receiver1': None}),
    ])

    assert export.accepted == {'bgperf_receiver0': 60,
                               'bgperf_receiver1': 40}


def test_the_recorder_rejects_samples_that_run_backwards():
    export = recorder()
    export.observe(2.0, {r: 1 for r in RECEIVERS})

    with pytest.raises(EventOrderError):
        export.observe(1.0, {r: 2 for r in RECEIVERS})


def test_the_recorder_rejects_a_sample_before_the_clock_origin():
    export = recorder(started=5.0)

    with pytest.raises(EventOrderError):
        export.observe(4.0, {r: 1 for r in RECEIVERS})


@pytest.mark.parametrize('bad', [-1, 1.5, True, 'many'])
def test_a_count_must_be_a_whole_number_of_prefixes_or_unread(bad):
    export = recorder()

    with pytest.raises((ValueError, TypeError)):
        export.observe(1.0, {'bgperf_receiver0': bad,
                             'bgperf_receiver1': 0})


def test_a_recorder_needs_receivers_and_a_positive_check_point():
    with pytest.raises(MeasurementEventError):
        ExportEventRecorder(0.0, [], REQUIRED)
    with pytest.raises(ValueError):
        ExportEventRecorder(0.0, RECEIVERS, 0)
    with pytest.raises(ValueError):
        ExportEventRecorder(0.0, ('a', 'a'), REQUIRED)


# --- when the poll may stop ----------------------------------------------


def test_the_poll_stops_only_once_every_receiver_holds_the_table():
    assert export_poll_can_stop({'a': 100, 'b': 100}, REQUIRED) is True
    assert export_poll_can_stop({'a': 100, 'b': 99}, REQUIRED) is False
    # An unread receiver is not a finished one: stopping there would leave the
    # fan-out judged on the sessions that happened to answer.
    assert export_poll_can_stop({'a': 100, 'b': None}, REQUIRED) is False
    assert export_poll_can_stop({}, REQUIRED) is False


def test_the_completion_round_is_the_round_that_carries_the_evidence():
    '''Both events fire on or before the poll that satisfies the stop rule, so
    ending the loop there loses nothing observable.'''
    export = drive([(1.0, {r: 100 for r in RECEIVERS})])

    assert export_poll_can_stop(export.accepted, REQUIRED) is True
    assert measured(export)['table_reached_s'] == 1.0


# --- the fleet ------------------------------------------------------------


def test_the_fan_out_is_served_when_its_slowest_receiver_has_the_table():
    export = drive([
        (1.0, {'bgperf_receiver0': 100, 'bgperf_receiver1': 10}),
        (5.0, {'bgperf_receiver0': 100, 'bgperf_receiver1': 100}),
    ])
    export_section = measured(export)

    assert export_section['receivers'] == 2
    assert export_section['receivers_complete'] == 2
    assert export_section['table_reached_s'] == 5.0
    assert export_section['export_spread_s'] == 4.0


def test_one_stalled_receiver_leaves_every_fleet_interval_null():
    '''All-or-nothing, on `tester_fleet_metrics()`'s rule: an interval bounded
    by the receivers that finished describes a fan-out that was not served.'''
    export = drive([
        (1.0, {'bgperf_receiver0': 100, 'bgperf_receiver1': 10}),
        (2.0, {'bgperf_receiver0': 100, 'bgperf_receiver1': 10}),
    ])
    export_section = measured(export)

    assert export_section['incomplete_receivers'] == ['bgperf_receiver1']
    assert export_section['receivers_complete'] == 1
    assert export_section['table_reached_s'] is None
    assert export_section['export_spread_s'] is None
    # The per-receiver evidence survives it: the one that was served says so.
    assert export_section['sessions'][
        'bgperf_receiver0']['table_reached_s'] == 1.0


def test_the_export_start_survives_a_receiver_that_never_finished():
    '''Gated separately from the intervals above: a fan-out where every session
    was seen taking prefixes and one never finished has a real export start,
    and that is exactly the run where a reader wants it.'''
    export = drive([
        (1.0, {'bgperf_receiver0': 10, 'bgperf_receiver1': 10}),
        (2.0, {'bgperf_receiver0': 100, 'bgperf_receiver1': 10}),
    ])
    export_section = measured(export)

    assert export_section['first_prefix_s'] == 1.0
    assert export_section['table_reached_s'] is None


def test_a_receiver_never_seen_taking_prefixes_withholds_the_export_start():
    export = drive([
        (1.0, {'bgperf_receiver0': 10, 'bgperf_receiver1': 0}),
    ])

    assert measured(export)['first_prefix_s'] is None


# --- resolution -----------------------------------------------------------


def test_an_event_carries_the_gap_the_round_achieved():
    '''The requested cadence is a floor, never the answer: a round is a
    `docker exec` per receiver and the loop waits after it.'''
    export = drive([
        (0.5, {r: 0 for r in RECEIVERS}),
        (4.0, {r: 100 for r in RECEIVERS}),
    ], interval=1.0)
    export_section = measured(export)

    assert export_section['table_reached_resolution_s'] == 3.5
    assert export_section['sessions'][
        'bgperf_receiver0']['table_reached_resolution_s'] == 3.5


def test_the_first_round_is_resolved_only_back_to_the_clock_origin():
    export = drive([(30.0, {r: 100 for r in RECEIVERS})], interval=1.0)

    assert measured(export)['table_reached_resolution_s'] == 30.0


def test_a_round_faster_than_the_cadence_cannot_beat_the_cadence():
    export = drive([
        (1.0, {r: 0 for r in RECEIVERS}),
        (1.2, {r: 100 for r in RECEIVERS}),
    ], interval=1.0)

    assert measured(export)['table_reached_resolution_s'] == 1.0


def test_the_spread_is_bounded_by_the_wider_of_the_two_rounds():
    export = drive([
        (1.0, {'bgperf_receiver0': 100, 'bgperf_receiver1': 0}),
        (6.0, {'bgperf_receiver0': 100, 'bgperf_receiver1': 100}),
    ], interval=1.0)

    assert measured(export)['export_spread_resolution_s'] == 5.0


def test_a_one_round_discrepancy_can_never_be_a_resolved_spread():
    """The safety property that lets one round stamp all its receivers.

    A round takes real time -- 2.8s for six receivers on a loaded box -- so a
    receiver read late in it is dated to the round's start and can look up to
    one round-gap ahead of one read early in it. The receiver seen a round
    later carries that round's gap as its resolution, so the spread it produces
    is bounded by the resolution published beside it, and a fan-out served
    simultaneously can never be reported as a spread that was resolved.
    """
    export = drive([
        (1.0, {'bgperf_receiver0': 0, 'bgperf_receiver1': 100}),
        (4.8, {'bgperf_receiver0': 100, 'bgperf_receiver1': 100}),
    ], interval=1.0)
    export_section = measured(export)

    assert export_section['export_spread_s'] == pytest.approx(3.8)
    assert export_section['export_spread_resolution_s'] == pytest.approx(3.8)
    assert export_section['export_spread_s'] <= \
        export_section['export_spread_resolution_s']


# --- against the monitor --------------------------------------------------


def test_the_delta_to_the_monitor_is_signed():
    '''The monitor is one export session among several and nothing orders
    them, so a receiver reaching the table first is a result rather than a
    fault -- and clamping it at zero would give that run the same number as one
    whose fan-out finished exactly with the instrument.'''
    export = drive([(2.0, {r: 100 for r in RECEIVERS})])
    required = event(EventKind.MONITOR_REQUIRED_REACHED, 5.0,
                     producer='bgperf_monitor')

    assert measured(export, [required])['monitor_delta_s'] == -3.0


def test_the_delta_is_withheld_when_the_monitor_never_converged():
    export = drive([(2.0, {r: 100 for r in RECEIVERS})])
    export_section = measured(export)

    assert export_section['monitor_delta_s'] is None
    assert export_section['monitor_delta_resolution_s'] is None


def test_the_delta_is_bounded_by_a_poll_from_each_loop():
    export = drive([
        (1.0, {r: 0 for r in RECEIVERS}),
        (2.0, {r: 100 for r in RECEIVERS}),
    ], interval=1.0)
    required = event(
        EventKind.MONITOR_REQUIRED_REACHED, 4.0, producer='bgperf_monitor',
        details={'poll_resolution_s': 2.5})

    export_section = measured(export, [required])
    assert export_section['monitor_delta_s'] == -2.0
    assert export_section['monitor_delta_resolution_s'] == 2.5


# --- the artifact ---------------------------------------------------------


def test_a_run_with_no_fan_out_keeps_the_document_it_always_produced():
    artifact = event_artifact([origin()], 'converged')

    assert 'export' not in artifact


def test_the_section_carries_the_controller_evidence_beside_the_intervals():
    export = drive([(2.0, {r: 100 for r in RECEIVERS})])
    artifact = event_artifact(
        [origin()] + list(export.events), 'converged',
        export={'required_prefixes': REQUIRED,
                'sessions': {'bgperf_receiver0': {'accepted_prefixes': 120},
                             'bgperf_receiver1': {'accepted_prefixes': 100}}})

    section = artifact['export']
    assert section['required_prefixes'] == REQUIRED
    assert section['table_reached_s'] == 2.0
    assert section['sessions'][
        'bgperf_receiver0']['accepted_prefixes'] == 120
    assert section['sessions']['bgperf_receiver0']['table_reached_s'] == 2.0


def test_evidence_may_not_overwrite_a_derived_interval():
    export = drive([(2.0, {r: 100 for r in RECEIVERS})])
    events = [origin()] + list(export.events)

    with pytest.raises(MeasurementEventError):
        event_artifact(events, 'converged',
                       export={'table_reached_s': 0.1,
                               'sessions': {r: {} for r in RECEIVERS}})
    with pytest.raises(MeasurementEventError):
        event_artifact(
            events, 'converged',
            export={'sessions': {'bgperf_receiver0': {'table_reached_s': 0.1},
                                 'bgperf_receiver1': {}}})


def test_a_receiver_that_produced_events_is_never_dropped_from_the_section():
    '''A receiver observed but not declared is a wiring fault, and dropping its
    intervals would hide it in the one document that could show it.'''
    export = drive([(2.0, {r: 100 for r in RECEIVERS})])
    artifact = event_artifact(
        [origin()] + list(export.events), 'converged',
        export={'sessions': {'bgperf_receiver0': {}}})

    assert artifact['export']['receivers'] == 2
    assert set(artifact['export']['sessions']) == set(RECEIVERS)


def test_a_failed_run_still_publishes_what_the_fan_out_had_been_served():
    export = drive([(2.0, {'bgperf_receiver0': 40,
                           'bgperf_receiver1': 40})])
    artifact = event_artifact(
        [origin()] + list(export.events), 'failed',
        export={'required_prefixes': REQUIRED,
                'sessions': {r: {'accepted_prefixes': 40} for r in RECEIVERS}})

    assert artifact['export']['incomplete_receivers'] == sorted(RECEIVERS)
    assert artifact['export']['first_prefix_s'] == 2.0


# --- the controller side --------------------------------------------------


import datetime
import json
import queue as queue_module
import threading
import time
from argparse import Namespace

import bgperf2
import monitor as monitor_module


class FakeReceiver:
    '''A receiver container that answers a poll from a scripted list.'''

    def __init__(self, name, counts):
        self.name = name
        self.counts = list(counts)
        self.reads = 0

    def accepted_prefixes(self):
        self.reads += 1
        answer = self.counts[min(self.reads - 1, len(self.counts) - 1)]
        if isinstance(answer, Exception):
            raise answer
        return answer


def poll_until_stopped(receivers, required=REQUIRED, interval=0.01, rounds=2):
    '''Run the real poll loop over fake receivers and return what it recorded.'''
    export = recorder([r.name for r in receivers], required, started=0.0,
                      interval=interval)
    state, failures = {}, {}
    stop = threading.Event()
    thread = bgperf2.controller_export_stats(
        receivers, export, state, failures, stop, interval)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if all(r.reads >= rounds for r in receivers):
            break
        time.sleep(0.01)
    stop.set()
    thread.join(timeout=5)
    return export, state, failures


def a_receiver(payload):
    receiver = monitor_module.Receiver.__new__(monitor_module.Receiver)
    receiver.name = 'bgperf_receiver0'
    receiver.local = lambda cmd: payload
    return receiver


def test_reading_a_receiver_is_not_polling_it_as_an_instrument():
    """`stats()` feeds the queue every published timing is read from, and stays
    refused. `accepted_prefixes()` answers a caller that keeps the count in its
    own recorder and its own artifact section."""
    receiver = a_receiver(
        json.dumps([{'afi_safis': [{'state': {'accepted': 42}}]}]).encode())

    assert receiver.accepted_prefixes() == 42
    with pytest.raises(NotImplementedError):
        receiver.stats(queue_module.Queue())


def test_a_session_that_has_been_given_nothing_reads_as_zero():
    """gobgp omits the field until the session has accepted something, which
    the monitor's own loop already reads as zero."""
    receiver = a_receiver(
        json.dumps([{'afi_safis': [{'state': {}}]}]).encode())

    assert receiver.accepted_prefixes() == 0


def test_an_answer_that_cannot_be_read_raises_rather_than_reporting_zero():
    """A session we failed to ask and a session holding nothing must not
    produce the same measurement."""
    receiver = a_receiver(b'not json')

    with pytest.raises(Exception):
        receiver.accepted_prefixes()


def test_the_poll_never_puts_a_receiver_count_in_the_run_queue():
    '''Nothing would reliably take it out again. `bench()`'s monitor loop stops
    the instant convergence is declared, and the churn and reload loops that
    read the queue afterwards skip anything that is not a monitor sample -- so
    a round completing near the end of a run would be queued and never
    observed, publishing a receiver that had been served as one that never was,
    with the previous round's stale count beside it. The poll thread is its
    recorder's only writer instead.'''
    q = queue_module.Queue()
    receivers = [FakeReceiver('bgperf_receiver0', [10, 100])]
    export = recorder(['bgperf_receiver0'], REQUIRED, interval=0.01)
    stop = threading.Event()

    thread = bgperf2.controller_export_stats(
        receivers, export, {}, {}, stop, 0.01)
    thread.join(timeout=5)
    stop.set()

    assert q.empty()
    assert export.accepted == {'bgperf_receiver0': 100}


def test_the_poll_stamps_the_round_before_it_reads_it():
    started = time.monotonic()
    receivers = [FakeReceiver('bgperf_receiver0', [0, 100])]
    export, _, _ = poll_until_stopped(receivers)
    stamps = [e.monotonic_s for e in export.events]

    assert stamps == sorted(stamps)
    assert all(started <= stamp <= time.monotonic() for stamp in stamps)


def test_the_poll_takes_one_closing_round_when_the_window_shuts():
    """The gap between rounds is wider than the window that follows the
    monitor's check-point -- at six receivers a 3.8s round plus a 3.8s floor,
    against the five monitor polls before convergence is declared. Returning
    without a last look would publish a fan-out served in that gap as one that
    was never served at all."""
    receivers = [FakeReceiver('bgperf_receiver0', [0, 100])]
    export = recorder(['bgperf_receiver0'], REQUIRED, interval=10.0)
    stop = threading.Event()
    delivery = threading.Event()

    thread = bgperf2.controller_export_stats(
        receivers, export, {}, {}, stop, 10.0, delivery_stop=delivery)
    deadline = time.monotonic() + 5
    while receivers[0].reads < 1 and time.monotonic() < deadline:
        time.sleep(0.01)
    # The receiver is served during the long wait, and the window then closes.
    delivery.set()
    thread.join(timeout=5)

    assert receivers[0].reads == 2, 'no closing round was taken'
    assert export.accepted == {'bgperf_receiver0': 100}
    assert measured(export, receivers=['bgperf_receiver0'])[
        'receivers_complete'] == 1


def test_a_failed_read_on_the_completing_round_still_ends_the_poll():
    """The stop rule reads what each receiver was last *seen* holding, not this
    round's dict. A transient exec failure on the round that completes the
    fan-out would otherwise keep N execs per round running for the rest of the
    delivery window -- inside the window whose `max cpu %` and `min free mem
    (GB)` the run publishes, in a load `max foreign cpu %` cannot see."""
    receivers = [FakeReceiver('bgperf_receiver0', [100, 100]),
                 FakeReceiver('bgperf_receiver1',
                              [100, RuntimeError('a transient exec failure')])]
    names = [r.name for r in receivers]
    export = recorder(names, REQUIRED, interval=0.01)
    stop = threading.Event()

    # The first round completes the fan-out for receiver0 only; the second is
    # the one where receiver1 crosses and its read fails.
    receivers[0].counts = [40, 100]
    receivers[1].counts = [40, 100]
    thread = bgperf2.controller_export_stats(
        receivers, export, {}, {}, stop, 0.01)
    thread.join(timeout=5)
    stop.set()

    assert not thread.is_alive(), 'the poll did not end'
    assert measured(export, receivers=names)['receivers_complete'] == 2


def test_the_poll_ends_itself_once_the_fan_out_holds_the_table():
    '''A round cannot be batched -- each receiver is its own container -- so a
    loop that ran to convergence would spend an exec per receiver per second on
    sessions with nothing left to say.'''
    receivers = [FakeReceiver('bgperf_receiver0', [100]),
                 FakeReceiver('bgperf_receiver1', [100])]
    names = [r.name for r in receivers]
    export = recorder(names, REQUIRED, interval=0.01)
    stop = threading.Event()

    thread = bgperf2.controller_export_stats(
        receivers, export, {}, {}, stop, 0.01)
    thread.join(timeout=5)
    stop.set()

    assert [r.reads for r in receivers] == [1, 1]
    assert measured(export, receivers=names)['receivers_complete'] == 2


def test_an_unreadable_receiver_is_recorded_rather_than_ending_the_run():
    receivers = [FakeReceiver('bgperf_receiver0',
                              [RuntimeError('container is gone'), 100])]
    export, state, failures = poll_until_stopped(receivers)

    assert failures['bgperf_receiver0']['polls'] == 1
    assert 'container is gone' in failures['bgperf_receiver0']['first_reason']
    assert state == {}
    # And it did not stop there: an unread receiver is not a finished one.
    assert export.accepted == {'bgperf_receiver0': 100}


def test_read_failures_are_counted_with_the_first_reason_kept():
    failures = {}
    bgperf2.note_export_read_failures({'bgperf_receiver0': 'first'}, failures)
    bgperf2.note_export_read_failures({'bgperf_receiver0': 'second'}, failures)

    assert failures == {'bgperf_receiver0': {'polls': 2,
                                             'first_reason': 'first'}}


def test_a_rejected_round_retires_the_recorder_and_keeps_its_events():
    export = recorder()
    state = {}
    assert bgperf2.observe_export_sample(
        1.0, {r: 100 for r in RECEIVERS}, export, state) is True
    # A round whose receiver set changed: the recorder refuses it rather than
    # letting the receivers that remain satisfy the fan-out.
    assert bgperf2.observe_export_sample(
        2.0, {'bgperf_receiver0': 100}, export, state) is False

    assert 'observation_error' in state
    assert measured(export)['table_reached_s'] == 1.0
    # Retired: a later well-formed round is not observed either.
    assert bgperf2.observe_export_sample(
        3.0, {r: 100 for r in RECEIVERS}, export, state) is False


def test_a_run_with_no_fan_out_summarises_to_nothing_at_all():
    assert bgperf2.export_lifecycle_summary(None, {}, {}, None) == ((), None)


def test_a_fan_out_that_could_not_be_measured_says_so_rather_than_nothing():
    """An absent section on a run whose `run.receivers` is 3 is exactly what an
    older build wrote, so silence would be indistinguishable from a build that
    never took the measurement."""
    events, evidence = bgperf2.export_lifecycle_summary(
        None, {}, {}, 0, ['bgperf_receiver0'], 'the check-point is 0')

    assert events == ()
    assert evidence['unmeasured_reason'] == 'the check-point is 0'
    assert evidence['sessions'] == {
        'bgperf_receiver0': {'accepted_prefixes': None}}
    # Not `observation_error`: a measurement never started and one abandoned
    # partway are different findings.
    assert 'observation_error' not in evidence


def test_an_unmeasured_fan_out_reaches_the_document_and_the_printed_lines():
    events, evidence = bgperf2.export_lifecycle_summary(
        None, {}, {}, 0, ['bgperf_receiver0'], 'the check-point is 0')
    artifact = event_artifact([origin()], 'converged', export=evidence)

    section = artifact['export']
    assert section['receivers'] == 1
    assert section['table_reached_s'] is None
    lines = bgperf2.describe_export_metrics(section)
    assert lines == ['export fan-out: 1 receiver(s), not measured -- '
                     'the check-point is 0']


def test_the_summary_carries_what_each_receiver_was_last_seen_holding():
    export = drive([
        (1.0, {'bgperf_receiver0': 100, 'bgperf_receiver1': 40}),
    ])
    events, evidence = bgperf2.export_lifecycle_summary(
        export, {'observation_error': 'a round went backwards'},
        {'bgperf_receiver1': {'polls': 3, 'first_reason': 'gone'}}, REQUIRED)

    assert len(events) == 3
    assert evidence['required_prefixes'] == REQUIRED
    assert evidence['observation_error'] == 'a round went backwards'
    assert evidence['sessions']['bgperf_receiver1'] == {
        'accepted_prefixes': 40,
        'read_failures': {'polls': 3, 'first_reason': 'gone'},
    }


# --- what the run says out loud ------------------------------------------


def describe(**section):
    base_section = {'receivers': 2, 'receivers_complete': 2,
                    'incomplete_receivers': [], 'required_prefixes': REQUIRED,
                    'table_reached_s': 4.0, 'table_reached_resolution_s': 1.0,
                    'export_spread_s': 0.0, 'export_spread_resolution_s': 1.0,
                    'monitor_delta_s': 3.0, 'monitor_delta_resolution_s': 1.0,
                    'monitor_reached_required': True, 'sessions': {}}
    base_section.update(section)
    return bgperf2.describe_export_metrics(base_section)


def test_nothing_is_printed_for_a_run_with_no_fan_out():
    assert bgperf2.describe_export_metrics(None) == []


def test_a_served_fan_out_reports_its_span_and_its_lag_behind_the_monitor():
    lines = describe()

    assert '2 of 2 receiver(s) reached 100 prefix(es), the last in 4.0s' \
        in lines[0]
    assert 'within the 1.0s poll resolution of each other' in lines[0]
    assert '3.0s after the monitor reached the required count' in lines[1]


def test_a_spread_wider_than_one_look_is_reported_as_a_duration():
    lines = describe(export_spread_s=5.0)

    assert '5.0s between the first and last of them' in lines[0]


def test_a_delta_inside_one_look_is_not_reported_as_a_lag():
    lines = describe(monitor_delta_s=0.5)

    assert 'within the 1.0s poll resolution of each other' in lines[1]


def test_a_receiver_that_beat_the_monitor_is_said_so_rather_than_clamped():
    lines = describe(monitor_delta_s=-4.0)

    assert '4.0s before the monitor reached the required count' in lines[1]


def test_a_failed_run_does_not_blame_a_policy_for_its_own_failure():
    """`monitor_reached_required` is false for *every* failed run -- a stuck
    target, a lost session, a generator that never sent -- so the import-policy
    explanation would name a cause that was never configured, beside a row
    already marked FAILED with its own reason."""
    section = {'receivers': 3, 'receivers_complete': 0,
               'incomplete_receivers': ['bgperf_receiver0'],
               'required_prefixes': REQUIRED, 'table_reached_s': None,
               'export_spread_s': None, 'monitor_delta_s': None,
               'monitor_reached_required': False,
               'sessions': {'bgperf_receiver0': {'accepted_prefixes': 10}}}

    failed = bgperf2.describe_export_metrics(section, 'failed')
    converged = bgperf2.describe_export_metrics(section, 'converged')

    assert not any('import policy' in line for line in failed)
    assert 'the run did not converge' in failed[1]
    assert any('import policy' in line for line in converged)
    # And the first line never claims the run converged either.
    assert 'when the run converged' not in failed[0]


def test_a_stalled_receiver_is_named_with_what_it_last_held():
    lines = describe(
        receivers_complete=1, incomplete_receivers=['bgperf_receiver1'],
        table_reached_s=None, export_spread_s=None, monitor_delta_s=None,
        sessions={'bgperf_receiver1': {'accepted_prefixes': 40}})

    assert '1 of 2 receiver(s)' in lines[0]
    assert 'the delivery window closed' in lines[0]
    assert 'bgperf_receiver1 (last seen holding 40)' in lines[0]
    assert 'not comparable with the monitor' in lines[1]
    assert 'a receiver never got the whole table' in lines[1]


def test_an_unreachable_check_point_is_not_blamed_on_the_receivers():
    """The check-point takes no account of a `--filter_test` policy, so a
    policy that drops enough of the table puts it out of reach for every
    session in the run -- and every receiver would otherwise be named as though
    it had stalled. Read from the monitor rather than from the flag: whether a
    policy drops that much depends on the workload."""
    lines = describe(
        receivers_complete=0, incomplete_receivers=['bgperf_receiver0'],
        table_reached_s=None, export_spread_s=None, monitor_delta_s=None,
        monitor_reached_required=False,
        sessions={'bgperf_receiver0': {'accepted_prefixes': 900}})

    assert 'the monitor did not reach that count either' in lines[1]
    assert 'says nothing about the receivers' in lines[1]


def test_a_receiver_that_stalled_while_the_monitor_did_not_is_still_named():
    lines = describe(
        receivers_complete=1, incomplete_receivers=['bgperf_receiver1'],
        table_reached_s=None, export_spread_s=None, monitor_delta_s=None,
        monitor_reached_required=True,
        sessions={'bgperf_receiver1': {'accepted_prefixes': 40}})

    assert 'bgperf_receiver1 (last seen holding 40)' in lines[0]
    assert not any('the monitor did not reach that count' in line
                   for line in lines)


def test_the_section_says_whether_the_monitor_reached_the_count():
    export = drive([(2.0, {r: 100 for r in RECEIVERS})])
    required = event(EventKind.MONITOR_REQUIRED_REACHED, 3.0,
                     producer='bgperf_monitor')

    assert measured(export)['monitor_reached_required'] is False
    assert measured(export, [required])['monitor_reached_required'] is True


def test_a_poll_thread_that_raises_says_so_instead_of_dying_quietly():
    """It runs on a daemon thread, so anything escaping the narrow catch would
    end the poll silently -- leaving `is_alive()` false, no `poll_incomplete`,
    and the receivers it never reached published as a finding about the target
    rather than about a dead instrument."""
    class ExplodingRecorder:
        """A recorder whose failure is not one `observe_export_sample()` catches.

        The read itself is already guarded per receiver, so the way this
        happens for real is a fault in the recording step -- which catches only
        ValueError and TypeError, the shapes `observe()` documents.
        """

        required_prefixes = REQUIRED

        def observe(self, monotonic_s, accepted):
            raise RuntimeError('a fault the narrow catch does not cover')

    receivers = [FakeReceiver('bgperf_receiver0', [1])]
    state = {}
    stop = threading.Event()

    thread = bgperf2.controller_export_stats(
        receivers, ExplodingRecorder(), state, {}, stop, 0.01)
    thread.join(timeout=5)
    stop.set()

    assert not thread.is_alive()
    assert 'the receiver poll raised and stopped' in state['observation_error']


def test_a_stale_queue_is_not_allowed_to_date_the_next_workload():
    """The post-convergence workloads stamp their own start from the monitor
    sample they are holding when they issue the command, so a backlog makes the
    first burst look as though it began seconds before the `birdc` that carried
    it -- against a 1.0s published resolution."""
    q = queue_module.Queue()
    for i in range(5):
        q.put({'who': 'bgperf_monitor', 'monotonic_s': float(i)})

    assert bgperf2.drain_stale_samples(q) == 5
    assert q.empty()
    assert bgperf2.drain_stale_samples(q) == 0


def test_a_closing_round_is_taken_whichever_event_ends_the_window():
    """The wait listens to the delivery event, so a controller-only shutdown is
    seen by `ended()` at the top of the loop -- and that path must close the
    same way, or a teardown that did not go through the delivery event loses
    the last look."""
    receivers = [FakeReceiver('bgperf_receiver0', [0, 100])]
    export = recorder(['bgperf_receiver0'], REQUIRED, interval=0.01)
    stop = threading.Event()
    delivery = threading.Event()

    thread = bgperf2.controller_export_stats(
        receivers, export, {}, {}, stop, 0.01, delivery_stop=delivery)
    deadline = time.monotonic() + 5
    while receivers[0].reads < 1 and time.monotonic() < deadline:
        time.sleep(0.01)
    stop.set()                       # the controller's event, not delivery's
    thread.join(timeout=5)

    assert not thread.is_alive()
    assert export.accepted == {'bgperf_receiver0': 100}


def test_a_retired_recorder_ends_the_poll_rather_than_being_asked_again():
    receivers = [FakeReceiver('bgperf_receiver0', [1, 1, 1])]
    export = recorder(['bgperf_receiver0'], REQUIRED, interval=0.01)
    state = {'observation_error': 'a round was rejected'}
    stop = threading.Event()

    thread = bgperf2.controller_export_stats(
        receivers, export, state, {}, stop, 0.01)
    thread.join(timeout=5)
    stop.set()

    assert not thread.is_alive()
    # One round, then the closing one: a retired recorder collects nothing.
    assert receivers[0].reads <= 2


def test_the_teardown_wait_scales_with_the_fan_out():
    """A round is one serialised `docker exec` per receiver and nothing bounds
    that count, so a flat wait long enough for six expires on fifty -- and what
    it would drop is the closing round, the evidence that round exists to
    collect."""
    six = bgperf2.export_poll_teardown_wait_s(6)
    fifty = bgperf2.export_poll_teardown_wait_s(50)

    assert six >= bgperf2.EXPORT_POLL_TEARDOWN_WAIT_S
    # Two rounds at the measured ~0.63s a read is ~63s at fifty receivers.
    assert fifty > 63
    assert fifty > six


def test_a_truncated_poll_is_not_reported_as_a_retired_one():
    """Different findings: a rejected round killed the measurement, one that
    did not come back only truncates it. And `observation_error` is the key
    `observe_export_sample()` treats as the retirement flag, so putting a
    timeout note there would stop a still-running thread recording the very
    round the note is about."""
    export = drive([(1.0, {r: 40 for r in RECEIVERS})])
    _, evidence = bgperf2.export_lifecycle_summary(
        export, {'poll_incomplete': 'the receiver poll had not returned'},
        {}, REQUIRED)

    assert 'observation_error' not in evidence
    lines = describe(**{'poll_incomplete': evidence['poll_incomplete'],
                        'monitor_reached_required': True})
    assert not any('retired mid-run' in line for line in lines)
    assert any('had not returned' in line for line in lines)

    # The retirement flag still gates the recorder; a timeout note must not.
    state = {'poll_incomplete': 'truncated'}
    assert bgperf2.observe_export_sample(
        2.0, {r: 100 for r in RECEIVERS}, export, state) is True


def test_the_summary_copies_the_read_failures_it_publishes():
    """Where the teardown wait expired the poll thread is still writing these,
    and a record handed on by reference can change size between the summary and
    `json.dump()`."""
    export = drive([(1.0, {r: 40 for r in RECEIVERS})])
    live = {'polls': 1, 'first_reason': 'gone'}
    _, evidence = bgperf2.export_lifecycle_summary(
        export, {}, {'bgperf_receiver0': live}, REQUIRED)
    live['polls'] = 99

    assert evidence['sessions'][
        'bgperf_receiver0']['read_failures']['polls'] == 1


def test_the_event_stream_uses_the_order_the_section_publishes():
    """Two orders for one fan-out is a reader's problem, not a tie-break: the
    raw stream must not emit receiver0, receiver1, receiver10, receiver2 while
    `sessions` and `incomplete_receivers` list them by index."""
    names = ['bgperf_receiver{0}'.format(i) for i in range(12)]
    export = drive([(1.0, {name: REQUIRED for name in names})],
                   receivers=names)

    first_prefix = [e.producer for e in export.events
                    if e.kind is EventKind.RECEIVER_FIRST_PREFIX]
    assert first_prefix[:3] == ['bgperf_receiver0', 'bgperf_receiver1',
                                'bgperf_receiver2']
    assert first_prefix == sorted(first_prefix, key=natural_key)


def test_receivers_are_ordered_by_index_not_lexicographically():
    """Container names are not zero-padded, so a plain sort gives 0, 1, 10, 11,
    12, 2 -- and the printed line names only the first few incomplete ones, so
    a reader of a twenty-receiver run would be shown an arbitrary subset with
    2 through 9 hidden behind "and N more"."""
    names = ['bgperf_receiver{0}'.format(i) for i in range(12)]
    export = drive([(1.0, {name: 1 for name in names})], receivers=names)

    section = measured(export, receivers=names)
    assert section['incomplete_receivers'][:4] == [
        'bgperf_receiver0', 'bgperf_receiver1', 'bgperf_receiver2',
        'bgperf_receiver3']
    assert list(section['sessions'])[:3] == [
        'bgperf_receiver0', 'bgperf_receiver1', 'bgperf_receiver2']


def test_a_retired_poll_is_said_out_loud():
    lines = describe(observation_error='a round went backwards')

    assert 'the receiver poll was retired mid-run' in lines[-1]


# --- the run's document ---------------------------------------------------


class FakeComponent:
    stop_monitoring = False


def test_finish_bench_publishes_the_export_section(tmp_path, monkeypatch):
    '''The fan-out reaches the artifact by the same path the churn and reload
    sections do, on a run that failed as well as one that converged.'''
    args = Namespace(target='bird', label=None, neighbor_num=2,
                     prefix_num=100, tester_type='bird', single_table=False,
                     filter_test=None, receivers=2, results_dir=str(tmp_path))
    output_stats = {
        'max_cpu': 1.0, 'max_mem': 1, 'min_idle': 99, 'min_free': 1,
        'elapsed': datetime.timedelta(seconds=4),
        'first_received_time': datetime.timedelta(seconds=1),
        'tester_errors': 0, 'tester_timeouts': 0, 'required': REQUIRED,
        'recved': REQUIRED, 'monitor_wait_time': 0, 'cores': 1, 'memory': 1,
    }
    monkeypatch.setattr(bgperf2, 'collect_provenance',
                        lambda *a, **k: {'target': {'version': 'x'},
                                         'monitor': {'version': 'y'},
                                         'testers': []})
    monkeypatch.setattr(bgperf2, 'create_bench_graphs', lambda *a, **k: None)
    export = drive([(2.0, {r: 100 for r in RECEIVERS})])

    bgperf2.finish_bench(
        args, output_stats, [], time.time(), FakeComponent(), FakeComponent(),
        lifecycle_events=[origin()],
        export_lifecycle=export, export_state={},
        export_read_failures={}, export_required=REQUIRED)

    path = tmp_path / 'bird_bird_100_2_rx2.events.json'
    section = json.loads(path.read_text())['export']
    assert section['receivers_complete'] == 2
    assert section['table_reached_s'] == 2.0
    assert section['required_prefixes'] == REQUIRED
    assert section['sessions']['bgperf_receiver0']['accepted_prefixes'] == 100


def test_export_timing_is_withheld_when_a_second_workload_runs():
    '''Not a gap: the poll's window closes at convergence, which is exactly
    where churn and the reload begin, so coexisting costs something published
    either way. The fan-out is kept and its timing withheld, by name.'''
    events, evidence = bgperf2.export_lifecycle_summary(
        None, {}, {}, REQUIRED, ['bgperf_receiver0', 'bgperf_receiver1'],
        'this run also drives a post-convergence workload')

    assert events == ()
    assert 'post-convergence workload' in evidence['unmeasured_reason']
    section = event_artifact([origin()], 'converged',
                             export=evidence)['export']
    assert section['receivers'] == 2
    assert section['table_reached_s'] is None
    assert bgperf2.describe_export_metrics(section) == [
        'export fan-out: 2 receiver(s), not measured -- this run also drives '
        'a post-convergence workload']
