'''Repeating a batch matrix, and keeping every pass's evidence.

One observation per cell says nothing about run-to-run variance, and the
machinery for a second observation is not "run it again": every artifact a run
writes is named from `run_name()`, so a second pass with the same name replaces
the first one's evidence and leaves two CSV rows nothing can tell apart.
'''
from argparse import Namespace

import pytest
import yaml

import base
import bgperf2


@pytest.fixture
def fake_img_exists(monkeypatch):
    '''Patch img_exists in both modules -- bgperf2 does `from base import *`.'''
    def _install(predicate):
        monkeypatch.setattr(base, 'img_exists', predicate)
        monkeypatch.setattr(bgperf2, 'img_exists', predicate)
    return _install


def a_test(**overrides):
    test = {
        'name': 'reps',
        'neighbors': [1, 2],
        'prefixes': [10],
        'filter_test': ['None'],
        'targets': [{'name': 'bird'}],
    }
    test.update(overrides)
    return test


class TestBatchRepetitions:
    def test_defaults_to_one_pass(self):
        assert bgperf2.batch_repetitions(a_test()) == 1

    @pytest.mark.parametrize('value', [0, -1, '3', 3.0, None, True])
    def test_rejects_anything_that_is_not_a_positive_count(self, value):
        '''A `repetitions: 0` that ran nothing, or a quoted 3 that ran once,
        would otherwise be found hours in or not at all.
        '''
        with pytest.raises(SystemExit) as e:
            bgperf2.batch_repetitions(a_test(repetitions=value))
        assert 'repetitions' in str(e.value)
        assert 'reps' in str(e.value)


class TestExpandBatchCells:
    def test_one_pass_enumerates_the_matrix_in_order(self):
        targets = [{'name': 'bird'}, {'name': 'frr_c'}]
        cells = bgperf2.expand_batch_cells(a_test(), targets)
        assert [(c['neighbors'], c['target']['name']) for c in cells] == [
            (1, 'bird'), (1, 'frr_c'), (2, 'bird'), (2, 'frr_c')]
        assert [c['ordinal'] for c in cells] == [0, 1, 2, 3]
        # None, not 1: a single-pass run is named exactly as it always was, and
        # the cell id has to agree with the name or resume can mix the two.
        assert {c['repetition'] for c in cells} == {None}

    def test_repetitions_repeat_the_whole_matrix_not_each_cell(self):
        '''Back-to-back runs of one cell share a page cache and a thermal
        state; an interrupted block order also leaves one observation of
        everything rather than every observation of the first few cells.
        '''
        cells = bgperf2.expand_batch_cells(a_test(repetitions=3), [{'name': 'bird'}])
        assert [c['repetition'] for c in cells] == [1, 1, 2, 2, 3, 3]
        assert [c['neighbors'] for c in cells] == [1, 2, 1, 2, 1, 2]

    def test_the_ordinal_identifies_the_cell_not_the_run(self):
        cells = bgperf2.expand_batch_cells(a_test(repetitions=2), [{'name': 'bird'}])
        assert [c['ordinal'] for c in cells] == [0, 1, 0, 1]


class TestCellIdentity:
    def ids(self, **overrides):
        test = a_test(**overrides)
        return [bgperf2.batch_cell_id(test['name'], c)
                for c in bgperf2.expand_batch_cells(test, test['targets'])]

    def test_every_repetition_of_every_cell_is_distinct(self):
        ids = self.ids(repetitions=3)
        assert len(set(ids)) == len(ids) == 6

    def test_asking_for_more_repetitions_does_not_move_the_earlier_ones(self):
        '''Otherwise raising a test from two passes to three would re-run the
        two that already have results.
        '''
        assert self.ids(repetitions=3)[:4] == self.ids(repetitions=2)

    def test_the_id_says_which_pass_it_came_from(self):
        import json
        decoded = [json.loads(i) for i in self.ids(repetitions=2)]
        assert [d['repetition'] for d in decoded] == [1, 1, 2, 2]


class TestRunName:
    def base_args(self, **overrides):
        args = Namespace(target='bird', label=None, version=None, repetition=None)
        for k, v in overrides.items():
            setattr(args, k, v)
        return args

    def test_a_single_pass_run_keeps_the_name_it_always_had(self):
        assert bgperf2.run_name(self.base_args(label='bird 2.19.2')) == 'bird 2.19.2'
        assert bgperf2.run_name(self.base_args(version='2.19.2')) == 'bird 2.19.2'
        assert bgperf2.run_name(self.base_args()) == 'bird'

    def test_a_repeated_run_names_its_pass(self):
        assert bgperf2.run_name(
            self.base_args(label='bird 2.19.2', repetition=2)) == 'bird 2.19.2 #2'
        assert bgperf2.run_name(self.base_args(repetition=1)) == 'bird #1'

    def test_bench_outside_a_batch_has_no_repetition_attribute(self):
        '''`bench` sets no such attribute, and run_name() names every artifact.'''
        assert bgperf2.run_name(Namespace(target='bird', label=None)) == 'bird'


class TestBatchRunsRepetitions:
    def write(self, tmp_path, **overrides):
        config = tmp_path / 'reps.yaml'
        config.write_text(yaml.safe_dump({'tests': [a_test(**overrides)]}))
        return str(config)

    def test_each_pass_gets_its_own_run_identity(
            self, fake_img_exists, tmp_path, monkeypatch):
        '''Two runs of one cell sharing a name means the second replaces the
        first's events.json, versions.json and PNGs, and the CSV grows two rows
        that cannot be told apart.
        '''
        fake_img_exists(lambda name: True)
        monkeypatch.setattr(bgperf2, 'create_batch_graphs', lambda *a, **k: None)
        names = []
        monkeypatch.setattr(
            bgperf2, 'bench',
            lambda a: names.append(bgperf2.run_name(a)) or [bgperf2.run_name(a)])

        bgperf2.batch(Namespace(
            batch_config=self.write(tmp_path, repetitions=2, neighbors=[1]),
            results_dir=str(tmp_path)))

        assert names == ['bird #1', 'bird #2']
        assert len(set(names)) == len(names)

    def test_a_single_pass_batch_is_unchanged(
            self, fake_img_exists, tmp_path, monkeypatch):
        fake_img_exists(lambda name: True)
        monkeypatch.setattr(bgperf2, 'create_batch_graphs', lambda *a, **k: None)
        names = []
        monkeypatch.setattr(
            bgperf2, 'bench',
            lambda a: names.append(bgperf2.run_name(a)) or ['r'])

        bgperf2.batch(Namespace(
            batch_config=self.write(tmp_path, neighbors=[1]), results_dir=str(tmp_path)))

        assert names == ['bird']

    def test_resume_after_an_interruption_inside_a_repetition(
            self, fake_img_exists, tmp_path, monkeypatch):
        fake_img_exists(lambda name: True)
        monkeypatch.setattr(bgperf2, 'create_batch_graphs', lambda *a, **k: None)
        config = self.write(tmp_path, repetitions=3, neighbors=[1])
        args = Namespace(batch_config=config, results_dir=str(tmp_path), resume=True)

        ran = []

        def interrupted(a):
            ran.append(bgperf2.run_name(a))
            if a.repetition == 2:
                raise RuntimeError('interrupted')
            return [bgperf2.run_name(a)]

        monkeypatch.setattr(bgperf2, 'bench', interrupted)
        with pytest.raises(RuntimeError, match='interrupted'):
            bgperf2.batch(args)
        assert ran == ['bird #1', 'bird #2']

        ran.clear()
        monkeypatch.setattr(
            bgperf2, 'bench', lambda a: ran.append(bgperf2.run_name(a)) or [bgperf2.run_name(a)])
        bgperf2.batch(args)

        assert ran == ['bird #2', 'bird #3'], 'the completed pass should not run again'
        csv_text = (tmp_path / 'reps.csv').read_text()
        for name in ['bird #1', 'bird #2', 'bird #3']:
            assert name in csv_text

    def test_a_bad_repetition_count_stops_before_the_first_container(
            self, fake_img_exists, tmp_path, monkeypatch):
        fake_img_exists(lambda name: True)
        ran = []
        monkeypatch.setattr(bgperf2, 'bench', lambda a: ran.append(a) or [])
        config = tmp_path / 'bad.yaml'
        config.write_text(yaml.safe_dump({'tests': [
            a_test(name='good'),
            a_test(name='bad', repetitions=0),
        ]}))

        with pytest.raises(SystemExit):
            bgperf2.batch(Namespace(batch_config=str(config), results_dir=str(tmp_path)))
        assert ran == []


class TestProgressSchema:
    def test_a_single_pass_id_keeps_its_pre_repetition_shape(self):
        '''An in-flight batch written by an older build has to keep resuming.

        A new key in every id would match nothing in that file, and --resume
        would silently re-run hours of finished work.
        '''
        import json
        test = a_test(neighbors=[1])
        cell = bgperf2.expand_batch_cells(test, test['targets'])[0]
        assert json.loads(bgperf2.batch_cell_id('reps', cell)) == {
            'test': 'reps', 'ordinal': 0, 'neighbors': 1, 'prefixes': 10,
            'filter': 'None', 'target': {'name': 'bird'},
        }

    def test_the_schema_version_did_not_have_to_move(self, tmp_path):
        import json
        path = tmp_path / 'old.progress.json'
        path.write_text(json.dumps({'schema_version': 1, 'cells': {'id': ['row']}}))
        assert bgperf2.load_batch_progress(str(path)) == {'id': ['row']}

    def test_a_written_file_reads_back(self, tmp_path):
        path = str(tmp_path / 'p.json')
        bgperf2.write_batch_progress(path, {'id': ['row']})
        assert bgperf2.load_batch_progress(path) == {'id': ['row']}


class TestBatchGraphsSurviveRepetitions:
    '''create_graph() de-duplicates row names but not row data.

    It keys the x axis off a dict of names and appends one bar height per row,
    so two rows sharing a name and a (peers, prefixes, filter) key give it one
    tick and two heights -- a graph that is either wrong or fatal depending on
    the matplotlib version, produced at the end of a batch that has already
    spent hours running. This is why a repetition is part of the run name
    rather than a column beside it.
    '''

    def rows(self, bench_args, bench_stats, repetitions):
        rows = []
        for r in repetitions:
            bench_args.repetition = r
            rows.append(bgperf2.create_output_stats(bench_args, '2.19.2', bench_stats))
        return rows

    def test_every_repetition_gets_its_own_bar(
            self, bench_args, bench_stats, tmp_path, monkeypatch):
        rows = self.rows(bench_args, bench_stats, [1, 2, 3])
        ticks = []
        monkeypatch.setattr(bgperf2.plt, 'xticks',
                            lambda x, labels: ticks.append(list(labels)))

        bgperf2.create_batch_graphs(rows, 'reps', results_dir=str(tmp_path))

        assert (tmp_path / 'bgperf_reps_total_time.png').exists()
        assert ticks and all(t == ['bird #1', 'bird #2', 'bird #3'] for t in ticks)

    def test_rows_that_share_a_name_collapse_to_one_bar(
            self, bench_args, bench_stats, tmp_path, monkeypatch):
        rows = self.rows(bench_args, bench_stats, [None, None])
        ticks = []
        monkeypatch.setattr(bgperf2.plt, 'xticks',
                            lambda x, labels: ticks.append(list(labels)))
        try:
            bgperf2.create_batch_graphs(rows, 'clash', results_dir=str(tmp_path))
        except Exception:
            return  # some matplotlib versions refuse the mismatch outright
        assert ticks and all(t == ['bird'] for t in ticks), (
            'two runs, one tick: the second observation is not on the graph')


class TestNameAndIdentityAgree:
    '''The run name and the cell id must say the same thing about a pass.

    They disagreed once: the name was only suffixed when a test asked for more
    than one pass, while the id always carried `repetition: 1`. A completed
    single-pass batch whose config then gained `repetitions: 3` matched its
    stored pass-1 ids under `--resume` -- which `scripts/run_2026_suite.sh`
    passes by default -- reused those rows unchanged, and produced a CSV
    holding `bird` beside `bird #2` and `bird #3`.
    '''

    def test_adding_repetitions_invalidates_the_single_pass_ids(self):
        single = a_test(neighbors=[1])
        repeated = a_test(neighbors=[1], repetitions=3)
        single_ids = {bgperf2.batch_cell_id('reps', c)
                      for c in bgperf2.expand_batch_cells(single, single['targets'])}
        repeated_ids = {bgperf2.batch_cell_id('reps', c)
                        for c in bgperf2.expand_batch_cells(repeated, repeated['targets'])}
        assert not (single_ids & repeated_ids)

    def test_resume_across_that_change_re_runs_rather_than_mixing(
            self, fake_img_exists, tmp_path, monkeypatch):
        fake_img_exists(lambda name: True)
        monkeypatch.setattr(bgperf2, 'create_batch_graphs', lambda *a, **k: None)
        config = tmp_path / 'reps.yaml'
        ran = []
        monkeypatch.setattr(
            bgperf2, 'bench',
            lambda a: ran.append(bgperf2.run_name(a)) or [bgperf2.run_name(a)])
        args = Namespace(batch_config=str(config), results_dir=str(tmp_path), resume=True)

        config.write_text(yaml.safe_dump({'tests': [a_test(neighbors=[1])]}))
        bgperf2.batch(args)
        assert ran == ['bird']

        ran.clear()
        config.write_text(yaml.safe_dump({'tests': [a_test(neighbors=[1], repetitions=3)]}))
        bgperf2.batch(args)

        assert ran == ['bird #1', 'bird #2', 'bird #3']
        rows = (tmp_path / 'reps.csv').read_text().splitlines()[1:]
        assert rows == ['bird #1', 'bird #2', 'bird #3'], 'an unnamed pass survived'


class TestCheckBatchTest:
    '''A test that cannot be expanded should say so, not raise a KeyError.'''

    @pytest.mark.parametrize('key', ['name', 'neighbors', 'prefixes', 'filter_test', 'targets'])
    def test_a_missing_axis_is_named(self, key):
        test = a_test()
        del test[key]
        with pytest.raises(SystemExit) as e:
            bgperf2.expand_batch_cells(test, test.get('targets') or [])
        assert key in str(e.value)

    @pytest.mark.parametrize('value', [[], None, 'None', 10])
    def test_an_axis_that_is_not_a_list_of_values_is_rejected(self, value):
        '''`filter_test: None` expands to nothing and `filter_test: transit`
        iterates the string one character at a time.
        '''
        test = a_test(filter_test=value)
        with pytest.raises(SystemExit) as e:
            bgperf2.expand_batch_cells(test, test['targets'])
        assert 'filter_test' in str(e.value)

    def test_a_bad_axis_stops_before_the_first_container(
            self, fake_img_exists, tmp_path, monkeypatch):
        fake_img_exists(lambda name: True)
        ran = []
        monkeypatch.setattr(bgperf2, 'bench', lambda a: ran.append(a) or [])
        bad = a_test(name='bad')
        del bad['filter_test']
        config = tmp_path / 'bad.yaml'
        config.write_text(yaml.safe_dump({'tests': [a_test(name='good'), bad]}))

        with pytest.raises(SystemExit):
            bgperf2.batch(Namespace(batch_config=str(config), results_dir=str(tmp_path)))
        assert ran == []
