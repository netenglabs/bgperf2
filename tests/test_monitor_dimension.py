"""`--monitor gobgp|sink`: the instrument as a run dimension (measurement plan
7a, docs/invariants/workload-controls.md).

The sink is the default since 7d, and GoBGP stays selectable to re-check a sink
cell against. One cell measured with each is the same workload, so the
instrument has to reach everything a dimension reaches -- the entry points, the
cell id, the artifact stem and both `run` blocks -- or the two overwrite or
resume into each other.
"""
from argparse import Namespace

import pytest

import base
import bgperf2


class TestNames:
    def args(self, **kw):
        a = Namespace(target='bird', label=None, version=None,
                      tester_type='bird', prefix_num=100, neighbor_num=10,
                      filter_test=None)
        for k, v in kw.items():
            setattr(a, k, v)
        return a

    def test_gobgp_keeps_the_name_every_existing_artifact_has(self):
        assert bgperf2.bench_output_prefix(self.args(monitor='gobgp')) == \
            'bird_bird_100_10'

    def test_the_default_is_the_sink_and_is_marked(self):
        '''7d. The omission stays with the instrument the old rows were
        measured on, not with the default, or every one of them is renamed.'''
        assert bgperf2.DEFAULT_MONITOR == 'sink'
        assert bgperf2.UNMARKED_MONITOR == 'gobgp'
        for args in (self.args(), self.args(monitor=None), self.args(monitor='sink')):
            assert bgperf2.bench_output_prefix(args) == 'bird_bird_100_10_mon-sink'

    def test_every_monitor_class_is_selectable(self):
        assert set(bgperf2.MONITOR_TYPES) == set(bgperf2.MONITOR_CLASSES)
        assert bgperf2.DEFAULT_MONITOR in bgperf2.MONITOR_TYPES


class TestCli:
    def test_bench_takes_it_and_config_does_not(self):
        parser = bgperf2.create_args_parser()
        assert parser.parse_args(['bench']).monitor == 'sink'
        assert parser.parse_args(['bench', '--monitor', 'gobgp']).monitor == 'gobgp'
        with pytest.raises(SystemExit):
            parser.parse_args(['bench', '--monitor', 'bird'])
        with pytest.raises(SystemExit):
            parser.parse_args(['config', '--monitor', 'sink'])


class TestBenchImage:
    def args(self, **kw):
        a = Namespace(dir='/tmp', bench_name='x', docker_network_name=None,
                      file=None, target='bird', version=None, image=None,
                      repeat=False, neighbor_num=10, prefix_num=100,
                      prefix_scope='per-peer', tester_type='bird',
                      mrt_file=None, mrt_injector=None, path_diversity=1,
                      receivers=0, pin=None, monitor='sink')
        for k, v in kw.items():
            setattr(a, k, v)
        return a

    def test_an_unbuilt_monitor_is_refused_before_the_teardown(self, monkeypatch):
        asked = []
        monkeypatch.setattr(bgperf2, 'target_image', lambda *a: 'bgperf/bird:latest')
        monkeypatch.setattr(base, 'img_exists',
                            lambda tag, images=None: asked.append(tag) or False)

        def no_teardown():
            raise AssertionError('tore down before refusing')
        monkeypatch.setattr(bgperf2, 'remove_target_containers', no_teardown)
        with pytest.raises(SystemExit, match='bgperf/sink'):
            bgperf2.bench(self.args())
        assert asked == ['bgperf/sink:latest']

    def test_the_receivers_image_is_checked_when_the_run_has_receivers(self, monkeypatch):
        '''Found in review: the receivers are their own class, and when it was
        not the monitor's, a run with receivers on a host without their image
        passed the check and died at `create_container` after the teardown.'''
        class OtherReceiver(base.Container):
            IMAGE_REPO = 'bgperf/other-receiver'
        monkeypatch.setitem(bgperf2.RECEIVER_CLASSES, 'sink', OtherReceiver)
        monkeypatch.setattr(bgperf2, 'target_image', lambda *a: 'bgperf/bird:latest')
        monkeypatch.setattr(base, 'img_exists', lambda tag, images=None:
                            tag.startswith('bgperf/sink'))

        def no_teardown():
            raise AssertionError('tore down before refusing')
        monkeypatch.setattr(bgperf2, 'remove_target_containers', no_teardown)
        with pytest.raises(SystemExit, match='bgperf/other-receiver'):
            bgperf2.bench(self.args(receivers=2))
        # and not asked for when the run has none
        monkeypatch.setattr(bgperf2, 'remove_target_containers',
                            lambda: (_ for _ in ()).throw(StopIteration('reached')))
        with pytest.raises(StopIteration):
            bgperf2.bench(self.args(receivers=0))


class TestBatch:
    def test(self, **kw):
        test = {'name': 't', 'neighbors': [10], 'prefixes': [100],
                'filter_test': [None],
                'targets': [{'name': 'bird', 'tester_type': 'bird'}]}
        test.update(kw)
        return test

    def test_it_is_a_test_key(self):
        assert 'monitor' in bgperf2.BATCH_TEST_OPTIONAL_KEYS
        # under a target it would be ignored, and that target measured with
        # the default instrument while the operator believed otherwise
        assert 'monitor' in bgperf2.BATCH_TEST_ONLY_KEYS

    def test_an_unknown_monitor_is_refused_before_the_matrix(self):
        with pytest.raises(SystemExit, match='unknown monitor'):
            bgperf2.check_batch_test(self.test(monitor='bird'))

    def test_under_a_target_it_is_refused(self):
        test = self.test()
        test['targets'][0]['monitor'] = 'sink'
        with pytest.raises(SystemExit):
            bgperf2.check_batch_test(test)

    def test_cells_carry_it(self):
        test = self.test(monitor='gobgp')
        assert [c['monitor'] for c in
                bgperf2.expand_batch_cells(test, test['targets'])] == ['gobgp']
        test = self.test()
        assert [c['monitor'] for c in
                bgperf2.expand_batch_cells(test, test['targets'])] == ['sink']

    def test_the_id_and_description_name_only_the_sink(self):
        test = self.test(monitor='gobgp')
        cell = bgperf2.expand_batch_cells(test, test['targets'])[0]
        old_cell = {k: v for k, v in cell.items() if k != 'monitor'}
        # An id written before the flag existed resumes.
        assert bgperf2.batch_cell_id('t', cell) == bgperf2.batch_cell_id('t', old_cell)
        assert 'monitor' not in bgperf2.batch_cell_description(cell)
        sink = dict(cell, monitor='sink')
        assert bgperf2.batch_cell_id('t', sink) != bgperf2.batch_cell_id('t', cell)
        assert 'monitor=sink' in bgperf2.batch_cell_description(sink)

    def test_an_old_id_is_still_gobgp_after_the_flip(self):
        '''A cell id omits `monitor` on GoBGP. Read as the default, every
        GoBGP cell measured before 7d -- which `timing_variance_review.py`
        reads back from progress files -- would be described as a sink cell.'''
        import json
        test = self.test(monitor='gobgp')
        old = json.loads(bgperf2.batch_cell_id(
            't', bgperf2.expand_batch_cells(test, test['targets'])[0]))
        assert 'monitor' not in old
        assert bgperf2.cell_monitor(old) == 'gobgp'
        assert 'monitor' not in bgperf2.batch_cell_description(old)

    def test_a_config_with_no_monitor_does_not_resume_into_gobgp_rows(self):
        '''A batch with no `monitor:` key ran GoBGP before 7d and runs the
        sink after it. Its old rows must not be reused under the new
        instrument, so the ids must differ.'''
        before = self.test(monitor='gobgp')
        after = self.test()
        assert bgperf2.batch_cell_id('t', bgperf2.expand_batch_cells(
            before, before['targets'])[0]) != bgperf2.batch_cell_id(
            't', bgperf2.expand_batch_cells(after, after['targets'])[0])

    def test_a_missing_monitor_image_ends_the_batch_before_it_starts(self, monkeypatch):
        monkeypatch.setattr(base, 'img_exists', lambda tag, images=None:
                            not tag.startswith('bgperf/sink'))
        bgperf2.check_batch_monitor_images([self.test(monitor='gobgp')])
        with pytest.raises(SystemExit, match='bgperf/sink'):
            bgperf2.check_batch_monitor_images(
                [self.test(monitor='gobgp'), self.test()])

    def test_a_missing_receiver_image_ends_the_batch_before_it_starts(self, monkeypatch):
        class OtherReceiver(base.Container):
            IMAGE_REPO = 'bgperf/other-receiver'
        monkeypatch.setitem(bgperf2.RECEIVER_CLASSES, 'sink', OtherReceiver)
        monkeypatch.setattr(base, 'img_exists', lambda tag, images=None:
                            not tag.startswith('bgperf/other-receiver'))
        bgperf2.check_batch_monitor_images([self.test(monitor='sink')])
        with pytest.raises(SystemExit, match='bgperf/other-receiver'):
            bgperf2.check_batch_monitor_images([self.test(monitor='sink', receivers=2)])

    def test_the_receivers_follow_the_monitor(self):
        assert bgperf2.RECEIVER_CLASSES['gobgp'] is bgperf2.Receiver
        assert bgperf2.RECEIVER_CLASSES['sink'] is bgperf2.SinkReceiver
        assert set(bgperf2.RECEIVER_CLASSES) == set(bgperf2.MONITOR_TYPES)


class TestRecorded:
    def test_provenance_names_the_instrument_that_ran(self):
        class Ctn:
            image = 'bgperf/sink:latest'

            def version_string(self):
                return '0.1.0 (src c47b36384df1; gobgp/v4 v4.9.0; go1.25.14)'

        class Target(Ctn):
            image = 'bgperf/bird:latest'

        doc = bgperf2.collect_provenance(
            Namespace(target='bird', monitor='sink'), Target(), Ctn(), [])
        assert doc['monitor']['daemon'] == 'sink'
        assert doc['monitor']['image'].startswith('bgperf/sink')
        doc = bgperf2.collect_provenance(Namespace(target='bird'), Target(), Ctn(), [])
        assert doc['monitor']['daemon'] == 'sink'
        doc = bgperf2.collect_provenance(
            Namespace(target='bird', monitor='gobgp'), Target(), Ctn(), [])
        assert doc['monitor']['daemon'] == 'gobgp'


@pytest.mark.parametrize('scenario', [None, 'scenario.yaml'])
def test_both_run_blocks_record_it_under_f_too(tmp_path, scenario):
    '''bgperf2 starts the monitor whatever wrote the scenario, so unlike the
    workload keys this is known under `-f` as well.'''
    import json
    args = Namespace(target='bird', label=None, version=None,
                     tester_type='bird', prefix_num=1_000, neighbor_num=10,
                     filter_test=None, file=scenario, path_diversity=1,
                     receivers=0, monitor='sink', results_dir=str(tmp_path))
    bgperf2.write_provenance(args, {}, 'run')
    bgperf2.write_event_artifact(args, [], 'run', 'converged')
    with open(tmp_path / 'run.versions.json') as f:
        assert json.load(f)['run']['monitor'] == 'sink'
    with open(tmp_path / 'run.events.json') as f:
        assert json.load(f)['run']['monitor'] == 'sink'


class TestResumeAcrossTheFlip:
    '''Rows one instrument measured must not be resumed under another. Found
    in review twice: a test with no `monitor:` (GoBGP before 7d, the sink
    after), and then an explicit `monitor:` edited between runs. Each re-ran
    every cell and carried the old rows forward beside the new ones.'''

    def write(self, tmp_path, test, monitor):
        cells = bgperf2.expand_batch_cells(dict(test, monitor=monitor),
                                           test['targets'])
        bgperf2.write_batch_progress(
            str(tmp_path / 't.progress.json'),
            {bgperf2.batch_cell_id('t', c): ['row'] for c in cells},
            order='matrix', seed=None, previous_seeds=[])

    def a_test(self, **kw):
        test = {'name': 't', 'neighbors': [10], 'prefixes': [100],
                'filter_test': [None], 'targets': [{'name': 'bird'}]}
        test.update(kw)
        return test

    def test_gobgp_rows_under_a_test_naming_no_monitor_are_refused(self, tmp_path):
        test = self.a_test()
        self.write(tmp_path, test, 'gobgp')
        with pytest.raises(SystemExit, match='1 cell\\(s\\) under gobgp, and this '
                           'test runs under sink'):
            bgperf2.check_resume_across_monitor_flip([test], str(tmp_path))

    def test_an_edited_monitor_is_refused_too(self, tmp_path):
        test = self.a_test()
        self.write(tmp_path, test, 'gobgp')
        with pytest.raises(SystemExit, match='under gobgp'):
            bgperf2.check_resume_across_monitor_flip(
                [self.a_test(monitor='sink')], str(tmp_path))
        self.write(tmp_path, test, 'sink')
        with pytest.raises(SystemExit, match='under sink, and this test runs under gobgp'):
            bgperf2.check_resume_across_monitor_flip(
                [self.a_test(monitor='gobgp')], str(tmp_path))

    def test_rows_of_the_instrument_the_test_runs_resume(self, tmp_path):
        test = self.a_test()
        self.write(tmp_path, test, 'gobgp')
        bgperf2.check_resume_across_monitor_flip(
            [self.a_test(monitor='gobgp')], str(tmp_path))
        self.write(tmp_path, test, 'sink')
        bgperf2.check_resume_across_monitor_flip([test], str(tmp_path))
        bgperf2.check_resume_across_monitor_flip([test], str(tmp_path / 'none'))


def test_the_repetition_check_reads_an_archived_config_as_gobgp():
    '''It only ever checks the timing-validation blocks, all GoBGP, and the
    rendered copies it reads were snapshotted with no `monitor:` key.'''
    import sys
    sys.path.insert(0, str(bgperf2.REPO_ROOT / 'scripts'))
    try:
        import check_repetition_configs as check
    finally:
        sys.path.pop(0)
    test = {'name': 't', 'neighbors': [10], 'prefixes': [100],
            'filter_test': [None], 'targets': [{'name': 'bird'}]}
    assert not any('monitor' in d for d in check.cells_of(test))
    assert 'monitor' not in test
    assert all('monitor=sink' in d for d in check.cells_of(dict(test, monitor='sink')))
