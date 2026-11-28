'''Per-block policy attributes on the BIRD generator (policy phase 1, step 3).

No daemon is involved: these check the scenario `gen_conf()` renders and the
native BIRD text the generator writes from it. Whether BIRD carries the
attributes onto the wire is the live check's job.
'''
import ipaddress
import json
from argparse import Namespace

import pytest
import yaml
from mako.template import Template

import bgperf2
import import_policy as ip
import tester as tester_mod


PEERING = '10.10.0.0/16'


def scenario_args(**overrides):
    args = Namespace(
        neighbor_num=3, prefix_num=10, filter_type='in',
        as_path_list_num=0, prefix_list_num=0, community_list_num=0,
        ext_community_list_num=0, single_table=False,
        target_config_file=None, local_address_prefix=PEERING,
        target_local_address=None, target_router_id=None,
        monitor_local_address=None, monitor_router_id=None,
        filter_test=None, license_file=None, threads=None,
        tester_type='bird', mrt_file=None, prefix_scope='per-peer',
        path_diversity=1, prefix_length=32)
    for name, value in overrides.items():
        setattr(args, name, value)
    return args


def rendered(**overrides):
    return yaml.safe_load(Template(bgperf2.gen_conf(
        scenario_args(**overrides))).render())


def neighbors(**overrides):
    return list(rendered(**overrides)['testers'][0]['neighbors'].values())


def write_peer(tmp_path, neighbor):
    t = tester_mod.BIRDTester.__new__(tester_mod.BIRDTester)
    t.host_dir = str(tmp_path)
    t.guest_dir = '/root/config'
    t.dev = 'eth1'
    t.conf = {'neighbors': {neighbor['router-id']: neighbor}}
    t.configure_neighbors({'local-address': '10.10.255.254', 'as': 1000})
    return (tmp_path / '{0}.conf'.format(neighbor['router-id'])).read_text()


def peer(paths, blocks=None, **extra):
    neighbor = {'as': 1003, 'router-id': '10.10.0.3',
                'local-address': '10.10.0.3', 'paths': list(paths)}
    if blocks is not None:
        neighbor['policy-blocks'] = blocks
    neighbor.update(extra)
    return neighbor


class TestTheScenario:
    def test_without_attributes_nothing_is_added(self):
        assert bgperf2.gen_conf(scenario_args()) == bgperf2.gen_conf(
            scenario_args(tester_attributes=False))
        for n in neighbors():
            assert 'policy-blocks' not in n

    @pytest.mark.parametrize('peers', [3, 12])
    @pytest.mark.parametrize('length', [32, 24])
    def test_each_neighbour_carries_the_blocks_of_the_slice_it_announces(
            self, peers, length):
        '''Twelve peers put AS order and slice order apart, so a neighbour
        dealt its blocks by AS would carry another slice's attributes.'''
        rendered_neighbors = neighbors(neighbor_num=peers, prefix_num=10,
                                       prefix_length=length,
                                       tester_attributes=True)
        plain = neighbors(neighbor_num=peers, prefix_num=10,
                          prefix_length=length)
        model = ip.policy_blocks(peers, 10)
        for slice_, (n, before) in enumerate(zip(rendered_neighbors, plain)):
            # The paths are the ones a run without attributes announces.
            assert n['paths'] == before['paths']
            mine = [b for b in model if b.peer == slice_]
            assert n['policy-blocks'] == [
                {'count': b.count, 'as-path': list(b.as_path),
                 'communities': [list(c) for c in b.communities]}
                for b in mine]

    def test_the_slice_order_is_not_the_as_order(self):
        rendered_neighbors = neighbors(neighbor_num=12, prefix_num=4,
                                       tester_attributes=True)
        first_block = [n['policy-blocks'][0]['as-path'][0]
                       for n in rendered_neighbors]
        assert first_block == [ip.BLOCK_PATH_ASN_BASE + k * ip.BLOCKS_PER_PEER
                               for k in range(12)]
        assert [n['as'] for n in rendered_neighbors] != sorted(
            n['as'] for n in rendered_neighbors)

    def test_blocks_cover_each_peers_whole_list(self):
        for n in neighbors(neighbor_num=5, prefix_num=7,
                           tester_attributes=True):
            assert sum(b['count'] for b in n['policy-blocks']) == len(n['paths'])

    @pytest.mark.parametrize('overrides', [
        {'tester_type': 'exa'},
        {'path_diversity': 3},
        {'churn_prefixes': 2},
    ])
    def test_shapes_that_cannot_carry_blocks_are_refused(self, overrides):
        with pytest.raises(ValueError):
            bgperf2.gen_conf(scenario_args(tester_attributes=True,
                                           **overrides))

    def test_scenario_blocks_are_dealt_in_router_id_text_order(self):
        blocks = ip.scenario_policy_blocks(['10.10.0.9', '10.10.0.10'], 4)
        assert list(blocks) == ['10.10.0.10', '10.10.0.9']
        assert blocks['10.10.0.10'][0]['as-path'][0] == ip.BLOCK_PATH_ASN_BASE
        assert blocks['10.10.0.9'][0]['as-path'][0] == \
            ip.BLOCK_PATH_ASN_BASE + ip.BLOCKS_PER_PEER


PATHS = ['1.0.0.{0}/32'.format(i) for i in range(1, 8)]


class TestTheGeneratorConfig:
    def test_without_blocks_the_one_static_protocol_is_written(self, tmp_path):
        config = write_peer(tmp_path, peer(PATHS))
        assert config.count('protocol static') == 1
        assert tester_mod.POLICY_BLOCK_PROTOCOL not in config

    def test_exact_text_of_one_block(self, tmp_path):
        blocks = [{'count': 2, 'as-path': [4210000000, 4200000001],
                   'communities': [[64513, 0], [64512, 1]]}]
        config = write_peer(tmp_path, peer(PATHS[:2], blocks))
        assert config.endswith('''protocol static policy_block0 { ipv4 { import filter {
        bgp_path.prepend(4200000001);
        bgp_path.prepend(4210000000);
        bgp_community.add((64513, 0));
        bgp_community.add((64512, 1));
        accept;
    }; };
      route 1.0.0.1/32 via 10.10.0.3;
      route 1.0.0.2/32 via 10.10.0.3;
}''')
        assert 'protocol static { ipv4;' not in config

    def test_every_route_lands_in_its_blocks_protocol_once(self, tmp_path):
        blocks = ip.scenario_policy_blocks(['10.10.0.3'], 7)['10.10.0.3']
        config = write_peer(tmp_path, peer(PATHS, blocks))
        protocols = config.split('protocol static ')[1:]
        assert len(protocols) == ip.BLOCKS_PER_PEER
        start = 0
        for position, (text, block) in enumerate(zip(protocols, blocks)):
            assert text.startswith('{0}{1} '.format(
                tester_mod.POLICY_BLOCK_PROTOCOL, position))
            routes = [line.split()[1] for line in text.splitlines()
                      if line.strip().startswith('route ')]
            assert routes == PATHS[start:start + block['count']]
            start += block['count']
            # Innermost first, so the path on the wire is the block's own
            # order after the peer's AS.
            prepends = [int(line.strip()[len('bgp_path.prepend('):-2])
                        for line in text.splitlines()
                        if 'bgp_path.prepend' in line]
            assert prepends == list(reversed(block['as-path']))
            # Every route is accepted, so the offered table is whole.
            assert 'reject' not in text
        assert start == len(PATHS)

    def test_blocks_that_do_not_cover_the_list_are_refused(self, tmp_path):
        blocks = [{'count': 3, 'as-path': [1], 'communities': []}]
        with pytest.raises(ValueError, match='cover 3'):
            write_peer(tmp_path, peer(PATHS, blocks))

    def test_blocks_and_a_churn_block_are_refused_together(self, tmp_path):
        blocks = ip.scenario_policy_blocks(['10.10.0.3'], 7)['10.10.0.3']
        with pytest.raises(ValueError, match='churn'):
            write_peer(tmp_path, peer(PATHS, blocks, **{'churn-prefixes': 1}))

    def test_a_rendered_scenario_writes_a_whole_table_per_peer(self, tmp_path):
        for n in neighbors(neighbor_num=3, prefix_num=10, prefix_length=24,
                           tester_attributes=True):
            config = write_peer(tmp_path, n)
            routes = [line.split()[1] for line in config.splitlines()
                      if line.strip().startswith('route ')]
            assert routes == n['paths']
            assert all(ipaddress.IPv4Network(r).prefixlen == 24
                       for r in routes)


class TestResolving:
    @pytest.mark.parametrize('enabled', [None, False])
    def test_off_is_off_whatever_else_is_set(self, enabled):
        assert ip.resolve_tester_attributes(
            enabled, 'exa', 5, 10, 'transit', 2, 1, 1) is False

    def test_on_is_on(self):
        assert ip.resolve_tester_attributes(True, 'bird', 1, 0, None, 0,
                                            10, 100) is True
        assert ip.resolve_tester_attributes(True, None, None, None, 'None',
                                            None) is True

    @pytest.mark.parametrize('value', ['true', 1, 'yes'])
    def test_only_a_boolean_is_a_value(self, value):
        with pytest.raises(ValueError, match='true or false'):
            ip.resolve_tester_attributes(value)

    @pytest.mark.parametrize('kwargs, message', [
        ({'tester_type': 'exa'}, 'BIRD generator'),
        ({'tester_type': 'bgpdump2'}, 'BIRD generator'),
        ({'path_diversity': 2}, '--path-diversity'),
        ({'churn_prefixes': 5}, '--churn-prefixes'),
        ({'filter_test': 'transit'}, '--filter_test transit'),
        ({'policy_reload_blocks': 2}, '--policy-reload-blocks'),
        ({'peers': 2, 'prefixes': 3}, 'at least 4 prefixes'),
        ({'peers': 16385, 'prefixes': 4}, 'at most 16,384 peers'),
    ])
    def test_refusals_name_the_flag_and_the_reason(self, kwargs, message):
        with pytest.raises(ValueError, match='--tester-attributes') as raised:
            ip.resolve_tester_attributes(True, **kwargs)
        assert message in str(raised.value)


def write_generator(directory, protocol='protocol static { ipv4;'):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / '10.10.0.3.conf').write_text(
        'router id 10.10.0.3;\n{0}\n      route 100.0.0.0/32 via 10.10.0.3;\n'
        '}}'.format(protocol))
    return '{0}:/root/config'.format(directory)


TESTER = 'bgperf_bird_tester_bgperf_bird_tester'


class TestNamingAndProvenance:
    def args(self, **overrides):
        args = Namespace(monitor='gobgp', target='bird', label=None,
                         version=None, tester_type='bird', prefix_num=1_000,
                         neighbor_num=10, filter_test=None, file=None,
                         path_diversity=1)
        for name, value in overrides.items():
            setattr(args, name, value)
        return args

    def test_the_default_keeps_its_stem(self):
        assert bgperf2.bench_output_prefix(self.args()) == 'bird_bird_1000_10'
        assert bgperf2.bench_output_prefix(
            self.args(tester_attributes=False)) == 'bird_bird_1000_10'

    def test_the_stem_carries_it(self):
        assert bgperf2.bench_output_prefix(self.args(
            tester_attributes=True, prefix_length=24)) == \
            'bird_bird_1000_10_pl24_ta'

    @pytest.mark.parametrize('writer', ['provenance', 'events'])
    def test_both_run_blocks_record_it(self, tmp_path, writer):
        for args, expected in ((self.args(tester_attributes=True), True),
                               (self.args(), False),
                               (self.args(file='scenario.yaml'), None),
                               (self.args(tester_type='bgpdump2'), None)):
            args.results_dir = str(tmp_path)
            if writer == 'provenance':
                path = bgperf2.write_provenance(args, {}, 'run')
            else:
                bgperf2.write_event_artifact(args, [], 'run', 'converged')
                path = tmp_path / 'run.events.json'
            with open(path) as f:
                assert json.load(f)['run']['tester_attributes'] is expected


class TestTheCommandLineEntryPoints:
    def bench_args(self, **overrides):
        args = Namespace(dir='/tmp', bench_name='x', docker_network_name=None,
                         file=None, target='bird', version=None, image=None,
                         repeat=False, neighbor_num=10, prefix_num=100,
                         prefix_scope='per-peer', tester_type='bird',
                         mrt_file=None, mrt_injector=None, path_diversity=1,
                         local_address_prefix='10.10.0.0/16',
                         tester_attributes=True)
        for name, value in overrides.items():
            setattr(args, name, value)
        return args

    def test_the_parser_defaults_to_off(self):
        parser = bgperf2.create_args_parser(main=False)
        for command in ('bench', 'config'):
            assert parser.parse_args([command]).tester_attributes is False
            assert parser.parse_args(
                [command, '--tester-attributes']).tester_attributes is True

    def test_bench_refuses_it_under_a_scenario_file(self):
        with pytest.raises(SystemExit, match='nothing to attach under -f'):
            bgperf2.bench(self.bench_args(file='scenario.yaml'))

    def test_bench_refuses_it_under_repeat(self):
        with pytest.raises(SystemExit,
                           match='--tester-attributes cannot be used with'):
            bgperf2.bench(self.bench_args(repeat=True))

    @pytest.mark.parametrize('overrides, message', [
        ({'tester_type': 'exa'}, 'BIRD generator'),
        ({'path_diversity': 2}, '--path-diversity'),
        ({'churn_prefixes': 5}, '--churn-prefixes'),
        ({'prefix_num': 3}, 'at least 4 prefixes'),
    ])
    def test_bench_refuses_what_resolving_refuses(self, overrides, message):
        with pytest.raises(SystemExit, match=message):
            bgperf2.bench(self.bench_args(**overrides))

    def test_bench_checks_the_fleet_after_the_scope(self):
        '''40 prefixes under `total` is 4 per peer, enough for four blocks;
        30 is 3.'''
        with pytest.raises(SystemExit, match='at least 4 prefixes'):
            bgperf2.bench(self.bench_args(prefix_num=30, prefix_scope='total'))

    @pytest.mark.parametrize('overrides, message', [
        ({'tester_type': 'exa'}, 'BIRD generator'),
        ({'prefix_num': 3}, 'at least 4 prefixes'),
    ])
    def test_config_refuses_what_resolving_refuses(self, overrides, message):
        with pytest.raises(SystemExit, match=message):
            bgperf2.config(self.bench_args(output='/dev/null', **overrides))

    def test_config_writes_the_blocks(self, tmp_path):
        out = tmp_path / 'scenario.yaml'
        args = bgperf2.create_args_parser(main=False).parse_args(
            ['config', '-o', str(out), '-n', '2', '-p', '8',
             '--tester-attributes'])
        bgperf2.config(args)
        conf = yaml.safe_load(Template(out.read_text()).render())
        for n in conf['testers'][0]['neighbors'].values():
            assert [b['count'] for b in n['policy-blocks']] == [2, 2, 2, 2]


class TestReusedGenerators:
    '''`-r` without the flag would reuse generators a `ta` run started.'''

    def test_the_block_protocol_is_recognised_before_the_first_route(self):
        assert tester_mod.carries_policy_blocks(
            ['router id 1;', 'protocol static policy_block0 { ipv4 {'])
        assert not tester_mod.carries_policy_blocks(
            ['protocol static { ipv4;', '  route 1.0.0.0/24 via x;',
             'protocol static policy_block0 {'])
        assert not tester_mod.carries_policy_blocks([])

    def test_carrying_generators_are_named(self, tmp_path):
        bind = write_generator(
            tmp_path / 'tester',
            'protocol static policy_block0 { ipv4 { import filter {')
        assert bgperf2.reused_generators_with_attributes(
            [TESTER, 'bgperf_monitor'], lambda name: [bind]) == [
                TESTER + ':10.10.0.3.conf']

    def test_plain_generators_are_not(self, tmp_path):
        bind = write_generator(tmp_path / 'tester')
        assert bgperf2.reused_generators_with_attributes(
            [TESTER], lambda name: [bind]) == []

    @pytest.fixture
    def bench_reaches_the_check(self, monkeypatch):
        class Image:
            @staticmethod
            def require_image():
                pass
        mounts = {}

        class Dckr:
            def inspect_container(self, name):
                return {'HostConfig': {'CpusetCpus': '', 'Binds': mounts[name]}}
        monkeypatch.setattr(bgperf2, 'target_image', lambda *a, **k: 'img')
        monkeypatch.setitem(bgperf2.MONITOR_CLASSES, 'sink', Image)
        monkeypatch.setattr(bgperf2, 'dckr', Dckr())
        monkeypatch.setattr(bgperf2, 'get_ctn_names', lambda: list(mounts))

        def torn_down():
            raise AssertionError('reached the teardown')
        monkeypatch.setattr(bgperf2, 'remove_target_containers', torn_down)
        return mounts

    def repeat_args(self, tmp_path):
        return TestTheCommandLineEntryPoints().bench_args(
            dir=str(tmp_path / 'this-run'), repeat=True,
            tester_attributes=False, prefix_length=32, monitor='sink')

    def test_bench_refuses_reusing_them(self, tmp_path, bench_reaches_the_check):
        bench_reaches_the_check[TESTER] = [write_generator(
            tmp_path / 'tester',
            'protocol static policy_block0 { ipv4 { import filter {')]
        with pytest.raises(SystemExit, match='carrying per-block policy'):
            bgperf2.bench(self.repeat_args(tmp_path))

    def test_bench_reuses_plain_ones(self, tmp_path, bench_reaches_the_check):
        bench_reaches_the_check[TESTER] = [write_generator(tmp_path / 'tester')]
        with pytest.raises(AssertionError, match='reached the teardown'):
            bgperf2.bench(self.repeat_args(tmp_path))


def a_test(**overrides):
    test = {'name': 'attrs', 'neighbors': [4], 'prefixes': [100],
            'filter_test': ['None'], 'targets': [{'name': 'bird'}],
            'tester_attributes': True}
    test.update(overrides)
    return test


class TestTheBatch:
    def test_a_test_may_declare_it(self):
        bgperf2.check_batch_test(a_test())

    def test_it_is_a_test_key(self):
        with pytest.raises(SystemExit, match='tester_attributes'):
            bgperf2.check_batch_test(a_test(
                tester_attributes=None,
                targets=[{'name': 'bird', 'tester_attributes': True}]))

    def test_a_bad_value_is_refused_before_the_first_cell(self):
        with pytest.raises(SystemExit, match='true or false'):
            bgperf2.check_batch_test(a_test(tester_attributes='yes'))

    def test_an_exabgp_target_refuses_the_test(self):
        with pytest.raises(SystemExit, match='BIRD generator'):
            bgperf2.check_batch_test(a_test(targets=[
                {'name': 'bird'},
                {'name': 'bird', 'label': 'x', 'tester_type': 'exa'}]))

    def test_a_scenario_target_has_nothing_to_attach(self):
        with pytest.raises(SystemExit, match='nothing to attach'):
            bgperf2.check_batch_test(a_test(
                targets=[{'name': 'bird', 'file': 's.yaml'}]))

    def test_a_repeat_target_is_refused(self):
        with pytest.raises(SystemExit,
                           match='tester_attributes cannot be used with repeat'):
            bgperf2.check_batch_test(a_test(
                targets=[{'name': 'bird', 'repeat': True}]))

    def test_every_fleet_on_the_axes_is_checked(self):
        with pytest.raises(SystemExit, match='at least 4 prefixes'):
            bgperf2.check_batch_test(a_test(prefixes=[100, 3]))

    def test_a_filter_on_the_axis_is_refused(self):
        with pytest.raises(SystemExit, match='--filter_test transit'):
            bgperf2.check_batch_test(a_test(filter_test=['None', 'transit']))

    @pytest.mark.parametrize('order', [0, 1])
    def test_a_repeat_target_in_another_test_is_refused(self, order):
        tests = [a_test(name='attrs'),
                 a_test(name='again', tester_attributes=None,
                        targets=[{'name': 'bird', 'repeat': True}])]
        if order:
            tests.reverse()
        with pytest.raises(SystemExit,
                           match='attrs sets tester_attributes and again has'):
            bgperf2.check_batch_prefix_length_and_repeat(tests)

    def test_the_cell_carries_it_and_the_args_get_it(self):
        [cell] = bgperf2.expand_batch_cells(a_test(), [{'name': 'bird'}])
        assert cell['tester_attributes'] is True
        assert bgperf2.batch_cell_args(Namespace(), cell).tester_attributes

    def test_a_default_cell_is_the_shape_it_always_had(self):
        [plain] = bgperf2.expand_batch_cells(a_test(tester_attributes=None),
                                             [{'name': 'bird'}])
        assert 'tester_attributes' not in plain
        assert 'tester_attributes' not in json.dumps(
            bgperf2.batch_cell_id('t', plain))
        assert bgperf2.batch_cell_args(Namespace(), plain).tester_attributes \
            is False

    def test_it_is_part_of_the_identity_and_the_description(self):
        [plain] = bgperf2.expand_batch_cells(a_test(tester_attributes=None),
                                             [{'name': 'bird'}])
        [attrs] = bgperf2.expand_batch_cells(a_test(), [{'name': 'bird'}])
        assert bgperf2.batch_cell_id('t', plain) != \
            bgperf2.batch_cell_id('t', attrs)
        assert 'tester attributes' not in bgperf2.batch_cell_description(plain)
        assert 'tester attributes' in bgperf2.batch_cell_description(attrs)

    def test_native_controlled_cells_refuse_it(self):
        import native_mrt
        args = Namespace(file=None, repeat=False, tester_type='bird',
                         monitor='sink', tester_attributes=True, image=None,
                         generator_image=None, observer_image=None)
        with pytest.raises(ValueError, match='plain transit'):
            native_mrt.synthetic_spec(args)

    def test_recipes_refuse_it(self):
        import recipes
        source = yaml.safe_dump({'tests': [a_test()]})
        with pytest.raises(recipes.ContractError, match='tester_attributes'):
            recipes._source_tests(source)

    @pytest.mark.parametrize('target', [
        {'name': 'bird', 'repeat': True}, {'name': 'bird', 'file': 's.yaml'}])
    def test_a_bad_value_is_named_before_any_other_rule(self, target):
        with pytest.raises(SystemExit, match='true or false'):
            bgperf2.check_batch_test(a_test(tester_attributes='no',
                                            targets=[target]))

    def test_a_bad_value_is_not_counted_as_set_across_the_batch(self):
        bgperf2.check_batch_prefix_length_and_repeat([
            a_test(name='attrs', tester_attributes='no'),
            a_test(name='again', tester_attributes=None,
                   targets=[{'name': 'bird', 'repeat': True}])])

    def test_a_scenario_filter_target_is_refused(self):
        with pytest.raises(SystemExit, match='-c/--community-list-num'):
            bgperf2.check_batch_test(a_test(targets=[
                {'name': 'bird', 'community_list_num': 10}]))


class TestNoPolicyOnTheTarget:
    @pytest.mark.parametrize('field, flag', bgperf2.SCENARIO_FILTER_FLAGS)
    def test_bench_refuses_each_scenario_filter(self, field, flag):
        with pytest.raises(SystemExit, match=flag):
            bgperf2.bench(TestTheCommandLineEntryPoints().bench_args(
                **{field: 10}))

    def test_config_refuses_them(self):
        with pytest.raises(SystemExit, match='-a/--as-path-list-num'):
            bgperf2.config(TestTheCommandLineEntryPoints().bench_args(
                output='/dev/null', as_path_list_num=5, prefix_list_num=0,
                community_list_num=0, ext_community_list_num=0))


def scenario_with(tester_type='bird', **neighbor):
    n = {'router-id': '10.10.0.3', 'paths': PATHS,
         'policy-blocks': ip.scenario_policy_blocks(['10.10.0.3'], 7)[
             '10.10.0.3']}
    n.update(neighbor)
    return {'testers': [{'type': tester_type,
                         'neighbors': {'10.10.0.3': n}}]}


class TestAScenarioFilesBlocks:
    def test_good_blocks_pass(self):
        bgperf2.check_scenario_policy_blocks(scenario_with())
        bgperf2.check_scenario_policy_blocks({'testers': None})

    @pytest.mark.parametrize('tester_type, neighbor, message', [
        ('exa', {}, "'exa' generator cannot send them"),
        ('bird', {'paths': PATHS[:6]}, 'cover 7'),
        ('bird', {'churn-prefixes': 1}, 'churn'),
        ('bird', {'policy-blocks': [{'as-path': []}]}, 'count'),
    ])
    def test_bad_blocks_are_refused(self, tester_type, neighbor, message):
        with pytest.raises(ValueError, match=message):
            bgperf2.check_scenario_policy_blocks(
                scenario_with(tester_type, **neighbor))

    def test_bench_refuses_them_before_the_teardown(self, tmp_path,
                                                     monkeypatch):
        def torn_down():
            raise AssertionError('reached the teardown')
        monkeypatch.setattr(bgperf2, 'remove_target_containers', torn_down)
        scenario = tmp_path / 's.yaml'
        scenario.write_text(yaml.safe_dump(scenario_with('exa')))
        with pytest.raises(SystemExit, match='cannot send them'):
            bgperf2.bench(TestTheCommandLineEntryPoints().bench_args(
                file=str(scenario), tester_attributes=False))
