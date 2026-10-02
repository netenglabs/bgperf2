"""`--pin`: per-role cpusets, and the guards that refuse a layout that cannot
hold (comparison plan §4 item 2, docs/invariants/workload-controls.md)."""
from argparse import Namespace

import pytest

import base
import bgperf2

HOST = frozenset(range(16))
LAYOUT = 'target=0-7,monitor=8-9,testers=10-15'


class TestCpuLists:
    @pytest.mark.parametrize('text, cpus', [
        ('0', {0}), ('0-3', {0, 1, 2, 3}), ('0-1,4,6-7', {0, 1, 4, 6, 7})])
    def test_parse(self, text, cpus):
        assert bgperf2.parse_cpu_list(text) == cpus

    @pytest.mark.parametrize('text', ['', 'a', '3-1', '1-', '-1', '1.5'])
    def test_parse_refuses(self, text):
        with pytest.raises(ValueError):
            bgperf2.parse_cpu_list(text)

    def test_format_is_shortest(self):
        assert bgperf2.format_cpu_list({8, 0, 1, 2, 3, 10}) == '0-3,8,10'


class TestResolvePin:
    def test_unset_is_unpinned(self):
        assert bgperf2.resolve_pin(None, 0, HOST) is None
        assert bgperf2.resolve_pin('', 0, HOST) is None

    def test_a_full_layout_is_canonical(self):
        assert bgperf2.resolve_pin(LAYOUT, 0, HOST) == LAYOUT

    def test_two_spellings_are_one_layout(self):
        assert bgperf2.resolve_pin(
            'testers=15,10-14,monitor=9,8,target=0-3,4-7', 0, HOST) == LAYOUT

    def test_a_comma_list_extends_the_role_before_it(self):
        assert bgperf2.resolve_pin(
            'target=0,2,monitor=4,testers=5', 0, HOST) == \
            'target=0,2,monitor=4,testers=5'

    @pytest.mark.parametrize('spec', ['target=0-7,monitor=8-9',
                                      'monitor=8-9,testers=10-15'])
    def test_an_unnamed_role_is_refused(self, spec):
        with pytest.raises(ValueError, match='unpinned'):
            bgperf2.resolve_pin(spec, 0, HOST)

    def test_receivers_must_be_named_when_the_run_has_them(self):
        with pytest.raises(ValueError, match='receivers'):
            bgperf2.resolve_pin(LAYOUT, 2, HOST)
        assert bgperf2.resolve_pin(
            'target=0-5,monitor=6,testers=7-13,receivers=14-15', 2, HOST) \
            .endswith('receivers=14-15')

    def test_receivers_without_receivers_is_refused(self):
        with pytest.raises(ValueError, match='has none'):
            bgperf2.resolve_pin(LAYOUT + ',receivers=0', 0, frozenset(range(17)))

    def test_overlap_is_refused(self):
        with pytest.raises(ValueError, match='disjoint'):
            bgperf2.resolve_pin('target=0-8,monitor=8-9,testers=10-15', 0, HOST)

    def test_cpus_the_host_lacks_are_refused(self):
        with pytest.raises(ValueError, match='does not have'):
            bgperf2.resolve_pin(LAYOUT, 0, frozenset(range(8)))

    @pytest.mark.parametrize('spec', ['bogus=1', 'target=1,target=2',
                                      '0-3', 'target=x', 17])
    def test_bad_syntax_is_refused(self, spec):
        with pytest.raises(ValueError):
            bgperf2.resolve_pin(spec, 0, HOST)

    def test_cpusets_round_trip(self):
        assert bgperf2.pin_cpusets('target=0,2,monitor=4,testers=5-6') == {
            'target': '0,2', 'monitor': '4', 'testers': '5-6'}
        assert bgperf2.pin_cpusets(None) == {}


class TestArtifactNames:
    def args(self, **kw):
        a = Namespace(monitor='gobgp', target='bird', label=None, version=None,
                      tester_type='bird', prefix_num=100, neighbor_num=10,
                      filter_test=None)
        for k, v in kw.items():
            setattr(a, k, v)
        return a

    def test_unpinned_keeps_its_name(self):
        assert bgperf2.bench_output_prefix(self.args()) == \
            bgperf2.bench_output_prefix(self.args(pin=None))

    def test_pinned_and_unpinned_differ(self):
        stem = bgperf2.bench_output_prefix(self.args(pin='target=0,2,monitor=4,testers=5'))
        assert stem != bgperf2.bench_output_prefix(self.args())
        assert stem.endswith('_pin.target0+2.monitor4.testers5')
        assert ',' not in stem and ' ' not in stem


class TestBenchEntryPoint:
    def args(self, **kw):
        a = Namespace(dir='/tmp', bench_name='x', docker_network_name=None,
                      file=None, target='bird', version=None, image=None,
                      repeat=False, neighbor_num=10, prefix_num=100,
                      prefix_scope='per-peer', tester_type='bird',
                      mrt_file=None, mrt_injector=None, path_diversity=1,
                      receivers=0, pin=LAYOUT)
        for k, v in kw.items():
            setattr(a, k, v)
        return a

    @pytest.fixture(autouse=True)
    def no_docker(self, monkeypatch):
        class NoDocker:
            def __getattr__(self, name):
                raise AssertionError('asked Docker (dckr.{0})'.format(name))
        monkeypatch.setattr(bgperf2, 'dckr', NoDocker())
        monkeypatch.setattr(base, 'dckr', NoDocker())
        monkeypatch.setattr(bgperf2, 'host_cpus', lambda: HOST)

    def test_repeat_is_refused_before_docker(self):
        with pytest.raises(SystemExit, match='repeat'):
            bgperf2.bench(self.args(repeat=True))

    def test_a_bad_layout_is_refused_before_docker(self):
        with pytest.raises(SystemExit, match='unpinned'):
            bgperf2.bench(self.args(pin='target=0-7'))

    def test_receivers_are_read_from_the_command_line(self):
        with pytest.raises(SystemExit, match='receivers'):
            bgperf2.bench(self.args(receivers=2))

    def test_a_remote_scenario_target_is_refused(self, tmp_path):
        scenario = tmp_path / 's.yaml'
        scenario.write_text('target: {remote: true, local-address: 10.0.0.1}\n')
        with pytest.raises(SystemExit, match='remote'):
            bgperf2.bench(self.args(file=str(scenario)))

    def test_a_scenario_states_its_own_receivers(self, tmp_path):
        scenario = tmp_path / 's.yaml'
        scenario.write_text(
            'target: {local-address: 10.0.0.1}\n'
            'receivers: [{as: 1, router-id: 1.1.1.1, local-address: 10.0.0.9}]\n')
        with pytest.raises(SystemExit, match='receivers'):
            bgperf2.bench(self.args(file=str(scenario)))

    def test_config_does_not_take_it(self):
        parser = bgperf2.create_args_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(['config', '--pin', LAYOUT])
        assert parser.parse_args(['bench', '--pin', LAYOUT]).pin == LAYOUT


class TestRepeatAfterAPinnedRun:
    def test_pinned_testers_are_named(self):
        names = ['bgperf_bird_tester_tester10', 'bgperf_bird_tester_tester2',
                 'bgperf_monitor', 'bgperf_bird_target']
        assert bgperf2.pinned_tester_containers(
            names, lambda n: '10-15') == ['bgperf_bird_tester_tester2',
                                         'bgperf_bird_tester_tester10']

    def test_unpinned_testers_pass(self):
        assert bgperf2.pinned_tester_containers(
            ['bgperf_bird_tester_tester0'], lambda n: '') == []


class TestBatch:
    def test(self, **kw):
        test = {'name': 't', 'neighbors': [10], 'prefixes': [100],
                'filter_test': [None],
                'targets': [{'name': 'bird', 'tester_type': 'bird'}]}
        test.update(kw)
        return test

    @pytest.fixture(autouse=True)
    def host(self, monkeypatch):
        monkeypatch.setattr(bgperf2, 'host_cpus', lambda: HOST)

    def test_it_is_a_test_key(self):
        assert 'pin' in bgperf2.BATCH_TEST_OPTIONAL_KEYS
        assert 'pin' in bgperf2.BATCH_TEST_ONLY_KEYS

    def test_a_bad_layout_is_refused_before_the_matrix(self):
        with pytest.raises(SystemExit, match='unpinned'):
            bgperf2.check_batch_test(self.test(pin='target=0-7'))

    def test_repeat_is_refused(self):
        test = self.test(pin=LAYOUT)
        test['targets'][0]['repeat'] = True
        with pytest.raises(SystemExit, match='repeat'):
            bgperf2.check_batch_test(test)

    def test_receivers_on_the_test_must_be_pinned(self):
        with pytest.raises(SystemExit, match='receivers'):
            bgperf2.check_batch_test(self.test(pin=LAYOUT, receivers=2))

    def test_cells_carry_the_canonical_layout(self):
        test = self.test(pin='testers=10-15,monitor=8-9,target=0-7')
        cells = bgperf2.expand_batch_cells(test, test['targets'])
        assert [c['pin'] for c in cells] == [LAYOUT]

    def test_the_id_and_description_name_it_only_when_set(self):
        test = self.test()
        cell = bgperf2.expand_batch_cells(test, test['targets'])[0]
        assert 'pin' not in bgperf2.batch_cell_id('t', cell)
        assert 'pin' not in bgperf2.batch_cell_description(cell)
        pinned = dict(cell, pin=LAYOUT)
        assert bgperf2.batch_cell_id('t', pinned) != \
            bgperf2.batch_cell_id('t', cell)
        assert 'pin=' + LAYOUT in bgperf2.batch_cell_description(pinned)


class TestContainer:
    def test_unpinned_by_default(self, tmp_path):
        c = base.Container('x', 'img', str(tmp_path / 'd'), '/root/config', {})
        assert c.cpuset is None


class TestBatchPinAgainstRepeat:
    def tests(self, pin_first=True):
        pinned = {'name': 'a', 'pin': LAYOUT, 'targets': [{'name': 'bird'}]}
        repeat = {'name': 'b', 'targets': [{'name': 'bird', 'repeat': True}]}
        return [pinned, repeat] if pin_first else [repeat, pinned]

    @pytest.mark.parametrize('pin_first', [True, False])
    def test_a_mix_is_refused_in_either_order(self, pin_first, monkeypatch):
        monkeypatch.setattr(bgperf2, 'get_ctn_names', lambda: [])
        with pytest.raises(SystemExit, match='separate batches'):
            bgperf2.check_batch_pin_and_repeat(self.tests(pin_first))

    def test_leftover_pinned_testers_are_refused_up_front(self, monkeypatch):
        class Dckr:
            def inspect_container(self, name):
                return {'HostConfig': {'CpusetCpus': '6-7'}}
        monkeypatch.setattr(bgperf2, 'dckr', Dckr())
        monkeypatch.setattr(bgperf2, 'get_ctn_names',
                            lambda: ['bgperf_bird_tester_tester0'])
        with pytest.raises(SystemExit, match='pinned run'):
            bgperf2.check_batch_pin_and_repeat(self.tests()[1:])

    def test_no_repeat_asks_nothing(self, monkeypatch):
        monkeypatch.setattr(bgperf2, 'get_ctn_names',
                            lambda: pytest.fail('asked Docker'))
        bgperf2.check_batch_pin_and_repeat(self.tests()[:1])
