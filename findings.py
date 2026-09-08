'''Conservative bottleneck findings over the intervals a run measured.

Phase 4 of the measurement plan asks one question of a finished run: what was
the run waiting for?  The honest answer is usually not "the tester" or "the
target" -- it is "these measurements do not say" -- and the reason this is a
module rather than a print statement is that the conditions under which it may
say something have to be named, written down, and tested.

Two kinds of not-saying are kept apart, because they ask for different work:

  `inconclusive`  the measurement that would decide it was never made.  A
      generator that never reported completion, a monitor that never reached
      the check-point, a run with no generator that can be asked at all.
  `unresolved`  the measurements exist, and something forbids attributing
      them.  A busy host, a run near the memory ceiling, a generator whose
      completion is counted where the routes were queued rather than sent.

Neither is a failure of the run, and neither is a validity boolean: a finding
carries the rule it applied and the raw durations it applied it to, so a
reader can disagree with the policy without having to re-derive the numbers.

Kept free of Docker and of bgperf2 imports, like contention.py and
convergence.py, so the policy is testable without a daemon.  Its input is the
event artifact measurements.py builds, which means it can never reason about a
duration the event stream did not support.
'''

from contention import CONTENTION_PERCENT, format_foreign_load


FINDINGS_SCHEMA = 'bgperf2/measurement-findings/v1alpha1'

# Named, and versioned separately from the artifact schema, because the same
# durations can be published under a changed policy: a reader comparing two
# runs needs to know whether the verdicts were reached the same way.
POLICY_VERSION = 'conservative/v1'

# What the run was waiting for, where it can be said at all.
TESTER = 'tester'
TARGET_OR_MONITOR = 'target_or_monitor'
UNRESOLVED = 'unresolved'
INCONCLUSIVE = 'inconclusive'

# What a finding does to the verdict.  `attribution` proposes a component;
# `confounder` withholds one; `missing_evidence` says the deciding measurement
# was never made; `qualification` narrows how an interval may be read without
# by itself preventing an attribution some other interval supports.
ATTRIBUTION = 'attribution'
CONFOUNDER = 'confounder'
MISSING_EVIDENCE = 'missing_evidence'
QUALIFICATION = 'qualification'

# Host idle at or under this leaves no spare CPU, so any interval in the run
# may be a queue for the scheduler rather than a property of a daemon.  It is
# host-wide and includes bgperf2's own load, which is why it withholds an
# attribution instead of supplying one: see the CPU attribution boundary in
# the implementation plan.  Per-role, time-aligned CPU would be needed to say
# more, and no such measurement exists yet.
HOST_IDLE_PERCENT = 5.0

# Free memory under this share of the host's total means the run was close
# enough to reclaim that its timings include page pressure.  A fraction rather
# than a constant because the column is also moved by bgperf2's own logging
# when the bench directory is tmpfs -- a 31GB tester log is not a daemon's
# working set, and on a small host it is the whole of the difference.
LOW_FREE_MEMORY_FRACTION = 0.05

# How much of the offered table has to fall inside the measured injection
# interval before that interval may be read as the generator's send.
#
# This is the rule that keeps a queue-side counter from being read as a send
# rate, without the policy having to know which generator produced it.  BIRD
# 2.19 counts an export when the route is handed to the BGP protocol, so a
# 4-peer 250k run reported its whole 1,000,000 prefixes offered at 1.94s while
# the monitor had seen 215,552: repeated runs put between 0 and 153,744 of the
# million inside the measured interval, i.e. at most 15% of it, depending only
# on where the first poll landed.  A generator that really was dribbling its
# table out over the run has nearly all of it inside the interval instead.
INJECTION_COVERAGE = 0.5


def _finding(name, kind, policy, summary, evidence, component=None):
    return {
        'finding': name,
        'kind': kind,
        'limiting_component': component,
        'policy': policy,
        'summary': summary,
        'evidence': evidence,
    }


def derive_findings(artifact, host=None):
    '''Qualify a finished run's intervals, naming the rule behind each verdict.

    `artifact` is the document `measurements.event_artifact()` builds.  `host`
    carries the run-level evidence that is not an event -- idle CPU, foreign
    CPU, free memory -- since those are sampled by the controller's own
    threads and never enter the lifecycle stream.  Both are read defensively:
    a run whose generators could not be polled at all still has to produce a
    document, and it must say that it cannot attribute rather than defaulting
    to a component.
    '''
    findings = []
    findings.extend(_timing_findings(
        artifact.get('status'),
        artifact.get('measurements') or {},
        artifact.get('tester_fleet')))
    findings.extend(_backpressure_findings(artifact.get('testers') or {}))
    findings.extend(_host_findings(host or {}))
    component, decided_by = _resolve(findings)
    return {
        'schema': FINDINGS_SCHEMA,
        'policy_version': POLICY_VERSION,
        'limiting_component': component,
        'decided_by': decided_by['finding'] if decided_by else None,
        'reason': decided_by['summary'] if decided_by
                  else 'no interval in this run supports naming a component',
        'findings': findings,
    }


def _timing_findings(status, measurements, fleet):
    '''What the run's own intervals support, in the order they can fail.

    Each early return is a measurement whose absence makes everything below it
    unreadable rather than merely uncertain: an interval bounded by a
    completion that never happened is not a short interval.
    '''
    if not fleet:
        return [_finding(
            'missing_timing_evidence', MISSING_EVIDENCE,
            'attribution needs a generator that reports its own sending',
            'no generator in this run could be asked what it offered, so the '
            'run has no measured injection to compare with its convergence',
            {'status': status,
             'convergence_s': measurements.get('convergence_s')})]

    if fleet['incomplete_testers']:
        return [_finding(
            'tester_incomplete', MISSING_EVIDENCE,
            'every generator must report completion before the load counts '
            'as delivered',
            '{0} of {1} generators reported completion; the workload was '
            'never fully offered, so no interval bounded by it can be '
            'read'.format(fleet['testers_complete'], fleet['testers']),
            {'testers': fleet['testers'],
             'testers_complete': fleet['testers_complete'],
             'incomplete_testers': list(fleet['incomplete_testers'])})]

    if measurements.get('convergence_s') is None:
        return [_finding(
            'missing_timing_evidence', MISSING_EVIDENCE,
            'attribution needs the monitor to have reached the check-point',
            'the monitor never reached the required count, so the run has no '
            'end to measure its generators against',
            {'status': status,
             'complete_s': fleet['complete_s'],
             'convergence_s': None})]

    findings = []
    injection = fleet['injection_s']
    injection_resolution = fleet['injection_resolution_s']
    tail = fleet['post_injection_tail_s']
    tail_resolution = fleet['post_injection_tail_resolution_s']
    offered = fleet['offered_prefixes']
    covered = fleet['offered_in_interval']
    rate = fleet['offered_rate_pps']
    reported = fleet['reported_injection_s']

    # An interval no wider than the look that bounds it is not a fast
    # injection, it is one this cadence could not resolve.  Every MRT run has
    # this shape -- a 10,000-prefix walk is over in about a millisecond -- so
    # it is a qualification and not a confounder: it forbids reading the
    # injection as the run's cost, and forbids nothing about the tail.
    resolved_injection = (injection is not None
                          and injection_resolution is not None
                          and injection > injection_resolution)
    if not resolved_injection:
        findings.append(_finding(
            'injection_unresolved', QUALIFICATION,
            'an interval at or under the poll that bounds it is unresolved, '
            'not short',
            'the fleet injection was not resolved at this poll resolution, '
            'so the generators cannot be shown to have cost the run anything',
            {'injection_s': injection,
             'injection_resolution_s': injection_resolution,
             'reported_injection_s': reported}))

    coverage = None
    if offered and covered is not None:
        coverage = covered / offered

    # Whether the boundary between injection and tail can be trusted at all.
    # It can, either because most of the table demonstrably crossed the
    # measured interval, or because the generator timed its own send and so
    # states directly when it stopped.  Where neither holds, the count went
    # final before the instrument first looked and the generator's completion
    # may sit anywhere inside its own sending -- which moves the boundary
    # between the two intervals this policy is trying to compare.
    trusted_boundary = ((coverage is not None
                         and coverage >= INJECTION_COVERAGE)
                        or reported is not None)
    if not trusted_boundary:
        # The count can be missing in two further ways, and neither may be
        # printed as a number: a generator that had no readable count at
        # completion, and one whose counter reset mid-run when a protocol
        # restarted, which is where `offered_in_interval` is None rather than
        # small. Both reach this finding, and saying "only None of them" would
        # publish a shortfall that was really an unreadable instrument.
        if offered is None:
            crossed = ('no generator produced a readable count at its '
                       'completion')
        elif covered is None:
            crossed = ('a generator\'s counter reset mid-run, so how much of '
                       'the {0} prefixes offered crossed the measured '
                       'interval is unknown'.format(offered))
        else:
            crossed = ('the generators offered {0} prefixes and only {1} of '
                       'them crossed the measured interval'.format(
                           offered, covered))
        findings.append(_finding(
            'injection_boundary_unresolved', CONFOUNDER,
            'a generator whose count saturated before the first poll cannot '
            'place its own completion',
            '{0}, and none of them timed its own send, so completion may '
            'precede the end of their sending'.format(crossed),
            {'offered_prefixes': offered,
             'offered_in_interval': covered,
             'injection_s': injection,
             'reported_injection_s': reported}))

    if tail is None or tail_resolution is None:
        findings.append(_finding(
            'missing_timing_evidence', MISSING_EVIDENCE,
            'attribution needs both ends of the post-injection tail',
            'the interval between the last generator finishing and the '
            'required count has no measured bound',
            {'post_injection_tail_s': tail,
             'post_injection_tail_resolution_s': tail_resolution}))
        return findings

    if tail > tail_resolution:
        # Everything the generators were configured to send had been handed
        # over, and the run went on for longer than either poll loop's own
        # uncertainty.  That time was spent somewhere between the target and
        # the monitor, and nothing here separates the two: the monitor is the
        # instrument, so its own polling is inside this number.
        findings.append(_finding(
            'post_injection_tail', ATTRIBUTION,
            'a tail wider than the polls bounding it is time the generators '
            'did not spend',
            'the run continued for {0:.1f}s after the last generator '
            'finished, which is longer than the {1:.1f}s bounding the two '
            'polls'.format(tail, tail_resolution),
            {'post_injection_tail_s': tail,
             'post_injection_tail_resolution_s': tail_resolution,
             'injection_s': injection,
             'convergence_s': measurements.get('convergence_s')},
            component=TARGET_OR_MONITOR))
        return findings

    # No tail worth the name: the monitor reached the check-point while the
    # generators were finishing, or within one look of it.  That is the shape
    # of a run the target was keeping up with -- but it only names the tester
    # if the generators can be shown to have been sending for a measurable
    # part of it, at a rate this instrument could actually observe.
    if resolved_injection and rate is not None \
            and coverage is not None and coverage >= INJECTION_COVERAGE:
        # An overlap is reported as one rather than as a near-zero tail: the
        # monitor reaching the check-point well before the generators finished
        # is the strongest form of this finding, and describing it as "within
        # one poll" would understate it.
        reached = 'within {0:.1f}s of their completion'.format(tail_resolution)
        if tail < -tail_resolution:
            reached = '{0:.1f}s before they finished'.format(-tail)
        findings.append(_finding(
            'tester_limited', ATTRIBUTION,
            'the generators must be measured sending for the run to be '
            'called generator-bound',
            'the generators were still offering the workload {0:.1f}s into '
            'the run, at {1:.0f} prefixes/s over a measured {2:.1f}s, and the '
            'monitor reached the required count {3}'.format(
                fleet['complete_s'], rate, injection, reached),
            {'injection_s': injection,
             'injection_resolution_s': injection_resolution,
             'complete_s': fleet['complete_s'],
             'offered_prefixes': offered,
             'offered_in_interval': covered,
             'offered_rate_pps': rate,
             'post_injection_tail_s': tail,
             'post_injection_tail_resolution_s': tail_resolution},
            component=TESTER))
        return findings

    # Two different ways to arrive here, and they are not the same statement.
    # A traced bgpdump2 run has a measured five-second injection with none of
    # the table inside it, and reporting that as a run that finished inside
    # its polls would be false about the one number it published.
    if not resolved_injection:
        summary = ('the whole run finished inside what these poll loops can '
                   'resolve, so neither the generators nor the target can be '
                   'shown to have held it up')
    else:
        summary = ('the generators were measured sending for {0:.1f}s, but '
                   'too little of the table crossed that interval to read it '
                   'as their send'.format(injection))
    findings.append(_finding(
        'no_dominant_interval', QUALIFICATION,
        'neither interval is long enough, or well enough observed, to name a '
        'component',
        summary,
        {'injection_s': injection,
         'injection_resolution_s': injection_resolution,
         'post_injection_tail_s': tail,
         'post_injection_tail_resolution_s': tail_resolution,
         'offered_in_interval': covered,
         'offered_rate_pps': rate}))
    return findings


def _backpressure_findings(testers):
    '''Blocked writes, reported as an interaction rather than a component.

    A generator held up on a socket says the two ends did not keep pace; it
    does not say which end.  The receiver may not be draining, or the sender
    may be outrunning a link that is doing exactly what it should.  Assigning
    it would be a guess, so it withholds an attribution instead of supplying
    one.

    Only the cumulative counts of *being blocked* qualify -- writes the socket
    took part of, and encode passes that found no room.  BIRD 3's queue depths
    are deliberately not read here: a nonzero `TX pending` is what a healthy
    session looks like at the instant it is polled, and treating it as
    backpressure would withhold every BIRD 3 verdict there is.
    '''
    blocked = {}
    for producer, section in sorted(testers.items()):
        evidence = (section or {}).get('backpressure') or {}
        if not evidence.get('available'):
            continue
        counts = {key: evidence[key]
                  for key in ('max_blocked_writes', 'max_send_stalls')
                  if evidence.get(key)}
        if counts:
            blocked[producer] = counts
    if not blocked:
        return []
    return [_finding(
        'backpressure_observed', CONFOUNDER,
        'a blocked write is an interaction between two ends, not a property '
        'of one',
        '{0} reported blocked writes, so the run includes time one end spent '
        'waiting for the other and no interval here says which'.format(
            ', '.join(sorted(blocked))),
        {'generators': blocked})]


def _host_findings(host):
    '''What the machine was doing to the run, from the controller's samplers.

    None of these name a component.  Every one of them is a reason the
    published intervals belong to this machine on this day rather than to the
    daemon under test, which is exactly the case in which a verdict would be
    read as a finding about the daemon.
    '''
    findings = []
    idle = host.get('min_idle_percent')
    if idle is not None and idle <= HOST_IDLE_PERCENT:
        findings.append(_finding(
            'host_cpu_saturated', CONFOUNDER,
            'host saturation without per-role CPU leaves the component '
            'unresolved',
            'host idle fell to {0:.0f}%, and this run has no time-aligned '
            'per-role CPU evidence to say whose work that was'.format(idle),
            {'min_idle_percent': idle,
             'threshold_percent': HOST_IDLE_PERCENT}))

    foreign = host.get('max_foreign_cpu_percent')
    if foreign is not None and foreign >= CONTENTION_PERCENT:
        # Named where the run recorded them, never re-derived: this reads the
        # artifact long after the run, and a competitor that has since exited
        # is exactly the case -- four MRT calibration runs on the campaign host
        # were withheld by a `python` process that was gone before anyone
        # asked. An older artifact carries no names and says so by their
        # absence rather than by an empty list.
        named = host.get('max_foreign_cpu_processes')
        evidence = {'max_foreign_cpu_percent': foreign,
                    'threshold_percent': CONTENTION_PERCENT}
        summary = ('processes outside the benchmark used up to {0:.1f} cores '
                   'during this run'.format(foreign / 100.0))
        if named:
            evidence['processes'] = named
            summary += ', led by ' + format_foreign_load(named)
        findings.append(_finding(
            'foreign_cpu_contention', CONFOUNDER,
            'a run sharing the machine is not comparable with one that did '
            'not',
            summary, evidence))

    free = host.get('min_free_bytes')
    total = host.get('total_memory_bytes')
    if free is not None and total:
        share = free / total
        if share < LOW_FREE_MEMORY_FRACTION:
            findings.append(_finding(
                'low_free_memory', CONFOUNDER,
                'a run near the memory ceiling is timing reclaim as well as '
                'BGP',
                'free memory fell to {0:.1f}% of the host, so these intervals '
                'include page pressure'.format(share * 100.0),
                {'min_free_bytes': free,
                 'total_memory_bytes': total,
                 'threshold_fraction': LOW_FREE_MEMORY_FRACTION}))
    return findings


def _resolve(findings):
    '''Reduce the findings to one component and the finding that decided it.

    Missing evidence outranks a confounder because they are different
    statements: one says the deciding measurement was never made, the other
    that it was made and cannot be attributed.  Both outrank an attribution --
    a proposed component is only ever published when nothing above it objects.
    '''
    for kind, component in ((MISSING_EVIDENCE, INCONCLUSIVE),
                            (CONFOUNDER, UNRESOLVED)):
        blocking = [f for f in findings if f['kind'] == kind]
        if blocking:
            return component, blocking[0]
    for f in findings:
        if f['kind'] == ATTRIBUTION:
            return f['limiting_component'], f
    for f in findings:
        if f['kind'] == QUALIFICATION:
            return UNRESOLVED, f
    return UNRESOLVED, None


def policy_failure(exc):
    '''A findings section for a policy that raised, so the artifact still writes.

    The event artifact's job is to preserve the evidence; this module's is to
    hold an opinion about it.  A run that has already converged must not lose
    its only record because the opinion could not be formed -- so the caller
    catches, and publishes the failure in the same shape as a verdict rather
    than an absent section that would read as a run with nothing to say.
    '''
    return {
        'schema': FINDINGS_SCHEMA,
        'policy_version': POLICY_VERSION,
        'limiting_component': INCONCLUSIVE,
        'decided_by': None,
        'reason': 'the qualification policy failed: {0}: {1}'.format(
            type(exc).__name__, exc),
        'findings': [],
    }


def describe_findings(result):
    '''The lines a finished run prints: the verdict, then what shaped it.

    The verdict already carries the summary of whichever finding decided it,
    so that one is not repeated below.  The rest are printed in full rather
    than counted: a run qualified by a busy host and one qualified by an
    unreadable generator have nothing in common except the word `unresolved`.
    '''
    lines = ['limiting component: {0} -- {1}'.format(
        result['limiting_component'], result['reason'])]
    decided_by = result.get('decided_by')
    for finding in result['findings']:
        if finding['finding'] == decided_by:
            decided_by = None
            continue
        lines.append('finding: {0} ({1})'.format(
            finding['summary'], finding['finding']))
    return lines
