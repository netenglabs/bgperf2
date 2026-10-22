'''Batch cell results, and the hooks that let a caller run a batch in pieces.

Every cell writes its row to its own document, so a batch can be listed, run
a few cells at a time, and reported from whatever has been recorded -- and the
report must match a batch that ran the whole matrix in one invocation.
'''
import json
from argparse import Namespace

import pytest
import yaml

import base
import bgperf2


@pytest.fixture
def fake_img_exists(monkeypatch):
    def _install(predicate):
        monkeypatch.setattr(base, 'img_exists', predicate)
        monkeypatch.setattr(bgperf2, 'img_exists', predicate)
    return _install


@pytest.fixture
def no_graphs(monkeypatch):
    drawn = []
    monkeypatch.setattr(bgperf2, 'create_batch_graphs',
                        lambda results, name, **k: drawn.append((name, len(results))))
    return drawn


def a_row(a):
    '''A stats row of the header's width, distinct per run.'''
    width = len(bgperf2.stats_header().split(','))
    row = [bgperf2.run_name(a)] + [0] * (width - 1)
    row[8] = a.neighbor_num * 10 + (a.repetition or 0)
    return row


@pytest.fixture
def fake_bench(monkeypatch):
    ran = []

    def bench(a):
        ran.append((bgperf2.run_name(a), a.neighbor_num))
        return a_row(a)
    monkeypatch.setattr(bgperf2, 'bench', bench)
    return ran


def write_config(tmp_path, **overrides):
    test = {
        'name': 'cells',
        'neighbors': [1, 2],
        'prefixes': [10],
        'filter_test': ['None'],
        'targets': [{'name': 'bird'}, {'name': 'frr_c'}],
    }
    test.update(overrides)
    path = tmp_path / 'cells.yaml'
    path.write_text(yaml.safe_dump({'tests': [test]}))
    return str(path)


def batch_args(config, results_dir, **flags):
    return Namespace(batch_config=config, results_dir=str(results_dir), **flags)


def listed(capsys, config, results_dir):
    capsys.readouterr()
    bgperf2.batch(batch_args(config, results_dir, list_cells=True))
    return json.loads(capsys.readouterr().out)


class TestCellResults:
    def test_every_cell_writes_its_own_result(
            self, fake_img_exists, no_graphs, fake_bench, tmp_path):
        fake_img_exists(lambda name: True)
        config = write_config(tmp_path)
        bgperf2.batch(batch_args(config, tmp_path))

        completed = bgperf2.load_batch_cell_results(str(tmp_path), 'cells')
        progress = bgperf2.load_batch_progress(str(tmp_path / 'cells.progress.json'))
        assert completed == progress
        assert len(completed) == 4

    def test_a_fresh_batch_clears_its_predecessors_results(
            self, fake_img_exists, no_graphs, fake_bench, tmp_path):
        fake_img_exists(lambda name: True)
        bgperf2.batch(batch_args(write_config(tmp_path), tmp_path))
        bgperf2.batch(batch_args(write_config(tmp_path, neighbors=[1]), tmp_path))

        assert len(bgperf2.load_batch_cell_results(str(tmp_path), 'cells')) == 2

    def test_resume_keeps_them(self, fake_img_exists, no_graphs, fake_bench, tmp_path):
        fake_img_exists(lambda name: True)
        config = write_config(tmp_path)
        bgperf2.batch(batch_args(config, tmp_path))
        fake_bench.clear()
        bgperf2.batch(batch_args(config, tmp_path, resume=True))

        assert fake_bench == []
        assert len(bgperf2.load_batch_cell_results(str(tmp_path), 'cells')) == 4

    @pytest.mark.parametrize('document', [
        [], {'schema_version': 2, 'cell_id': 'x', 'row': []},
        {'schema_version': 1, 'row': []}, {'schema_version': 1, 'cell_id': 'x'}])
    def test_a_malformed_result_is_refused_not_skipped(self, tmp_path, document):
        directory = tmp_path / 'cells.cells'
        directory.mkdir()
        (directory / (bgperf2.batch_cell_key('x') + '.json')).write_text(json.dumps(document))
        with pytest.raises(ValueError, match='malformed'):
            bgperf2.load_batch_cell_results(str(tmp_path), 'cells')

    def test_a_result_under_the_wrong_name_is_refused(self, tmp_path):
        bgperf2.write_batch_cell_result(str(tmp_path), 'cells', 'x', ['r'])
        directory = tmp_path / 'cells.cells'
        (directory / (bgperf2.batch_cell_key('x') + '.json')).rename(directory / 'other.json')
        with pytest.raises(ValueError, match='malformed'):
            bgperf2.load_batch_cell_results(str(tmp_path), 'cells')


class TestListCells:
    def test_lists_cells_in_run_order_without_docker_or_running(
            self, fake_img_exists, fake_bench, tmp_path, capsys):
        fake_img_exists(lambda name: pytest.fail('--list-cells asked about an image'))
        document = listed(capsys, write_config(tmp_path, order='shuffle', seed=7), tmp_path)

        [test] = document['tests']
        assert (test['name'], test['order'], test['seed']) == ('cells', 'shuffle', 7)
        expanded = bgperf2.expand_batch_config(str(tmp_path / 'cells.yaml'))
        _t, _targets, cells, order, seed = expanded[0]
        expected = [bgperf2.batch_cell_id('cells', c)
                    for c in bgperf2.order_batch_cells('cells', cells, order, seed)]
        assert [c['id'] for c in test['cells']] == expected
        assert [c['key'] for c in test['cells']] == [
            bgperf2.batch_cell_key(i) for i in expected]
        assert fake_bench == []

    def test_keys_are_unique_across_repetitions(self, tmp_path, capsys):
        document = listed(capsys, write_config(tmp_path, repetitions=3), tmp_path)
        keys = [c['key'] for c in document['tests'][0]['cells']]
        assert len(keys) == len(set(keys)) == 12


class TestSelectedCells:
    def test_runs_only_the_named_cells_in_the_named_order(
            self, fake_img_exists, no_graphs, fake_bench, tmp_path, capsys):
        fake_img_exists(lambda name: True)
        config = write_config(tmp_path)
        cells = listed(capsys, config, tmp_path)['tests'][0]['cells']

        bgperf2.batch(batch_args(config, tmp_path, cells=[cells[3]['key'], cells[0]['key']]))

        assert fake_bench == [('frr_c', 2), ('bird', 1)]
        assert not (tmp_path / 'cells.progress.json').exists()

    @pytest.mark.parametrize('keys', [['0000000000000000'], ['dup', 'dup']])
    def test_bad_keys_stop_before_the_first_container(
            self, fake_img_exists, fake_bench, tmp_path, capsys, keys):
        fake_img_exists(lambda name: True)
        config = write_config(tmp_path)
        first = listed(capsys, config, tmp_path)['tests'][0]['cells'][0]['key']
        keys = [first if k == 'dup' else k for k in keys]

        with pytest.raises(SystemExit, match='--cells'):
            bgperf2.batch(batch_args(config, tmp_path, cells=keys))
        assert fake_bench == []

    def test_only_the_selected_images_are_checked(
            self, fake_img_exists, no_graphs, fake_bench, tmp_path, capsys):
        config = write_config(tmp_path)
        cells = listed(capsys, config, tmp_path)['tests'][0]['cells']
        bird = [c['key'] for c in cells if c['description'].startswith('bird')]
        fake_img_exists(lambda name: 'frr' not in name)

        bgperf2.batch(batch_args(config, tmp_path, cells=bird))
        assert [name for name, _n in fake_bench] == ['bird', 'bird']


class TestReport:
    def outputs(self, directory):
        return ((directory / 'cells.csv').read_text(),
                json.loads((directory / 'cells.summary.json').read_text()))

    def test_running_in_pieces_reports_what_one_batch_reports(
            self, fake_img_exists, no_graphs, fake_bench, tmp_path, capsys):
        fake_img_exists(lambda name: True)
        whole, pieces = tmp_path / 'whole', tmp_path / 'pieces'
        config = write_config(tmp_path, repetitions=2, order='shuffle', seed=3)
        bgperf2.batch(batch_args(config, whole))

        keys = [c['key'] for c in listed(capsys, config, pieces)['tests'][0]['cells']]
        bgperf2.batch(batch_args(config, pieces, cells=keys[5:]))
        bgperf2.batch(batch_args(config, pieces, cells=list(reversed(keys[:5]))))
        assert self.outputs(pieces) == self.outputs(whole)

        (pieces / 'cells.csv').unlink()
        (pieces / 'cells.summary.json').unlink()
        bgperf2.batch(batch_args(config, pieces, report=True))
        assert self.outputs(pieces) == self.outputs(whole)
        assert no_graphs[-1] == ('cells', 8)

    def test_missing_cells_are_named_and_graphs_withheld(
            self, fake_img_exists, no_graphs, fake_bench, tmp_path, capsys):
        fake_img_exists(lambda name: True)
        config = write_config(tmp_path)
        keys = [c['key'] for c in listed(capsys, config, tmp_path)['tests'][0]['cells']]
        bgperf2.batch(batch_args(config, tmp_path, cells=keys[:3]))

        out = capsys.readouterr().out
        assert '1 of 4 cell(s) have no result' in out
        assert 'missing: frr_c, peers=2' in out
        assert no_graphs == []
        assert len((tmp_path / 'cells.csv').read_text().splitlines()) == 4

    def test_no_results_writes_nothing(self, no_graphs, tmp_path, capsys):
        config = write_config(tmp_path)
        bgperf2.batch(batch_args(config, tmp_path, report=True))

        assert 'nothing reported' in capsys.readouterr().out
        assert not (tmp_path / 'cells.csv').exists()


class TestCommandLine:
    def test_the_modes_are_exclusive(self):
        parser = bgperf2.create_args_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(['batch', '-c', 'x.yaml', '--resume', '--report'])

    def test_cells_takes_keys(self):
        args = bgperf2.create_args_parser().parse_args(
            ['batch', '-c', 'x.yaml', '--cells', 'a', 'b'])
        assert (args.cells, args.list_cells, args.report) == (['a', 'b'], False, False)


class TestReviewFixes:
    def test_resume_gives_progress_only_rows_their_documents(
            self, fake_img_exists, no_graphs, fake_bench, tmp_path, capsys):
        '''A batch begun by a build with no cell results must keep its rows.'''
        fake_img_exists(lambda name: True)
        config = write_config(tmp_path)
        bgperf2.batch(batch_args(config, tmp_path))
        for path in (tmp_path / 'cells.cells').glob('*.json'):
            path.unlink()
        fake_bench.clear()

        bgperf2.batch(batch_args(config, tmp_path, resume=True))
        assert fake_bench == []
        bgperf2.batch(batch_args(config, tmp_path, report=True))
        assert len((tmp_path / 'cells.csv').read_text().splitlines()) == 5

    def test_resume_reports_the_recorded_result_and_skips_its_cell(
            self, fake_img_exists, no_graphs, fake_bench, tmp_path, capsys):
        fake_img_exists(lambda name: True)
        config = write_config(tmp_path)
        keys = [c['key'] for c in listed(capsys, config, tmp_path)['tests'][0]['cells']]
        bgperf2.batch(batch_args(config, tmp_path, cells=keys[:1]))
        fake_bench.clear()

        bgperf2.batch(batch_args(config, tmp_path, resume=True))
        assert len(fake_bench) == 3, 'the cell run by --cells should not run again'

    def test_cells_refuses_to_replace_a_recorded_result(
            self, fake_img_exists, no_graphs, fake_bench, tmp_path, capsys):
        fake_img_exists(lambda name: True)
        config = write_config(tmp_path)
        key = listed(capsys, config, tmp_path)['tests'][0]['cells'][0]['key']
        bgperf2.batch(batch_args(config, tmp_path, cells=[key]))
        fake_bench.clear()

        with pytest.raises(SystemExit, match='already recorded'):
            bgperf2.batch(batch_args(config, tmp_path, cells=[key]))
        assert fake_bench == []

    def test_a_fresh_batch_says_what_it_removed(
            self, fake_img_exists, no_graphs, fake_bench, tmp_path, capsys):
        fake_img_exists(lambda name: True)
        config = write_config(tmp_path)
        bgperf2.batch(batch_args(config, tmp_path))
        capsys.readouterr()
        bgperf2.batch(batch_args(config, tmp_path))
        assert 'removed 4 recorded cell result(s)' in capsys.readouterr().out

    def test_a_partial_report_flags_earlier_graphs(
            self, fake_img_exists, no_graphs, fake_bench, tmp_path, capsys):
        fake_img_exists(lambda name: True)
        config = write_config(tmp_path)
        keys = [c['key'] for c in listed(capsys, config, tmp_path)['tests'][0]['cells']]
        (tmp_path / 'bgperf_cells_elapsed.png').write_bytes(b'old')
        bgperf2.batch(batch_args(config, tmp_path, cells=keys[:1]))
        assert 'drawn from other rows' in capsys.readouterr().out

    def test_list_cells_refuses_a_drawn_seed(self, tmp_path, capsys):
        with pytest.raises(SystemExit, match='seed'):
            bgperf2.batch(batch_args(write_config(tmp_path, order='shuffle'), tmp_path,
                                     list_cells=True))

    def test_tests_may_not_share_a_name(self, tmp_path):
        path = tmp_path / 'twice.yaml'
        test = {'name': 'same', 'neighbors': [1], 'prefixes': [10],
                'filter_test': ['None'], 'targets': [{'name': 'bird'}]}
        path.write_text(yaml.safe_dump({'tests': [test, dict(test, prefixes=[20])]}))
        with pytest.raises(SystemExit, match='same'):
            bgperf2.expand_batch_config(str(path))

    def test_interrupted_cell_writes_are_swept(self, tmp_path):
        (tmp_path / 'cells.cells').mkdir()
        (tmp_path / 'cells.cells' / 'abc.json.tmp').write_text('')
        assert bgperf2.sweep_stale_temp_files(str(tmp_path)) == ['cells.cells/abc.json.tmp']
