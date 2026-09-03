'''Sequencing a batch, without moving what any of its cells is.

Matrix order runs every cell of one target next to every other cell of that
target, so anything that drifts over hours -- a thermal ramp, a filling page
cache, a neighbour's job that starts halfway through -- lands on the axes as a
pattern and leaves as a difference between the daemons. Permuting the order
does not remove the drift; it stops it lining up with one axis.

Two things must survive the permutation: a cell's identity, so `--resume` still
matches, and the matrix order of the report, because `create_graph()` pairs bar
heights with x labels positionally.
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
        'name': 'ord',
        'neighbors': [1, 2, 3],
        'prefixes': [10],
        'filter_test': ['None'],
        'targets': [{'name': 'bird'}, {'name': 'frr_c'}],
    }
    test.update(overrides)
    return test


def cells(**overrides):
    test = a_test(**overrides)
    return test, bgperf2.expand_batch_cells(test, test['targets'])


def sequence(order='shuffle', seed=7, **overrides):
    test, matrix = cells(**overrides)
    ordered = bgperf2.order_batch_cells(test['name'], matrix, order, seed)
    return [(c['repetition'], c['ordinal']) for c in ordered]


class TestBatchOrder:
    def test_matrix_is_the_default(self):
        assert bgperf2.batch_order(a_test()) == ('matrix', None)

    def test_an_unrecognised_order_is_rejected(self):
        '''Falling back to the matrix would make a batch that looks like it
        randomised and did not.'''
        with pytest.raises(SystemExit) as e:
            bgperf2.batch_order(a_test(order='random'))
        assert 'order' in str(e.value) and 'ord' in str(e.value)

    def test_a_seed_without_a_shuffle_is_rejected(self):
        '''A config that names a seed is asking to be permuted; running it in
        matrix order and saying nothing is the failure.'''
        with pytest.raises(SystemExit) as e:
            bgperf2.batch_order(a_test(seed=5))
        assert 'seed' in str(e.value)

    @pytest.mark.parametrize('value', ['5', 5.0, True, [5]])
    def test_a_seed_that_is_not_an_integer_is_rejected(self, value):
        with pytest.raises(SystemExit) as e:
            bgperf2.batch_order(a_test(order='shuffle', seed=value))
        assert 'seed' in str(e.value)

    def test_an_explicit_seed_is_kept(self):
        assert bgperf2.batch_order(a_test(order='shuffle', seed=5)) == ('shuffle', 5)

    def test_an_omitted_seed_is_drawn_rather_than_fixed(self):
        '''A constant default is one permutation, shared by every batch -- a
        permutation nobody chose is the pattern this exists to break.'''
        drawn = {bgperf2.batch_order(a_test(order='shuffle'))[1] for _ in range(5)}
        assert len(drawn) > 1
        assert all(isinstance(s, int) for s in drawn)


class TestOrderBatchCells:
    def test_matrix_order_is_the_enumeration_order(self):
        test, matrix = cells()
        assert bgperf2.order_batch_cells(test['name'], matrix, 'matrix', None) == matrix

    def test_a_shuffle_keeps_every_cell_exactly_once(self):
        test, matrix = cells(repetitions=2)
        ordered = bgperf2.order_batch_cells(test['name'], matrix, 'shuffle', 7)
        assert len(ordered) == len(matrix)
        assert sorted(map(id, ordered)) == sorted(map(id, matrix))

    def test_a_shuffle_actually_moves_something(self):
        assert sequence() != sequence(order='matrix')

    def test_the_same_seed_gives_the_same_order(self):
        assert sequence(seed=11) == sequence(seed=11)

    def test_a_different_seed_gives_a_different_order(self):
        assert any(sequence(seed=s) != sequence(seed=11) for s in range(20))

    def test_the_order_is_fixed_by_the_seed_alone(self):
        '''Pinned rather than merely reproducible in-process: the point of
        recording a seed is that the sequence can be rebuilt later, so it must
        not be a property of this interpreter's PRNG. Changing the keying
        scheme has to be a deliberate edit to this expectation.
        '''
        assert sequence(seed=7) == [
            (None, 5), (None, 0), (None, 2), (None, 1), (None, 4), (None, 3)]

    def test_a_pass_is_permuted_within_itself_and_never_across(self):
        '''A repetition stays a block, so an interrupted batch holds one
        observation of everything rather than every observation of the first
        few cells. Dealing the passes together would take that back.
        '''
        ordered = sequence(seed=7, repetitions=3)
        assert [r for r, _ in ordered] == [1] * 6 + [2] * 6 + [3] * 6

    def test_each_pass_draws_its_own_permutation(self):
        '''One permutation reused for every pass applies the same position
        bias three times, and the repetitions cannot average it out.'''
        ordered = sequence(seed=7, repetitions=3)
        passes = [[o for r, o in ordered if r == n] for n in (1, 2, 3)]
        assert len({tuple(p) for p in passes}) == 3
        assert all(sorted(p) == list(range(6)) for p in passes)

    def test_identity_does_not_move_with_the_order(self):
        '''`ordinal` is the cell's place in the matrix and the id says nothing
        about when it ran, which is what lets --resume match either way.'''
        test, matrix = cells(repetitions=2)
        before = {bgperf2.batch_cell_id(test['name'], c) for c in matrix}
        ordered = bgperf2.order_batch_cells(test['name'], matrix, 'shuffle', 7)
        assert {bgperf2.batch_cell_id(test['name'], c) for c in ordered} == before


class TestBatchReportRows:
    def test_rows_come_back_in_matrix_order_whatever_order_they_ran_in(self):
        '''create_graph() keys the x axis off the row names it sees and appends
        one bar height per row, pairing them positionally: a report in
        execution order gives it bars under the wrong labels, or a length
        mismatch, at the end of a batch that has already run for hours.
        '''
        test, matrix = cells()
        completed = {bgperf2.batch_cell_id(test['name'], c): [c['ordinal']]
                     for c in reversed(matrix)}
        assert bgperf2.batch_report_rows(test['name'], matrix, completed) == [
            [0], [1], [2], [3], [4], [5]]

    def test_a_partial_batch_reports_what_it_has(self):
        test, matrix = cells()
        completed = {bgperf2.batch_cell_id(test['name'], matrix[4]): ['row']}
        assert bgperf2.batch_report_rows(test['name'], matrix, completed) == [['row']]


class TestBatchRunsInTheOrderItRecorded:
    def write(self, tmp_path, **overrides):
        config = tmp_path / 'ord.yaml'
        config.write_text(yaml.safe_dump({'tests': [a_test(**overrides)]}))
        return str(config)

    def run(self, tmp_path, monkeypatch, args, ran, fail_on=None):
        def fake_bench(a):
            row = '{0}-{1}n'.format(a.target, a.neighbor_num)
            ran.append(row)
            if fail_on is not None and row == fail_on:
                raise RuntimeError('interrupted')
            return [row]

        monkeypatch.setattr(bgperf2, 'bench', fake_bench)
        monkeypatch.setattr(bgperf2, 'create_batch_graphs', lambda *a, **k: None)
        bgperf2.batch(args)

    def test_the_cells_run_shuffled_and_report_in_matrix_order(
            self, fake_img_exists, tmp_path, monkeypatch):
        fake_img_exists(lambda name: True)
        ran = []
        self.run(tmp_path, monkeypatch, Namespace(
            batch_config=self.write(tmp_path, order='shuffle', seed=7),
            results_dir=str(tmp_path)), ran)

        matrix = ['bird-1n', 'frr_c-1n', 'bird-2n', 'frr_c-2n', 'bird-3n', 'frr_c-3n']
        assert sorted(ran) == sorted(matrix)
        assert ran != matrix, 'seed 7 permutes this matrix'
        assert (tmp_path / 'ord.csv').read_text().splitlines()[1:] == matrix

    def test_the_seed_is_recorded_before_the_first_cell(
            self, fake_img_exists, tmp_path, monkeypatch):
        '''A seed written only once a cell finished would be missing from
        exactly the batches that died early.'''
        fake_img_exists(lambda name: True)
        seeds = []

        def record_then_fail(a):
            seeds.append(bgperf2.load_batch_progress_document(
                str(tmp_path / 'ord.progress.json')).get('seed'))
            raise RuntimeError('interrupted')

        monkeypatch.setattr(bgperf2, 'bench', record_then_fail)
        with pytest.raises(RuntimeError):
            bgperf2.batch(Namespace(
                batch_config=self.write(tmp_path, order='shuffle'),
                results_dir=str(tmp_path)))
        assert len(seeds) == 1 and isinstance(seeds[0], int)

    def test_resume_finishes_the_sequence_it_planned(
            self, fake_img_exists, tmp_path, monkeypatch):
        '''An interrupted batch resumed under a fresh permutation has run two
        orders, and neither one is the order it recorded.'''
        fake_img_exists(lambda name: True)
        config = self.write(tmp_path, order='shuffle')
        args = Namespace(batch_config=config, results_dir=str(tmp_path), resume=True)

        planned = []
        with pytest.raises(RuntimeError, match='interrupted'):
            self.run(tmp_path, monkeypatch, args, planned, fail_on='bird-1n')
        seed = bgperf2.load_batch_progress_document(
            str(tmp_path / 'ord.progress.json'))['seed']
        expected = [
            '{0}-{1}n'.format(c['target']['name'], c['neighbors'])
            for c in bgperf2.order_batch_cells(
                'ord', bgperf2.expand_batch_cells(a_test(), a_test()['targets']),
                'shuffle', seed)]

        resumed = []
        self.run(tmp_path, monkeypatch, args, resumed)

        # The interrupted cell did not complete, so it is the first thing the
        # resumed pass runs -- and the sequence either side of it is the one
        # the recorded seed describes.
        assert planned[:-1] + resumed == expected
        assert bgperf2.load_batch_progress_document(
            str(tmp_path / 'ord.progress.json'))['seed'] == seed

    def test_a_bad_order_stops_before_the_first_container(
            self, fake_img_exists, tmp_path, monkeypatch):
        fake_img_exists(lambda name: True)
        ran = []
        monkeypatch.setattr(bgperf2, 'bench', lambda a: ran.append(a) or [])
        config = tmp_path / 'bad.yaml'
        config.write_text(yaml.safe_dump({'tests': [
            a_test(name='good'),
            a_test(name='bad', order='sideways'),
        ]}))

        with pytest.raises(SystemExit):
            bgperf2.batch(Namespace(batch_config=str(config), results_dir=str(tmp_path)))
        assert ran == []

    def test_a_seed_the_config_states_is_not_overridden_by_the_record(
            self, fake_img_exists, tmp_path, monkeypatch):
        '''Recovering a drawn seed keeps a resumed batch on the sequence it
        planned; overriding a stated one would ignore an edit the operator
        made deliberately.'''
        fake_img_exists(lambda name: True)
        config = self.write(tmp_path, order='shuffle', seed=7)
        args = Namespace(batch_config=config, results_dir=str(tmp_path), resume=True)

        planned = []
        with pytest.raises(RuntimeError, match='interrupted'):
            self.run(tmp_path, monkeypatch, args, planned, fail_on='bird-1n')
        done = set(planned[:-1])
        assert done, 'the interrupted pass has to have completed something'
        self.write(tmp_path, order='shuffle', seed=11)

        resumed = []
        self.run(tmp_path, monkeypatch, args, resumed)

        assert bgperf2.load_batch_progress_document(
            str(tmp_path / 'ord.progress.json'))['seed'] == 11
        assert resumed == [
            row for row in (
                '{0}-{1}n'.format(c['target']['name'], c['neighbors'])
                for c in bgperf2.order_batch_cells(
                    'ord', bgperf2.expand_batch_cells(a_test(), a_test()['targets']),
                    'shuffle', 11))
            if row not in done]

    def test_a_superseded_seed_is_kept_beside_the_new_one(
            self, fake_img_exists, tmp_path, monkeypatch):
        '''The progress file is rewritten whole on every checkpoint, so a seed
        that is simply dropped leaves the document describing an order that
        some of its own completed rows did not run in.'''
        fake_img_exists(lambda name: True)
        config = self.write(tmp_path, order='shuffle', seed=7)
        args = Namespace(batch_config=config, results_dir=str(tmp_path), resume=True)

        with pytest.raises(RuntimeError, match='interrupted'):
            self.run(tmp_path, monkeypatch, args, [], fail_on='bird-1n')
        self.write(tmp_path, order='shuffle', seed=11)
        self.run(tmp_path, monkeypatch, args, [])

        document = bgperf2.load_batch_progress_document(
            str(tmp_path / 'ord.progress.json'))
        assert document['seed'] == 11
        assert document['previous_seeds'] == [{'order': 'shuffle', 'seed': 7}]

    def test_a_seed_no_row_ran_under_supersedes_nothing(
            self, fake_img_exists, tmp_path, monkeypatch):
        '''A batch that died in its first cell recorded a seed and no rows, so
        there is nothing for the old sequence to describe.'''
        fake_img_exists(lambda name: True)
        self.write(tmp_path, order='shuffle', seed=7)
        args = Namespace(batch_config=str(tmp_path / 'ord.yaml'),
                         results_dir=str(tmp_path), resume=True)
        monkeypatch.setattr(bgperf2, 'create_batch_graphs', lambda *a, **k: None)
        monkeypatch.setattr(bgperf2, 'bench', lambda a: (_ for _ in ()).throw(
            RuntimeError('interrupted')))
        with pytest.raises(RuntimeError, match='interrupted'):
            bgperf2.batch(args)
        assert bgperf2.load_batch_progress_document(
            str(tmp_path / 'ord.progress.json'))['cells'] == {}

        self.write(tmp_path, order='shuffle', seed=11)
        self.run(tmp_path, monkeypatch, args, [])

        document = bgperf2.load_batch_progress_document(
            str(tmp_path / 'ord.progress.json'))
        assert document['seed'] == 11 and 'previous_seeds' not in document

    def test_a_matrix_pass_resumed_as_a_shuffle_is_superseded(
            self, fake_img_exists, tmp_path, monkeypatch):
        '''The rows already on disk ran in matrix order. Recording only the new
        shuffle would have the file claim they ran under a permutation.'''
        fake_img_exists(lambda name: True)
        self.write(tmp_path, order='matrix')
        args = Namespace(batch_config=str(tmp_path / 'ord.yaml'),
                         results_dir=str(tmp_path), resume=True)
        with pytest.raises(RuntimeError, match='interrupted'):
            self.run(tmp_path, monkeypatch, args, [], fail_on='bird-2n')
        self.write(tmp_path, order='shuffle', seed=11)
        self.run(tmp_path, monkeypatch, args, [])

        document = bgperf2.load_batch_progress_document(
            str(tmp_path / 'ord.progress.json'))
        assert document['seed'] == 11
        assert document['previous_seeds'] == [{'order': 'matrix', 'seed': None}]

    def test_a_file_that_names_no_order_ran_in_the_only_one_there_was(
            self, fake_img_exists, tmp_path, monkeypatch):
        '''A progress file from a build without ordering resumes in matrix
        order and supersedes nothing -- there was no other order to have run
        in, so nothing about the record has changed.'''
        import json
        fake_img_exists(lambda name: True)
        self.write(tmp_path)
        progress = tmp_path / 'ord.progress.json'
        args = Namespace(batch_config=str(tmp_path / 'ord.yaml'),
                         results_dir=str(tmp_path), resume=True)
        with pytest.raises(RuntimeError, match='interrupted'):
            self.run(tmp_path, monkeypatch, args, [], fail_on='bird-2n')
        legacy = bgperf2.load_batch_progress_document(str(progress))
        progress.write_text(json.dumps(
            {'schema_version': 1, 'cells': legacy['cells']}))

        self.run(tmp_path, monkeypatch, args, [])

        assert 'previous_seeds' not in bgperf2.load_batch_progress_document(str(progress))
