#!/usr/bin/env python3
# Copyright (C) 2026 bgperf2 contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

'''Does a repetition block run the comparison the campaign selected, and only that?

Two blocks have had their matrix decided by a *different* block, and both are
checked here. `metadata/block10-selection.json` was written between Block 9's
first reading of the statistics and the run that validates them, and names
three comparisons to repeat and seven to decline with reasons;
`metadata/block11-expansion.json` was written from Block 10's own pooled read
and expands exactly one of those three to five passes. The configs have to
execute exactly that, and "a block that ran the wrong matrix would produce
rows that look exactly like the right ones" is the whole reason the runner
refuses to improvise one.

So this reads the selection and the configs and refuses a mismatch, before any
container starts. It is not the variance review: it computes no statistic,
opens no results directory, and says nothing about whether the rows qualify.
It answers the narrower question the review cannot answer yet -- the review
needs the block's own passes to be COMPLETE, which they cannot be until after
the block it is guarding has run.

One script and one table rather than one script per block, deliberately. The
second block's guard is the first one with two names changed, and a copy of a
check is a check that stops being run against the block it was copied for --
the failure this repository keeps finding in its own documents.

Pure: no Docker and no results. Configs and one JSON document.
'''
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yaml  # noqa: E402

from bgperf2 import (BatchLoader, batch_cell_description,  # noqa: E402
                     batch_order, check_batch_run_names, check_batch_test,
                     expand_batch_cells, expand_target_versions)

# The campaign's mechanical order seed: the year with the block number
# appended, continuing 20268 from Block 8. Per block, because a repetition
# that re-ran its predecessor's permutation would apply one position bias
# twice more rather than averaging it out.
BLOCK_SEEDS = {10: 202610, 11: 202611}

# How many passes of a comparison each earlier block holds, and which block
# that is. A comparison's `prior` names the blocks its existing observations
# are in, so the count and the names come from one place -- a count on its own
# leaves an operator to work out which blocks it meant, and the two drifting
# apart is how a refusal message starts describing a different campaign.
PRIOR_BLOCK_PASSES = {
    'block8-bird-architecture-screen': 1,
    'block10-selected-repetitions': 2,
}
FIRST_PASS_BLOCK_NAME = 'block8-bird-architecture-screen'
REPETITION_BLOCK_NAME = 'block10-selected-repetitions'

# Pass 1 of every one of them, which is where the comparison's first
# observation came from.
FIRST_PASS_BLOCK = FIRST_PASS_BLOCK_NAME

# Which configs run which selection, and in which pass. This is the mapping the
# block executes; the selection document is the decision it executes. They are
# checked against each other rather than one being derived from the other,
# because a derived matrix is one nobody has to agree with.
#
# Two configs per selection, not three: Block 8 measured pass 1 of every screen
# scenario, and these are repetitions 2 and 3. `passes_requested` in the
# selection is the total, so the arithmetic is checked below rather than
# assumed.
# `first_pass` is Block 8's config for the same scenario, and `narrowed` names
# the keys this block is allowed to change against it. Everything else must be
# literally equal: the three passes are read as the dispersion of one cell, so
# a `tester_type` or a `threads` that drifted from pass 1 would be a difference
# in the thing measured arriving inside the statistic meant to measure
# run-to-run noise -- and comparing only the two configs here would never see
# it, because they drift together.
#
# `narrowed` is empty for two of the three. Only the peer sweep is repeated in
# part: the selection names the 250-peer cells and declines the 50- and
# 500-peer ones, so `neighbors` is the one key that may differ from Block 8's.
BLOCK10_CONFIGS = {
    'bird-session-scaling-250-peers': {
        'passes': (('2026-timing-bird-peers250-rep2', 2),
                   ('2026-timing-bird-peers250-rep3', 3)),
        'first_pass': '2026-timing-bird-peers',
        'narrowed': ('neighbors',),
    },
    'bird-competing-path-selection': {
        'passes': (('2026-timing-bird-diversity-rep2', 2),
                   ('2026-timing-bird-diversity-rep3', 3)),
        'first_pass': '2026-timing-bird-diversity',
        'narrowed': (),
    },
    'bird-policy-recalculation': {
        'passes': (('2026-timing-bird-reload-rep2', 2),
                   ('2026-timing-bird-reload-rep3', 3)),
        'first_pass': '2026-timing-bird-reload',
        'narrowed': (),
    },
}

# Block 11 expands one of those three and nothing else. Its two configs are
# passes 4 and 5, so three passes already exist rather than one -- one in
# Block 8 and two in Block 10 -- and each comparison's `prior` is what keeps
# the arithmetic honest about which.
#
# `first_pass` is still Block 8's config, not Block 10's. The five passes are
# read as the dispersion of one cell, and the pass every later one must match
# is the one that defined the cell; checking against repetition 3 instead
# would compare a copy with the copy it was made from, which is precisely the
# drift this comparison exists to catch.
BLOCK11_CONFIGS = {
    'bird-session-scaling-250-peers': {
        'passes': (('2026-timing-bird-peers250-rep4', 4),
                   ('2026-timing-bird-peers250-rep5', 5)),
        'first_pass': '2026-timing-bird-peers',
        'narrowed': ('neighbors',),
        # Per comparison, not per block. It is the same number for every
        # comparison in each of these two blocks, which is exactly why a block
        # constant looked right: a later block expanding `diversity` (3 prior)
        # while newly repeating `fanout` (1 prior) would check the second
        # against the first's history, in the accepting direction -- the
        # failure that replacing the literal `+ 1` was meant to prevent.
        'prior': (FIRST_PASS_BLOCK_NAME, REPETITION_BLOCK_NAME),
    },
}

BLOCK_PLANS = {
    10: {'configs': BLOCK10_CONFIGS},
    11: {'configs': BLOCK11_CONFIGS},
}

# What tells the passes apart rather than describing the workload. `name` is
# the artifact stem, and the seed is per block by the campaign's own rule.
PASS_KEYS = ('name', 'seed')

# What a selection document may call itself. Both names, for the reason
# `timing_variance_review.py` accepts both: Block 10's is on disk under the
# name the shape had when it was the only one, it is the record of a decision
# an accepted block carried out, and it is not rewritten to satisfy a rename.
SELECTION_SCHEMAS = ('bgperf2/campaign-selection/v1alpha1',
                     'bgperf2/block10-selection/v1alpha1')


def read_config(path):
    with open(path, 'r') as handle:
        document = yaml.load(handle, Loader=BatchLoader)
    tests = document.get('tests') or []
    if len(tests) != 1:
        raise ValueError('{0}: expected exactly one test, found {1}'.format(
            path, len(tests)))
    return tests[0]


def cells_of(test):
    '''The cells one config will run, described exactly as the selection
    names them -- `batch_cell_description()` is what produced the strings in
    the selection document, so the two cannot drift apart.'''
    check_batch_test(test)
    targets = expand_target_versions(test['targets'])
    check_batch_run_names(test, targets)
    return [batch_cell_description(cell)
            for cell in expand_batch_cells(test, targets)]


def mapping_without(test, keys=('name',)):
    return {key: value for key, value in test.items() if key not in keys}


def mapping_without_name(test):
    return mapping_without(test, ('name',))


def check(selection_path, config_dir, problems, block=10):
    block_configs = BLOCK_PLANS[block]['configs']
    if not os.path.isfile(selection_path):
        problems.append('no selection document at {0}; Block {1} may not run '
                        'until one is written'.format(selection_path, block))
        return
    try:
        with open(selection_path, 'r') as handle:
            document = json.load(handle)
    except (ValueError, OSError) as failure:
        problems.append('{0} is not readable JSON: {1}'.format(
            selection_path, failure))
        return
    if not isinstance(document, dict):
        problems.append('{0} is {1}, not an object'.format(
            selection_path, type(document).__name__))
        return

    # Ids are operator-written, so a missing or non-string one is reported
    # rather than being allowed to reach a `sorted()` that raises on the mix.
    # Everything below this function is the refusal it exists to print; a
    # traceback in its place is the refusal not printed.
    entries = {}
    for entry in document.get('repetitions') or []:
        if not isinstance(entry, dict):
            problems.append('a selected repetition is {0}, not an object'
                            .format(type(entry).__name__))
            continue
        name = entry.get('id')
        if not isinstance(name, str) or not name.strip():
            problems.append('a selected repetition has no usable `id`: {0!r}'
                            .format(name))
            continue
        entries[name] = entry

    # The document's own shape, before its arithmetic. `validate_selection()`
    # in the variance review is the full check -- it reads the rows, the
    # exclusions and the resolution rule -- but it cannot run for a series
    # whose newest block has not run, which is every selection at the moment
    # the block it plans is about to start. Block 10's selection was validated
    # by Block 9 because Block 9 reviewed a series that was complete; Block
    # 11's expansion had nothing checking it at all, so a typo in its brand-new
    # `schema` string, or a repetition with no hypothesis, would have been
    # silent until the report went looking. These are the checks that need no
    # measurement; the rest still happen in the review, which is where they
    # belong.
    schema = document.get('schema')
    if schema not in SELECTION_SCHEMAS:
        problems.append('the selection declares schema {0!r}; this campaign '
                        'writes {1}'.format(schema, ' or '.join(
                            repr(one) for one in SELECTION_SCHEMAS)))
    for field in ('decided_utc', 'decided_by', 'basis'):
        if not str(document.get(field) or '').strip():
            problems.append('the selection has no `{0}`; a decision with no '
                            'record of who made it, when, and off what is '
                            'indistinguishable from one nobody made'
                            .format(field))
    for name, entry in sorted(entries.items()):
        for field in ('hypothesis', 'variance_reason'):
            if not str(entry.get(field) or '').strip():
                problems.append('{0}: no `{1}`; an expansion without one is a '
                                're-run of a result someone disliked'
                                .format(name, field))
        cells = entry.get('cells')
        if not isinstance(cells, list) or not cells:
            problems.append('{0}: names no cells'.format(name))
    for entry in document.get('declined') or []:
        if not isinstance(entry, dict):
            problems.append('a declined comparison is {0}, not an object'
                            .format(type(entry).__name__))
        elif not str(entry.get('reason') or '').strip():
            problems.append('a declined comparison ({0!r}) has no reason'
                            .format(entry.get('id')))

    selected = set(entries)
    configured = set(block_configs)
    for name in sorted(selected - configured):
        problems.append('{0} is selected and this block runs no config for '
                        'it'.format(name))
    for name in sorted(configured - selected):
        problems.append('{0} has configs here and is not in the selection; a '
                        'row it measured would belong to no comparison'
                        .format(name))

    for name in sorted(selected & configured):
        entry = entries[name]
        plan = block_configs[name]
        configs = plan['passes']
        wanted = [cell for cell in (entry.get('cells') or [])
                  if isinstance(cell, str)]

        requested = entry.get('passes_requested')
        # Some passes already exist elsewhere -- one in Block 8 for a Block 10
        # selection, three for a Block 11 one. Asking for as many as already
        # ran would add no observation, and asking for more than this block
        # runs leaves the comparison short with nothing saying so.
        prior_blocks = plan.get('prior', (FIRST_PASS_BLOCK_NAME,))
        prior = sum(PRIOR_BLOCK_PASSES[one] for one in prior_blocks)
        if not isinstance(requested, int) or isinstance(requested, bool):
            problems.append('{0}: `passes_requested` is {1!r}, not a whole '
                            'number'.format(name, requested))
        elif requested != len(configs) + prior:
            problems.append(
                '{0}: the selection asks for {1} pass(es) and {2} of them are '
                'in {3}, so this block should run {4} and it runs {5}'.format(
                    name, requested, prior, ' and '.join(prior_blocks),
                    requested - prior, len(configs)))

        first = None
        first_path = os.path.join(config_dir,
                                  '{0}.yaml'.format(plan['first_pass']))
        if os.path.isfile(first_path):
            try:
                first = read_config(first_path)
            except (Exception, SystemExit) as failure:   # noqa: BLE001
                problems.append('{0}: {1}: {2}: {3}'.format(
                    name, plan['first_pass'], type(failure).__name__, failure))
        else:
            problems.append('{0}: no pass-1 config at {1}, so the repetitions '
                            'cannot be checked against what {2} '
                            'measured'.format(name, first_path,
                                              FIRST_PASS_BLOCK))

        mappings = []
        for stem, _repetition in configs:
            path = os.path.join(config_dir, '{0}.yaml'.format(stem))
            if not os.path.isfile(path):
                problems.append('{0}: no config at {1}'.format(name, path))
                continue
            try:
                test = read_config(path)
                described = cells_of(test)
                order, seed = batch_order(test)
            except (Exception, SystemExit) as failure:   # noqa: BLE001
                # `SystemExit` as well, deliberately. `check_batch_test()` and
                # `check_batch_run_names()` report by `sys.exit()`, so a config
                # that trips one of those would otherwise abort this script
                # part way through -- reporting the first bad config and
                # nothing about the other five, from a guard whose whole job is
                # to say everything that is wrong before anything runs.
                problems.append('{0}: {1}: {2}: {3}'.format(
                    name, stem, type(failure).__name__, failure))
                continue

            if test.get('name') != stem:
                problems.append(
                    '{0}: {1} declares the test name {2!r}; the file name and '
                    'the test name are both the artifact stem and must '
                    'agree'.format(name, stem, test.get('name')))

            if (order, seed) != ('shuffle', BLOCK_SEEDS[block]):
                problems.append(
                    '{0}: {1} runs {2} with seed {3}; the campaign\'s rule is '
                    'shuffle with seed {4}'.format(
                        name, stem, order, seed, BLOCK_SEEDS[block]))

            extra = sorted(set(described) - set(wanted))
            missing = sorted(set(wanted) - set(described))
            for cell in extra:
                problems.append('{0}: {1} runs {2!r}, which the selection does '
                                'not name'.format(name, stem, cell))
            for cell in missing:
                problems.append('{0}: {1} does not run {2!r}, which the '
                                'selection names'.format(name, stem, cell))
            if len(described) != len(set(described)):
                problems.append('{0}: {1} runs a cell twice'.format(name, stem))

            # Against Block 8's own config, not only against each other. A
            # cell description does not carry `tester_type`, `threads` or
            # anything else in the target mapping, so a drift in one of those
            # would pass every check above -- and the two repetitions drift
            # together, being made from each other.
            if first is not None:
                allowed = set(PASS_KEYS) | set(plan['narrowed'])
                if mapping_without(test, allowed) != mapping_without(first,
                                                                     allowed):
                    problems.append(
                        '{0}: {1} differs from {2} in more than {3}, so its '
                        'rows are not passes of the comparison Block 8 '
                        'measured'.format(name, stem, plan['first_pass'],
                                          ', '.join(sorted(allowed))))
            mappings.append((stem, mapping_without_name(test)))

        # The passes of one cell are observations of one thing only if the
        # thing did not move between them. The test `name` is what tells the
        # passes apart -- it is the artifact stem -- so it is the one field
        # allowed to differ, and everything else is compared literally.
        for (first_stem, one), (other_stem, other) in zip(mappings,
                                                          mappings[1:]):
            if one != other:
                problems.append(
                    '{0}: {1} and {2} differ in more than the test name, so '
                    'their rows are not passes of one comparison'.format(
                        name, first_stem, other_stem))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--selection', required=True,
                        help='the selection document the block executes')
    # Required, with no default. The block and its selection are two halves of
    # one statement and a default would let a mistyped `--selection` be
    # checked against the other block's table -- which is the one mistake this
    # script exists to catch, made by the script itself.
    parser.add_argument('--block', required=True, type=int,
                        choices=sorted(BLOCK_PLANS),
                        help='which repetition block these configs are for')
    parser.add_argument('--config-dir', default='benchmarks',
                        help='where the block\'s configs are read from '
                             '(the rendered copies, when a block is running)')
    args = parser.parse_args(argv)

    problems = []
    check(args.selection, args.config_dir, problems, block=args.block)
    for line in problems:
        print('error: {0}'.format(line), file=sys.stderr)
    configs = BLOCK_PLANS[args.block]['configs']
    if problems:
        print('{0} problem(s); Block {1} would not run the comparison the '
              'campaign selected'.format(len(problems), args.block),
              file=sys.stderr)
        return 1
    print('Block {0} configs match {1}: {2} selection(s), {3} config(s)'.format(
        args.block, os.path.basename(args.selection), len(configs),
        sum(len(plan['passes']) for plan in configs.values())))
    return 0


if __name__ == '__main__':
    sys.exit(main())
