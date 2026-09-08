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


def event_artifact(events: Iterable[LifecycleEvent], status, testers=None,
                   churn=None, policy_reload=None):
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
    return artifact


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
