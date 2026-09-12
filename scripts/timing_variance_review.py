#!/usr/bin/env python3
'''The three passes of one canonical workload, read together.

Blocks 2-4 and 5-7 each ran one pass of the same fourteen-configuration
matrix, and each published its own CSV, its own progress file and its own
per-run artifacts.  A pass is a whole block on purpose -- see
`docs/invariants/batch-passes.md` -- so the dispersion of a cell is the one
statistic this campaign cannot read off any single block.  This is what reads
them together, and it is Block 9's mechanical work.

Four things it deliberately does not do:

- **It re-derives no measurement.**  Every number is read from a document a
  pass already published, and the arithmetic over them is `summary.py`'s --
  the same module that writes each block's own `<test>.summary.json`, floors
  the variance rule at the metric's resolution, and refuses a dispersion over
  one observation.  A second implementation of a median would disagree with
  the first one eventually, on exactly the cells anyone cared about.
- **It writes nothing into a block's results.**  Those passes are finished,
  reviewed and accepted; this reads them.
- **It decides no selection.**  Whether a comparison has earned repetitions
  4-5 is the operator's call, recorded in `metadata/block10-selection.json`,
  which this *validates* and never writes.  A tool that both proposed an
  expansion and approved it is the "re-run the results you dislike" failure
  the variance rule exists to prevent.
- **It publishes nothing absent as a zero.**  A withheld statistic is `null`
  with its reason beside it, a pass that failed is counted apart from one that
  never ran, and a cell that is missing from a pass is a problem rather than a
  smaller `n`.

Run it by hand to read a series, or through
`scripts/run_timing_validation_block.sh block-9`, which runs exactly this and
turns its exit status into the block's RAN marker.
'''
import argparse
import glob
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
for _path in (REPO_ROOT, HERE):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from summary import (DECISION_METRIC, EXPAND, EXPANSION_PASSES,  # noqa: E402
                     METRIC_RESOLUTION, OBSERVED, summarize_batch,
                     summarize_metric)
# Which cells are drawn beside each other, and therefore which ones a cell has
# to be separated *from*. Private to `summary.py` and imported anyway: a
# second copy of "one graph's group is (peers, prefixes, filter)" is a rule
# that would drift from the rule the verdict was computed under.
from summary import _comparison_key as comparison_key  # noqa: E402
# And the rounding the rule's own published gaps go through. Comparing a raw
# `abs(a - b)` against the resolution reports 1.0000000000000002 > 1.0 for a
# pair the rule can never separate -- a float artefact approving hours of
# measurement.
from summary import _round as round_like_the_rule  # noqa: E402
# The pairing of an artifact to the row of the cell that produced it, from the
# one module that already does it -- including its refusal to choose when two
# rows of a directory cannot be told apart.  A second copy of that rule is how
# Block 8's peer sweep would have been qualified against one arbitrary cell.
from check_timing_evidence import RowIndex, load_json  # noqa: E402
# Three names from the controller, none of them a measurement: what a run is
# called, how a cell is described in a printed line, and what an unsampled
# memory column looks like in a row.  Copying any of the three here is the
# drift this project keeps finding: `unsampled_row_values()` in particular is
# a sentinel whose second copy would silently stop matching and publish a
# 931,322 GB mean on a 64 GB host.
from bgperf2 import (batch_cell_description, target_run_name,  # noqa: E402
                     unsampled_row_values)

REVIEW_SCHEMA = 'bgperf2/timing-variance-review/v1alpha1'
SELECTION_SCHEMA = 'bgperf2/block10-selection/v1alpha1'

# The canonical workloads, and which block ran which pass of each.  Nothing
# inside a block says it is one pass of three -- a repetition is part of a
# run's *name* and never a column beside it, and here it is part of a block's
# name -- so this table is the only place the three are joined.  It names the
# block keys `run_timing_validation_block.sh` uses, so a renamed directory
# fails here rather than quietly reviewing two passes.
SERIES = (
    {
        'name': 'synthetic',
        # The plan's "never expand the entire matrix automatically" is about
        # this shape of series: fourteen configurations that a reader who
        # disliked the CSV could re-run wholesale. A screen scenario is three
        # cells that *are* one comparison, and the plan asks for those to be
        # repeated by the scenario.
        'scope': 'matrix',
        'workload': '50 peers x 100,000 prefixes per peer, BIRD generator, no policy',
        'passes': (
            {'repetition': 1, 'block': 'block2-synthetic-rep1', 'results': 'synthetic'},
            {'repetition': 2, 'block': 'block3-synthetic-rep2', 'results': 'synthetic'},
            {'repetition': 3, 'block': 'block4-synthetic-rep3', 'results': 'synthetic'},
        ),
    },
    {
        'name': 'mrt',
        'scope': 'matrix',
        'workload': '10 full-internet peers, ten bgpdump2 injectors, pinned Route Views RIB',
        'passes': (
            {'repetition': 1, 'block': 'block5-mrt-rep1', 'results': 'mrt'},
            {'repetition': 2, 'block': 'block6-mrt-rep2', 'results': 'mrt'},
            {'repetition': 3, 'block': 'block7-mrt-rep3', 'results': 'mrt'},
        ),
    },
)

# The BIRD architecture screen is one observation per cell, by design -- the
# plan calls it "deliberately adaptive": run the screen, then repeat only what
# separates the configurations.  It is reviewed through the identical code
# path, which is the point: `summary.py` then withholds every dispersion with
# "a dispersion needs at least two observations" instead of this file deciding
# what a single pass may claim.  Each scenario is its own series because each
# ran into its own results directory, and that separation is load-bearing --
# reload and churn are both 50 x 50,000 with the same three run names.
SCREEN_BLOCK = 'block8-bird-architecture-screen'
SCREEN_SERIES = tuple(
    {
        'name': 'screen-{0}'.format(scenario),
        'scope': 'scenario',
        'workload': 'BIRD architecture screen: {0} (one observation per cell)'.format(scenario),
        'passes': ({'repetition': 1, 'block': SCREEN_BLOCK, 'results': scenario},),
    }
    for scenario in ('peers', 'diversity', 'fanout', 'reload', 'churn')
)

ALL_SERIES = SERIES + SCREEN_SERIES

# Every block whose rows this reads.  They must be accepted, not merely run:
# a COMPLETE marker is the record that an operator reviewed the rows, and a
# statistic computed over an unreviewed pass would carry that pass's unread
# problems into a verdict about a daemon.
INPUT_BLOCKS = tuple(dict.fromkeys(
    entry['block'] for series in ALL_SERIES for entry in series['passes']))

# Timing components read from the per-run artifact, each from the document
# that published it.  The plan asks Block 9 to "separate end-to-end,
# injection, post-injection tail, CPU, and memory findings"; `elapsed (s)`,
# the CPU and the memory columns are in the stats row and are summarised by
# `summary.py`, and these are the rest.
#
# `post_injection_tail_s` is signed and nothing clamps it, `monitor_lag_s` is
# signed for the same reason, and an absent value is None rather than 0 --
# `delivery` is withheld entirely by daemons with no export gauge, and a
# missing interval published as a zero is a daemon that answered instantly.
ARTIFACT_INTERVALS = (
    ('first_prefix_s', ('measurements', 'first_prefix_s')),
    ('convergence_s', ('measurements', 'convergence_s')),
    ('assurance_s', ('measurements', 'assurance_s')),
    ('tester_startup_s', ('tester_fleet', 'tester_startup_s')),
    ('injection_s', ('tester_fleet', 'injection_s')),
    ('reported_injection_s', ('tester_fleet', 'reported_injection_s')),
    ('post_injection_tail_s', ('tester_fleet', 'post_injection_tail_s')),
    ('offered_rate_pps', ('tester_fleet', 'offered_rate_pps')),
    # Not an interval: the number of offered prefixes that crossed the
    # interval `injection_s` measures. It travels with that interval because
    # it is what makes it readable -- a BIRD 2.19 generator's offered count is
    # queue-side and saturates before the first poll, so `injection_s` comes
    # back as 0.0 with nothing having crossed it, which is a span nothing
    # crossed and not a send that took no time.
    ('offered_in_interval', ('tester_fleet', 'offered_in_interval')),
    ('delivery_complete_s', ('target_table', 'delivery', 'complete_s')),
    ('delivery_monitor_lag_s', ('target_table', 'delivery', 'monitor_lag_s')),
)

# The workload controls' own completion measurements, which are the numbers
# the BIRD screen separates its configurations on -- `elapsed (s)` is not the
# measurement for a policy reload or a churn burst.  Read from the same
# artifacts; absent on every canonical run, which is what `None` says.
WORKLOAD_METRICS = (
    ('reload_s', ('policy_reload', 'reload_s')),
    ('reload_cpu_percent_mean', ('policy_reload', 'target_cpu_percent_mean')),
    ('reload_command_s', ('policy_reload', 'command_s')),
    ('export_spread_s', ('export', 'export_spread_s')),
    ('export_monitor_delta_s', ('export', 'monitor_delta_s')),
)

# Host facts that make a replacement machine the same *class* of host, from
# the campaign's Fixed Campaign Identity: instance type, CPU model, vCPU count
# and memory.  Kernel, availability zone and instance id are recorded and
# advisory, so they are deliberately not here.
HOST_CLASS_FIELDS = (('cpu_model', ('cpu_model',)),
                     ('cpu_threads', ('cpu_threads',)),
                     ('memory_total_kb', ('memory_total_kb',)),
                     ('instance_type', ('instance', 'type')))

# Memory is the one class field compared with a tolerance, and it has to be.
# `MemTotal` is what the kernel has left after firmware and its own early
# reservations, so two boots of one instance type differ by a few kB: this
# campaign's own blocks recorded 64,425,440 and 64,425,436 kB on the same
# instance type and the same CPU, 4 kB apart.  An exact test there reports a
# host-class change over 0.000006%, which is the rule failing on the case it
# was written for -- a replacement machine after a spot reclaim.  Everything
# else in the class is a name or a count and is compared exactly.
HOST_MEMORY_TOLERANCE = 0.01

ERROR = 'error'
NOTE = 'note'


def problem(problems, severity, message):
    problems.append({'severity': severity, 'message': message})
    return problems


def read_json(path, problems, why):
    '''One document, or a named problem and None.

    `check_timing_evidence.load_json()` *returns* None for a file it cannot
    read rather than raising, which is the right shape for its caller and the
    wrong one to assume: a `try/except ValueError` around it never fires, and
    the None goes on to be dereferenced two lines later.  Every read here goes
    through this instead, so a truncated progress file, a corrupt artifact or
    a half-written selection is reported as the thing it is.

    That is not hypothetical for the selection in particular: it is written by
    hand, between two sessions, and a malformed one is the expected failure.
    '''
    document = load_json(path)
    if document is None:
        problem(problems, ERROR, '{0}: {1}'.format(path, why))
    return document


def dig(document, path):
    '''One nested field, or None when any level of it is absent.

    None rather than a default, everywhere: an interval a run never published
    and an interval that measured zero are different facts, and this campaign
    keeps them apart at every level of aggregation.
    '''
    value = document
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def csv_header(path):
    '''The header a pass's rows were written under.

    Read from that pass's own CSV rather than from `stats_header()`, because a
    row is only readable against the header it was written with: a pass
    measured before a column was appended is one field short, and
    `summary.py` calls that pass `unreadable` rather than shifting its
    columns.  Blocks measured under different headers are a problem this
    reports, not one it silently reconciles.
    '''
    with open(path, 'r', encoding='utf-8') as f:
        line = f.readline()
    return [field.strip() for field in line.rstrip('\n').split(',')]


def execution_positions(cell_ids, seed, order):
    '''Where each cell ran within its pass, rebuilt from the recorded seed.

    `order_batch_cells()` sorts a pass's cells by the digest of
    `"<seed>:<batch_cell_id>"`, and the keys of the progress document *are*
    those cell ids -- so this sorts strings the document already carries
    rather than rebuilding the identity that produced them.  That is the whole
    reason a seed is recorded: the sequence can be rebuilt later.  Checked
    against the positions the plan's own Block 4 record cites (`openbgp 8.8`
    at 7, 14 and 4 across the three synthetic passes).

    A pass that ran in matrix order has positions too, and they are its
    ordinals: `order_batch_cells()` returns that list untouched.
    '''
    if order == 'shuffle':
        sequence = sorted(cell_ids, key=lambda cell_id: hashlib.sha256(
            '{0}:{1}'.format(seed, cell_id).encode('utf-8')).hexdigest())
    else:
        sequence = sorted(cell_ids,
                          key=lambda cell_id: json.loads(cell_id)['ordinal'])
    return {cell_id: index for index, cell_id in enumerate(sequence, 1)}


def cell_identity_key(identity):
    '''What makes two passes' rows observations of one cell.

    Everything the cell id carries except the two fields that describe the
    *pass* rather than the cell: `test`, which differs by construction -- the
    three configs of a series differ in their `name` and their `seed` and
    nothing else -- and `repetition`, which a single-pass block does not carry
    at all.  Anything else differing means the matrix moved between passes,
    and that is reported rather than reconciled.
    '''
    return json.dumps({key: value for key, value in identity.items()
                       if key not in ('test', 'repetition')}, sort_keys=True)


def read_pass(run_root, entry, problems):
    '''One pass: its rows already paired with their cells, and its artifacts.

    The rows come from the progress document rather than from the CSV, and
    that is not a shortcut.  The progress file maps `batch_cell_id()` -> the
    stats row, so a row arrives already carrying the identity of the cell that
    produced it; `publish_batch_summary()` groups its passes from exactly that
    mapping.  Reading the CSV instead would mean re-deriving the pairing from
    three columns -- which is what `RowIndex` is for, and it is needed here
    only for the *artifacts*, where no such mapping exists.
    '''
    directory = os.path.join(run_root, entry['block'], entry['results'])
    found = sorted(glob.glob(os.path.join(directory, '*.progress.json')))
    if len(found) != 1:
        problem(problems, ERROR, '{0}: expected one progress file, found {1}'
                .format(directory, len(found)))
        return None
    progress_path = found[0]
    test = os.path.basename(progress_path)[: -len('.progress.json')]
    csv_path = os.path.join(directory, '{0}.csv'.format(test))
    if not os.path.isfile(csv_path):
        problem(problems, ERROR, '{0}: no CSV beside {1}'.format(
            directory, os.path.basename(progress_path)))
        return None
    progress = read_json(progress_path, problems,
                         'the progress file could not be read, so this pass '
                         'has no rows and no recorded order')
    if progress is None:
        return None
    cells_by_id = progress.get('cells') or {}
    # A pass that was resumed after its config was edited has rows that ran
    # under a sequence the file no longer names -- `write_batch_progress()`
    # moves the old one to `previous_seeds` precisely so that is knowable.
    # Rebuilding positions from the surviving seed alone would publish an
    # order some of these rows never ran in, which is the one thing recording
    # a seed exists to prevent, so they are withheld instead.
    superseded = progress.get('previous_seeds') or []
    if superseded:
        problem(problems, NOTE,
                '{0}: {1} superseded sequence(s) recorded, so some rows ran '
                'in an order this file no longer names; execution positions '
                'are withheld for this pass'.format(directory, len(superseded)))
        positions = {}
    else:
        positions = execution_positions(list(cells_by_id), progress.get('seed'),
                                        progress.get('order'))
    header = csv_header(csv_path)
    cells = []
    for cell_id, row in sorted(
            cells_by_id.items(),
            key=lambda item: json.loads(item[0])['ordinal']):
        identity = json.loads(cell_id)
        cells.append({
            'cell_id': cell_id,
            'key': cell_identity_key(identity),
            'identity': identity,
            'row': row,
            'position': positions.get(cell_id),
        })
    artifact_paths, artifacts = [], []
    for artifact_path in sorted(glob.glob(os.path.join(directory,
                                                       '*.events.json'))):
        artifact = read_json(artifact_path, problems,
                             'this run\'s artifact could not be read, so its '
                             'intervals are absent from the review')
        if artifact is None:
            # Dropped rather than carried as None: `RowIndex` reads `run` off
            # every artifact it is handed. The cell then reports "a row and no
            # artifact", which is what happened.
            continue
        artifact_paths.append(artifact_path)
        artifacts.append(artifact)
    return {
        'repetition': entry['repetition'],
        'block': entry['block'],
        'results': entry['results'],
        'directory': directory,
        'test': test,
        'csv': csv_path,
        'seed': progress.get('seed'),
        'order': progress.get('order'),
        'positions_known': not superseded,
        'header': header,
        'cells': cells,
        'artifacts': artifacts,
        # The file name as the evidence documents record it. That is the only
        # thing that tells two rows of one scenario apart when they share a run
        # name -- the screen's peer sweep writes three rows called `bird
        # 2.19.2`, and one of the three was rejected.
        'artifact_names': [os.path.basename(path) for path in artifact_paths],
        'rows': len(cells),
    }


def pair_artifacts(one_pass, problems):
    '''Artifact -> cell, through the checker's own row index.

    A run's artifact records the run name and the three axes the CSV carries,
    and `RowIndex` is what pairs those with a row; the rows here are the same
    row objects the cells hold, so an identity match on the row is a match on
    the cell.  Its refusal to choose between two rows it cannot tell apart is
    the reason to use it rather than a dict: the screen's peer sweep writes
    three rows named `bird 3.3.2`, and a cell paired with the wrong one would
    publish another cell's intervals under this cell's name.
    '''
    index = RowIndex()
    rows = [dict(zip(one_pass['header'], [str(field) for field in cell['row']]))
            for cell in one_pass['cells']]
    by_row_id = {id(row): cell for row, cell in zip(rows, one_pass['cells'])}
    index.add_rows(rows)
    for artifact, artifact_name, (row, trouble) in zip(
            one_pass['artifacts'], one_pass['artifact_names'],
            index.pair_all(one_pass['artifacts'])):
        if row is None:
            problem(problems, ERROR, '{0}: artifact for {1!r} has no cell: {2}'
                    .format(one_pass['directory'],
                            (artifact.get('run') or {}).get('name'), trouble))
            continue
        cell = by_row_id.get(id(row))
        if cell is None:
            continue
        if cell.get('artifact') is not None:
            problem(problems, ERROR,
                    '{0}: two artifacts pair with the same cell {1}'.format(
                        one_pass['directory'], cell['identity']['ordinal']))
            continue
        cell['artifact'] = artifact
        cell['artifact_name'] = artifact_name
    for cell in one_pass['cells']:
        if cell.get('artifact') is None:
            problem(problems, ERROR, '{0}: cell {1} has a row and no artifact'
                    .format(one_pass['directory'], cell['identity']['ordinal']))


def build_groups(passes, problems):
    '''The passes of each cell, in matrix order, in `summary.py`'s own shape.

    A cell that one pass ran and another did not still gets an entry for the
    pass that did not: `summarize_cell()` then counts it `not run`, which is
    counted apart from a pass that failed, because one is unfinished work and
    the other is a result.  Dropping it would change `n` without saying so,
    which is the one thing a dispersion cannot survive.
    '''
    order, collected = [], {}
    for one_pass in passes:
        for cell in one_pass['cells']:
            if cell['key'] not in collected:
                collected[cell['key']] = {'identity': cell['identity'],
                                          'by_repetition': {}}
                order.append(cell['key'])
            collected[cell['key']]['by_repetition'][one_pass['repetition']] = cell
    groups, records = [], []
    for key in sorted(order, key=lambda k: collected[k]['identity']['ordinal']):
        entry = collected[key]
        identity = entry['identity']
        cell_passes, pass_records = [], []
        for one_pass in passes:
            cell = entry['by_repetition'].get(one_pass['repetition'])
            if cell is None:
                problem(problems, ERROR,
                        'cell {0} ({1}) is absent from pass {2} ({3})'.format(
                            identity['ordinal'], target_run_name(identity['target']),
                            one_pass['repetition'], one_pass['block']))
            cell_passes.append({'repetition': one_pass['repetition'],
                                'row': None if cell is None else cell['row']})
            pass_records.append({
                'repetition': one_pass['repetition'],
                'block': one_pass['block'],
                'results': one_pass['results'],
                'position': None if cell is None else cell['position'],
                'cell': cell,
            })
        groups.append({
            'ordinal': identity['ordinal'],
            'name': target_run_name(identity['target']),
            'description': batch_cell_description(identity),
            'identity': {'peers': identity['neighbors'],
                         'prefixes': identity['prefixes'],
                         'filter': identity['filter'],
                         'target': identity['target']},
            'passes': cell_passes,
        })
        records.append({'ordinal': identity['ordinal'],
                        'name': target_run_name(identity['target']),
                        'description': batch_cell_description(identity),
                        'passes': pass_records})
    return groups, records


def agreement(values):
    '''One value if every pass reported the same one, else all of them.

    The shape `summary.py` publishes for an image or a version, reached for
    the same reason: two passes that disagree about what they measured are not
    two observations of one thing, and the disagreement is surfaced rather
    than resolved.
    '''
    distinct = []
    for value in values:
        if value not in distinct:
            distinct.append(value)
    if not distinct:
        return None, None
    if len(distinct) == 1:
        return distinct[0], None
    return distinct, distinct


def order_relation(observations):
    '''Whether this cell's passes rank the way their positions do.

    Descriptive and named as such.  Fourteen cells over three passes is not a
    test of anything, and publishing a coefficient beside it would read as
    one; what it can honestly say is whether the slowest pass of a cell was
    also its latest, and how many cells say the same thing.  A tie is its own
    answer -- the decision metric is whole seconds, so passes of one cell
    agreeing exactly is the common case and reading a direction out of it
    would be reading the rounding.
    '''
    ranked = [entry for entry in observations
              if entry['position'] is not None and entry['value'] is not None]
    if len(ranked) < 2:
        return 'too few observations'
    ranked.sort(key=lambda entry: entry['position'])
    values = [entry['value'] for entry in ranked]
    if len(set(values)) == 1:
        return 'tied'
    if all(b >= a for a, b in zip(values, values[1:])):
        return 'rises with position'
    if all(b <= a for a, b in zip(values, values[1:])):
        return 'falls with position'
    return 'neither'


def review_series(run_root, series, unavailable, problems):
    '''One workload's passes, summarised together.'''
    passes = []
    for entry in series['passes']:
        one_pass = read_pass(run_root, entry, problems)
        if one_pass is None:
            return None
        pair_artifacts(one_pass, problems)
        passes.append(one_pass)

    headers = {tuple(one_pass['header']) for one_pass in passes}
    if len(headers) != 1:
        problem(problems, ERROR,
                '{0}: the passes were written under different stats headers, '
                'so their rows are not columns of one table'.format(series['name']))
        return None
    header = passes[0]['header']
    positions_known = all(one_pass['positions_known'] for one_pass in passes)

    groups, records = build_groups(passes, problems)
    try:
        document = summarize_batch(series['name'], header, groups,
                                   repetitions=len(passes),
                                   unavailable=unavailable)
    except Exception as failure:      # noqa: BLE001 - see above
        # `summarize_batch()` refuses a header that does not carry a column it
        # reads, which is what three passes written under an older stats
        # header look like -- the per-pass equality check above only catches
        # passes that disagree with *each other*. Uncaught it killed the whole
        # review, with the runner then pointing at a `review/` directory that
        # had been removed and never recreated.
        #
        # Broad, like `summarize_batch()`'s own catch around the variance
        # rule, and for the same reason one level up: this reads six other
        # series from documents that are all still on disk, and a KeyError in
        # one of them must cost that one. The type is named so the failure is
        # not mistaken for a rule.
        problem(problems, ERROR, '{0}: {1}: {2}'.format(
            series['name'], type(failure).__name__, failure))
        return None
    if document.get('variance_failure'):
        problem(problems, ERROR, '{0}: {1}'.format(series['name'],
                                                   document['variance_failure']))
    by_ordinal = {cell['cell']: cell for cell in document['cells']}
    # The cells each cell is drawn beside, which is the group `separated` is a
    # claim about.
    grouped = {}
    for cell in document['cells']:
        grouped.setdefault(comparison_key(cell), []).append(cell)
    rivals_of = {cell['cell']: [other for other in grouped[comparison_key(cell)]
                                if other is not cell]
                 for cell in document['cells']}

    metric_index = {name: position for position, name in enumerate(header)}
    relations = {}
    for record in records:
        summary_cell = by_ordinal.get(record['ordinal']) or {}
        if summary_cell.get('inconsistent'):
            problem(problems, ERROR,
                    '{0}: {1} passes disagree about {2}; they are not '
                    'observations of one thing'.format(
                        series['name'], record['description'],
                        ', '.join(sorted(summary_cell['inconsistent']))))
        # Which passes actually observed anything, decided by `summary.py` and
        # read back rather than decided again here.  A row exists for a pass
        # that FAILED as well as for one that converged -- `batch()` records
        # `completed[cell_id] = bench(a)` either way -- and reading the metric
        # off the row because the row is there publishes a failed run as an
        # observation.  It did: a cell with one failed pass of three reported
        # `observations: 2` in its summary beside three values in its
        # decomposition, a direction in `order_relation` that existed only
        # because of the failed run, and a 50% coefficient of variation on
        # `convergence_s` invented by a run that never converged.
        #
        # Keyed by repetition rather than by position in the list, because a
        # near-miss on two parallel lists is exactly how this went wrong once.
        states = {entry.get('repetition'): entry.get('state')
                  for entry in (summary_cell.get('passes') or [])}
        observations, artifacts = [], []
        for entry in record['passes']:
            cell = entry.pop('cell')
            entry['artifact'] = None if cell is None else cell.get('artifact_name')
            entry['state'] = states.get(entry['repetition'])
            value = None
            observed = entry['state'] == OBSERVED
            if observed and cell is not None and cell['row'] is not None:
                index = metric_index[DECISION_METRIC]
                raw = cell['row'][index] if index < len(cell['row']) else None
                value = raw if isinstance(raw, (int, float)) else None
            entry[DECISION_METRIC] = value
            observations.append({'position': entry['position'], 'value': value})
            # The artifact goes the same way: a failed run's intervals
            # describe a failure, and averaging them in is the same error one
            # document down.
            artifacts.append(cell.get('artifact')
                             if observed and cell is not None else None)
        # Carried onto the record so a selection can be judged on the cells
        # it names rather than only on each cell's own group.
        decision = (summary_cell.get('metrics') or {}).get(DECISION_METRIC) or {}
        record['median'] = decision.get('median')
        record['stdev'] = decision.get('stdev')
        record['expansion'] = expansion_prospect(
            summary_cell, rivals_of.get(record['ordinal']) or [])
        record['order_relation'] = (
            order_relation(observations) if positions_known
            else 'order withheld: a superseded sequence')
        relations[record['order_relation']] = relations.get(record['order_relation'], 0) + 1
        record['intervals'] = interval_statistics(artifacts, record['passes'],
                                                  ARTIFACT_INTERVALS)
        workload = interval_statistics(artifacts, record['passes'], WORKLOAD_METRICS)
        # Only the controls this scenario actually exercised: every canonical
        # run publishes none of them, and a screen run publishes one.  An
        # empty section would read as a reload that took no time.
        record['workload'] = {name: stats for name, stats in workload.items()
                              if stats['n']}
        record['churn'] = churn_statistics(artifacts, record['passes'])
        # Only the passes that observed something. `artifacts` carries None
        # for a pass that failed or never ran, and an agreement over those
        # published `['unresolved', None]` as the cell's attribution and then
        # reported it as a disagreement -- a pass that failed described in the
        # same clause as an attribution that differs, which is the one thing
        # this file's header says it does not do.
        attributions = [dig(artifact, ('findings', 'limiting_component'))
                        for artifact in artifacts if artifact is not None]
        limiting, disagreed = agreement(attributions)
        record['limiting_component'] = limiting
        # Counted by state rather than as "n of m", which collapses a pass
        # that failed into one clause with a pass that never ran -- the one
        # distinction this campaign keeps at every level of aggregation, and
        # `0 of 3` means all three failed, none ran, or any mix of the two.
        record['limiting_component_observations'] = {
            'passes': {state: sum(1 for entry in record['passes']
                                  if entry['state'] == state)
                       for state in sorted({entry['state']
                                            for entry in record['passes']}
                                           - {None})},
            # Not the same number: a pass can be `observed` and still have no
            # artifact to attribute from -- `pair_artifacts()` reports that as
            # a cell with a row and no artifact -- and counting the states
            # alone published three passes behind a verdict two of them
            # supported.
            'attributed': len(attributions)}
        record['limiting_reason'] = agreement(
            [dig(artifact, ('findings', 'reason'))
             for artifact in artifacts if artifact is not None])[0]
        if disagreed:
            # A note, not an error.  The verdict is a judgement about one run
            # and it is allowed to differ between passes -- that difference is
            # itself a finding, and the campaign's within-daemon comparisons
            # do not rest on it.
            problem(problems, NOTE,
                    '{0}: {1} was attributed to {2} across its passes'.format(
                        series['name'], record['description'],
                        ' / '.join(str(value) for value in disagreed)))

    return {
        'schema': REVIEW_SCHEMA,
        'series': series['name'],
        'scope': series['scope'],
        'workload': series['workload'],
        'decision_metric': DECISION_METRIC,
        'metric_resolution': METRIC_RESOLUTION.get(DECISION_METRIC),
        'expansion_passes': EXPANSION_PASSES,
        'passes': [{'repetition': one_pass['repetition'],
                    'block': one_pass['block'],
                    'test': one_pass['test'],
                    'seed': one_pass['seed'],
                    'order': one_pass['order'],
                    'rows': one_pass['rows'],
                    'csv': os.path.relpath(one_pass['csv'], run_root)}
                   for one_pass in passes],
        'summary': document,
        'cells': records,
        'order_effects': {
            'relations': relations,
            'basis': 'each cell ranked by its own passes; {0} cells over {1} '
                     'passes is a description and not a test'.format(
                         len(records), len(passes)),
        },
    }


def expansion_prospect(cell, rivals):
    '''Whether a tighter dispersion could change this cell's verdict.

    The rule separates two cells when their medians differ by more than the
    sum of their deviations, **floored at the metric's resolution** -- so a
    pair whose medians are one second apart on a metric counted off a one
    second poll can never be separated, however many passes are run: with a
    dispersion of exactly zero the margin is still zero, and the rule needs it
    positive.  "Observed variance could change the decision" is a condition
    the plan puts on expanding a comparison, so it is worth saying out loud
    rather than leaving to be re-derived by whoever plans Block 10.

    **The claim is about the dispersion, not about the future.**  More passes
    move a median as well as tightening a spread, so "these two can never be
    separated" is not something this can know.  What it does know is that at
    the medians already observed, a gap inside the resolution cannot be
    cleared by *any* reduction in dispersion -- the floor is what the margin
    is measured against -- so expanding is a bet on a median moving rather
    than on the variance the plan's condition names.  Hence
    `dispersion_could_decide` and not `could_separate`.

    **Decided against the nearest rival, not the binding one.**  The verdict's
    own `evidence` names the rival with the smallest *margin*, which is the
    closest call and the right thing to report a verdict against -- but it is
    the wrong thing to ask this question of, because `separated` means
    distinguishable from *every* cell drawn beside it.  A cell 0.5s from one
    rival and 10s from the rival that happened to bind is not separated by
    tightening anything, and reading the binding rival's gap says it is.  Same
    shape of error as the one `apply_variance_rule()` records making three
    times: a rule written against the case in front of it rather than against
    the claim.

    **Only rivals the rule would judge**, which is `summary.py`'s `measurable`
    set: a rival with a median and no dispersion has one observation, and a
    provisional median is not something to rule against -- the verdict
    withholds `separated` for such a rival under its own reason, and that one
    *is* removable by giving the rival more passes.

    It says nothing about whether the comparison is worth making.  That is the
    review, and it is the reason this returns a prospect rather than a
    recommendation.
    '''
    variance = cell.get('variance') or {}
    if variance.get('verdict') != EXPAND:
        return None
    statistics = (cell.get('metrics') or {}).get(DECISION_METRIC) or {}
    median = statistics.get('median')
    if median is None:
        return None
    resolution = METRIC_RESOLUTION.get(DECISION_METRIC, 0.0)
    gaps = []
    for other in rivals:
        rival = (other.get('metrics') or {}).get(DECISION_METRIC) or {}
        if rival.get('median') is None or rival.get('stdev') is None:
            continue
        gaps.append((round_like_the_rule(abs(rival['median'] - median)),
                     other['description']))
    if not gaps:
        return None
    gap, nearest = min(gaps)
    if gap > resolution:
        return {'dispersion_could_decide': True, 'gap': gap,
                'resolution': resolution, 'rival': nearest,
                'rival_chosen_by': 'gap'}
    return {
        'dispersion_could_decide': False, 'gap': gap, 'resolution': resolution,
        'rival': nearest, 'rival_chosen_by': 'gap',
        'reason': 'a gap of {0} to {1} is inside the {2} resolution of {3}, '
                  'which the rule floors the combined deviation at -- so no '
                  'reduction in dispersion separates them, and only a moved '
                  'median could'.format(gap, nearest, resolution,
                                        DECISION_METRIC),
    }


def interval_statistics(artifacts, pass_records, definitions):
    '''Each named interval across the passes, with its per-pass values kept.

    `summarize_metric()` does the arithmetic, so the withholding rules are the
    ones the campaign already publishes: no dispersion under two observations,
    no coefficient of variation without a positive mean, and `min`/`max` left
    unrounded because they are observations.
    '''
    statistics_by_name = {}
    for name, path in definitions:
        values, by_pass = [], []
        for artifact, entry in zip(artifacts, pass_records):
            value = dig(artifact or {}, path)
            value = value if isinstance(value, (int, float)) else None
            by_pass.append({'repetition': entry['repetition'], 'value': value})
            if value is not None:
                values.append(value)
        statistics_by_name[name] = dict(summarize_metric(values),
                                        by_pass=by_pass)
    return statistics_by_name


def churn_statistics(artifacts, pass_records):
    '''The churn scenario's two halves, over every burst of every pass.

    Timing the withdraw and the re-announce separately is what showed BIRD 3
    splitting by half in Block 8; one end-to-end burst number reads as a
    uniform loss.  Bursts are pooled with passes here rather than averaged per
    run first, so `n` is the number of measured bursts and says so.
    '''
    pooled = {'withdraw_s': [], 'reannounce_s': [], 'burst_s': []}
    by_pass = []
    for artifact, entry in zip(artifacts, pass_records):
        bursts = dig(artifact or {}, ('churn', 'bursts')) or []
        for burst in bursts:
            for name in pooled:
                value = burst.get(name)
                if isinstance(value, (int, float)):
                    pooled[name].append(value)
        if bursts:
            by_pass.append({'repetition': entry['repetition'],
                            'bursts': len(bursts)})
    if not by_pass:
        return None
    result = {name: summarize_metric(values) for name, values in pooled.items()}
    result['bursts_by_pass'] = by_pass
    return result


def review_blocks(run_root, problems):
    '''What measured the passes: the markers, the hosts and the images.

    Three questions a per-block document cannot answer on its own, and all
    three decide whether the rows may be read together at all:

    - **Was every pass reviewed?**  A COMPLETE marker is an operator's record
      that they read the block's evidence.  A statistic over an unreviewed
      pass carries that pass's unread problems into a verdict about a daemon.
    - **Was it the same class of host?**  A spot reclaim hands the campaign a
      replacement machine, and one matching on instance type, CPU model, vCPU
      count and memory continues the campaign; a host change between blocks is
      expected and recorded.  A change of *class* is not, and it would land
      inside the dispersion this block exists to compute.
    - **Was it the same binary?**  The manifest records each image's id per
      block, and that is the only thing in this campaign that can answer it.
      The Block 6 and 7 records had to argue from "nothing ran `prepare`"
      precisely because provenance carries the image *tag* and the daemon's
      own version string -- a rebuilt `:latest` reporting the same `-dev`
      string is invisible in a stats row.  The ids are not.
    '''
    manifest_path = os.path.join(run_root, 'metadata', 'manifest.json')
    manifest = {}
    if os.path.isfile(manifest_path):
        manifest = read_json(manifest_path, problems,
                             'the manifest could not be read, so no host or '
                             'image can be checked across the blocks') or {}
    else:
        problem(problems, ERROR, '{0}: no manifest, so no host or image can be '
                'checked across the blocks'.format(manifest_path))
    blocks = manifest.get('blocks') or {}
    review = {'schema': REVIEW_SCHEMA, 'manifest': os.path.relpath(
        manifest_path, run_root), 'blocks': {}, 'images': {}}

    for key in INPUT_BLOCKS:
        marker = os.path.join(run_root, key, 'COMPLETE')
        entry = blocks.get(key) or {}
        host = entry.get('host') or {}
        accepted = os.path.isfile(marker)
        if not accepted:
            problem(problems, ERROR,
                    '{0} has no COMPLETE marker, so its rows have not been '
                    'reviewed and may not be read together with the '
                    'others'.format(key))
        attempts = [attempt.get('host') or {}
                    for attempt in entry.get('previous_entries') or []]
        review['blocks'][key] = {
            'accepted': accepted,
            'host': host,
            'revision': dig(entry, ('bgperf2', 'revision')),
            'previous_hosts': [{field: dig(attempt, path)
                                for field, path in HOST_CLASS_FIELDS}
                               for attempt in attempts],
            'mrt_inputs': entry.get('mrt_inputs'),
        }
        if attempts:
            problem(problems, NOTE,
                    '{0} was measured across {1} attempt(s); a reclaim inside '
                    'a block is a finding in that block\'s record, not grounds '
                    'to discard it'.format(key, len(attempts) + 1))

    for field, path in HOST_CLASS_FIELDS:
        values = {key: dig(entry['host'], path)
                  for key, entry in review['blocks'].items()}
        present = {key: value for key, value in values.items() if value is not None}
        absent = sorted(key for key in values if key not in present)
        described = ', '.join('{0}={1}'.format(key, value)
                              for key, value in sorted(present.items()))
        if len(set(present.values())) > 1:
            spread = host_memory_spread(field, present)
            if spread is not None and spread <= HOST_MEMORY_TOLERANCE:
                problem(problems, NOTE,
                        'the input blocks report {0} within {1:.6%} of each '
                        'other, which is one host class: {2}'.format(
                            field, spread, described))
            else:
                problem(problems, ERROR,
                        'the input blocks do not agree about {0}: {1}'.format(
                            field, described))
        if absent:
            # `host.instance` was added with the host-class rule on
            # 2026-09-10, so blocks 0-2 record CPU, cores, memory and hostname
            # and not the instance type the rule turns on.  Said out loud: an
            # absent check reads as one that passed.
            problem(problems, NOTE, '{0} is not recorded for {1}'.format(
                field, ', '.join(absent)))

    for key, entry in review['blocks'].items():
        for image, facts in ((blocks.get(key) or {}).get('docker') or {}).get(
                'bgperf_images', {}).items():
            review['images'].setdefault(image, {})[key] = facts.get('id')
    for image, ids in sorted(review['images'].items()):
        # Named before the agreement is read, on the rule the host-class check
        # two loops up follows: an absent check reads as one that passed.  A
        # tag recorded by two passes of three tells you nothing about the
        # third, and "identical in every block" counted it as agreeing.
        unrecorded = sorted(key for key in review['blocks'] if key not in ids)
        if unrecorded:
            problem(problems, NOTE,
                    '{0} has no recorded image id in {1}, so those blocks say '
                    'nothing about whether it moved'.format(
                        image, ', '.join(unrecorded)))
        distinct = set(ids.values())
        if len(distinct) == 1 and not unrecorded:
            continue
        for series in ALL_SERIES:
            keys = [entry['block'] for entry in series['passes']]
            within = {key: ids[key] for key in keys if key in ids}
            if len(set(within.values())) > 1:
                problem(problems, ERROR,
                        '{0}: {1} is a different image in different passes '
                        '({2}); those passes did not measure one binary'.format(
                            series['name'], image,
                            ', '.join('{0}={1}'.format(block, value)
                                      for block, value in sorted(within.items()))))
        if len(distinct) > 1:
            problem(problems, NOTE, '{0} differs between blocks: {1}'.format(
                image, ', '.join('{0}={1}'.format(block, value)
                                 for block, value in sorted(ids.items()))))
    return review


def host_memory_spread(field, values):
    '''How far apart the recorded memories are, or None for any other field.'''
    if field != 'memory_total_kb':
        return None
    numbers = [value for value in values.values()
               if isinstance(value, (int, float)) and not isinstance(value, bool)]
    if len(numbers) < 2 or min(numbers) <= 0:
        return None
    return (max(numbers) - min(numbers)) / float(min(numbers))


def rejected_rows(run_root, problems):
    '''Every row an accepted block excluded, by block and run name.

    The plan expands a comparison "only when all existing rows pass
    qualification", so a selection naming a cell that was excluded from one of
    its own passes is refused.  Read from the verdicts in the block's evidence
    documents, which is where `check_timing_evidence.py` wrote them -- not
    from a count of failed checker calls, which is 1 for a block of fourteen
    whether one row was rejected or all of them.
    '''
    # Three views of one fact, and each is needed: the two lookups are keyed
    # by tuples, `records` is the same thing in a shape `json.dump` accepts,
    # and `listed` is what a reader reads.
    excluded = {'by_artifact': {}, 'by_name': {}, 'listed': [], 'records': []}
    for key in INPUT_BLOCKS:
        for path in sorted(glob.glob(os.path.join(run_root, key, 'evidence',
                                                  '*.json'))):
            label = os.path.basename(path)[: -len('.json')]
            # An unreadable verdict is not an absent one, which is the rule
            # `block_exclusion_report` states in the runner. Here it decides
            # whether a selection may be validated at all: exclusions read
            # from a directory with an unreadable document are exclusions that
            # may be incomplete.
            document = read_json(path, problems,
                                 'a verdict document could not be read, so '
                                 'this block\'s exclusions are not known')
            if document is None:
                continue
            for run in document.get('runs') or []:
                if run.get('verdict') == 'qualified':
                    continue
                verdict = run.get('verdict') or 'no verdict'
                name = run.get('run') or 'unnamed'
                artifact = run.get('artifact')
                # Keyed by the artifact where the document names one, because
                # a run name is not a cell: the screen's peer sweep rejected
                # `bird 2.19.2` at 500 peers and qualified it at 50 and 250,
                # and an exclusion keyed on the name alone would refuse an
                # expansion of the two cells that were never in question.
                if artifact:
                    excluded['by_artifact'][(key, label, artifact)] = verdict
                else:
                    excluded['by_name'].setdefault((key, label, name),
                                                   []).append(verdict)
                excluded['records'].append({
                    'block': key, 'label': label, 'run': name,
                    'artifact': artifact, 'verdict': verdict})
                excluded['listed'].append('{0}/{1}: {2} ({3}): {4}'.format(
                    key, label, name, artifact or 'no artifact named', verdict))
    return excluded


def exclusion_for(excluded, block, results, artifact, name):
    '''Why this cell's row in this pass was excluded, or None.

    Falls back to the run name only where the block's evidence document named
    no artifact, which is what a document written before that field existed
    looks like. Kept as a fallback rather than a first choice, for the reason
    `RowIndex` was built: a name is shared by every cell of a swept axis.
    '''
    verdict = excluded['by_artifact'].get((block, results, artifact))
    if verdict:
        return verdict
    verdicts = excluded['by_name'].get((block, results, name))
    return '; '.join(verdicts) if verdicts else None


def selection_prospect(cells, resolution):
    '''Whether the comparison a selection names is resolvable at all.

    Judged on the cells the selection names, not on each cell's whole group.
    A cell can sit inside the resolution of some *other* daemon's median and
    still be 27s from the cell it is being compared with -- `bird 2.19.2` is
    1s from `frr_c 10.0` and 27s from `bird 3.3.2 (default threads)` -- and
    refusing that expansion in the name of a cell the selection never mentions
    is the group-wide claim answering a question nobody asked.

    The widest pair, not the narrowest: a three-cell comparison where two
    cells happen to agree is still worth expanding for the third.

    **Only cells that have a dispersion**, which is the same rule
    `expansion_prospect()` applies to a rival and for the same reason: a
    median from one observation is provisional, and refusing an expansion on
    the strength of it refuses exactly the passes that would settle it.  Every
    BIRD screen cell is one observation by design, so without this the three
    scenarios Block 10 is *for* were judged on single readings -- and passed
    only because their gaps happen to be large.
    '''
    known = [(cell['description'], cell.get('median')) for cell in cells
             if cell.get('median') is not None and cell.get('stdev') is not None]
    if len(known) < 2:
        return None
    gaps = []
    for index, (described, median) in enumerate(known):
        for other_described, other_median in known[index + 1:]:
            gaps.append((round_like_the_rule(abs(other_median - median)),
                         described, other_described))
    gap, one, two = max(gaps)
    if gap > resolution:
        return None
    return ('its widest pair is {0} apart ({1} against {2}), inside the {3} '
            'resolution of {4} -- no dispersion separates any pair here, and '
            'only a moved median could'.format(gap, one, two, resolution,
                                               DECISION_METRIC))


def validate_selection(document, reviews, excluded, problems, attempted=None):
    '''Check the operator's Block 10 selection against what the passes measured.

    The plan's exit criterion for this block is that "every optional
    repetition has a named hypothesis and variance reason, or the campaign
    advances with no optional repeats", and its statistical contract adds two
    conditions on any expansion: all existing rows of the comparison passed
    qualification, and observed variance could change the decision.  Those are
    checkable against documents that already exist, so they are checked here
    rather than trusted -- an expansion is hours of measurement, and a
    selection nobody can argue with is how a benchmark becomes a search for
    the expected answer.

    What it does not check is the *hypothesis*.  That it is present, named and
    written down is mechanical; whether it is a good one is the review.
    '''
    if document.get('schema') != SELECTION_SCHEMA:
        problem(problems, ERROR, 'the selection is not {0}: {1!r}'.format(
            SELECTION_SCHEMA, document.get('schema')))
        return
    for field in ('decided_utc', 'decided_by'):
        if not str(document.get(field) or '').strip():
            problem(problems, ERROR, 'the selection has no {0}'.format(field))

    by_series = {review['series']: review for review in reviews}
    repetitions = document.get('repetitions')
    if not isinstance(repetitions, list):
        problem(problems, ERROR, 'the selection has no `repetitions` list')
        return
    if not repetitions and not str(
            document.get('no_repetitions_reason') or '').strip():
        # "or the campaign advances with no optional repeats" is a decision,
        # and a decision with no reason beside it is indistinguishable from
        # the block never having been reviewed.
        problem(problems, ERROR,
                'the selection asks for no repetitions and gives no '
                '`no_repetitions_reason`')

    seen = set()
    for entry in repetitions:
        if not isinstance(entry, dict):
            problem(problems, ERROR,
                    'a selected repetition is {0}, not an object: {1!r}'.format(
                        type(entry).__name__, entry))
            continue
        name = str(entry.get('id') or '').strip()
        if not name:
            problem(problems, ERROR, 'a selected repetition has no `id`')
            continue
        if name in seen:
            problem(problems, ERROR, 'two selected repetitions are called {0!r}'
                    .format(name))
        seen.add(name)
        for field in ('hypothesis', 'variance_reason'):
            if not str(entry.get(field) or '').strip():
                problem(problems, ERROR, '{0}: no {1}'.format(name, field))
        review = by_series.get(entry.get('series'))
        if review is None:
            # A series that was read and dropped for a fault has already
            # reported why. Calling it unknown as well is a second error that
            # reads as a bad selection document -- and the false one looks the
            # more actionable, which is the thing this keeps getting wrong.
            named = entry.get('series')
            problem(problems, ERROR, '{0}: {1}'.format(name,
                    '{0!r} was not reviewed; see its error above'.format(named)
                    if named in (attempted or set())
                    else '{0!r} is not a reviewed series'.format(named)))
            continue
        known = {cell['description']: cell for cell in review['cells']}
        cells = entry.get('cells') or []
        if not cells:
            problem(problems, ERROR, '{0}: names no cells'.format(name))
        # The cells that resolved, counted before the per-cell guards: gating
        # those on the raw list let one misspelled name turn a single-cell
        # selection into a two-cell one, skipping the very check the rule is
        # there to make while reporting only the typo.
        resolved = [described for described in cells if described in known]
        for described in cells:
            cell = known.get(described)
            if cell is None:
                problem(problems, ERROR, '{0}: {1!r} is not a cell of {2}'
                        .format(name, described, review['series']))
                continue
            prospect = cell.get('expansion')
            if (len(resolved) == 1 and prospect
                    and not prospect.get('dispersion_could_decide')):
                # A selection naming one cell is a comparison against that
                # cell's own group, which is what the prospect is a claim
                # about. Where it names several, the comparison is between
                # them and is judged below -- deliberately, and it is worth
                # saying because it looks like a hole: a cell whose group-wide
                # prospect is `false` can be selected against a *named* cell
                # that has no dispersion, and nothing refuses it. That is the
                # right answer. A cell with no dispersion has one observation
                # -- by design for every screen cell -- and the passes being
                # asked for are exactly what would give it one, so refusing on
                # the strength of its provisional median refuses the
                # measurement that would settle it.
                problem(problems, ERROR,
                        '{0}: {1} is not separated from the cells drawn beside '
                        'it by any dispersion more passes could produce -- {2}'
                        .format(name, described, prospect['reason']))
            for entry_pass in cell['passes']:
                verdict = exclusion_for(excluded, entry_pass['block'],
                                        entry_pass['results'],
                                        entry_pass['artifact'], cell['name'])
                if verdict:
                    problem(problems, ERROR,
                            '{0}: {1} was {2} in {3}, so this comparison\'s '
                            'existing rows do not all pass qualification'.format(
                                name, described, verdict, entry_pass['block']))
        if (review.get('scope') == 'matrix' and known
                and len(set(cells)) >= len(known)):
            # "Never expand the entire matrix automatically."  A selection
            # that names every cell of the canonical matrix is that expansion
            # wearing a hypothesis, and it is the one shape of selection this
            # campaign rules out in advance.  A screen scenario is exempt
            # because its three cells are one comparison -- refusing it would
            # forbid the repetitions the plan asks this block to select.
            problem(problems, ERROR,
                    '{0}: names every cell of {1}; the plan forbids expanding '
                    'the whole matrix'.format(name, review['series']))
        # The plan's second condition -- "observed variance could change the
        # decision" -- read against the comparison this selection names.
        #
        # Only where the comparison is about the metric the rule is computed
        # on. A selection may declare its own (`metric: reload_s`), and the
        # BIRD reload scenario is exactly that: `summary.py` computes the
        # variance rule on `elapsed (s)` alone, so a policy-reload comparison
        # refused on its elapsed medians would be refused on a number it was
        # never about.
        measured_by = entry.get('metric') or DECISION_METRIC
        if measured_by == DECISION_METRIC:
            unresolvable = selection_prospect(
                [known[described] for described in resolved],
                METRIC_RESOLUTION.get(DECISION_METRIC, 0.0))
            if unresolvable:
                problem(problems, ERROR, '{0}: {1}'.format(name, unresolvable))

        observed = len(review['passes'])
        requested = entry.get('passes_requested')
        if not isinstance(requested, int) or isinstance(requested, bool):
            problem(problems, ERROR, '{0}: `passes_requested` is not a number'
                    .format(name))
        elif requested <= observed:
            problem(problems, ERROR,
                    '{0}: asks for {1} passes and {2} already ran, so it adds '
                    'no observation'.format(name, requested, observed))
        elif requested > EXPANSION_PASSES:
            problem(problems, ERROR,
                    '{0}: asks for {1} passes; the plan stops at {2}, where an '
                    'unseparated pair is a result rather than a sixth '
                    'pass'.format(name, requested, EXPANSION_PASSES))

    for entry in document.get('declined') or []:
        if not str(entry.get('reason') or '').strip():
            problem(problems, ERROR, 'a declined comparison ({0!r}) has no reason'
                    .format(entry.get('id')))


def shared_suffix(descriptions):
    """The axes every cell of a series has in common, at a `, ` boundary.

    Fourteen cells of one canonical pass differ only in their target, so
    `batch_cell_description()` gives fourteen strings that agree for their
    last forty characters -- and a table truncated to fit them shows the part
    they agree about. The suffix is printed once above the table instead. A
    screen scenario that sweeps an axis has a shorter one, which is the axis
    it sweeps staying in the labels where it belongs.
    """
    if len(descriptions) < 2:
        return ''
    first = descriptions[0]
    for cut in range(len(first)):
        candidate = first[cut:]
        if candidate.startswith(', ') and all(
                other.endswith(candidate) for other in descriptions):
            return candidate
    return ''


# The decomposition, in the order a run produces it, with the column names the
# artifacts use shortened only for the table's width.
# The columns whose individual readings are worth having in the text report
# as well as in the document. `max mem (GB)` is here because this campaign has
# one bimodal cell -- `frr_c 10.7` measured 6.284, 5.772 and 5.717 GB, two
# clusters rather than a spread -- and a median with a coefficient of
# variation beside it describes neither mode.
OBSERVATION_COLUMNS = (('elapsed (s)', 'elapsed'),
                       ('max cpu %', 'cpu'),
                       ('max mem (GB)', 'mem'),
                       ('min free mem (GB)', 'free'))

DECOMPOSITION = (('first_prefix_s', 'first prefix'),
                 ('injection_s', 'injection'),
                 ('offered_in_interval', 'offered'),
                 ('post_injection_tail_s', 'post tail'),
                 ('convergence_s', 'convergence'),
                 ('assurance_s', 'assurance'),
                 ('delivery_complete_s', 'delivery'))


def render_series(review):
    """The series as a reader reads it: one row per cell, statistics beside it."""
    lines = ['{0} -- {1}'.format(review['series'], review['workload'])]
    for entry in review['passes']:
        lines.append('  pass {0}: {1} ({2}, {3} order, seed {4}, {5} rows)'.format(
            entry['repetition'], entry['block'], entry['test'], entry['order'],
            entry['seed'], entry['rows']))
    descriptions = [record['description'] for record in review['cells']]
    suffix = shared_suffix(descriptions)
    labels = {record['ordinal']: (record['description'][:-len(suffix)]
                                  if suffix else record['description'])
              for record in review['cells']}
    width = max([len(label) for label in labels.values()] + [4])
    if suffix:
        lines.append('  every cell{0}'.format(suffix))
    cells = {cell['cell']: cell for cell in review['summary']['cells']}
    row = '  {0:<' + str(width) + '} {1:>2} {2:>8} {3:>13} {4:>7}  {5:<26} {6:<11} {7}'
    lines.extend(['', row.format('cell', 'n', 'median', 'min-max', 'CV%',
                                 'variance ({0})'.format(DECISION_METRIC),
                                 'positions', 'order')])
    for record in review['cells']:
        cell = cells.get(record['ordinal']) or {}
        metric = (cell.get('metrics') or {}).get(DECISION_METRIC) or {}
        variance = cell.get('variance') or {}
        verdict = variance.get('verdict') or 'no verdict'
        if verdict == EXPAND and variance.get('passes_recommended'):
            verdict = '{0} to {1}'.format(verdict, variance['passes_recommended'])
        lines.append(row.format(
            labels[record['ordinal']], cell.get('observations', 0),
            _number(metric.get('median')),
            '{0}-{1}'.format(_number(metric.get('min')), _number(metric.get('max'))),
            _percent(metric.get('cv_percent')), verdict[:26],
            '/'.join(str(entry['position']) for entry in record['passes']),
            record['order_relation']))

    lines.extend(['', '  medians of the decomposition, null where the run '
                  'published none:', ''])
    column = '  {0:<' + str(width) + '} {1}'
    lines.append(column.format('cell', ' '.join(
        '{0:>12}'.format(shown) for _, shown in DECOMPOSITION)))
    for record in review['cells']:
        lines.append(column.format(labels[record['ordinal']], ' '.join(
            '{0:>12}'.format(_number(
                (record['intervals'].get(name) or {}).get('median'),
                count=(name == 'offered_in_interval')))
            for name, _ in DECOMPOSITION)))
    short = ['{0}.{1} (n={2} of {3})'.format(
        labels[record['ordinal']], name,
        (record['intervals'].get(name) or {}).get('n'), len(review['passes']))
        for record in review['cells'] for name, _ in DECOMPOSITION
        if 0 < ((record['intervals'].get(name) or {}).get('n') or 0)
        < len(review['passes'])]
    if short:
        # A median printed from one pass of three looks exactly like a median
        # printed from three. `summary.py` refuses to shrink an `n` in
        # silence; the JSON here carries `by_pass`, and this is the text
        # report saying the same thing.
        lines.append('  fewer observations than passes: {0}'.format(
            ', '.join(short)))

    nothing_crossed = [labels[record['ordinal']] for record in review['cells']
                       if (record['intervals'].get('offered_in_interval')
                           or {}).get('median') == 0]
    if nothing_crossed:
        # Said rather than left to be read out of a zero. `findings.py`
        # refuses these rows for the same reason, by name.
        lines.append('  injection_s spans an interval nothing crossed on {0} '
                     'cell(s), so it is not a send time'.format(
                         len(nothing_crossed)))

    for record in review['cells']:
        if record['workload']:
            lines.append('  {0}: {1}'.format(labels[record['ordinal']], ', '.join(
                '{0} median {1}'.format(name, _number(stats.get('median')))
                for name, stats in sorted(record['workload'].items()))))
        if record['churn']:
            lines.append('  {0}: {1}'.format(labels[record['ordinal']], ', '.join(
                '{0} median {1} over {2} burst(s)'.format(
                    name, _number(record['churn'][name].get('median')),
                    record['churn'][name].get('n'))
                for name in ('withdraw_s', 'reannounce_s'))))
    lines.extend(['', '  every observation, pass by pass -- a statistic over '
                  'a bimodal cell describes neither mode:', ''])
    for record in review['cells']:
        cell = cells.get(record['ordinal']) or {}
        metrics = cell.get('metrics') or {}
        lines.append(column.format(labels[record['ordinal']], '  '.join(
            '{0} {1}'.format(shown, '/'.join(
                _number(value) for value in (metrics.get(name) or {}).get('values') or []))
            for name, shown in OBSERVATION_COLUMNS)))

    undecidable = [labels[record['ordinal']] for record in review['cells']
                   if record['expansion']
                   and not record['expansion']['dispersion_could_decide']]
    if undecidable:
        lines.extend(['', '  no dispersion separates these from their nearest '
                      'rivals -- the gap is inside the {0}s resolution of {1}, '
                      'so only a moved median could: {2}'.format(
                          review['metric_resolution'], DECISION_METRIC,
                          ', '.join(undecidable))])

    lines.append('')
    lines.append('  order effects: {0}'.format(', '.join(
        '{0} {1}'.format(count, relation) for relation, count
        in sorted(review['order_effects']['relations'].items()))))
    lines.append('  {0}'.format(review['order_effects']['basis']))
    lines.append('  limiting component: {0}'.format(', '.join(sorted(
        {str(record['limiting_component']) for record in review['cells']}))))
    return lines


def _percent(value):
    return 'null' if value is None else '{0:.2f}'.format(value)


def _number(value, count=False):
    if value is None:
        return 'null'
    if count:
        return '{0:,.0f}'.format(value)
    return '{0:g}'.format(value)


def render_blocks(review):
    lines = ['input blocks']
    for key, entry in sorted(review['blocks'].items()):
        host = entry['host'] or {}
        lines.append('  {0:<34} {1:<10} {2} / {3} / {4} threads / {5} kB{6}'.format(
            key, 'accepted' if entry['accepted'] else 'NOT ACCEPTED',
            dig(host, ('instance', 'id')) or host.get('hostname') or '?',
            host.get('cpu_model') or '?', host.get('cpu_threads') or '?',
            host.get('memory_total_kb') or '?',
            '' if not entry['previous_hosts']
            else ' ({0} earlier attempt(s))'.format(len(entry['previous_hosts']))))
    everywhere = [image for image, ids in review['images'].items()
                  if len(ids) == len(review['blocks'])]
    agreed = sum(1 for image in everywhere
                 if len(set(review['images'][image].values())) == 1)
    lines.append('  images identical in every block: {0} of the {1} recorded '
                 'in all {2} blocks ({3} image(s) in total)'.format(
                     agreed, len(everywhere), len(review['blocks']),
                     len(review['images'])))
    return lines


def write_json(path, document):
    '''Strict JSON, for the reason `write_batch_summary()` is strict.

    `allow_nan=False`: a non-finite value written as a bare `NaN` is rejected
    by jq and by most non-Python parsers, which turns a readable document into
    an unreadable one at the moment somebody tries to check the arithmetic.
    '''
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(document, f, indent=2, sort_keys=True, default=str,
                  allow_nan=False)
        f.write('\n')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--run-root',
                        default=os.path.join('results', '2026',
                                             '2026-timing-validation'),
                        help='the campaign run root holding the blocks')
    parser.add_argument('--out', help='directory to write the review into')
    parser.add_argument('--selection',
                        help='the Block 10 selection document to validate; '
                             'its absence is an error, because the block is '
                             'not reviewed until the selection is written')
    parser.add_argument('--series', action='append',
                        help='review only this series (repeatable)')
    args = parser.parse_args(argv)

    problems = []
    if args.out:
        # Before any check runs, not after they all pass. `run_variance_review`
        # removes this directory and regenerates it, and the runner's messages
        # name it -- so an exception anywhere below used to leave the operator
        # pointed at a directory that had been deleted and never recreated.
        # The transcript under `metadata/` holds the traceback either way; this
        # makes the named directory exist to be looked in.
        os.makedirs(args.out, exist_ok=True)
    unavailable = unsampled_row_values()
    wanted = set(args.series or [])
    reviews, attempted = [], set()
    for series in ALL_SERIES:
        if wanted and series['name'] not in wanted:
            continue
        # Attempted, not succeeded: a series dropped because its documents
        # could not be read has already reported why, and naming it again as
        # one that does not exist is a second, false error beside the true
        # one -- and the false one looks the more actionable.
        attempted.add(series['name'])
        review = review_series(args.run_root, series, unavailable, problems)
        if review is not None:
            reviews.append(review)
    if wanted:
        for name in sorted(wanted - attempted):
            problem(problems, ERROR, 'no such series: {0}'.format(name))

    blocks = review_blocks(args.run_root, problems)
    excluded = rejected_rows(args.run_root, problems)

    if args.selection:
        if not os.path.isfile(args.selection):
            # The plan asks for the selection to be written "to durable
            # metadata before running more", so its absence is the block's
            # exit criterion unmet rather than an optional check skipped.
            problem(problems, ERROR,
                    'no selection document at {0}; Block 10 may not be '
                    'planned until one is written'.format(args.selection))
        else:
            document = read_json(args.selection, problems,
                                 'the selection document is not readable JSON')
            if document is not None:
                validate_selection(document, reviews, excluded, problems,
                                   attempted=attempted)

    lines = []
    for review in reviews:
        lines.extend(render_series(review))
        lines.append('')
    lines.extend(render_blocks(blocks))
    lines.append('')
    if excluded['listed']:
        lines.append('rows excluded by an accepted block, which may not '
                     'support an expansion:')
        for entry in excluded['listed']:
            lines.append('  {0}'.format(entry))
        lines.append('')
    errors = [entry for entry in problems if entry['severity'] == ERROR]
    for entry in problems:
        lines.append('{0}: {1}'.format(entry['severity'], entry['message']))
    lines.append('')
    lines.append('{0} series reviewed, {1} error(s), {2} note(s)'.format(
        len(reviews), len(errors), len(problems) - len(errors)))
    text = '\n'.join(lines)
    print(text)

    if args.out:
        for review in reviews:
            write_json(os.path.join(args.out, '{0}.json'.format(review['series'])),
                       review)
        write_json(os.path.join(args.out, 'blocks.json'), blocks)
        write_json(os.path.join(args.out, 'problems.json'),
                   {'schema': REVIEW_SCHEMA, 'problems': problems,
                    'excluded_rows': excluded['records']})
        with open(os.path.join(args.out, 'review.txt'), 'w',
                  encoding='utf-8') as f:
            f.write(text + '\n')
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
