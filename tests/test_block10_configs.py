'''Does Block 10 run the comparison the campaign selected, and only that?

Block 10 is the one block whose matrix was decided by a different block:
`metadata/block10-selection.json` names three comparisons to repeat and seven
to decline, and these configs have to execute exactly that. A block that ran
the wrong matrix would produce rows that look exactly like the right ones,
which is why the guard is a refusal before the first container rather than
something to notice in the CSV afterwards.

The repository's own configs and its own selection document are checked here
as well as the synthetic cases, because that pair is what will actually run.
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
    'check_block10_configs', REPO_ROOT / 'scripts' / 'check_block10_configs.py')
checker = importlib.util.module_from_spec(spec)
sys.modules['check_block10_configs'] = checker
spec.loader.exec_module(checker)

SELECTION = (REPO_ROOT / 'results' / '2026' / '2026-timing-validation'
             / 'metadata' / 'block10-selection.json')
BENCHMARKS = REPO_ROOT / 'benchmarks'


def problems_for(selection_path, config_dir):
    found = []
    checker.check(str(selection_path), str(config_dir), found)
    return found


class TestTheRealConfigs:
    def test_the_repositorys_configs_execute_the_selection(self):
        if not SELECTION.is_file():
            pytest.skip('no campaign selection document on this checkout')
        assert problems_for(SELECTION, BENCHMARKS) == []

    def test_every_config_the_block_runs_exists(self):
        for plan in checker.BLOCK10_CONFIGS.values():
            for stem, _repetition in plan['passes']:
                assert (BENCHMARKS / '{0}.yaml'.format(stem)).is_file(), stem
            assert (BENCHMARKS
                    / '{0}.yaml'.format(plan['first_pass'])).is_file()

    def test_the_two_passes_of_a_comparison_differ_only_in_the_test_name(self):
        """Stated in every one of those files' headers; checked here so it
        cannot quietly stop being true. Block 11 reads the passes as the
        dispersion of one cell, so drift between them is a difference in the
        thing measured arriving inside the statistic meant to measure
        run-to-run noise."""
        for name, plan in checker.BLOCK10_CONFIGS.items():
            mappings = []
            for stem, _repetition in plan['passes']:
                test = checker.read_config(
                    str(BENCHMARKS / '{0}.yaml'.format(stem)))
                mappings.append(checker.mapping_without_name(test))
            assert all(m == mappings[0] for m in mappings), name

    def test_every_config_states_the_campaigns_block_seed(self):
        """The year with the block number appended, continuing 20268."""
        assert checker.BLOCK_SEED == 202610
        for plan in checker.BLOCK10_CONFIGS.values():
            for stem, _repetition in plan['passes']:
                test = checker.read_config(
                    str(BENCHMARKS / '{0}.yaml'.format(stem)))
                assert test['seed'] == 202610
                assert test['order'] == 'shuffle'


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
