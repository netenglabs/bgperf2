'''Typed lifecycle events and pure helpers for benchmark measurements.

This module deliberately has no Docker or bgperf2 imports.  It is the shared
measurement vocabulary; runtime adapters can translate their existing queue
messages into these records incrementally.
'''

from dataclasses import dataclass, field
from enum import Enum
import json
import math
from types import MappingProxyType
from typing import Iterable, Mapping, Optional, Tuple


EVENT_ARTIFACT_SCHEMA = 'bgperf2/measurement-events/v1alpha1'


class EventKind(str, Enum):
    BENCH_CLOCK_STARTED = 'bench_clock_started'
    TESTER_SESSION_READY = 'tester_session_ready'
    TESTER_FIRST_UPDATE = 'tester_first_update'
    TESTER_LAST_UPDATE = 'tester_last_update'
    TESTER_COMPLETE = 'tester_complete'
    MONITOR_FIRST_PREFIX = 'monitor_first_prefix'
    MONITOR_REQUIRED_REACHED = 'monitor_required_reached'
    MONITOR_LAST_CHANGE = 'monitor_last_change'
    CONVERGENCE_CONFIRMED = 'convergence_confirmed'


class EventPhase(str, Enum):
    SETUP = 'setup'
    INJECTION = 'injection'
    CONVERGENCE = 'convergence'
    ASSURANCE = 'assurance'


EVENT_PHASE = {
    EventKind.BENCH_CLOCK_STARTED: EventPhase.SETUP,
    EventKind.TESTER_SESSION_READY: EventPhase.SETUP,
    EventKind.TESTER_FIRST_UPDATE: EventPhase.INJECTION,
    EventKind.TESTER_LAST_UPDATE: EventPhase.INJECTION,
    EventKind.TESTER_COMPLETE: EventPhase.INJECTION,
    EventKind.MONITOR_FIRST_PREFIX: EventPhase.CONVERGENCE,
    EventKind.MONITOR_REQUIRED_REACHED: EventPhase.CONVERGENCE,
    EventKind.MONITOR_LAST_CHANGE: EventPhase.CONVERGENCE,
    EventKind.CONVERGENCE_CONFIRMED: EventPhase.ASSURANCE,
}


class MeasurementEventError(ValueError):
    '''Base class for an invalid or ambiguous lifecycle-event calculation.'''


class DuplicateEventError(MeasurementEventError):
    '''Raised when a calculation requiring one event finds more than one.'''


class EventOrderError(MeasurementEventError):
    '''Raised when an interval endpoint precedes its start event.'''


@dataclass(frozen=True)
class LifecycleEvent:
    '''One observed benchmark event on a monotonic clock.'''

    kind: EventKind
    monotonic_s: float
    producer: str
    phase: EventPhase
    counters: Mapping[str, int] = field(default_factory=dict)
    details: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self):
        if not isinstance(self.kind, EventKind):
            raise TypeError('kind must be an EventKind')
        if not isinstance(self.phase, EventPhase):
            raise TypeError('phase must be an EventPhase')
        if self.phase != EVENT_PHASE[self.kind]:
            raise ValueError(
                '{0} must use the {1} phase'.format(
                    self.kind.value, EVENT_PHASE[self.kind].value))
        if not isinstance(self.monotonic_s, (int, float)) \
                or isinstance(self.monotonic_s, bool) \
                or not math.isfinite(self.monotonic_s):
            raise ValueError('monotonic_s must be a finite number')
        if not isinstance(self.producer, str) or not self.producer.strip():
            raise ValueError('producer must be a non-empty string')

        counters = dict(self.counters)
        if any(not isinstance(key, str) or not key for key in counters):
            raise ValueError('counter names must be non-empty strings')
        if any(not isinstance(value, int) or isinstance(value, bool)
               for value in counters.values()):
            raise ValueError('counter values must be integers')

        details = dict(self.details)
        if any(not isinstance(key, str) or not key for key in details):
            raise ValueError('detail names must be non-empty strings')
        try:
            json.dumps(details, allow_nan=False)
        except (TypeError, ValueError) as error:
            raise ValueError(
                'detail values must be JSON-compatible: {0}'.format(error)) from None

        object.__setattr__(self, 'monotonic_s', float(self.monotonic_s))
        object.__setattr__(self, 'counters', MappingProxyType(counters))
        object.__setattr__(self, 'details', MappingProxyType(details))

    def to_dict(self):
        '''Return the stable JSON-compatible shape used by future artifacts.'''
        return {
            'event': self.kind.value,
            'monotonic_s': self.monotonic_s,
            'producer': self.producer,
            'phase': self.phase.value,
            'counters': dict(self.counters),
            'details': dict(self.details),
        }


def ordered_events(events: Iterable[LifecycleEvent]) -> Tuple[LifecycleEvent, ...]:
    '''Return events in monotonic order, preserving input order for ties.'''
    return tuple(sorted(events, key=lambda event: event.monotonic_s))


def unique_event(events: Iterable[LifecycleEvent], kind: EventKind,
                 producer: Optional[str] = None) -> Optional[LifecycleEvent]:
    '''Return one matching event, None when missing, or reject ambiguity.'''
    matches = [event for event in events
               if event.kind == kind
               and (producer is None or event.producer == producer)]
    if len(matches) > 1:
        producer_description = producer if producer is not None else 'any producer'
        raise DuplicateEventError(
            'multiple {0} events for {1}'.format(kind.value, producer_description))
    return matches[0] if matches else None


def duration_s(events: Iterable[LifecycleEvent], start_kind: EventKind,
               end_kind: EventKind, start_producer: Optional[str] = None,
               end_producer: Optional[str] = None) -> Optional[float]:
    '''Calculate a monotonic interval, returning None for missing evidence.'''
    events = tuple(events)
    start = unique_event(events, start_kind, start_producer)
    end = unique_event(events, end_kind, end_producer)
    if start is None or end is None:
        return None
    if end.monotonic_s < start.monotonic_s:
        raise EventOrderError(
            '{0} at {1} precedes {2} at {3}'.format(
                end.kind.value, end.monotonic_s,
                start.kind.value, start.monotonic_s))
    return end.monotonic_s - start.monotonic_s


class MonitorEventRecorder:
    '''Translate monitor samples into the typed lifecycle vocabulary.

    The monitor remains a legacy queue producer.  This recorder is the narrow
    compatibility seam at the controller boundary: it observes accepted-count
    samples without knowing anything about Docker or daemon adapters.
    '''

    def __init__(self, bench_started_s, producer='monitor'):
        if not isinstance(producer, str) or not producer.strip():
            raise ValueError('producer must be a non-empty string')
        self.producer = producer
        self._events = [LifecycleEvent(
            EventKind.BENCH_CLOCK_STARTED,
            bench_started_s,
            'controller',
            EventPhase.SETUP,
        )]
        self._last_sample_s = None
        self._last_accepted = 0
        self._last_change = None
        self._confirmed = False

    @property
    def events(self):
        '''Return the current facts in deterministic monotonic order.'''
        # A final accepted-count change and confirmation can share a sample
        # timestamp. Keep the observed change before the verdict for that tie.
        confirmed = [event for event in self._events
                     if event.kind == EventKind.CONVERGENCE_CONFIRMED]
        events = [event for event in self._events
                  if event.kind != EventKind.CONVERGENCE_CONFIRMED]
        if self._last_change is not None:
            events.append(self._last_change)
        events.extend(confirmed)
        return ordered_events(events)

    def observe(self, monotonic_s, accepted_prefixes, required_reached=False):
        '''Record one monitor sample and its first/threshold/change events.'''
        if self._confirmed:
            raise MeasurementEventError(
                'cannot observe monitor samples after convergence is confirmed')
        if not isinstance(monotonic_s, (int, float)) \
                or isinstance(monotonic_s, bool) \
                or not math.isfinite(monotonic_s):
            raise ValueError('monotonic_s must be a finite number')
        monotonic_s = float(monotonic_s)
        if not isinstance(accepted_prefixes, int) \
                or isinstance(accepted_prefixes, bool) \
                or accepted_prefixes < 0:
            raise ValueError('accepted_prefixes must be a non-negative integer')

        origin_s = self._events[0].monotonic_s
        if monotonic_s < origin_s:
            raise EventOrderError('monitor sample precedes bench_clock_started')
        if self._last_sample_s is not None and monotonic_s < self._last_sample_s:
            raise EventOrderError('monitor samples are not monotonic')
        self._last_sample_s = monotonic_s

        counters = {'accepted_prefixes': accepted_prefixes}
        if accepted_prefixes > 0 and unique_event(
                self._events, EventKind.MONITOR_FIRST_PREFIX) is None:
            self._events.append(LifecycleEvent(
                EventKind.MONITOR_FIRST_PREFIX,
                monotonic_s,
                self.producer,
                EventPhase.CONVERGENCE,
                counters=counters,
            ))

        if required_reached and unique_event(
                self._events, EventKind.MONITOR_REQUIRED_REACHED) is None:
            self._events.append(LifecycleEvent(
                EventKind.MONITOR_REQUIRED_REACHED,
                monotonic_s,
                self.producer,
                EventPhase.CONVERGENCE,
                counters=counters,
            ))

        if accepted_prefixes != self._last_accepted:
            self._last_change = LifecycleEvent(
                EventKind.MONITOR_LAST_CHANGE,
                monotonic_s,
                self.producer,
                EventPhase.CONVERGENCE,
                counters=counters,
            )
        self._last_accepted = accepted_prefixes

    def confirm_convergence(self, monotonic_s=None):
        '''Record successful assurance at the most recently observed sample.'''
        if self._confirmed:
            raise DuplicateEventError('convergence is already confirmed')
        if self._last_sample_s is None:
            raise MeasurementEventError(
                'cannot confirm convergence before a monitor sample')
        if monotonic_s is None:
            monotonic_s = self._last_sample_s
        if monotonic_s < self._last_sample_s:
            raise EventOrderError(
                'convergence confirmation precedes the last monitor sample')
        self._events.append(LifecycleEvent(
            EventKind.CONVERGENCE_CONFIRMED,
            monotonic_s,
            self.producer,
            EventPhase.ASSURANCE,
            counters={'accepted_prefixes': self._last_accepted},
        ))
        self._confirmed = True


def monitor_metrics(events: Iterable[LifecycleEvent]):
    '''Derive the monitor-owned intervals from their named endpoints.'''
    events = tuple(events)
    return {
        'first_prefix_s': duration_s(
            events,
            EventKind.BENCH_CLOCK_STARTED,
            EventKind.MONITOR_FIRST_PREFIX,
            start_producer='controller',
        ),
        'convergence_s': duration_s(
            events,
            EventKind.BENCH_CLOCK_STARTED,
            EventKind.MONITOR_REQUIRED_REACHED,
            start_producer='controller',
        ),
        'assurance_s': duration_s(
            events,
            EventKind.MONITOR_REQUIRED_REACHED,
            EventKind.CONVERGENCE_CONFIRMED,
        ),
    }


def event_artifact(events: Iterable[LifecycleEvent], status):
    '''Build the stable JSON-compatible event artifact document.'''
    if status not in ('converged', 'failed'):
        raise ValueError('status must be converged or failed')
    events = ordered_events(events)
    return {
        'schema': EVENT_ARTIFACT_SCHEMA,
        'clock': 'monotonic',
        'status': status,
        'measurements': monitor_metrics(events),
        'events': [event.to_dict() for event in events],
    }
