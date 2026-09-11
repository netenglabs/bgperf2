#!/usr/bin/env python3
'''Qualify a block's rows against the 64 GB timing validation campaign's own
acceptance rules.

`findings.py` decides what a *run* was waiting for. This decides whether a run
may be used for the *campaign's* version comparisons, which is a different and
stricter question: the plan's Acceptance Rules ask for correct final state,
complete tester evidence, verified provenance for all three roles, no tester
error or timeout, no material foreign CPU contention, memory above a guardrail
of its own, and a limiting component that was either assigned or explicitly
left unresolved.

Three things it deliberately does not do:

- **It does not re-derive a measurement.** Every number here is read from the
  documents the run published; a checker that recomputed one would be a second
  implementation of the measurement, and the two would disagree eventually --
  on exactly the runs anyone cared about.
- **It does not delete or rewrite anything.** The plan says a rejected row is
  preserved with its findings and excluded only from the comparisons it cannot
  support, so this prints and returns a verdict and touches nothing.
- **It does not take the campaign's memory guardrail from `findings.py`.**
  That module withholds a verdict below 5% free, which is a statement about
  whether the *timings* include page pressure. The campaign guardrail is 20%,
  a statement about whether the *host* is safe to keep running blocks on. Two
  different questions, deliberately two different numbers; the stricter one
  produces a note here rather than silently overriding the artifact's finding.

It has one extra mode, for Block 1. A *calibration* case is a run whose
bottleneck was chosen in advance by starving one role from outside bgperf2,
and `--expect-limiting` / `--expect-egress-mbit` say what that case was built
to produce. Those two are separate conditions on purpose: at a size where the
unconstrained shape is already generator-bound, a slow-tester case qualified
on its verdict alone would be cleared by a constraint that bound nothing.

Reads the batch CSV by column name, never by index: that row is positional for
`create_batch_graphs()` and has drifted by a column once already.
'''
import argparse
import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from contention import CONTENTION_PERCENT  # noqa: E402
from findings import (INCONCLUSIVE, TARGET_OR_MONITOR, TESTER,  # noqa: E402
                      UNRESOLVED)

# The campaign's own guardrail, from the 64 GB safety contract: "Flag a row
# when minimum free memory is below 20% of recorded host memory."
CAMPAIGN_FREE_MEMORY_FRACTION = 0.20

LIMITING_COMPONENTS = (TESTER, TARGET_OR_MONITOR, UNRESOLVED, INCONCLUSIVE)

# How far a rate-capped generator may be off the cap imposed on it. Loose on
# purpose: the question a calibration case asks is whether the cap bound the
# traffic at all, and the alternative it has to separate is an unshaped
# session an order of magnitude faster. Measured on this host, both injectors
# came back within 4%.
DEFAULT_EGRESS_TOLERANCE = 0.25

# Every run must publish these, whatever the generator or the target.  A
# missing one is not a slow run, it is a run nobody can qualify.
REQUIRED_EVENTS = ('bench_clock_started', 'monitor_first_prefix',
                   'monitor_required_reached', 'convergence_confirmed')

OK, NOTE, FAIL = 'ok', 'note', 'fail'


class Check(object):
    def __init__(self, name, status, detail):
        self.name = name
        self.status = status
        self.detail = detail

    def as_dict(self):
        return {'check': self.name, 'status': self.status,
                'detail': self.detail}


# `Mem (GB)` is written by `mem_human()`, which picks its unit from the value:
# GB above a gibibyte, then MB, KB and a bare B below. The column is named GB
# and every host this campaign runs on reports GB, so stripping only that
# suffix worked -- but on any smaller host `total` came back `None` and the
# memory guardrail failed the row for "does not carry both free and total
# memory", diagnosing a missing column that was present and populated. Convert
# instead of stripping: a unit that is dropped rather than applied is worse
# than one that is not understood.
_MEM_UNITS = (('GB', 1.0), ('MB', 1.0 / 1024.0), ('KB', 1.0 / (1024.0 ** 2)),
              ('B', 1.0 / (1024.0 ** 3)))


def _row_float(row, column):
    raw = (row.get(column) or '').strip()
    if not raw:
        return None
    scale = 1.0
    # Longest suffix first: 'B' is a suffix of 'GB', 'MB' and 'KB'.
    for suffix, factor in _MEM_UNITS:
        if raw.upper().endswith(suffix):
            raw = raw[:-len(suffix)]
            scale = factor
            break
    try:
        return float(raw) * scale
    except ValueError:
        return None


def _row_int(row, column):
    value = _row_float(row, column)
    return None if value is None else int(value)


def load_rows(csv_path):
    '''Map CSV `name` to the row, by column name.'''
    rows = {}
    with open(csv_path, newline='', encoding='utf-8') as f:
        reader = csv.reader(f)
        try:
            header = [h.strip() for h in next(reader)]
        except StopIteration:
            return rows
        for raw in reader:
            if not raw:
                continue
            # A short row is a row written by an older build, and indexing it
            # against the current header is the failure `summary.py` calls
            # `unreadable`.  Keep it, flagged, rather than dropping it: a row
            # that has gone missing is indistinguishable from a pass that
            # never ran.
            row = dict(zip(header, [c.strip() for c in raw]))
            if len(raw) != len(header):
                row['__short_row__'] = '{0} fields against {1} columns'.format(
                    len(raw), len(header))
            rows[row.get('name', '')] = row
    return rows


def row_name_for(artifact):
    '''The CSV `name` a run's artifact corresponds to.

    `run_name()` already carries the repetition suffix, and the artifact
    records that same string -- so this is a lookup, not a reconstruction.
    Appending the repetition here again produced "bird 3.3.2 #1 #1" and matched
    no row at all, which read as a missing row rather than as a bad key.
    Reading the name off the artifact also keeps this off
    `bench_output_prefix()`'s file naming, which carries every workload
    dimension and would have to be reimplemented to be parsed.
    '''
    return (artifact.get('run') or {}).get('name') or ''


def check_provenance(artifact, versions):
    checks = []
    tool = artifact.get('bgperf2') or {}
    missing = [k for k in ('revision', 'event_schema', 'findings_schema',
                           'findings_policy') if not tool.get(k)]
    if missing:
        checks.append(Check(
            'tool_provenance', FAIL,
            'events artifact does not say which bgperf2 measured it: missing '
            + ', '.join(missing)))
    else:
        checks.append(Check('tool_provenance', OK, '{0} ({1})'.format(
            tool['revision'], tool['findings_policy'])))

    if versions is None:
        checks.append(Check('role_provenance', FAIL,
                            'no versions manifest beside the artifact'))
        return checks

    unknown = []
    absent = []
    described = []
    roles = [('target', versions.get('target')),
             ('monitor', versions.get('monitor'))]
    for i, tester in enumerate(versions.get('testers') or []):
        roles.append(('tester[{0}]'.format(i), tester))
    if len(roles) == 2:
        absent.append('testers')
    for role, doc in roles:
        if not doc:
            absent.append(role)
            continue
        version = doc.get('version')
        image = doc.get('image')
        if not version or not image:
            absent.append(role)
        elif str(version).startswith('UNKNOWN'):
            # Never guessed at: `version_string()` says why it could not ask.
            unknown.append('{0}={1}'.format(role, version))
        else:
            described.append('{0} {1} ({2})'.format(role, version, image))
    if absent:
        checks.append(Check('role_provenance', FAIL,
                            'no version/image recorded for ' + ', '.join(absent)))
    elif unknown:
        checks.append(Check('role_provenance', FAIL,
                            'a role could not be identified: ' + '; '.join(unknown)))
    else:
        checks.append(Check('role_provenance', OK, '; '.join(described)))
    return checks


def check_status(artifact, row):
    checks = []
    status = artifact.get('status')
    if status == 'converged':
        checks.append(Check('status', OK, 'converged'))
    else:
        checks.append(Check('status', FAIL,
                            'run status is {0!r}'.format(status)))
    if row is None:
        checks.append(Check('stats_row', FAIL, 'no CSV row named by this run'))
        return checks
    if row.get('__short_row__'):
        checks.append(Check('stats_row', FAIL,
                            'row is not the header width ({0})'.format(
                                row['__short_row__'])))
        return checks
    failed = (row.get('failed') or '').strip()
    if failed:
        checks.append(Check('stats_row', FAIL, 'row is marked {0}: {1}'.format(
            failed, row.get('MSG') or 'no message')))
    else:
        checks.append(Check('stats_row', OK, 'elapsed (s) {0}, total time {1}'.format(
            row.get('elapsed (s)'), row.get('total time'))))

    required = _row_int(row, 'required')
    received = _row_int(row, 'received')
    run = artifact.get('run') or {}
    if required is None or received is None:
        checks.append(Check('route_counts', FAIL,
                            'row does not carry both required and received'))
    elif run.get('tester_type') in MRT_TESTER_TYPES:
        checks.extend(_mrt_route_counts(
            artifact, received, required,
            filtered=bool((row.get('filters') or '').strip()),
            row_filters=(row.get('filters') or '').strip()))
    else:
        # Synthetic, or a `-f` scenario that stated its own check-point:
        # `required` is a statement about the table either way, because
        # bgperf2 generated the prefix lists or the file named the number, and
        # a shortfall is route loss.
        if received < required:
            checks.append(Check('route_counts', FAIL,
                                'received {0} is below the required {1}'.format(
                                    received, required)))
        else:
            checks.append(Check('route_counts', OK,
                                'received {0} against a required {1}'.format(
                                    received, required)))
    return checks


# The same 1% `convergence.DROP_FRACTION` uses to decide that a monitor decline
# is not route loss, applied to the same kind of comparison one step later: two
# counts of one session that should agree. It is not a new tolerance invented
# for this check -- `tests/test_stats_contract.py` pins it against the tracker's
# constant, on the rule `summary.py`'s METRIC_RESOLUTION follows, because this
# script must not import bgperf2.
# The generators bgperf2 builds the prefix lists for. An MRT injector replays
# whatever its peer's table holds, so `required` is a guess for those and a
# statement of fact for these. Mirrors `bgperf2.SYNTHETIC_TESTER_TYPES`, which
# this script must not import -- it reads published documents and re-derives no
# measurement, which is what lets it run anywhere. Pinned against it in
# tests/test_stats_contract.py, on the rule the two constants below follow: a
# third synthetic generator added to bgperf2 and not here would route its rows
# down the MRT branch and quietly stop applying the strict `received >=
# required` rule.
SYNTHETIC_TESTER_TYPES = ('exa', 'bird')

# The generators that replay a file. Tested for by membership rather than by
# not-being-synthetic, because a third state exists: a `-f` scenario run
# records `tester_type: null`, and such a run states its own check-point in the
# file, so `required` is a statement of fact there exactly as it is for a
# synthetic one. Reading "not synthetic" as "MRT" downgraded those rows'
# `received >= required` from necessary to merely sufficient.
MRT_TESTER_TYPES = ('gobgp', 'bgpdump2')

WITNESS_AGREEMENT_FRACTION = 0.01

# How old the target's own reading may be before it stops being a cross-check.
# `convergence.WITNESS_CARRY_SAMPLES` (5) monitor polls at the 1s cadence both
# loops run, which is the bound the tracker already refuses to carry a witness
# past; pinned against it in tests/test_stats_contract.py for the reason the
# fraction above is.
STALE_WITNESS_S = 5.0


def _series_truncated_s(artifact, series):
    """How far a target series stops short of the monitor's own last reading.

    A witness is withheld -- not frozen -- whenever a configured peering is not
    reporting: `table_witness()` returns None for that key, the poll keeps
    running, and every reading it does produce is perfectly fresh. So the
    staleness guard, which asks how old the last reading was, sees nothing
    wrong while `final` is a mid-delivery value and `received` is the monitor's
    count at convergence. Comparing those publishes a truncated series as route
    loss: reproduced at 111% "disagreement" for a monitor peering that stopped
    reporting `pfxSnt` halfway through a run.

    `target_table_section()` publishes `final_monotonic_s` per series for
    exactly this -- "a peer that drops near the end truncates the target series
    while `monitor_accepted` runs on, and a `decline_from_peak` compared across
    those two windows is comparing different runs". The same applies one step
    later to any comparison against the row.

    None when either end cannot be dated, since an undateable series cannot be
    shown to be truncated either.
    """
    monitor = ((artifact.get('target_table') or {}).get('series') or {}).get(
        'monitor_accepted') or {}
    target_final = series.get('final_monotonic_s')
    monitor_final = monitor.get('final_monotonic_s')
    if target_final is None or monitor_final is None:
        return None
    return monitor_final - target_final


def _final_witness_age_s(artifact, series):
    """How old the last export reading was when it was recorded.

    `target_table.samples` carries `witness_age_s` per monitor poll; the
    section's `max_witness_age_s` is the maximum across the whole run, which
    answers a different question. Falls back to that maximum when the samples
    are not there, since an over-strict bound only mutes a check and never
    invents one.
    """
    samples = (artifact.get('target_table') or {}).get('samples') or []
    for sample in reversed(samples):
        # Both halves have to be there. Returning the sample's age as soon as
        # an export value is found skips the fallback whenever that sample
        # carries no `witness_age_s`, which hands back None -- and a None age
        # disables the staleness guard entirely, publishing a frozen sampler as
        # route loss, which is the one thing the guard exists to stop.
        if sample.get('exported_to_monitor') is not None \
                and sample.get('witness_age_s') is not None:
            return sample['witness_age_s']
    return series.get('max_witness_age_s')


def _mrt_route_counts(artifact, received, required, filtered=False,
                      row_filters=None):
    """Correctness for a run that replayed an MRT file.

    `required` is `0.99 * -p` for an MRT injector -- `-p` being the per-injector
    cap, not the size of the table, because the union of ten peers' overlapping
    views is not knowable in advance. It works as the monitor's check-point and
    it is not a statement about what the target should hold, so a shortfall
    against it is not route loss.

    Measured 2026-09-11 on one RIB: RustyBGP advertised 1,081,178, BIRD and
    OpenBGPD 1,056,779 each, and every FRR release ~961,000. Three totals from
    four daemons, because best-path selection and export rules genuinely
    differ. Judging all four against one absolute rejected every FRR row while
    passing the rest, which is a fact about the yardstick rather than about
    FRR -- and FRR's five releases agree with each other to 0.91%, so the
    within-daemon comparisons every Primary Question actually asks were never
    in doubt.

    What *is* checkable is consistency: the monitor's count against the
    target's own count of what it sent that very session. Completeness is not,
    and this check does not claim it -- an MRT run has no external statement of
    how big the table should be. Delivery is covered elsewhere and by different
    evidence: the run must have converged, and every injector must have
    reported its walk complete.

    A daemon with no witness gets a NOTE rather than a pass or a failure. The
    check could not be made, which is neither of those, and saying so is the
    same distinction `findings.py` keeps between `unresolved` and
    `inconclusive`.
    """
    table = ((artifact.get('target_table') or {}).get('series') or {})
    checks = []

    # The size floor, and the only one an MRT run has. `received` and
    # `exported_to_monitor` are the two ends of one link: they agree whenever
    # the link works, so a target that imported a tenth of the RIB would show
    # them agreeing at a tenth and pass a consistency test alone. The target's
    # own count of what it accepted from its peers is what bounds the size, and
    # it is checked against what the generators say they offered -- both
    # measured, neither guessed.
    #
    # Reaching the check-point is *sufficient* and was never the problem: a
    # daemon that exports more than `0.99 * -p` has demonstrably not shrunk the
    # table, and those rows are judged exactly as they always were. What was
    # wrong is treating it as *necessary*, which rejected every FRR row for
    # exporting a smaller share of one RIB than a number nobody could have set
    # correctly in advance.
    # `final`, not `peak`: peak says the table was *ever* there, and the export
    # cross-check below compares two ends of one link that agree whenever the
    # link works -- so a target that imported the whole RIB, lost a large share
    # of it and settled with its export matching the monitor would clear both
    # on a stale peak. The convergence tracker's DROP_FRACTION rule fails most
    # such runs outright; this keeps the row-level floor describing the table
    # the row was actually measured on.
    imported_series = table.get('imported_paths') or {}
    imported = imported_series.get('final')
    # Withheld on the last samples is the same fault as withheld on all of
    # them, and the floor has no other bound: a mid-delivery reading compared
    # against the whole offered count reports the target as having lost routes
    # it was still being sent.
    imported_truncated_s = _series_truncated_s(artifact, imported_series)
    if imported is not None and imported_truncated_s is not None \
            and imported_truncated_s > STALE_WITNESS_S:
        imported = None
        imported_withheld_late = True
    else:
        imported_withheld_late = False
    offered = (artifact.get('tester_fleet') or {}).get('offered_prefixes')
    if filtered:
        # `imported_paths` is post-import-policy for both daemons that publish
        # it -- FRR's `pfxRcd`, BIRD's `imported` -- so a filtered run is
        # *designed* to accept far less than the fleet offered, and it sits
        # below the check-point for the same reason. Failing it here would
        # assert route loss about a policy doing its job, which is the mistake
        # the whole MRT branch exists to stop, reintroduced one layer down.
        # `benchmarks/2026-filters.yaml` pairs bgpdump2 with policy cells, so
        # this combination is real rather than hypothetical.
        # `imported_paths` is post-policy, so nothing here bounds the table's
        # size -- and the export cross-check below compares two ends of one
        # link and agrees at any size. A row that lost 90% of the RIB for a
        # reason unrelated to the policy would be indistinguishable from one
        # the policy trimmed as configured. The unfiltered path rejects
        # "below the check-point and no import gauge ... because nothing
        # vouches for it"; this is the same row with the same evidence, and
        # the campaign's acceptance rule asks for final route state to be
        # *correct*, not merely unchallenged.
        checks.append(Check(
            'route_counts', FAIL,
            'received {0} under policy {1}: post-policy counts are not '
            'comparable with the {2} check-point or the offered count, so '
            'nothing bounds what the target should have kept'.format(
                received, (row_filters or '?'), required)))
    elif required is not None and received >= required:
        checks.append(Check(
            'route_counts', OK,
            'received {0}, at or above the {1} check-point'.format(
                received, required)))
    elif imported is not None and offered:
        shortfall = (offered - imported) / float(offered)
        if shortfall > WITNESS_AGREEMENT_FRACTION:
            checks.append(Check(
                'route_counts', FAIL,
                'the target accepted {0} paths of the {1} its generators '
                'offered, {2:.2%} short'.format(imported, offered, shortfall)))
        else:
            checks.append(Check(
                'route_counts', OK,
                'the target accepted {0} paths of the {1} offered'.format(
                    imported, offered)))
    else:
        # Below the check-point with nothing to bound the size, which is a row
        # nothing can vouch for: the export cross-check below compares the two
        # ends of one link and agrees whenever the link works, so it would pass
        # a 33% route loss on its own. Rejected, which is what the absolute did
        # before this branch existed -- "judged exactly as they always were"
        # has to hold for the shortfall case too, not only for rows that clear
        # the check-point.
        #
        # The two ways of getting here are named apart, because they send the
        # reader to opposite sides of the run. A missing import gauge is a
        # property of the target; a missing offered count is a property of the
        # generators -- `tester_fleet.offered_prefixes` is absent for an MRT
        # injector that does not set `REPORTS_OFFERING` (gobgp,
        # exabgp_mrtparse) and is withheld entirely by `tester_fleet_metrics()`
        # when one injector never completed. Blaming the target for a gauge it
        # does publish is the wrong half of the run to go and look at.
        if offered == 0:
            # Absent and zero are different findings everywhere else in this
            # project, and they send the reader to different places: nothing
            # published against a generator that demonstrably sent nothing.
            checks.append(Check(
                'route_counts', FAIL,
                'received {0} against a {1} check-point, and the generators '
                'report offering nothing at all'.format(received, required)))
        elif not offered:
            checks.append(Check(
                'route_counts', FAIL,
                'received {0} against a {1} check-point, and the generators '
                'report no offered count to measure the shortfall '
                'against'.format(received, required)))
        elif imported_withheld_late:
            checks.append(Check(
                'route_counts', FAIL,
                'received {0} against a {1} check-point, and this target\'s '
                'import gauge stopped reporting {2:.1f}s before the monitor '
                'did, so nothing says what it was holding at the end'.format(
                    received, required, imported_truncated_s)))
        elif (artifact.get('target_table') or {}).get('unmeasured_reason'):
            # The section says why itself -- the poll thread died, or never
            # landed a sample -- and that is the target's *instrument*, not a
            # peering that failed to report. Blaming the peers here would name
            # the nearest rule rather than the fault, with the correct reason
            # sitting unread in the same document.
            checks.append(Check(
                'route_counts', FAIL,
                'received {0} against a {1} check-point, and the target table '
                'was not measured: {2}'.format(
                    received, required,
                    artifact['target_table']['unmeasured_reason'])))
        elif artifact.get('target_table'):
            # A run with no witness gets no `target_table` section at all, so
            # the section's presence is what says the daemon has a gauge --
            # `table` above is the *series*, which is empty in exactly the case
            # being distinguished here.
            #
            # The daemon has the gauge and every sample withheld it, which
            # `table_witness()` does on any poll where a configured peering was
            # not reporting -- a tester or receiver session that never came up.
            # Blaming the target for lacking a capability it has sends the
            # reader to the wrong half of the run, which the refusal rule
            # elsewhere in this project is explicit about.
            checks.append(Check(
                'route_counts', FAIL,
                'received {0} against a {1} check-point, and this target\'s '
                'import gauge was withheld on every sample -- either a peering '
                'was not reporting or the daemon\'s CLI never parsed'.format(
                    received, required)))
        else:
            checks.append(Check(
                'route_counts', FAIL,
                'received {0} against a {1} check-point, and this target '
                'publishes no import gauge to say whether the table was ever '
                'there'.format(received, required)))

    series = table.get('exported_to_monitor') or {}
    exported = series.get('final')
    # `max_witness_age_s` exists so a frozen series is not read as a steady
    # table, and the same applies one step later: the target's witness is
    # resampled onto the monitor's polls, so a target sampler that stalls late
    # in a run leaves `final` at an old value while the monitor's count climbs
    # past it. Comparing those publishes a dead instrument as route loss --
    # and `check_instrument()` only downgrades a target-sampler failure to a
    # NOTE, so nothing else would contradict it. A stale witness cross-checks
    # nothing, which is the rule this function already applies to a missing
    # one.
    # The age of the *last* reading, not the whole run's maximum. `final` is
    # what is being compared, so its freshness is what matters -- and one
    # transient slow target poll anywhere in a run (a `vtysh` call blocking on
    # a busy bgpd during a 1.05M-prefix injection is the realistic case, on the
    # exact daemon and workload this was written for) would otherwise push the
    # run-wide maximum past the bound and mute the row's only consistency check
    # while `final` was perfectly fresh.
    truncated_s = _series_truncated_s(artifact, series)
    if exported is not None and truncated_s is not None \
            and truncated_s > STALE_WITNESS_S:
        return checks + [Check(
            'route_counts', NOTE,
            'received {0}; the target\'s export series ends {1:.1f}s before '
            'the monitor\'s, so the two were not measured over the same '
            'window'.format(received, truncated_s))]
    stale_s = _final_witness_age_s(artifact, series)
    if exported is not None and stale_s is not None \
            and stale_s > STALE_WITNESS_S:
        return checks + [Check(
            'route_counts', NOTE,
            'received {0}; the target\'s export witness went {1:.1f}s without '
            'being re-read, so the two ends of the monitor session could not '
            'be compared'.format(received, stale_s))]
    if exported is None:
        return checks + [Check('route_counts', NOTE,
                      'received {0}; this target publishes no export witness, '
                      'so the two ends of the monitor session could not be '
                      'cross-checked (check-point was {1})'.format(
                          received, required))]
    if not received or not exported:
        # Two zeros agree arithmetically and attest to nothing -- the session
        # every published timing is read from was simply not carrying the
        # table. Churn's "a collapsed count is not a withdrawal", one more
        # side over.
        return checks + [Check('route_counts', FAIL,
                      'received {0} against the target\'s own export count '
                      '{1}: a zero on either end is an absent session, not '
                      'agreement'.format(received, exported))]
    drift = abs(received - exported) / float(exported)
    if drift > WITNESS_AGREEMENT_FRACTION:
        return checks + [Check('route_counts', FAIL,
                      'received {0} but the target says it sent {1} on that '
                      'session, a {2:.2%} disagreement'.format(
                          received, exported, drift))]
    return checks + [Check('route_counts', OK,
                  'received {0} and the target says it sent {1} on that '
                  'session ({2:.3%} apart); the MRT check-point was {3}'.format(
                      received, exported, drift, required))]


def check_events(artifact):
    events = artifact.get('events') or []
    if not events:
        return [Check('event_stream', FAIL, 'no events recorded')]
    checks = []
    out_of_order = []
    previous = None
    for event in events:
        t = event.get('monotonic_s')
        if t is None:
            out_of_order.append('{0} has no timestamp'.format(
                event.get('event')))
            continue
        if previous is not None and t < previous:
            out_of_order.append('{0} at {1:.6f} follows {2:.6f}'.format(
                event.get('event'), t, previous))
        previous = t
    if out_of_order:
        checks.append(Check('event_order', FAIL, '; '.join(out_of_order)))
    else:
        checks.append(Check('event_order', OK,
                            '{0} events, non-decreasing'.format(len(events))))

    seen = set(e.get('event') for e in events)
    missing = [name for name in REQUIRED_EVENTS if name not in seen]
    if missing:
        checks.append(Check('event_coverage', FAIL,
                            'no ' + ', '.join(missing)))
    else:
        checks.append(Check('event_coverage', OK,
                            'every required event present'))
    return checks


def check_testers(artifact):
    fleet = artifact.get('tester_fleet')
    if not fleet:
        return [Check('tester_evidence', FAIL,
                      'no tester_fleet section: no generator reported itself')]
    checks = []
    total = fleet.get('testers')
    complete = fleet.get('testers_complete')
    incomplete = fleet.get('incomplete_testers') or []
    if not total:
        checks.append(Check('tester_evidence', FAIL,
                            'the fleet reports no generators'))
    elif complete != total or incomplete:
        checks.append(Check('tester_evidence', FAIL,
                            '{0} of {1} generators reported completion; '
                            'incomplete: {2}'.format(
                                complete, total,
                                ', '.join(incomplete) or 'unnamed')))
    else:
        checks.append(Check('tester_evidence', OK,
                            '{0} of {1} generators complete, {2} prefixes '
                            'offered'.format(complete, total,
                                             fleet.get('offered_prefixes'))))

    # A synthetic run is the one case where the campaign knows what the fleet
    # should have offered: bgperf2 generated the prefix lists.  An MRT
    # injector replays whatever that peer's table holds, so its offered count
    # is evidence rather than a target, and comparing it against the
    # configured number would reject every full-internet row.
    run = artifact.get('run') or {}
    if run.get('tester_type') in SYNTHETIC_TESTER_TYPES:
        peers = run.get('peers')
        per_peer = run.get('prefixes_per_peer')
        offered = fleet.get('offered_prefixes')
        if peers and per_peer and offered is not None:
            # `n * p`, and never scaled by --path-diversity. Diversity changes
            # which prefixes the peers announce, not how many each announces:
            # `gen_conf()` gives every neighbour `p` paths and only the
            # monitor's check-point is divided into groups. Multiplying here
            # rejected every correct diversity row -- which is the whole of
            # Block 8's synthetic screen.
            expected = peers * per_peer
            if offered != expected:
                checks.append(Check('offered_count', FAIL,
                                    'the fleet offered {0} of a configured '
                                    '{1}'.format(offered, expected)))
            else:
                checks.append(Check('offered_count', OK,
                                    'offered the configured {0}'.format(
                                        expected)))
    return checks


def describe_tester_health(health, errors, timeouts):
    '''What the counts were, and -- when the run captured them -- what they said.

    A rejection whose detail is only a number sends the reader to logs that no
    longer exist: `bench()` rmtree's the work directory at the start of the
    next cell, so by review time the lines behind the count are gone. Block 4
    of the 64 GB timing campaign rejected two rows that way, both of which had
    converged on the full table, and neither could be diagnosed or usefully
    re-measured.

    A run with no capture is described exactly as it was before, and says that
    there is nothing to quote rather than implying the run had nothing to say.

    It does **not** say why. Reaching here at all means the count was nonzero,
    and a nonzero count with no file has two causes this cannot tell apart: a
    run from a build before the capture existed, and a writer that failed (a
    full disk during a campaign block is the realistic one). This text lands in
    `evidence/<label>.json` and `.txt`, which is the durable per-row record a
    later session reads, so naming one of them would record a run whose
    evidence was *lost* as a run from an older build. (Not in the `RAN` /
    `COMPLETE` markers: those carry `evidence: N check(s) failed` and
    `block_exclusion_report()`'s `excluded_row:` lines, and no check detail.)

    (`-r/--repeat` is not a third cause. It builds no tester objects, so
    nothing is scanned *and* nothing is counted: the row reports zero and
    `check_host()` never calls this at all. It matters on the writer side,
    where a clean row must still remove an earlier run's file, and that is
    where `write_tester_health_artifact()` accounts for it.)
    '''
    detail = '{0} tester errors, {1} timeouts'.format(errors, timeouts)
    if not isinstance(health, dict):
        return detail + '; no captured lines available'
    # Shape-tolerant, because this reads a file off disk and the module
    # degrades per run everywhere else: `load_json` swallows a parse error and
    # an unreadable artifact becomes one `unreadable` verdict. An exception
    # here escapes `main()` and costs every *other* run in the block its
    # verdict -- one malformed document taking down thirteen good ones.
    # The quoted line and the number beside it must come from the same list.
    # Summing the two and quoting the first error gives "first of 20 captured"
    # for a run with one error and nineteen timeouts, which reads as twenty
    # captures backing the one line shown.
    for key, kind in (('error_samples', 'error'),
                      ('timeout_samples', 'timeout')):
        value = health.get(key)
        if not isinstance(value, list):
            continue
        found = [s for s in value if isinstance(s, dict)]
        if found:
            break
    else:
        found = []
    if not found:
        return detail + '; capture present but empty'
    first = found[0]
    text = str(first.get('text', '')).strip()
    # The writer trims at base.ERROR_SAMPLE_LINE_CHARS and says so; dropping
    # that flag here would render a cut line as a complete one, and by review
    # time this text *is* the evidence -- the log it came from is gone.
    if text and first.get('truncated'):
        text += ' [trimmed]'
    if not text:
        # Reachable: the MRT and bgpdump2 needles are bare substrings, so a
        # blank line can match. Saying so beats a dangling "a.log:1: ", which
        # reads as a formatting fault rather than as what was matched.
        text = '(blank line)'
    # `source` names the tester the log belongs to, which is the half a bare
    # filename cannot supply: every MRT injector writes `bgpdump2.log`.
    where = '/'.join(str(first[k]) for k in ('source', 'log') if first.get(k))
    shown = '{0}:{1}: {2}'.format(where, first.get('line'), text)
    # The count is the authority on how many there were; the capture is bounded
    # per list (base.ERROR_SAMPLE_LIMIT), so say how many of *that kind* are
    # quotable rather than letting the first line stand for all of them.
    return '{0}; first of {1} captured {2} line(s): {3}'.format(
        detail, len(found), kind, shown)


def check_host(artifact, row, health=None):
    '''Contention and memory, from the row and from the run's own findings.

    The findings are the run's verdict on itself and are read rather than
    recomputed; the row is what the campaign's stricter guardrail is applied
    to.  Both are reported, because a row that passes the campaign guardrail
    while carrying a `low_free_memory` finding is a row whose *timings* were
    withheld for a reason the guardrail does not cover.
    '''
    checks = []
    fired = set()
    findings = (artifact.get('findings') or {}).get('findings') or []
    for finding in findings:
        fired.add(finding.get('finding'))

    if row is None or row.get('__short_row__'):
        checks.append(Check('host_evidence', FAIL,
                            'no usable CSV row to read host columns from'))
        return checks

    errors = _row_int(row, 'tester errors')
    timeouts = _row_int(row, 'tester timeouts')
    if errors is None or timeouts is None:
        checks.append(Check('tester_health', FAIL,
                            'row does not carry tester errors/timeouts'))
    elif errors or timeouts:
        checks.append(Check('tester_health', FAIL,
                            describe_tester_health(health, errors, timeouts)))
    else:
        checks.append(Check('tester_health', OK, 'no errors, no timeouts'))

    foreign = _row_float(row, 'max foreign cpu %')
    if foreign is None:
        checks.append(Check('contention', FAIL,
                            'row does not carry max foreign cpu %'))
    elif foreign >= CONTENTION_PERCENT or 'foreign_cpu_contention' in fired:
        checks.append(Check('contention', FAIL,
                            'processes outside the benchmark used up to '
                            '{0:.1f} cores'.format(foreign / 100.0)))
    else:
        checks.append(Check('contention', OK,
                            'peak foreign CPU {0:.0f}%'.format(foreign)))

    free = _row_float(row, 'min free mem (GB)')
    total = _row_float(row, 'Mem (GB)')
    if free is None or not total:
        checks.append(Check('memory_guardrail', FAIL,
                            'row does not carry both free and total memory'))
    elif free > total:
        # `min_free` starts above every real value so the first sample can only
        # lower it, and `free` raising kills that sampler thread while the run
        # goes on -- so an untouched sentinel reaches the row as ~931,322 GB and
        # clears any guardrail there is. `findings.py` maps it back to None and
        # `summary.py` withholds the column; a checker that divided it by the
        # host's memory would qualify, for the campaign's comparisons, the one
        # row with no host-memory evidence at all.
        checks.append(Check('memory_guardrail', FAIL,
                            'min free mem reads {0:.1f} GB against a host of '
                            '{1:.1f} GB: the memory sampler never lowered its '
                            'sentinel, so this run has no free-memory '
                            'evidence'.format(free, total)))
    else:
        share = free / total
        detail = 'min free {0:.1f} GB of {1:.1f} GB ({2:.0f}%)'.format(
            free, total, share * 100.0)
        if share < CAMPAIGN_FREE_MEMORY_FRACTION:
            checks.append(Check('memory_guardrail', FAIL, detail
                                + ', below the campaign guardrail of {0:.0f}%'
                                .format(CAMPAIGN_FREE_MEMORY_FRACTION * 100)))
        else:
            checks.append(Check('memory_guardrail', OK, detail))
    if 'low_free_memory' in fired:
        checks.append(Check('memory_finding', NOTE,
                            "the run's own findings include low_free_memory"))
    if 'host_cpu_saturated' in fired:
        checks.append(Check('host_cpu', NOTE,
                            "the run's own findings include host_cpu_saturated"))
    return checks


def check_findings(artifact):
    findings = artifact.get('findings')
    if not findings:
        return [Check('findings', FAIL, 'no findings section')]
    component = findings.get('limiting_component')
    if component not in LIMITING_COMPONENTS:
        return [Check('findings', FAIL,
                      'limiting_component is {0!r}'.format(component))]
    # `unresolved` and `inconclusive` are answers, not failures: the campaign
    # requires the policy to assign a component *or explicitly leave it
    # unresolved*, and collapsing the two would hide which one an operator can
    # act on.
    return [Check('findings', OK, '{0} ({1})'.format(
        component, findings.get('decided_by') or 'no deciding finding'))]


def _generator_egress_mbit(artifact):
    '''Each generator's own wire-side rate, from its own two published numbers.

    `octets_on_wire` is counted on a successful `write()` and
    `reported_injection_s` is the generator's own measurement of its send, so
    the quotient is the rate that generator achieved. bgperf2 publishes no
    such rate and knows nothing about a constraint applied from outside it, so
    this is not a second implementation of one of its measurements -- it is
    the only thing in the artifact that can be compared against a cap the tool
    was never told about.
    '''
    rates = {}
    for name, section in (artifact.get('testers') or {}).items():
        octets = (section or {}).get('octets_on_wire')
        seconds = (section or {}).get('reported_injection_s')
        # `not seconds` and not `seconds is None`: a generator whose own send
        # came back 0.0 resolves no rate at all, and dividing by it raises in
        # the middle of qualifying a block.
        if octets is None or not seconds:
            continue
        rates[name] = octets * 8.0 / 1e6 / seconds
    return rates


def check_calibration(artifact, expect_limiting, expect_mbit, tolerance):
    '''The extra conditions a *calibration* case has to meet.

    A calibration case is a run whose bottleneck was chosen in advance by
    starving one role from outside bgperf2, so that the findings policy can be
    checked against a known cause. Two things are asked of one, and they are
    separate on purpose:

    - the policy must name the component the constraint was built to produce,
      or explicitly decline to name one where nothing was constrained;
    - the constraint must be recoverable from the run's own numbers.

    The second is not decoration. A cap that bound nothing has happened here
    and reported itself as applied (`tc` succeeded on a device the session did
    not use), and at a size where the unconstrained shape is already
    generator-bound the verdict alone would have cleared it.
    '''
    checks = []
    if expect_limiting:
        component = (artifact.get('findings') or {}).get('limiting_component')
        wanted = ' or '.join(expect_limiting)
        if component in expect_limiting:
            checks.append(Check('expected_limiting', OK,
                                'limiting_component is {0}, as this case was '
                                'built to produce'.format(component)))
        else:
            checks.append(Check('expected_limiting', FAIL,
                                'limiting_component is {0!r}; this case was '
                                'built to produce {1}'.format(component,
                                                              wanted)))

    generators = sorted((artifact.get('testers') or {}).keys())
    rates = _generator_egress_mbit(artifact)
    described = '; '.join('{0} {1:.2f} mbit'.format(name, rates[name])
                          for name in sorted(rates))
    if expect_mbit is None:
        # Always published, never asserted, when no cap was imposed: the
        # unconstrained companion's rate is what the constrained one is read
        # against, and a number nobody recorded cannot play that part later.
        if rates:
            checks.append(Check('generator_egress', NOTE, described))
        return checks

    if not generators:
        checks.append(Check('generator_egress', FAIL,
                            'no generator section at all, so an imposed rate '
                            'cannot be recovered from this run'))
        return checks

    # Every generator, not every generator that happened to answer. Both
    # numbers are withheld rather than guessed -- `octets_on_wire` unless every
    # session in the container reported a written count, `reported_injection_s`
    # for a multi-RIB session -- and a generator dropped for want of one is a
    # generator this case has no evidence about. Cleared on the ones that did
    # answer, the case would be qualified while an injector ran unshaped at
    # 65 mbit: `calibration_case.sh` counts constrained containers rather than
    # successes for that reason, and this is the same rule on the reading side.
    silent = [name for name in generators if name not in rates]
    off = sorted(name for name, rate in rates.items()
                 if abs(rate - expect_mbit) > tolerance * expect_mbit)
    detail = '{0} against an imposed {1:.2f} mbit'.format(
        described or 'no generator published a recoverable rate', expect_mbit)
    faults = []
    if off:
        faults.append('outside +/-{0:.0f}%: {1}'.format(tolerance * 100,
                                                        ', '.join(off)))
    if silent:
        faults.append('published no recoverable rate: ' + ', '.join(silent))
    if faults:
        checks.append(Check('generator_egress', FAIL,
                            '{0}; {1}'.format(detail, '; '.join(faults))))
    else:
        checks.append(Check('generator_egress', OK,
                            '{0} (within +/-{1:.0f}%, all {2} generators)'
                            .format(detail, tolerance * 100, len(generators))))
    return checks


def check_instrument(artifact):
    """Did the run's own instruments read cleanly?

    `bench()` publishes an `instrument` section only when a sampler failed a
    read, and both samplers read `gobgp neighbor -j` -- whose errors come back
    JSON-encoded and used to kill the reading thread outright. They survive one
    now, which is what keeps a run alive; it is not what makes the run
    comparable.

    The monitor is the instrument every published timing is derived from, so a
    gap in its 1-second series is a gap under `elapsed (s)`, `first_prefix_s`
    and `convergence_s` alike: that is a FAIL, not a note. A target-side gap is
    a NOTE -- it costs the neighbour checkpoint, which moves the assurance
    window from 5 samples to 20 and lengthens the run without corrupting the
    timings the row publishes.

    A run with no section read cleanly, which is what every run before this
    section existed also looks like. That is deliberate: absent means "no
    failures recorded", and an older artifact cannot be told from a clean one,
    so this may not manufacture a failure from silence.
    """
    instrument = artifact.get('instrument')
    if not instrument:
        return [Check('instrument_reads', OK,
                      'no sampler read failures recorded')]
    checks = []
    monitor = instrument.get('monitor') or {}
    if monitor.get('failed_reads'):
        checks.append(Check(
            'instrument_reads', FAIL,
            'the monitor failed {0} read(s) ({1}); every published timing is '
            'derived from that series'.format(
                monitor['failed_reads'], monitor.get('last_error'))))
    target = instrument.get('target_neighbor_sampler') or {}
    if target.get('failed_reads'):
        checks.append(Check(
            'instrument_reads', NOTE,
            "the target's neighbour sampler failed {0} read(s) ({1}); the "
            'neighbour checkpoint may have been reached late'.format(
                target['failed_reads'], target.get('last_error'))))
    if not checks:
        checks.append(Check('instrument_reads', OK,
                            'no sampler read failures recorded'))
    return checks


def qualify(artifact, versions, row, expect_limiting=None,
            expect_mbit=None, tolerance=DEFAULT_EGRESS_TOLERANCE,
            health=None):
    checks = []
    checks.extend(check_provenance(artifact, versions))
    checks.extend(check_status(artifact, row))
    checks.extend(check_events(artifact))
    checks.extend(check_testers(artifact))
    checks.extend(check_host(artifact, row, health))
    checks.extend(check_findings(artifact))
    checks.extend(check_instrument(artifact))
    checks.extend(check_calibration(artifact, expect_limiting, expect_mbit,
                                    tolerance))
    verdict = 'rejected' if any(c.status == FAIL for c in checks) else 'qualified'
    return verdict, checks


def load_json(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Qualify a block\'s runs against the campaign acceptance '
                    'rules.')
    parser.add_argument('results_dir',
                        help='directory holding <run>.events.json and the '
                             'batch CSV')
    parser.add_argument('--json', dest='json_out',
                        help='write the machine-readable verdicts here')
    parser.add_argument('--expect', type=int, default=None,
                        help='how many runs this block should have produced; '
                             'a shortfall is a failure, since a run that '
                             'never happened looks exactly like one nobody '
                             'looked for')
    parser.add_argument('--expect-limiting', default=None,
                        help='for a calibration case: the limiting component '
                             'this run was built to produce, or a '
                             'comma-separated set of acceptable ones. An '
                             'unconstrained control takes '
                             '"unresolved,inconclusive" -- the two ways of '
                             'declining to name a component, which are kept '
                             'apart everywhere else and are both correct here')
    parser.add_argument('--expect-egress-mbit', type=float, default=None,
                        help='for a calibration case whose generators were '
                             'rate-capped from outside bgperf2: the cap, in '
                             'mbit/s. Every generator that published an octet '
                             'count and its own send duration must recover it')
    parser.add_argument('--egress-tolerance', type=float,
                        default=DEFAULT_EGRESS_TOLERANCE,
                        help='fraction of the imposed rate a generator may be '
                             'off by (default {0}); see '
                             'DEFAULT_EGRESS_TOLERANCE'.format(
                                 DEFAULT_EGRESS_TOLERANCE))
    args = parser.parse_args(argv)

    expect_limiting = None
    if args.expect_limiting:
        expect_limiting = [c.strip() for c in args.expect_limiting.split(',')
                           if c.strip()]
        if not expect_limiting:
            # Separators alone, or an empty value from shell quoting. Left
            # alone it is falsy, so the verdict check is skipped and the
            # calibration case is qualified with nothing asserted -- which the
            # typo guard below cannot catch, since there is nothing to reject.
            parser.error('--expect-limiting names no component')
        unknown = [c for c in expect_limiting if c not in LIMITING_COMPONENTS]
        if unknown:
            # A typo here would silently expect a component nothing can
            # produce, and every calibration case would fail for a reason that
            # has nothing to do with the run.
            parser.error('unknown limiting component(s): '
                         + ', '.join(unknown))

    rows = {}
    for entry in sorted(os.listdir(args.results_dir)):
        if entry.endswith('.csv'):
            rows.update(load_rows(os.path.join(args.results_dir, entry)))

    artifacts = sorted(e for e in os.listdir(args.results_dir)
                       if e.endswith('.events.json'))
    results = []
    for entry in artifacts:
        path = os.path.join(args.results_dir, entry)
        artifact = load_json(path)
        if artifact is None:
            results.append({'artifact': entry, 'verdict': 'unreadable',
                            'checks': []})
            continue
        stem = path[:-len('.events.json')]
        versions = load_json(stem + '.versions.json')
        # Written only when a count is nonzero, and by builds from 2026-09-11
        # onward. None covers both, and the detail says which.
        health = load_json(stem + '.tester-health.json')
        name = row_name_for(artifact)
        verdict, checks = qualify(artifact, versions, rows.get(name),
                                  expect_limiting, args.expect_egress_mbit,
                                  args.egress_tolerance, health)
        results.append({'artifact': entry, 'run': name, 'verdict': verdict,
                        'checks': [c.as_dict() for c in checks]})

    for result in results:
        print('{0}: {1}'.format(result.get('run') or result['artifact'],
                                result['verdict'].upper()))
        for check in result['checks']:
            print('  [{0:>4}] {1}: {2}'.format(check['status'], check['check'],
                                               check['detail']))

    qualified = sum(1 for r in results if r['verdict'] == 'qualified')
    print('\n{0} of {1} runs qualified'.format(qualified, len(results)))

    shortfall = None
    if args.expect is not None and len(results) != args.expect:
        shortfall = '{0} runs found, {1} expected'.format(len(results),
                                                          args.expect)
        print('shortfall: ' + shortfall)

    if args.json_out:
        with open(args.json_out, 'w', encoding='utf-8') as f:
            json.dump({'results_dir': args.results_dir,
                       'expected_runs': args.expect,
                       'expected_limiting': expect_limiting,
                       'expected_egress_mbit': args.expect_egress_mbit,
                       'egress_tolerance': args.egress_tolerance,
                       'shortfall': shortfall,
                       'qualified': qualified,
                       'runs': results}, f, indent=2, sort_keys=True,
                      allow_nan=False)
            f.write('\n')

    if shortfall or qualified != len(results) or not results:
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
