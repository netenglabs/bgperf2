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


@dataclass(frozen=True)
class TesterOffering:
    '''One poll of what a single generator session has offered so far.

    `offered` is the generator's own cumulative count of updates it put on the
    wire.  None means the evidence could not be read, which is deliberately
    distinct from 0: a generator that has sent nothing and a generator we
    failed to ask must not produce the same measurement.

    `expected` comes from the run configuration, which is always known, and is
    what completion is judged against.  `configured` is the separate, optional
    observation of how large a table the generator says it actually loaded --
    a cross-check that it got the workload it was given, never the source of
    `expected`.  Deriving `expected` from the generator's own report would make
    a generator that loaded half its config look complete.

    `send_complete` is a generator's own statement that it finished the send
    contract, for the generators that make one.  None means it does not, and
    completion is inferred from the counts instead.
    '''

    established: bool
    expected: int
    offered: Optional[int] = None
    configured: Optional[int] = None
    tx_pending_bytes: Optional[int] = None
    pending_prefixes: Optional[int] = None
    send_complete: Optional[bool] = None

    def __post_init__(self):
        if not isinstance(self.established, bool):
            raise TypeError('established must be a bool')
        if self.send_complete is not None \
                and not isinstance(self.send_complete, bool):
            raise TypeError('send_complete must be a bool or None')
        for name in ('expected', 'offered', 'configured',
                     'tx_pending_bytes', 'pending_prefixes'):
            value = getattr(self, name)
            if value is None and name != 'expected':
                continue
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(
                    '{0} must be a non-negative integer'.format(name))

    @property
    def complete(self):
        '''True only on positive evidence that the whole table was offered.

        Gated on an established session with something to send. Without that,
        an `expected` of 0 makes any generator 'complete' on its first poll --
        which would emit `tester_complete` before `tester_session_ready` and
        order the lifecycle in a way no consumer can read.

        A generator that reports its own completion decides it, in both
        directions.  MRT playback is why: the size of the table an injector
        ends up with is a property of the MRT peer it was pointed at, not of
        the number the run asked for, so `offered >= expected` can stay false
        forever on an injector that has demonstrably sent everything it holds.
        The reverse matters just as much -- a generator that says it has *not*
        finished is not overruled by a count that happens to have reached
        `expected`, since its own report is the more direct evidence.

        Reported completion does not require a readable count, so it does not
        carry the `expected > 0` gate the paragraph above describes.  The
        ordering that gate protected is enforced where it belongs instead:
        TesterEventRecorder holds `tester_complete` until an update has been
        observed.
        '''
        if not self.established:
            return False
        if self.send_complete is not None:
            return self.send_complete
        return (self.expected > 0
                and self.offered is not None
                and self.offered >= self.expected)


class TesterEventRecorder:
    '''Translate polled generator counters into the lifecycle vocabulary.

    One recorder per tester container.  A container can drive several BGP
    sessions, and the aggregation across them is deliberately pessimistic: the
    tester is ready when its *last* session comes up and complete when its
    *slowest* session has offered its whole table.  Taking the first or the
    best would let one fast session hide a peer that stalled or never came up,
    which is the specific way a load generator lies about finishing.

    Nothing here synthesizes an event from monitor timestamps.  A run whose
    generator never reports completion simply has no `tester_complete`, and the
    derived injection interval is None rather than a plausible guess.
    '''

    def __init__(self, bench_started_s, producer, sample_interval_s=None):
        if not isinstance(producer, str) or not producer.strip():
            raise ValueError('producer must be a non-empty string')
        if sample_interval_s is not None:
            if not isinstance(sample_interval_s, (int, float)) \
                    or isinstance(sample_interval_s, bool) \
                    or not math.isfinite(sample_interval_s) \
                    or sample_interval_s <= 0:
                raise ValueError('sample_interval_s must be a positive number')
            sample_interval_s = float(sample_interval_s)
        if not isinstance(bench_started_s, (int, float)) \
                or isinstance(bench_started_s, bool) \
                or not math.isfinite(bench_started_s):
            raise ValueError('bench_started_s must be a finite number')
        self.producer = producer
        # Every derived tester interval is quantised by the poll cadence, so
        # each event carries it: an injection that measures 0.0s at a 1s poll
        # is not an instant injection, it is an unresolved one.
        self.sample_interval_s = sample_interval_s
        self._origin_s = float(bench_started_s)
        self._events = []
        self._sessions = None
        self._last_sample_s = None
        self._total_offered = 0
        self._last_update = None
        self._max_tx_pending_bytes = None
        self._max_pending_prefixes = None
        self._backpressure_readable = False

    def _details(self, extra=None):
        details = {}
        if self.sample_interval_s is not None:
            details['sample_interval_s'] = self.sample_interval_s
        if extra:
            details.update(extra)
        return details

    def _add(self, kind, monotonic_s, counters, details=None):
        self._events.append(LifecycleEvent(
            kind, monotonic_s, self.producer, EVENT_PHASE[kind],
            counters=counters, details=self._details(details)))

    @property
    def events(self):
        '''Return the recorded facts in deterministic monotonic order.'''
        # The final increase and the completion verdict land on the same poll,
        # so break that tie in causal order: the update was observed, and only
        # then did it satisfy the contract.
        complete = [e for e in self._events
                    if e.kind == EventKind.TESTER_COMPLETE]
        events = [e for e in self._events
                  if e.kind != EventKind.TESTER_COMPLETE]
        if self._last_update is not None:
            events.append(self._last_update)
        events.extend(complete)
        return ordered_events(events)

    @property
    def backpressure(self):
        '''Blocked-write evidence, or an explicit statement that there is none.

        BIRD 3 reports `TX pending: N bytes` per session; BIRD 2.19 has no
        equivalent field.  A run on 2.x must record that the evidence was
        unavailable -- reporting 0 would assert the generator was never blocked
        on a version that cannot tell us either way.
        '''
        if not self._backpressure_readable:
            return {
                'available': False,
                'reason': 'generator reported no blocked-write counter',
            }
        evidence = {'available': True}
        if self._max_tx_pending_bytes is not None:
            evidence['max_tx_pending_bytes'] = self._max_tx_pending_bytes
        if self._max_pending_prefixes is not None:
            evidence['max_pending_prefixes'] = self._max_pending_prefixes
        return evidence

    def observe(self, monotonic_s, sessions: Mapping[str, TesterOffering]):
        '''Record one poll covering every session this tester drives.'''
        if not isinstance(monotonic_s, (int, float)) \
                or isinstance(monotonic_s, bool) \
                or not math.isfinite(monotonic_s):
            raise ValueError('monotonic_s must be a finite number')
        monotonic_s = float(monotonic_s)
        if monotonic_s < self._origin_s:
            raise EventOrderError('tester sample precedes bench_clock_started')
        if self._last_sample_s is not None and monotonic_s < self._last_sample_s:
            raise EventOrderError('tester samples are not monotonic')
        if not sessions:
            raise MeasurementEventError('a tester sample needs at least one session')
        for offering in sessions.values():
            if not isinstance(offering, TesterOffering):
                raise TypeError('sessions must map to TesterOffering records')
        # A generator's peers are fixed by its configuration, so the caller
        # passes every one of them on every poll and marks an unreadable one
        # with offered=None. Silently dropping a key instead would let
        # `all(complete)` be satisfied by the sessions that happen to be left,
        # which is the same "fastest peer hides the slowest" failure this class
        # aggregates pessimistically to avoid -- only harder to see, because
        # the counters would look internally consistent.
        if self._sessions is None:
            self._sessions = frozenset(sessions)
        elif frozenset(sessions) != self._sessions:
            raise MeasurementEventError(
                'tester sessions changed between polls: expected {0}'.format(
                    sorted(self._sessions)))
        self._last_sample_s = monotonic_s

        offerings = list(sessions.values())
        expected = sum(o.expected for o in offerings)
        measured = [o.offered for o in offerings if o.offered is not None]
        # `offered` is published only when every session answered. Summing the
        # ones that did against an `expected` covering all of them reports a
        # shortfall that is really a failed read, and nothing downstream could
        # tell the two apart. `sessions_measured` says how much was legible.
        offered = sum(measured) if len(measured) == len(offerings) else None
        counters = {'sessions': len(offerings),
                    'sessions_measured': len(measured),
                    'expected_prefixes': expected}
        if offered is not None:
            counters['offered_prefixes'] = offered
        loaded = [o.configured for o in offerings if o.configured is not None]
        if len(loaded) == len(offerings):
            counters['configured_prefixes'] = sum(loaded)

        for o in offerings:
            # Either field is evidence. They come from different parts of the
            # CLI output, so a capture can carry one and not the other -- and
            # reporting 'no evidence' while holding a queue depth is the one
            # answer this must never give.
            if o.tx_pending_bytes is not None:
                self._backpressure_readable = True
                self._max_tx_pending_bytes = o.tx_pending_bytes \
                    if self._max_tx_pending_bytes is None \
                    else max(self._max_tx_pending_bytes, o.tx_pending_bytes)
            if o.pending_prefixes is not None:
                self._backpressure_readable = True
                self._max_pending_prefixes = o.pending_prefixes \
                    if self._max_pending_prefixes is None \
                    else max(self._max_pending_prefixes, o.pending_prefixes)

        if all(o.established for o in offerings) and unique_event(
                self._events, EventKind.TESTER_SESSION_READY) is None:
            self._add(EventKind.TESTER_SESSION_READY, monotonic_s, counters)

        if offered and unique_event(
                self._events, EventKind.TESTER_FIRST_UPDATE) is None:
            self._add(EventKind.TESTER_FIRST_UPDATE, monotonic_s, counters)

        # Polling continues until the monitor converges, so a cumulative
        # counter can still move after completion. Recording that would sort a
        # `tester_last_update` after `tester_complete`, inverting the
        # vocabulary's own ordering and the tail interval derived from it.
        completed = unique_event(
            self._events, EventKind.TESTER_COMPLETE) is not None
        if not completed and offered is not None \
                and offered > self._total_offered:
            self._last_update = LifecycleEvent(
                EventKind.TESTER_LAST_UPDATE, monotonic_s, self.producer,
                EVENT_PHASE[EventKind.TESTER_LAST_UPDATE],
                counters=counters, details=self._details())
            self._total_offered = offered

        # Completion is held until an update has been observed. A generator that
        # reports its own completion can say so on a poll where its counters
        # were not yet legible, and recording that would put `tester_complete`
        # before the `tester_first_update` a later poll finds -- an inverted
        # stream that `tester_metrics()` rejects with an EventOrderError, out of
        # `finish_bench()`, killing a run that had already converged. The
        # first-update event above is recorded earlier in this same poll, so a
        # generator whose completion and first legible count arrive together
        # still completes on that poll.
        if all(o.complete for o in offerings) \
                and unique_event(
                    self._events, EventKind.TESTER_FIRST_UPDATE) is not None \
                and unique_event(
                    self._events, EventKind.TESTER_COMPLETE) is None:
            self._add(EventKind.TESTER_COMPLETE, monotonic_s, counters,
                      {'backpressure': self.backpressure})


def tester_metrics(events: Iterable[LifecycleEvent], producer: str):
    '''Derive one generator's owned intervals from its named endpoints.

    `events` must include the controller's `bench_clock_started`, which a
    TesterEventRecorder does not produce: the run has one clock origin, and a
    second copy per tester would make every merged lookup ambiguous. Callers
    merge the controller's events in. A missing origin raises rather than
    returning a null startup interval, because that is a wiring mistake that
    would otherwise be published as a measurement.
    '''
    events = tuple(events)
    if unique_event(events, EventKind.BENCH_CLOCK_STARTED,
                    'controller') is None:
        raise MeasurementEventError(
            'tester metrics need the controller bench_clock_started event')
    startup_s = duration_s(
        events, EventKind.BENCH_CLOCK_STARTED, EventKind.TESTER_SESSION_READY,
        start_producer='controller', end_producer=producer)
    injection_s = duration_s(
        events, EventKind.TESTER_FIRST_UPDATE, EventKind.TESTER_COMPLETE,
        start_producer=producer, end_producer=producer)

    complete = unique_event(events, EventKind.TESTER_COMPLETE, producer)
    first = unique_event(events, EventKind.TESTER_FIRST_UPDATE, producer)
    offered = complete.counters.get('offered_prefixes') if complete else None

    # The rate's numerator has to be the prefixes offered *inside* the interval
    # it is divided by. `injection_s` starts at the first poll that saw a
    # nonzero count, by which time that many prefixes were already on the wire;
    # dividing the running total by it counts them twice and biases the rate
    # high -- most on a short run, but always upward.
    #
    # A rate also needs a measured interval to divide by. At a 1s poll a small
    # workload finishes inside one sample, and 'offered / 0' is not an infinite
    # rate, it is an interval too short for this instrument to resolve.
    #
    # `offered_in_interval` is published beside the rate because on its own the
    # rate cannot be read safely. BIRD 2.19 counts an export when the route is
    # handed to the BGP protocol, not when it reaches the wire, so a 1M-prefix
    # table is already fully 'offered' at the first poll: measured at 0.2s
    # intervals that run reported 21452 prefixes/s, which is the slope of the
    # last 6436 prefixes and not the generator's send rate at all. Saying how
    # much of the table the interval covers makes that visible instead of
    # publishing a precise-looking artifact of the poll cadence.
    rate = None
    offered_in_interval = None
    if offered is not None and first is not None:
        already_sent = first.counters.get('offered_prefixes')
        # BIRD resets a protocol's route-change stats when the protocol
        # restarts, so a session that flapped mid-run can report fewer offered
        # prefixes at completion than at the first update. That is not a
        # negative send rate, it is a counter this instrument cannot read
        # across the reset.
        if already_sent is not None and offered >= already_sent:
            offered_in_interval = offered - already_sent
            if injection_s:
                rate = offered_in_interval / injection_s

    return {
        'tester_startup_s': startup_s,
        'injection_s': injection_s,
        'offered_prefixes': offered,
        'offered_in_interval': offered_in_interval,
        'offered_rate_pps': rate,
    }


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


def event_artifact(events: Iterable[LifecycleEvent], status, testers=None):
    '''Build the stable JSON-compatible event artifact document.

    `testers` maps a generator's producer name to whatever evidence it holds
    outside the event stream -- blocked-write availability, a poll that could
    not be recorded. Its intervals are derived from the events themselves, so a
    generator that produced none is reported with null intervals rather than
    left out: a run where the tester was never readable and a run with no
    tester at all must not produce the same document.
    '''
    if status not in ('converged', 'failed'):
        raise ValueError('status must be converged or failed')
    events = ordered_events(events)
    artifact = {
        'schema': EVENT_ARTIFACT_SCHEMA,
        'clock': 'monotonic',
        'status': status,
        'measurements': monitor_metrics(events),
        'events': [event.to_dict() for event in events],
    }
    if testers:
        artifact['testers'] = {
            producer: _tester_section(events, producer, evidence)
            for producer, evidence in testers.items()
        }
    return artifact


def _tester_section(events, producer, evidence):
    '''One generator's derived intervals, plus its non-event evidence.

    The evidence is caller-supplied, so it is refused where it would land on a
    derived name. Merging blindly would let a caller overwrite a measured
    interval with a value nothing in the event stream supports -- which is the
    one thing this artifact exists to make impossible.
    '''
    measured = tester_metrics(events, producer)
    evidence = dict(evidence or {})
    collisions = sorted(set(evidence) & set(measured))
    if collisions:
        raise MeasurementEventError(
            'tester evidence for {0} would overwrite derived {1}'.format(
                producer, ', '.join(collisions)))
    measured.update(evidence)
    return measured
