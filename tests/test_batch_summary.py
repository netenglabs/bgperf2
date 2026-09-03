'''Summarising the passes of a repeated matrix, without hiding any of them.

Three observations of a cell are only worth having if something says how far
apart they were, and a summary is only worth having if the observations behind
it are still there to argue with. The rules that matter here are the ones about
what is *not* published: a dispersion over one run, a coefficient of variation
over a column of zeros, and a distribution over passes that ran against
different images are each a number that would read as a finding and is not one.
'''
from argparse import Namespace

import pytest
import yaml

import base
import bgperf2
import summary


HEADER = [f.strip() for f in bgperf2.stats_header().split(',')]


@pytest.fixture
def fake_img_exists(monkeypatch):
    '''Patch img_exists in both modules -- bgperf2 does `from base import *`.'''
    def _install(predicate):
        monkeypatch.setattr(base, 'img_exists', predicate)
        monkeypatch.setattr(bgperf2, 'img_exists', predicate)
    return _install


def a_row(**overrides):
    '''A stats row of the shape create_output_stats() builds, by column name.'''
    values = {
        'name': 'bird', 'target': 'bird', 'version': '2.19.2', 'peers': '1',
        'prefixes per peer': '10', 'required': 10, 'received': 10,
        'monitor (s)': 2, 'elapsed (s)': 40, 'prefix received (s)': 5,
        'testers (s)': 35, 'total time': 60.0, 'max cpu %': 100,
        'max mem (GB)': 1.0, 'min idle%': 90, 'min free mem (GB)': 50.0,
        'flags': '', 'date': '2026-09-03', 'cores': '32', 'Mem (GB)': '64.00GB',
        'tester errors': 0, 'tester timeouts': 0, 'failed': '', 'MSG': '',
        'filters': '', 'max foreign cpu %': 0, 'target image': 'bgperf/bird:2.19.2',
        'tester version': '2.19.2', 'monitor version': '3.38.0',
    }
    values.update(overrides)
    assert set(values) == set(HEADER), 'the fixture row must match the header'
    return [values[column] for column in HEADER]


def a_group(rows, name='bird', ordinal=0, description=None, identity=None):
    '''One cell whose passes produced these rows; None for a pass that did not run.'''
    axes = {'peers': 1, 'prefixes': 10, 'filter': 'None',
            'target': {'name': 'bird'}}
    axes.update(identity or {})
    return {
        'ordinal': ordinal,
        'name': name,
        'description': description or '{0}, peers=1, prefixes=10, filter=None'.format(name),
        'identity': axes,
        'passes': [{'repetition': i, 'row': row} for i, row in enumerate(rows, 1)],
    }


def a_cell_taking(elapsed, name='bird', ordinal=0, **kwargs):
    '''One cell of the matrix whose passes took these elapsed times.'''
    return a_group([a_row(**{'elapsed (s)': value}) for value in elapsed],
                   name=name, ordinal=ordinal,
                   description=kwargs.pop('description', name), **kwargs)


def variance_of(*groups):
    '''The rule's verdict per cell, keyed by the cell's name.'''
    document = summary.summarize_batch('sum', HEADER, list(groups))
    return {cell['name']: cell['variance'] for cell in document['cells']}


def a_test(**overrides):
    test = {
        'name': 'sum',
        'neighbors': [1],
        'prefixes': [10],
        'filter_test': ['None'],
        'targets': [{'name': 'bird'}],
    }
    test.update(overrides)
    return test


class TestSummarizeMetric:
    def test_the_statistics_over_several_observations(self):
        m = summary.summarize_metric([40, 42, 47])
        assert m['n'] == 3
        assert m['values'] == [40, 42, 47]
        assert m['median'] == 42
        assert m['min'] == 40
        assert m['max'] == 47
        assert m['mean'] == pytest.approx(43.0)
        assert m['stdev'] == pytest.approx(3.605551, abs=1e-6)
        assert m['cv_percent'] == pytest.approx(8.385, abs=1e-3)
        assert 'withheld' not in m

    def test_the_dispersion_is_the_sample_one(self):
        '''n-1: three passes are a sample of what the machine does, and the
        population formula understates the spread of one -- to exactly 0 at
        n=1, which is the lie this module exists to avoid telling.
        '''
        m = summary.summarize_metric([1, 2, 3])
        assert m['stdev'] == pytest.approx(1.0)

    def test_the_extremes_are_observations_and_are_not_rounded(self):
        '''A summary must not report an extreme no run produced.'''
        m = summary.summarize_metric([1.1234567891, 2.9876543219])
        assert m['min'] == 1.1234567891
        assert m['max'] == 2.9876543219
        assert m['mean'] == round((1.1234567891 + 2.9876543219) / 2, 6)

    def test_one_observation_withholds_every_dispersion(self):
        '''A CV of 0 over one run would say the measurement is perfectly
        repeatable on the strength of never having been repeated.
        '''
        m = summary.summarize_metric([42])
        assert m['median'] == 42 and m['min'] == 42 and m['max'] == 42
        assert m['stdev'] is None
        assert m['cv_percent'] is None
        assert m['withheld'] == {'stdev': summary.NEEDS_TWO,
                                 'cv_percent': summary.NEEDS_TWO}

    def test_a_column_of_zeros_has_a_dispersion_but_no_relative_one(self):
        '''`tester errors` is 0 in every good run: the spread is real and zero,
        the ratio to the mean is a division nobody can do.
        '''
        m = summary.summarize_metric([0, 0, 0])
        assert m['stdev'] == 0.0
        assert m['cv_percent'] is None
        assert m['withheld'] == {'cv_percent': summary.MEAN_NOT_POSITIVE}

    def test_no_observation_publishes_no_statistic(self):
        m = summary.summarize_metric([])
        assert m['n'] == 0
        assert all(m[name] is None for name in
                   ('mean', 'median', 'min', 'max', 'stdev', 'cv_percent'))
        assert set(m['withheld'].values()) == {summary.NO_OBSERVATION}

    def test_a_non_numeric_observation_withholds_rather_than_drops(self):
        '''Dropping the offending pass would change n without saying so, which
        is the one thing a dispersion cannot survive.
        '''
        m = summary.summarize_metric([40, '', 42])
        assert m['values'] == [40, '', 42]
        assert m['median'] is None
        assert set(m['withheld'].values()) == {summary.NON_NUMERIC}

    @pytest.mark.parametrize('value', [float('nan'), float('inf')])
    def test_a_non_finite_value_is_not_a_number(self, value):
        m = summary.summarize_metric([40, value])
        assert set(m['withheld'].values()) == {summary.NON_NUMERIC}

    def test_a_non_finite_value_is_published_as_something_json_can_hold(self):
        '''json.dump writes a nan as a bare word that jq rejects, so the fact
        that a pass reported one is kept as its repr instead.
        '''
        import json
        m = summary.summarize_metric([40, float('nan')])
        assert m['values'] == [40, 'nan']
        json.dumps(m, allow_nan=False)

    def test_the_never_sampled_sentinel_is_not_an_observation(self):
        '''`min_free` starts above every real value so the first sample can
        only lower it. Averaging an untouched sentinel publishes a machine with
        a petabyte free.
        '''
        m = summary.summarize_metric([931322.575], unsampled=931322.575)
        assert m['values'] == [None]
        assert m['median'] is None
        assert set(m['withheld'].values()) == {summary.UNSAMPLED}

    def test_one_unsampled_pass_withholds_the_column_for_the_whole_cell(self):
        '''Two real values beside the sentinel would publish a mean of ~310,474
        GB and a CV of 173% on a 64 GB box -- which reads as a finding about
        the daemon. Dropping that pass would change n without saying so.
        '''
        m = summary.summarize_metric([50.0, 931322.575, 50.1],
                                     unsampled=931322.575)
        assert m['values'] == [50.0, None, 50.1]
        assert m['cv_percent'] is None
        assert set(m['withheld'].values()) == {summary.UNSAMPLED}

    def test_a_real_value_is_not_mistaken_for_the_sentinel(self):
        m = summary.summarize_metric([50.0, 50.1], unsampled=931322.575)
        assert m['values'] == [50.0, 50.1]
        assert 'withheld' not in m

    def test_no_sentinel_is_assumed_when_none_is_given(self):
        m = summary.summarize_metric([931322.575, 931322.575])
        assert m['median'] == 931322.575

    def test_a_boolean_is_not_a_number(self):
        m = summary.summarize_metric([True, False])
        assert set(m['withheld'].values()) == {summary.NON_NUMERIC}


class TestSummarizeCell:
    def test_a_metric_is_summarised_from_the_named_column(self):
        cell = summary.summarize_cell(HEADER, a_group([
            a_row(**{'elapsed (s)': 40}),
            a_row(**{'elapsed (s)': 44}),
        ]))
        assert cell['metrics']['elapsed (s)']['values'] == [40, 44]
        assert cell['metrics']['elapsed (s)']['median'] == 42

    def test_every_metric_column_is_read(self):
        cell = summary.summarize_cell(HEADER, a_group([a_row()]))
        assert set(cell['metrics']) == set(summary.METRIC_COLUMNS)

    def test_the_legacy_column_keeps_its_name(self):
        '''Renaming it here would be the silent redefinition the plan forbids.'''
        assert 'testers (s)' in summary.METRIC_COLUMNS

    def test_a_failed_pass_is_counted_and_named_but_not_averaged(self):
        '''Averaging it in would put a crashed run's elapsed beside two good
        ones; dropping it silently would make two passes of three look like a
        complete, tight distribution.
        '''
        cell = summary.summarize_cell(HEADER, a_group([
            a_row(**{'elapsed (s)': 40}),
            a_row(**{'elapsed (s)': 3, 'failed': 'FAILED', 'MSG': 'stuck at 0'}),
            a_row(**{'elapsed (s)': 44}),
        ]))
        assert cell['observations'] == 2
        assert cell['passes_expected'] == 3
        assert cell['observed_passes'] == [1, 3]
        assert cell['metrics']['elapsed (s)']['values'] == [40, 44]
        assert cell['passes'][1] == {'repetition': 2, 'state': summary.FAILED,
                                     'message': 'stuck at 0'}

    def test_a_pass_that_has_not_run_is_apart_from_one_that_failed(self):
        '''One is a result and the other is unfinished work; an operator does
        something different about each.
        '''
        cell = summary.summarize_cell(HEADER, a_group([
            a_row(), a_row(**{'failed': 'FAILED'}), None]))
        assert [p['state'] for p in cell['passes']] == [
            summary.OBSERVED, summary.FAILED, summary.NOT_RUN]
        assert cell['observations'] == 1

    def test_the_min_free_sentinel_is_withheld_through_the_cell(self):
        cell = summary.summarize_cell(
            HEADER, a_group([a_row(**{'min free mem (GB)': 931322.575})]),
            unavailable={'min free mem (GB)': 931322.575})
        assert cell['metrics']['min free mem (GB)']['median'] is None
        # Every other column of that pass is still an observation.
        assert cell['metrics']['elapsed (s)']['median'] == 40
        assert cell['observations'] == 1

    def test_a_row_that_is_not_this_headers_width_costs_only_its_own_pass(self):
        '''`--resume` onto a progress file written before a column was appended
        is a supported path, and such a row is one field short. Indexed against
        this header it raises IndexError, which the caller catches into no
        summary at all for the whole test.
        '''
        cell = summary.summarize_cell(HEADER, a_group([
            a_row(**{'elapsed (s)': 40}), a_row()[:-1],
            a_row(**{'elapsed (s)': 44})]))
        assert [p['state'] for p in cell['passes']] == [
            summary.OBSERVED, summary.UNREADABLE, summary.OBSERVED]
        assert 'field(s)' in cell['passes'][1]['message']
        assert cell['observations'] == 2
        assert cell['metrics']['elapsed (s)']['values'] == [40, 44]

    def test_an_unreadable_pass_is_apart_from_a_failed_one(self):
        '''One says nothing about the daemon; the other is a result.'''
        assert summary.UNREADABLE != summary.FAILED

    def test_a_cell_whose_every_pass_failed_still_says_which_cell_it_was(self):
        cell = summary.summarize_cell(HEADER, a_group([
            a_row(**{'failed': 'FAILED'}), a_row(**{'failed': 'FAILED'})]))
        assert cell['observations'] == 0
        assert cell['name'] == 'bird'
        assert cell['identity']['peers'] == 1
        assert cell['identity']['prefixes'] == 10

    def test_the_observed_passes_are_in_the_order_of_every_metrics_values(self):
        cell = summary.summarize_cell(HEADER, a_group([
            None,
            a_row(**{'elapsed (s)': 44}),
            a_row(**{'elapsed (s)': 40}),
        ]))
        assert cell['observed_passes'] == [2, 3]
        assert cell['metrics']['elapsed (s)']['values'] == [44, 40]

    def test_provenance_the_passes_agree_on_is_one_value(self):
        cell = summary.summarize_cell(HEADER, a_group([a_row(), a_row()]))
        assert cell['provenance']['target image'] == 'bgperf/bird:2.19.2'
        assert 'inconsistent' not in cell

    def test_passes_that_ran_against_different_images_are_not_averaged_over(self):
        '''This is the gcov trap one layer up: a freshly built version beside a
        cached one is not two observations of the same thing.
        '''
        cell = summary.summarize_cell(HEADER, a_group([
            a_row(**{'target image': 'bgperf/bird:2.19.2'}),
            a_row(**{'target image': 'bgperf/bird:latest'}),
        ]))
        assert cell['inconsistent']['target image'] == [
            'bgperf/bird:2.19.2', 'bgperf/bird:latest']
        assert cell['provenance']['target image'] == [
            'bgperf/bird:2.19.2', 'bgperf/bird:latest']
        # The measurement is still published; the disagreement is what is said
        # out loud about it.
        assert cell['metrics']['elapsed (s)']['n'] == 2

    def test_a_disagreement_about_the_required_count_is_surfaced(self):
        cell = summary.summarize_cell(HEADER, a_group([
            a_row(required=10), a_row(required=11)]))
        assert cell['inconsistent']['required'] == [10, 11]

    def test_the_configured_size_is_carried_beside_what_was_received(self):
        cell = summary.summarize_cell(HEADER, a_group([a_row(required=10)]))
        assert cell['identity']['required'] == 10
        assert cell['metrics']['received']['median'] == 10


class TestSummarizeBatch:
    def test_the_document_names_its_schema_and_its_passes(self):
        document = summary.summarize_batch(
            'sum', HEADER, [a_group([a_row(), a_row()])], repetitions=2)
        assert document['schema'] == summary.SUMMARY_SCHEMA
        assert document['test'] == 'sum'
        assert document['repetitions'] == 2
        assert len(document['cells']) == 1

    def test_the_sentinel_reaches_every_cell(self):
        document = summary.summarize_batch(
            'sum', HEADER, [a_group([a_row(**{'min free mem (GB)': 931322.575})]),
                            a_group([a_row(**{'min free mem (GB)': 931322.575})],
                                    ordinal=1)],
            unavailable={'min free mem (GB)': 931322.575})
        for cell in document['cells']:
            assert cell['metrics']['min free mem (GB)']['median'] is None

    def test_a_header_that_lost_a_column_is_named_not_guessed(self):
        with pytest.raises(ValueError, match='total time'):
            summary.summarize_batch(
                'sum', [c for c in HEADER if c != 'total time'], [])

    def test_every_metric_column_exists_in_the_stats_header(self):
        '''summary.py reads the row by name; the header is the contract, and it
        has drifted by a column once already.
        '''
        for column in (summary.METRIC_COLUMNS + summary.PROVENANCE_COLUMNS
                       + summary.ROW_IDENTITY_COLUMNS
                       + (summary.FAILED_COLUMN, summary.MESSAGE_COLUMN)):
            assert column in HEADER, column


class TestDescribeBatchSummary:
    def test_a_single_pass_test_prints_nothing(self):
        '''Every dispersion in it is withheld; a block of "CV unavailable" says
        only that the test asked for one pass.
        '''
        document = summary.summarize_batch(
            'sum', HEADER, [a_group([a_row()])], repetitions=1)
        assert summary.describe_batch_summary(document) == []

    def test_a_repeated_test_reports_its_spread(self):
        document = summary.summarize_batch('sum', HEADER, [a_group([
            a_row(**{'elapsed (s)': 40, 'total time': 60.0}),
            a_row(**{'elapsed (s)': 44, 'total time': 64.0}),
        ])], repetitions=2)
        lines = summary.describe_batch_summary(document, path='results/sum.summary.json')

        assert 'repeatability over 2 passes' in lines[0]
        assert 'results/sum.summary.json' in lines[0]
        assert 'bird, peers=1, prefixes=10, filter=None: 2 of 2 passes observed' in lines[1]
        assert 'elapsed (s) median 42.0 (40-44)' in lines[1]
        assert 'CV' in lines[1]

    def test_a_failed_pass_is_named_under_its_cell(self):
        document = summary.summarize_batch('sum', HEADER, [a_group([
            a_row(), a_row(**{'failed': 'FAILED', 'MSG': 'stuck at 0'})])],
            repetitions=2)
        lines = summary.describe_batch_summary(document)
        assert any('1 of 2 passes observed' in line for line in lines)
        assert any('pass 2: failed (stuck at 0)' in line for line in lines)

    def test_a_cell_with_no_description_falls_back_to_its_name(self):
        group = a_group([a_row()])
        del group['description']
        cell = summary.summarize_cell(HEADER, group)
        assert cell['description'] == 'bird'

    def test_an_unreadable_pass_is_named_under_its_cell(self):
        document = summary.summarize_batch('sum', HEADER, [a_group([
            a_row(), a_row()[:-1]])], repetitions=2)
        lines = summary.describe_batch_summary(document)
        assert any('pass 2: unreadable' in line for line in lines)

    def test_a_disagreement_is_printed_even_for_a_single_pass_document(self):
        '''It is the finding, not the statistic beside it.'''
        document = summary.summarize_batch('sum', HEADER, [a_group([
            a_row(**{'monitor version': '3.38.0'}),
            a_row(**{'monitor version': '3.37.0'})])], repetitions=1)
        lines = summary.describe_batch_summary(document)
        assert len(lines) == 1
        assert 'disagree on monitor version' in lines[0]


class TestBatchSummaryGroups:
    def groups(self, test, completed=None):
        targets = bgperf2.expand_target_versions(test['targets'])
        cells = bgperf2.expand_batch_cells(test, targets)
        return bgperf2.batch_summary_groups(test['name'], cells, completed or {})

    def test_the_passes_of_one_cell_group_together(self):
        groups = self.groups(a_test(repetitions=3, neighbors=[1, 2]))
        assert [g['ordinal'] for g in groups] == [0, 1]
        assert [[p['repetition'] for p in g['passes']] for g in groups] == [
            [1, 2, 3], [1, 2, 3]]

    def test_a_group_is_one_cell_not_one_target(self):
        groups = self.groups(a_test(neighbors=[1, 2], prefixes=[10, 20]))
        assert len(groups) == 4
        assert [g['identity']['peers'] for g in groups] == [1, 1, 2, 2]
        assert [g['identity']['prefixes'] for g in groups] == [10, 20, 10, 20]

    def test_two_cells_of_one_target_are_described_apart(self):
        '''`bird: 3 of 3 passes observed` printed twice names neither cell.'''
        groups = self.groups(a_test(neighbors=[1, 2]))
        descriptions = [g['description'] for g in groups]
        assert len(set(descriptions)) == 2
        assert 'peers=1' in descriptions[0] and 'peers=2' in descriptions[1]

    def test_a_description_names_the_cell_not_the_pass(self):
        '''The passes are inside the group, so `repetition 1/3` in its own
        heading would name one of them.
        '''
        groups = self.groups(a_test(repetitions=3))
        assert 'repetition' not in groups[0]['description']

    def test_the_group_name_carries_no_repetition_suffix(self):
        '''The passes are inside the group; a group called `bird #1` would name
        one of them.
        '''
        groups = self.groups(a_test(repetitions=2))
        assert [g['name'] for g in groups] == ['bird']

    def test_the_whole_target_entry_is_carried(self):
        '''`threads`, `mrt_file` and `image` are what a run was asked for and
        none of them reach the run name.
        '''
        groups = self.groups(a_test(targets=[{'name': 'bird', 'threads': 4}]))
        assert groups[0]['identity']['target']['threads'] == 4

    def test_a_cell_with_no_result_yet_carries_a_pass_with_no_row(self):
        groups = self.groups(a_test(repetitions=2))
        assert [p['row'] for p in groups[0]['passes']] == [None, None]

    def test_a_completed_cell_is_matched_by_its_id(self):
        test = a_test(repetitions=2)
        targets = bgperf2.expand_target_versions(test['targets'])
        cells = bgperf2.expand_batch_cells(test, targets)
        completed = {bgperf2.batch_cell_id('sum', cells[1]): a_row()}
        groups = bgperf2.batch_summary_groups('sum', cells, completed)
        assert [p['row'] is None for p in groups[0]['passes']] == [True, False]

    def test_grouping_does_not_depend_on_the_order_the_cells_ran_in(self):
        '''`ordinal` is a cell's place in the matrix, which is the one field a
        permuted execution order does not touch.
        '''
        test = a_test(repetitions=2, neighbors=[1, 2], order='shuffle', seed=7)
        targets = bgperf2.expand_target_versions(test['targets'])
        cells = bgperf2.expand_batch_cells(test, targets)
        sequenced = bgperf2.order_batch_cells('sum', cells, 'shuffle', 7)
        assert [c['ordinal'] for c in sequenced] != [c['ordinal'] for c in cells]
        assert (bgperf2.batch_summary_groups('sum', cells, {})
                == bgperf2.batch_summary_groups('sum', sequenced, {}))


class TestUnsampledRowValues:
    def test_the_sentinel_is_named_in_the_units_the_row_carries(self):
        '''One formatter, so the sentinel's row form cannot drift from the
        real one.
        '''
        assert bgperf2.unsampled_row_values() == {
            'min free mem (GB)': bgperf2.row_gb(bgperf2.UNSAMPLED_MIN_FREE),
            'max mem (GB)': bgperf2.row_gb(0)}

    def test_it_is_the_value_an_unsampled_run_actually_writes(self, bench_args,
                                                              bench_stats):
        bench_stats['min_free'] = bgperf2.UNSAMPLED_MIN_FREE
        row = bgperf2.create_output_stats(bench_args, 'v1', bench_stats)
        named = dict(zip(HEADER, row))
        assert named['min free mem (GB)'] == \
            bgperf2.unsampled_row_values()['min free mem (GB)']

    def test_an_unsampled_target_memory_peak_is_named_too(self, bench_args,
                                                            bench_stats):
        '''`max_mem` starts at 0 so the first sample can only raise it, and
        `Container.stats()` has no `try` around its walk. A cell reading 1.0,
        0.0, 1.0 publishes an 87% CV invented by a dead sampler -- beside a
        `min free mem (GB)` that is correctly withheld.
        '''
        bench_stats['max_mem'] = 0
        row = bgperf2.create_output_stats(bench_args, 'v1', bench_stats)
        named = dict(zip(HEADER, row))
        assert named['max mem (GB)'] == \
            bgperf2.unsampled_row_values()['max mem (GB)']

    @pytest.mark.parametrize('column', ['min idle%', 'max cpu %'])
    def test_an_ambiguous_sentinel_is_deliberately_left_alone(self, column):
        '''`min idle%` starts at 100 and `max cpu %` rounds to 0 from any peak
        under 0.5%: both are values a real run can report, and withholding
        them would cost a measured column.
        '''
        assert column not in bgperf2.unsampled_row_values()

    def test_the_columns_it_names_are_summarised_columns(self):
        for column in bgperf2.unsampled_row_values():
            assert column in summary.METRIC_COLUMNS


class TestBatchPublishesTheSummary:
    def write(self, tmp_path, **overrides):
        config = tmp_path / 'sum.yaml'
        config.write_text(yaml.safe_dump({'tests': [a_test(**overrides)]}))
        return str(config)

    def run(self, tmp_path, monkeypatch, rows, **overrides):
        monkeypatch.setattr(bgperf2, 'create_batch_graphs', lambda *a, **k: None)
        supplied = iter(rows)
        # Each pass names its own row, exactly as create_output_stats() does.
        monkeypatch.setattr(
            bgperf2, 'bench',
            lambda a: a_row(**dict(next(supplied), name=bgperf2.run_name(a))))
        bgperf2.batch(Namespace(
            batch_config=self.write(tmp_path, **overrides),
            results_dir=str(tmp_path)))

    def test_a_repeated_batch_writes_a_summary_beside_its_csv(
            self, fake_img_exists, tmp_path, monkeypatch, capsys):
        import json
        fake_img_exists(lambda name: True)
        self.run(tmp_path, monkeypatch,
                 [{'elapsed (s)': 40}, {'elapsed (s)': 44}], repetitions=2)

        document = json.loads((tmp_path / 'sum.summary.json').read_text())
        assert document['repetitions'] == 2
        cell = document['cells'][0]
        assert cell['metrics']['elapsed (s)']['values'] == [40, 44]
        assert cell['metrics']['elapsed (s)']['median'] == 42
        # The rows themselves are still the record.
        csv_text = (tmp_path / 'sum.csv').read_text()
        assert 'bird #1' in csv_text and 'bird #2' in csv_text
        assert 'repeatability over 2 passes' in capsys.readouterr().out

    def test_a_stale_summary_does_not_outlive_the_batch_it_described(
            self, fake_img_exists, tmp_path, monkeypatch):
        '''A document still claiming three passes that were discarded is worse
        than no document, so it is written before the first cell runs.
        '''
        import json
        fake_img_exists(lambda name: True)
        monkeypatch.setattr(bgperf2, 'create_batch_graphs', lambda *a, **k: None)
        (tmp_path / 'sum.summary.json').write_text('{"cells": ["stale"]}')

        def dies(a):
            raise RuntimeError('interrupted')

        monkeypatch.setattr(bgperf2, 'bench', dies)
        with pytest.raises(RuntimeError, match='interrupted'):
            bgperf2.batch(Namespace(
                batch_config=self.write(tmp_path, repetitions=3),
                results_dir=str(tmp_path)))

        document = json.loads((tmp_path / 'sum.summary.json').read_text())
        assert document['repetitions'] == 3
        assert [p['state'] for p in document['cells'][0]['passes']] == [
            summary.NOT_RUN] * 3

    def test_a_single_pass_batch_prints_no_summary_block(
            self, fake_img_exists, tmp_path, monkeypatch, capsys):
        fake_img_exists(lambda name: True)
        self.run(tmp_path, monkeypatch, [{}])
        assert 'repeatability' not in capsys.readouterr().out

    def test_the_summary_survives_a_batch_that_died_part_way(
            self, fake_img_exists, tmp_path, monkeypatch):
        '''A batch that dies in its third pass should still say what its first
        two measured.
        '''
        import json
        fake_img_exists(lambda name: True)
        monkeypatch.setattr(bgperf2, 'create_batch_graphs', lambda *a, **k: None)

        def interrupted(a):
            if a.repetition == 2:
                raise RuntimeError('interrupted')
            return a_row(**{'elapsed (s)': 40})

        monkeypatch.setattr(bgperf2, 'bench', interrupted)
        with pytest.raises(RuntimeError, match='interrupted'):
            bgperf2.batch(Namespace(
                batch_config=self.write(tmp_path, repetitions=3),
                results_dir=str(tmp_path)))

        cell = json.loads((tmp_path / 'sum.summary.json').read_text())['cells'][0]
        assert cell['observations'] == 1
        assert [p['state'] for p in cell['passes']] == [
            summary.OBSERVED, summary.NOT_RUN, summary.NOT_RUN]

    def test_an_unsampled_target_peak_is_not_published_as_a_measurement(
            self, fake_img_exists, tmp_path, monkeypatch):
        import json
        fake_img_exists(lambda name: True)
        self.run(tmp_path, monkeypatch,
                 [{'max mem (GB)': 1.0}, {'max mem (GB)': 0.0},
                  {'max mem (GB)': 1.0}], repetitions=3)

        cell = json.loads((tmp_path / 'sum.summary.json').read_text())['cells'][0]
        metric = cell['metrics']['max mem (GB)']
        assert metric['values'] == [1.0, None, 1.0]
        assert metric['cv_percent'] is None
        assert set(metric['withheld'].values()) == {summary.UNSAMPLED}

    def test_an_unsampled_memory_column_is_not_published_as_a_measurement(
            self, fake_img_exists, tmp_path, monkeypatch):
        '''One pass of three losing its `free` sampler would otherwise publish
        a ~310,474 GB mean and a 173% CV on a 64 GB box.
        '''
        import json
        fake_img_exists(lambda name: True)
        sentinel = bgperf2.unsampled_row_values()['min free mem (GB)']
        self.run(tmp_path, monkeypatch,
                 [{'min free mem (GB)': 50.0},
                  {'min free mem (GB)': sentinel},
                  {'min free mem (GB)': 50.1}], repetitions=3)

        cell = json.loads((tmp_path / 'sum.summary.json').read_text())['cells'][0]
        metric = cell['metrics']['min free mem (GB)']
        assert metric['values'] == [50.0, None, 50.1]
        assert metric['cv_percent'] is None
        assert set(metric['withheld'].values()) == {summary.UNSAMPLED}
        # The cell's other columns are unaffected.
        assert cell['metrics']['elapsed (s)']['n'] == 3

    def test_a_discarded_batch_leaves_no_summary_behind(
            self, fake_img_exists, tmp_path, monkeypatch):
        '''A non-resumed batch drops its predecessor's progress file; the
        summary goes with it, so a write that then fails cannot leave a
        document describing three passes that no longer exist.
        '''
        fake_img_exists(lambda name: True)
        monkeypatch.setattr(bgperf2, 'create_batch_graphs', lambda *a, **k: None)
        (tmp_path / 'sum.summary.json').write_text('{"cells": ["stale"]}')
        monkeypatch.setattr(bgperf2, 'summarize_batch',
                            lambda *a, **k: (_ for _ in ()).throw(ValueError('boom')))
        monkeypatch.setattr(bgperf2, 'bench', lambda a: a_row())

        bgperf2.batch(Namespace(
            batch_config=self.write(tmp_path), results_dir=str(tmp_path)))

        assert not (tmp_path / 'sum.summary.json').exists()

    def test_a_failure_before_the_first_cell_is_reported_at_once(
            self, fake_img_exists, tmp_path, monkeypatch, capsys):
        '''Otherwise the only report that the document beside the CSV is not
        the one describing it arrives hours later.
        '''
        fake_img_exists(lambda name: True)
        monkeypatch.setattr(bgperf2, 'create_batch_graphs', lambda *a, **k: None)
        monkeypatch.setattr(bgperf2, 'summarize_batch',
                            lambda *a, **k: (_ for _ in ()).throw(ValueError('boom')))

        def dies(a):
            print('SENTINEL-FIRST-CELL')
            raise RuntimeError('interrupted')

        monkeypatch.setattr(bgperf2, 'bench', dies)
        with pytest.raises(RuntimeError, match='interrupted'):
            bgperf2.batch(Namespace(
                batch_config=self.write(tmp_path), results_dir=str(tmp_path)))

        out = capsys.readouterr().out
        assert 'summary unavailable: ValueError: boom' in out
        assert out.index('summary unavailable') < out.index('SENTINEL-FIRST-CELL')

    def test_a_row_from_an_older_build_costs_its_pass_and_not_the_document(
            self, fake_img_exists, tmp_path, monkeypatch):
        '''`--resume` onto a progress file written before a column was appended
        is supported, and such a row is one field short.
        '''
        import json
        fake_img_exists(lambda name: True)
        monkeypatch.setattr(bgperf2, 'create_batch_graphs', lambda *a, **k: None)
        config = self.write(tmp_path, repetitions=2)
        args = Namespace(batch_config=config, results_dir=str(tmp_path), resume=True)

        # A completed pass 1 written by a build with one column fewer.
        targets = bgperf2.expand_target_versions(a_test()['targets'])
        cells = bgperf2.expand_batch_cells(a_test(repetitions=2), targets)
        bgperf2.write_batch_progress(
            str(tmp_path / 'sum.progress.json'),
            {bgperf2.batch_cell_id('sum', cells[0]): a_row()[:-1]})
        monkeypatch.setattr(bgperf2, 'bench',
                            lambda a: a_row(**{'elapsed (s)': 44}))
        bgperf2.batch(args)

        cell = json.loads((tmp_path / 'sum.summary.json').read_text())['cells'][0]
        assert [p['state'] for p in cell['passes']] == [
            summary.UNREADABLE, summary.OBSERVED]
        assert cell['metrics']['elapsed (s)']['values'] == [44]

    def test_a_summariser_that_raises_costs_the_summary_and_not_the_rows(
            self, fake_img_exists, tmp_path, monkeypatch, capsys):
        '''The rows are already on disk by then, at the end of a batch that has
        already run for hours.
        '''
        fake_img_exists(lambda name: True)
        monkeypatch.setattr(bgperf2, 'summarize_batch',
                            lambda *a, **k: (_ for _ in ()).throw(ValueError('boom')))
        self.run(tmp_path, monkeypatch, [{}])

        assert 'summary unavailable: ValueError: boom' in capsys.readouterr().out
        assert 'bird' in (tmp_path / 'sum.csv').read_text()


class TestTheVarianceRule:
    """Phase 5 asks that a test expand from three passes to five *only under a
    named variance rule*. Without one, the decision to rerun belongs to whoever
    read the CSV and disliked it, which reruns the surprising results and turns
    a benchmark into a search for the expected answer.

    The rule is comparative because no coefficient of variation means the same
    thing twice here: 2% is nothing between targets 40% apart and fatal between
    ones 0.12% apart, which is what the FRR releases actually were.
    """

    def test_a_gap_wider_than_the_noise_needs_no_more_passes(self):
        verdicts = variance_of(
            a_cell_taking([40, 40, 40], name='bird', ordinal=0),
            a_cell_taking([50, 50, 50], name='frr_c', ordinal=1))
        assert [v['verdict'] for v in verdicts.values()] == [
            summary.SEPARATED, summary.SEPARATED]

    def test_a_gap_inside_the_noise_earns_the_expansion(self):
        """Medians 42 and 45 differ by 3, under the combined deviation of 4.
        Three passes cannot say which of these two daemons is faster.
        """
        verdicts = variance_of(
            a_cell_taking([40, 42, 44], name='bird', ordinal=0),
            a_cell_taking([43, 45, 47], name='frr_c', ordinal=1))
        assert verdicts['bird']['verdict'] == summary.EXPAND
        assert verdicts['bird']['passes_recommended'] == summary.EXPANSION_PASSES
        evidence = verdicts['bird']['evidence']
        assert evidence['gap'] == 3
        assert evidence['combined_stdev'] == 4
        assert evidence['rival_cell'] == 1

    def test_the_expansion_has_a_ceiling(self):
        """A cell still unseparated at five passes is not asking for a sixth.
        It is saying those two are not distinguishable at this workload, and
        expanding without a limit is how a batch spends a weekend failing to
        decide something.
        """
        verdicts = variance_of(
            a_cell_taking([40, 42, 44, 41, 43], name='bird', ordinal=0),
            a_cell_taking([43, 45, 47, 44, 46], name='frr_c', ordinal=1))
        assert verdicts['bird']['verdict'] == summary.UNSEPARATED_AT_LIMIT
        assert 'passes_recommended' not in verdicts['bird']

    def test_a_cell_with_nothing_to_compare_against_is_not_a_verdict(self):
        verdict = variance_of(a_cell_taking([40, 42, 44]))['bird']
        assert verdict['verdict'] == summary.UNDECIDED
        assert verdict['reason'] == summary.NOTHING_TO_COMPARE

    def test_only_cells_sharing_the_axes_are_compared(self):
        """create_graph() draws one group of bars per (peers, prefixes,
        filter), and the rule answers a question somebody asks of the picture.
        A 10-peer cell is not the rival of a 50-peer one.
        """
        verdicts = variance_of(
            a_cell_taking([40, 42, 44], name='bird', ordinal=0),
            a_cell_taking([41, 43, 45], name='frr_c', ordinal=1,
                          identity={'peers': 50}))
        assert [v['reason'] for v in verdicts.values()] == [
            summary.NOTHING_TO_COMPARE, summary.NOTHING_TO_COMPARE]

    def test_the_rival_with_the_smallest_margin_is_the_one_reported(self):
        """Where every rival has the same dispersion the binding one is also
        the nearest, which is the ordinary case: the closest call in the group
        is the ranking a reader would challenge first.
        """
        verdicts = variance_of(
            a_cell_taking([40, 40, 40], name='bird', ordinal=0),
            a_cell_taking([90, 90, 90], name='gobgp', ordinal=1),
            a_cell_taking([41, 41, 41], name='frr_c', ordinal=2))
        assert verdicts['bird']['evidence']['rival_cell'] == 2
        assert verdicts['bird']['evidence']['rival_chosen_by'] == 'margin'

    def test_one_pass_has_no_dispersion_and_so_no_verdict(self):
        """A single-pass test says nothing about repeatability, and a rule that
        answered anyway would be reading a stdev it does not have.
        """
        verdicts = variance_of(
            a_cell_taking([40], name='bird', ordinal=0),
            a_cell_taking([41], name='frr_c', ordinal=1))
        assert verdicts['bird']['verdict'] == summary.UNDECIDED
        assert 'elapsed (s)' in verdicts['bird']['reason']

    def test_a_rival_without_dispersion_still_shows_the_gap(self):
        """Undecided, not separated -- but the reader is told which pair could
        not be judged and by how much they differ.
        """
        verdicts = variance_of(
            a_cell_taking([40, 42, 44], name='bird', ordinal=0),
            a_cell_taking([45], name='frr_c', ordinal=1))
        verdict = verdicts['bird']
        assert verdict['verdict'] == summary.UNDECIDED
        assert 'frr_c' in verdict['reason']
        assert verdict['evidence']['gap'] == 3

    def test_a_withheld_metric_does_not_raise(self):
        """The sentinel withholds every statistic in a column; the rule has to
        survive a cell it cannot read.
        """
        verdicts = variance_of(
            a_cell_taking([40, 'n/a', 44], name='bird', ordinal=0),
            a_cell_taking([43, 45, 47], name='frr_c', ordinal=1))
        assert verdicts['bird']['verdict'] == summary.UNDECIDED

    def test_the_document_names_the_rule_it_applied(self):
        """A verdict nobody can argue with is a boolean with extra words."""
        document = summary.summarize_batch('sum', HEADER, [a_cell_taking([40])])
        assert document['variance_rule'] == summary.VARIANCE_RULE
        assert document['cells'][0]['variance']['policy'] == summary.VARIANCE_RULE

    def test_an_expansion_is_printed_with_what_to_do_about_it(self):
        document = summary.summarize_batch('sum', HEADER, [
            a_cell_taking([40, 42, 44], name='bird', ordinal=0),
            a_cell_taking([43, 45, 47], name='frr_c', ordinal=1)],
            repetitions=3)
        printed = ' '.join(summary.describe_batch_summary(document))
        assert 'is not separated from' in printed
        assert 'repetitions: 5' in printed

    def test_a_separated_batch_prints_nothing_about_variance(self):
        """The rule is silent about the results it supports."""
        document = summary.summarize_batch('sum', HEADER, [
            a_cell_taking([40, 40, 40], name='bird', ordinal=0),
            a_cell_taking([90, 90, 90], name='frr_c', ordinal=1)],
            repetitions=3)
        printed = ' '.join(summary.describe_batch_summary(document))
        assert 'variance rule' not in printed

    def test_separation_is_decided_against_every_rival_not_the_nearest(self):
        """Separating a cell from its closest neighbour separates it from the
        rest of the group only if every rival has the same dispersion, which
        is not a thing anyone measured.

        bird clears frr by a mile -- gap 1 against a combined 0.02 -- and is
        nowhere near gobgp, whose own spread is 10. `create_graph()` draws all
        three side by side, so publishing `separated` here would tell a reader
        that bird is distinguishable from the others in a picture where it is
        not.
        """
        verdicts = variance_of(
            a_cell_taking([39.99, 40.0, 40.01], name='bird', ordinal=0),
            a_cell_taking([40.99, 41.0, 41.01], name='frr_c', ordinal=1),
            a_cell_taking([35.0, 45.0, 55.0], name='gobgp', ordinal=2))
        assert verdicts['bird']['verdict'] == summary.EXPAND
        # The binding rival is the closest call, not the closest median.
        assert verdicts['bird']['evidence']['rival_cell'] == 2
        assert verdicts['bird']['evidence']['margin'] < 0
        assert verdicts['bird']['rivals_considered'] == 2

    def test_the_binding_rival_can_still_be_the_nearest_one(self):
        """When the dispersions are alike, the closest call is the closest
        median and the rule is unchanged from the simple case.
        """
        verdicts = variance_of(
            a_cell_taking([40, 40, 40], name='bird', ordinal=0),
            a_cell_taking([90, 90, 90], name='gobgp', ordinal=1),
            a_cell_taking([41, 41, 41], name='frr_c', ordinal=2))
        assert verdicts['bird']['evidence']['rival_cell'] == 2

    def test_one_dispersionless_cell_does_not_mute_the_whole_group(self):
        """A cell with two of three passes failed has a median and no stdev.
        Picking the nearest rival first and only then noticing it had no
        dispersion let that cell sit between two others that were plainly
        unseparated and withhold the verdict for both -- with nothing printed
        to say the rule had been silenced at all.
        """
        verdicts = variance_of(
            a_cell_taking([39.5, 40.0, 40.5], name='bird', ordinal=0),
            a_cell_taking([40.2], name='broken', ordinal=1),
            a_cell_taking([36.0, 41.0, 46.0], name='frr_c', ordinal=2))
        assert verdicts['bird']['verdict'] == summary.EXPAND
        assert verdicts['bird']['evidence']['rival_cell'] == 2
        assert verdicts['broken']['verdict'] == summary.UNDECIDED

    def test_a_rival_without_dispersion_is_only_a_refusal_when_none_has_one(self):
        verdicts = variance_of(
            a_cell_taking([40, 42, 44], name='bird', ordinal=0),
            a_cell_taking([45], name='frr_c', ordinal=1))
        assert verdicts['bird']['verdict'] == summary.UNDECIDED
        assert 'frr_c' in verdicts['bird']['reason']

    def test_the_recommendation_never_drops_below_the_declared_repetitions(self):
        """A `repetitions: 7` test told to rerun at five would *lose* two
        passes and the observations in them.
        """
        document = summary.summarize_batch('sum', HEADER, [
            a_cell_taking([40, 42, 44, 41], name='bird', ordinal=0),
            a_cell_taking([43, 45, 47, 44], name='frr_c', ordinal=1)],
            repetitions=7)
        variance = document['cells'][0]['variance']
        assert variance['verdict'] == summary.EXPAND
        assert variance['passes_recommended'] == 7

    def test_a_shortfall_from_failed_passes_is_named_not_rerun(self):
        """Reaching the ceiling in passes but not in observations is a failure
        to investigate, not a missing repetition, and rerunning at the same
        count just repeats it.
        """
        rows = [a_row(**{'elapsed (s)': v}) for v in (40, 42, 44, 41)]
        rows.append(a_row(**{'failed': 'FAILED', 'MSG': 'stuck at 0'}))
        document = summary.summarize_batch('sum', HEADER, [
            a_group(rows, name='bird', ordinal=0, description='bird'),
            a_cell_taking([42, 44, 46, 43, 45], name='frr_c', ordinal=1)],
            repetitions=5)
        variance = document['cells'][0]['variance']
        assert variance['verdict'] == summary.EXPAND
        assert '4 of 5 passes' in variance['shortfall']
        printed = ' '.join(summary.describe_batch_summary(document))
        assert '4 of 5 passes produced an observation' in printed

    def test_a_mirrored_pair_is_printed_once(self):
        """The verdict is per cell and the binding rival is usually mutual, so
        a two-target group otherwise states one relation twice with identical
        numbers.
        """
        document = summary.summarize_batch('sum', HEADER, [
            a_cell_taking([40, 42, 44], name='bird', ordinal=0),
            a_cell_taking([43, 45, 47], name='frr_c', ordinal=1)],
            repetitions=3)
        printed = summary.describe_batch_summary(document)
        assert sum('variance rule' in line for line in printed) == 1


class TestWhatTheRuleWillNotClaim:
    """Three defects review found in the rule after it was written. Each is a
    case where the summary published something an operator would act on and
    the passes did not support -- which is the only failure mode a variance
    rule has, since nobody re-derives its arithmetic.
    """

    def test_a_nearer_rival_without_dispersion_withholds_separation(self):
        """`separated` is read as "distinguishable from the cells drawn beside
        it", because `create_graph()` draws the whole group side by side. One
        rival with a dispersion was enough to earn that verdict even while a
        rival at an identical median sat in the same group unjudged -- the
        nearest-rival defect one path over, reached through the cell that was
        skipped rather than the one that decided it.
        """
        verdicts = variance_of(
            a_cell_taking([40, 40, 40], name='bird', ordinal=0),
            a_cell_taking([40.0], name='broken', ordinal=1),
            a_cell_taking([90, 90, 90], name='gobgp', ordinal=2))
        assert verdicts['bird']['verdict'] == summary.UNDECIDED
        assert 'broken' in verdicts['bird']['reason']
        assert verdicts['bird']['rivals_unjudged'] == ['broken']

    def test_a_further_unjudged_rival_does_not_withhold_it(self):
        """Only a rival *nearer* than the one that decided the verdict
        contradicts it. Withholding on any unjudgeable rival at all would mute
        a whole group for one cell whose passes failed, which is what
        preferring the measurable rivals exists to prevent.
        """
        verdicts = variance_of(
            a_cell_taking([40, 40, 40], name='bird', ordinal=0),
            a_cell_taking([50, 50, 50], name='frr_c', ordinal=1),
            a_cell_taking([90.0], name='broken', ordinal=2))
        assert verdicts['bird']['verdict'] == summary.SEPARATED
        assert verdicts['bird']['rivals_unjudged'] == ['broken']

    def test_an_unseparated_verdict_survives_a_nearer_unjudged_rival(self):
        """Unseparated is already the conservative answer: a rival nobody could
        judge cannot make it less so, and degrading it would take the
        actionable line away.
        """
        verdicts = variance_of(
            a_cell_taking([40, 42, 44], name='bird', ordinal=0),
            a_cell_taking([41.0], name='broken', ordinal=1),
            a_cell_taking([43, 45, 47], name='frr_c', ordinal=2))
        assert verdicts['bird']['verdict'] == summary.EXPAND

    def test_the_printed_pair_is_the_more_actionable_of_its_two_verdicts(self):
        """The two sides of a mutual pair need not agree. A cell whose passes
        all succeeded is `unseparated at the expansion limit` -- "more passes
        will not decide it" -- while the rival that lost two of them is
        `expand` with a shortfall, which is a failed pass to go and look at.
        Printing whichever came first meant matrix position chose between those
        two, and half the time printed the one that says to do nothing.
        """
        short = [a_row(**{'elapsed (s)': v}) for v in (40, 42, 44)]
        short += [a_row(**{'failed': 'FAILED', 'MSG': 'stuck at 0'})] * 2
        document = summary.summarize_batch('sum', HEADER, [
            a_cell_taking([43, 45, 47, 44, 46], name='frr_c', ordinal=0),
            a_group(short, name='bird', ordinal=1, description='bird')],
            repetitions=5)
        # Both are `expand`: the fully observed cell is not at the limit
        # either, because its rival has not spent the passes that verdict
        # assumes. They differ in that one carries a shortfall.
        assert document['cells'][0]['variance']['verdict'] == summary.EXPAND
        assert 'shortfall' not in document['cells'][0]['variance']
        assert document['cells'][1]['variance']['verdict'] == summary.EXPAND
        assert document['cells'][1]['variance']['shortfall']
        printed = [line for line in summary.describe_batch_summary(document)
                   if 'variance rule' in line]
        assert len(printed) == 1
        assert '3 of 5 passes produced an observation' in printed[0]

    def test_the_ordering_of_the_pair_does_not_change_the_advice(self):
        """The same two cells with their ordinals swapped print the same line.
        That is the whole defect: which advice the operator got depended on
        where the cell sat in the matrix.
        """
        def printed(shortfall_ordinal):
            short = [a_row(**{'elapsed (s)': v}) for v in (40, 42, 44)]
            short += [a_row(**{'failed': 'FAILED', 'MSG': 'stuck at 0'})] * 2
            cells = [a_group(short, name='bird', ordinal=shortfall_ordinal,
                             description='bird'),
                     a_cell_taking([43, 45, 47, 44, 46], name='frr_c',
                                   ordinal=1 - shortfall_ordinal)]
            document = summary.summarize_batch(
                'sum', HEADER, sorted(cells, key=lambda c: c['ordinal']),
                repetitions=5)
            return [line for line in summary.describe_batch_summary(document)
                    if 'variance rule' in line]

        assert len(printed(0)) == len(printed(1)) == 1
        for line in printed(0) + printed(1):
            assert '3 of 5 passes produced an observation' in line

    def test_a_cell_that_never_ran_says_so_rather_than_naming_a_dispersion(self):
        """`this cell has no dispersion` reads as one observation. A cell whose
        every pass failed has none at all, and the two are already told apart
        in one place -- the metric's own `withheld` entry -- so the refusal
        quotes that rather than restating it in a second vocabulary.
        """
        failed = [a_row(**{'failed': 'FAILED', 'MSG': 'stuck at 0'})] * 3
        verdicts = variance_of(
            a_group(failed, name='bird', ordinal=0, description='bird'),
            a_cell_taking([43, 45, 47], name='frr_c', ordinal=1))
        assert verdicts['bird']['verdict'] == summary.UNDECIDED
        assert summary.NO_OBSERVATION in verdicts['bird']['reason']

    def test_a_single_pass_names_the_other_reason(self):
        verdicts = variance_of(
            a_cell_taking([40.0], name='bird', ordinal=0),
            a_cell_taking([43, 45, 47], name='frr_c', ordinal=1))
        assert summary.NEEDS_TWO in verdicts['bird']['reason']

    def test_a_sentinel_withheld_column_names_its_own_reason(self):
        """A cell whose elapsed column was withheld by the never-sampled
        sentinel is a third case again, and reads as neither of the others.
        """
        document = summary.summarize_batch(
            'sum', HEADER,
            [a_cell_taking([40, 42, 999], name='bird', ordinal=0),
             a_cell_taking([43, 45, 47], name='frr_c', ordinal=1)],
            unavailable={'elapsed (s)': 999})
        variance = document['cells'][0]['variance']
        assert variance['verdict'] == summary.UNDECIDED
        assert summary.UNSAMPLED in variance['reason']

    def test_a_shortfall_does_not_replace_the_rerun_count(self):
        """A failed pass and a rerun count are two things to do about one cell,
        and the shortfall used to be printed instead of the count. With
        `repetitions: 3` and one failed pass, the pair de-duplication then
        suppressed the rival's line that carried the count, so the obvious next
        move -- fix the pass, rerun at three -- comes back unseparated again.
        """
        rows = [a_row(**{'elapsed (s)': v}) for v in (40, 41)]
        rows.append(a_row(**{'failed': 'FAILED', 'MSG': 'stuck at 0'}))
        document = summary.summarize_batch('sum', HEADER, [
            a_group(rows, name='bird', ordinal=0, description='bird'),
            a_cell_taking([41, 42, 43], name='frr_c', ordinal=1)],
            repetitions=3)
        printed = [line for line in summary.describe_batch_summary(document)
                   if 'variance rule' in line]
        assert len(printed) == 1
        assert 'repetitions: 5' in printed[0]
        assert '2 of 3 passes produced an observation' in printed[0]

    def test_the_refusal_names_every_rival_it_could_not_judge(self):
        """The reason string names the nearest one so the reader gets a gap.
        That left any others unmentioned anywhere in the document.
        """
        verdict = variance_of(
            a_cell_taking([40, 42, 44], name='bird', ordinal=0),
            a_cell_taking([44.5], name='brokenA', ordinal=1),
            a_cell_taking([45.0], name='brokenB', ordinal=2))['bird']
        assert verdict['verdict'] == summary.UNDECIDED
        assert verdict['rivals_unjudged'] == ['brokenA', 'brokenB']

    def test_one_quantum_apart_is_not_separated(self):
        """`elapsed (s)` is whole seconds, and not by choice: it is counted off
        the monitor's 1s poll loop with an integer number of assurance samples
        subtracted. Passes that agree exactly agree to within one bucket, not
        to within nothing -- so a combined deviation of 0.0 would let any gap
        at all satisfy the rule, and the batch would publish `separated` on a
        rounding boundary, silently, since it prints nothing about the results
        it supports.
        """
        verdicts = variance_of(
            a_cell_taking([95, 95, 95], name='frr_8.5', ordinal=0),
            a_cell_taking([96, 96, 96], name='frr_9.1', ordinal=1))
        assert verdicts['frr_8.5']['verdict'] == summary.EXPAND
        evidence = verdicts['frr_8.5']['evidence']
        assert evidence['gap'] == 1.0
        assert evidence['combined_stdev'] == 1.0
        assert evidence['metric_resolution'] == 1.0

    def test_the_resolution_is_a_floor_and_not_a_replacement(self):
        """A real dispersion wider than the quantum is used as it is."""
        evidence = variance_of(
            a_cell_taking([40, 42, 44], name='bird', ordinal=0),
            a_cell_taking([43, 45, 47], name='frr_c', ordinal=1),
        )['bird']['evidence']
        assert evidence['combined_stdev'] == 4

    def test_a_gap_well_past_the_quantum_still_separates(self):
        verdicts = variance_of(
            a_cell_taking([40, 40, 40], name='bird', ordinal=0),
            a_cell_taking([50, 50, 50], name='frr_c', ordinal=1))
        assert verdicts['bird']['verdict'] == summary.SEPARATED

    def test_rivals_that_produced_nothing_are_not_no_rivals_at_all(self):
        """A rival whose every pass failed has no median, so it drops out of
        the comparison -- and the survivor claimed to have no rivals sharing
        its axes, which is false about the test. Nothing to compare against is
        a property of the matrix as written; rivals that produced nothing is a
        property of the run, and only the second is something to go and fix.
        """
        failed = [a_row(**{'failed': 'FAILED', 'MSG': 'stuck at 0'})] * 3
        verdicts = variance_of(
            a_group(failed, name='bird', ordinal=0, description='bird'),
            a_cell_taking([41, 42, 43], name='frr_c', ordinal=1))
        reason = verdicts['frr_c']['reason']
        assert reason != summary.NOTHING_TO_COMPARE
        assert 'bird (every pass failed)' in reason

    def test_a_lone_cell_still_says_it_has_no_rivals(self):
        verdict = variance_of(a_cell_taking([40, 42, 44]))['bird']
        assert verdict['reason'] == summary.NOTHING_TO_COMPARE

    def test_a_withheld_separation_is_printed_rather_than_left_silent(self):
        """Silence otherwise means both "the rule endorsed this ranking" and
        "the rule could not judge it", which are the two things a reader most
        needs told apart. Fixing the verdict without fixing the printing is
        the same defect one layer down.
        """
        document = summary.summarize_batch('sum', HEADER, [
            a_cell_taking([40, 40, 40], name='bird', ordinal=0),
            a_cell_taking([40.0], name='broken', ordinal=1),
            a_cell_taking([90, 90, 90], name='gobgp', ordinal=2)],
            repetitions=3)
        printed = [line for line in summary.describe_batch_summary(document)
                   if 'variance rule' in line]
        # Two lines, not one: `broken` sits at the same distance from gobgp as
        # the rival that decided gobgp's verdict, so gobgp is withheld too --
        # and the two refusals are about different pairs, so neither may
        # de-duplicate the other away.
        assert len(printed) == 2
        assert any('no verdict for bird' in line for line in printed)
        assert any('no verdict for gobgp' in line for line in printed)
        assert all('broken' in line for line in printed)

    def test_a_refusal_without_a_combined_deviation_still_prints(self):
        """The refusal that fires when no rival has a dispersion has no
        combined deviation to report. Building the comparison sentence before
        branching on the verdict raised KeyError at the end of a batch that had
        already run for hours.
        """
        document = summary.summarize_batch('sum', HEADER, [
            a_cell_taking([40, 42, 44], name='bird', ordinal=0),
            a_cell_taking([44.5], name='brokenA', ordinal=1),
            a_cell_taking([45.0], name='brokenB', ordinal=2)], repetitions=3)
        printed = [line for line in summary.describe_batch_summary(document)
                   if 'variance rule' in line]
        assert len(printed) == 1
        assert 'no verdict for bird' in printed[0]

    def test_a_separated_group_is_still_silent(self):
        """The refusals print; the endorsements must not start to."""
        document = summary.summarize_batch('sum', HEADER, [
            a_cell_taking([40, 40, 40], name='bird', ordinal=0),
            a_cell_taking([90, 90, 90], name='gobgp', ordinal=1)],
            repetitions=3)
        assert not [line for line in summary.describe_batch_summary(document)
                    if 'variance rule' in line]

    def test_two_cells_blocked_by_different_rivals_both_print(self):
        """The printed lines are de-duplicated per pair, and a withheld
        separation reports a relation against the cell that blocked it, not
        against the binding rival in its evidence. Keying on the binding rival
        collapsed two such refusals onto one pair, and matrix position decided
        which was printed -- the defect the ranking exists to prevent, reached
        one path over.
        """
        document = summary.summarize_batch('sum', HEADER, [
            a_cell_taking([40, 40, 40], name='A', ordinal=0),
            a_cell_taking([60, 60, 60], name='B', ordinal=1),
            a_cell_taking([40.0], name='X', ordinal=2),
            a_cell_taking([60.0], name='Y', ordinal=3)], repetitions=3)
        assert document['cells'][0]['variance']['withheld_by'] == 2
        assert document['cells'][1]['variance']['withheld_by'] == 3
        printed = [line for line in summary.describe_batch_summary(document)
                   if 'variance rule' in line]
        assert any('no verdict for A' in line for line in printed)
        assert any('no verdict for B' in line for line in printed)

    def test_an_equally_close_unjudged_rival_withholds_separation_too(self):
        """A rival exactly as close as the one that decided the verdict
        contradicts "distinguishable from the cells drawn beside it" just as
        completely as a closer one -- and an equal gap is the likeliest shape
        here, since the decision metric is quantised.
        """
        verdicts = variance_of(
            a_cell_taking([40, 40, 40], name='bird', ordinal=0),
            a_cell_taking([45, 45, 45], name='frr_c', ordinal=1),
            a_cell_taking([35.0], name='broken', ordinal=2))
        assert verdicts['bird']['verdict'] == summary.UNDECIDED
        assert verdicts['bird']['rivals_unjudged'] == ['broken']

    def test_rivals_that_have_not_run_yet_are_not_rivals_that_failed(self):
        """The summary is written before the first cell and rewritten after
        every one, so for most of a batch a finished cell's rivals have simply
        not run -- and an interrupted batch leaves exactly that document
        behind, since the surviving file is the last checkpoint. Saying its
        rivals produced nothing reports work to investigate where there is
        none. Same `failed` against `not run` distinction `summarize_cell()`
        keeps at the pass level.
        """
        verdicts = variance_of(
            a_cell_taking([40, 42, 44], name='bird', ordinal=0),
            a_group([None, None, None], name='frr_c', ordinal=1,
                    description='frr_c'))
        assert 'frr_c (has not run yet)' in verdicts['bird']['reason']

    def test_rivals_that_all_failed_still_say_so(self):
        failed = [a_row(**{'failed': 'FAILED', 'MSG': 'stuck at 0'})] * 3
        verdicts = variance_of(
            a_cell_taking([40, 42, 44], name='bird', ordinal=0),
            a_group(failed, name='frr_c', ordinal=1, description='frr_c'))
        assert 'frr_c (every pass failed)' in verdicts['bird']['reason']

    def test_the_evidence_names_the_rival_the_branch_actually_chose(self):
        """`nearest_*` was a lie in the branch that picks the binding rival:
        with bird 40, frr 41 and gobgp 45 the reported cell is gobgp, the one
        furthest away. The refusal branch really does use the nearest, so one
        key name meant two things in one document.
        """
        verdicts = variance_of(
            a_cell_taking([39.99, 40.0, 40.01], name='bird', ordinal=0),
            a_cell_taking([40.99, 41.0, 41.01], name='frr_c', ordinal=1),
            a_cell_taking([35.0, 45.0, 55.0], name='gobgp', ordinal=2))
        evidence = verdicts['bird']['evidence']
        assert evidence['rival_cell'] == 2
        assert evidence['rival_chosen_by'] == 'margin'

    def test_a_refusal_reports_the_rival_it_chose_by_gap(self):
        evidence = variance_of(
            a_cell_taking([40, 42, 44], name='bird', ordinal=0),
            a_cell_taking([44.5], name='brokenA', ordinal=1),
            a_cell_taking([60.0], name='brokenB', ordinal=2))['bird']['evidence']
        assert evidence['rival_cell'] == 1
        assert evidence['rival_chosen_by'] == 'gap'

    def test_a_rival_with_no_observation_is_named_and_withholds_separation(self):
        """A rival that never ran, or whose every pass failed, has no median --
        so filtering the unjudgeable rivals on having one dropped it out of the
        naming as well as out of the comparison, and it went unmentioned
        anywhere in the verdict. `rivals_considered: 1` could not be told from
        "one of two". It is also *less* known than a rival with a median and no
        dispersion, so withholding `separated` for that one while publishing it
        beside this one would be the rule being stricter about the case it
        knows more about.
        """
        verdicts = variance_of(
            a_cell_taking([40, 40, 40], name='bird', ordinal=0),
            a_cell_taking([60, 60, 60], name='frr_c', ordinal=1),
            a_group([None, None, None], name='gobgp', ordinal=2,
                    description='gobgp'))
        verdict = verdicts['bird']
        assert verdict['verdict'] == summary.UNDECIDED
        assert 'gobgp' in verdict['reason']
        assert 'has not run yet' in verdict['reason']
        assert verdict['rivals_unjudged'] == ['gobgp']

    def test_a_rival_whose_passes_all_failed_says_that_instead(self):
        failed = [a_row(**{'failed': 'FAILED', 'MSG': 'stuck at 0'})] * 3
        verdict = variance_of(
            a_cell_taking([40, 40, 40], name='bird', ordinal=0),
            a_cell_taking([60, 60, 60], name='frr_c', ordinal=1),
            a_group(failed, name='gobgp', ordinal=2,
                    description='gobgp'))['bird']
        assert 'every pass failed' in verdict['reason']

    def test_the_expansion_limit_is_reached_by_the_pair_not_one_cell(self):
        """"More passes will not decide it" is a claim about the pair. A rival
        that produced two of its five passes has not spent the passes that
        claim assumes, so a fully observed cell must not publish it beside one.
        """
        short = [a_row(**{'elapsed (s)': v}) for v in (40, 42)]
        short += [a_row(**{'failed': 'FAILED', 'MSG': 'stuck at 0'})] * 3
        document = summary.summarize_batch('sum', HEADER, [
            a_cell_taking([41, 42, 43, 41, 42], name='frr_c', ordinal=0),
            a_group(short, name='bird', ordinal=1, description='bird')],
            repetitions=5)
        assert document['cells'][0]['variance']['verdict'] == summary.EXPAND

    def test_a_fully_observed_pair_does_reach_the_limit(self):
        verdicts = variance_of(
            a_cell_taking([40, 42, 44, 41, 43], name='bird', ordinal=0),
            a_cell_taking([43, 45, 47, 44, 46], name='frr_c', ordinal=1))
        assert verdicts['bird']['verdict'] == summary.UNSEPARATED_AT_LIMIT
        assert verdicts['frr_c']['verdict'] == summary.UNSEPARATED_AT_LIMIT

    def test_one_unstarted_rival_does_not_relabel_a_rival_that_failed(self):
        """The refusal names each rival with its own state. Deciding it with an
        `any(... not run ...)` over the group reported a rival that ran and
        failed every pass as a batch merely in progress -- and that failed
        rival is the only thing there an operator can go and fix.
        """
        failed = [a_row(**{'failed': 'FAILED', 'MSG': 'stuck at 0'})] * 3
        verdict = variance_of(
            a_cell_taking([40, 42, 44], name='bird', ordinal=0),
            a_group(failed, name='frr_c', ordinal=1, description='frr_c'),
            a_group([None, None, None], name='gobgp', ordinal=2,
                    description='gobgp'))['bird']
        assert 'frr_c (every pass failed)' in verdict['reason']
        assert 'gobgp (has not run yet)' in verdict['reason']

    def test_a_rival_that_partly_failed_and_partly_did_not_run_says_both(self):
        """Same collapse one rival down: testing for `not run` at all let one
        unstarted pass describe a rival whose other two had failed.
        """
        mixed = [a_row(**{'failed': 'FAILED', 'MSG': 'stuck at 0'})] * 2 + [None]
        verdict = variance_of(
            a_cell_taking([40, 40, 40], name='bird', ordinal=0),
            a_cell_taking([60, 60, 60], name='frr_c', ordinal=1),
            a_group(mixed, name='gobgp', ordinal=2,
                    description='gobgp'))['bird']
        assert 'of 3 passes, 2 failed, 1 not run' in verdict['reason']

    def test_every_refusal_says_how_many_rivals_it_had(self):
        """The branch reporting rivals without observations named none of them,
        so the document could not say whether the cell had one rival or five.
        """
        failed = [a_row(**{'failed': 'FAILED', 'MSG': 'stuck at 0'})] * 3
        verdict = variance_of(
            a_cell_taking([40, 42, 44], name='bird', ordinal=0),
            a_group(failed, name='frr_c', ordinal=1, description='frr_c'),
            a_group(failed, name='gobgp', ordinal=2,
                    description='gobgp'))['bird']
        assert verdict['rivals_considered'] == 0
        assert verdict['rivals_unjudged'] == ['frr_c', 'gobgp']

    def test_a_pair_short_because_of_the_rival_is_not_told_to_rerun(self):
        """A cell that spent every pass it was given can still be unseparated
        only because the rival did not. Recommending the count it already ran
        is a no-op printed as advice -- and the rival's own shortfall is filed
        under whichever pair *its* verdict binds to, which need not be this
        one, so the no-op can stand alone.
        """
        short = [a_row(**{'elapsed (s)': v}) for v in (43, 45, 47)]
        short += [a_row(**{'failed': 'FAILED', 'MSG': 'stuck at 0'})] * 2
        document = summary.summarize_batch('sum', HEADER, [
            a_cell_taking([40, 42, 44, 41, 43], name='bird', ordinal=0),
            a_group(short, name='frr_c', ordinal=1, description='frr_c'),
            a_cell_taking([44, 46, 48, 45, 47], name='gobgp', ordinal=2)],
            repetitions=5)
        variance = document['cells'][0]['variance']
        assert variance['verdict'] == summary.EXPAND
        assert 'passes_recommended' not in variance
        assert '3 of 5 passes' in variance['rival_shortfall']
        printed = [line for line in summary.describe_batch_summary(document)
                   if 'no verdict' not in line and 'variance rule' in line]
        assert any('Rerun this test with repetitions: 5' not in line
                   and '3 of 5 passes' in line for line in printed)

    def test_a_raising_rule_costs_the_verdicts_and_not_the_statistics(self,
                                                                      monkeypatch):
        """Same rule `write_event_artifact()` applies to `derive_findings()`:
        by the time the rule runs, these statistics are the only record of what
        the passes measured, and `publish_batch_summary()` catches at the outer
        level -- so anything raised here loses the whole document at the end of
        a multi-hour batch.
        """
        def explode(*args, **kwargs):
            raise TypeError("unhashable type: 'list'")
        monkeypatch.setattr(summary, 'apply_variance_rule', explode)
        document = summary.summarize_batch('sum', HEADER, [
            a_cell_taking([40, 42, 44], name='bird', ordinal=0),
            a_cell_taking([43, 45, 47], name='frr_c', ordinal=1)],
            repetitions=3)
        assert document['cells'][0]['metrics']['elapsed (s)']['median'] == 42
        assert 'variance_rule' not in document
        assert 'TypeError' in document['variance_failure']
        printed = summary.describe_batch_summary(document, path='sum.json')
        assert any('no verdicts' in line for line in printed)
        # Under the heading, not adrift above it.
        assert printed[0].startswith('repeatability over 3 passes')

    def test_a_partial_ranking_is_not_published(self):
        """The rule reads each cell against its group, so a run that stopped
        part way leaves some cells of one group judged and others not, with
        nothing saying which. A ranking nobody can argue with is the failure
        this module exists to avoid.
        """
        real = summary.apply_variance_rule

        def half(cells, **kwargs):
            real(cells[:1], **kwargs)
            raise RuntimeError('stopped')

        original = summary.apply_variance_rule
        summary.apply_variance_rule = half
        try:
            document = summary.summarize_batch('sum', HEADER, [
                a_cell_taking([40, 42, 44], name='bird', ordinal=0),
                a_cell_taking([43, 45, 47], name='frr_c', ordinal=1)],
                repetitions=3)
        finally:
            summary.apply_variance_rule = original
        assert all('variance' not in cell for cell in document['cells'])
        assert 'RuntimeError' in document['variance_failure']

    def test_a_group_whose_rival_failed_every_pass_is_not_silent(self):
        """That refusal names its rivals and carries no evidence, so filtering
        the printed lines on `evidence` dropped it -- and silence is what an
        endorsed ranking looks like.
        """
        failed = [a_row(**{'failed': 'FAILED', 'MSG': 'stuck at 0'})] * 3
        document = summary.summarize_batch('sum', HEADER, [
            a_cell_taking([40, 42, 44], name='bird', ordinal=0),
            a_group(failed, name='frr_c', ordinal=1, description='frr_c')],
            repetitions=3)
        printed = [line for line in summary.describe_batch_summary(document)
                   if 'variance rule' in line]
        assert len(printed) == 1
        assert 'frr_c (every pass failed)' in printed[0]

    def test_a_rival_whose_column_was_withheld_does_not_claim_a_pass_state(self):
        """A cell reaches the unobserved path whenever its decision-metric
        median is None, which includes a column withheld for being non-numeric.
        Saying "no pass produced an observation" there contradicts the
        `observations: 3` two keys away in the same document.
        """
        rows = [a_row(**{'elapsed (s)': v}) for v in ('', '', '')]
        verdict = variance_of(
            a_cell_taking([40, 42, 44], name='bird', ordinal=0),
            a_group(rows, name='frr_c', ordinal=1, description='frr_c'))['bird']
        assert summary.NON_NUMERIC in verdict['reason']

    def test_a_single_pass_batch_prints_nothing_even_when_the_rule_raises(self,
                                                                         monkeypatch):
        """A single-pass test prints nothing at all, and no cell of one can
        carry a printable verdict anyway -- every dispersion in it is withheld.
        Emitting the failure outside that gate put a lone indented line into
        the output with no heading naming the test or the summary path, and
        every checked-in benchmark config is single-pass.
        """
        def explode(*args, **kwargs):
            raise TypeError("unhashable type: 'list'")
        monkeypatch.setattr(summary, 'apply_variance_rule', explode)
        document = summary.summarize_batch('sum', HEADER, [
            a_cell_taking([40], name='bird', ordinal=0),
            a_cell_taking([43], name='frr_c', ordinal=1)], repetitions=1)
        assert 'TypeError' in document['variance_failure']
        assert summary.describe_batch_summary(document, path='sum.json') == []
