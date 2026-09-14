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

'''Does Block 10 run the comparison the campaign selected, and only that?

Block 10 is the one block whose matrix was decided by a *different* block:
`metadata/block10-selection.json` was written between Block 9's first reading of
the statistics and the run that validates them, and it names three comparisons
to repeat and seven to decline with reasons. The configs here have to execute
exactly that, and "a block that ran the wrong matrix would produce rows that
look exactly like the right ones" is the whole reason the runner refuses to
improvise one.

So this reads the selection and the configs and refuses a mismatch, before any
container starts. It is not the variance review: it computes no statistic,
opens no results directory, and says nothing about whether the rows qualify.
It answers the narrower question the review cannot answer yet -- the review
needs Block 10's own passes to be COMPLETE, which they cannot be until after
the block it is guarding has run.

Pure: no Docker and no results. Six configs and one JSON document.
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
# appended, continuing 20268 from Block 8.
BLOCK_SEED = 202610

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

# Pass 1 of every one of them, which is where the comparison's first
# observation came from and why only two more configs are needed.
FIRST_PASS_BLOCK = 'block8-bird-architecture-screen'

# What tells the passes apart rather than describing the workload. `name` is
# the artifact stem, and the seed is per block by the campaign's own rule.
PASS_KEYS = ('name', 'seed')


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


def check(selection_path, config_dir, problems):
    if not os.path.isfile(selection_path):
        problems.append('no selection document at {0}; Block 10 may not run '
                        'until one is written'.format(selection_path))
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

    selected = set(entries)
    configured = set(BLOCK10_CONFIGS)
    for name in sorted(selected - configured):
        problems.append('{0} is selected and this block runs no config for '
                        'it'.format(name))
    for name in sorted(configured - selected):
        problems.append('{0} has configs here and is not in the selection; a '
                        'row it measured would belong to no comparison'
                        .format(name))

    for name in sorted(selected & configured):
        entry = entries[name]
        plan = BLOCK10_CONFIGS[name]
        configs = plan['passes']
        wanted = [cell for cell in (entry.get('cells') or [])
                  if isinstance(cell, str)]

        requested = entry.get('passes_requested')
        # One pass already exists, in Block 8. Asking for three and running
        # three here would be four observations of a comparison the plan
        # expands in steps, and asking for three while running one leaves it
        # short with nothing saying so.
        if not isinstance(requested, int) or isinstance(requested, bool):
            problems.append('{0}: `passes_requested` is {1!r}, not a whole '
                            'number'.format(name, requested))
        elif requested != len(configs) + 1:
            problems.append(
                '{0}: the selection asks for {1} pass(es) and 1 of them is in '
                '{2}, so this block should run {3} and it runs {4}'.format(
                    name, requested, FIRST_PASS_BLOCK, requested - 1,
                    len(configs)))

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
                            'cannot be checked against what Block 8 '
                            'measured'.format(name, first_path))

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

            if (order, seed) != ('shuffle', BLOCK_SEED):
                problems.append(
                    '{0}: {1} runs {2} with seed {3}; the campaign\'s rule is '
                    'shuffle with seed {4}'.format(
                        name, stem, order, seed, BLOCK_SEED))

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
                        help='the Block 10 selection document')
    parser.add_argument('--config-dir', default='benchmarks',
                        help='where the block\'s configs are read from '
                             '(the rendered copies, when a block is running)')
    args = parser.parse_args(argv)

    problems = []
    check(args.selection, args.config_dir, problems)
    for line in problems:
        print('error: {0}'.format(line), file=sys.stderr)
    if problems:
        print('{0} problem(s); Block 10 would not run the comparison the '
              'campaign selected'.format(len(problems)), file=sys.stderr)
        return 1
    print('Block 10 configs match {0}: {1} selection(s), {2} config(s)'.format(
        os.path.basename(args.selection), len(BLOCK10_CONFIGS),
        sum(len(plan['passes']) for plan in BLOCK10_CONFIGS.values())))
    return 0


if __name__ == '__main__':
    sys.exit(main())
