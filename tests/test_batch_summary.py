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


def a_group(rows, name='bird', ordinal=0, description=None):
    '''One cell whose passes produced these rows; None for a pass that did not run.'''
    return {
        'ordinal': ordinal,
        'name': name,
        'description': description or '{0}, peers=1, prefixes=10, filter=None'.format(name),
        'identity': {'peers': 1, 'prefixes': 10, 'filter': 'None',
                     'target': {'name': 'bird'}},
        'passes': [{'repetition': i, 'row': row} for i, row in enumerate(rows, 1)],
    }


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
