#
# Copyright (C) 2015, 2016 Nippon Telegraph and Telephone Corporation.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.


"""Pure batch matrix construction and legacy identity; no runtime imports."""

import hashlib
import json
import yaml

from churn import DEFAULT_CHURN_PREFIXES, DEFAULT_CHURN_BURSTS
from policy import DEFAULT_POLICY_RELOAD_BLOCKS

# How many peers announce each block of prefixes. 1 is what bgperf has always
# generated: every peer takes its own block off the shared iterator, so the
# peers are disjoint and the table is `n * p`. Above 1 the peers are grouped and
# every peer in a group announces the *same* block, so the target holds that
# many competing paths for each of those prefixes and has to select between
# them -- which is the work `n * p` disjoint prefixes never asks it to do.
DEFAULT_PATH_DIVERSITY = 1
# How many receive-only sessions the target exports its table to, beside the
# monitor. 0 is every run bgperf has ever made: one table in, one session out,
# so the cost of exporting a table and the cost of receiving one are a single
# number that nothing downstream can separate. Each receiver is one more copy
# of the RIB-out for the target to build, encode and send, and it announces
# nothing -- so the ingress side of the run is untouched by how many there are.
DEFAULT_RECEIVERS = 0
# The instrument every row before Phase 7 was measured with. A run on it is
# named and identified exactly as before the flag existed, so every existing
# stem and cell id resumes. Deliberately a constant of its own, not
# DEFAULT_MONITOR: the default is now the sink, and if the omission followed it,
# a sink cell would take the old unmarked name and every GoBGP cell measured
# before the flip would be renamed to something no artifact on disk carries.
UNMARKED_MONITOR = 'gobgp'

# How `-p/--prefix-num` is read. `per-peer` is what bgperf has always meant by
# it, and multiplies: `-n 50 -p 100000` is five million routes. `total` reads it
# as the whole table and splits it across the sessions.
PREFIX_SCOPES = ('per-peer', 'total')

# Generators that play back an MRT file rather than synthesising prefixes. For
# these `-p` is already the size of the whole table -- `gen_conf()` sets the
# monitor check-point from it directly rather than multiplying -- so a scope
# has nothing to divide and asking for one is a mistake worth naming.
MRT_TESTER_TYPES = ('bgpdump2',)

# Every generator `-g` accepts, and the single source for the CLI's `choices`.
# `gen_conf()` branches on `not in ('exa', 'bird')` rather than on
# MRT_TESTER_TYPES, so an unrecognised value is treated as an MRT injector: a
# typo'd `tester_type: brid` on a batch target -- which bypasses argparse
# entirely -- reached that branch and died at its bare `exit(1)`, taking the
# rest of the matrix with it.
SYNTHETIC_TESTER_TYPES = ('exa', 'bird')
TESTER_TYPES = SYNTHETIC_TESTER_TYPES + MRT_TESTER_TYPES


def resolve_prefix_scope(scope, neighbor_num, prefix_num, tester_type=None):
    """The per-peer prefix count a run should generate, from what was asked for.

    Sessions and table size are one axis today, and that is the gap this
    closes. `gen_conf()` gives every neighbour its own `gen_paths(p)` off a
    shared iterator, so the peers get disjoint prefixes and the table is
    `n * p`: a batch sweeping `neighbors: [10, 25, 50]` at a fixed `prefixes`
    is sweeping the table size at the same time, and nothing downstream can
    separate "50 sessions were slower" from "five times the routes were
    slower". `2026-core-synth.yaml` is exactly this shape -- its four cells
    hold 500k, 1M, 2.5M and 5M routes.

    Under `total` the peer count moves and the table does not. The result is
    normalised to a per-peer count here, before anything reads it, because
    `-n 50 -p 100000 --prefix-scope total` and `-n 50 -p 2000` are the same
    workload and must produce the same row: the CSV column is called
    `prefixes per peer`, `bench_output_prefix()` names artifacts from
    `prefix_num`, and `create_graph()` groups bars by it. A scope that
    survived into those would have to be a new dimension in all three.

    The division has to be exact, and an inexact one is refused rather than
    rounded or spread. A remainder means the peers do not all offer the same
    table, so `prefixes per peer` is a number that is not true of any of them,
    each neighbour's `check-points` differs, and the monitor's own check-point
    stops being `n * p`. Refusing costs a message before the first container;
    the alternative is a column that quietly means something else for those
    rows.
    """
    if scope in (None, 'per-peer'):
        return prefix_num
    if scope not in PREFIX_SCOPES:
        raise ValueError("unknown prefix scope '{0}': expected one of {1}".format(
            scope, ', '.join(PREFIX_SCOPES)))
    if tester_type in MRT_TESTER_TYPES:
        raise ValueError(
            "--prefix-scope total does not apply to the '{0}' tester: it plays "
            'back an MRT file, so -p is already the whole table and there is '
            'nothing to divide across the peers'.format(tester_type))
    if neighbor_num < 1:
        raise ValueError('--prefix-scope total needs at least one peer to '
                         'divide the table across, got {0}'.format(neighbor_num))
    if prefix_num < neighbor_num:
        raise ValueError(
            '--prefix-scope total: {0} prefixes across {1} peers leaves peers '
            'with none. A session that offers nothing is not a peer under '
            'test'.format(prefix_num, neighbor_num))
    if prefix_num % neighbor_num:
        per_peer = prefix_num // neighbor_num
        # Prefix counts always -- both are exact by construction. Peer counts
        # only where a usable one exists, since a table with no divisor near
        # the asked-for count has nothing to offer and saying so is better
        # than naming one nobody would run.
        peers = _divisors_near(prefix_num, neighbor_num)
        advice = "use {0} or {1} prefixes".format(
            per_peer * neighbor_num, (per_peer + 1) * neighbor_num)
        if peers:
            advice += ', or {0} peers'.format(
                ' or '.join(str(n) for n in peers))
        raise ValueError(
            '--prefix-scope total: {0} prefixes do not divide evenly across '
            '{1} peers ({2} each, {3} left over). An uneven split makes the '
            "CSV's `prefixes per peer` untrue of every peer; {4}".format(
                prefix_num, neighbor_num, per_peer, prefix_num % neighbor_num,
                advice))
    return prefix_num // neighbor_num


# How far *above* the asked-for peer count the search will look -- a distance,
# not an absolute ceiling. Only the upward half needs bounding: the scan
# otherwise walked to `prefix_num` itself, offering five million peers after a
# fifth of a second of searching, and a suggestion far above what the operator
# asked for is not one whatever it costs. Downward it is already bounded by the
# asked-for count, and a divisor below that is by construction a number the
# operator was willing to be near -- 1443 for someone who asked for 1500 is
# useful advice, so it is deliberately not capped.
MAX_SUGGESTED_PEERS = 512


def _is_positive_count(value):
    """A whole number of 1 or more, the one rule both entry points apply.

    `True` is an `int` in Python and is not a peer count.
    """
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _divisors_near(prefix_num, neighbor_num):
    """Peer counts closest to the one asked for that divide this table.

    A message that only says the division failed leaves the operator doing
    arithmetic on a 1,050,000-prefix RIB; a workable number either side is the
    whole fix. One peer is excluded for the same reason a five-million-peer
    suggestion is: a suggestion the operator cannot act on is worse than none,
    because it reads as the tool having thought about it.
    """
    # Never past two prefixes per peer, at either end: a peer count equal to
    # the table size divides it exactly and offers each session a single
    # route, which is the same kind of unusable advice as suggesting five
    # million peers, and the next divisor down is the first that is not.  Only
    # reachable on a table small enough to be within MAX_SUGGESTED_PEERS of
    # the asked-for count.
    most = prefix_num // 2
    below = next((n for n in range(min(neighbor_num - 1, most), 1, -1)
                  if prefix_num % n == 0), None)
    # A distance above the asked-for count, not an absolute cap: an absolute
    # one offers nothing at all to anybody who asked for more than it, so a
    # 513-peer request got no upward suggestion even though 625 divides.
    ceiling = min(most, neighbor_num + MAX_SUGGESTED_PEERS)
    above = next((n for n in range(neighbor_num + 1, ceiling + 1)
                  if prefix_num % n == 0), None)
    return [n for n in (below, above) if n]



def cell_monitor(cell):
    '''The monitor a batch cell, or a parsed cell id, was measured with.

    A cell id omits `monitor` on UNMARKED_MONITOR, so an absent key is that
    instrument and never DEFAULT_MONITOR. Now that the default is the sink,
    reading it as the default would describe every GoBGP cell measured before
    7d -- in `timing_variance_review.py`, which reads parsed ids -- as a sink
    cell.
    '''
    return cell.get('monitor') or UNMARKED_MONITOR


def construct_batch_cells(test, targets, *, repetitions, prefix_resolver,
                          path_diversity, receivers, churn_prefixes,
                          churn_bursts, policy_reload_blocks, pin, monitor):
    """Construct cells from caller-validated and resolved workload controls.

    Defaults and argument guards remain at the existing batch entry point.
    This constructor is shared with the restricted declarative recipe reader.
    """
    scope = test.get('prefix_scope')
    diversity = path_diversity
    reload_blocks = policy_reload_blocks
    cells = []
    for repetition in range(1, repetitions + 1):
        ordinal = 0
        for n in test['neighbors']:
            for p in test['prefixes']:
                for filter_test in test['filter_test']:
                    for t in targets:
                        cells.append({
                            'repetition': repetition if repetitions > 1 else None,
                            'ordinal': ordinal,
                            'neighbors': n,
                            # The per-peer count, resolved here rather than
                            # carried as a scope: `-n 50 -p 100000` under
                            # `total` and `-n 50 -p 2000` are the same
                            # workload, so they must produce the same cell
                            # identity, the same row, the same artifact names
                            # and the same bar. `check_batch_test()` has
                            # already refused an inexact division.
                            'prefixes': prefix_resolver(scope, n, p),
                            'filter': filter_test,
                            'path_diversity': diversity,
                            'receivers': receivers,
                            'churn_prefixes': churn_prefixes,
                            'churn_bursts': churn_bursts,
                            'policy_reload_blocks': reload_blocks,
                            'pin': pin,
                            'monitor': monitor,
                            'target': t,
                        })
                        ordinal += 1
    return cells


def batch_cell_id(test_name, cell):
    """Return a stable, human-inspectable identity for one batch matrix cell.

    Keyed by what the cell is, never by when it ran: `ordinal` is its position
    within one pass over the matrix and `repetition` says which pass, so
    resume keeps matching when the execution order changes and two passes of
    one cell are told apart by the one field that differs.

    A single-pass test carries no `repetition` key at all, which is what a cell
    id looked like before repetitions existed. That is deliberate: an in-flight
    batch written by an older build resumes exactly as it did, instead of
    finding no id it recognises and silently re-running hours of finished work.
    """
    identity = {
        'test': test_name,
        'ordinal': cell['ordinal'],
        'neighbors': cell['neighbors'],
        'prefixes': cell['prefixes'],
        'filter': cell['filter'],
        'target': cell['target'],
    }
    if cell['repetition'] is not None:
        identity['repetition'] = cell['repetition']
    # Omitted at the default for the same reason `repetition` is omitted for a
    # single-pass test: a disjoint cell's id keeps exactly the shape it had
    # before this flag existed, so an in-flight batch written by an older build
    # resumes instead of costing the operator every completed cell, and
    # `BATCH_PROGRESS_SCHEMA_VERSION` does not have to move.
    diversity = cell.get('path_diversity') or DEFAULT_PATH_DIVERSITY
    if diversity != DEFAULT_PATH_DIVERSITY:
        identity['path_diversity'] = diversity
    receivers = cell.get('receivers') or DEFAULT_RECEIVERS
    if receivers != DEFAULT_RECEIVERS:
        identity['receivers'] = receivers
    # Both keys or neither, and only away from the default: a burst count with
    # no block is not a workload, so recording one on a cell that churns
    # nothing would put a key in the id that says nothing about what ran.
    churn_prefixes = cell.get('churn_prefixes') or DEFAULT_CHURN_PREFIXES
    if churn_prefixes != DEFAULT_CHURN_PREFIXES:
        identity['churn_prefixes'] = churn_prefixes
        identity['churn_bursts'] = (cell.get('churn_bursts')
                                    or DEFAULT_CHURN_BURSTS)
    reload_blocks = (cell.get('policy_reload_blocks')
                     or DEFAULT_POLICY_RELOAD_BLOCKS)
    if reload_blocks != DEFAULT_POLICY_RELOAD_BLOCKS:
        identity['policy_reload_blocks'] = reload_blocks
    # Omitted when unpinned, on the rule above, so every existing id resumes.
    if cell.get('pin'):
        identity['pin'] = cell['pin']
    # Omitted on the instrument every existing id was measured with, on the
    # rule above, so every existing id resumes; see UNMARKED_MONITOR for why
    # that is not "omitted at the default".
    monitor = cell_monitor(cell)
    if monitor != UNMARKED_MONITOR:
        identity['monitor'] = monitor
    return json.dumps(identity, sort_keys=True, separators=(',', ':'), default=str)


def batch_cell_key(cell_id):
    """A short, filename-safe name for a cell id: the id itself is JSON."""
    return hashlib.sha256(cell_id.encode('utf-8')).hexdigest()[:16]


class BatchLoader(yaml.SafeLoader):
    '''YAML loader that leaves version-shaped scalars alone.

    Plain yaml reads `10.10` as the float 10.1, which would quietly bench FRR
    10.1 when the config asked for 10.10. Nothing in a batch config is
    legitimately a float, so dropping the implicit float resolver costs
    nothing and keeps versions as the strings they were written as.
    '''


BatchLoader.yaml_implicit_resolvers = {
    ch: [(tag, regexp) for tag, regexp in resolvers if tag != 'tag:yaml.org,2002:float']
    for ch, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}



def expand_target_versions(targets):
    '''Turn `versions: [8.0, 9.0]` on a target into one entry per version.

    Comparing releases is the common case, and writing them out by hand means
    repeating the whole target block -- including the image tag, which is the
    part that is easy to get wrong.
    '''
    expanded = []
    for t in targets:
        versions = t.get('versions') or [t.get('version')]
        for v in versions:
            entry = dict(t)
            entry.pop('versions', None)
            if v is None:
                entry.pop('version', None)
            else:
                # yaml turns 10.1 into a float and 10 into an int; both have to
                # survive as the string the tag was built from.
                entry['version'] = str(v)
                if 'label' not in t:
                    entry['label'] = '{0} {1}'.format(t['name'], v)
                elif len(versions) > 1:
                    # An explicit label on a multi-version entry would name every
                    # run the same thing: duplicate rows in the CSV, per-run PNGs
                    # overwriting each other, and create_graph() raising a shape
                    # mismatch because it de-duplicates labels but not data.
                    entry['label'] = '{0} {1}'.format(t['label'], v)
            expanded.append(entry)
    return expanded
