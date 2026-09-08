'''Export fan-out: one table feeding several receive-only sessions.

Every run bgperf has made has exactly one session the target exports to -- the
monitor -- so the cost of building, encoding and sending a table has never been
separable from the cost of receiving one. `--receivers N` (batch: `receivers:
N` on a test) adds N sessions the target advertises its whole table to and
which announce nothing back. Decoupled exports are one of the three
responsibilities BIRD 3's worker threads exist to parallelise.

The load-bearing rule is that a receiver is *not* a route source. It is a
top-level `receivers` key rather than an entry in `conf['testers']`, so
`get_test_counts()` never waits on it for a table it will never send, the
monitor's check-point does not move with the receiver count, and the ingress
side of the run is untouched by how many there are.
'''
from argparse import Namespace

import pytest
import yaml
from mako.template import Template

import bgperf2
import base
import monitor


def a_test(**overrides):
    test = {
        'name': 'fanout',
        'neighbors': [10],
        'prefixes': [1_000],
        'filter_test': ['None'],
        'targets': [{'name': 'bird'}],
    }
    test.update(overrides)
    return test


def scenario(**overrides):
    args = Namespace(
        neighbor_num=3, prefix_num=2, filter_type='in',
        as_path_list_num=0, prefix_list_num=0, community_list_num=0,
        ext_community_list_num=0, single_table=False,
        target_config_file=None, local_address_prefix='10.10.0.0/16',
        target_local_address=None, target_router_id=None,
        monitor_local_address=None, monitor_router_id=None,
        filter_test=None, license_file=None, threads=None,
        tester_type='bird', mrt_file=None, prefix_scope='per-peer',
        path_diversity=1, receivers=0)
    for name, value in overrides.items():
        setattr(args, name, value)
    return yaml.safe_load(Template(bgperf2.gen_conf(args)).render())


class TestResolvingTheCount:
    def test_absent_is_no_fan_out(self):
        '''Every existing command line and every existing batch config.'''
        assert bgperf2.resolve_receivers(None) == 0

    def test_zero_is_no_fan_out(self):
        assert bgperf2.resolve_receivers(0) == 0

    def test_a_count_is_returned(self):
        assert bgperf2.resolve_receivers(4) == 4

    @pytest.mark.parametrize('value', [-1, 2.5, '3', True])
    def test_a_value_that_is_not_a_count_is_refused(self, value):
        '''A quoted entry from a batch yaml would otherwise reach `range()` as
        a bare `TypeError`, and `True` is an `int` in Python.'''
        with pytest.raises(ValueError) as raised:
            bgperf2.resolve_receivers(value)
        assert '0 or more' in str(raised.value)

    def test_an_mrt_generator_is_not_refused(self):
        """Unlike `--path-diversity` and `--prefix-scope`, this is a
        target-side session and has nothing to do with the generator: an MRT
        run has the same reason to want export fan-out as a synthetic one.
        """
        conf = scenario(tester_type='bgpdump2', mrt_file='rib.mrt',
                        receivers=2)
        assert len(conf['receivers']) == 2


class TestTheScenarioItProduces:
    def test_no_receivers_key_by_default(self):
        '''The scenario every existing run produces, unchanged.'''
        assert 'receivers' not in scenario()

    def test_each_receiver_is_a_session_like_the_monitor(self):
        """Anything a target's config writer can do with the monitor it can do
        with a receiver: the same three fields, and nothing else.
        """
        conf = scenario(receivers=2)
        assert len(conf['receivers']) == 2
        for r in conf['receivers']:
            assert sorted(r) == ['as', 'local-address', 'router-id']

    def test_receivers_do_not_collide_with_the_peers(self):
        conf = scenario(neighbor_num=3, receivers=2)
        peers = {n['local-address']
                 for n in conf['testers'][0]['neighbors'].values()}
        receivers = {r['local-address'] for r in conf['receivers']}
        assert not peers & receivers
        assert conf['target']['local-address'] not in receivers
        assert conf['monitor']['local-address'] not in receivers

    def test_receiver_as_numbers_are_distinct(self):
        """They continue the peers' own index, so `1000 + i` is distinct by
        construction rather than by a separate range that would only be safe
        until somebody ran enough peers to reach it.
        """
        conf = scenario(neighbor_num=3, receivers=3)
        asns = [n['as'] for n in conf['testers'][0]['neighbors'].values()]
        asns += [r['as'] for r in conf['receivers']]
        asns += [conf['monitor']['as'], conf['target']['as']]
        assert len(set(asns)) == len(asns)

    def test_receivers_announce_nothing(self):
        assert all('paths' not in r and 'count' not in r
                   for r in scenario(receivers=2)['receivers'])

    def test_they_are_not_testers(self):
        """The whole of `not treating the extra receivers as route sources`:
        `get_test_counts()` reads `conf['testers']`, so a receiver in there
        would be waited on for a full table it never sends and the run would
        never converge.
        """
        conf = scenario(neighbor_num=3, receivers=5)
        assert sum(len(t['neighbors']) for t in conf['testers']) == 3

    @pytest.mark.parametrize('count', [0, 1, 5, 20])
    def test_the_ingress_count_does_not_move_with_the_fan_out(self, count):
        '''The acceptance criterion, stated directly.'''
        conf = scenario(neighbor_num=3, prefix_num=2, receivers=count)
        offered = [p for n in conf['testers'][0]['neighbors'].values()
                   for p in n['paths']]
        assert len(offered) == 6
        assert conf['monitor']['check-points'] == [int(6 * 0.99)]

    def test_the_peers_are_untouched_by_the_fan_out(self):
        '''Byte-for-byte: the receivers are appended, they do not renumber.'''
        assert scenario(receivers=4)['testers'] == scenario()['testers']

    def test_it_composes_with_path_diversity(self):
        """Two independent axes: the diversity decides the distinct-prefix
        count the monitor requires, the fan-out decides how many sessions that
        table is exported to.
        """
        conf = scenario(neighbor_num=6, prefix_num=4, path_diversity=3,
                        receivers=2)
        assert conf['monitor']['check-points'] == [int(8 * 0.99)]
        assert len(conf['receivers']) == 2


class TestTheNeighborSeam:
    """Eight target modules built `flatten(testers) + [monitor]` independently.
    A receiver added to seven of them is a target that quietly exports to fewer
    sessions than the run says, with nothing in the row to show for it.
    """

    def target(self, conf):
        t = base.Target.__new__(base.Target)
        t.scenario_global_conf = conf
        return t

    def test_every_session_reaches_the_target_config(self):
        conf = scenario(neighbor_num=3, receivers=2)
        addresses = [n['local-address']
                     for n in self.target(conf).scenario_neighbors()]
        assert len(addresses) == 6
        assert conf['monitor']['local-address'] in addresses
        for r in conf['receivers']:
            assert r['local-address'] in addresses

    def test_a_run_without_receivers_is_the_list_it_always_was(self):
        conf = scenario(neighbor_num=3)
        neighbors = self.target(conf).scenario_neighbors()
        assert len(neighbors) == 4
        assert neighbors == sorted(
            list(conf['testers'][0]['neighbors'].values())
            + [conf['monitor']], key=lambda n: n['as'])

    def test_the_unsorted_callers_keep_their_order(self):
        """`frr.py` and `gobgp.py` never sorted, and ordering in a generated
        config is cosmetic -- changing it would put an unrelated diff in front
        of anyone comparing a config against an older run's.
        """
        conf = scenario(neighbor_num=3, receivers=2)
        neighbors = self.target(conf).scenario_neighbors(sort=False)
        assert neighbors[-3] is conf['monitor']
        assert neighbors[-2:] == conf['receivers']

    def test_no_module_still_builds_the_list_by_hand(self):
        '''The seam is only a seam while every caller goes through it.'''
        import pathlib
        repo = pathlib.Path(base.REPO_ROOT)
        offenders = [p.name for p in repo.glob('*.py')
                     if p.name != 'monitor.py'
                     and "scenario_global_conf['monitor']" in p.read_text()]
        assert offenders == []


class TestTheReceiverContainer:
    def test_it_is_named_like_a_tester_and_removed_like_one(self):
        """`batch()` runs cell after cell in one process, so a receiver left
        behind fails the next cell on a duplicate container name.
        """
        assert monitor.Receiver.CONTAINER_NAME_PREFIX == 'bgperf_receiver'
        import inspect
        source = inspect.getsource(bgperf2.remove_old_containers)
        assert 'Receiver.CONTAINER_NAME_PREFIX' in source

    def test_it_is_not_an_instrument(self):
        """A receiver polled as though it were the monitor would publish a
        second, unlabelled `recved` series into the same queue.
        """
        r = monitor.Receiver.__new__(monitor.Receiver)
        with pytest.raises(NotImplementedError) as raised:
            r.stats(None)
        assert 'not an instrument' in str(raised.value)

    def test_it_shares_the_monitor_config_writer(self):
        '''Subclassing rather than copying: two gobgpd config writers would
        drift, and the receiver's would drift silently.'''
        assert monitor.Receiver.run is monitor.Monitor.run


class TestWhatARepeatInherits:
    """`-r/--repeat` reuses the previous run's containers, but everything else
    still acts on the number asked for -- the target's config, the artifact
    names and both `run` blocks -- so the two disagreeing is a published claim
    about a topology that did not run, silently, in both directions.
    """

    def test_a_matching_fan_out_is_accepted(self):
        bgperf2.check_repeat_receivers(3, 3)
        bgperf2.check_repeat_receivers(0, 0)

    def test_asking_for_more_than_are_running_is_refused(self):
        '''The row and the manifest would claim a fan-out the run never had.'''
        with pytest.raises(ValueError) as raised:
            bgperf2.check_repeat_receivers(3, 0)
        assert 'asks for 3' in str(raised.value)

    def test_asking_for_fewer_than_are_running_is_refused(self):
        """Worse on a dynamic-neighbour target: the surplus containers are
        still up and `neighbor range 10.0.0.0/8` accepts every one of them, so
        the target really does export to sessions the manifest omits.
        """
        with pytest.raises(ValueError) as raised:
            bgperf2.check_repeat_receivers(1, 5)
        assert 'left 5 receivers running' in str(raised.value)

    def test_the_running_count_comes_from_the_container_names(self):
        names = ['bgperf_monitor', 'bgperf_receiver0', 'bgperf_receiver1',
                 'bgperf_bird_tester_x', 'bgperf_bird_target']
        assert bgperf2.existing_receiver_count(names) == 2
        assert bgperf2.existing_receiver_count([]) == 0


class TestWhatTheFanOutCostsTheHost:
    """Each receiver is a full GoBGP holding its own copy of the table on the
    same host, and `min free mem (GB)` is host-wide -- so `findings.py` can
    turn memory the run consumed by design into the `low_free_memory`
    confounder and withhold `limiting_component` entirely.
    """

    def test_nothing_is_said_when_there_is_no_fan_out(self):
        assert bgperf2.describe_export_fanout_cost(0) is None
        assert bgperf2.describe_export_fanout_cost(None) is None

    def test_it_names_the_column_and_the_confounder(self):
        said = bgperf2.describe_export_fanout_cost(4)
        assert 'min free mem' in said
        assert 'low_free_memory' in said

    def test_it_does_not_estimate(self):
        """For the reason `LOG_SPACE_FLOOR_GB` is not an estimate: what a GoBGP
        holds per route depends on the paths, and an invented number would be
        quoted back as though it had been measured.
        """
        said = bgperf2.describe_export_fanout_cost(4)
        assert 'GB' not in said and 'MB' not in said


class TestAScenarioFilesOwnReceivers:
    """`resolve_receivers()` guards every path that builds a scenario; this is
    the one path that is handed one.
    """

    def test_no_receivers_is_an_empty_list(self):
        assert bgperf2.scenario_receivers({}) == []

    def test_a_well_formed_list_passes(self):
        conf = {'receivers': [{'as': 1007, 'router-id': '10.10.0.7',
                               'local-address': '10.10.0.7'}]}
        assert bgperf2.scenario_receivers(conf) == conf['receivers']

    def test_a_count_is_refused_rather_than_iterated(self):
        """An operator mirroring the CLI flag as `receivers: 3` otherwise
        reached `enumerate()` as a bare `TypeError`.
        """
        with pytest.raises(ValueError) as raised:
            bgperf2.scenario_receivers({'receivers': 3})
        assert 'not a count' in str(raised.value)

    def test_an_entry_that_is_not_a_session_is_refused(self):
        with pytest.raises(ValueError) as raised:
            bgperf2.scenario_receivers({'receivers': ['10.10.0.7']})
        assert 'must be a session' in str(raised.value)

    def test_a_session_missing_its_fields_is_refused(self):
        '''Otherwise the failure is a `KeyError` inside a config writer.'''
        with pytest.raises(ValueError) as raised:
            bgperf2.scenario_receivers({'receivers': [{'as': 1007}]})
        assert 'router-id' in str(raised.value)
        assert 'local-address' in str(raised.value)


class TestNamingAndProvenance:
    def args(self, **overrides):
        args = Namespace(target='bird', label=None, version=None,
                         tester_type='bird', prefix_num=1_000,
                         neighbor_num=10, filter_test=None, file=None,
                         path_diversity=1, receivers=0)
        for name, value in overrides.items():
            setattr(args, name, value)
        return args

    def test_no_fan_out_keeps_the_stem_it_has_always_had(self):
        assert bgperf2.bench_output_prefix(self.args()) == 'bird_bird_1000_10'

    def test_the_stem_carries_the_fan_out(self):
        assert bgperf2.bench_output_prefix(self.args(receivers=4)) == \
            'bird_bird_1000_10_rx4'

    def test_a_missing_field_is_the_default(self):
        args = self.args()
        del args.receivers
        assert bgperf2.bench_output_prefix(args) == 'bird_bird_1000_10'

    def test_both_run_blocks_record_it(self, tmp_path):
        """`<prefix>.events.json` is what `findings.py` reasons over and
        `<prefix>.versions.json` is the build manifest; a dimension in the
        filename alone is one a summary has to parse a stem to recover.
        """
        import json
        args = self.args(receivers=4, results_dir=str(tmp_path))
        bgperf2.write_provenance(args, {}, 'run')
        bgperf2.write_event_artifact(args, [], 'run', 'converged')
        with open(tmp_path / 'run.versions.json') as f:
            assert json.load(f)['run']['receivers'] == 4
        with open(tmp_path / 'run.events.json') as f:
            assert json.load(f)['run']['receivers'] == 4

    def test_a_scenario_run_records_no_fan_out(self, tmp_path):
        '''The file states the sessions the target has; provenance never
        guesses about a workload bgperf2 did not build.'''
        import json
        args = self.args(file='scenario.yaml', results_dir=str(tmp_path))
        bgperf2.write_provenance(args, {}, 'run')
        with open(tmp_path / 'run.versions.json') as f:
            assert json.load(f)['run']['receivers'] is None


class TestTheBatchPath:
    def test_a_test_may_declare_it(self):
        bgperf2.check_batch_test(a_test(receivers=4))

    def test_a_value_that_is_not_a_count_is_refused(self):
        with pytest.raises(SystemExit) as raised:
            bgperf2.check_batch_test(a_test(receivers='4'))
        assert '0 or more' in str(raised.value)

    def test_a_scenario_target_has_nothing_to_add(self):
        test = a_test(receivers=4,
                      targets=[{'name': 'bird', 'file': 'scenario.yaml'}])
        with pytest.raises(SystemExit) as raised:
            bgperf2.check_batch_test(test)
        assert 'nothing to add' in str(raised.value)

    def test_a_scenario_target_without_it_is_untouched(self):
        bgperf2.check_batch_test(
            a_test(targets=[{'name': 'bird', 'file': 'scenario.yaml'}]))

    def test_it_is_a_test_key_and_not_a_target_key(self):
        with pytest.raises(SystemExit) as raised:
            bgperf2.check_batch_test(
                a_test(targets=[{'name': 'bird', 'receivers': 4}]))
        assert 'receivers' in str(raised.value)
        assert 'Move it up one level' in str(raised.value)

    def test_the_cell_carries_it(self):
        cells = bgperf2.expand_batch_cells(a_test(receivers=4),
                                          [{'name': 'bird'}])
        assert all(c['receivers'] == 4 for c in cells)

    def test_a_test_without_it_carries_the_default(self):
        cells = bgperf2.expand_batch_cells(a_test(), [{'name': 'bird'}])
        assert all(c['receivers'] == 0 for c in cells)


class TestTheCellIdentity:
    def cell(self, **overrides):
        cell = {'repetition': None, 'ordinal': 0, 'neighbors': 10,
                'prefixes': 1_000, 'filter': 'None', 'path_diversity': 1,
                'receivers': 0, 'target': {'name': 'bird'}}
        cell.update(overrides)
        return cell

    def test_a_run_without_fan_out_has_the_id_it_always_had(self):
        assert 'receivers' not in bgperf2.batch_cell_id('t', self.cell())

    def test_a_missing_key_reads_as_the_default(self):
        cell = self.cell()
        del cell['receivers']
        assert bgperf2.batch_cell_id('t', cell) == \
            bgperf2.batch_cell_id('t', self.cell())

    def test_the_fan_out_is_part_of_the_identity(self):
        assert bgperf2.batch_cell_id('t', self.cell()) != \
            bgperf2.batch_cell_id('t', self.cell(receivers=4))

    def test_the_description_names_it_only_when_it_is_set(self):
        assert 'receivers' not in bgperf2.batch_cell_description(self.cell())
        assert 'receivers=4' in \
            bgperf2.batch_cell_description(self.cell(receivers=4))


class TestTheCommandLineEntryPoints:
    def bench_args(self, **overrides):
        args = Namespace(dir='/tmp', bench_name='x', docker_network_name=None,
                         file=None, target='bird', version=None, image=None,
                         repeat=True, neighbor_num=10, prefix_num=100,
                         prefix_scope='per-peer', tester_type='bird',
                         mrt_file=None, mrt_injector=None, path_diversity=1,
                         receivers=-1)
        for name, value in overrides.items():
            setattr(args, name, value)
        return args

    def test_bench_refuses_a_bad_count(self):
        with pytest.raises(SystemExit) as raised:
            bgperf2.bench(self.bench_args())
        assert '0 or more' in str(raised.value)

    def test_bench_refuses_it_under_a_scenario_file(self):
        with pytest.raises(SystemExit) as raised:
            bgperf2.bench(self.bench_args(file='scenario.yaml', receivers=4))
        assert 'nothing to add under -f' in str(raised.value)

    def test_a_scenario_file_without_it_is_untouched(self):
        '''It must not refuse every `-f` run.'''
        with pytest.raises(SystemExit) as raised:
            bgperf2.bench(self.bench_args(file='scenario.yaml', receivers=0,
                                          prefix_scope='total'))
        assert 'nothing to divide under -f' in str(raised.value)

    def test_config_refuses_a_bad_count(self):
        with pytest.raises(SystemExit) as raised:
            bgperf2.config(self.bench_args(output='/dev/null'))
        assert '0 or more' in str(raised.value)
