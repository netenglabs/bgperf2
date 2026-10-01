#!/usr/bin/env python3
'''Pair each cell's GoBGP-monitor and sink-monitor artifacts, and compare them.

Measurement plan 7a's Docker checks each compare the sink with the GoBGP
monitor on the same cell. A batch with one test per monitor writes
`<stem>.events.json` and `<stem>_mon-sink.events.json` side by side, because
`--monitor sink` appends `mon-sink` to the stem and nothing else. This reads
every events artifact under the directories given, pairs them on that stem, and
for each pair reports:

- each run's status and the count its monitor ended on (check 2: identical);
- what the sink's own log says about the instrument, from `instrument.sink_log`:
  lost sessions (check 3: none), restarts, malformed lines, refused messages,
  the largest gap between two lines, and the clock offset (check 5);
- each receiver's final count, where the run had receivers.

It computes no timing comparison. `convergence_s` is printed beside each pair
for reading, but which monitor is faster is the bridge block's question (7c),
asked over repetitions, and one pass of each cannot answer it.

Exits 0 when every pair passes, 1 when one does not, and 2 when there is
nothing to compare. A cell with only one of the two artifacts is reported
unpaired and fails: a check that skipped half of its cells has not passed.
Two runs that both failed pass if they failed on the same count: that is a
property of the target, and the instruments agreed about it.
'''
import argparse
import glob
import json
import os
import sys

SINK_SUFFIX = '_mon-sink'

# Past this, the sink's monotonic clock is not the host's in any sense the
# controller could rely on. The measured offsets are a few microseconds, and a
# container in its own time namespace is off by its whole offset, which is
# seconds or more.
CLOCK_OFFSET_LIMIT_NS = 1_000_000


def pair_key(path):
    stem = os.path.basename(path)[:-len('.events.json')]
    if stem.endswith(SINK_SUFFIX):
        return stem[:-len(SINK_SUFFIX)], 'sink'
    return stem, None


def final_accepted(doc):
    '''The count the run's monitor ended on, or None where nothing says.

    `convergence_confirmed`'s count when the run converged. A run that did
    not has no such event, and its last monitor *event* can be from the first
    second -- `monitor_first_prefix` -- so it is not used. The last
    `target_table` sample's `monitor_accepted` is: that is the monitor's count
    on the run's final poll. A failed run on a target with no table witness
    has neither, and its count is unknown rather than guessed.
    '''
    confirmed = [e for e in doc.get('events') or []
                 if e.get('event') == 'convergence_confirmed'
                 and 'accepted_prefixes' in (e.get('counters') or {})]
    if confirmed:
        return confirmed[-1]['counters']['accepted_prefixes']
    samples = ((doc.get('target_table') or {}).get('samples')) or []
    for sample in reversed(samples):
        if sample.get('monitor_accepted') is not None:
            return sample['monitor_accepted']
    return None


def receiver_counts(doc):
    sessions = ((doc.get('export') or {}).get('sessions')) or {}
    return {name: (s or {}).get('accepted_prefixes')
            for name, s in sorted(sessions.items())}


def sink_problems(doc):
    '''What the sink's own log says is wrong with the instrument, if anything.'''
    log = ((doc.get('instrument') or {}).get('sink_log'))
    if log is None:
        return ['no instrument.sink_log: the run predates it, or was not a '
                'sink run']
    if 'unreadable' in log:
        return ['the sink log was unreadable: {0}'.format(log['unreadable'])]
    problems = []
    if log.get('sessions_lost'):
        problems.append('{0} session(s) lost'.format(log['sessions_lost']))
    if (log.get('processes') or 0) != 1:
        problems.append('{0} sink processes'.format(log.get('processes')))
    if log.get('malformed_lines'):
        problems.append('{0} malformed line(s)'.format(log['malformed_lines']))
    if log.get('refused_messages'):
        problems.append('{0} refused message(s), last: {1}'.format(
            log['refused_messages'], log.get('last_refused')))
    offset = log.get('clock_offset_ns')
    if offset is None:
        problems.append('no clock offset: the log had no B line')
    elif abs(offset) > CLOCK_OFFSET_LIMIT_NS:
        problems.append('clock offset {0:.3f} ms'.format(offset / 1e6))
    return problems


def compare(gobgp, sink):
    '''The verdict for one pair, as (passed, list of reasons it did not).'''
    reasons = []
    # The two runs must end the same way, not necessarily converged. A target
    # that never reaches the check-point (FRR on the MRT table, which exports
    # ~9% less of it) fails with either instrument, and what this check asks
    # is whether the two instruments failed it on the same count.
    if gobgp.get('status') != sink.get('status'):
        reasons.append('status gobgp {0} vs sink {1}'.format(
            gobgp.get('status'), sink.get('status')))
    g, s = final_accepted(gobgp), final_accepted(sink)
    if g is None or s is None or g != s:
        reasons.append('final count gobgp {0} vs sink {1}'.format(g, s))
    rg, rs = receiver_counts(gobgp), receiver_counts(sink)
    if rg != rs:
        reasons.append('receivers gobgp {0} vs sink {1}'.format(rg, rs))
    reasons.extend('sink: ' + p for p in sink_problems(sink))
    return not reasons, reasons


def load(paths):
    '''{stem: {'gobgp': doc, 'sink': doc}} from every events artifact found.'''
    pairs = {}
    for directory in paths:
        for path in sorted(glob.glob(os.path.join(directory, '**', '*.events.json'),
                                     recursive=True)):
            with open(path) as f:
                doc = json.load(f)
            stem, marked = pair_key(path)
            monitor = (doc.get('run') or {}).get('monitor') or 'gobgp'
            if (marked == 'sink') != (monitor == 'sink'):
                # The stem and the document disagree about the instrument.
                # Trusting either would pair it against the wrong run.
                raise SystemExit('{0}: named for {1} but run.monitor is {2}'.format(
                    path, marked or 'gobgp', monitor))
            pairs.setdefault(stem, {})[monitor] = dict(doc, _path=path)
    return pairs


def describe(doc):
    if doc is None:
        return '-'
    log = (doc.get('instrument') or {}).get('sink_log') or {}
    conv = (doc.get('measurements') or {}).get('convergence_s')
    text = '{0} count={1} convergence_s={2}'.format(
        doc.get('status'), final_accepted(doc),
        None if conv is None else round(conv, 3))
    if log and 'unreadable' not in log:
        gap = log.get('max_line_gap_ns')
        offset = log.get('clock_offset_ns')
        text += ' max_gap_ms={0} offset_us={1}'.format(
            None if gap is None else round(gap / 1e6, 1),
            None if offset is None else round(offset / 1e3, 1))
    return text


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('dirs', nargs='+', help='results directories to read')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)

    pairs = load(args.dirs)
    if not pairs:
        print('no events artifacts found', file=sys.stderr)
        return 2
    report = []
    for stem in sorted(pairs):
        found = pairs[stem]
        if 'gobgp' not in found or 'sink' not in found:
            report.append({'stem': stem, 'passed': False,
                           'reasons': ['unpaired: only {0}'.format(
                               ', '.join(sorted(found)))],
                           'gobgp': describe(found.get('gobgp')),
                           'sink': describe(found.get('sink'))})
            continue
        passed, reasons = compare(found['gobgp'], found['sink'])
        report.append({'stem': stem, 'passed': passed, 'reasons': reasons,
                       'gobgp': describe(found['gobgp']),
                       'sink': describe(found['sink'])})

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for row in report:
            print('{0} {1}'.format('PASS' if row['passed'] else 'FAIL', row['stem']))
            print('     gobgp: {0}'.format(row['gobgp']))
            print('     sink:  {0}'.format(row['sink']))
            for reason in row['reasons']:
                print('     - {0}'.format(reason))
        failed = sum(1 for r in report if not r['passed'])
        print('{0} pair(s), {1} failed'.format(len(report), failed))
    return 0 if all(r['passed'] for r in report) else 1


if __name__ == '__main__':
    sys.exit(main())
