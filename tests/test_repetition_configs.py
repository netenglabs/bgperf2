'''Does a repetition block run the comparison the campaign selected, and only that?

Blocks 10 and 11 both had their matrix decided by a different block:
`metadata/block10-selection.json` names three comparisons to repeat and seven
to decline, and `metadata/block11-expansion.json` expands the one of those
three that reversed rather than settling. Those configs have to execute
exactly that. A block that ran the wrong matrix would produce rows that look
exactly like the right ones, which is why the guard is a refusal before the
first container rather than something to notice in the CSV afterwards.

The repository's own configs and its own selection documents are checked here
as well as the synthetic cases, because those pairs are what will actually run.
'''
import copy
import importlib.util
import json
import os
import sys

import pytest
import yaml

from conftest import REPO_ROOT

spec = importlib.util.spec_from_file_location(
    'check_repetition_configs',
    REPO_ROOT / 'scripts' / 'check_repetition_configs.py')
checker = importlib.util.module_from_spec(spec)
sys.modules['check_repetition_configs'] = checker
spec.loader.exec_module(checker)

METADATA = (REPO_ROOT / 'results' / '2026' / '2026-timing-validation'
            / 'metadata')
SELECTIONS = {10: METADATA / 'block10-selection.json',
              11: METADATA / 'block11-expansion.json'}
SELECTION = SELECTIONS[10]
BENCHMARKS = REPO_ROOT / 'benchmarks'


def problems_for(selection_path, config_dir, block=10):
    found = []
    checker.check(str(selection_path), str(config_dir), found, block=block)
    return found


@pytest.mark.parametrize('block', sorted(SELECTIONS))
class TestTheRealConfigs:
    """Both blocks, from one table: the second block's guard is the first
    one's, and a check that stopped covering the block it was written for is
    the failure the shared table exists to prevent."""

    def test_the_repositorys_configs_execute_the_selection(self, block):
        if not SELECTIONS[block].is_file():
            pytest.skip('no campaign selection document on this checkout')
        assert problems_for(SELECTIONS[block], BENCHMARKS, block=block) == []

    def test_every_config_the_block_runs_exists(self, block):
        for plan in checker.BLOCK_PLANS[block]['configs'].values():
            for stem, _repetition in plan['passes']:
                assert (BENCHMARKS / '{0}.yaml'.format(stem)).is_file(), stem
            assert (BENCHMARKS
                    / '{0}.yaml'.format(plan['first_pass'])).is_file()

    def test_the_passes_of_a_comparison_differ_only_in_the_test_name(self, block):
        """Stated in every one of those files' headers; checked here so it
        cannot quietly stop being true. The final report reads the passes as
        the dispersion of one cell, so drift between them is a difference in
        the thing measured arriving inside the statistic meant to measure
        run-to-run noise."""
        for name, plan in checker.BLOCK_PLANS[block]['configs'].items():
            mappings = []
            for stem, _repetition in plan['passes']:
                test = checker.read_config(
                    str(BENCHMARKS / '{0}.yaml'.format(stem)))
                mappings.append(checker.mapping_without_name(test))
            assert all(m == mappings[0] for m in mappings), name

    def test_every_config_states_the_campaigns_block_seed(self, block):
        """The year with the block number appended, continuing 20268. A
        repetition that re-ran its predecessor's permutation would apply one
        position bias twice more rather than averaging it out."""
        seed = checker.BLOCK_SEEDS[block]
        assert seed == 202600 + block
        for plan in checker.BLOCK_PLANS[block]['configs'].values():
            for stem, _repetition in plan['passes']:
                test = checker.read_config(
                    str(BENCHMARKS / '{0}.yaml'.format(stem)))
                assert test['seed'] == seed
                assert test['order'] == 'shuffle'

    def test_the_blocks_seed_is_its_own(self, block):
        assert len(set(checker.BLOCK_SEEDS.values())) \
            == len(checker.BLOCK_SEEDS)


def a_selection(tmp_path, mutate=None):
    document = json.loads(SELECTION.read_text())
    if mutate:
        mutate(document)
    path = tmp_path / 'selection.json'
    path.write_text(json.dumps(document))
    return path


def a_config_dir(tmp_path, mutate=None):
    directory = tmp_path / 'benchmarks'
    directory.mkdir(exist_ok=True)
    for plan in checker.BLOCK10_CONFIGS.values():
        stems = [stem for stem, _ in plan['passes']] + [plan['first_pass']]
        for stem in stems:
            source = BENCHMARKS / '{0}.yaml'.format(stem)
            (directory / source.name).write_text(source.read_text())
    if mutate:
        mutate(directory)
    return directory


@pytest.mark.skipif(not SELECTION.is_file(), reason='no selection document')
class TestWhatItRefuses:
    def test_a_config_running_a_cell_the_selection_does_not_name(self, tmp_path):
        def widen(directory):
            path = directory / '2026-timing-bird-peers250-rep2.yaml'
            path.write_text(path.read_text().replace(
                'neighbors: [250]', 'neighbors: [50, 250, 500]'))

        found = problems_for(a_selection(tmp_path), a_config_dir(tmp_path, widen))
        assert any('which the selection does not name' in line for line in found)

    def test_a_config_missing_a_cell_the_selection_names(self, tmp_path):
        def narrow(directory):
            path = directory / '2026-timing-bird-diversity-rep3.yaml'
            text = path.read_text()
            # Drop the four-thread target, which is a third of the comparison.
            text = text.split('       -\n         name: bird\n         version: 3.3.2\n'
                              '         label: bird 3.3.2 (4 threads)')[0]
            path.write_text(text)

        found = problems_for(a_selection(tmp_path), a_config_dir(tmp_path, narrow))
        assert any('which the selection names' in line for line in found)

    def test_two_passes_that_stopped_being_one_comparison(self, tmp_path):
        def drift(directory):
            path = directory / '2026-timing-bird-reload-rep3.yaml'
            path.write_text(path.read_text().replace(
                'policy_reload_blocks: 10', 'policy_reload_blocks: 5'))

        found = problems_for(a_selection(tmp_path), a_config_dir(tmp_path, drift))
        assert any('differ in more than the test name' in line for line in found)

    def test_a_seed_that_is_not_the_blocks(self, tmp_path):
        def reseed(directory):
            path = directory / '2026-timing-bird-reload-rep2.yaml'
            path.write_text(path.read_text().replace('seed: 202610', 'seed: 20268'))

        found = problems_for(a_selection(tmp_path), a_config_dir(tmp_path, reseed))
        assert any("the campaign's rule is shuffle with seed 202610" in line
                   for line in found)

    def test_a_selection_this_block_runs_nothing_for(self, tmp_path):
        def add(document):
            entry = copy.deepcopy(document['repetitions'][0])
            entry['id'] = 'a-comparison-with-no-configs'
            document['repetitions'].append(entry)

        found = problems_for(a_selection(tmp_path, add), a_config_dir(tmp_path))
        assert any('this block runs no config for it' in line for line in found)

    def test_a_comparison_with_configs_and_no_selection(self, tmp_path):
        def drop(document):
            document['repetitions'] = [
                entry for entry in document['repetitions']
                if entry['id'] != 'bird-policy-recalculation']

        found = problems_for(a_selection(tmp_path, drop), a_config_dir(tmp_path))
        assert any('belong to no comparison' in line for line in found)

    def test_pass_arithmetic_that_does_not_add_up(self, tmp_path):
        """Block 8 supplied pass 1, so two configs here mean three passes.
        Asking for five and running two leaves the comparison short with
        nothing saying so."""
        def raise_it(document):
            for entry in document['repetitions']:
                entry['passes_requested'] = 5

        found = problems_for(a_selection(tmp_path, raise_it), a_config_dir(tmp_path))
        assert any('should run 4 and it runs 2' in line for line in found)

    def test_a_missing_selection_document_is_the_refusal(self, tmp_path):
        found = problems_for(tmp_path / 'nothing.json', a_config_dir(tmp_path))
        assert found and 'may not run until one is written' in found[0]

    def test_a_missing_config_is_named(self, tmp_path):
        def remove(directory):
            (directory / '2026-timing-bird-peers250-rep3.yaml').unlink()

        found = problems_for(a_selection(tmp_path), a_config_dir(tmp_path, remove))
        assert any('no config at' in line for line in found)


@pytest.mark.skipif(not SELECTION.is_file(), reason='no selection document')
class TestDriftFromWhatBlock8Measured:
    """Comparing the two repetitions against each other is not enough.

    They are made from each other, so they drift together; and a cell
    description carries the axes and the run name, not `tester_type`,
    `threads`, or anything else in the target mapping. A pass that quietly
    stopped running the generator Block 8 ran would satisfy every other check
    here and be caught only by the review, after all eighteen runs.
    """

    def test_a_target_field_that_moved_away_from_pass_one(self, tmp_path):
        def drift(directory):
            for stem in ('2026-timing-bird-diversity-rep2',
                         '2026-timing-bird-diversity-rep3'):
                path = directory / '{0}.yaml'.format(stem)
                # Invisible in every cell description -- which is the point.
                path.write_text(path.read_text().replace(
                    '         label: bird 2.19.2\n',
                    '         label: bird 2.19.2\n         threads: 2\n'))

        found = problems_for(a_selection(tmp_path), a_config_dir(tmp_path, drift))
        assert any('differs from 2026-timing-bird-diversity in more than'
                   in line for line in found)

    def test_the_peer_narrowing_is_allowed_and_nothing_else_is(self, tmp_path):
        """`neighbors` is the one key the peer sweep may change against Block
        8, because the selection names the 250-peer cells and declines the
        rest. A second changed key is not covered by that."""
        assert checker.BLOCK10_CONFIGS[
            'bird-session-scaling-250-peers']['narrowed'] == ('neighbors',)
        assert checker.BLOCK11_CONFIGS[
            'bird-session-scaling-250-peers']['narrowed'] == ('neighbors',)

        def drift(directory):
            for stem in ('2026-timing-bird-peers250-rep2',
                         '2026-timing-bird-peers250-rep3'):
                path = directory / '{0}.yaml'.format(stem)
                path.write_text(path.read_text().replace(
                    'prefixes: [2_000]', 'prefixes: [4_000]'))

        found = problems_for(a_selection(tmp_path), a_config_dir(tmp_path, drift))
        assert any('in more than' in line for line in found)

    def test_a_missing_pass_one_config_is_named(self, tmp_path):
        def remove(directory):
            (directory / '2026-timing-bird-reload.yaml').unlink()

        found = problems_for(a_selection(tmp_path), a_config_dir(tmp_path, remove))
        assert any('no pass-1 config at' in line for line in found)


@pytest.mark.skipif(not SELECTION.is_file(), reason='no selection document')
class TestAMalformedSelectionIsRefusedNotRaised:
    """Everything below `check()` is the refusal this script exists to print.
    A traceback in its place is the refusal not printed, and the document is
    written by hand."""

    def test_a_repetition_with_no_id(self, tmp_path):
        def mutate(document):
            document['repetitions'][0].pop('id')

        found = problems_for(a_selection(tmp_path, mutate), a_config_dir(tmp_path))
        assert any('no usable `id`' in line for line in found)

    def test_passes_requested_as_a_string(self, tmp_path):
        def mutate(document):
            document['repetitions'][0]['passes_requested'] = '3'

        found = problems_for(a_selection(tmp_path, mutate), a_config_dir(tmp_path))
        assert any('not a whole number' in line for line in found)

    def test_a_repetition_that_is_not_an_object(self, tmp_path):
        def mutate(document):
            document['repetitions'].append('bird-session-scaling-250-peers')

        found = problems_for(a_selection(tmp_path, mutate), a_config_dir(tmp_path))
        assert any('not an object' in line for line in found)

    def test_a_document_that_is_not_json(self, tmp_path):
        path = tmp_path / 'selection.json'
        path.write_text('{not json')
        found = problems_for(path, a_config_dir(tmp_path))
        assert any('not readable JSON' in line for line in found)

    def test_a_config_that_trips_an_existing_guard_is_reported(self, tmp_path):
        """`check_batch_test()` reports by `sys.exit()`, which is not an
        `Exception`. Uncaught it aborts this script part way through, so the
        other five configs are never checked by a guard whose job is to say
        everything that is wrong before anything runs."""
        def mutate(directory):
            path = directory / '2026-timing-bird-reload-rep2.yaml'
            path.write_text(path.read_text().replace(
                'tester_type: bird', 'tester_type: nonesuch'))

        found = problems_for(a_selection(tmp_path), a_config_dir(tmp_path, mutate))
        assert any('SystemExit' in line for line in found)
        # And the run continued: the other comparisons were still checked.
        assert any('2026-timing-bird-reload-rep2' in line for line in found)

    def test_a_document_that_is_a_list(self, tmp_path):
        path = tmp_path / 'selection.json'
        path.write_text('[]')
        found = problems_for(path, a_config_dir(tmp_path))
        assert any('not an object' in line for line in found)


@pytest.mark.skipif(not SELECTIONS[11].is_file(), reason='no expansion document')
class TestTheExpansionCountsThePassesThatAlreadyRan:
    """Block 11's two configs are passes 4 and 5, not 2 and 3.

    Three passes of the 250-peer comparison exist before it -- one in Block 8
    and two in Block 10 -- so the arithmetic a Block 10 selection was checked
    against is wrong here by two, in the direction that looks right: a
    selection asking for three would be satisfied by a block that added
    nothing.
    """

    def an_expansion(self, tmp_path, mutate=None):
        document = json.loads(SELECTIONS[11].read_text())
        if mutate:
            mutate(document)
        path = tmp_path / 'expansion.json'
        path.write_text(json.dumps(document))
        return path

    def test_the_prior_passes_are_the_three_that_ran(self):
        """Per comparison, not per block: a later block expanding one
        comparison with three prior passes while newly repeating another with
        one would check the second against the first's history, in the
        accepting direction."""
        plan = checker.BLOCK_PLANS[11]['configs'][
            'bird-session-scaling-250-peers']
        assert plan['prior'] == (checker.FIRST_PASS_BLOCK_NAME,
                                 checker.REPETITION_BLOCK_NAME)
        assert sum(checker.PRIOR_BLOCK_PASSES[one]
                   for one in plan['prior']) == 3

    def test_an_expansion_asking_for_three_passes_is_refused(self, tmp_path):
        def lower(document):
            for entry in document['repetitions']:
                entry['passes_requested'] = 3

        found = problems_for(self.an_expansion(tmp_path, lower), BENCHMARKS,
                             block=11)
        assert any('should run 0 and it runs 2' in line for line in found)
        assert any('block10-selected-repetitions' in line for line in found)

    def test_the_expansion_read_against_block_10s_table_does_not_pass(self, tmp_path):
        """The block and its selection are two halves of one statement. Read
        against the other block's configs, this asks five passes of a table
        that runs repetitions 2 and 3 -- which is the mistake `--block` is
        required for."""
        found = problems_for(self.an_expansion(tmp_path), BENCHMARKS, block=10)
        assert any('should run 4 and it runs 2' in line for line in found)


@pytest.mark.skipif(not SELECTION.is_file(), reason='no selection document')
class TestTheDocumentsOwnShape:
    """The checks that need no measurement, made here because nothing else
    makes them in time.

    `validate_selection()` in the variance review is the full check, and it
    cannot run for a series whose newest block has not run -- which is every
    selection at the moment the block it plans is about to start. Block 10's
    was validated by Block 9 because Block 9 reviewed a complete series; Block
    11's expansion had nothing checking it at all, so a typo in its `schema`
    would have been silent until the report went looking for it.
    """

    def test_a_schema_this_campaign_does_not_write(self, tmp_path):
        def mutate(document):
            document['schema'] = 'bgperf2/block10-selection/v2'

        found = problems_for(a_selection(tmp_path, mutate),
                             a_config_dir(tmp_path))
        assert any('declares schema' in line for line in found)

    def test_both_schema_names_are_accepted(self, tmp_path):
        """Block 10's document is on disk under the name the shape had when it
        was the only one, and is not rewritten to satisfy a rename."""
        for schema in checker.SELECTION_SCHEMAS:
            def mutate(document, schema=schema):
                document['schema'] = schema

            found = problems_for(a_selection(tmp_path, mutate),
                                 a_config_dir(tmp_path))
            assert not [line for line in found if 'schema' in line], schema

    def test_an_expansion_with_no_hypothesis(self, tmp_path):
        def mutate(document):
            document['repetitions'][0].pop('hypothesis')

        found = problems_for(a_selection(tmp_path, mutate),
                             a_config_dir(tmp_path))
        assert any('re-run of a result someone disliked' in line
                   for line in found)

    def test_a_decision_with_no_record_of_who_made_it(self, tmp_path):
        for field in ('decided_utc', 'decided_by', 'basis'):
            def mutate(document, field=field):
                document.pop(field, None)

            found = problems_for(a_selection(tmp_path, mutate),
                                 a_config_dir(tmp_path))
            assert any('has no `{0}`'.format(field) in line
                       for line in found), field

    def test_a_declined_comparison_with_no_reason(self, tmp_path):
        def mutate(document):
            document['declined'][0]['reason'] = '   '

        found = problems_for(a_selection(tmp_path, mutate),
                             a_config_dir(tmp_path))
        assert any('has no reason' in line for line in found)
