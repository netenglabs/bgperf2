'''Prefix length: synthetic tables of `/24`s as well as the historical `/32`s.

Every synthetic run bgperf2 has made announces `/32` host routes walked up from
100.0.0.0, and that walk must stay byte-identical: a 50 x 100,000 table already
walks through 100.64.0.0/10, so skipping reserved space at `/32` would change
the prefixes of runs that have been published. A shorter length is a new table
shape with its own walk, drawn from public unicast space.
'''
import ipaddress
from itertools import islice

import pytest

import prefix_length as pl


def overlaps_any(spans, networks):
    for start, end in spans:
        for network in networks:
            net = ipaddress.IPv4Network(network)
            lo, hi = int(net.network_address), int(net.broadcast_address) + 1
            if start < hi and lo < end:
                return network
    return None


class TestResolving:
    def test_absent_is_the_historical_length(self):
        assert pl.resolve_prefix_length(None) == 32

    def test_the_default_is_untouched_by_every_refusal(self):
        '''Refusing the default would refuse every run that predates the flag,
        MRT runs and oversized tables included.'''
        assert pl.resolve_prefix_length(32, 'bgpdump2', 10**12, '10.10.0.0/16',
                                        ('bgpdump2',)) == 32
        assert pl.resolve_prefix_length(32, 'exa') == 32

    def test_a_supported_length_is_returned(self):
        assert pl.resolve_prefix_length(24, 'bird', 1000, '10.10.0.0/16') == 24

    @pytest.mark.parametrize('value', [0, 16, 33, -24, 24.0, '24', True])
    def test_anything_else_is_refused(self, value):
        '''`True` is an `int`, and a quoted batch value would otherwise reach
        the walk as a bare `TypeError`.'''
        with pytest.raises(ValueError) as raised:
            pl.resolve_prefix_length(value)
        assert 'must be one of 24, 32' in str(raised.value)

    def test_an_mrt_generator_is_refused(self):
        with pytest.raises(ValueError) as raised:
            pl.resolve_prefix_length(24, 'bgpdump2', mrt_tester_types=('bgpdump2',))
        assert 'does not apply' in str(raised.value)

    def test_exabgp_is_refused(self):
        '''Unpinned and unversioned, and without the per-block attribute
        filters the policy workload needs.'''
        with pytest.raises(ValueError) as raised:
            pl.resolve_prefix_length(24, 'exa')
        assert "not 'exa'" in str(raised.value)

    def test_a_table_larger_than_the_walk_is_refused(self):
        available = pl.capacity(24, ('10.10.0.0/16',))
        assert pl.resolve_prefix_length(24, 'bird', available, '10.10.0.0/16') == 24
        with pytest.raises(ValueError) as raised:
            pl.resolve_prefix_length(24, 'bird', available + 1, '10.10.0.0/16')
        assert 'can supply {0:,}'.format(available) in str(raised.value)


class TestTheWalk:
    def test_it_starts_at_the_bottom_of_public_space(self):
        assert list(islice(pl.walk(24), 3)) == [
            '1.0.0.0/24', '1.0.1.0/24', '1.0.2.0/24']

    def test_it_is_deterministic(self):
        assert list(islice(pl.walk(24), 1000)) == list(islice(pl.walk(24), 1000))

    def test_no_reserved_range_is_walked(self):
        assert overlaps_any(pl._allowed_spans(24, ()), pl.RESERVED_NETWORKS) is None

    def test_it_stops_below_multicast(self):
        assert pl._allowed_spans(24, ())[-1][1] == pl.WALK_END

    def test_it_skips_the_peering_subnet(self):
        '''A route covering the subnet would capture the next hop every route
        in the run is announced with.'''
        spans = pl._allowed_spans(24, ('8.8.8.0/28',))
        assert overlaps_any(spans, ('8.8.8.0/28',)) is None
        assert pl.capacity(24, ('8.8.8.0/28',)) == pl.capacity(24) - 1

    def test_a_private_peering_subnet_costs_nothing(self):
        '''The default 10.10.0.0/16 is already inside a reserved range.'''
        assert pl.capacity(24, ('10.10.0.0/16',)) == pl.capacity(24)

    def test_the_skip_is_visible_in_the_walk(self):
        walked = list(islice(pl.walk(24, ('1.0.1.0/24',)), 2))
        assert walked == ['1.0.0.0/24', '1.0.2.0/24']

    def test_capacity_counts_what_the_walk_yields(self):
        exclude = ('1.0.0.0/9',)
        spans = pl._allowed_spans(24, exclude)
        assert pl.capacity(24, exclude) == sum((e - s) // 256 for s, e in spans)

    def test_capacity_at_24(self):
        '''Pinned so that an edit to the reserved list is a visible change to
        how large a /24 table may be.'''
        assert pl.capacity(24) == 14_461_947

    def test_the_historical_length_is_not_drawn_from_here(self):
        '''The /32 walk lives in the scenario preamble; a second definition of
        it would be two definitions of every published table.'''
        with pytest.raises(ValueError):
            next(pl.walk(32))
        with pytest.raises(ValueError):
            pl.capacity(32)


# ---------------------------------------------------------------------------
# Plumbing: the scenario, the names, the manifests and the four entry points.

import json
from argparse import Namespace

import yaml
from mako.template import Template

import bgperf2
import recipes


def a_test(**overrides):
    test = {'name': 'lengths', 'neighbors': [4], 'prefixes': [100],
            'filter_test': ['None'], 'targets': [{'name': 'bird'}]}
    test.update(overrides)
    return test


def scenario_args(**overrides):
    args = Namespace(
        neighbor_num=4, prefix_num=3, filter_type='in',
        as_path_list_num=0, prefix_list_num=0, community_list_num=0,
        ext_community_list_num=0, single_table=False,
        target_config_file=None, local_address_prefix='10.10.0.0/16',
        target_local_address=None, target_router_id=None,
        monitor_local_address=None, monitor_router_id=None,
        filter_test=None, license_file=None, threads=None,
        tester_type='bird', mrt_file=None, prefix_scope='per-peer',
        path_diversity=1)
    for name, value in overrides.items():
        setattr(args, name, value)
    return args


def render(args):
    return yaml.safe_load(Template(bgperf2.gen_conf(args)).render())


def offered(conf):
    return [n['paths'] for _, n in sorted(conf['testers'][0]['neighbors'].items())]


class TestTheScenario:
    def test_the_historical_scenario_is_byte_identical(self):
        '''An args namespace from before the flag and one asking for /32 must
        render the same text, preamble included.'''
        assert bgperf2.gen_conf(scenario_args()) == \
            bgperf2.gen_conf(scenario_args(prefix_length=32))

    def test_the_historical_preamble_is_untouched(self):
        assert bgperf2.gen_mako_macro() == bgperf2.gen_mako_macro(32, ('10.10.0.0/16',))
        assert "iter_iprange('100.0.0.0','160.0.0.0')" in bgperf2.gen_mako_macro()

    def test_the_default_still_walks_host_routes_from_100(self):
        assert offered(render(scenario_args()))[0] == [
            '100.0.0.0/32', '100.0.0.1/32', '100.0.0.2/32']

    def test_a_24_table_is_drawn_from_the_walk(self):
        paths = offered(render(scenario_args(prefix_length=24)))
        assert paths[0] == ['1.0.0.0/24', '1.0.1.0/24', '1.0.2.0/24']
        assert all(p.endswith('/24') for peer in paths for p in peer)
        flat = [p for peer in paths for p in peer]
        assert len(set(flat)) == len(flat) == 12

    def test_a_24_table_shares_blocks_under_path_diversity(self):
        paths = offered(render(scenario_args(prefix_length=24, path_diversity=2)))
        assert len({tuple(p) for p in paths}) == 2

    def test_the_checkpoint_does_not_move_with_the_length(self):
        assert render(scenario_args(prefix_length=24))['monitor']['check-points'] == \
            render(scenario_args())['monitor']['check-points']

    def test_the_peering_subnet_is_excluded(self):
        args = scenario_args(prefix_length=24, local_address_prefix='1.0.0.0/28')
        assert offered(render(args))[0][0] == '1.0.1.0/24'


class TestNamingAndProvenance:
    def args(self, **overrides):
        args = Namespace(monitor='gobgp', target='bird', label=None, version=None,
                         tester_type='bird', prefix_num=1_000, neighbor_num=10,
                         filter_test=None, file=None, path_diversity=1)
        for name, value in overrides.items():
            setattr(args, name, value)
        return args

    def test_the_default_keeps_its_stem(self):
        assert bgperf2.bench_output_prefix(self.args()) == 'bird_bird_1000_10'
        assert bgperf2.bench_output_prefix(self.args(prefix_length=32)) == \
            'bird_bird_1000_10'

    def test_the_stem_carries_the_length(self):
        assert bgperf2.bench_output_prefix(self.args(prefix_length=24)) == \
            'bird_bird_1000_10_pl24'

    @pytest.mark.parametrize('writer', ['provenance', 'events'])
    def test_both_run_blocks_record_it(self, tmp_path, writer):
        for args, expected in ((self.args(prefix_length=24), 24),
                               (self.args(), 32),
                               (self.args(file='scenario.yaml'), None),
                               (self.args(tester_type='bgpdump2'), None)):
            args.results_dir = str(tmp_path)
            if writer == 'provenance':
                path = bgperf2.write_provenance(args, {}, 'run')
            else:
                bgperf2.write_event_artifact(args, [], 'run', 'converged')
                path = tmp_path / 'run.events.json'
            with open(path) as f:
                assert json.load(f)['run']['prefix_length'] == expected


class TestTheCommandLineEntryPoints:
    def bench_args(self, **overrides):
        args = Namespace(dir='/tmp', bench_name='x', docker_network_name=None,
                         file=None, target='bird', version=None, image=None,
                         repeat=False, neighbor_num=10, prefix_num=100,
                         prefix_scope='per-peer', tester_type='bird',
                         mrt_file=None, mrt_injector=None, path_diversity=1,
                         local_address_prefix='10.10.0.0/16', prefix_length=24)
        for name, value in overrides.items():
            setattr(args, name, value)
        return args

    def test_bench_refuses_it_under_a_scenario_file(self):
        with pytest.raises(SystemExit) as raised:
            bgperf2.bench(self.bench_args(file='scenario.yaml'))
        assert 'nothing to shorten under -f' in str(raised.value)

    def test_bench_refuses_a_falsy_length_under_a_scenario_file(self):
        '''0 is not the default, and `or` would have read it as 32.'''
        with pytest.raises(SystemExit) as raised:
            bgperf2.bench(self.bench_args(file='scenario.yaml', prefix_length=0))
        assert 'nothing to shorten under -f' in str(raised.value)

    def test_bench_refuses_a_prefix_list(self):
        with pytest.raises(SystemExit) as raised:
            bgperf2.bench(self.bench_args(prefix_list_num=10))
        assert '-e/--prefix-list-num' in str(raised.value)

    def test_config_refuses_a_prefix_list(self):
        with pytest.raises(SystemExit) as raised:
            bgperf2.config(self.bench_args(output='/dev/null', prefix_list_num=10,
                                           as_path_list_num=0, community_list_num=0,
                                           ext_community_list_num=0))
        assert '-e/--prefix-list-num' in str(raised.value)

    def test_bench_refuses_it_under_repeat(self):
        with pytest.raises(SystemExit) as raised:
            bgperf2.bench(self.bench_args(repeat=True))
        assert 'cannot be used with -r/--repeat' in str(raised.value)

    def test_bench_refuses_exabgp(self):
        with pytest.raises(SystemExit) as raised:
            bgperf2.bench(self.bench_args(tester_type='exa'))
        assert "not 'exa'" in str(raised.value)

    def test_bench_refuses_an_unsupported_length(self):
        with pytest.raises(SystemExit) as raised:
            bgperf2.bench(self.bench_args(prefix_length=16))
        assert 'must be one of 24, 32' in str(raised.value)

    def test_bench_checks_capacity_after_the_scope(self):
        '''`-p` under `total` is the whole table, so the per-peer count the
        capacity multiplies is the divided one.'''
        per_peer = pl.capacity(24) // 10 + 1
        with pytest.raises(SystemExit) as raised:
            bgperf2.bench(self.bench_args(prefix_num=per_peer * 10,
                                          prefix_scope='total'))
        assert 'can supply' in str(raised.value)

    def test_config_refuses_an_unsupported_length(self):
        with pytest.raises(SystemExit) as raised:
            bgperf2.config(self.bench_args(output='/dev/null', prefix_length=16))
        assert 'must be one of 24, 32' in str(raised.value)

    def test_config_refuses_exabgp(self):
        with pytest.raises(SystemExit) as raised:
            bgperf2.config(self.bench_args(output='/dev/null', tester_type='exa'))
        assert "not 'exa'" in str(raised.value)

    def test_the_parser_defaults_to_the_historical_length(self):
        parser = bgperf2.create_args_parser(main=False)
        for command in ('bench', 'config'):
            args = parser.parse_args([command])
            assert args.prefix_length == 32
        assert parser.parse_args(['bench', '--prefix-length', '24']).prefix_length == 24

    def test_a_config_scenario_at_24_renders_on_its_own(self, tmp_path):
        '''`config -o` output is what `bench -f` is later handed, so its
        preamble must render outside `gen_conf()`.'''
        out = tmp_path / 'scenario.yaml'
        args = bgperf2.create_args_parser(main=False).parse_args(
            ['config', '-o', str(out), '-n', '2', '-p', '2', '--prefix-length', '24'])
        bgperf2.config(args)
        conf = yaml.safe_load(Template(out.read_text()).render())
        assert offered(conf)[0] == ['1.0.0.0/24', '1.0.1.0/24']


class TestTheBatch:
    def test_a_test_may_declare_it(self):
        bgperf2.check_batch_test(a_test(prefix_length=24))

    def test_it_is_a_test_key(self):
        with pytest.raises(SystemExit) as raised:
            bgperf2.check_batch_test(
                a_test(targets=[{'name': 'bird', 'prefix_length': 24}]))
        assert 'prefix_length' in str(raised.value)

    def test_a_bad_value_is_refused_before_the_first_cell(self):
        with pytest.raises(SystemExit) as raised:
            bgperf2.check_batch_test(a_test(prefix_length='24'))
        assert 'must be one of 24, 32' in str(raised.value)

    def test_an_exabgp_target_refuses_the_test(self):
        with pytest.raises(SystemExit) as raised:
            bgperf2.check_batch_test(a_test(
                prefix_length=24,
                targets=[{'name': 'bird'}, {'name': 'bird', 'label': 'x',
                                            'tester_type': 'exa'}]))
        assert "not 'exa'" in str(raised.value)

    def test_a_scenario_target_has_nothing_to_shorten(self):
        with pytest.raises(SystemExit) as raised:
            bgperf2.check_batch_test(a_test(
                prefix_length=24, targets=[{'name': 'bird', 'file': 's.yaml'}]))
        assert 'nothing to shorten' in str(raised.value)

    def test_a_repeat_target_is_refused(self):
        with pytest.raises(SystemExit) as raised:
            bgperf2.check_batch_test(a_test(
                prefix_length=24, targets=[{'name': 'bird', 'repeat': True}]))
        assert 'cannot be used with repeat' in str(raised.value)

    def test_every_combination_on_the_axes_is_checked_for_capacity(self):
        ok = pl.capacity(24) // 10
        bgperf2.check_batch_test(a_test(prefix_length=24, neighbors=[1, 10],
                                        prefixes=[ok]))
        with pytest.raises(SystemExit) as raised:
            bgperf2.check_batch_test(a_test(prefix_length=24, neighbors=[1, 11],
                                            prefixes=[ok]))
        assert 'can supply' in str(raised.value)

    def test_a_prefix_list_target_is_refused(self):
        with pytest.raises(SystemExit) as raised:
            bgperf2.check_batch_test(a_test(
                prefix_length=24,
                targets=[{'name': 'bird', 'prefix_list_num': 10}]))
        assert '-e/--prefix-list-num' in str(raised.value)

    @pytest.mark.parametrize('order', [0, 1])
    def test_a_repeat_target_in_another_test_is_refused(self, order):
        '''One test at a time passed both; either may run first.'''
        tests = [a_test(name='short', prefix_length=24),
                 a_test(name='again', targets=[{'name': 'bird', 'repeat': True}])]
        if order:
            tests.reverse()
        with pytest.raises(SystemExit) as raised:
            bgperf2.check_batch_prefix_length_and_repeat(tests)
        assert 'short sets prefix_length and again has a repeat' in str(raised.value)

    def test_repeat_beside_the_default_length_is_untouched(self):
        bgperf2.check_batch_prefix_length_and_repeat([
            a_test(name='plain', prefix_length=32),
            a_test(name='again', targets=[{'name': 'bird', 'repeat': True}])])

    def test_the_capacity_check_reads_the_subnet_the_cell_runs_on(self):
        for target in ({'name': 'bird'},
                       {'name': 'bird', 'local_address_prefix': '1.0.0.0/28'}):
            [cell] = bgperf2.expand_batch_cells(a_test(prefix_length=24), [target])
            cell['target'] = target
            assert bgperf2.batch_local_address_prefix(target) == \
                bgperf2.batch_cell_args(Namespace(), cell).local_address_prefix

    def test_native_controlled_cells_refuse_it(self):
        '''Their post-run inspection expects the /32 walk.'''
        import native_mrt
        args = Namespace(file=None, repeat=False, tester_type='bird',
                         monitor='sink', prefix_length=24, image=None,
                         generator_image=None, observer_image=None)
        with pytest.raises(ValueError) as raised:
            native_mrt.synthetic_spec(args)
        assert 'plain transit' in str(raised.value)
        args.prefix_length = 32
        with pytest.raises(ValueError) as raised:
            native_mrt.synthetic_spec(args)
        assert 'immutable image' in str(raised.value)

    def test_the_cell_carries_it_and_the_args_get_it(self):
        [cell] = bgperf2.expand_batch_cells(a_test(prefix_length=24),
                                            [{'name': 'bird'}])
        assert cell['prefix_length'] == 24
        assert bgperf2.batch_cell_args(Namespace(), cell).prefix_length == 24

    def test_a_default_cell_id_is_the_shape_it_always_had(self):
        [plain] = bgperf2.expand_batch_cells(a_test(), [{'name': 'bird'}])
        [explicit] = bgperf2.expand_batch_cells(a_test(prefix_length=32),
                                                [{'name': 'bird'}])
        old = dict(plain)
        del old['prefix_length']
        assert 'prefix_length' not in json.dumps(bgperf2.batch_cell_id('t', plain))
        assert bgperf2.batch_cell_id('t', plain) == bgperf2.batch_cell_id('t', old) \
            == bgperf2.batch_cell_id('t', explicit)

    def test_the_length_is_part_of_the_identity(self):
        [plain] = bgperf2.expand_batch_cells(a_test(), [{'name': 'bird'}])
        [short] = bgperf2.expand_batch_cells(a_test(prefix_length=24),
                                             [{'name': 'bird'}])
        assert bgperf2.batch_cell_id('t', plain) != bgperf2.batch_cell_id('t', short)

    def test_the_description_names_it_only_when_set(self):
        [plain] = bgperf2.expand_batch_cells(a_test(), [{'name': 'bird'}])
        [short] = bgperf2.expand_batch_cells(a_test(prefix_length=24),
                                             [{'name': 'bird'}])
        assert 'prefix length' not in bgperf2.batch_cell_description(plain)
        assert 'prefix length=/24' in bgperf2.batch_cell_description(short)

    def test_recipes_refuse_it(self):
        '''Recipe prefix identity assumes contiguous /32 host routes.'''
        source = yaml.safe_dump({'tests': [a_test(prefix_length=24)]})
        with pytest.raises(recipes.ContractError) as raised:
            recipes._source_tests(source)
        assert 'prefix_length' in str(raised.value)
