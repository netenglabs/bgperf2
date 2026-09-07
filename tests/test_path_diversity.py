'''Path diversity: several peers announcing competing paths for one prefix.

`gen_conf()` has only ever generated disjoint prefixes -- every peer takes its
own block off a shared iterator -- so every route the target learns is the only
path it has for that prefix and best-path selection never runs against a rival.
That is not what a router does with a full table, where the same prefix arrives
from several neighbours and the work is choosing between them, holding the
losers, and re-running the choice when one is withdrawn.

`--path-diversity D` (batch: `path_diversity: D` on a test) deals the peers
into groups of D and gives each group one shared block, so the fleet offers
`n * p` paths for `(n / D) * p` distinct prefixes. The two numbers are
different, and which one the monitor counts is the whole of the accounting: it
sees what the target *re-advertises*, which is one best path per prefix.
'''
from argparse import Namespace

import pytest
import yaml
from mako.template import Template

import bgperf2


def a_test(**overrides):
    test = {
        'name': 'diverse',
        'neighbors': [10],
        'prefixes': [1_000],
        'filter_test': ['None'],
        'targets': [{'name': 'bird'}],
    }
    test.update(overrides)
    return test


class TestResolvingTheDiversity:
    def test_absent_is_the_disjoint_workload(self):
        '''Every existing command line and every existing batch config.'''
        assert bgperf2.resolve_path_diversity(None, 50) == 1

    def test_one_is_the_disjoint_workload(self):
        assert bgperf2.resolve_path_diversity(1, 50) == 1

    def test_a_diversity_that_divides_is_returned(self):
        assert bgperf2.resolve_path_diversity(5, 50) == 5

    def test_every_peer_on_one_block_is_allowed(self):
        '''The extreme of the axis, not a mistake: one shared block announced
        by the whole fleet is the maximum competition a run can present.'''
        assert bgperf2.resolve_path_diversity(50, 50) == 50

    @pytest.mark.parametrize('value', [0, -1, 2.5, '3', True])
    def test_a_diversity_that_is_not_a_count_is_refused(self, value):
        '''`True` is an `int` in Python and is not a group size, and a quoted
        entry from a batch yaml would otherwise reach the arithmetic as a bare
        `TypeError`.'''
        with pytest.raises(ValueError) as raised:
            bgperf2.resolve_path_diversity(value, 50)
        assert '1 or more' in str(raised.value)

    def test_more_diversity_than_peers_is_refused(self):
        with pytest.raises(ValueError) as raised:
            bgperf2.resolve_path_diversity(51, 50)
        assert 'there are 50' in str(raised.value)

    def test_an_inexact_division_is_refused(self):
        """The remainder group would announce a block with fewer competing
        paths than the rest, so the number is true of none of the table and the
        monitor's check-point stops being `groups * p`.
        """
        with pytest.raises(ValueError) as raised:
            bgperf2.resolve_path_diversity(4, 50)
        assert 'does not divide 50 peers' in str(raised.value)

    def test_the_refusal_names_group_sizes_that_work(self):
        '''A message that only says the division failed leaves the operator
        factorising a peer count by hand.'''
        with pytest.raises(ValueError) as raised:
            bgperf2.resolve_path_diversity(4, 50)
        assert 'use 2 or 5 instead' in str(raised.value)

    def test_both_ends_of_the_divisor_search_are_usable(self):
        '''Unlike the peer-count suggestions for `--prefix-scope total`, 1 and
        the peer count itself are answers rather than degenerate advice.'''
        assert bgperf2._diversity_divisors_near(9, 2) == [1, 3]
        assert bgperf2._diversity_divisors_near(9, 5) == [3, 9]

    @pytest.mark.parametrize('tester', bgperf2.MRT_TESTER_TYPES)
    def test_an_mrt_generator_is_refused(self, tester):
        """`gen_conf()` synthesises no paths for these -- the diversity of an
        MRT run is whatever the file holds -- and the monitor check-point comes
        straight from `-p`. Accepting it would print a diversity into the
        manifest of a run that had none.
        """
        with pytest.raises(ValueError) as raised:
            bgperf2.resolve_path_diversity(5, 50, tester)
        assert 'does not apply' in str(raised.value)

    @pytest.mark.parametrize('tester', bgperf2.MRT_TESTER_TYPES)
    def test_an_mrt_generator_at_the_default_is_untouched(self, tester):
        '''Refusing the default would refuse every MRT run that predates the
        flag, which is all of them.'''
        assert bgperf2.resolve_path_diversity(None, 50, tester) == 1
        assert bgperf2.resolve_path_diversity(1, 50, tester) == 1

    def test_the_total_prefix_scope_is_refused(self):
        """`the whole table` has two readings that differ by exactly the
        diversity -- the paths offered and the distinct prefixes held -- and
        neither is written down. The reading would reach the `prefixes per
        peer` column, the cell identity and every artifact name.
        """
        with pytest.raises(ValueError) as raised:
            bgperf2.resolve_path_diversity(5, 50, 'bird', 'total')
        assert 'not defined together' in str(raised.value)

    def test_the_per_peer_scope_is_untouched(self):
        assert bgperf2.resolve_path_diversity(5, 50, 'bird', 'per-peer') == 5
        assert bgperf2.resolve_path_diversity(5, 50, 'bird', None) == 5

    def test_an_unrecognised_scope_is_left_to_the_scope_to_diagnose(self):
        """A typo'd `prefix_scope: totl` beside a diversity was reported as
        `--prefix-scope totl is not defined together with --path-diversity`,
        naming the misspelling as if it were a real scope -- so the operator
        removes the diversity, and only then gets the `unknown prefix scope`
        that was the actual fault. A refusal must name the fault, not the
        nearest rule it trips.
        """
        assert bgperf2.resolve_path_diversity(5, 50, 'bird', 'totl') == 5
        with pytest.raises(ValueError) as raised:
            bgperf2.resolve_prefix_scope('totl', 50, 100)
        assert 'unknown prefix scope' in str(raised.value)


class TestTheBlockArithmetic:
    def test_the_default_gives_every_peer_its_own_block(self):
        assert bgperf2.path_diversity_groups(50, 1) == 50

    def test_a_group_of_five_gives_ten_blocks(self):
        assert bgperf2.path_diversity_groups(50, 5) == 10

    @pytest.mark.parametrize('neighbors,diversity', [(50, 4), (50, 0), (50, -1)])
    def test_it_refuses_to_do_arithmetic_it_cannot_do_exactly(self, neighbors,
                                                              diversity):
        """Every operator path reaches `resolve_path_diversity()` first, so a
        raise here is a rule that was applied nowhere -- and the alternative is
        a fleet whose last group announces a block with fewer competing paths
        than the rest, silently.
        """
        with pytest.raises(ValueError):
            bgperf2.path_diversity_groups(neighbors, diversity)


class TestTheScenarioItProduces:
    def scenario(self, **overrides):
        args = Namespace(
            neighbor_num=6, prefix_num=4, filter_type='in',
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
        return yaml.safe_load(Template(bgperf2.gen_conf(args)).render())

    def neighbors(self, conf):
        return [n for _, n in sorted(conf['testers'][0]['neighbors'].items())]

    def test_the_default_still_generates_disjoint_prefixes(self):
        '''What bgperf has always generated, and what every published result
        was measured against.'''
        neighbors = self.neighbors(self.scenario())
        offered = [p for n in neighbors for p in n['paths']]
        assert len(offered) == 24
        assert len(set(offered)) == 24

    def test_a_group_announces_one_shared_block(self):
        neighbors = self.neighbors(self.scenario(path_diversity=3))
        assert neighbors[0]['paths'] == neighbors[1]['paths'] == \
            neighbors[2]['paths']
        assert neighbors[3]['paths'] == neighbors[4]['paths'] == \
            neighbors[5]['paths']

    def test_different_groups_stay_disjoint(self):
        neighbors = self.neighbors(self.scenario(path_diversity=3))
        assert not set(neighbors[0]['paths']) & set(neighbors[3]['paths'])

    def test_the_fleet_offers_more_paths_than_there_are_prefixes(self):
        '''The whole point of the mode: 24 paths for 8 prefixes, so the target
        selects between three rivals for each one.'''
        neighbors = self.neighbors(self.scenario(path_diversity=3))
        offered = [p for n in neighbors for p in n['paths']]
        assert len(offered) == 24
        assert len(set(offered)) == 8

    def test_every_peer_still_offers_the_per_peer_count(self):
        """`count` and the per-neighbour `check-points` are what the target
        compares each session's accepted routes against, and a peer under
        diversity still sends `p` -- all of them accepted, since BGP holds the
        losing paths too.
        """
        neighbors = self.neighbors(self.scenario(path_diversity=3))
        assert all(n['count'] == 4 for n in neighbors)
        assert all(n['check-points'] == 4 for n in neighbors)

    def test_the_monitor_checkpoint_counts_distinct_prefixes(self):
        """The monitor reads what the target *re-advertises*, which is one best
        path per prefix. Counting the 24 offered paths would give a run that
        can never converge; counting one block would report CONVERGED on a
        quarter of the table.
        """
        conf = self.scenario(path_diversity=3)
        assert conf['monitor']['check-points'] == [int(8 * 0.99)]

    def test_the_default_checkpoint_is_unchanged(self):
        assert self.scenario()['monitor']['check-points'] == [int(24 * 0.99)]

    def test_every_peer_on_one_block_leaves_one_block(self):
        conf = self.scenario(path_diversity=6)
        neighbors = self.neighbors(conf)
        assert len({tuple(n['paths']) for n in neighbors}) == 1
        assert conf['monitor']['check-points'] == [int(4 * 0.99)]

    def test_an_args_namespace_without_the_field_is_the_default(self):
        '''`gen_conf()` is reached from callers that predate this flag, and an
        absent attribute has to read as the disjoint workload rather than
        raising.'''
        args = Namespace(
            neighbor_num=6, prefix_num=4, filter_type='in',
            as_path_list_num=0, prefix_list_num=0, community_list_num=0,
            ext_community_list_num=0, single_table=False,
            target_config_file=None, local_address_prefix='10.10.0.0/16',
            target_local_address=None, target_router_id=None,
            monitor_local_address=None, monitor_router_id=None,
            filter_test=None, license_file=None, threads=None,
            tester_type='bird', mrt_file=None)
        conf = yaml.safe_load(Template(bgperf2.gen_conf(args)).render())
        assert conf['monitor']['check-points'] == [int(24 * 0.99)]
        offered = [p for n in conf['testers'][0]['neighbors'].values()
                   for p in n['paths']]
        assert len(set(offered)) == 24


class TestNamingAndProvenance:
    def args(self, **overrides):
        args = Namespace(target='bird', label=None, version=None,
                         tester_type='bird', prefix_num=1_000,
                         neighbor_num=10, filter_test=None, file=None,
                         path_diversity=1)
        for name, value in overrides.items():
            setattr(args, name, value)
        return args

    def test_the_default_keeps_the_stem_it_has_always_had(self):
        assert bgperf2.bench_output_prefix(self.args()) == 'bird_bird_1000_10'

    def test_the_stem_carries_the_diversity(self):
        """Nothing else in the stem does: a disjoint run and a run whose peers
        compete have the same peer count and the same per-peer prefix count, so
        two tests in one batch config differing only in `path_diversity` would
        write every artifact over each other.
        """
        assert bgperf2.bench_output_prefix(self.args(path_diversity=5)) == \
            'bird_bird_1000_10_pd5'

    def test_a_missing_field_is_the_default(self):
        args = self.args()
        del args.path_diversity
        assert bgperf2.bench_output_prefix(args) == 'bird_bird_1000_10'

    def test_the_events_artifact_records_it_too(self, tmp_path):
        """`<prefix>.events.json` is the durable per-run evidence and the
        document `findings.py` reasons over. Carrying `peers` and
        `prefixes_per_peer` alone, it would state a 10,000-prefix table for a
        run whose target held 2,000 distinct prefixes, with nothing in the
        document able to correct it -- the only other carrier is the `pd5` in
        the filename. Same rule as `repetition`.
        """
        import json
        args = self.args(path_diversity=5, results_dir=str(tmp_path))
        bgperf2.write_event_artifact(args, [], 'run', 'converged')
        with open(tmp_path / 'run.events.json') as f:
            assert json.load(f)['run']['path_diversity'] == 5

    def test_a_scenario_run_records_no_diversity_in_the_events_either(
            self, tmp_path):
        import json
        args = self.args(file='scenario.yaml', results_dir=str(tmp_path))
        bgperf2.write_event_artifact(args, [], 'run', 'converged')
        with open(tmp_path / 'run.events.json') as f:
            assert json.load(f)['run']['path_diversity'] is None

    def test_provenance_records_what_was_configured(self, tmp_path):
        doc = self.record(tmp_path, self.args(path_diversity=5))
        assert doc['run']['path_diversity'] == 5

    def test_provenance_records_the_default_explicitly(self, tmp_path):
        doc = self.record(tmp_path, self.args())
        assert doc['run']['path_diversity'] == 1

    def test_a_scenario_run_records_no_diversity(self, tmp_path):
        """Under `-f` the file states each neighbour's paths, so a 1 here would
        be an assertion about a workload bgperf2 did not build. Provenance
        never guesses.
        """
        doc = self.record(tmp_path, self.args(file='scenario.yaml'))
        assert doc['run']['path_diversity'] is None

    def record(self, tmp_path, args):
        import json
        args.results_dir = str(tmp_path)
        path = bgperf2.write_provenance(args, {}, 'run')
        with open(path) as f:
            return json.load(f)


class TestTheBatchPath:
    def test_a_test_may_declare_it(self):
        bgperf2.check_batch_test(a_test(path_diversity=5))

    def test_an_inexact_division_is_refused_before_the_first_container(self):
        with pytest.raises(SystemExit) as raised:
            bgperf2.check_batch_test(a_test(path_diversity=4))
        assert 'does not divide 10 peers' in str(raised.value)

    def test_every_peer_count_on_the_axis_is_checked(self):
        """A matrix is where a division that works for one entry and not the
        next is easy to write, and finding that out at cell three is hours.
        """
        bgperf2.check_batch_test(a_test(neighbors=[10, 25, 50],
                                        path_diversity=5))
        with pytest.raises(SystemExit) as raised:
            bgperf2.check_batch_test(
                a_test(neighbors=[10, 24, 50], path_diversity=5))
        assert 'does not divide 24 peers' in str(raised.value)

    def test_an_mrt_target_refuses_the_whole_test(self):
        '''`prefixes` and the diversity are single axes shared by every target,
        so a test mixing an MRT generator with a synthetic one cannot be right
        for both.'''
        test = a_test(path_diversity=5,
                      targets=[{'name': 'bird'},
                               {'name': 'frr_c', 'tester_type': 'bgpdump2',
                                'mrt_file': 'rib.mrt'}])
        with pytest.raises(SystemExit) as raised:
            bgperf2.check_batch_test(test)
        assert 'does not apply' in str(raised.value)

    def test_a_scenario_target_has_nothing_to_group(self):
        """`bench()`'s own refusal is unreachable from here: `batch()`
        synthesizes the args itself, so a scenario target reaches `bench()`
        with `-f` set and the value still on it.
        """
        test = a_test(path_diversity=5,
                      targets=[{'name': 'bird', 'file': 'scenario.yaml'}])
        with pytest.raises(SystemExit) as raised:
            bgperf2.check_batch_test(test)
        assert 'nothing to group' in str(raised.value)

    def test_a_scenario_target_without_it_is_untouched(self):
        bgperf2.check_batch_test(
            a_test(targets=[{'name': 'bird', 'file': 'scenario.yaml'}]))

    def test_the_total_scope_is_refused_with_it(self):
        with pytest.raises(SystemExit) as raised:
            bgperf2.check_batch_test(
                a_test(path_diversity=5, prefix_scope='total',
                       prefixes=[100_000]))
        assert 'not defined together' in str(raised.value)

    def test_it_is_a_test_key_and_not_a_target_key(self):
        """Every knob an operator sets is a target key, so one level too deep
        is the natural slip: `batch()` reads a fixed field list and ignores the
        rest, so the test would run disjoint and its rows would read as a
        diversity sweep.
        """
        with pytest.raises(SystemExit) as raised:
            bgperf2.check_batch_test(
                a_test(targets=[{'name': 'bird', 'path_diversity': 5}]))
        assert 'path_diversity' in str(raised.value)
        assert 'Move it up one level' in str(raised.value)

    def test_the_cell_carries_it(self):
        cells = bgperf2.expand_batch_cells(a_test(path_diversity=5),
                                           [{'name': 'bird'}])
        assert all(c['path_diversity'] == 5 for c in cells)

    def test_a_test_without_it_carries_the_default(self):
        cells = bgperf2.expand_batch_cells(a_test(), [{'name': 'bird'}])
        assert all(c['path_diversity'] == 1 for c in cells)


class TestTheCellIdentity:
    def cell(self, **overrides):
        cell = {'repetition': None, 'ordinal': 0, 'neighbors': 10,
                'prefixes': 1_000, 'filter': 'None', 'path_diversity': 1,
                'target': {'name': 'bird'}}
        cell.update(overrides)
        return cell

    def test_a_disjoint_cell_id_is_the_shape_it_always_had(self):
        """Omitted at the default for the same reason `repetition` is omitted
        for a single-pass test: an in-flight batch written by an older build
        resumes instead of costing the operator every completed cell, and
        `BATCH_PROGRESS_SCHEMA_VERSION` does not have to move.
        """
        assert 'path_diversity' not in bgperf2.batch_cell_id('t', self.cell())

    def test_a_missing_key_reads_as_the_default(self):
        cell = self.cell()
        del cell['path_diversity']
        assert bgperf2.batch_cell_id('t', cell) == \
            bgperf2.batch_cell_id('t', self.cell())

    def test_the_diversity_is_part_of_the_identity(self):
        """A test whose `path_diversity` is edited between runs describes a
        different workload; an id that did not say so would let `--resume`
        reuse rows measured against the old one.
        """
        assert bgperf2.batch_cell_id('t', self.cell()) != \
            bgperf2.batch_cell_id('t', self.cell(path_diversity=5))

    def test_the_description_names_it_only_when_it_is_set(self):
        assert 'paths per prefix' not in \
            bgperf2.batch_cell_description(self.cell())
        assert 'paths per prefix=5' in \
            bgperf2.batch_cell_description(self.cell(path_diversity=5))


class TestTheCommandLineEntryPoints:
    def bench_args(self, **overrides):
        args = Namespace(dir='/tmp', bench_name='x', docker_network_name=None,
                         file=None, target='bird', version=None, image=None,
                         repeat=True, neighbor_num=10, prefix_num=100,
                         prefix_scope='per-peer', tester_type='bird',
                         mrt_file=None, mrt_injector=None, path_diversity=4)
        for name, value in overrides.items():
            setattr(args, name, value)
        return args

    def test_bench_refuses_an_inexact_division(self):
        with pytest.raises(SystemExit) as raised:
            bgperf2.bench(self.bench_args())
        assert 'does not divide 10 peers' in str(raised.value)

    def test_bench_refuses_it_under_a_scenario_file(self):
        """`-n` and `-p` are already ignored under `-f` and this would be too,
        but the whole point of the flag is that it changes the workload, so
        accepting it where it does nothing is worse than the existing silence.
        """
        with pytest.raises(SystemExit) as raised:
            bgperf2.bench(self.bench_args(file='scenario.yaml',
                                          path_diversity=5))
        assert 'nothing to group under -f' in str(raised.value)

    def test_a_scenario_file_at_the_default_is_untouched(self):
        '''It must not refuse every `-f` run, which is what a check that did
        not exempt the default would do.'''
        with pytest.raises(SystemExit) as raised:
            bgperf2.bench(self.bench_args(file='scenario.yaml',
                                          path_diversity=1,
                                          prefix_scope='total'))
        assert 'nothing to divide under -f' in str(raised.value)

    def test_config_refuses_an_inexact_division(self):
        """The tool that would produce a scenario file is this one, so it needs
        the guard at least as much as `bench` does.
        """
        args = self.bench_args(output='/dev/null')
        with pytest.raises(SystemExit) as raised:
            bgperf2.config(args)
        assert 'does not divide 10 peers' in str(raised.value)

    def test_config_refuses_it_beside_the_total_scope(self):
        args = self.bench_args(output='/dev/null', path_diversity=5,
                               neighbor_num=10, prefix_num=100,
                               prefix_scope='total')
        with pytest.raises(SystemExit) as raised:
            bgperf2.config(args)
        assert 'not defined together' in str(raised.value)
