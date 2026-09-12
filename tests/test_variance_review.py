'''Reading the passes of one canonical workload together.

`scripts/timing_variance_review.py` is Block 9's mechanical work: the three
passes of a matrix live in three block directories, and nothing inside any of
them says so. What it must not do is quietly turn a missing pass into a
smaller `n`, pair a cell with another cell's artifact, or let an expansion be
selected over rows that did not qualify -- each of which would produce a
document that looks exactly like a correct one.

The arithmetic itself is `summary.py`'s and is tested in
`test_batch_summary.py`; what is tested here is the joining, the order
reconstruction, and the refusals.
'''
import importlib.util
import json
import sys

import pytest

from conftest import REPO_ROOT

import bgperf2

spec = importlib.util.spec_from_file_location(
    'timing_variance_review', REPO_ROOT / 'scripts' / 'timing_variance_review.py')
review = importlib.util.module_from_spec(spec)
sys.modules['timing_variance_review'] = review
spec.loader.exec_module(review)


def a_target(name='bird', version=None, label=None):
    target = {'name': name}
    if version:
        target['version'] = version
    if label:
        target['label'] = label
    return target


def an_identity(ordinal=0, target=None, test='t', neighbors=50,
                prefixes=100000, filter='None', repetition=None):
    identity = {'test': test, 'ordinal': ordinal, 'neighbors': neighbors,
                'prefixes': prefixes, 'filter': filter,
                'target': target or a_target()}
    if repetition is not None:
        identity['repetition'] = repetition
    return identity


class TestExecutionOrder:
    '''The seed is recorded so the sequence can be rebuilt; this rebuilds it.'''

    def test_it_reproduces_the_controllers_own_permutation(self):
        """Not a second implementation of the ordering: the same one, checked.

        `order_batch_cells()` is what ran the pass, and the progress file's
        keys are the cell ids it keyed on -- so the review's positions have to
        come out of the same digest in the same order or they describe a run
        that did not happen.
        """
        test = {'name': 'ord', 'neighbors': [10, 50], 'prefixes': [100],
                'filter_test': ['None'],
                'targets': [{'name': 'bird'}, {'name': 'gobgp'},
                            {'name': 'frr_c'}]}
        cells = bgperf2.expand_batch_cells(test, test['targets'])
        ids = [bgperf2.batch_cell_id(test['name'], cell) for cell in cells]
        expected = [bgperf2.batch_cell_id(test['name'], cell) for cell in
                    bgperf2.order_batch_cells(test['name'], cells, 'shuffle', 20262)]
        positions = review.execution_positions(ids, 20262, 'shuffle')
        assert [cell_id for cell_id, _ in
                sorted(positions.items(), key=lambda item: item[1])] == expected

    def test_a_matrix_pass_is_positioned_by_ordinal(self):
        ids = [json.dumps(an_identity(ordinal=n), sort_keys=True)
               for n in (2, 0, 1)]
        positions = review.execution_positions(ids, None, 'matrix')
        assert sorted(positions.values()) == [1, 2, 3]
        assert positions[json.dumps(an_identity(ordinal=0), sort_keys=True)] == 1


class TestCellIdentity:
    def test_the_pass_is_not_part_of_the_cell(self):
        '''The three configs of a series differ in `name` and `seed` alone, so
        the test name differs by construction and must not separate a cell
        from its own other passes.'''
        one = review.cell_identity_key(an_identity(test='rep1'))
        two = review.cell_identity_key(an_identity(test='rep2', repetition=2))
        assert one == two

    def test_a_different_target_is_a_different_cell(self):
        one = review.cell_identity_key(an_identity())
        two = review.cell_identity_key(
            an_identity(target=a_target(version='3.3.2')))
        assert one != two

    def test_a_moved_axis_is_a_different_cell(self):
        assert review.cell_identity_key(an_identity()) != \
            review.cell_identity_key(an_identity(neighbors=250))


def a_pass(repetition, cells, block='block', results='synthetic'):
    return {'repetition': repetition, 'block': block, 'results': results,
            'cells': cells}


def a_cell(ordinal=0, row=None, position=1, target=None):
    identity = an_identity(ordinal=ordinal, target=target)
    return {'cell_id': json.dumps(identity, sort_keys=True),
            'key': review.cell_identity_key(identity),
            'identity': identity, 'row': row or ['bird'], 'position': position}


class TestGrouping:
    def test_a_cell_missing_from_a_pass_is_a_problem_and_a_pass_that_did_not_run(self):
        """Never a smaller `n` in silence.

        Dropping the pass would change the denominator of every statistic for
        that cell without saying so, which is the one thing a dispersion
        cannot survive -- and `summary.py` counts a pass that did not run
        apart from one that failed for the same reason.
        """
        problems = []
        groups, records = review.build_groups(
            [a_pass(1, [a_cell(0), a_cell(1, target=a_target('gobgp'))]),
             a_pass(2, [a_cell(0)], block='block-two')], problems)
        assert [entry['severity'] for entry in problems] == [review.ERROR]
        assert 'absent from pass 2' in problems[0]['message']
        missing = [group for group in groups if group['ordinal'] == 1][0]
        assert [entry['row'] for entry in missing['passes']] == [['bird'], None]
        assert len(records) == 2

    def test_cells_are_grouped_in_matrix_order(self):
        problems = []
        groups, _ = review.build_groups(
            [a_pass(1, [a_cell(2, target=a_target('gobgp')), a_cell(0)])],
            problems)
        assert [group['ordinal'] for group in groups] == [0, 2]
        assert problems == []


class TestOrderRelation:
    def marks(self, pairs):
        return review.order_relation(
            [{'position': position, 'value': value} for position, value in pairs])

    def test_identical_values_are_tied_not_a_direction(self):
        '''The decision metric is whole seconds off a 1s poll, so passes of a
        cell agreeing exactly is the common case; reading a direction out of
        it would be reading the rounding.'''
        assert self.marks([(1, 90), (5, 90), (9, 90)]) == 'tied'

    def test_a_monotone_rise_with_position_is_named(self):
        assert self.marks([(9, 92), (1, 90), (5, 91)]) == 'rises with position'

    def test_a_monotone_fall_with_position_is_named(self):
        assert self.marks([(1, 92), (5, 91), (9, 90)]) == 'falls with position'

    def test_anything_else_is_neither(self):
        assert self.marks([(1, 92), (5, 90), (9, 91)]) == 'neither'

    def test_one_observation_says_so_rather_than_claiming_a_tie(self):
        assert self.marks([(1, 90)]) == 'too few observations'
        assert self.marks([(1, None), (5, 90)]) == 'too few observations'


class TestSharedSuffix:
    def test_the_axes_every_cell_agrees_about_are_lifted_out(self):
        assert review.shared_suffix(['bird 2.19.2, peers=50, filter=None',
                                     'frr_c 10.7, peers=50, filter=None']) == \
            ', peers=50, filter=None'

    def test_a_swept_axis_stays_in_the_labels(self):
        assert review.shared_suffix(['bird, peers=50, filter=None',
                                     'bird, peers=500, filter=None']) == \
            ', filter=None'

    def test_one_cell_keeps_its_whole_description(self):
        assert review.shared_suffix(['bird, peers=50']) == ''


class TestHostClass:
    def test_two_boots_of_one_machine_are_one_class(self):
        '''`MemTotal` is what the kernel has left after its own reservations,
        and this campaign's blocks recorded 64,425,440 and 64,425,436 kB on
        one instance type. An exact test rejects the host-class rule on
        0.000006%.'''
        spread = review.host_memory_spread(
            'memory_total_kb', {'a': 64425440, 'b': 64425436})
        assert spread is not None
        assert spread < review.HOST_MEMORY_TOLERANCE

    def test_a_real_memory_change_is_not_inside_the_tolerance(self):
        assert review.host_memory_spread(
            'memory_total_kb', {'a': 64425440, 'b': 32212720}) > \
            review.HOST_MEMORY_TOLERANCE

    def test_nothing_else_is_compared_with_a_tolerance(self):
        assert review.host_memory_spread('cpu_threads', {'a': 16, 'b': 32}) is None


class TestExclusionLookup:
    def test_a_rejected_row_is_keyed_by_its_artifact_not_its_name(self):
        """A run name is not a cell.

        The screen's peer sweep writes three rows called `bird 2.19.2` and
        rejected one of them; keyed on the name, an expansion of the two cells
        that were never in question would be refused.
        """
        excluded = {'by_artifact': {('block8', 'peers', 'b_500.events.json'): 'rejected'},
                    'by_name': {}, 'listed': []}
        assert review.exclusion_for(excluded, 'block8', 'peers',
                                    'b_500.events.json', 'bird 2.19.2') == 'rejected'
        assert review.exclusion_for(excluded, 'block8', 'peers',
                                    'b_50.events.json', 'bird 2.19.2') is None

    def test_the_name_is_the_fallback_where_no_artifact_was_named(self):
        excluded = {'by_artifact': {},
                    'by_name': {('b', 'mrt', 'bird 2.19.2'): ['rejected']},
                    'listed': []}
        assert review.exclusion_for(excluded, 'b', 'mrt', None,
                                    'bird 2.19.2') == 'rejected'


def a_review(series='synthetic', cells=('bird 2.19.2', 'frr_c 10.7'), passes=3,
             scope='matrix'):
    return {
        'series': series,
        'scope': scope,
        'passes': [{'repetition': n + 1} for n in range(passes)],
        'cells': [{'ordinal': n, 'name': name, 'expansion': None,
                   'description': '{0}, peers=50'.format(name),
                   'passes': [{'block': 'block{0}'.format(p + 2),
                               'results': series,
                               'artifact': '{0}_{1}.events.json'.format(name, p)}
                              for p in range(passes)]}
                  for n, name in enumerate(cells)],
    }


NO_EXCLUSIONS = {'by_artifact': {}, 'by_name': {}, 'listed': []}


def a_selection(**overrides):
    document = {
        'schema': review.SELECTION_SCHEMA,
        'decided_utc': '2026-09-12T00:00:00Z',
        'decided_by': 'operator',
        'repetitions': [{
            'id': 'frr-10.7-against-10.0',
            'series': 'synthetic',
            'cells': ['frr_c 10.7, peers=50'],
            'passes_requested': 5,
            'hypothesis': 'FRR 10.7 is faster than 10.0 at this workload',
            'variance_reason': 'the medians are 6s apart and the pair is '
                               'unseparated at three passes',
        }],
    }
    document.update(overrides)
    return document


def errors_for(document, reviews=None, excluded=None):
    problems = []
    review.validate_selection(document, reviews or [a_review()],
                              excluded or NO_EXCLUSIONS, problems)
    return [entry['message'] for entry in problems
            if entry['severity'] == review.ERROR]


class TestSelection:
    '''What may be expanded, and on what evidence.

    The plan expands a comparison "only when all existing rows pass
    qualification and observed variance could change the decision", and never
    the whole matrix. Unchecked, the decision to re-run belongs to whoever read
    the CSV and disliked it -- which re-runs the surprising results and turns a
    benchmark into a search for the expected answer.
    '''

    def test_a_complete_selection_passes(self):
        assert errors_for(a_selection()) == []

    def test_a_repetition_without_a_hypothesis_is_refused(self):
        document = a_selection()
        document['repetitions'][0]['hypothesis'] = '   '
        assert any('no hypothesis' in message for message in errors_for(document))

    def test_a_repetition_without_a_variance_reason_is_refused(self):
        document = a_selection()
        del document['repetitions'][0]['variance_reason']
        assert any('no variance_reason' in message
                   for message in errors_for(document))

    def test_no_repetitions_still_needs_a_reason(self):
        """"The campaign advances with no optional repeats" is a decision.

        With nothing beside it, it is indistinguishable from the block never
        having been reviewed.
        """
        assert any('no_repetitions_reason' in message
                   for message in errors_for(a_selection(repetitions=[])))
        assert errors_for(a_selection(
            repetitions=[],
            no_repetitions_reason='every decision-relevant pair is separated')) == []

    def test_a_cell_that_is_not_in_the_review_is_refused(self):
        document = a_selection()
        document['repetitions'][0]['cells'] = ['bird 9.9.9, peers=50']
        assert any('is not a cell of synthetic' in message
                   for message in errors_for(document))

    def test_the_whole_matrix_may_not_be_expanded(self):
        document = a_selection()
        document['repetitions'][0]['cells'] = [
            cell['description'] for cell in a_review()['cells']]
        assert any('forbids expanding the whole matrix' in message
                   for message in errors_for(document))

    def test_a_screen_scenario_may_be_repeated_whole(self):
        """Three cells of a screen scenario are one comparison.

        The plan asks this block to "select BIRD architecture scenarios for
        two additional repetitions", so refusing a selection that names all
        three would forbid the one expansion the block exists to choose. The
        rule guards the fourteen-configuration matrix, which is the thing a
        reader who disliked the CSV could re-run wholesale.
        """
        screen = a_review(series='screen-diversity',
                          cells=('bird 2.19.2', 'bird 3.3.2'), passes=1,
                          scope='scenario')
        document = a_selection(repetitions=[{
            'id': 'bird-3-competing-paths',
            'series': 'screen-diversity',
            'cells': [cell['description'] for cell in screen['cells']],
            'passes_requested': 3,
            'hypothesis': 'BIRD 3 is slower at competing-path selection',
            'variance_reason': 'one observation per cell decides nothing',
        }])
        assert errors_for(document, reviews=[screen]) == []

    def test_an_expansion_that_adds_no_pass_is_refused(self):
        document = a_selection()
        document['repetitions'][0]['passes_requested'] = 3
        assert any('adds no observation' in message
                   for message in errors_for(document))

    def test_the_expansion_stops_at_five(self):
        document = a_selection()
        document['repetitions'][0]['passes_requested'] = 6
        assert any('the plan stops at 5' in message
                   for message in errors_for(document))

    def test_a_pair_more_passes_cannot_separate_may_not_be_expanded(self):
        '''The plan's second condition: "observed variance could change the
        decision".  Where the rule's own floor says it cannot -- a gap inside
        the metric's resolution -- the expansion buys hours and the same
        verdict, and `variance_reason` being a non-empty string is not a check
        of that.'''
        reviewed = a_review()
        reviewed['cells'][1]['expansion'] = {
            'could_separate': False, 'gap': 1.0, 'resolution': 1.0,
            'rival': 'frr_c 10.0, peers=50',
            'reason': 'a gap of 1.0 cannot clear the 1.0 resolution of '
                      'elapsed (s) at any number of passes'}
        assert any('cannot be separated by more passes' in message
                   for message in errors_for(a_selection(), reviews=[reviewed]))

    def test_a_pair_more_passes_could_separate_is_allowed(self):
        reviewed = a_review()
        reviewed['cells'][1]['expansion'] = {
            'could_separate': True, 'gap': 6.0, 'resolution': 1.0,
            'rival': 'frr_c 10.0, peers=50'}
        assert errors_for(a_selection(), reviews=[reviewed]) == []

    def test_a_cell_whose_row_was_excluded_may_not_be_expanded(self):
        '''"Only when all existing rows pass qualification" -- checked against
        the block's own verdicts rather than trusted.'''
        excluded = {'by_artifact': {('block2', 'synthetic',
                                     'frr_c 10.7_0.events.json'): 'rejected'},
                    'by_name': {}, 'listed': []}
        messages = errors_for(a_selection(), excluded=excluded)
        assert any('do not all pass qualification' in message
                   for message in messages)

    def test_a_selection_of_the_wrong_schema_is_refused(self):
        assert any('is not bgperf2/block10-selection' in message
                   for message in errors_for(a_selection(schema='something/else')))

    def test_two_repetitions_may_not_share_an_id(self):
        document = a_selection()
        document['repetitions'].append(dict(document['repetitions'][0]))
        assert any('are called' in message for message in errors_for(document))

    def test_a_declined_comparison_needs_a_reason(self):
        document = a_selection(declined=[{'id': 'bird-3-threads'}])
        assert any('has no reason' in message for message in errors_for(document))


HEADER = [field.strip() for field in bgperf2.stats_header().split(',')]
COLUMN = {name: position for position, name in enumerate(HEADER)}


def a_row(name, elapsed=90, failed='', message='', received=5000000):
    '''One stats row of the current header's width, by column name.'''
    row = [''] * len(HEADER)
    row[COLUMN['name']] = name
    row[COLUMN['peers']] = '50'
    row[COLUMN['prefixes per peer']] = '100000'
    row[COLUMN['required']] = 4950000
    row[COLUMN['received']] = received
    row[COLUMN['elapsed (s)']] = elapsed
    row[COLUMN['failed']] = failed
    row[COLUMN['MSG']] = message
    row[COLUMN['target image']] = 'bgperf/{0}:latest'.format(name)
    row[COLUMN['tester version']] = 'bird 2.19.2'
    row[COLUMN['monitor version']] = 'gobgp 3.37.0'
    return row


def a_run_root(tmp_path, series, rows_by_pass, convergence_by_pass):
    '''A run root holding one series' passes: progress, CSV header, artifacts.

    The CSV carries its header and no rows on purpose: the rows are read from
    the progress document, which is where they are already paired with the
    cell that produced them, and the header is read from the CSV because that
    is what a row was written under.
    '''
    root = tmp_path / 'run'
    for entry, rows, convergences in zip(series['passes'], rows_by_pass,
                                         convergence_by_pass):
        directory = root / entry['block'] / entry['results']
        directory.mkdir(parents=True)
        (root / entry['block'] / 'COMPLETE').write_text('accepted\n')
        test = 'test-rep{0}'.format(entry['repetition'])
        cells = {}
        for ordinal, (row, convergence) in enumerate(zip(rows, convergences)):
            identity = an_identity(ordinal=ordinal, test=test,
                                   target=a_target(name=row[COLUMN['name']]))
            cells[json.dumps(identity, sort_keys=True)] = row
            (directory / '{0}.events.json'.format(row[COLUMN['name']])).write_text(
                json.dumps({
                    'run': {'name': row[COLUMN['name']], 'peers': 50,
                            'prefixes_per_peer': 100000, 'filter_test': None},
                    'measurements': {'convergence_s': convergence},
                    'findings': {'limiting_component': 'unresolved'},
                }))
        (directory / '{0}.progress.json'.format(test)).write_text(json.dumps(
            {'schema_version': 1, 'order': 'shuffle', 'seed': 7, 'cells': cells}))
        (directory / '{0}.csv'.format(test)).write_text(','.join(HEADER) + '\n')
    (root / 'metadata').mkdir()
    (root / 'metadata' / 'manifest.json').write_text(json.dumps({'blocks': {}}))
    return root


class TestFailedPassesAreNotObservations:
    """A row exists whether the run converged or not.

    `batch()` records `completed[cell_id] = bench(a)` for a FAILED run exactly
    as for a converged one, so reading the metric off the row because the row
    is there publishes a failure as an observation -- beside a summary that
    counted it out, in the same document.
    """

    def review_one_series(self, tmp_path, failed_pass=None):
        series = review.SERIES[0]
        rows, convergences = [], []
        for index in range(len(series['passes'])):
            failed = failed_pass == index
            rows.append([a_row('bird', elapsed=10 if failed else 90,
                               failed='FAILED' if failed else '',
                               message='did not converge' if failed else '',
                               received=0 if failed else 5000000),
                         a_row('gobgp', elapsed=50)])
            convergences.append([10.0 if failed else 90.0, 50.0])
        root = a_run_root(tmp_path, series, rows, convergences)
        problems = []
        document = review.review_series(str(root), series, {}, problems)
        cell = [record for record in document['cells']
                if record['name'] == 'bird'][0]
        return document, cell, problems

    def test_three_clean_passes_are_three_observations(self, tmp_path):
        document, cell, problems = self.review_one_series(tmp_path)
        assert document['summary']['cells'][0]['observations'] == 3
        assert cell['intervals']['convergence_s']['n'] == 3
        assert [entry['state'] for entry in cell['passes']] == ['observed'] * 3

    def test_a_failed_pass_is_not_a_value_in_the_decomposition(self, tmp_path):
        document, cell, _ = self.review_one_series(tmp_path, failed_pass=1)
        assert document['summary']['cells'][0]['observations'] == 2
        assert cell['passes'][1]['state'] == 'failed'
        assert cell['passes'][1][review.DECISION_METRIC] is None
        assert cell['intervals']['convergence_s']['n'] == 2, (
            'the failed run\'s convergence was averaged into the interval')
        assert cell['intervals']['convergence_s']['max'] == 90.0

    def test_a_failed_pass_invents_no_order_effect(self, tmp_path):
        '''A direction that exists only because one run did not converge.'''
        _, cell, _ = self.review_one_series(tmp_path, failed_pass=1)
        assert cell['order_relation'] in ('tied', 'too few observations')


class TestUnreadableDocuments:
    """`load_json()` returns None rather than raising, so nothing may assume.

    The selection in particular is hand-written between two sessions, and a
    malformed one is the expected failure here -- it must be named, not a
    traceback.
    """

    def test_an_unreadable_document_is_a_named_problem(self, tmp_path):
        broken = tmp_path / 'broken.json'
        broken.write_text('{"schema": ')
        problems = []
        assert review.read_json(str(broken), problems, 'it is truncated') is None
        assert problems[0]['severity'] == review.ERROR
        assert 'it is truncated' in problems[0]['message']

    def test_a_truncated_progress_file_costs_its_pass_and_not_a_traceback(
            self, tmp_path):
        series = review.SERIES[0]
        root = a_run_root(tmp_path, series, [[a_row('bird')]] * 3,
                          [[90.0]] * 3)
        entry = series['passes'][1]
        path = (root / entry['block'] / entry['results'] / 'test-rep2.progress.json')
        path.write_text('{"cells": ')
        problems = []
        assert review.review_series(str(root), series, {}, problems) is None
        assert any(entry['severity'] == review.ERROR
                   and 'progress file could not be read' in entry['message']
                   for entry in problems)
