#!/usr/bin/env python3
"""Summarise one finished 2026 daemon comparison step for its plan record.

    venv/bin/python scripts/comparison_step_table.py results/2026/2026-comparison/rrc00-n38

Prints, per test in the directory: the per-cell table the plan's step records
carry (passes, median, received, peak target memory, floor of free memory,
limiting component), and then every row that needs a decision before the step
can be recorded -- not converged, `tester_incomplete`, decided on one witness,
tester errors, or free memory under the guardrail.

It reads and prints; it decides nothing. A row it lists is not thereby
excluded: the plan's rules, and the operator, say what a listed row means.
That is also why it prints every pass rather than only a median, and why a
figure it could not find is printed as `?` rather than left out.

The stats row is read by column name, never by position, for the reason
`docs/invariants/batch-passes.md` gives `summary.py`: the row has shifted
before. Standard library only, so it runs with any python3 on the host.
"""

import argparse
import collections
import csv
import glob
import json
import os
import re
import sys

# `batch_run_label()` adds ` #N` only when a test runs more than one pass.
ROW_SUFFIX = re.compile(r'^(?P<cell>.+?)(?: #(?P<pass>\d+))?$')
# bgperf2's unsampled sentinels (`unsampled_row_values()`): min free starts
# above any real host, and a peak under 0.5 MB is a sampler that never read.
MIN_REAL_MAX_MEM_GB = 0.0005


def read_rows(path):
    with open(path, newline='') as f:
        reader = csv.reader(f)
        header = [h.strip() for h in next(reader)]
        return [dict(zip(header, (v.strip() for v in row))) for row in reader if row]


def number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fmt(value, digits=2):
    if value is None:
        return '?'
    if float(value).is_integer() and digits == 0:
        return '{:,}'.format(int(value))
    return '{:,.{}f}'.format(value, digits)


def span(values, digits=0):
    known = sorted(v for v in values if v is not None)
    if not known:
        return '?'
    if known[0] == known[-1]:
        return fmt(known[0], digits)
    return '{}–{}'.format(fmt(known[0], digits), fmt(known[-1], digits))


def summary_medians(path):
    """Cell label -> median elapsed, from the batch's own summary."""
    medians = {}
    if not os.path.exists(path):
        return medians
    with open(path) as f:
        document = json.load(f)
    for cell in document.get('cells', []):
        target = cell.get('identity', {}).get('target', {})
        label = target.get('label') or ' '.join(
            str(x) for x in (target.get('name'), target.get('version')) if x)
        elapsed = cell.get('metrics', {}).get('elapsed (s)', {})
        medians[label] = (elapsed.get('median'), elapsed.get('n'))
    return medians


def pin_text(pin):
    """`target=0-7,monitor=8-9` and `{'target': '0-7', ...}` as one string."""
    if not pin:
        return ''
    if isinstance(pin, str):
        # As bgperf2's pin_cpusets(): a token with no `=` continues the
        # previous role's cpuset (`target=0-3,8-11`).
        sets, role = {}, None
        for token in pin.split(','):
            name, sep, cpus = token.partition('=')
            if sep:
                role = name
                sets[role] = cpus
            elif role is not None:
                sets[role] += ',' + token
        pin = sets
    return ','.join('{}={}'.format(k, pin[k]) for k in sorted(pin))


def run_key(name, tester_type, peers, prefixes, filter_test, monitor, pin):
    # Every axis two tests of one config have been seen to differ by. The name
    # alone collides across tests; so did name+generator+size until the
    # `cores` tests, which differ only in pin.
    return (name, str(tester_type or 'bird'), int(peers), int(prefixes),
            str(filter_test), str(monitor), pin_text(pin))


def load_events(directory):
    """Every events.json, keyed by the run's name *and* its axes.

    The name alone is not identity: a config with several tests reuses its
    cell names in each, and their events files sit in one directory.
    """
    found = {}
    for path in glob.glob(os.path.join(directory, '*.events.json')):
        try:
            with open(path) as f:
                document = json.load(f)
            run = document['run']
            key = run_key(run['name'], run.get('tester_type'), run['peers'],
                          run['prefixes_per_peer'], run.get('filter_test'),
                          run.get('monitor'), run.get('pin'))
        except (OSError, ValueError, KeyError, TypeError) as e:
            print('unreadable events file {}: {}'.format(path, e), file=sys.stderr)
            continue
        if key in found:
            # Never let the last file read win silently.
            print('two events files share one identity, neither used: {} and {}'.format(
                found[key][0], path), file=sys.stderr)
            found[key] = (None, None)
            continue
        found[key] = (path, document)
    return found


def test_keys(progress_path):
    """Row name -> events key, for the rows this test's progress records."""
    keys = {}
    if not os.path.exists(progress_path):
        return keys
    with open(progress_path) as f:
        document = json.load(f)
    # Each key is the cell's identity as JSON; each value is its stats row.
    for cell_id, row in document.get('cells', {}).items():
        try:
            identity = json.loads(cell_id)
        except ValueError:
            continue
        if not row:
            continue
        target = identity.get('target', {})
        filter_test = identity.get('filter')
        keys[row[0]] = run_key(row[0], target.get('tester_type'), identity.get('neighbors'),
                               identity.get('prefixes'),
                               None if filter_test in (None, 'None') else filter_test,
                               # batch_cell_id() leaves the monitor out when it is
                               # gobgp, the unmarked default; events.json names it.
                               identity.get('monitor') or 'gobgp', identity.get('pin'))
    return keys


def health_samples(events_path):
    path = events_path.replace('.events.json', '.tester-health.json')
    if not os.path.exists(path):
        return []
    with open(path) as f:
        document = json.load(f)
    return ['{} {}'.format(s.get('source'), s.get('text'))
            for s in document.get('error_samples', []) + document.get('timeout_samples', [])]


def summarise(csv_path, events, guardrail):
    test = os.path.basename(csv_path)[:-len('.csv')]
    rows = read_rows(csv_path)
    medians = summary_medians(csv_path[:-len('.csv')] + '.summary.json')
    keys = test_keys(csv_path[:-len('.csv')] + '.progress.json')
    cells = collections.OrderedDict()
    notes = []
    host_mem = None
    for row in rows:
        m = ROW_SUFFIX.match(row.get('name', ''))
        cells.setdefault(m.group('cell'), []).append((int(m.group('pass') or 1), row))
        host_mem = host_mem or number(row.get('Mem (GB)', '').rstrip('GB'))

    def row_events(row):
        return events.get(keys.get(row['name']), (None, None))

    def max_mem(row):
        value = number(row.get('max mem (GB)'))
        return None if value is None or value < MIN_REAL_MAX_MEM_GB else value

    def min_free(row):
        value = number(row.get('min free mem (GB)'))
        return None if value is None or (host_mem and value > host_mem) else value

    def extreme(fn, values):
        # One unknown pass makes the cell's extreme unknown: the pass that was
        # not sampled may be the one that held it.
        values = list(values)
        return None if not values or None in values else fn(values)

    print('## {}\n'.format(test))
    print('{} rows in {} cells. Host memory {} GB; {:.0%} guardrail is {} GB.\n'.format(
        len(rows), len(cells), fmt(host_mem), guardrail,
        fmt(host_mem * guardrail if host_mem else None)))
    print('| cell | passes (elapsed s) | median | received | max mem (GB) '
          '| min free mem (GB) | limiting component |')
    print('|---|---|---|---|---|---|---|')
    for cell, passes in cells.items():
        passes.sort()
        limiting = collections.Counter()
        for _, row in passes:
            document = row_events(row)[1] or {}
            limiting[document.get('findings', {}).get('limiting_component', '?')] += 1
        median, n = medians.get(cell, (None, None))
        median_text = fmt(median, 1) if median is not None else '?'
        if n is not None and n != len(passes):
            median_text += ' (summary n={})'.format(n)
        print('| {} | {} | {} | {} | {} | {} | {} |'.format(
            cell,
            ', '.join(row.get('elapsed (s)', '?') for _, row in passes),
            median_text,
            span([number(r.get('received')) for _, r in passes]),
            fmt(extreme(max, (max_mem(r) for _, r in passes))),
            fmt(extreme(min, (min_free(r) for _, r in passes))),
            ', '.join('`{}` ×{}'.format(k, v) if v > 1 else '`{}`'.format(k)
                      for k, v in limiting.most_common())))

    print('\n### Rows that need a decision\n')
    flagged = 0
    for cell, passes in cells.items():
        for _, row in passes:
            reasons = []
            path, document = row_events(row)
            if document is None:
                reasons.append('no events.json found for this row')
            else:
                if document.get('status') != 'converged':
                    reasons.append('status {}'.format(document.get('status')))
                findings = [f.get('finding') for f in
                            document.get('findings', {}).get('findings', [])]
                if 'tester_incomplete' in findings:
                    reasons.append('tester_incomplete')
                incomplete = document.get('tester_fleet', {}).get('incomplete_testers')
                if incomplete:
                    reasons.append('incomplete testers {}'.format(incomplete))
                if 'convergence_rule' in document:
                    reasons.append('decided on one witness (convergence_rule present)')
                for finding in ('low_free_memory', 'foreign_cpu_contention'):
                    if finding in findings:
                        reasons.append(finding)
            if row.get('failed'):
                reasons.append('failed: {}'.format(row.get('failed')))
            errors, timeouts = row.get('tester errors', '0'), row.get('tester timeouts', '0')
            if errors not in ('', '0') or timeouts not in ('', '0'):
                reasons.append('tester errors {}, timeouts {}'.format(errors, timeouts))
                if path:
                    reasons.extend('  ' + s for s in health_samples(path))
            if max_mem(row) is None or min_free(row) is None:
                reasons.append('memory not sampled (max mem {}, min free mem {}): the '
                               'sampler failed, so this row\'s memory is unknown'.format(
                                   row.get('max mem (GB)'), row.get('min free mem (GB)')))
            free = min_free(row)
            if free is not None and host_mem and free < host_mem * guardrail:
                reasons.append('min free mem {} GB, below the {:.0%} guardrail ({:.1%} of the host)'.format(
                    fmt(free), guardrail, free / host_mem))
            if reasons:
                flagged += 1
                print('- **{}**: {}'.format(row['name'], reasons[0]))
                for reason in reasons[1:]:
                    print('  - {}'.format(reason.strip()))
    if not flagged:
        print('None.')

    print('\n### Other readings\n')
    foreign = [(number(r.get('max foreign cpu %')), r['name'])
               for p in cells.values() for _, r in p]
    foreign = [f for f in foreign if f[0] is not None]
    if foreign:
        print('- max foreign cpu %: {} ({})'.format(fmt(max(foreign)[0], 0), max(foreign)[1]))
    kept = collections.Counter()
    for p in cells.values():
        for _, row in p:
            sink = (row_events(row)[1] or {}).get('instrument', {}).get('sink_log') or {}
            if sink.get('last_kept'):
                kept[sink['last_kept']] += 1
    for text, count in kept.most_common():
        print('- sink kept `{}` in {} row(s)'.format(text, count))
    for note in notes:
        print('- {}'.format(note))
    print()


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('results_dir')
    parser.add_argument('--guardrail', type=float, default=0.15,
                        help='free-memory guardrail as a fraction of host memory '
                             '(default 0.15, the plan\'s since 2026-10-05)')
    args = parser.parse_args()
    csvs = sorted(glob.glob(os.path.join(args.results_dir, '*.csv')))
    if not csvs:
        sys.exit('no batch CSV in {}'.format(args.results_dir))
    events = load_events(args.results_dir)
    for path in csvs:
        summarise(path, events, args.guardrail)


if __name__ == '__main__':
    main()
