'''Changing import policy on a table the target already holds.

Every workload before this one measures a target *acquiring* routes -- the
initial delivery, and, since churn, a bounded block of it going away and coming
back. `--policy-reload-blocks N` (batch: `policy_reload_blocks: N` on a test)
measures the other thing a router spends its life doing: carrying a full table
while the policy over it changes. Once the run has converged, an import policy
rejecting the last N of the fleet's prefix blocks is installed and applied with
the daemon's own reload command, the sessions stay up, and the monitor is
watched until the table has settled at what the new policy leaves.

Five rules carry the weight and each is tested here rather than inferred:

- the policy rejects **whole blocks** off the tail, so it needs no seed and a
  shared block under `--path-diversity` loses the prefix rather than falling
  back to a surviving path -- which is what makes the completion count exact;
- the expected count is measured down from the count the run actually
  converged on, and a target that never held part of a rejected block stalls
  rather than being tolerated;
- a collapsed count is not an applied policy, in either phase;
- what issuing the change cost is published beside what applying it cost, never
  as it: on BIRD the reply returns in milliseconds and the table drains after;
- the target CPU sampled across the interval is the measurement, and an
  interval too short to sample is `null` rather than 0.
'''
import json
from argparse import Namespace

import pytest
import yaml
from mako.template import Template

import bgperf2
import bird
from bird import (POLICY_RELOAD_FILTER, policy_reload_failure,
                  policy_reload_filter_config)
from measurements import (EventKind, EventPhase, MeasurementEventError,
                          PolicyReloadEventRecorder, event_artifact,
                          policy_reload_metrics)
from policy import (DEFAULT_POLICY_RELOAD_BLOCKS,
                    POLICY_RELOAD_STALL_SAMPLES,
                    PolicyReloadConfigurationError, PolicyReloadTracker,
                    policy_reload_counts, rejected_block_indexes,
                    rejected_peer_asns)


def a_test(**overrides):
    test = {
        'name': 'reload',
        'neighbors': [10],
        'prefixes': [1_000],
        'filter_test': ['None'],
        'targets': [{'name': 'bird'}],
    }
    test.update(overrides)
    return test


def conf_args(**overrides):
    args = Namespace(
        neighbor_num=3, prefix_num=4, filter_type='in',
        as_path_list_num=0, prefix_list_num=0, community_list_num=0,
        ext_community_list_num=0, single_table=False,
        target_config_file=None, local_address_prefix='10.10.0.0/16',
        target_local_address=None, target_router_id=None,
        monitor_local_address=None, monitor_router_id=None,
        filter_test=None, license_file=None, threads=None,
        tester_type='bird', mrt_file=None, prefix_scope='per-peer',
        path_diversity=1, receivers=0, churn_prefixes=0, churn_bursts=1)
    for name, value in overrides.items():
        setattr(args, name, value)
    return args


def scenario(**overrides):
    return yaml.safe_load(Template(bgperf2.gen_conf(conf_args(**overrides))).render())


def peers(**overrides):
    conf = scenario(**overrides)
    return [n for t in conf['testers'] for n in t['neighbors'].values()]


def stem_args(**overrides):
    args = Namespace(target='bird', label=None, version=None,
                     tester_type='bird', prefix_num=100, neighbor_num=10,
                     filter_test=None, path_diversity=1, receivers=0,
                     churn_prefixes=0, churn_bursts=1,
                     policy_reload_blocks=DEFAULT_POLICY_RELOAD_BLOCKS)
    for name, value in overrides.items():
        setattr(args, name, value)
    return args


def drive(tracker, samples):
    '''Feed samples until the reload ends, returning every step.'''
    steps = []
    for sample in samples:
        step = tracker.update(sample)
        steps.append(step)
        if step.action in (PolicyReloadTracker.DONE,
                           PolicyReloadTracker.FAILED):
            break
    return steps


class TestChoosingTheBlocks:
    def test_the_policy_rejects_the_tail(self):
        '''Reproducible from the peer count, the diversity and the block count
        alone. A sampled selection would need a seed, and a seed is another
        dimension in the cell identity, the stem and the manifest -- what
        `--prefix-scope` and `--path-diversity` both refuse to become.'''
        assert rejected_block_indexes(10, 3) == (7, 8, 9)
        assert rejected_block_indexes(4, 1) == (3,)

    def test_every_block_is_refused(self):
        '''A target left holding nothing reports the same accepted count as one
        that lost its sessions, which is exactly the reading
        POLICY_RELOAD_COLLAPSE_FRACTION exists to refuse.'''
        with pytest.raises(PolicyReloadConfigurationError) as e:
            rejected_block_indexes(4, 4)
        assert 'holding nothing' in str(e.value)
        with pytest.raises(PolicyReloadConfigurationError):
            rejected_block_indexes(4, 5)

    @pytest.mark.parametrize('blocks', [0, -1, 1.5, True, None, '2'])
    def test_a_block_count_must_be_a_whole_positive_number(self, blocks):
        with pytest.raises(PolicyReloadConfigurationError):
            rejected_block_indexes(4, blocks)

    def test_the_peers_of_the_rejected_blocks_are_named(self):
        '''One peer per block at the default diversity, so the last N peers.'''
        assert rejected_peer_asns(peers(neighbor_num=4), 1, 2) == [1005, 1006]

    def test_a_shared_block_rejects_every_peer_announcing_it(self):
        '''Under --path-diversity a block is announced by several peers, and
        rejecting only some of them would leave the prefix behind a surviving
        path: the target does real work and the monitor's count does not move,
        so the reload could never be observed to complete.'''
        fleet = peers(neighbor_num=6, path_diversity=3)
        assert len(fleet) == 6
        assert rejected_peer_asns(fleet, 3, 1) == [1006, 1007, 1008]

    def test_the_peers_are_ordered_by_as_not_by_mapping_order(self):
        '''A scenario is YAML and the order of a mapping is not part of what
        the file means, while gen_conf() assigns the address and the AS from
        the same index it keys the diversity block on.'''
        fleet = peers(neighbor_num=4)
        assert rejected_peer_asns(list(reversed(fleet)), 1, 2) == [1005, 1006]

    def test_an_inexact_diversity_is_refused(self):
        with pytest.raises(PolicyReloadConfigurationError) as e:
            rejected_peer_asns(peers(neighbor_num=4), 3, 1)
        assert 'equal blocks' in str(e.value)

    def test_a_fleet_with_no_peers_is_refused(self):
        with pytest.raises(PolicyReloadConfigurationError):
            rejected_peer_asns([], 1, 1)


class TestWhatTheMonitorShouldSee:
    def test_the_expected_count_is_exact(self):
        counts = policy_reload_counts(10_000, 1_000, 3)
        assert counts == {'rejected_prefixes': 3_000,
                          'expected_accepted': 7_000}

    def test_it_is_measured_down_from_what_the_run_converged_on(self):
        '''Not from what the fleet offered. The monitor's check-point carries a
        0.99 factor because a target does not always hold every prefix offered
        to it, and a run that converged short would otherwise be given a target
        it can never reach.'''
        assert policy_reload_counts(9_990, 1_000, 1)['expected_accepted'] == 8_990

    def test_a_policy_rejecting_more_than_the_table_is_refused(self):
        with pytest.raises(PolicyReloadConfigurationError) as e:
            policy_reload_counts(500, 1_000, 1)
        assert 'cannot be observed' in str(e.value)


class TestDrivingTheReload:
    def test_the_first_sample_issues_the_reload(self):
        tracker = PolicyReloadTracker(1_000, 800)
        assert tracker.update(1_000).action == PolicyReloadTracker.RELOAD

    def test_it_completes_on_the_sample_that_reaches_the_expected_count(self):
        tracker = PolicyReloadTracker(1_000, 800)
        steps = drive(tracker, [1_000, 950, 870, 800])
        assert [s.action for s in steps] == [
            PolicyReloadTracker.RELOAD, PolicyReloadTracker.WAIT,
            PolicyReloadTracker.WAIT, PolicyReloadTracker.DONE]
        assert steps[-1].completed == PolicyReloadTracker.RELOAD_PHASE
        assert tracker.complete

    def test_a_count_below_the_expected_one_still_completes(self):
        '''The target may hold fewer prefixes than the fleet offered, which is
        why the check-point carries a factor at all. Completion is `<=`.'''
        tracker = PolicyReloadTracker(1_000, 800)
        steps = drive(tracker, [1_000, 799])
        assert steps[-1].action == PolicyReloadTracker.DONE

    def test_a_reload_that_never_lands_stalls_and_names_both_counts(self):
        '''A reconfigure the daemon never applied has no other symptom than the
        count not moving, and the message has to say what it held and what it
        wanted -- a tolerance instead would let a policy that was only half
        applied be published as one that was applied.'''
        tracker = PolicyReloadTracker(1_000, 800, stall_samples=3)
        steps = drive(tracker, [1_000] * 6)
        assert steps[-1].action == PolicyReloadTracker.FAILED
        assert 'stalled' in tracker.fail_msg
        assert '1000' in tracker.fail_msg and '800' in tracker.fail_msg

    def test_progress_resets_the_stall_counter(self):
        '''A large table draining slowly must never be cut off: the bound is
        samples without progress, not elapsed samples.'''
        tracker = PolicyReloadTracker(1_000, 800, stall_samples=3)
        steps = drive(tracker, [1_000, 999, 999, 998, 998, 998, 800])
        assert steps[-1].action == PolicyReloadTracker.DONE

    def test_a_collapsed_count_after_the_reload_is_not_success(self):
        '''Read as an applied policy, a session that flapped would be published
        as a daemon that re-evaluated a table quickly.'''
        tracker = PolicyReloadTracker(1_000, 800)
        steps = drive(tracker, [1_000, 0])
        assert steps[-1].action == PolicyReloadTracker.FAILED
        assert 'no policy rejected' in tracker.fail_msg
        assert 'while the new policy was being applied' in tracker.fail_msg

    def test_a_collapsed_count_before_the_reload_names_that_phase(self):
        '''A table that had already lost routes is not one to change policy on,
        and the two cases send the reader to different logs.'''
        tracker = PolicyReloadTracker(1_000, 800)
        steps = drive(tracker, [10])
        assert steps[-1].action == PolicyReloadTracker.FAILED
        assert 'before the new policy was issued' in tracker.fail_msg

    def test_a_count_just_under_the_expected_one_is_not_a_collapse(self):
        '''The floor scales with the table so a small run is not held to an
        exactness the monitor's own sampling cannot promise.'''
        tracker = PolicyReloadTracker(1_000, 800)
        assert drive(tracker, [1_000, 795])[-1].action == PolicyReloadTracker.DONE

    def test_a_policy_that_rejects_nothing_is_refused(self):
        '''The count is already where it will end, so the first sample would
        complete the reload and publish the poll it landed on as the cost of
        re-evaluating the table.'''
        with pytest.raises(PolicyReloadConfigurationError) as e:
            PolicyReloadTracker(1_000, 1_000)
        assert 'rejects none' in str(e.value)

    def test_a_finished_reload_refuses_more_samples(self):
        tracker = PolicyReloadTracker(1_000, 800)
        drive(tracker, [1_000, 800])
        with pytest.raises(PolicyReloadConfigurationError):
            tracker.update(800)

    @pytest.mark.parametrize('accepted', [-1, 1.5, True, None, '800'])
    def test_a_sample_must_be_a_whole_count(self, accepted):
        tracker = PolicyReloadTracker(1_000, 800)
        with pytest.raises(PolicyReloadConfigurationError):
            tracker.update(accepted)

    def test_the_default_stall_bound_is_the_published_one(self):
        assert PolicyReloadTracker(1_000, 800).stall_samples == \
            POLICY_RELOAD_STALL_SAMPLES


class TestTheBirdMechanism:
    def test_the_filter_is_one_membership_test(self):
        '''A line per peer would make the cost of the policy a property of how
        the filter was generated.'''
        config = policy_reload_filter_config([1002, 1003])
        assert 'bgp_path ~ [1002, 1003]' in config
        assert config.count('reject') == 1
        assert POLICY_RELOAD_FILTER in config

    def test_no_reload_renders_nothing(self):
        '''A run that asked for none renders exactly the config it always has.'''
        assert policy_reload_filter_config([]) == ''
        assert policy_reload_filter_config(None) == ''

    @pytest.mark.parametrize('reply', ['Reconfigured',
                                       'BIRD 3.3.2 ready.\nReconfigured',
                                       'Reconfiguration in progress'])
    def test_an_accepted_configuration_reports_no_failure(self, reply):
        assert policy_reload_failure(reply) is None

    def test_a_syntax_error_is_a_failure(self):
        '''Verified on bgperf/bird:3.3.2: birdc answers `syntax error, ...`,
        exits 1, and leaves the running configuration untouched -- so a failure
        taken for success would mean the run went on measuring the old policy
        while the artifact recorded the new one. The reply text is what we can
        read: `Container.local()` returns the exec's output and never its
        status.'''
        reply = ('Reading configuration from /root/config/bird.conf\n'
                 '/root/config/bird.conf:16:1 syntax error, unexpected '
                 'CF_SYM_UNDEFINED')
        assert 'syntax error' in policy_reload_failure(reply)

    @pytest.mark.parametrize('reply', ['', None, '   '])
    def test_no_reply_at_all_is_a_failure(self, reply):
        assert policy_reload_failure(reply) == 'no reply from birdc configure'

    def test_the_import_clause_prefers_the_reload(self):
        target = bird.BIRDTarget.__new__(bird.BIRDTarget)
        target.conf = {}
        assert target.import_filter_clause(None) == 'all'
        assert target.import_filter_clause([1002]) == \
            'filter {0}'.format(POLICY_RELOAD_FILTER)
        target.conf = {'filter_test': 'transit'}
        assert target.import_filter_clause(None) == 'filter transit'
        # Refused together at every entry point; if that is ever lifted, a
        # config quietly dropping the reload it recorded is the worse failure.
        assert target.import_filter_clause([1002]) == \
            'filter {0}'.format(POLICY_RELOAD_FILTER)

    def test_the_target_declares_its_mechanism(self):
        '''Recorded rather than assumed: a reload that resets its sessions
        measures a second table delivery and belongs in a different
        comparison.'''
        assert bird.BIRDTarget.SUPPORTS_POLICY_RELOAD
        assert bird.BIRDTarget.POLICY_RELOAD_MECHANISM == 'birdc configure'
        assert bird.BIRDTarget.POLICY_RELOAD_SESSION_PRESERVING is True

    def test_every_other_target_declares_it_cannot(self):
        others = {name for name, cls in bgperf2.TARGET_CLASSES.items()
                  if not getattr(cls, 'SUPPORTS_POLICY_RELOAD', False)}
        assert 'bird' not in others
        assert others == set(bgperf2.TARGET_CLASSES) - {'bird'}


class TestTheGuards:
    def test_the_default_is_no_reload(self):
        assert bgperf2.resolve_policy_reload(None, 10) == \
            DEFAULT_POLICY_RELOAD_BLOCKS
        assert bgperf2.resolve_policy_reload(0, 10) == 0

    def test_a_valid_reload_passes(self):
        assert bgperf2.resolve_policy_reload(2, 10, 1, 'bird', 'bird') == 2

    @pytest.mark.parametrize('blocks', [-1, 1.5, True, '2'])
    def test_a_block_count_must_be_a_whole_positive_number(self, blocks):
        with pytest.raises(ValueError):
            bgperf2.resolve_policy_reload(blocks, 10)

    def test_a_target_with_no_mechanism_is_refused(self):
        with pytest.raises(ValueError) as e:
            bgperf2.resolve_policy_reload(2, 10, 1, 'frr_c', 'bird')
        assert 'frr_c' in str(e.value) and 'bird' in str(e.value)

    @pytest.mark.parametrize('tester', ['gobgp', 'bgpdump2'])
    def test_an_mrt_generator_is_refused(self, tester):
        '''The policy selects a block by the peer AS bgperf2 assigned, and an
        MRT injector replays the AS paths in the file; -p is the whole table
        there, so neither the selection nor the expected count survives.'''
        with pytest.raises(ValueError) as e:
            bgperf2.resolve_policy_reload(2, 10, 1, 'bird', tester)
        assert tester in str(e.value)

    def test_a_policy_filter_is_refused(self):
        with pytest.raises(ValueError) as e:
            bgperf2.resolve_policy_reload(2, 10, 1, 'bird', 'bird', 'transit')
        assert 'two policies at once' in str(e.value)

    def test_a_churn_workload_is_refused(self):
        '''Both run against the converged table off the same monitor samples,
        so one would take the other's outcome as its baseline and nothing in
        the row or the artifacts would say which ran first.'''
        with pytest.raises(ValueError) as e:
            bgperf2.resolve_policy_reload(2, 10, 1, 'bird', 'bird', None, 4)
        assert '--churn-prefixes' in str(e.value)

    def test_a_bare_burst_count_is_seen_as_churn_too(self):
        '''Read as the operator wrote them, not as resolve_churn() normalised
        them, so `--churn-bursts 3` alone is still visible here.'''
        with pytest.raises(ValueError) as e:
            bgperf2.resolve_policy_reload(2, 10, 1, 'bird', 'bird', None,
                                          None, 3)
        assert '--churn-bursts' in str(e.value)

    def test_repeat_is_refused(self):
        '''The count the reload completes on is blocks x prefixes per peer, and
        repeat reuses the generator containers as they are. Measured: `-n 4
        -p 1000 -r` behind a `-p 10000` run converged at 40,000, expected the
        policy to leave 39,000, and the rejected peer took 10,000 with it.'''
        with pytest.raises(ValueError) as e:
            bgperf2.resolve_policy_reload(2, 10, 1, 'bird', 'bird', None, None,
                                          None, True)
        assert '-r/--repeat' in str(e.value)

    def test_more_blocks_than_the_fleet_has_is_refused(self):
        with pytest.raises(ValueError) as e:
            bgperf2.resolve_policy_reload(10, 10, 1, 'bird', 'bird')
        assert 'holding nothing' in str(e.value)

    def test_diversity_decides_how_many_blocks_there_are(self):
        '''Ten peers at diversity 5 are two blocks, so two is every block.'''
        assert bgperf2.resolve_policy_reload(1, 10, 5, 'bird', 'bird') == 1
        with pytest.raises(ValueError):
            bgperf2.resolve_policy_reload(2, 10, 5, 'bird', 'bird')

    def test_an_inexact_diversity_is_refused(self):
        with pytest.raises(ValueError):
            bgperf2.resolve_policy_reload(1, 10, 3, 'bird', 'bird')


class TestTheBatchPath:
    def test_a_valid_reload_is_accepted(self):
        bgperf2.check_batch_test(a_test(policy_reload_blocks=2))

    def test_a_reload_on_a_target_with_no_mechanism_is_refused(self):
        '''A batch target bypasses argparse and bench()'s own guards, and the
        cost of finding out mid-batch is the cells that already ran.'''
        with pytest.raises(SystemExit) as e:
            bgperf2.check_batch_test(a_test(
                policy_reload_blocks=2, targets=[{'name': 'frr_c'}]))
        assert 'frr_c' in str(e.value)

    def test_one_unsupported_target_refuses_the_whole_test(self):
        with pytest.raises(SystemExit):
            bgperf2.check_batch_test(a_test(
                policy_reload_blocks=2,
                targets=[{'name': 'bird'}, {'name': 'gobgp'}]))

    def test_every_peer_count_on_the_axis_is_checked(self):
        '''Not just the first: two blocks fit ten peers and not two, and
        finding that out at cell three is hours lost.'''
        with pytest.raises(SystemExit) as e:
            bgperf2.check_batch_test(a_test(
                policy_reload_blocks=2, neighbors=[10, 2]))
        assert 'holding nothing' in str(e.value)

    def test_every_filter_on_the_axis_is_checked(self):
        with pytest.raises(SystemExit) as e:
            bgperf2.check_batch_test(a_test(
                policy_reload_blocks=2, filter_test=['None', 'transit']))
        assert 'two policies at once' in str(e.value)

    def test_an_mrt_target_is_refused(self):
        with pytest.raises(SystemExit) as e:
            bgperf2.check_batch_test(a_test(
                policy_reload_blocks=2,
                targets=[{'name': 'bird', 'tester_type': 'bgpdump2',
                          'mrt_file': '/tmp/x.mrt'}]))
        assert 'bgpdump2' in str(e.value)

    def test_a_scenario_target_is_refused(self):
        with pytest.raises(SystemExit) as e:
            bgperf2.check_batch_test(a_test(
                policy_reload_blocks=2,
                targets=[{'name': 'bird', 'file': '/tmp/scenario.yaml'}]))
        assert 'nothing to reject' in str(e.value)

    def test_a_repeat_target_is_refused(self):
        '''On the CLI that is one wrong run; here it is every cell of a matrix
        naming a policy whose completion count describes another run's
        generators.'''
        with pytest.raises(SystemExit) as e:
            bgperf2.check_batch_test(a_test(
                policy_reload_blocks=2,
                targets=[{'name': 'bird', 'repeat': True}]))
        assert '-r/--repeat' in str(e.value)

    def test_it_is_a_test_key_not_a_target_key(self):
        '''Every other knob an operator sets is a target key, so a test key one
        level too deep is the natural slip -- and it fails silently.'''
        with pytest.raises(SystemExit) as e:
            bgperf2.check_batch_test(a_test(
                targets=[{'name': 'bird', 'policy_reload_blocks': 2}]))
        assert 'policy_reload_blocks' in str(e.value)

    def test_a_misspelt_key_is_refused(self):
        with pytest.raises(SystemExit):
            bgperf2.check_batch_test(a_test(policy_reload_block=2))


class TestTheCellIdentity:
    def cell(self, **overrides):
        cell = {'repetition': None, 'ordinal': 0, 'neighbors': 10,
                'prefixes': 100, 'filter': 'None', 'path_diversity': 1,
                'receivers': 0, 'churn_prefixes': 0, 'churn_bursts': 1,
                'policy_reload_blocks': DEFAULT_POLICY_RELOAD_BLOCKS,
                'target': {'name': 'bird'}}
        cell.update(overrides)
        return cell

    def test_the_default_omits_the_key_entirely(self):
        '''So a cell id keeps exactly the shape it had before this flag
        existed, an in-flight batch from an older build still resumes, and
        BATCH_PROGRESS_SCHEMA_VERSION does not have to move.'''
        identity = json.loads(bgperf2.batch_cell_id('reload', self.cell()))
        assert 'policy_reload_blocks' not in identity

    def test_a_reload_is_part_of_the_identity(self):
        '''Widening the policy is a different run rather than more of the same
        one, so --resume must not match a cell measured against the old one.'''
        identity = json.loads(
            bgperf2.batch_cell_id('reload', self.cell(policy_reload_blocks=2)))
        assert identity['policy_reload_blocks'] == 2
        assert bgperf2.batch_cell_id('reload', self.cell(policy_reload_blocks=2)) \
            != bgperf2.batch_cell_id('reload', self.cell(policy_reload_blocks=3))

    def test_the_cell_is_described_with_it(self):
        described = bgperf2.batch_cell_description(
            self.cell(policy_reload_blocks=2))
        assert 'policy reload=2 block(s)' in described
        assert 'policy reload' not in bgperf2.batch_cell_description(self.cell())

    def test_expansion_carries_it_onto_every_cell(self):
        test = a_test(policy_reload_blocks=2)
        cells = bgperf2.expand_batch_cells(test, test['targets'])
        assert {c['policy_reload_blocks'] for c in cells} == {2}


class TestTheArtifactStem:
    def test_the_default_keeps_the_name_it_has_always_had(self):
        assert bgperf2.bench_output_prefix(stem_args()) == 'bird_bird_100_10'

    def test_a_reload_is_in_the_stem(self):
        '''Nothing else in the stem moves with it, so two tests differing only
        in the policy would write every per-run artifact over each other.'''
        assert bgperf2.bench_output_prefix(
            stem_args(policy_reload_blocks=2)).endswith('_pr2')

    def test_two_policies_do_not_share_a_stem(self):
        assert bgperf2.bench_output_prefix(stem_args(policy_reload_blocks=2)) \
            != bgperf2.bench_output_prefix(stem_args(policy_reload_blocks=3))


class TestTheScenarioIsUnchanged:
    def test_a_reload_changes_no_part_of_the_scenario(self):
        '''It is a runtime action on the target, which is why `config` does not
        take the flag: offering it there would print a scenario that reads as
        though it encoded a workload it does not.'''
        parser = bgperf2.create_args_parser()
        args = parser.parse_args(['bench', '-t', 'bird'])
        assert args.policy_reload_blocks == DEFAULT_POLICY_RELOAD_BLOCKS
        config_args = parser.parse_args(['config'])
        assert not hasattr(config_args, 'policy_reload_blocks')


class TestTheEvents:
    def recorder(self, **overrides):
        counters = {'rejected_blocks': 2, 'rejected_prefixes': 200,
                    'converged_prefixes': 1_000, 'expected_accepted': 800}
        counters.update(overrides)
        return PolicyReloadEventRecorder(
            10.0, producer='bgperf_monitor', sample_interval_s=1,
            counters=counters, rejected_peer_asns=[1009, 1010])

    def test_both_events_are_stamped_at_monitor_samples(self):
        r = self.recorder()
        r.observe(11.0, 1_000)
        r.note_reload_started(command_s=0.04)
        r.observe(14.0, 800)
        r.note_reload_complete()
        kinds = [(e.kind, e.monotonic_s) for e in r.events]
        assert kinds == [(EventKind.POLICY_RELOAD_STARTED, 11.0),
                         (EventKind.POLICY_RELOAD_COMPLETE, 14.0)]
        assert all(e.phase == EventPhase.POLICY_RELOAD for e in r.events)

    def test_the_phase_is_its_own(self):
        '''Both this and churn happen after convergence, but one measures a
        table moving under a fixed policy and the other a fixed table under a
        policy that moved -- a reader grouping by phase must not find two
        intervals under one name.'''
        assert EventPhase.POLICY_RELOAD != EventPhase.CHURN

    def test_an_event_before_any_sample_is_refused(self):
        with pytest.raises(MeasurementEventError):
            self.recorder().note_reload_started()

    def test_completing_a_reload_that_did_not_start_is_refused(self):
        r = self.recorder()
        r.observe(11.0, 1_000)
        with pytest.raises(MeasurementEventError):
            r.note_reload_complete()

    def test_a_sample_before_convergence_is_refused(self):
        r = self.recorder()
        with pytest.raises(Exception):
            r.observe(9.0, 1_000)

    def test_the_metrics_carry_both_counts_and_the_interval(self):
        r = self.recorder()
        r.observe(11.0, 1_000)
        r.note_reload_started(command_s=0.04)
        r.observe(14.0, 800)
        r.note_reload_complete()
        measured = policy_reload_metrics(r.events)
        assert measured['complete'] is True
        assert measured['accepted_before'] == 1_000
        assert measured['accepted_after'] == 800
        assert measured['expected_accepted'] == 800
        assert measured['rejected_blocks'] == 2
        assert measured['rejected_peer_asns'] == [1009, 1010]
        assert measured['reload_s'] == pytest.approx(3.0)
        assert measured['command_s'] == pytest.approx(0.04)

    def test_the_command_cost_is_not_the_reload(self):
        '''On BIRD the reply comes back in milliseconds and the table drains
        afterwards, so publishing one number would credit the daemon with an
        instant reload.'''
        r = self.recorder()
        r.observe(11.0, 1_000)
        r.note_reload_started(command_s=0.04)
        r.observe(14.0, 800)
        r.note_reload_complete()
        measured = policy_reload_metrics(r.events)
        assert measured['command_s'] < measured['reload_s']

    def test_a_reload_that_did_not_finish_keeps_what_it_measured(self):
        '''A document holding a reload with nothing saying it did not finish
        reads as a run that never asked for one.'''
        r = self.recorder()
        r.observe(11.0, 1_000)
        r.note_reload_started()
        measured = policy_reload_metrics(r.events)
        assert measured['requested'] is True
        assert measured['complete'] is False
        assert measured['accepted_before'] == 1_000
        assert measured['accepted_after'] is None
        assert measured['reload_s'] is None

    def test_an_interval_of_one_poll_carries_its_resolution(self):
        '''An interval bounded below by one poll is an upper bound, not a
        duration: the reload is issued just after a sample and the soonest it
        can be seen is the next.'''
        r = self.recorder()
        r.observe(11.0, 1_000)
        r.note_reload_started()
        r.observe(12.0, 800)
        r.note_reload_complete()
        measured = policy_reload_metrics(r.events)
        assert measured['reload_s'] == pytest.approx(1.0)
        assert measured['reload_resolution_s'] == pytest.approx(1.0)


class TestTheArtifact:
    def events(self):
        r = PolicyReloadEventRecorder(
            0.0, producer='bgperf_monitor', sample_interval_s=1,
            counters={'rejected_blocks': 1, 'rejected_prefixes': 100,
                      'converged_prefixes': 1_000, 'expected_accepted': 900},
            rejected_peer_asns=[1010])
        r.observe(1.0, 1_000)
        r.note_reload_started(command_s=0.01)
        r.observe(3.0, 900)
        r.note_reload_complete()
        return r.events

    def test_a_run_with_no_reload_has_no_section(self):
        '''So a document produced by every command line that predates this flag
        is unchanged.'''
        assert 'policy_reload' not in event_artifact((), 'converged')

    def test_a_driven_reload_is_published(self):
        artifact = event_artifact(self.events(), 'converged')
        assert artifact['policy_reload']['accepted_after'] == 900

    def test_evidence_alone_is_enough(self):
        '''A reload refused before it was issued has nothing in the event
        stream, and a document with no section would read as a run that never
        asked for one.'''
        artifact = event_artifact(
            (), 'converged',
            policy_reload={'reload_complete': False,
                           'incomplete_reason': 'no mechanism'})
        assert artifact['policy_reload']['incomplete_reason'] == 'no mechanism'
        assert artifact['policy_reload']['requested'] is False

    def test_evidence_may_not_overwrite_a_derived_interval(self):
        '''A caller able to overwrite a measured interval with a value the
        events do not support defeats the point of deriving them.'''
        with pytest.raises(MeasurementEventError):
            event_artifact(self.events(), 'converged',
                           policy_reload={'reload_s': 0.0})

    def test_the_mechanism_reaches_the_document(self):
        '''A reload that resets its sessions measures a second delivery and
        belongs in a different comparison; a reader cannot tell which they have
        without being told.'''
        artifact = event_artifact(
            self.events(), 'converged',
            policy_reload={'mechanism': 'birdc configure',
                           'session_preserving': True})
        assert artifact['policy_reload']['session_preserving'] is True

    def test_an_unsampled_cpu_interval_is_not_zero(self):
        artifact = event_artifact(
            self.events(), 'converged',
            policy_reload={'target_cpu_samples': 0,
                           'target_cpu_percent_max': None})
        assert artifact['policy_reload']['target_cpu_percent_max'] is None


class TestUnrunEvidence:
    def test_a_run_that_asked_and_issued_none_says_so(self):
        '''`run.policy_reload_blocks: 2` with no section reads as a run that
        asked for no reload, which is the ambiguity the artifact removes.'''
        args = Namespace(policy_reload_blocks=2)
        evidence = bgperf2.unrun_policy_reload_evidence(args, 'failed')
        assert evidence['reload_complete'] is False
        assert 'did not converge' in evidence['incomplete_reason']

    def test_a_run_that_asked_for_none_produces_nothing(self):
        args = Namespace(policy_reload_blocks=0)
        assert bgperf2.unrun_policy_reload_evidence(args, 'converged') is None

    def test_a_converged_run_is_described_differently(self):
        args = Namespace(policy_reload_blocks=2)
        evidence = bgperf2.unrun_policy_reload_evidence(args, 'converged')
        assert evidence['incomplete_reason'] == 'no policy reload was issued'


class TestTheDescriptions:
    def test_the_workload_is_stated_before_the_run(self):
        described = bgperf2.describe_policy_reload_workload(
            2, 10, 1_000, 1, 'birdc configure')
        assert '2 of 10' in described
        assert '2000 distinct prefix(es)' in described
        assert 'birdc configure' in described

    def test_a_shared_block_names_every_peer_it_rejects(self):
        described = bgperf2.describe_policy_reload_workload(1, 10, 1_000, 5)
        assert '1 of 2' in described
        assert '5 peer(s)' in described

    def test_no_reload_says_nothing(self):
        assert bgperf2.describe_policy_reload_workload(0, 10, 1_000) is None

    def test_a_completed_reload_reports_both_costs(self):
        lines = bgperf2.describe_policy_reload_metrics({
            'reload_complete': True, 'accepted_before': 1_000,
            'accepted_after': 900,
            'reload_s': 3.0, 'reload_resolution_s': 1.0, 'command_s': 0.04,
            'target_cpu_percent_max': 87.5, 'target_cpu_samples': 3})
        assert 'in 3.0s' in lines[0]
        assert '0.040s' in lines[0]
        assert '87.50%' in lines[1]

    def test_an_interval_of_one_poll_is_reported_as_a_bound(self):
        lines = bgperf2.describe_policy_reload_metrics({
            'reload_complete': True, 'accepted_before': 1_000,
            'accepted_after': 900,
            'reload_s': 1.0, 'reload_resolution_s': 1.0, 'command_s': 0.04,
            'target_cpu_percent_max': None, 'target_cpu_samples': 0})
        assert 'within the 1.0s poll resolution' in lines[0]

    def test_an_unsampled_cpu_interval_is_said_out_loud(self):
        '''An interval too short to sample and an interval in which the target
        did nothing are different findings, and only the second is about the
        daemon.'''
        lines = bgperf2.describe_policy_reload_metrics({
            'reload_complete': True, 'accepted_before': 1_000,
            'accepted_after': 900,
            'reload_s': 1.0, 'reload_resolution_s': 1.0, 'command_s': 0.04,
            'target_cpu_percent_max': None, 'target_cpu_samples': 0})
        assert 'unmeasured at this resolution' in lines[1]

    def test_an_incomplete_reload_says_why(self):
        lines = bgperf2.describe_policy_reload_metrics(
            {'reload_complete': False,
             'incomplete_reason': 'the reload stalled'})
        assert lines == ['policy reload: not completed; the reload stalled']

    def test_no_section_says_nothing(self):
        assert bgperf2.describe_policy_reload_metrics(None) == []
