'''Typed lifecycle events and pure helpers for benchmark measurements.

This module deliberately has no Docker or bgperf2 imports.  It is the shared
measurement vocabulary; runtime adapters can translate their existing queue
messages into these records incrementally.
'''

from dataclasses import dataclass, field
from enum import Enum
import json
import math
import re
from types import MappingProxyType
from typing import Iterable, Mapping, Optional, Tuple


EVENT_ARTIFACT_SCHEMA = 'bgperf2/measurement-events/v1alpha1'


class EventKind(str, Enum):
    BENCH_CLOCK_STARTED = 'bench_clock_started'
    TESTER_SESSION_READY = 'tester_session_ready'
    TESTER_FIRST_UPDATE = 'tester_first_update'
    TESTER_LAST_UPDATE = 'tester_last_update'
    TESTER_COMPLETE = 'tester_complete'
    RECEIVER_FIRST_PREFIX = 'receiver_first_prefix'
    RECEIVER_TABLE_REACHED = 'receiver_table_reached'
    MONITOR_FIRST_PREFIX = 'monitor_first_prefix'
    MONITOR_REQUIRED_REACHED = 'monitor_required_reached'
    MONITOR_LAST_CHANGE = 'monitor_last_change'
    CONVERGENCE_CONFIRMED = 'convergence_confirmed'
    CHURN_BURST_STARTED = 'churn_burst_started'
    CHURN_WITHDRAW_COMPLETE = 'churn_withdraw_complete'
    CHURN_BURST_COMPLETE = 'churn_burst_complete'
    POLICY_RELOAD_STARTED = 'policy_reload_started'
    POLICY_RELOAD_COMPLETE = 'policy_reload_complete'


class EventPhase(str, Enum):
    SETUP = 'setup'
    INJECTION = 'injection'
    CONVERGENCE = 'convergence'
    ASSURANCE = 'assurance'
    # What the target put on its other export sessions. The monitor is one
    # export session and its events are the run's convergence; a receiver's are
    # not, and must never be read as it. A reader grouping this stream by phase
    # would otherwise find several first-prefix intervals under `convergence`
    # with nothing saying which of them the row's `elapsed (s)` came from.
    EXPORT = 'export'
    # Everything after the table has been delivered and confirmed. A churn
    # burst is a second workload run against a converged target, so its events
    # must not share a phase with the initial delivery -- a reader grouping by
    # phase would otherwise find two `injection` intervals in one document and
    # no way to tell which one the row's `elapsed (s)` came from.
    CHURN = 'churn'
    # A policy reload is a third workload run against the converged target, and
    # it gets a phase of its own for the reason churn has one: a reader
    # grouping by phase must never find two intervals under one name with
    # nothing saying which of them the row describes. It is separate from
    # `CHURN` as well -- both happen after convergence, but one measures a
    # table moving under a fixed policy and the other a fixed table under a
    # policy that moved, and averaging those would describe neither.
    POLICY_RELOAD = 'policy_reload'


EVENT_PHASE = {
    EventKind.BENCH_CLOCK_STARTED: EventPhase.SETUP,
    EventKind.TESTER_SESSION_READY: EventPhase.SETUP,
    EventKind.TESTER_FIRST_UPDATE: EventPhase.INJECTION,
    EventKind.TESTER_LAST_UPDATE: EventPhase.INJECTION,
    EventKind.TESTER_COMPLETE: EventPhase.INJECTION,
    EventKind.RECEIVER_FIRST_PREFIX: EventPhase.EXPORT,
    EventKind.RECEIVER_TABLE_REACHED: EventPhase.EXPORT,
    EventKind.MONITOR_FIRST_PREFIX: EventPhase.CONVERGENCE,
    EventKind.MONITOR_REQUIRED_REACHED: EventPhase.CONVERGENCE,
    EventKind.MONITOR_LAST_CHANGE: EventPhase.CONVERGENCE,
    EventKind.CONVERGENCE_CONFIRMED: EventPhase.ASSURANCE,
    EventKind.CHURN_BURST_STARTED: EventPhase.CHURN,
    EventKind.CHURN_WITHDRAW_COMPLETE: EventPhase.CHURN,
    EventKind.CHURN_BURST_COMPLETE: EventPhase.CHURN,
    EventKind.POLICY_RELOAD_STARTED: EventPhase.POLICY_RELOAD,
    EventKind.POLICY_RELOAD_COMPLETE: EventPhase.POLICY_RELOAD,
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


def signed_duration_s(events: Iterable[LifecycleEvent], start_kind: EventKind,
                      end_kind: EventKind, start_producer: Optional[str] = None,
                      end_producer: Optional[str] = None) -> Optional[float]:
    '''Calculate a monotonic interval that is allowed to run backwards.

    `duration_s()` refuses an inverted interval, and should: a monitor that
    reached its first prefix before the clock started is a wiring fault, not a
    negative duration. But an interval spanning two producers can legitimately
    close before it opens -- the target can reach the required route count
    while a generator is still finishing -- and there the sign is the finding.
    Clamping it at zero would report an overlap as an instant tail.

    Use this only where the contract says what a negative value means. Every
    interval owned by one producer stays with `duration_s()`.
    '''
    events = tuple(events)
    start = unique_event(events, start_kind, start_producer)
    end = unique_event(events, end_kind, end_producer)
    if start is None or end is None:
        return None
    return end.monotonic_s - start.monotonic_s


def _resolution_for_poll(monotonic_s, since_s, sample_interval_s):
    '''How coarsely one poll of a loop can place an event in time.

    An event is dated to the poll that saw it, so its timestamp is known only
    to within the gap since the previous look -- and on the first poll, to
    within everything that happened since the clock started, which is where
    work that finished before the instrument arrived shows up honestly rather
    than as an instant.

    The requested cadence is a floor on that gap, never the answer. Both poll
    loops here stamp a sample, read a container, and only then wait, so the
    cadence achieved is `read + wait` and publishing the nominal interval
    understates the resolution by the cost of the read -- which for a 50-100
    peer BIRD tester, or a `gobgp neighbor -j` exec, is not small.
    Understating it is the one direction that matters: these are the numbers
    that qualify an interval as unresolved instead of instant, so a poll
    reports the coarser of the interval asked for and the gap it achieved.
    '''
    gap = monotonic_s - since_s
    if sample_interval_s is None:
        return gap
    return max(gap, sample_interval_s)


def _validated_interval(sample_interval_s):
    '''Accept a positive finite poll cadence, or no declared cadence at all.'''
    if sample_interval_s is None:
        return None
    if not isinstance(sample_interval_s, (int, float)) \
            or isinstance(sample_interval_s, bool) \
            or not math.isfinite(sample_interval_s) \
            or sample_interval_s <= 0:
        raise ValueError('sample_interval_s must be a positive number')
    return float(sample_interval_s)


class MonitorEventRecorder:
    '''Translate monitor samples into the typed lifecycle vocabulary.

    The monitor remains a legacy queue producer.  This recorder is the narrow
    compatibility seam at the controller boundary: it observes accepted-count
    samples without knowing anything about Docker or daemon adapters.
    '''

    def __init__(self, bench_started_s, producer='monitor',
                 sample_interval_s=None):
        if not isinstance(producer, str) or not producer.strip():
            raise ValueError('producer must be a non-empty string')
        self.producer = producer
        # The cadence the monitor loop was asked for, and so only the floor of
        # the resolution it achieves -- it execs `gobgp neighbor -j` and only
        # then waits. Every monitor-owned interval is quantised by how often
        # the instrument actually looked, so each event carries that gap: a
        # `first_prefix_s` of 0.0s at a 1s poll is not an instant first
        # prefix, it is one the monitor could not resolve.
        self.sample_interval_s = _validated_interval(sample_interval_s)
        self._origin_s = float(bench_started_s)
        self._events = [LifecycleEvent(
            EventKind.BENCH_CLOCK_STARTED,
            bench_started_s,
            'controller',
            EventPhase.SETUP,
        )]
        self._last_sample_s = None
        self._poll_resolution_s = None
        self._last_accepted = 0
        self._last_change = None
        self._confirmed = False

    def _details(self):
        details = {}
        if self.sample_interval_s is not None:
            details['sample_interval_s'] = self.sample_interval_s
        if self._poll_resolution_s is not None:
            details['poll_resolution_s'] = self._poll_resolution_s
        return details

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
        self._poll_resolution_s = _resolution_for_poll(
            monotonic_s,
            self._origin_s if self._last_sample_s is None
            else self._last_sample_s,
            self.sample_interval_s)
        self._last_sample_s = monotonic_s

        counters = {'accepted_prefixes': accepted_prefixes}
        details = self._details()
        if accepted_prefixes > 0 and unique_event(
                self._events, EventKind.MONITOR_FIRST_PREFIX) is None:
            self._events.append(LifecycleEvent(
                EventKind.MONITOR_FIRST_PREFIX,
                monotonic_s,
                self.producer,
                EventPhase.CONVERGENCE,
                counters=counters,
                details=details,
            ))

        if required_reached and unique_event(
                self._events, EventKind.MONITOR_REQUIRED_REACHED) is None:
            self._events.append(LifecycleEvent(
                EventKind.MONITOR_REQUIRED_REACHED,
                monotonic_s,
                self.producer,
                EventPhase.CONVERGENCE,
                counters=counters,
                details=details,
            ))

        if accepted_prefixes != self._last_accepted:
            self._last_change = LifecycleEvent(
                EventKind.MONITOR_LAST_CHANGE,
                monotonic_s,
                self.producer,
                EventPhase.CONVERGENCE,
                counters=counters,
                details=details,
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
        # Carries the last sample's resolution, not a gap measured to the
        # confirmation stamp. Assurance is a verdict on that sample rather
        # than a fresh look at the monitor, so what bounds it in time is how
        # wide the look was that supplied the count it ruled on.
        self._events.append(LifecycleEvent(
            EventKind.CONVERGENCE_CONFIRMED,
            monotonic_s,
            self.producer,
            EventPhase.ASSURANCE,
            counters={'accepted_prefixes': self._last_accepted},
            details=self._details(),
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

    `octets_on_wire` is the cumulative bytes the generator says a successful
    write() put on the socket.  It is the one wire-side number these polls
    carry: `offered` is counted where a route is handed to the session's write
    buffer, so on a generator whose encoder outruns its socket the two diverge,
    and a real bgpdump2 capture shows exactly that -- 9,981 prefixes encoded
    against 88 octets written.  Reported beside `offered`, never instead of it.

    `reported_send_duration_s` is the generator's own measurement of how long
    its send took, for the generators that make one.  It is on the generator's
    clock and bounded by its own definition of sending, so it is evidence
    beside the controller's polled interval and not a substitute for it -- but
    at MRT playback speeds it is the only evidence that exists, because a walk
    that finishes in a millisecond is over before the first poll looks.

    `tx_pending_bytes` and `pending_prefixes` are queue depths: how much the
    generator was holding when it was looked at.  `blocked_writes` and
    `send_stalls` are the other kind of blocked-write evidence, cumulative
    counts of the times it was held up -- writes the socket took only part of,
    and passes where the generator could not hand over any more because its own
    buffer had not drained.  A generator may expose either kind, both, or
    neither; None means it was not asked or could not say, never zero.
    '''

    established: bool
    expected: int
    offered: Optional[int] = None
    configured: Optional[int] = None
    tx_pending_bytes: Optional[int] = None
    pending_prefixes: Optional[int] = None
    blocked_writes: Optional[int] = None
    send_stalls: Optional[int] = None
    send_complete: Optional[bool] = None
    octets_on_wire: Optional[int] = None
    reported_send_duration_s: Optional[float] = None

    def __post_init__(self):
        if not isinstance(self.established, bool):
            raise TypeError('established must be a bool')
        if self.send_complete is not None \
                and not isinstance(self.send_complete, bool):
            raise TypeError('send_complete must be a bool or None')
        if self.reported_send_duration_s is not None:
            value = self.reported_send_duration_s
            if not isinstance(value, (int, float)) or isinstance(value, bool) \
                    or not math.isfinite(value) or value < 0:
                raise ValueError(
                    'reported_send_duration_s must be a non-negative number')
            object.__setattr__(
                self, 'reported_send_duration_s', float(value))
        for name in ('expected', 'offered', 'configured',
                     'tx_pending_bytes', 'pending_prefixes', 'octets_on_wire',
                     'blocked_writes', 'send_stalls'):
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
        sample_interval_s = _validated_interval(sample_interval_s)
        if not isinstance(bench_started_s, (int, float)) \
                or isinstance(bench_started_s, bool) \
                or not math.isfinite(bench_started_s):
            raise ValueError('bench_started_s must be a finite number')
        self.producer = producer
        # The cadence the poll loop was *asked* for. Every derived tester
        # interval is quantised by how often the generator is actually looked
        # at, so each event carries a resolution: an injection that measures
        # 0.0s at a 1s poll is not an instant injection, it is an unresolved
        # one. This value is only the floor of that resolution -- see
        # _resolution_for(), which reports the gap the loop achieved.
        self.sample_interval_s = sample_interval_s
        self._origin_s = float(bench_started_s)
        self._events = []
        self._sessions = None
        self._last_sample_s = None
        self._poll_resolution_s = None
        self._total_offered = 0
        self._last_update = None
        self._max_tx_pending_bytes = None
        self._max_pending_prefixes = None
        self._max_blocked_writes = None
        self._max_send_stalls = None
        self._backpressure_readable = False
        self._reported_send_duration_s = None

    def _resolution_for(self, monotonic_s):
        '''How coarsely this poll can place an event in time.

        A generator whose entire walk finished before the instrument arrived
        shows up in the first poll's resolution -- everything since the clock
        started -- rather than as an instant injection.
        '''
        return _resolution_for_poll(
            monotonic_s,
            self._origin_s if self._last_sample_s is None
            else self._last_sample_s,
            self.sample_interval_s)

    def _details(self, extra=None):
        details = {}
        if self.sample_interval_s is not None:
            details['sample_interval_s'] = self.sample_interval_s
        if self._poll_resolution_s is not None:
            details['poll_resolution_s'] = self._poll_resolution_s
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
        equivalent field, and bgpdump2 has none unless the run turned on its IO
        log class.  A generator that cannot tell us either way must record that
        the evidence was unavailable -- reporting 0 would assert it was never
        blocked on the strength of a counter nobody read.
        '''
        if not self._backpressure_readable:
            return {
                'available': False,
                'reason': 'generator reported no blocked-write counter',
            }
        evidence = {'available': True}
        for key, value in (
                ('max_tx_pending_bytes', self._max_tx_pending_bytes),
                ('max_pending_prefixes', self._max_pending_prefixes),
                ('max_blocked_writes', self._max_blocked_writes),
                ('max_send_stalls', self._max_send_stalls)):
            if value is not None:
                evidence[key] = value
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
        # Computed before _last_sample_s moves, and before any event is added,
        # so every event this poll produces carries the resolution of the poll
        # that produced it.
        self._poll_resolution_s = self._resolution_for(monotonic_s)
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
        # Wire-side bytes, summed under the same rule as the prefix counts and
        # for the same reason: a total covering only the sessions that answered
        # would read as a small transfer rather than as a partial reading.
        written = [o.octets_on_wire for o in offerings
                   if o.octets_on_wire is not None]
        if len(written) == len(offerings):
            counters['octets_on_wire'] = sum(written)
        # A generator's own send duration is per session, so the sessions are
        # not summed -- that would add up intervals that ran at the same time.
        # The longest is taken, matching how this class aggregates everything
        # else: the container is done when its slowest session is. It stays a
        # lower bound on the container's whole send span, since two sessions
        # that started at different moments span more than the longer of them.
        #
        # Rebuilt every poll, cleared included. The counters above are rebuilt
        # by construction because they live in this poll's `counters` dict;
        # this one is held on the recorder so that the completion event can
        # carry it, and a value that merely persisted would be published
        # against a poll that could not read it -- mixing two polls' evidence
        # into the one event whose whole job is to say what was true when the
        # generator finished.
        durations = [o.reported_send_duration_s for o in offerings
                     if o.reported_send_duration_s is not None]
        self._reported_send_duration_s = max(durations) \
            if len(durations) == len(offerings) else None

        # Any one of these fields is evidence. They come from different parts
        # of a generator's output, so a capture can carry one and not the rest
        # -- and reporting 'no evidence' while holding a queue depth is the one
        # answer this must never give.
        #
        # Each is kept as a maximum over sessions as well as over polls: the
        # depths because the deepest queue is the one worth reporting, and the
        # cumulative counts because the most-blocked session is. Neither is
        # summed across sessions, which is what lets a maximum stay honest when
        # one session could not be read -- it is then a lower bound rather than
        # a total that silently left a peer out.
        for o in offerings:
            for name, attr in (('_max_tx_pending_bytes', o.tx_pending_bytes),
                               ('_max_pending_prefixes', o.pending_prefixes),
                               ('_max_blocked_writes', o.blocked_writes),
                               ('_max_send_stalls', o.send_stalls)):
                if attr is None:
                    continue
                self._backpressure_readable = True
                seen = getattr(self, name)
                setattr(self, name, attr if seen is None else max(seen, attr))

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
            details = {'backpressure': self.backpressure}
            if self._reported_send_duration_s is not None:
                details['reported_send_duration_s'] = \
                    self._reported_send_duration_s
            self._add(EventKind.TESTER_COMPLETE, monotonic_s, counters, details)


def offering_poll_can_stop(sessions: Mapping[str, TesterOffering]) -> bool:
    '''True when one more poll of this generator could not learn anything.

    The poll loop otherwise runs until the monitor converges, which for a
    bind-mounted log costs a file read but for a BIRD tester is a `docker exec`
    running one `birdc` per configured peer, once a second, for the whole run.
    At 50-100 peers that is a hundred short-lived processes a second spawned by
    the instrument itself -- and `birdc` is in `contention.BGPERF_PROCESSES`, so
    it is the one load the `max foreign cpu %` column cannot see, in a column
    whose whole meaning is "0 means the machine was yours".

    The rule is deliberately the exact condition under which
    `TesterEventRecorder.observe()` records `tester_complete` on this same poll,
    not merely `all(o.complete)`:

    - every session complete, aggregated pessimistically like the recorder, so
      one finished peer cannot end the poll while another is still sending;
    - every session's count legible and their sum nonzero, because the recorder
      holds `tester_complete` until it has seen a `tester_first_update`. A
      generator can report its own completion on a poll whose counters were not
      yet readable -- bgpdump2 logs `RIB walk complete` before its final `Sent`
      counters -- and stopping there would take away the later poll that would
      have supplied the update, leaving a converged run with a generator that
      never completed.

    Nothing after completion is lost by stopping. `offered` is cumulative and
    the recorder already refuses to move it past completion; a queue depth
    stops growing once the last update has been handed to the session, so the
    poll that observes completion is the poll that reads the largest queue
    there will be; and a cumulative blocked-write count stops with it, because
    a generator that has reported its send complete has flushed what it
    encoded. Verified on the log of the one generator that reports these
    counts: in a backpressured 2 x 500,000-prefix run, both injectors logged
    every one of their writes before `End-of-RIB` and none after it.
    '''
    if not sessions:
        return False
    offerings = list(sessions.values())
    if not all(o.complete for o in offerings):
        return False
    measured = [o.offered for o in offerings if o.offered is not None]
    return len(measured) == len(offerings) and sum(measured) > 0


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
            # A numerator of zero is not a rate of zero. It says the whole
            # table was already offered when the first poll landed and the
            # completion arrived at a later one -- which is the ordinary shape
            # for a generator that reports its own completion, since its final
            # count is legible a poll before it says it is done. Dividing
            # publishes `0 prefixes/s` for a generator that delivered
            # everything, and that reads as a broken one.
            if injection_s and offered_in_interval:
                rate = offered_in_interval / injection_s

    # Each interval gets the resolution of the polls that bound *it*. One
    # shared number cannot do this job: `tester_session_ready` is routinely
    # found on the very first poll, whose resolution is the whole interval
    # since the clock started -- the origin is stamped before the testers are
    # even launched -- while first update and completion are bounded by two
    # ordinary 1s polls later on. Folding them together would qualify a
    # 1s-resolved injection with a 30s bound, which overstates the uncertainty
    # as badly as the nominal cadence understated it.
    ready = unique_event(events, EventKind.TESTER_SESSION_READY, producer)

    # The generator's own two numbers, both read at completion.
    #
    # `reported_injection_s` is not a better `injection_s`, it is a different
    # measurement: a different clock, and the generator's own definition of
    # sending -- bgpdump2's walk time is encode time bounded by its write
    # buffer, so it tracks the wire only on a table large enough to fill that
    # buffer. It is published because at MRT playback speeds it is the only
    # evidence there is: a 10,000-prefix walk takes about a millisecond, which
    # is over before the first poll looks, and `injection_s` can then say no
    # more than 'shorter than one look'. No rate is derived from it here for
    # the same reason the polled rate is published beside
    # `offered_in_interval` -- dividing an encode-side count by an encode-side
    # interval yields a send rate the generator never achieved.
    #
    # `octets_on_wire` is the count at the poll that saw completion, which is
    # the one that pairs with `offered_prefixes`: both come from the same line
    # of the generator's own counters, one encode-side and one wire-side.
    reported_injection_s = complete.details.get('reported_send_duration_s') \
        if complete else None
    octets = complete.counters.get('octets_on_wire') if complete else None

    # What the run spent after this generator had handed over its whole
    # workload -- the question the legacy `testers (s)` column was read as
    # answering and never could, since that column starts at the monitor's
    # first prefix and knows nothing about the generator at all.
    #
    # It is signed, and a negative value is a result rather than an error: the
    # monitor reaches the configured check-point before the generator reports
    # completion whenever the check-point sits below the full table, or when
    # the generator is still flushing sessions the check-point did not need.
    # That is an overlap, and it is the shape a run has when the target was
    # never the thing being waited for. Clamping it at zero would publish that
    # run as one with an instant tail.
    #
    # Null when either end is missing, which covers a failed run (no required
    # count was ever reached) and a generator that never completed. Measuring
    # from `tester_last_update` instead would answer a different question --
    # the last update *observed*, not the end of the workload -- and it would
    # answer it for exactly the runs where the generator is under suspicion.
    required = unique_event(events, EventKind.MONITOR_REQUIRED_REACHED)
    tail_s = signed_duration_s(
        events, EventKind.TESTER_COMPLETE, EventKind.MONITOR_REQUIRED_REACHED,
        start_producer=producer)

    return {
        'tester_startup_s': startup_s,
        'startup_resolution_s': _poll_resolution(ready),
        'injection_s': injection_s,
        'injection_resolution_s': _bounding_resolution(first, complete),
        'post_injection_tail_s': tail_s,
        'post_injection_tail_resolution_s': _bounding_resolution(
            complete, required),
        'reported_injection_s': reported_injection_s,
        'offered_prefixes': offered,
        'offered_in_interval': offered_in_interval,
        'offered_rate_pps': rate,
        'octets_on_wire': octets,
    }


def _poll_resolution(event):
    '''How wide the look was that placed this event in time, if it says.

    None for an event not produced by a poll loop, which is the case for a
    stream assembled by hand rather than by a recorder.
    '''
    if event is None:
        return None
    return event.details.get('poll_resolution_s')


def _bounding_resolution(*events):
    '''The coarser of the two looks bounding an interval.

    An interval is the distance between two polls, so it is only as sharp as
    the wider of them: an `injection_s` of 0.0 says the generator finished
    somewhere inside one look, and this says how wide that look was. Taking
    the worst rather than an average keeps the qualification conservative --
    the direction that reports less certainty than there is, never more.

    A missing endpoint yields no resolution at all. There is no interval to
    qualify when one of the two polls never happened, and publishing the other
    one's gap beside a null `injection_s` describes an unmeasured injection as
    a bounded one -- which is exactly what a generator that stalled and never
    completed produces.
    '''
    seen = [_poll_resolution(e) for e in events]
    if any(r is None for r in seen):
        return None
    return max(seen) if seen else None


def _fleet_total(values):
    '''Sum a per-generator count, or refuse the total if one is missing.

    Same all-or-nothing rule the sessions inside one container already use, one
    level up and for a sharper reason: a total covering nine of ten injectors
    is not a small shortfall, it is a different measurement, and a run whose
    tenth injector was never legible would publish a fleet count that looks
    like a workload 10% short of its configuration.
    '''
    values = list(values)
    if not values or any(value is None for value in values):
        return None
    return sum(values)


def tester_fleet_metrics(events: Iterable[LifecycleEvent], producers):
    '''Aggregate every generator in a run without letting the fastest speak.

    A full-internet MRT run drives ten injector containers, and the question
    the run as a whole asks is not what any one of them did but whether the
    workload was offered at all.  Every aggregate here is taken pessimistically,
    the same way TesterEventRecorder combines the sessions inside one container:
    the fleet is ready when its *last* generator is ready, its injection starts
    at the *earliest* first update and ends when its *slowest* generator
    completes.

    Completion gates every interval, and it is all-or-nothing.  One injector
    that never reported completion leaves `injection_s` None and its name in
    `incomplete_testers`, rather than an interval bounded by the nine that did
    finish -- that number would describe a workload that was never fully
    offered, which is precisely the failure an aggregate is added to expose and
    the one it must not average away.

    This is a summary of the per-generator sections, never a replacement for
    them: the fleet says whether the workload was delivered, and the individual
    sections say which generator was slow.
    '''
    events = tuple(events)
    producers = sorted(producers)
    if not producers:
        raise MeasurementEventError(
            'a fleet summary needs at least one generator')
    origin = unique_event(events, EventKind.BENCH_CLOCK_STARTED, 'controller')
    if origin is None:
        raise MeasurementEventError(
            'fleet metrics need the controller bench_clock_started event')

    per = [tester_metrics(events, producer) for producer in producers]
    ready = {p: unique_event(events, EventKind.TESTER_SESSION_READY, p)
             for p in producers}
    first = {p: unique_event(events, EventKind.TESTER_FIRST_UPDATE, p)
             for p in producers}
    done = {p: unique_event(events, EventKind.TESTER_COMPLETE, p)
            for p in producers}

    # A generator that completed without ever being seen to offer anything is
    # counted as incomplete too. The recorder cannot produce that stream -- it
    # holds `tester_complete` until an update is observed -- but a fleet
    # interval measured from a first update some other generator supplied would
    # be exactly the substitution this function exists to refuse.
    incomplete = [p for p in producers
                  if done[p] is None or first[p] is None]

    first_update_s = None
    complete_s = None
    injection_s = None
    injection_resolution_s = None
    end = None
    if not incomplete:
        start = min(first.values(), key=lambda e: e.monotonic_s)
        end = max(done.values(), key=lambda e: e.monotonic_s)
        if end.monotonic_s < start.monotonic_s:
            raise EventOrderError(
                'fleet {0} at {1} precedes {2} at {3}'.format(
                    end.kind.value, end.monotonic_s,
                    start.kind.value, start.monotonic_s))
        first_update_s = start.monotonic_s - origin.monotonic_s
        complete_s = end.monotonic_s - origin.monotonic_s
        injection_s = complete_s - first_update_s
        # The fleet interval is bounded by two polls belonging to two different
        # generators, and it is only as sharp as the wider of them.
        injection_resolution_s = _bounding_resolution(start, end)

    # Measured from the *slowest* generator's completion, for the same reason
    # the fleet's injection ends there: the workload is not delivered until
    # the last of them has finished, and a tail measured from the first would
    # charge the target with time it spent waiting on another injector. All
    # or nothing with the rest of the fleet -- one generator that never
    # completed leaves it null rather than bounded by the ones that did.
    required = unique_event(events, EventKind.MONITOR_REQUIRED_REACHED)
    post_injection_tail_s = None
    post_injection_tail_resolution_s = None
    if end is not None and required is not None:
        post_injection_tail_s = required.monotonic_s - end.monotonic_s
        post_injection_tail_resolution_s = _bounding_resolution(end, required)

    startup_s = None
    startup_resolution_s = None
    if all(event is not None for event in ready.values()):
        last_ready = max(ready.values(), key=lambda e: e.monotonic_s)
        startup_s = last_ready.monotonic_s - origin.monotonic_s
        startup_resolution_s = _poll_resolution(last_ready)

    offered = _fleet_total(m['offered_prefixes'] for m in per)
    # Summed rather than recomputed against the fleet interval, which makes it
    # a lower bound: each generator's own interval sits inside the fleet's, and
    # what it had already offered when its own first poll landed is outside
    # both. The bias is downward, which is the only safe direction for a
    # number a rate is divided from -- an overstated numerator would publish a
    # send rate no generator achieved.
    in_interval = _fleet_total(m['offered_in_interval'] for m in per)
    # Zero prefixes inside the span is not a send rate of zero, and at the
    # fleet level it is the *normal* case for MRT playback: every injector's
    # sub-millisecond walk finishes before its own first poll, so a span
    # bounded by two injectors completing at different polls contains none of
    # the table. Publishing 0 prefixes/s there would describe ten injectors
    # that delivered everything instantly as ten that sent nothing.
    rate = in_interval / injection_s \
        if in_interval and injection_s else None
    # Not summed. The generators send at the same time, so adding their own
    # reported durations would total intervals that overlapped. The longest is
    # taken for the reason the per-container aggregate takes it: it is a lower
    # bound on the span, since generators that started at different moments
    # cover more than the longest of them alone.
    reported = [m['reported_injection_s'] for m in per]
    reported_injection_s = max(reported) \
        if reported and all(value is not None for value in reported) else None

    return {
        'testers': len(producers),
        'testers_complete': len(producers) - len(incomplete),
        'incomplete_testers': incomplete,
        'tester_startup_s': startup_s,
        'startup_resolution_s': startup_resolution_s,
        'first_update_s': first_update_s,
        'complete_s': complete_s,
        'injection_s': injection_s,
        'injection_resolution_s': injection_resolution_s,
        'post_injection_tail_s': post_injection_tail_s,
        'post_injection_tail_resolution_s': post_injection_tail_resolution_s,
        'reported_injection_s': reported_injection_s,
        'offered_prefixes': offered,
        'offered_in_interval': in_interval,
        'offered_rate_pps': rate,
        'octets_on_wire': _fleet_total(m['octets_on_wire'] for m in per),
    }


def monitor_metrics(events: Iterable[LifecycleEvent]):
    '''Derive the monitor-owned intervals from their named endpoints.'''
    events = tuple(events)
    # Each interval carries the resolution of the polls that bound it, on the
    # same rule the generators already use. The two that start at the clock
    # origin are bounded by one poll only -- the origin is stamped by the
    # controller, not looked up -- while assurance runs between two monitor
    # samples and is only as sharp as the wider of them.
    first_prefix = unique_event(events, EventKind.MONITOR_FIRST_PREFIX)
    required = unique_event(events, EventKind.MONITOR_REQUIRED_REACHED)
    confirmed = unique_event(events, EventKind.CONVERGENCE_CONFIRMED)
    return {
        'first_prefix_s': duration_s(
            events,
            EventKind.BENCH_CLOCK_STARTED,
            EventKind.MONITOR_FIRST_PREFIX,
            start_producer='controller',
        ),
        'first_prefix_resolution_s': _poll_resolution(first_prefix),
        'convergence_s': duration_s(
            events,
            EventKind.BENCH_CLOCK_STARTED,
            EventKind.MONITOR_REQUIRED_REACHED,
            start_producer='controller',
        ),
        'convergence_resolution_s': _poll_resolution(required),
        'assurance_s': duration_s(
            events,
            EventKind.MONITOR_REQUIRED_REACHED,
            EventKind.CONVERGENCE_CONFIRMED,
        ),
        'assurance_resolution_s': _bounding_resolution(required, confirmed),
    }


def natural_key(name: str):
    '''Order `x2` before `x10`, which a plain sort does not.

    Receiver containers are `bgperf_receiver0 ... bgperf_receiverN` with no
    zero padding, so `sorted()` gives 0, 1, 10, 11, 12, 2 -- and the printed
    line names only the first few `incomplete_receivers`, so at twenty
    receivers a reader is shown an arbitrary subset while the ones between 2
    and 9 are hidden behind "and N more". The list and its printed sample have
    to mean what they read as.
    '''
    return tuple(int(part) if part.isdigit() else part
                 for part in re.split(r'(\d+)', name))


def export_poll_can_stop(accepted: Mapping[str, Optional[int]],
                         required_prefixes: int) -> bool:
    '''True when every receiver holds the table and one more look adds nothing.

    The export poll otherwise runs until the monitor converges, and unlike the
    generator poll it cannot be batched: each receiver is its own container, so
    a round is one `docker exec` per receiver. At a large fan-out that is the
    instrument spending a measurable share of every second inside containers,
    during the window the run's own resource columns describe -- and nothing in
    the row reports it. Not because it is bgperf2's own process tree: the read
    runs *inside* the receiver container, so `own_process_tree()` does not
    reach it. It is invisible because `gobgp` is in
    `contention.BGPERF_PROCESSES`, the by-name allowlist, exactly as `birdc` is
    for the generator poll. The distinction matters to anyone reasoning from
    this comment: a generator whose CLI is not in that frozenset would have its
    poll charged to `max foreign cpu %` as somebody else's load.

    Nothing observable is lost by stopping. Both export events fire on or
    before the poll that satisfies this, and a receiver's accepted count cannot
    move past the table the target has to give it.
    '''
    values = list(accepted.values())
    if not values:
        return False
    return all(value is not None and value >= required_prefixes
               for value in values)


class ExportEventRecorder:
    '''Translate polled receiver counts into the export vocabulary.

    A receiver is the *other* end of the target's export work: the monitor is
    one export session and what it observes is the run's convergence, so
    without this a `--receivers 20` run and a `--receivers 0` run differ in
    exactly one published number -- `elapsed (s)` -- and what the fan-out cost
    is inside it, indistinguishable from a slow target.

    One recorder covers the whole fan-out rather than one per container, because
    one poll round reads every receiver: the events it produces name the
    receiver as their producer, and every interval below is derived per
    receiver from those.

    It deliberately does not stamp `bench_clock_started`. That event is the
    monitor recorder's, there is exactly one of it in a run, and a second would
    make every `unique_event()` lookup against the merged stream ambiguous.
    '''

    def __init__(self, bench_started_s, receivers, required_prefixes,
                 sample_interval_s=None):
        receivers = tuple(receivers)
        if not receivers:
            raise MeasurementEventError(
                'an export recorder needs at least one receiver')
        for name in receivers:
            if not isinstance(name, str) or not name.strip():
                raise ValueError('receiver names must be non-empty strings')
        if len(set(receivers)) != len(receivers):
            raise ValueError('receiver names must be unique')
        if not isinstance(required_prefixes, int) \
                or isinstance(required_prefixes, bool) \
                or required_prefixes <= 0:
            raise ValueError('required_prefixes must be a positive integer')
        self.receivers = frozenset(receivers)
        # What a receiver has to hold to have been served: the run's own
        # check-point, which is the same yardstick the monitor is judged by.
        # Deriving one from what the monitor has seen so far would couple the
        # two instruments, and the whole point of reading a receiver is that
        # its answer does not depend on the monitor's.
        self.required_prefixes = required_prefixes
        self.sample_interval_s = _validated_interval(sample_interval_s)
        self._origin_s = float(bench_started_s)
        self._events = []
        self._last_sample_s = None
        self._poll_resolution_s = None
        self._accepted = {name: None for name in receivers}

    def _details(self):
        details = {}
        if self.sample_interval_s is not None:
            details['sample_interval_s'] = self.sample_interval_s
        if self._poll_resolution_s is not None:
            details['poll_resolution_s'] = self._poll_resolution_s
        return details

    @property
    def events(self):
        '''Return the current facts in deterministic monotonic order.'''
        return ordered_events(self._events)

    @property
    def accepted(self):
        '''The last count read from each receiver, None where none ever was.

        Kept across a failed read rather than cleared by one: a receiver that
        answered and then went unreadable has been observed holding that many
        prefixes, and replacing it with None would lose evidence that a later
        poll cannot recover.
        '''
        return dict(self._accepted)

    def observe(self, monotonic_s, accepted: Mapping[str, Optional[int]]):
        '''Record one poll round covering every receiver in the fan-out.'''
        if not isinstance(monotonic_s, (int, float)) \
                or isinstance(monotonic_s, bool) \
                or not math.isfinite(monotonic_s):
            raise ValueError('monotonic_s must be a finite number')
        monotonic_s = float(monotonic_s)
        if monotonic_s < self._origin_s:
            raise EventOrderError('receiver sample precedes bench_clock_started')
        if self._last_sample_s is not None and monotonic_s < self._last_sample_s:
            raise EventOrderError('receiver samples are not monotonic')
        # Every configured receiver on every poll, with None where the read
        # failed -- the rule `TesterEventRecorder.observe()` states for a
        # generator's sessions, and here it is what stops the receivers that
        # happen to answer from satisfying "the whole fan-out has the table".
        if frozenset(accepted) != self.receivers:
            raise MeasurementEventError(
                'receiver set changed between polls: expected {0}'.format(
                    sorted(self.receivers)))
        for name, value in accepted.items():
            if value is None:
                continue
            if not isinstance(value, int) or isinstance(value, bool) \
                    or value < 0:
                raise ValueError(
                    'accepted prefixes for {0} must be a non-negative integer '
                    'or None'.format(name))

        # Computed before the sample moves and before any event is added, so
        # every event this poll produces carries the poll's own resolution.
        self._poll_resolution_s = _resolution_for_poll(
            monotonic_s,
            self._origin_s if self._last_sample_s is None
            else self._last_sample_s,
            self.sample_interval_s)
        self._last_sample_s = monotonic_s

        details = self._details()
        # Sorted so a poll that fires two receivers' events places them in a
        # deterministic order when they share a timestamp -- and in the same
        # order the section publishes, since names are unpadded and a plain
        # sort would emit receiver0, receiver1, receiver10, receiver2 into the
        # event stream while `sessions` and `incomplete_receivers` list them by
        # index. Two orders for one fan-out is a reader's problem, not a
        # tie-break.
        for name in sorted(accepted, key=natural_key):
            value = accepted[name]
            if value is None:
                continue
            self._accepted[name] = value
            counters = {'accepted_prefixes': value,
                        'required_prefixes': self.required_prefixes}
            if value > 0 and unique_event(
                    self._events, EventKind.RECEIVER_FIRST_PREFIX,
                    name) is None:
                self._events.append(LifecycleEvent(
                    EventKind.RECEIVER_FIRST_PREFIX, monotonic_s, name,
                    EventPhase.EXPORT, counters=counters, details=details))
            if value >= self.required_prefixes and unique_event(
                    self._events, EventKind.RECEIVER_TABLE_REACHED,
                    name) is None:
                self._events.append(LifecycleEvent(
                    EventKind.RECEIVER_TABLE_REACHED, monotonic_s, name,
                    EventPhase.EXPORT, counters=counters, details=details))


def export_metrics(events: Iterable[LifecycleEvent], receivers):
    '''Derive what the target's other export sessions were served, and when.

    The per-receiver sections say which session lagged; the fleet fields say
    whether the table was exported to all of them at all. Same division of
    labour as `tester_metrics()` and `tester_fleet_metrics()`, and the same
    pessimism: the fan-out is served when its *slowest* receiver has the table,
    and one receiver that never got there leaves every fleet interval null
    rather than bounded by the ones that did.

    `monitor_delta_s` is the one number that relates this to the published row.
    It is deliberately measured against the monitor rather than against the
    generators: an export tail measured from the fleet's completion is
    `post_injection_tail_s + monitor_delta_s`, and publishing it here would mean
    repeating `tester_fleet_metrics()`'s all-or-nothing completion rule in a
    second place, where the two could drift apart.
    '''
    events = tuple(events)
    receivers = sorted(receivers, key=natural_key)
    if not receivers:
        raise MeasurementEventError(
            'an export summary needs at least one receiver')
    origin = unique_event(events, EventKind.BENCH_CLOCK_STARTED, 'controller')
    if origin is None:
        raise MeasurementEventError(
            'export metrics need the controller bench_clock_started event')

    required = unique_event(events, EventKind.MONITOR_REQUIRED_REACHED)
    first = {r: unique_event(events, EventKind.RECEIVER_FIRST_PREFIX, r)
             for r in receivers}
    reached = {r: unique_event(events, EventKind.RECEIVER_TABLE_REACHED, r)
               for r in receivers}
    sessions = {}
    for name in receivers:
        sessions[name] = {
            'first_prefix_s': duration_s(
                events, EventKind.BENCH_CLOCK_STARTED,
                EventKind.RECEIVER_FIRST_PREFIX,
                start_producer='controller', end_producer=name),
            'first_prefix_resolution_s': _poll_resolution(first[name]),
            'table_reached_s': duration_s(
                events, EventKind.BENCH_CLOCK_STARTED,
                EventKind.RECEIVER_TABLE_REACHED,
                start_producer='controller', end_producer=name),
            'table_reached_resolution_s': _poll_resolution(reached[name]),
        }

    incomplete = [r for r in receivers if reached[r] is None]

    # Gated separately from the intervals below: a fan-out where every receiver
    # was seen taking prefixes and one never finished has a real, useful export
    # start, and it is exactly the case where a reader wants it.
    first_prefix_s = None
    first_prefix_resolution_s = None
    if all(event is not None for event in first.values()):
        earliest = min(first.values(), key=lambda e: e.monotonic_s)
        first_prefix_s = earliest.monotonic_s - origin.monotonic_s
        first_prefix_resolution_s = _poll_resolution(earliest)

    table_reached_s = None
    table_reached_resolution_s = None
    spread_s = None
    spread_resolution_s = None
    slowest = None
    if not incomplete:
        # An inverted stream has already been refused: the per-receiver pass
        # above measures every one of these events with `duration_s()`, which
        # rejects an endpoint preceding the origin.
        slowest = max(reached.values(), key=lambda e: e.monotonic_s)
        fastest = min(reached.values(), key=lambda e: e.monotonic_s)
        table_reached_s = slowest.monotonic_s - origin.monotonic_s
        table_reached_resolution_s = _poll_resolution(slowest)
        # How far apart the fan-out's sessions were served. Zero at or under
        # the resolution below means they were served within one look of each
        # other, which is what a target exporting to them in parallel looks
        # like at this cadence; it is not proof that it did.
        spread_s = slowest.monotonic_s - fastest.monotonic_s
        spread_resolution_s = _bounding_resolution(fastest, slowest)

    # Signed, and for the same reason `post_injection_tail_s` is: the monitor is
    # just another export session, so a receiver reaching the table before it
    # is ordinary rather than a fault, and clamping at zero would give that run
    # the same number as one whose fan-out finished exactly with the
    # instrument.
    monitor_delta_s = None
    monitor_delta_resolution_s = None
    if slowest is not None and required is not None:
        monitor_delta_s = slowest.monotonic_s - required.monotonic_s
        monitor_delta_resolution_s = _bounding_resolution(slowest, required)

    return {
        'receivers': len(receivers),
        'receivers_complete': len(receivers) - len(incomplete),
        'incomplete_receivers': incomplete,
        # Whether the *monitor* got there, which is what says whether an
        # incomplete fan-out is a finding about the receivers at all. The
        # check-point takes no account of a `--filter_test` policy, so a policy
        # that drops enough of the table puts it out of reach for every session
        # in the run -- and every receiver would then be named as though it had
        # stalled. Read from the event stream rather than from the flag,
        # because whether a policy drops that much depends on the workload:
        # `--filter_test transit` at 2 peers x 1000 prefixes reached the
        # check-point on the development host.
        'monitor_reached_required': required is not None,
        'first_prefix_s': first_prefix_s,
        'first_prefix_resolution_s': first_prefix_resolution_s,
        'table_reached_s': table_reached_s,
        'table_reached_resolution_s': table_reached_resolution_s,
        'export_spread_s': spread_s,
        'export_spread_resolution_s': spread_resolution_s,
        'monitor_delta_s': monitor_delta_s,
        'monitor_delta_resolution_s': monitor_delta_resolution_s,
        'sessions': sessions,
    }


class ChurnEventRecorder:
    """Translate a churn burst sequence into the typed lifecycle vocabulary.

    The monitor is the instrument for churn exactly as it is for the initial
    table -- what a burst costs is what the target takes to withdraw the block
    from its export sessions and to put it back -- so these events are stamped
    at monitor samples and carry that loop's resolution.

    It is a recorder of its own rather than more state on
    `MonitorEventRecorder` for two reasons. That recorder refuses samples after
    convergence is confirmed, which is the rule that keeps the published
    `elapsed (s)` from drifting once the table is delivered, and a churn burst
    is a second workload that must not move `monitor_last_change` or any
    interval derived from it. And its clock origin is different: the first
    churn sample is one poll after convergence, not one poll after the bench
    clock started, so measuring its resolution from the run origin would
    publish the whole convergence time as the resolution of the first burst.
    """

    def __init__(self, since_s, producer='monitor', sample_interval_s=None,
                 requested_bursts=1, offered_withdrawals=0,
                 distinct_withdrawals=0):
        if not isinstance(producer, str) or not producer.strip():
            raise ValueError('producer must be a non-empty string')
        for name, value in (('requested_bursts', requested_bursts),
                            ('offered_withdrawals', offered_withdrawals),
                            ('distinct_withdrawals', distinct_withdrawals)):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(
                    '{0} must be a non-negative integer'.format(name))
        self.producer = producer
        self.sample_interval_s = _validated_interval(sample_interval_s)
        self._since_s = float(since_s)
        self._counts = {
            'requested_bursts': requested_bursts,
            'offered_withdrawals': offered_withdrawals,
            'distinct_withdrawals': distinct_withdrawals,
        }
        self._events = []
        self._last_sample_s = None
        self._last_accepted = None
        self._poll_resolution_s = None
        self._open_burst = None
        self._withdrawn_burst = None

    def _details(self):
        details = {}
        if self.sample_interval_s is not None:
            details['sample_interval_s'] = self.sample_interval_s
        if self._poll_resolution_s is not None:
            details['poll_resolution_s'] = self._poll_resolution_s
        return details

    @property
    def events(self):
        """Return the recorded facts in deterministic monotonic order."""
        return ordered_events(self._events)

    def observe(self, monotonic_s, accepted_prefixes):
        """Record one post-convergence monitor sample.

        This produces no event on its own. It is what dates the events the
        caller then records: every burst transition is a decision about a
        sample, so it is stamped at that sample and carries the gap since the
        previous look, on the same rule the rest of this module uses.
        """
        if not isinstance(monotonic_s, (int, float)) \
                or isinstance(monotonic_s, bool) \
                or not math.isfinite(monotonic_s):
            raise ValueError('monotonic_s must be a finite number')
        monotonic_s = float(monotonic_s)
        if not isinstance(accepted_prefixes, int) \
                or isinstance(accepted_prefixes, bool) \
                or accepted_prefixes < 0:
            raise ValueError('accepted_prefixes must be a non-negative integer')
        if monotonic_s < self._since_s:
            raise EventOrderError('churn sample precedes convergence')
        if self._last_sample_s is not None and monotonic_s < self._last_sample_s:
            raise EventOrderError('churn samples are not monotonic')
        self._poll_resolution_s = _resolution_for_poll(
            monotonic_s,
            self._since_s if self._last_sample_s is None else self._last_sample_s,
            self.sample_interval_s)
        self._last_sample_s = monotonic_s
        self._last_accepted = accepted_prefixes

    def _add(self, kind, burst):
        if self._last_sample_s is None:
            raise MeasurementEventError(
                'cannot record {0} before a churn sample'.format(kind.value))
        if not isinstance(burst, int) or isinstance(burst, bool) or burst < 1:
            raise ValueError('burst must be a whole number of 1 or more')
        counters = dict(self._counts)
        counters['burst'] = burst
        counters['accepted_prefixes'] = self._last_accepted
        self._events.append(LifecycleEvent(
            kind, self._last_sample_s, self.producer, EventPhase.CHURN,
            counters=counters, details=self._details()))

    def note_burst_started(self, burst):
        """Record that this sample opened a burst, before the withdrawal is issued.

        Stamped ahead of the `docker exec` that carries the withdrawal to the
        generator rather than after it, for the reason both poll loops stamp a
        sample before their read: the exec is the expensive half, and dating
        the start to when it returned would take that cost out of the
        withdrawal interval the burst exists to measure. It is a lower bound on
        when the block began to go away, which is the honest end to be sure of.
        """
        if self._open_burst is not None:
            raise MeasurementEventError(
                'churn burst {0} is still open'.format(self._open_burst))
        self._add(EventKind.CHURN_BURST_STARTED, burst)
        self._open_burst = burst

    def note_withdraw_complete(self, burst):
        """Record the sample on which the whole churn block had gone away."""
        if self._open_burst != burst:
            raise MeasurementEventError(
                'churn burst {0!r} did not start'.format(burst))
        if self._withdrawn_burst == burst:
            raise DuplicateEventError(
                'churn burst {0} already withdrew'.format(burst))
        self._add(EventKind.CHURN_WITHDRAW_COMPLETE, burst)
        self._withdrawn_burst = burst

    def note_burst_complete(self, burst):
        """Record the sample on which the table was back to its converged count."""
        if self._open_burst != burst:
            raise MeasurementEventError(
                'churn burst {0!r} did not start'.format(burst))
        if self._withdrawn_burst != burst:
            raise MeasurementEventError(
                'churn burst {0} completed without withdrawing'.format(burst))
        self._add(EventKind.CHURN_BURST_COMPLETE, burst)
        self._open_burst = None


def _burst_event(events, kind, burst):
    """One churn event of a kind for one burst, or None."""
    matches = [event for event in events
               if event.kind == kind and event.counters.get('burst') == burst]
    if len(matches) > 1:
        raise DuplicateEventError(
            'multiple {0} events for churn burst {1}'.format(kind.value, burst))
    return matches[0] if matches else None


def _burst_interval(start, end):
    """The interval between two churn events, refusing an inverted one.

    `duration_s()` cannot be used here: it identifies its endpoints by kind and
    producer, and every burst in a sequence shares both. Both endpoints belong
    to the same producer, so an inversion is a wiring fault rather than a
    finding -- the same rule `duration_s()` applies, for the same reason.
    """
    if start is None or end is None:
        return None
    if end.monotonic_s < start.monotonic_s:
        raise EventOrderError(
            '{0} at {1} precedes {2} at {3}'.format(
                end.kind.value, end.monotonic_s,
                start.kind.value, start.monotonic_s))
    return end.monotonic_s - start.monotonic_s


def churn_metrics(events: Iterable[LifecycleEvent]):
    """Derive each burst's withdrawal and reannouncement from its own events.

    The two halves are what the section is for. A burst timed end to end
    cannot say whether a daemon was slow to drop the routes or slow to
    re-select and re-export them, and those are different mechanisms -- the
    second is one of the three BIRD 3's worker threads exist to parallelise --
    so a single number would hide exactly what the workload was added to
    expose. `burst_s` **is** their sum: the withdrawal's end and the
    re-announcement's start are one event, so the three share two endpoints.
    It is published so a reader does not have to add two rounded numbers, and
    never as a third measurement.

    A burst that started and did not finish keeps its partial intervals and is
    reported `complete: false`, rather than being dropped. A sequence that was
    cut short has to be legible as a sequence that was cut short -- a document
    holding one burst of three with nothing saying three were asked for reads
    as a run that asked for one.
    """
    events = [event for event in ordered_events(events)
              if event.phase == EventPhase.CHURN]
    started = [event for event in events
               if event.kind == EventKind.CHURN_BURST_STARTED]
    counts = dict(started[0].counters) if started else {}
    bursts = []
    for event in started:
        burst = event.counters.get('burst')
        withdrew = _burst_event(events, EventKind.CHURN_WITHDRAW_COMPLETE, burst)
        completed = _burst_event(events, EventKind.CHURN_BURST_COMPLETE, burst)
        bursts.append({
            'burst': burst,
            'complete': completed is not None,
            'withdraw_s': _burst_interval(event, withdrew),
            'withdraw_resolution_s': _bounding_resolution(event, withdrew),
            'reannounce_s': _burst_interval(withdrew, completed),
            'reannounce_resolution_s': _bounding_resolution(withdrew, completed),
            'burst_s': _burst_interval(event, completed),
            'burst_resolution_s': _bounding_resolution(event, completed),
        })
    return {
        # What the run asked for, from the events themselves rather than from
        # the caller: a document whose requested count came from somewhere the
        # event stream cannot corroborate could claim a sequence that was never
        # driven.
        'requested_bursts': counts.get('requested_bursts'),
        'completed_bursts': sum(1 for b in bursts if b['complete']),
        # One burst's operation counts. They differ by exactly the path
        # diversity, and both are needed: the first is the work the fleet did,
        # the second is what the instrument could see.
        'offered_withdrawals': counts.get('offered_withdrawals'),
        'distinct_withdrawals': counts.get('distinct_withdrawals'),
        'bursts': bursts,
    }


class PolicyReloadEventRecorder:
    """Translate one policy reload into the typed lifecycle vocabulary.

    The monitor is the instrument here for the same reason it is for churn:
    what a policy change costs on a loaded table is what the target takes to
    re-evaluate it and to withdraw the rejected routes from its export
    sessions, and that is what the monitor reads. So both events are stamped at
    monitor samples and carry that loop's achieved resolution.

    A recorder of its own rather than more state on `MonitorEventRecorder`, on
    the two rules `ChurnEventRecorder` was separated for: that recorder refuses
    samples after convergence is confirmed, which is what keeps the published
    `elapsed (s)` from drifting once the table is delivered, and its clock
    origin is the start of the run rather than the moment this workload began
    -- measuring this interval's resolution from the run origin would publish
    the whole convergence time as the resolution of the reload.
    """

    def __init__(self, since_s, producer='monitor', sample_interval_s=None,
                 counters=None, rejected_peer_asns=()):
        if not isinstance(producer, str) or not producer.strip():
            raise ValueError('producer must be a non-empty string')
        self.producer = producer
        self.sample_interval_s = _validated_interval(sample_interval_s)
        self._since_s = float(since_s)
        self._counts = dict(counters or {})
        # In `details` rather than `counters`, which holds integers only: the
        # peers a policy rejects are the set a reader rebuilds the workload
        # from, and a count of them alone would not say *which* blocks moved.
        self._rejected_peer_asns = [int(asn) for asn in rejected_peer_asns]
        self._events = []
        self._last_sample_s = None
        self._last_accepted = None
        self._poll_resolution_s = None
        self._started = False
        self._completed = False

    @property
    def events(self):
        """Return the recorded facts in deterministic monotonic order."""
        return ordered_events(self._events)

    def _details(self):
        details = {'rejected_peer_asns': list(self._rejected_peer_asns)}
        if self.sample_interval_s is not None:
            details['sample_interval_s'] = self.sample_interval_s
        if self._poll_resolution_s is not None:
            details['poll_resolution_s'] = self._poll_resolution_s
        return details

    def observe(self, monotonic_s, accepted_prefixes):
        """Record one post-convergence monitor sample.

        Produces no event of its own. It is what dates the two that matter:
        both ends of this interval are decisions about a sample, so each is
        stamped at that sample and carries the gap since the previous look.
        """
        if not isinstance(monotonic_s, (int, float)) \
                or isinstance(monotonic_s, bool) \
                or not math.isfinite(monotonic_s):
            raise ValueError('monotonic_s must be a finite number')
        monotonic_s = float(monotonic_s)
        if not isinstance(accepted_prefixes, int) \
                or isinstance(accepted_prefixes, bool) \
                or accepted_prefixes < 0:
            raise ValueError('accepted_prefixes must be a non-negative integer')
        if monotonic_s < self._since_s:
            raise EventOrderError('policy reload sample precedes convergence')
        if self._last_sample_s is not None and monotonic_s < self._last_sample_s:
            raise EventOrderError('policy reload samples are not monotonic')
        self._poll_resolution_s = _resolution_for_poll(
            monotonic_s,
            self._since_s if self._last_sample_s is None else self._last_sample_s,
            self.sample_interval_s)
        self._last_sample_s = monotonic_s
        self._last_accepted = accepted_prefixes

    def _add(self, kind, **details):
        if self._last_sample_s is None:
            raise MeasurementEventError(
                'cannot record {0} before a policy reload sample'.format(
                    kind.value))
        counters = dict(self._counts)
        counters['accepted_prefixes'] = self._last_accepted
        stamped = self._details()
        stamped.update(details)
        self._events.append(LifecycleEvent(
            kind, self._last_sample_s, self.producer,
            EventPhase.POLICY_RELOAD, counters=counters, details=stamped))

    def note_reload_started(self, command_s=None):
        """Record the sample the reload was issued from.

        Dated to the *sample* the reload was issued from, not to the moment
        the command came back -- on the rule both poll loops stamp a sample
        before their read. Carrying the change into the container is a `docker
        exec` and the expensive half, so starting the interval at its return
        would take the cost of issuing the policy out of the interval this
        workload exists to measure. It is recorded once the command has
        returned, because `command_s` is that cost stated separately: a reader
        can then see how much of the interval was the controller reaching the
        daemon at all, and a daemon whose reply is instant is not thereby
        credited with an instant reload.
        """
        if self._started:
            raise DuplicateEventError('the policy reload already started')
        extra = {} if command_s is None else {'command_s': float(command_s)}
        self._add(EventKind.POLICY_RELOAD_STARTED, **extra)
        self._started = True

    def note_reload_complete(self):
        """Record the sample on which the new policy's count was first seen."""
        if not self._started:
            raise MeasurementEventError('the policy reload did not start')
        if self._completed:
            raise DuplicateEventError('the policy reload already completed')
        self._add(EventKind.POLICY_RELOAD_COMPLETE)
        self._completed = True


def policy_reload_metrics(events: Iterable[LifecycleEvent]):
    """Derive the reload interval and the counts either side of it.

    `accepted_before` and `accepted_after` are read off the two events rather
    than taken from the caller, for the reason `churn_metrics()` reads its
    requested burst count off the stream: a count the event stream cannot
    corroborate could describe a table the run never held.

    A reload that started and did not finish keeps its `accepted_before` and is
    reported `complete: false`, rather than being dropped. A document holding a
    reload with nothing saying it did not finish reads as a run that never
    asked for one.
    """
    events = [event for event in ordered_events(events)
              if event.phase == EventPhase.POLICY_RELOAD]
    started = unique_event(events, EventKind.POLICY_RELOAD_STARTED)
    completed = unique_event(events, EventKind.POLICY_RELOAD_COMPLETE)
    counters = dict(started.counters) if started else {}
    return {
        'requested': started is not None,
        'complete': completed is not None,
        'rejected_blocks': counters.get('rejected_blocks'),
        'rejected_peer_asns': (list(started.details.get('rejected_peer_asns'))
                               if started else None),
        'rejected_prefixes': counters.get('rejected_prefixes'),
        'converged_prefixes': counters.get('converged_prefixes'),
        'expected_accepted': counters.get('expected_accepted'),
        'accepted_before': counters.get('accepted_prefixes'),
        'accepted_after': (completed.counters.get('accepted_prefixes')
                           if completed else None),
        # What issuing the change cost, as distinct from what applying it did.
        # The command returning is not the daemon having finished: on BIRD the
        # reply comes back in milliseconds and the table drains afterwards, so
        # publishing one number would credit the daemon with an instant reload.
        'command_s': (started.details.get('command_s') if started else None),
        'reload_s': duration_s(events, EventKind.POLICY_RELOAD_STARTED,
                               EventKind.POLICY_RELOAD_COMPLETE),
        'reload_resolution_s': _bounding_resolution(started, completed),
    }


# The series a target table witness contributes, in the order a reader wants
# them: the instrument's own number first, then the two the target answers with.
TARGET_TABLE_SERIES = ('monitor_accepted', 'best_paths', 'imported_paths',
                       'exported_to_monitor')

# The target and the monitor are polled by independent loops, and a sample here
# is one *monitor* poll carrying whatever the target poll last produced. So the
# target's series is resampled onto the monitor's cadence: a target read taken
# between two monitor polls is dropped, and one that lands between none is
# carried twice. Each sample's `witness_monotonic_s` says which, per row. It is
# stated here because `decline_from_peak` for the target's own series is
# computed over the resampled series, and a rule written against it must know
# that its resolution is the monitor's, not the target's.
TARGET_TABLE_RESAMPLED = ('best_paths', 'imported_paths', 'exported_to_monitor')


# The oldest a witness reading may be and still attest to the sample it is
# paired with. The same span `ConvergenceTracker` refuses to carry a reading
# past (`WITNESS_CARRY_SAMPLES` monitor polls at `MONITOR_POLL_INTERVAL_S`),
# pinned against both by `tests/test_stats_contract.py` rather than imported,
# because this module stays free of project imports.
DELIVERY_WITNESS_MAX_AGE_S = 5.0

DELIVERY_RULE = ('the earliest reading of the terminal export plateau at or '
                 'after which the monitor holds it')

_DELIVERY_FIELDS = ('complete_s', 'resolution_s', 'plateau_start_s',
                    'plateau_samples', 'monitor_lag_s', 'exported_final',
                    'monitor_final')


def _sample_time(sample):
    return sample.get('monotonic_s')


def _delivery(reason=None, **values):
    '''Every field present on every path, absent ones null.

    A section whose keys come and go cannot be read by a consumer without
    knowing which branch produced it, and the branch is exactly what a reader
    is trying to find out. `unresolved_reason` says which one it was.
    '''
    section = {
        'derived': True,
        'derived_from': 'target_table.samples',
        'rule': DELIVERY_RULE,
        'unresolved_reason': reason,
    }
    section.update({field: values.get(field) for field in _DELIVERY_FIELDS})
    return section


def delivery_metrics(samples):
    '''When the target finished delivering its table, decided in retrospect.

    This is **not** `convergence_s` and must never be published as it.
    `convergence_s` is the monitor crossing the run's check-point, which for
    MRT playback is `0.99 * -p` -- a threshold part-way up the climb, not the
    end of it. Measured on one recorded 2-injector 500k run: the check-point
    was crossed at 16.85s with 500,171 prefixes visible, and the target went on
    exporting until 36.36s and 501,471. The two answer different questions and
    a row carrying both should show them differing.

    What it is for is the daemon that never crosses the check-point at all.
    `required` for MRT is the per-injector cap and the peers' union is larger
    and unknowable in advance, so a target exporting a smaller share of one RIB
    -- every FRR release, at ~961,000 against a 1,039,500 check-point -- emits
    no `monitor_required_reached`, and with it loses `convergence_s`,
    `assurance_s` and `post_injection_tail_s`. It is derived for *every* run
    with an export gauge, not only those rows, so the column is comparable
    across daemons rather than being a substitute that only the daemons in
    trouble carry.

    **Retrospective, which is the whole point.** Two online rules for this were
    built, verified and backed out (see the campaign plan's Block 5 record):
    both decided from the samples in hand, so a plateau that later resumed
    climbing had already been stamped, permanently and at a fraction of the
    table. Here the series is complete, so "and it never changed again" is
    checkable rather than assumed -- and when it is not checkable the answer is
    withheld with a reason rather than estimated.

    Ten things are refused, each because the alternative publishes a number
    that looks like a measurement and is not:

    - **No export gauge, or no samples.** Most daemons publish none; they get
      `no_export_gauge` and nothing else changes about their document.
    - **A final count of zero.** Nothing was delivered, so there is no
      delivery to date. A failed run's artifact carries its samples exactly
      like a converged one's, and an all-zero series otherwise satisfies every
      rule here -- the monitor is level at the first sample because `0 >= 0`.
      Churn's "a collapsed count is not a withdrawal" and the tracker's "a
      monitor count of zero never attests", on a third side.
    - **A truncated series.** The witness stopped reporting while the monitor
      polled on, so the last reading describes the middle of the run and the
      plateau after it is an absence of evidence.
    - **A plateau of one reading.** The count was still changing at the last
      sample there is. Nothing says the target finished; it says the run
      stopped. A minimum length beyond "more than one" is deliberately not
      imposed -- there is no measured number to set it to -- so
      `plateau_samples` is published for the reader to weigh.
    - **A withheld reading inside the plateau.** A poll whose sums were
      withheld carries no reading and a fresh timestamp, so the staleness rule
      cannot see it, and the flatness across the hole is an absence of
      evidence. `series_truncated`'s rule one step inward.
    - **A plateau resting on a single reading.** A target poll thread that
      dies leaves `bench()` appending its last reading to every later monitor
      sample, which is a perfect plateau made of one observation. The read
      timestamps say so and the age bound does not: a frozen sampler's ages
      are 1s..5s and all within bound. Two *distinct* reads are required, not
      all-distinct ones -- a repeated read is ordinary whenever the target's
      poll is the slower loop, which is likeliest on the large tables this
      measurement is for.
    - **A plateau whose readings cannot be dated**, which is every artifact
      written before those fields existed. Named apart from staleness: one was
      never asked, the other answered.
    - **A stale reading anywhere in the plateau**, past the carry bound.
    - **A monitor that never drew level.** Delivery is the far end holding what
      the target sent, so the count has to arrive. The comparison is exact
      rather than tolerant, and it asks whether the monitor *ever* reached the
      count, not whether it ended there: a monitor that draws level and then
      declines has still taken delivery, and such declines are ordinary on
      these runs -- `ConvergenceTracker`'s fourth rule exists because real
      10 x 1.05M MRT runs decline 1.18%-1.76% past their peak without losing a
      route. Reading it as an end-state test would withhold the measurement
      from exactly those runs. `monitor_final` is published so a later decline
      is visible rather than absorbed.
    - **Samples that cannot be dated at all.** `no_sample_times`, rather than
      a resolved section whose every interval is null -- the contract is that
      a null `complete_s` always has a reason beside it.

    `monitor_lag_s` is the gap between the target finishing and the monitor
    holding it, which is the one part of the tail this series can see on its
    own.

    **`final` is the last reading and deliberately not the series peak**, so a
    run whose export count settles *below* its peak is dated to where it
    settled. That shape is the normal one here rather than route loss: 11 of
    the 39 recorded runs end 1.35%-1.55% under their peak, and every one of
    them settles on exactly 1,056,779 -- the same count BIRD and OpenBGPD
    converge to on this RIB -- so the peak is a transient overshoot during
    convergence and the last reading is the true table. Taking the peak would
    wait for the monitor to draw level with a count the target does not hold,
    and withhold the answer for every MRT run there is. The cost is that a
    target which really did deliver and then *lose* routes is dated to the
    loss; that run is failed by `ConvergenceTracker`'s drop rule and rejected
    by `check_timing_evidence.py` before the number is read, and the decline
    itself is published one key over as `series.exported_to_monitor
    .decline_from_peak` rather than hidden.

    **What is not judged here is whether the table was the right size.** This
    function is handed samples and nothing else, so it has no denominator: a
    target that stalls at a fraction of the RIB and holds there has a terminal
    plateau like any other, and saying so is `check_timing_evidence.py`'s job,
    which knows the check-point and what the generators offered. The zero case
    above is refused not because the run was bad but because the rule itself
    degenerates -- `0 >= 0` makes the monitor trivially level -- which is a
    different reason and the line between the two.
    '''
    samples = [s for s in (samples or [])]
    if not samples:
        return _delivery('no_samples')
    readings = [(i, s) for i, s in enumerate(samples)
                if s.get('exported_to_monitor') is not None]
    if not readings:
        return _delivery('no_export_gauge')

    last_index, last_reading = readings[-1]
    final = last_reading['exported_to_monitor']
    monitor_final = samples[-1].get('monitor_accepted')
    known = {'exported_final': final, 'monitor_final': monitor_final}

    # A count of zero is not a delivery, and this is the third side of a rule
    # this project already holds on two others: churn's "a collapsed count is
    # not a withdrawal", and `ConvergenceTracker`'s "a monitor count of zero
    # never attests". Without it the cheapest series there is resolves --
    # `0 >= 0` draws the monitor level on the first sample, every reading is
    # fresh, and the plateau is the whole run -- so the tracker's "nothing
    # arriving at all within 15s" failure, whose artifact `bench()` writes
    # with its samples exactly like a converged one's, would publish a
    # completed delivery at 0.1s. The same guard covers a *collapse*: an
    # export count that falls to 0 at the end (the monitor session dropped)
    # would otherwise date the delivery to the collapse.
    if not final:
        return _delivery('nothing_delivered', **known)

    end_s = _sample_time(samples[-1])
    last_read_s = _sample_time(last_reading)
    if end_s is not None and last_read_s is not None \
            and end_s - last_read_s > DELIVERY_WITNESS_MAX_AGE_S:
        return _delivery('series_truncated', **known)

    position = len(readings) - 1
    while position > 0 \
            and readings[position - 1][1]['exported_to_monitor'] == final:
        position -= 1
    plateau = readings[position:]
    known['plateau_samples'] = len(plateau)
    known['plateau_start_s'] = _sample_time(plateau[0][1])
    if len(plateau) < 2:
        return _delivery('still_changing', **known)

    # A withheld sum is not a carried one, and only the carried kind is caught
    # below. `table_witness()` returns None for a peering that is not
    # reporting while the read itself stays perfectly fresh, so a poll missing
    # from the middle of the plateau leaves `witness_age_s` blameless while
    # "and it never changed again" is unsupported across the hole -- and a
    # peering dropping *after* convergence is precisely when that doubt
    # matters, because a partial read looks exactly like a table that shrank.
    # The same rule as `series_truncated`, one step inward, and it needs no
    # invented number: it is an absence of evidence, not a threshold.
    # Deliberately not fitted to an observed failure -- no recorded run on
    # this host reaches it (0 of 1303 post-first-reading samples withhold an
    # export sum), so this closes a blind spot rather than explaining a run.
    if plateau[-1][0] - plateau[0][0] + 1 != len(plateau):
        return _delivery('gauge_withheld_across_plateau', **known)

    # Absent evidence and bad evidence get different names, on the rule
    # `findings.py` follows for `inconclusive` against `unresolved` and
    # `summary.py` for `unreadable` against `failed`. An artifact written
    # before these fields existed can attest to nothing; one whose sampler
    # froze was asked and answered staleness.
    reads = [s.get('witness_monotonic_s') for _, s in plateau]
    ages = [s.get('witness_age_s') for _, s in plateau]
    if any(r is None for r in reads) or any(a is None for a in ages):
        return _delivery('gauge_undated', **known)
    # The plateau has to rest on more than one *observation*, which the read
    # timestamps say and the age bound does not: `bench()` re-pairs the last
    # reading with every later monitor sample, so a target poll thread that
    # died leaves a plateau of `WITNESS_CARRY_SAMPLES` samples whose ages are
    # 1s..5s and all within bound -- a perfect plateau made of one reading,
    # which is `still_changing`'s rule in read-space.
    #
    # Counted distinctly rather than required to be all-distinct, and the
    # difference is load-bearing. A duplicate read is *ordinary*: the target's
    # poll and the monitor's are independent loops, so whenever the target's
    # CLI read is the slower of the two a reading spans two monitor samples
    # and is carried twice -- `TARGET_TABLE_RESAMPLED` says so, and 11 of the
    # 39 recorded runs on this host contain one somewhere in the series. That
    # is likeliest on exactly the large-table runs this measurement exists
    # for, so refusing on any duplicate would withhold the answer from the
    # rows that need it while naming a dead sampler that was alive. Two
    # distinct reads plus the age bound below is the honest pair: at least two
    # independent looks, none of them older than the tracker's own carry
    # bound.
    if len(set(reads)) < 2:
        return _delivery('gauge_carried_across_plateau', **known)
    if max(ages) > DELIVERY_WITNESS_MAX_AGE_S:
        return _delivery('gauge_stale_across_plateau', **known)

    # Scanned over every sample from the plateau's start, not only the ones
    # carrying a reading: `monitor_accepted` is recorded on every poll whatever
    # the gauge did, so restricting this to readings makes a crossing that
    # happened during a withheld poll invisible and returns
    # `monitor_never_drawn_level` for a session the document's own
    # `monitor_final` disproves -- a refusal naming a disagreement that did
    # not happen, which sends a reader to the MRT consistency check for a
    # consistent session.
    start_index = plateau[0][0]
    for index in range(start_index, len(samples)):
        accepted = samples[index].get('monitor_accepted')
        if accepted is not None and accepted >= final:
            break
    else:
        return _delivery('monitor_never_drawn_level', **known)

    sample = samples[index]
    complete_s = _sample_time(sample)
    # Bounded by the poll that found it and the one before, on the rule both
    # poll loops already follow. The first sample is bounded by the clock
    # origin instead: nothing before the instrument arrived is visible.
    previous_s = _sample_time(samples[index - 1]) if index else 0.0
    # A resolved section with no answer in it is the one outcome `_delivery()`
    # exists to prevent: `complete_s` is documented as null only when
    # `unresolved_reason` is set, so a null reason beside a null answer leaves
    # the branch unnameable. Samples carry `monotonic_s` on every path
    # `bench()` writes, so this is the undated-artifact case one field over.
    if complete_s is None or previous_s is None \
            or known['plateau_start_s'] is None:
        return _delivery('no_sample_times', **known)
    known['complete_s'] = complete_s
    known['resolution_s'] = round(complete_s - previous_s, 6)
    known['monitor_lag_s'] = round(complete_s - known['plateau_start_s'], 6)
    return _delivery(None, **known)


def target_table_section(samples, unmeasured_reason=None, witness_rule=None):
    """The per-poll witness series, and the peak and final value of each.

    Derives no verdict of its own. The rule that reads this witness lives in
    `convergence.py`, where it decides the run, and `witness_rule` is that
    tracker's account of what it did -- carried here rather than recomputed,
    because two derivations of one verdict can disagree and the one that
    decided the run is the one worth publishing. It is absent when the rule
    changed nothing, so a run whose monitor count never fell writes the
    document it always did.

    The raw samples are kept beside the summary for the reason `summary.py`
    keeps its observations: a number whose inputs are gone is not auditable,
    and the shape here -- where in the run a peak sits, and what the other
    series were doing at that moment -- is the whole evidence.

    A series with no reading at all is absent rather than null-filled, and a
    single missing reading leaves that sample's value None: a poll that could
    not be parsed and a target holding nothing must not look the same.

    Two things every series states about *when* it was read, because without
    them a truncated or frozen series is indistinguishable from a steady table
    -- which is the exact claim a rule built on this would be making.
    `final_monotonic_s` is when the last reading was taken: the target's sums
    are withheld on any poll where a session was not reporting, so a peer that
    drops near the end truncates the target series while `monitor_accepted`
    runs on, and a `decline_from_peak` compared across those two windows is
    comparing different runs. `max_witness_age_s` is the oldest a carried
    witness got: the target poll thread is not the monitor's, so if it stops,
    every later sample repeats its last reading and the series reports
    `decline_from_peak` 0.0 for a target nobody asked. No threshold is applied
    to either -- there is no measured number to put on one, and a verdict is
    not this function's job.
    """
    samples = [dict(sample) for sample in samples]
    series = {}
    for name in TARGET_TABLE_SERIES:
        observed = [sample for sample in samples
                    if sample.get(name) is not None]
        if not observed:
            continue
        values = [sample[name] for sample in observed]
        peak = max(values)
        final = values[-1]
        ages = [sample['witness_age_s'] for sample in observed
                if sample.get('witness_age_s') is not None]
        series[name] = {
            # Monitor polls that carried a reading -- not target reads. The
            # target's own series is resampled onto the monitor's cadence; see
            # TARGET_TABLE_RESAMPLED.
            'observations': len(values),
            'resampled_onto_monitor_polls': name in TARGET_TABLE_RESAMPLED,
            'peak': peak,
            'final': final,
            'final_monotonic_s': observed[-1].get('monotonic_s'),
            # Only meaningful for the carried target-side series; the monitor's
            # own count is read on the very poll it is recorded with.
            'max_witness_age_s': (max(ages) if ages
                                  and name in TARGET_TABLE_RESAMPLED else None),
            # Against the peak, not the previous sample, because that is the
            # comparison ConvergenceTracker makes and the one the failing runs
            # are decided by.
            'decline_from_peak': (round((peak - final) / peak, 6)
                                  if peak else None),
        }
    # Derived here rather than beside `monitor_metrics()`, because it is a
    # reading of *this* series and nothing else, and putting it next to the
    # monitor's own intervals is the first step towards being mistaken for
    # one. `delivery_metrics()` says so itself: `derived` is true, the rule is
    # named, and it carries the samples it was computed from one key over.
    section = {'samples': samples, 'series': series,
               'delivery': delivery_metrics(samples)}
    if unmeasured_reason:
        section['unmeasured_reason'] = unmeasured_reason
    if witness_rule:
        section['witness_rule'] = witness_rule
    return section


def event_artifact(events: Iterable[LifecycleEvent], status, testers=None,
                   churn=None, policy_reload=None, export=None,
                   target_table=None, target_table_unmeasured_reason=None,
                   target_table_witness_rule=None, instrument=None):
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
        # Beside the per-generator sections, never instead of them. A ten
        # injector MRT run needs one place that says whether the whole
        # workload was offered -- reading that off ten sections means noticing
        # the one with a null interval, which is exactly the thing a reader
        # skims past.
        artifact['tester_fleet'] = tester_fleet_metrics(events, testers)
    # Present whenever the run had receivers, and absent otherwise, so a run
    # with no fan-out keeps exactly the document it has always produced. The
    # receiver set is the union of the ones the controller named and the ones
    # that produced events: a receiver observed but not declared is a wiring
    # fault, and dropping its intervals here would hide it in the one document
    # that could show it.
    export_producers = {event.producer for event in events
                        if event.phase == EventPhase.EXPORT}
    if export or export_producers:
        artifact['export'] = _export_section(events, export, export_producers)
    # Present whenever a churn sequence was driven *or* could not be, and
    # absent otherwise, so a run with no churn keeps exactly the document it
    # has always produced. Evidence alone is enough: a sequence refused before
    # its first burst -- a churn block larger than the converged table -- has
    # nothing in the event stream, and a document with no churn section at all
    # would read as a run that never asked for any.
    if churn or any(event.phase == EventPhase.CHURN for event in events):
        artifact['churn'] = _churn_section(events, churn)
    # Present on the same rule as the churn section, and absent otherwise so a
    # run that asked for no reload keeps the document it has always produced.
    # Evidence alone is enough: a reload refused before it was issued -- a
    # policy that would reject more than the target converged on -- has nothing
    # in the event stream, and a document with no section at all would read as
    # a run that never asked for one.
    if policy_reload or any(event.phase == EventPhase.POLICY_RELOAD
                            for event in events):
        artifact['policy_reload'] = _policy_reload_section(
            events, policy_reload)
    # Present when the target was read, and also when it *could* have been read
    # and was not -- the latter carrying an `unmeasured_reason`, so a BIRD run
    # whose poll never produced a sample cannot be mistaken for a daemon with
    # no gauge at all. A daemon that cannot answer gets no section, so every
    # such run keeps exactly the document it has always had.
    if target_table or target_table_unmeasured_reason:
        artifact['target_table'] = target_table_section(
            target_table or [], target_table_unmeasured_reason,
            target_table_witness_rule)
    # Present only when a sampler actually failed a read, so a clean run keeps
    # exactly the document it has always produced.
    #
    # This is the run saying its own evidence was incomplete. Both samplers
    # read `gobgp neighbor -j`, whose errors come back JSON-encoded and used to
    # kill the reading thread outright; they now survive, and the whole point
    # of surviving is lost if the run cannot say it happened. A target sampler
    # that missed reads may still have reached `note_neighbors_checkpoint()`
    # late, which moves the assurance window from 5 samples to 20 and shows up
    # nowhere else; a monitor that missed reads has gaps in the series every
    # published timing is derived from.
    if instrument:
        artifact['instrument'] = dict(instrument)
    return artifact


def _export_section(events, evidence, observed_receivers=()):
    """The derived export intervals, plus what the controller alone knows.

    `evidence` carries the run-level facts the event stream cannot show -- the
    check-point the receivers were judged against, a poll that could not be
    read -- with the per-receiver half under `sessions`, keyed by container
    name. Both halves are refused where they would land on a derived name, for
    the reason `_tester_section()` refuses it: a caller able to overwrite a
    measured interval with a value the events do not support defeats the point
    of deriving them.
    """
    evidence = dict(evidence or {})
    sessions = dict(evidence.pop('sessions', None) or {})
    receivers = set(sessions) | set(observed_receivers)
    measured = export_metrics(events, receivers)
    collisions = sorted(set(evidence) & set(measured))
    if collisions:
        raise MeasurementEventError(
            'export evidence would overwrite derived {0}'.format(
                ', '.join(collisions)))
    for name, detail in sessions.items():
        derived = measured['sessions'][name]
        clashes = sorted(set(detail or {}) & set(derived))
        if clashes:
            raise MeasurementEventError(
                'export evidence for {0} would overwrite derived {1}'.format(
                    name, ', '.join(clashes)))
        derived.update(detail or {})
    measured.update(evidence)
    return measured


def _policy_reload_section(events, evidence):
    '''The derived reload interval, plus what the controller alone knows.

    The evidence is caller-supplied -- whether the policy was applied, why not,
    the mechanism used, and the target CPU sampled across the interval -- and
    is refused where it would land on a derived name, for the reason
    `_churn_section()` and `_tester_section()` refuse the same thing: a caller
    able to overwrite a measured interval with a value the events do not
    support defeats the point of deriving them.
    '''
    measured = policy_reload_metrics(events)
    evidence = dict(evidence or {})
    collisions = sorted(set(evidence) & set(measured))
    if collisions:
        raise MeasurementEventError(
            'policy reload evidence would overwrite derived {0}'.format(
                ', '.join(collisions)))
    measured.update(evidence)
    return measured


def _churn_section(events, evidence):
    '''The derived burst intervals, plus what the controller alone knows.

    The evidence is caller-supplied -- whether the sequence ran to the end and
    why not -- and is refused where it would land on a derived name, for the
    reason `_tester_section()` refuses the same thing: a caller that could
    overwrite a measured interval with a value the events do not support
    defeats the point of deriving them.
    '''
    measured = churn_metrics(events)
    evidence = dict(evidence or {})
    collisions = sorted(set(evidence) & set(measured))
    if collisions:
        raise MeasurementEventError(
            'churn evidence would overwrite derived {0}'.format(
                ', '.join(collisions)))
    measured.update(evidence)
    return measured


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
