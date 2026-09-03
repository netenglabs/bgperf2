'''Summary statistics over the passes of a repeated batch matrix.

Phase 5 of the measurement plan asks for a median, a min and a max, a
dispersion and a coefficient of variation over the repetitions of one matrix
cell -- and asks for them *without hiding individual runs*, which is the whole
constraint.  One number per cell is what a reader wants, and it is also the
thing that makes three passes indistinguishable from one, so every statistic
here is published beside the observations it was computed from and the passes
those came from.

Kept free of Docker and of bgperf2 imports, like contention.py,
convergence.py and findings.py, so the arithmetic and the withholding rules
are testable without a daemon.

Its input is the stats rows the batch has already written to its CSV, read by
**column name**.  That row is positional for create_batch_graphs() and has
drifted by one column once already; a summary that averaged whichever column
happened to sit at index 12 would be arithmetic nobody could check.
'''

import math
import statistics


SUMMARY_SCHEMA = 'bgperf2/batch-summary/v1alpha1'

# Columns of the stats row that describe what was *measured*, so a
# distribution over the passes of one cell means something.  `required` is
# configuration and is carried as identity below; `date`, `cores` and
# `Mem (GB)` describe the machine, and `flags` and `MSG` are not numbers.
METRIC_COLUMNS = (
    'received',
    'monitor (s)',
    'elapsed (s)',
    'prefix received (s)',
    # Legacy, and named for what it is elsewhere: elapsed minus the first
    # monitor-visible prefix.  Summarised under its historical name, because
    # renaming it here would be the silent redefinition the plan forbids.
    'testers (s)',
    'total time',
    'max cpu %',
    'max mem (GB)',
    'min idle%',
    'min free mem (GB)',
    'tester errors',
    'tester timeouts',
    'max foreign cpu %',
)

# Read from the rows rather than from the cell, and checked for agreement
# across the passes: two passes of "one cell" that ran against different
# images are not two observations of the same thing, and that is the gcov trap
# -- a freshly built version beside a cached one -- reached one layer up.  A
# disagreement is surfaced, never averaged over.
PROVENANCE_COLUMNS = ('target image', 'tester version', 'monitor version')

# Configuration the target reported back, kept beside the metrics so a median
# `received` can be read against what the run required.
ROW_IDENTITY_COLUMNS = ('required',)

# What a run writes into a column it never sampled. Passed in by the caller
# rather than known here, because the sentinel is a property of the controller
# and this module is deliberately free of bgperf2 imports --
# `bgperf2.unsampled_row_values()` derives it from the one constant.
FAILED_COLUMN = 'failed'
FAILED_VALUE = 'FAILED'
MESSAGE_COLUMN = 'MSG'

# What the passes of a cell can be.  A pass that failed and a pass that has
# not run are both absent from the statistics and are counted apart, because
# one of them is a result and the other is unfinished work.
OBSERVED = 'observed'
FAILED = 'failed'
NOT_RUN = 'not run'
# A row that cannot be read against this header at all. It is kept apart from
# `failed` because it is not a result about the daemon: `--resume` onto a
# progress file written before a column was appended is a supported path, and
# such a row is one field short. One of them must cost that pass and not the
# whole document.
UNREADABLE = 'unreadable'

# Why a statistic is absent.  Nothing here is published as a zero: a
# coefficient of variation of 0 over one observation would say the measurement
# is perfectly repeatable on the strength of never having been repeated.
NO_OBSERVATION = 'no observation: every pass of this cell failed or has not run'
NON_NUMERIC = 'a pass reported a non-numeric value in this column'
NEEDS_TWO = 'a dispersion needs at least two observations'
UNSAMPLED = ('a pass reported the never-sampled sentinel in this column, so '
             'that pass never measured it')
MEAN_NOT_POSITIVE = 'the mean is not positive, so a relative dispersion has no meaning'

_STATISTICS = ('mean', 'median', 'min', 'max', 'stdev', 'cv_percent')

# Derived statistics are rounded; observations are not.  Six places keeps a
# small dispersion visible -- a 0.4 MB spread in `max mem (GB)` reads as
# 0.000391, not as 0.0 -- while keeping 1.4142135623730951 out of a document
# meant to be read.
_PLACES = 6

# What the printed line reports.  The rest is in the artifact: two metrics is
# a glance at repeatability, thirteen is a table nobody reads at the end of a
# batch that has run for hours.
PRINTED_METRICS = ('elapsed (s)', 'total time')


def _is_number(value):
    # A nan or an inf is not an observation.
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def _publishable(value):
    '''A value that survives `json.dump` into a document a strict parser reads.

    `json.dump` writes a nan or an inf as a bare word that jq and most
    non-Python parsers reject, so one is published as its own repr: the fact
    that a pass reported it is kept, and it is already not a number, so every
    statistic over that column is withheld anyway.
    '''
    if isinstance(value, float) and not math.isfinite(value):
        return repr(value)
    return value


def _round(value):
    return round(float(value), _PLACES)


def summarize_metric(values, unsampled=None):
    '''One column's distribution over the observed passes of one cell.

    `min` and `max` are observations and are copied through unrounded: a
    summary must not report an extreme no run produced.  Everything else is
    derived, so it is rounded, and `mean` is published because the coefficient
    of variation is otherwise a number a reader cannot check.

    `unsampled` is the value this column carries when the run never measured
    it.  One of those withholds the whole column for the cell rather than
    being dropped from it, for the same reason a non-numeric value does: a
    minimum that starts above every real value reaches the row as a machine
    with a petabyte free, and a cell where one pass of three lost its sampler
    would otherwise publish a coefficient of variation of 173% on a 64 GB box.
    '''
    raw = list(values)
    sentinel = [_is_number(v) and unsampled is not None and v == unsampled
                for v in raw]
    published = [None if seen else _publishable(v)
                 for v, seen in zip(raw, sentinel)]
    summary = {'values': published, 'n': len(published)}
    summary.update({name: None for name in _STATISTICS})
    withheld = {}
    if not raw:
        withheld = {name: NO_OBSERVATION for name in _STATISTICS}
    elif any(sentinel):
        withheld = {name: UNSAMPLED for name in _STATISTICS}
    elif not all(_is_number(v) for v in raw):
        # Dropping the offending pass instead would change n without saying
        # so, which is the one thing a dispersion cannot survive.
        withheld = {name: NON_NUMERIC for name in _STATISTICS}
    else:
        values = raw
        mean = statistics.fmean(values)
        summary['min'] = min(values)
        summary['max'] = max(values)
        summary['mean'] = _round(mean)
        summary['median'] = _round(statistics.median(values))
        if len(values) < 2:
            withheld['stdev'] = NEEDS_TWO
            withheld['cv_percent'] = NEEDS_TWO
        else:
            # Sample standard deviation, n-1: three passes are a sample of what
            # the machine does, and the population formula understates the
            # spread of one -- to exactly 0 at n=1.
            stdev = statistics.stdev(values)
            summary['stdev'] = _round(stdev)
            if mean > 0:
                summary['cv_percent'] = _round(100.0 * stdev / mean)
            else:
                withheld['cv_percent'] = MEAN_NOT_POSITIVE
    if withheld:
        summary['withheld'] = withheld
    return summary


def _agreement(rows, index, column):
    '''One value if every observed pass reported the same one, else all of them.

    Returns (value, disagreement) so the caller can both publish the field and
    say out loud that the passes did not agree about it.
    '''
    distinct = []
    for row in rows:
        value = row[index[column]]
        if value not in distinct:
            distinct.append(value)
    if not distinct:
        return None, None
    if len(distinct) == 1:
        return distinct[0], None
    return distinct, distinct


def summarize_cell(header, group, unavailable=None):
    '''One matrix cell: what was asked of it, which passes answered, and the
    distribution of those answers.

    The cell supplies the identity, because it is known whether or not any
    pass produced a row -- a cell whose every pass failed still has to say
    which cell it was.  The rows supply what came back.

    A row that is not this header's width costs its own pass and nothing else.
    `--resume` onto a progress file written before a column was appended is a
    supported path -- `BATCH_PROGRESS_SCHEMA_VERSION` deliberately did not move
    for `max foreign cpu %` -- and one short row indexed against this header
    raises `IndexError`, which the caller catches into *no summary at all* for
    the whole test, naming neither the cell nor the pass.  A row that is the
    right width but the wrong layout cannot be caught here at all, which is why
    `stats_header()` is the contract and `test_stats_contract.py` enforces it.
    '''
    index = {name: position for position, name in enumerate(header)}
    unavailable = unavailable or {}
    passes = []
    observed = []
    for entry in group['passes']:
        row = entry.get('row')
        described = {'repetition': entry.get('repetition')}
        if row is None:
            described['state'] = NOT_RUN
        elif len(row) != len(header):
            described['state'] = UNREADABLE
            described['message'] = (
                'row has {0} field(s), this header has {1}'.format(
                    len(row), len(header)))
        elif row[index[FAILED_COLUMN]] == FAILED_VALUE:
            described['state'] = FAILED
            described['message'] = row[index[MESSAGE_COLUMN]]
        else:
            described['state'] = OBSERVED
            observed.append(entry)
        passes.append(described)

    rows = [entry['row'] for entry in observed]
    identity = dict(group.get('identity') or {})
    inconsistent = {}
    for column in ROW_IDENTITY_COLUMNS:
        identity[column], disagreement = _agreement(rows, index, column)
        if disagreement:
            inconsistent[column] = disagreement
    provenance = {}
    for column in PROVENANCE_COLUMNS:
        provenance[column], disagreement = _agreement(rows, index, column)
        if disagreement:
            inconsistent[column] = disagreement

    summary = {
        'cell': group['ordinal'],
        'name': group['name'],
        # The run name is the target; two cells of one target differ only in
        # their axes, so a printed line naming only the target names both.
        'description': group.get('description') or group['name'],
        'identity': identity,
        'provenance': provenance,
        'passes_expected': len(group['passes']),
        'observations': len(observed),
        # In the same order as every metric's `values`, so a reader can say
        # which pass produced which number without a second lookup.
        'observed_passes': [entry.get('repetition') for entry in observed],
        'passes': passes,
        'metrics': {
            column: summarize_metric([row[index[column]] for row in rows],
                                     unsampled=unavailable.get(column))
            for column in METRIC_COLUMNS},
    }
    if inconsistent:
        summary['inconsistent'] = inconsistent
    return summary


def summarize_batch(test_name, header, groups, repetitions=1, unavailable=None):
    '''The whole test, one entry per matrix cell, in the order given.

    Matrix order, for the same reason the CSV is written in it: a shuffled
    execution order is a property of the run, not of the report.

    `unavailable` maps a column to the value a run writes into it when it
    never sampled it; see `summarize_metric()`.
    '''
    missing = [column for column in
               METRIC_COLUMNS + PROVENANCE_COLUMNS + ROW_IDENTITY_COLUMNS
               + (FAILED_COLUMN, MESSAGE_COLUMN)
               if column not in header]
    if missing:
        raise ValueError(
            'the stats header does not carry {0}; summary.py reads the row by '
            'column name and cannot guess'.format(', '.join(missing)))
    return {
        'schema': SUMMARY_SCHEMA,
        'test': test_name,
        'repetitions': repetitions,
        'cells': [summarize_cell(header, group, unavailable=unavailable)
                  for group in groups],
    }


def _describe_metric(metric):
    reported = '{0} median {1}'.format(metric['name'], metric['median'])
    reported = '{0} ({1}-{2})'.format(reported, metric['min'], metric['max'])
    if metric['cv_percent'] is None:
        return '{0}, CV unavailable'.format(reported)
    return '{0}, CV {1:.2f}%'.format(reported, metric['cv_percent'])


def describe_batch_summary(document, path=None):
    '''The lines a batch prints about its own repeatability.

    Nothing for a single-pass test: every dispersion in it is withheld, and a
    block of "CV unavailable" says only that the test asked for one pass.  A
    disagreement between passes is printed whenever there is one, because that
    is the finding, not the statistic beside it.
    '''
    lines = []
    cells = document.get('cells') or []
    repetitions = document.get('repetitions') or 1
    if repetitions > 1:
        heading = 'repeatability over {0} passes'.format(repetitions)
        lines.append('{0} ({1}):'.format(heading, path) if path else heading + ':')
        for cell in cells:
            described = ['{0}: {1} of {2} passes observed'.format(
                cell['description'], cell['observations'],
                cell['passes_expected'])]
            for column in PRINTED_METRICS:
                metric = cell['metrics'].get(column) or {}
                if metric.get('median') is None:
                    continue
                described.append(_describe_metric(dict(metric, name=column)))
            lines.append('  ' + '; '.join(described))
            for entry in cell['passes']:
                if entry['state'] == OBSERVED:
                    continue
                lines.append('    pass {0}: {1}{2}'.format(
                    entry['repetition'], entry['state'],
                    ' ({0})'.format(entry['message']) if entry.get('message') else ''))
    for cell in cells:
        for column, values in sorted((cell.get('inconsistent') or {}).items()):
            lines.append(
                '  warning: {0} passes disagree on {1}: {2}. These are not '
                'repeated observations of one thing.'.format(
                    cell['description'], column,
                    ', '.join(repr(v) for v in values)))
    return lines
