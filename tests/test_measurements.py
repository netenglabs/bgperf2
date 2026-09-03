'''Docker-free contract tests for typed lifecycle events.'''

import json

import pytest

from measurements import (
    DuplicateEventError,
    EVENT_PHASE,
    EventKind,
    EventOrderError,
    EventPhase,
    LifecycleEvent,
    MeasurementEventError,
    MonitorEventRecorder,
    duration_s,
    event_artifact,
    monitor_metrics,
    ordered_events,
    unique_event,
)


def event(kind, timestamp, producer='controller', phase=None,
          **kwargs):
    phase = phase or EVENT_PHASE[kind]
    return LifecycleEvent(kind, timestamp, producer, phase, **kwargs)


def test_event_has_stable_serializable_fields():
    observed = event(
        EventKind.MONITOR_FIRST_PREFIX,
        12,
        producer='monitor',
        counters={'accepted_prefixes': 1},
        details={'afi': 'ipv4'},
    )

    assert json.loads(json.dumps(observed.to_dict())) == {
        'event': 'monitor_first_prefix',
        'monotonic_s': 12.0,
        'producer': 'monitor',
        'phase': 'convergence',
        'counters': {'accepted_prefixes': 1},
        'details': {'afi': 'ipv4'},
    }


def test_event_defensively_copies_optional_mappings():
    counters = {'accepted_prefixes': 1}
    observed = event(EventKind.MONITOR_FIRST_PREFIX, 12, counters=counters)

    counters['accepted_prefixes'] = 2

    assert observed.counters['accepted_prefixes'] == 1
    with pytest.raises(TypeError):
        observed.counters['accepted_prefixes'] = 3


def test_event_rejects_a_phase_that_disagrees_with_its_meaning():
    with pytest.raises(ValueError, match='must use the assurance phase'):
        event(EventKind.CONVERGENCE_CONFIRMED, 12, phase=EventPhase.CONVERGENCE)


def test_event_rejects_details_that_cannot_be_persisted_as_json():
    with pytest.raises(ValueError, match='JSON-compatible'):
        event(EventKind.MONITOR_FIRST_PREFIX, 12, details={'bad': object()})


@pytest.mark.parametrize('timestamp', [float('nan'), float('inf'), True, '12'])
def test_event_rejects_non_monotonic_clock_values(timestamp):
    with pytest.raises(ValueError):
        event(EventKind.BENCH_CLOCK_STARTED, timestamp)


def test_ordered_events_uses_monotonic_time_and_is_stable_for_ties():
    later = event(EventKind.CONVERGENCE_CONFIRMED, 9)
    tied_first = event(EventKind.MONITOR_REQUIRED_REACHED, 4)
    tied_second = event(EventKind.MONITOR_LAST_CHANGE, 4)

    assert ordered_events([later, tied_first, tied_second]) == (
        tied_first, tied_second, later)


def test_unique_event_returns_none_for_missing_evidence():
    assert unique_event([], EventKind.TESTER_COMPLETE) is None


def test_unique_event_can_disambiguate_multiple_testers():
    events = [
        event(EventKind.TESTER_COMPLETE, 3, producer='tester0'),
        event(EventKind.TESTER_COMPLETE, 4, producer='tester1'),
    ]

    assert unique_event(
        events, EventKind.TESTER_COMPLETE, producer='tester1').monotonic_s == 4
    with pytest.raises(DuplicateEventError):
        unique_event(events, EventKind.TESTER_COMPLETE)


def test_duration_uses_named_monotonic_events_across_producers():
    events = [
        event(EventKind.BENCH_CLOCK_STARTED, 100, phase=EventPhase.SETUP),
        event(EventKind.MONITOR_REQUIRED_REACHED, 142.25, producer='monitor'),
    ]

    assert duration_s(
        events,
        EventKind.BENCH_CLOCK_STARTED,
        EventKind.MONITOR_REQUIRED_REACHED,
        start_producer='controller',
        end_producer='monitor',
    ) == 42.25


def test_duration_is_unavailable_when_an_endpoint_is_missing():
    events = [event(EventKind.TESTER_FIRST_UPDATE, 10, producer='tester0',
                    phase=EventPhase.INJECTION)]

    assert duration_s(
        events,
        EventKind.TESTER_FIRST_UPDATE,
        EventKind.TESTER_COMPLETE,
        start_producer='tester0',
        end_producer='tester0',
    ) is None


def test_duration_rejects_reversed_event_order():
    events = [
        event(EventKind.TESTER_FIRST_UPDATE, 10, producer='tester0',
              phase=EventPhase.INJECTION),
        event(EventKind.TESTER_COMPLETE, 9, producer='tester0',
              phase=EventPhase.INJECTION),
    ]

    with pytest.raises(EventOrderError):
        duration_s(
            events,
            EventKind.TESTER_FIRST_UPDATE,
            EventKind.TESTER_COMPLETE,
            start_producer='tester0',
            end_producer='tester0',
        )


def test_monitor_queue_samples_become_named_events_and_metrics():
    recorder = MonitorEventRecorder(100, producer='bgperf_monitor')

    recorder.observe(101, accepted_prefixes=0)
    recorder.observe(102, accepted_prefixes=1)
    recorder.observe(103, accepted_prefixes=990, required_reached=True)
    recorder.observe(104, accepted_prefixes=1000, required_reached=True)
    recorder.observe(108, accepted_prefixes=1000, required_reached=True)
    recorder.confirm_convergence()

    assert [observed.kind for observed in recorder.events] == [
        EventKind.BENCH_CLOCK_STARTED,
        EventKind.MONITOR_FIRST_PREFIX,
        EventKind.MONITOR_REQUIRED_REACHED,
        EventKind.MONITOR_LAST_CHANGE,
        EventKind.CONVERGENCE_CONFIRMED,
    ]
    assert monitor_metrics(recorder.events) == {
        'first_prefix_s': 2,
        'convergence_s': 3,
        'assurance_s': 5,
    }
    last_change = unique_event(recorder.events, EventKind.MONITOR_LAST_CHANGE)
    assert last_change.monotonic_s == 104
    assert last_change.counters == {'accepted_prefixes': 1000}


def test_failure_before_first_prefix_keeps_metrics_unavailable():
    recorder = MonitorEventRecorder(100)
    recorder.observe(116, accepted_prefixes=0)

    artifact = event_artifact(recorder.events, status='failed')

    assert [observed['event'] for observed in artifact['events']] == [
        'bench_clock_started']
    assert artifact['measurements'] == {
        'first_prefix_s': None,
        'convergence_s': None,
        'assurance_s': None,
    }


def test_failure_during_assurance_does_not_invent_confirmation():
    recorder = MonitorEventRecorder(100)
    recorder.observe(102, accepted_prefixes=1)
    recorder.observe(105, accepted_prefixes=990, required_reached=True)

    artifact = event_artifact(recorder.events, status='failed')

    assert artifact['measurements']['convergence_s'] == 5
    assert artifact['measurements']['assurance_s'] is None
    assert 'convergence_confirmed' not in {
        observed['event'] for observed in artifact['events']}


def test_monitor_recorder_rejects_out_of_order_samples():
    recorder = MonitorEventRecorder(100)
    recorder.observe(102, accepted_prefixes=1)

    with pytest.raises(EventOrderError, match='not monotonic'):
        recorder.observe(101, accepted_prefixes=2)


def test_monitor_recorder_validates_zero_prefix_sample_timestamp():
    recorder = MonitorEventRecorder(100)

    with pytest.raises(ValueError, match='finite number'):
        recorder.observe(float('nan'), accepted_prefixes=0)


def test_last_change_precedes_confirmation_when_sample_times_tie():
    recorder = MonitorEventRecorder(100)
    recorder.observe(105, accepted_prefixes=990, required_reached=True)
    recorder.confirm_convergence()

    assert [observed.kind for observed in recorder.events][-2:] == [
        EventKind.MONITOR_LAST_CHANGE,
        EventKind.CONVERGENCE_CONFIRMED,
    ]


def test_a_tester_with_no_events_reports_null_intervals_rather_than_absence():
    '''A generator that was polled and never answered must still appear: a run
    where the tester was unreadable and a run with no tester at all are
    different results.'''
    recorder = MonitorEventRecorder(0, producer='monitor')
    recorder.observe(1, 0)

    artifact = event_artifact(recorder.events, status='failed',
                              testers={'tester': {'backpressure': {'available': False}}})

    assert artifact['testers']['tester'] == {
        'tester_startup_s': None,
        'startup_resolution_s': None,
        'injection_s': None,
        'injection_resolution_s': None,
        'reported_injection_s': None,
        'offered_prefixes': None,
        'offered_in_interval': None,
        'offered_rate_pps': None,
        'octets_on_wire': None,
        'backpressure': {'available': False},
    }


def test_an_artifact_without_testers_keeps_its_original_shape():
    recorder = MonitorEventRecorder(0, producer='monitor')
    recorder.observe(1, 0)

    artifact = event_artifact(recorder.events, status='failed')

    assert set(artifact) == {'schema', 'clock', 'status', 'measurements', 'events'}


def test_tester_evidence_cannot_overwrite_a_derived_interval():
    '''The evidence beside the events is caller-supplied. Letting it land on a
    derived name would publish an interval the event stream does not support.'''
    recorder = MonitorEventRecorder(0, producer='monitor')
    recorder.observe(1, 0)

    with pytest.raises(MeasurementEventError, match='injection_s'):
        event_artifact(recorder.events, status='failed',
                       testers={'tester': {'injection_s': 4.0}})
