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
                   # Far enough apart that the comparison itself is always
                   # resolvable; the tests that care set their own.
                   'median': 90.0 + 27.0 * n, 'stdev': 1.0,
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
            'dispersion_could_decide': False, 'gap': 1.0, 'resolution': 1.0,
            'rival': 'frr_c 10.0, peers=50',
            'reason': 'a gap of 1.0 cannot clear the 1.0 resolution of '
                      'elapsed (s) at any number of passes'}
        assert any('not separated from the cells drawn beside it' in message
                   for message in errors_for(a_selection(), reviews=[reviewed]))

    def test_a_pair_more_passes_could_separate_is_allowed(self):
        reviewed = a_review()
        reviewed['cells'][1]['expansion'] = {
            'dispersion_could_decide': True, 'gap': 6.0, 'resolution': 1.0,
            'rival': 'frr_c 10.0, peers=50'}
        assert errors_for(a_selection(), reviews=[reviewed]) == []

    def test_a_near_neighbour_does_not_veto_a_wide_comparison(self):
        """The comparison is between the cells the selection names.

        `bird 2.19.2` sits 1s from `frr_c 10.0` and 27s from the BIRD 3 cell
        it is actually being compared with. Refusing that expansion in the
        name of a cell the selection never mentions is a group-wide claim
        answering a question nobody asked.
        """
        reviewed = a_review(cells=('bird 2.19.2', 'frr_c 10.0', 'bird 3.3.2'))
        reviewed['cells'][0]['median'] = 90.0
        reviewed['cells'][1]['median'] = 91.0
        reviewed['cells'][2]['median'] = 117.0
        reviewed['cells'][0]['expansion'] = {
            'dispersion_could_decide': False, 'gap': 1.0, 'resolution': 1.0,
            'rival': 'frr_c 10.0, peers=50', 'reason': 'a gap of 1.0 ...'}
        document = a_selection(repetitions=[{
            'id': 'bird-2-against-bird-3', 'series': 'synthetic',
            'cells': ['bird 2.19.2, peers=50', 'bird 3.3.2, peers=50'],
            'passes_requested': 5, 'hypothesis': 'BIRD 3 is slower here',
            'variance_reason': 'a 27s gap the passes have not resolved'}])
        assert errors_for(document, reviews=[reviewed]) == []

    def test_a_comparison_of_single_observations_is_not_refused(self):
        """Every BIRD screen cell is one observation, by design.

        There is no dispersion there to reason about and the median is one
        sample that will move, so refusing the expansion refuses exactly the
        passes that would settle it -- the same rule `expansion_prospect()`
        applies to a rival with one observation, reached from the other side.
        """
        screen = a_review(series='screen-reload', passes=1, scope='scenario',
                          cells=('bird 2.19.2', 'bird 3.3.2'))
        for cell, median in zip(screen['cells'], (43.0, 43.5)):
            cell['median'] = median
            cell['stdev'] = None
        document = a_selection(repetitions=[{
            'id': 'bird-policy-recalculation', 'series': 'screen-reload',
            'cells': [cell['description'] for cell in screen['cells']],
            'passes_requested': 3, 'hypothesis': '3.3.2 reloads in half the time',
            'variance_reason': 'one observation per cell decides nothing'}])
        assert errors_for(document, reviews=[screen]) == []

    def test_a_comparison_about_another_measurement_is_not_judged_on_elapsed(self):
        '''`summary.py` computes the variance rule on `elapsed (s)` alone, so a
        policy-reload comparison refused on its elapsed medians would be
        refused on a number it was never about.'''
        reviewed = a_review(cells=('bird 2.19.2', 'bird 3.3.2'))
        reviewed['cells'][0]['median'] = 43.0
        reviewed['cells'][1]['median'] = 43.5
        document = a_selection(repetitions=[{
            'id': 'reload', 'series': 'synthetic', 'metric': 'reload_s',
            'cells': [cell['description'] for cell in reviewed['cells']],
            'passes_requested': 5, 'hypothesis': 'reload_s halves',
            'variance_reason': 'reload_s has no dispersion in this campaign'}])
        assert not [message for message in errors_for(document, reviews=[reviewed])
                    if 'no dispersion separates any pair here' in message]

    def test_a_misspelt_cell_does_not_disarm_the_per_cell_check(self):
        '''One real unseparable cell plus one typo used to skip both guards:
        the per-cell branch saw two names and the pairwise one resolved
        only one.'''
        reviewed = a_review()
        reviewed['cells'][1]['expansion'] = {
            'dispersion_could_decide': False, 'gap': 1.0, 'resolution': 1.0,
            'rival': 'bird 2.19.2, peers=50', 'reason': 'a gap of 1.0 ...'}
        document = a_selection()
        document['repetitions'][0]['cells'].append('frr_c 99.9, peers=50')
        messages = errors_for(document, reviews=[reviewed])
        assert any('is not a cell of synthetic' in message for message in messages)
        assert any('not separated from the cells drawn beside it' in message
                   for message in messages)

    def test_a_comparison_no_dispersion_can_resolve_is_refused(self):
        reviewed = a_review(cells=('bird 2.19.2', 'frr_c 10.0', 'bird 3.3.2'))
        reviewed['cells'][0]['median'] = 90.0
        reviewed['cells'][1]['median'] = 90.5
        reviewed['cells'][2]['median'] = 117.0
        document = a_selection(repetitions=[{
            'id': 'bird-2-against-frr', 'series': 'synthetic',
            'cells': ['bird 2.19.2, peers=50', 'frr_c 10.0, peers=50'],
            'passes_requested': 5, 'hypothesis': 'they differ',
            'variance_reason': 'the medians are ordered'}])
        assert any('no dispersion separates any pair here' in message
                   for message in errors_for(document, reviews=[reviewed]))

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


def a_summary_cell(ordinal, description, median, stdev, verdict='expand',
                   peers=50, prefixes=100000, filter='None'):
    return {
        'cell': ordinal, 'description': description,
        'identity': {'peers': peers, 'prefixes': prefixes, 'filter': filter},
        'metrics': {review.DECISION_METRIC: {'median': median, 'stdev': stdev}},
        'variance': {'verdict': verdict},
    }


class TestExpansionProspect:
    """Whether more passes could change a verdict is a claim about every rival.

    `separated` means distinguishable from every cell drawn beside it, so a
    cell half a second from one rival cannot reach it however many passes are
    run -- even when the rival that happened to *bind* the verdict is ten
    seconds away. The verdict names the binding rival because that is the
    closest call; this question needs the nearest one.
    """

    def prospect(self, rival_medians, median=100.0, stdev=3.0,
                 rival_stdev=0.1):
        cell = a_summary_cell(0, 'A', median, stdev)
        rivals = [a_summary_cell(n + 1, chr(66 + n), rival_median, rival_stdev)
                  for n, rival_median in enumerate(rival_medians)]
        return review.expansion_prospect(cell, rivals)

    def test_a_far_binding_rival_does_not_hide_a_near_one(self):
        found = self.prospect([100.5, 110.0])
        assert found['dispersion_could_decide'] is False
        assert found['rival'] == 'B'
        assert '0.5' in found['reason']

    def test_a_gap_above_the_resolution_can_still_be_decided(self):
        found = self.prospect([106.0, 110.0])
        assert found['dispersion_could_decide'] is True
        assert found['rival'] == 'B'

    def test_a_separated_cell_has_no_prospect_to_report(self):
        cell = a_summary_cell(0, 'A', 100.0, 1.0, verdict='separated')
        assert review.expansion_prospect(cell, []) is None

    def test_a_cell_with_no_rival_median_reports_nothing(self):
        cell = a_summary_cell(0, 'A', 100.0, 1.0)
        blank = a_summary_cell(1, 'B', None, None)
        assert review.expansion_prospect(cell, [blank]) is None

    def test_a_cell_with_no_median_of_its_own_reports_nothing(self):
        '''Reached before the rivals are measured, not after: subtracting from
        None is a TypeError that costs the whole review.'''
        cell = a_summary_cell(0, 'A', None, None)
        assert review.expansion_prospect(
            cell, [a_summary_cell(1, 'B', 100.0, 1.0)]) is None

    def test_a_rival_with_one_observation_does_not_veto_an_expansion(self):
        """A provisional median is not something to rule against.

        `summary.py` decides the verdict on rivals that have a dispersion for
        exactly this reason, and `separated` is withheld against an unjudged
        near rival under its own reason -- one that *is* removable by giving
        that rival more passes. Counting it here would refuse a legitimate
        expansion on the strength of one observation.
        """
        cell = a_summary_cell(0, 'A', 100.0, 3.0)
        near_but_unjudged = a_summary_cell(1, 'B', 100.5, None)
        far_but_measurable = a_summary_cell(2, 'C', 105.0, 3.0)
        found = review.expansion_prospect(
            cell, [near_but_unjudged, far_but_measurable])
        assert found['dispersion_could_decide'] is True
        assert found['rival'] == 'C'

    def test_float_noise_does_not_clear_the_resolution(self):
        '''A nominal 1.0s gap that subtracts to 1.0000000000000002.

        `summary.py` publishes every gap through its own rounding; comparing a
        raw subtraction against the resolution reported a pair no dispersion
        can separate as one more passes could decide -- and would have
        approved hours of measurement on it. Medians 1.2 and 2.2, which is a
        pair this exact subtraction misreports.
        '''
        assert abs(2.2 - 1.2) > 1.0, 'this pair no longer exercises the noise'
        found = self.prospect([2.2], median=1.2)
        assert found['gap'] == 1.0
        assert found['dispersion_could_decide'] is False


class TestAttributionOverPasses:
    def test_a_failed_pass_is_not_a_second_opinion(self, tmp_path):
        """`['unresolved', None]` is not a disagreement about a component.

        It is one pass that failed, described in the same clause as an
        attribution that differs -- which is the distinction this campaign
        keeps at every other level of aggregation.
        """
        series = review.SERIES[0]
        rows, convergences = [], []
        for index in range(len(series['passes'])):
            failed = index == 1
            rows.append([a_row('bird', failed='FAILED' if failed else '')])
            convergences.append([90.0])
        root = a_run_root(tmp_path, series, rows, convergences)
        problems = []
        document = review.review_series(str(root), series, {}, problems)
        cell = document['cells'][0]
        assert cell['limiting_component'] == 'unresolved'
        assert cell['limiting_component_observations'] == {
            'passes': {'observed': 2, 'failed': 1}, 'attributed': 2}, (
                'a pass that failed and a pass that never ran must not be one '
                'clause, and the count behind the verdict is its own fact')
        assert not [entry for entry in problems
                    if 'was attributed to' in entry['message']]


class TestAnObsoleteHeaderCostsItsSeries:
    def test_a_header_missing_a_column_is_a_problem_not_a_traceback(self, tmp_path):
        """Three passes can agree on a header the summary cannot read.

        The per-pass equality check only catches passes that disagree with
        each other; `summarize_batch()` refuses a header that does not carry a
        column it reads, and uncaught that killed the whole review -- leaving
        the runner pointing at a `review/` directory it had just removed.
        """
        series = review.SERIES[0]
        root = a_run_root(tmp_path, series, [[a_row('bird')]] * 3, [[90.0]] * 3)
        short = [name for name in HEADER if name != 'max foreign cpu %']
        for entry in series['passes']:
            path = (root / entry['block'] / entry['results'] /
                    'test-rep{0}.csv'.format(entry['repetition']))
            path.write_text(','.join(short) + '\n')
        problems = []
        assert review.review_series(str(root), series, {}, problems) is None
        assert any('max foreign cpu %' in entry['message'] for entry in problems)


class TestSelectionScopeIsDeliberate:
    def test_a_named_cell_without_a_dispersion_does_not_refuse_the_comparison(self):
        """Looks like a hole in the guards, and is the right answer.

        A cell whose group-wide prospect is `false` can be selected against a
        named cell that has no dispersion, and nothing refuses it. A cell with
        no dispersion has one observation -- by design for every screen cell,
        and by accident when passes fail -- and the passes being asked for are
        exactly what would give it one. Refusing on the strength of its
        provisional median refuses the measurement that would settle it, which
        is the error this file made once already.
        """
        reviewed = a_review(cells=('bird 2.19.2', 'frr_c 10.0', 'bird 3.3.2'))
        reviewed['cells'][0]['median'] = 90.0
        reviewed['cells'][0]['expansion'] = {
            'dispersion_could_decide': False, 'gap': 0.5, 'resolution': 1.0,
            'rival': 'frr_c 10.0, peers=50', 'reason': 'a gap of 0.5 ...'}
        reviewed['cells'][1]['median'] = 90.5
        reviewed['cells'][1]['stdev'] = None
        document = a_selection(repetitions=[{
            'id': 'bird-2-against-frr-10.0', 'series': 'synthetic',
            'cells': ['bird 2.19.2, peers=50', 'frr_c 10.0, peers=50'],
            'passes_requested': 5, 'hypothesis': 'they differ',
            'variance_reason': 'one of the two has a single observation'}])
        assert errors_for(document, reviews=[reviewed]) == []


class TestSelectionDocumentShape:
    def test_a_repetition_that_is_not_an_object_is_named(self):
        '''`"repetitions": ["oops"]` used to raise out of the whole review,
        which left the runner naming a `review/` directory that was never
        written.'''
        messages = errors_for(a_selection(repetitions=['oops']))
        assert any('not an object' in message for message in messages)

    def test_a_series_that_was_read_and_dropped_is_not_called_unknown(self):
        messages = []
        review.validate_selection(a_selection(), [], NO_EXCLUSIONS, messages,
                                  attempted={'synthetic'})
        assert any('was not reviewed; see its error above' in entry['message']
                   for entry in messages)

    def test_a_series_that_does_not_exist_still_says_so(self):
        messages = []
        review.validate_selection(a_selection(), [], NO_EXCLUSIONS, messages,
                                  attempted=set())
        assert any('is not a reviewed series' in entry['message']
                   for entry in messages)
