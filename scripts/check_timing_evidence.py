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


def _row_float(row, column):
    raw = (row.get(column) or '').strip()
    if not raw:
        return None
    # `Mem (GB)` is written as e.g. "61.44GB"; the rest are bare numbers.
    for suffix in ('GB', 'gb'):
        if raw.endswith(suffix):
            raw = raw[:-len(suffix)]
    try:
        return float(raw)
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
    if required is None or received is None:
        checks.append(Check('route_counts', FAIL,
                            'row does not carry both required and received'))
    elif received < required:
        checks.append(Check('route_counts', FAIL,
                            'received {0} is below the required {1}'.format(
                                received, required)))
    else:
        checks.append(Check('route_counts', OK,
                            'received {0} against a required {1}'.format(
                                received, required)))
    return checks


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
    if run.get('tester_type') == 'bird':
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


def check_host(artifact, row):
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
                            '{0} tester errors, {1} timeouts'.format(
                                errors, timeouts)))
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


def qualify(artifact, versions, row):
    checks = []
    checks.extend(check_provenance(artifact, versions))
    checks.extend(check_status(artifact, row))
    checks.extend(check_events(artifact))
    checks.extend(check_testers(artifact))
    checks.extend(check_host(artifact, row))
    checks.extend(check_findings(artifact))
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
    args = parser.parse_args(argv)

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
        versions = load_json(path[:-len('.events.json')] + '.versions.json')
        name = row_name_for(artifact)
        verdict, checks = qualify(artifact, versions, rows.get(name))
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
