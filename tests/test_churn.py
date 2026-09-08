'''Bounded withdrawal/reannouncement bursts.

Every run bgperf2 has ever published measures one thing: a table arriving at a
daemon that has never seen it. A router spends almost none of its life doing
that -- it spends it holding a table while parts of it move. `--churn-prefixes
C` (batch: `churn_prefixes: C` on a test) withdraws the last C of each peer's
prefixes once the run has converged and puts them back, `--churn-bursts B`
times, so the target has to remove routes from a loaded table, re-run best-path
selection for every prefix that had a competing path, and withdraw and
re-advertise on every export session.

Four rules carry the weight and each is tested here rather than inferred:

- the churn block is the **tail** of a peer's own list, so a group sharing a
  block under `--path-diversity` churns the same prefixes and the monitor sees
  `groups * C` go away rather than `peers * C`;
- the two halves of a burst are timed separately, because dropping routes and
  re-selecting/re-exporting them are different mechanisms;
- an interval of one poll is an upper bound and not a duration, since a burst
  is issued just after a sample and can only be seen at the next;
- a burst nobody performed is reported at the moment it was issued, not
  discovered as a stall five minutes later.
'''
import json
from argparse import Namespace
from queue import Queue

import pytest
import yaml
from mako.template import Template

import bgperf2
import measurements
import tester as tester_mod
from bird import churn_failures, churn_reply_ok
from churn import (CHURN_STALL_SAMPLES, ChurnBurstTracker,
                   ChurnConfigurationError, churn_operation_counts,
                   split_churn_paths)
from measurements import (ChurnEventRecorder, EventKind, EventPhase,
                          MeasurementEventError, churn_metrics, event_artifact)


def a_test(**overrides):
    test = {
        'name': 'churn',
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


def drive(tracker, samples):
    '''Feed samples until the sequence ends, returning every step.'''
    steps = []
    for sample in samples:
        step = tracker.update(sample)
        steps.append(step)
        if step.action in (ChurnBurstTracker.DONE, ChurnBurstTracker.FAILED):
            break
    return steps


class TestSplittingTheBlock:
    def test_the_block_is_the_tail(self):
        '''Reproducible from the per-peer count and the churn count alone. A
        sampled block would need a seed, and a seed is a fourth dimension in
        the cell identity, the stem and the manifest.
        '''
        stable, churning = split_churn_paths(['a', 'b', 'c', 'd'], 2)
        assert (stable, churning) == (['a', 'b'], ['c', 'd'])

    def test_no_churn_leaves_the_list_alone(self):
        '''What every command line predating the flag renders: one static
        protocol holding every path, byte for byte.
        '''
        assert split_churn_paths(['a', 'b'], 0) == (['a', 'b'], [])

    def test_absent_is_no_churn(self):
        assert split_churn_paths(['a', 'b'], None) == (['a', 'b'], [])

    def test_the_whole_list_may_be_churned(self):
        assert split_churn_paths(['a', 'b'], 2) == ([], ['a', 'b'])

    def test_a_block_larger_than_the_peer_is_refused(self):
        with pytest.raises(ChurnConfigurationError) as e:
            split_churn_paths(['a', 'b'], 3)
        assert '3' in str(e.value) and '2' in str(e.value)

    def test_a_negative_block_is_refused(self):
        with pytest.raises(ChurnConfigurationError):
            split_churn_paths(['a', 'b'], -1)

    def test_a_boolean_is_not_a_count(self):
        with pytest.raises(ChurnConfigurationError):
            split_churn_paths(['a', 'b'], True)

    def test_a_group_sharing_a_block_churns_the_same_prefixes(self):
        '''The whole reason the tail is the rule. Under --path-diversity the
        peers of a group are handed the same list, so taking the tail of each
        gives them the same block -- the target loses the prefix rather than
        falling back to a surviving path, which is the withdrawal a best-path
        selection has to react to.
        '''
        shared = ['p1', 'p2', 'p3', 'p4']
        first = split_churn_paths(shared, 2)[1]
        second = split_churn_paths(shared, 2)[1]
        assert first == second == ['p3', 'p4']


class TestOperationCounts:
    def test_disjoint_peers_offer_and_show_the_same_count(self):
        assert churn_operation_counts(10, 5, 10) == {
            'offered_withdrawals': 50, 'distinct_withdrawals': 50}

    def test_a_shared_block_shows_fewer_than_it_offers(self):
        '''10 peers in groups of 5 is 2 blocks: the fleet withdraws 50 paths
        and the monitor sees 10 prefixes go away. Reporting only one of these
        mis-sizes the workload by exactly the diversity.
        '''
        assert churn_operation_counts(10, 5, 2) == {
            'offered_withdrawals': 50, 'distinct_withdrawals': 10}

    def test_more_blocks_than_peers_is_refused(self):
        with pytest.raises(ChurnConfigurationError):
            churn_operation_counts(4, 1, 5)

    def test_zero_peers_is_refused(self):
        with pytest.raises(ChurnConfigurationError):
            churn_operation_counts(0, 1, 1)


class TestTheBurstSequence:
    def test_one_burst_runs_withdraw_then_reannounce(self):
        tracker = ChurnBurstTracker(1, 100, 10)
        steps = drive(tracker, [100, 100, 90, 90, 100])
        assert [s.action for s in steps] == ['withdraw', 'wait', 'reannounce',
                                             'wait', 'done']
        assert [s.completed for s in steps] == [None, None, 'withdraw', None,
                                                'reannounce']
        assert tracker.completed_bursts == 1

    def test_a_burst_opens_on_the_sample_after_the_last_one_closed(self):
        '''Not on the same sample. Issuing the next withdrawal the instant the
        table looks restored puts burst 2 against a baseline the target had
        not actually reached -- it is still draining its export queues.
        '''
        tracker = ChurnBurstTracker(2, 100, 10)
        steps = drive(tracker, [100, 90, 100, 100, 90, 100])
        assert [s.action for s in steps] == ['withdraw', 'reannounce', 'wait',
                                             'withdraw', 'reannounce', 'done']
        assert steps[2].completed == 'reannounce' and steps[2].burst == 1
        assert steps[3].burst == 2

    def test_a_small_overshoot_still_completes_the_withdrawal(self):
        '''The rule is `fallen by at least the block`, not `equal to`: the
        monitor samples a table in motion, so a few prefixes either side of
        the floor is the instrument rather than a fault.
        '''
        tracker = ChurnBurstTracker(1, 1000, 100)
        steps = drive(tracker, [1000, 895, 1000])
        assert steps[1].completed == 'withdraw'

    def test_a_collapsed_count_is_not_a_withdrawal(self):
        '''The peers withdraw exactly the block, so a count far below the
        floor is routes nobody withdrew -- a session that flapped, a target
        that restarted. Read as a withdrawal it would stamp the burst
        complete, issue the re-announcement against a table that never lost
        the block, and publish the session re-learning the whole table as
        `reannounce_s`.
        '''
        tracker = ChurnBurstTracker(1, 1000, 100)
        steps = drive(tracker, [1000, 0])
        assert steps[-1].action == 'failed'
        assert 'lost more than the burst withdrew' in tracker.fail_msg

    def test_a_collapse_during_the_reannouncement_is_named_too(self):
        '''Waited out instead, it would reach the stall bound and be blamed
        on a slow target.
        '''
        tracker = ChurnBurstTracker(1, 1000, 100)
        steps = drive(tracker, [1000, 900, 0])
        assert steps[-1].action == 'failed'
        assert 'lost more than the burst withdrew' in tracker.fail_msg

    def test_a_collapse_between_bursts_is_named_too(self):
        '''And before the next burst is opened: a table that has lost routes
        nobody withdrew is not one to start a burst against.
        '''
        tracker = ChurnBurstTracker(2, 1000, 100)
        steps = drive(tracker, [1000, 900, 1000, 0])
        assert steps[-1].action == 'failed'
        assert 'between churn bursts after 1/2' in tracker.fail_msg

    def test_a_collapse_before_the_first_burst_says_so(self):
        '''A session dropping between convergence and the first churn poll is
        the flap this rule exists for, and `between bursts` would misdescribe
        when it happened.
        '''
        tracker = ChurnBurstTracker(2, 1000, 100)
        assert tracker.update(0).action == 'failed'
        assert 'before the first churn burst' in tracker.fail_msg

    def test_the_collapse_message_names_its_phase(self):
        '''The rule `_stall()` follows: a withdrawal that lost routes and a
        re-announcement that lost them send the reader to different logs.
        '''
        withdrawing = ChurnBurstTracker(1, 1000, 100)
        drive(withdrawing, [1000, 0])
        assert 'during the withdrawal' in withdrawing.fail_msg
        reannouncing = ChurnBurstTracker(1, 1000, 100)
        drive(reannouncing, [1000, 900, 0])
        assert 'during the re-announcement' in reannouncing.fail_msg

    def test_the_collapse_bound_scales_with_the_table(self):
        '''A fraction of the converged count, floored at one prefix so a
        small run is not held to an exactness the monitor cannot promise.
        '''
        assert ChurnBurstTracker(1, 1000, 100).collapse_below == 890
        assert ChurnBurstTracker(1, 20, 8).collapse_below == 11

    def test_a_partial_drop_does_not_complete_the_withdrawal(self):
        tracker = ChurnBurstTracker(1, 100, 10)
        steps = drive(tracker, [100, 95, 91])
        assert [s.completed for s in steps] == [None, None, None]

    def test_a_withdrawal_that_never_lands_stalls(self):
        tracker = ChurnBurstTracker(1, 100, 10, stall_samples=3)
        steps = drive(tracker, [100] * 10)
        assert steps[-1].action == 'failed'
        assert 'withdrawal' in tracker.fail_msg
        assert '1/1' in tracker.fail_msg

    def test_a_reannouncement_that_never_lands_stalls(self):
        tracker = ChurnBurstTracker(1, 100, 10, stall_samples=3)
        steps = drive(tracker, [100, 90] + [90] * 10)
        assert steps[-1].action == 'failed'
        assert 'reannouncement' in tracker.fail_msg

    def test_progress_resets_the_stall_counter(self):
        '''Counted in samples without progress, not in samples: a 5,000,000
        route reannouncement moves the count on nearly every poll and must
        never be cut off for taking a long time.
        '''
        tracker = ChurnBurstTracker(1, 100, 10, stall_samples=3)
        steps = drive(tracker, [100, 100, 100, 99, 99, 99, 98, 90, 100])
        assert steps[-1].action == 'done'

    def test_a_block_bigger_than_the_converged_table_is_refused(self):
        '''The one rule that cannot be checked before the run: the converged
        count is not known until the table has been delivered, so a run that
        accepted fewer prefixes than it offered can reach a block the flag
        guards passed. A burst nothing could observe would stall and be
        reported as a stuck target.
        '''
        with pytest.raises(ChurnConfigurationError) as e:
            ChurnBurstTracker(1, 5, 10)
        assert '10' in str(e.value) and '5' in str(e.value)

    def test_zero_bursts_is_refused(self):
        with pytest.raises(ChurnConfigurationError):
            ChurnBurstTracker(0, 100, 10)

    def test_an_empty_block_is_refused(self):
        with pytest.raises(ChurnConfigurationError):
            ChurnBurstTracker(1, 100, 0)

    def test_a_finished_sequence_refuses_more_samples(self):
        tracker = ChurnBurstTracker(1, 100, 10)
        drive(tracker, [100, 90, 100])
        with pytest.raises(ChurnConfigurationError):
            tracker.update(100)

    def test_a_non_integer_count_is_refused(self):
        tracker = ChurnBurstTracker(1, 100, 10)
        with pytest.raises(ChurnConfigurationError):
            tracker.update(1.5)

    def test_the_default_stall_bound_is_generous(self):
        '''Five minutes of complete silence at the monitor's 1s cadence. It
        bounds a burst nobody performed, not a burst that is taking a while.
        '''
        assert CHURN_STALL_SAMPLES >= 60


class TestRecordingTheEvents:
    def recorder(self, **kwargs):
        options = dict(producer='bgperf_monitor', sample_interval_s=1.0,
                       requested_bursts=2, offered_withdrawals=50,
                       distinct_withdrawals=10)
        options.update(kwargs)
        return ChurnEventRecorder(100.0, **options)

    def a_burst(self, recorder, burst, start, withdrawn, restored):
        recorder.observe(start, 1000)
        recorder.note_burst_started(burst)
        recorder.observe(withdrawn, 990)
        recorder.note_withdraw_complete(burst)
        recorder.observe(restored, 1000)
        recorder.note_burst_complete(burst)

    def test_a_burst_produces_three_events_in_the_churn_phase(self):
        recorder = self.recorder()
        self.a_burst(recorder, 1, 101.0, 103.0, 106.0)
        assert [e.kind for e in recorder.events] == [
            EventKind.CHURN_BURST_STARTED,
            EventKind.CHURN_WITHDRAW_COMPLETE,
            EventKind.CHURN_BURST_COMPLETE]
        assert all(e.phase == EventPhase.CHURN for e in recorder.events)

    def test_the_two_halves_are_reported_separately(self):
        '''Dropping routes and re-selecting/re-exporting them are different
        mechanisms, and the second is one of the three BIRD 3 parallelises. A
        single end-to-end number cannot say which one was slow.
        '''
        recorder = self.recorder()
        self.a_burst(recorder, 1, 101.0, 103.0, 106.0)
        measured = churn_metrics(recorder.events)['bursts'][0]
        assert measured['withdraw_s'] == 2.0
        assert measured['reannounce_s'] == 3.0

    def test_the_burst_is_the_sum_of_its_halves(self):
        '''The withdrawal's end and the re-announcement's start are one event,
        so the three intervals share two endpoints. Published so a reader does
        not have to add two rounded numbers, never as a third measurement.
        '''
        recorder = self.recorder()
        self.a_burst(recorder, 1, 101.0, 103.0, 106.0)
        measured = churn_metrics(recorder.events)['bursts'][0]
        assert measured['burst_s'] == \
            measured['withdraw_s'] + measured['reannounce_s'] == 5.0

    def test_the_operation_counts_come_from_the_events(self):
        recorder = self.recorder()
        self.a_burst(recorder, 1, 101.0, 103.0, 106.0)
        measured = churn_metrics(recorder.events)
        assert measured['requested_bursts'] == 2
        assert measured['offered_withdrawals'] == 50
        assert measured['distinct_withdrawals'] == 10
        assert measured['completed_bursts'] == 1

    def test_an_unfinished_burst_keeps_what_it_measured(self):
        '''A sequence cut short has to read as a sequence cut short. Dropping
        the burst would leave a document holding one burst of three with
        nothing saying three were asked for.
        '''
        recorder = self.recorder()
        self.a_burst(recorder, 1, 101.0, 103.0, 106.0)
        recorder.observe(107.0, 1000)
        recorder.note_burst_started(2)
        recorder.observe(109.0, 990)
        recorder.note_withdraw_complete(2)
        bursts = churn_metrics(recorder.events)['bursts']
        assert bursts[1]['complete'] is False
        assert bursts[1]['withdraw_s'] == 2.0
        assert bursts[1]['reannounce_s'] is None
        assert bursts[1]['burst_s'] is None
        assert churn_metrics(recorder.events)['completed_bursts'] == 1

    def test_each_interval_carries_the_resolution_of_its_bounding_polls(self):
        recorder = self.recorder()
        self.a_burst(recorder, 1, 101.0, 103.0, 106.0)
        measured = churn_metrics(recorder.events)['bursts'][0]
        assert measured['withdraw_resolution_s'] == 2.0
        assert measured['reannounce_resolution_s'] == 3.0

    def test_the_first_sample_is_measured_from_convergence(self):
        '''Not from the bench clock origin. The monitor has been polling all
        along, so the gap before the first churn sample is one poll -- taking
        the run origin would publish the whole convergence time as the
        resolution of burst 1.
        '''
        recorder = self.recorder()
        recorder.observe(101.0, 1000)
        recorder.note_burst_started(1)
        assert recorder.events[0].details['poll_resolution_s'] == 1.0

    def test_the_requested_cadence_is_a_floor_on_the_resolution(self):
        recorder = self.recorder(sample_interval_s=5.0)
        recorder.observe(101.0, 1000)
        recorder.note_burst_started(1)
        assert recorder.events[0].details['poll_resolution_s'] == 5.0

    def test_an_event_before_any_sample_is_refused(self):
        recorder = self.recorder()
        with pytest.raises(MeasurementEventError):
            recorder.note_burst_started(1)

    def test_two_open_bursts_are_refused(self):
        recorder = self.recorder()
        recorder.observe(101.0, 1000)
        recorder.note_burst_started(1)
        with pytest.raises(MeasurementEventError):
            recorder.note_burst_started(2)

    def test_a_completion_without_a_withdrawal_is_refused(self):
        recorder = self.recorder()
        recorder.observe(101.0, 1000)
        recorder.note_burst_started(1)
        with pytest.raises(MeasurementEventError):
            recorder.note_burst_complete(1)

    def test_samples_must_be_monotonic(self):
        recorder = self.recorder()
        recorder.observe(102.0, 1000)
        with pytest.raises(measurements.EventOrderError):
            recorder.observe(101.0, 1000)

    def test_a_sample_before_convergence_is_refused(self):
        recorder = self.recorder()
        with pytest.raises(measurements.EventOrderError):
            recorder.observe(99.0, 1000)

    def test_no_events_is_no_bursts_rather_than_a_crash(self):
        assert churn_metrics([]) == {
            'requested_bursts': None, 'completed_bursts': 0,
            'offered_withdrawals': None, 'distinct_withdrawals': None,
            'bursts': []}


class TestTheArtifactSection:
    def events(self):
        recorder = ChurnEventRecorder(
            100.0, producer='m', sample_interval_s=1.0, requested_bursts=1,
            offered_withdrawals=20, distinct_withdrawals=10)
        recorder.observe(101.0, 1000)
        recorder.note_burst_started(1)
        recorder.observe(102.0, 990)
        recorder.note_withdraw_complete(1)
        recorder.observe(104.0, 1000)
        recorder.note_burst_complete(1)
        return recorder.events

    def test_a_run_with_no_churn_has_no_churn_section(self):
        '''Every document produced by every command line that predates this
        flag is unchanged.
        '''
        doc = event_artifact([], 'converged')
        assert 'churn' not in doc

    def test_churn_events_produce_the_section(self):
        doc = event_artifact(self.events(), 'converged')
        assert doc['churn']['completed_bursts'] == 1
        assert doc['churn']['bursts'][0]['withdraw_s'] == 1.0

    def test_evidence_alone_produces_the_section(self):
        '''A sequence refused before its first burst has nothing in the event
        stream, and a document with no churn section would read as a run that
        never asked for any.
        '''
        doc = event_artifact([], 'converged', churn={
            'sequence_complete': False, 'incomplete_reason': 'no generator'})
        assert doc['churn']['incomplete_reason'] == 'no generator'
        assert doc['churn']['bursts'] == []

    def test_evidence_may_not_overwrite_a_derived_field(self):
        with pytest.raises(MeasurementEventError):
            event_artifact(self.events(), 'converged',
                           churn={'completed_bursts': 99})


class TestResolvingTheWorkload:
    def resolve(self, **kwargs):
        options = dict(churn_prefixes=None, churn_bursts=None, neighbor_num=10,
                       prefix_num=1000, tester_type='bird', filter_test=None)
        options.update(kwargs)
        return bgperf2.resolve_churn(**options)

    def test_absent_is_no_churn(self):
        assert self.resolve() == (0, 1)

    def test_a_block_and_a_count_pass_through(self):
        assert self.resolve(churn_prefixes=100, churn_bursts=3) == (100, 3)

    def test_a_block_defaults_to_one_burst(self):
        assert self.resolve(churn_prefixes=100) == (100, 1)

    def test_a_burst_count_with_nothing_to_churn_is_refused(self):
        '''It reads as a run that will do five bursts and does none.'''
        with pytest.raises(ValueError) as e:
            self.resolve(churn_bursts=5)
        assert '--churn-prefixes' in str(e.value)

    def test_a_block_larger_than_a_peer_announces_is_refused(self):
        with pytest.raises(ValueError) as e:
            self.resolve(churn_prefixes=1001)
        assert '1001' in str(e.value) and '1000' in str(e.value)

    def test_the_whole_per_peer_table_may_be_churned(self):
        assert self.resolve(churn_prefixes=1000) == (1000, 1)

    @pytest.mark.parametrize('generator', ['exa', 'gobgp', 'bgpdump2'])
    def test_only_the_bird_generator_can_churn(self, generator):
        '''The block is switched with that generator's own `birdc disable` on
        a static protocol bgperf2 wrote. Accepting another would start a
        sequence whose withdrawals nobody performs.
        '''
        with pytest.raises(ValueError) as e:
            self.resolve(churn_prefixes=10, tester_type=generator)
        assert generator in str(e.value)

    def test_a_policy_filter_is_refused(self):
        '''A burst completes when the count has fallen by the whole block, and
        a policy that drops part of that block makes that unreachable -- so a
        correctly filtered run would be published as a failed one.
        '''
        with pytest.raises(ValueError) as e:
            self.resolve(churn_prefixes=10, filter_test='transit')
        assert 'transit' in str(e.value)

    @pytest.mark.parametrize('value', [0, -1, 1.5, True, '10'])
    def test_a_block_that_is_not_a_count_is_refused(self, value):
        if value == 0:
            # Zero is the default rather than an error: it is no churn.
            assert self.resolve(churn_prefixes=0) == (0, 1)
            return
        with pytest.raises(ValueError):
            self.resolve(churn_prefixes=value)

    @pytest.mark.parametrize('value', [0, -1, 1.5, True, '3'])
    def test_a_burst_count_that_is_not_a_count_is_refused(self, value):
        with pytest.raises(ValueError):
            self.resolve(churn_prefixes=10, churn_bursts=value)

    def test_path_diversity_is_not_refused(self):
        '''Deliberately: competing paths is the case churn is most interesting
        for, and the accounting composes -- the monitor sees groups * C.
        '''
        assert self.resolve(churn_prefixes=10) == (10, 1)


class TestTheGeneratedScenario:
    def test_no_churn_leaves_the_scenario_alone(self):
        conf = scenario()
        assert all('churn-prefixes' not in n
                   for n in conf['testers'][0]['neighbors'].values())

    def test_the_default_renders_what_it_always_rendered(self):
        '''Byte-identical, not merely equivalent: an operator diffing a
        generated scenario against an older run's must see nothing.
        '''
        assert bgperf2.gen_conf(conf_args()) == \
            bgperf2.gen_conf(conf_args(churn_prefixes=0, churn_bursts=1))

    def test_every_peer_carries_the_block(self):
        conf = scenario(churn_prefixes=2)
        blocks = [n['churn-prefixes']
                  for n in conf['testers'][0]['neighbors'].values()]
        assert blocks == [2, 2, 2]

    def test_the_monitor_check_point_does_not_move(self):
        '''Churn happens after convergence, so it changes nothing the run
        converges against.
        '''
        assert scenario(churn_prefixes=2)['monitor']['check-points'] == \
            scenario()['monitor']['check-points']


class TestTheGeneratorConfig:
    def write(self, tmp_path, churn_prefixes):
        t = tester_mod.BIRDTester.__new__(tester_mod.BIRDTester)
        t.host_dir = str(tmp_path)
        t.guest_dir = '/root/config'
        t.dev = 'eth1'
        neighbor = {'as': 1003, 'router-id': '10.10.0.3',
                    'local-address': '10.10.0.3',
                    'paths': ['1.0.0.1/32', '1.0.0.2/32', '1.0.0.3/32']}
        if churn_prefixes:
            neighbor['churn-prefixes'] = churn_prefixes
        t.conf = {'neighbors': {'10.10.0.3': neighbor}}
        t.configure_neighbors({'local-address': '10.10.255.254', 'as': 1000})
        return (tmp_path / '10.10.0.3.conf').read_text()

    def test_no_churn_writes_the_config_it_always_wrote(self, tmp_path):
        assert 'protocol static churn' not in self.write(tmp_path, 0)

    def test_the_block_goes_into_a_protocol_of_its_own(self, tmp_path):
        config = self.write(tmp_path, 1)
        stable, _, churning = config.partition('protocol static churn')
        assert '1.0.0.1/32' in stable and '1.0.0.2/32' in stable
        assert '1.0.0.3/32' not in stable
        assert '1.0.0.3/32' in churning

    def test_one_exec_switches_the_whole_fleet(self, tmp_path):
        '''An exec is ~50ms: issued peer by peer at 50 peers the fleet would
        withdraw in a staircase and the interval measured would be that
        staircase rather than the target's reaction to it.
        '''
        t = tester_mod.BIRDTester.__new__(tester_mod.BIRDTester)
        t.guest_dir = '/root/config'
        t.conf = {'neighbors': {
            'a': {'router-id': 'a', 'churn-prefixes': 2},
            'b': {'router-id': 'b', 'churn-prefixes': 2}}}
        cmd = t.churn_command('disable')
        assert cmd[:2] == ['sh', '-c']
        assert cmd[2].count('birdc') == 2
        assert "'disable churn'" in cmd[2]

    def test_a_peer_with_no_block_is_not_asked(self):
        '''It has no `churn` protocol, so birdc would answer `syntax error` --
        correctly reported as a burst that was not issued.
        '''
        t = tester_mod.BIRDTester.__new__(tester_mod.BIRDTester)
        t.guest_dir = '/root/config'
        t.conf = {'neighbors': {'a': {'router-id': 'a'}}}
        assert t.churn_command('disable')[2] == ''
        assert t.churn('disable') == {}


class TestReadingTheReply:
    def test_the_success_wording_is_exact(self):
        assert churn_reply_ok('churn: disabled', 'disable')
        assert churn_reply_ok('BIRD 3.3.2 ready.\nchurn: enabled', 'enable')

    def test_already_disabled_is_not_success(self):
        '''The sequence alternates, so reaching a `disable` on an already
        disabled protocol means the previous `enable` was lost. Counting it
        would measure a burst that did not happen.
        '''
        assert not churn_reply_ok('churn: already disabled', 'disable')

    def test_an_unknown_protocol_is_not_success(self):
        assert not churn_reply_ok(
            'syntax error, unexpected CF_SYM_UNDEFINED', 'disable')

    def test_a_session_that_did_not_answer_is_named(self):
        '''Keyed by the sessions asked about, not by the sections that came
        back: the peers that did reply must not satisfy "the burst was issued"
        on their own.
        '''
        text = '===bgperf-session a\nchurn: disabled\n'
        assert churn_failures(text, ['a', 'b'], 'disable') == {'b': 'no reply'}

    def test_a_session_that_refused_carries_its_reply(self):
        text = ('===bgperf-session a\nchurn: disabled\n'
                '===bgperf-session b\nsyntax error, unexpected X\n')
        failures = churn_failures(text, ['a', 'b'], 'disable')
        assert 'syntax error' in failures['b']

    def test_every_session_answering_is_no_failure(self):
        text = ('===bgperf-session a\nchurn: enabled\n'
                '===bgperf-session b\nchurn: enabled\n')
        assert churn_failures(text, ['a', 'b'], 'enable') == {}


class FakeGenerator:
    name = 'bgperf_bird_tester'
    SUPPORTS_CHURN = True

    def __init__(self, failures=None, raises=None):
        self.actions = []
        self._failures = failures or {}
        self._raises = raises

    def churn(self, action):
        self.actions.append(action)
        if self._raises:
            raise self._raises
        return dict(self._failures)


def monitor_sample(accepted, monotonic_s):
    return {'who': 'bgperf_monitor', 'monotonic_s': monotonic_s,
            'checked': False,
            'afi_safis': [{'state': {'accepted': accepted}}]}


class TestDrivingTheSequence:
    def run(self, samples, generator, bursts=1, baseline=100, distinct=10,
            noise=()):
        q = Queue()
        for item in noise:
            q.put(item)
        for index, accepted in enumerate(samples):
            q.put(monitor_sample(accepted, 100.0 + index))
        recorder = ChurnEventRecorder(
            99.0, producer='bgperf_monitor', sample_interval_s=1.0,
            requested_bursts=bursts, offered_withdrawals=distinct,
            distinct_withdrawals=distinct)
        tracker = ChurnBurstTracker(bursts, baseline, distinct)
        return bgperf2.run_churn_bursts(
            q, 'bgperf_monitor', recorder, tracker, [generator])

    def test_a_burst_is_issued_and_completes(self):
        generator = FakeGenerator()
        events, evidence = self.run([100, 90, 100], generator)
        assert generator.actions == ['disable', 'enable']
        assert evidence == {'sequence_complete': True, 'incomplete_reason': None}
        assert churn_metrics(events)['completed_bursts'] == 1

    def test_other_producers_are_drained_and_change_nothing(self):
        '''The target's stats and the host samplers keep filling this queue.
        They are dropped rather than folded into the row: `elapsed (s)`,
        `max cpu %` and `min free mem (GB)` describe the delivery of the
        table, and a churn peak in them would make a churn run's row mean
        something different while looking identical.
        '''
        generator = FakeGenerator()
        noise = [{'who': 'bgperf_bird_target', 'cpu': 99.0, 'mem': 1},
                 {'who': 'controller', 'free': 1}]
        events, evidence = self.run([100, 90, 100], generator, noise=noise)
        assert evidence['sequence_complete'] is True

    def test_a_command_no_session_carried_out_ends_the_sequence(self):
        '''At the moment it was issued. A burst nobody performed otherwise has
        no symptom but the count not moving, which arrives CHURN_STALL_SAMPLES
        later and reads as a stuck target.
        '''
        generator = FakeGenerator(failures={'10.10.0.3': 'syntax error'})
        events, evidence = self.run([100, 90, 100], generator)
        assert evidence['sequence_complete'] is False
        assert '10.10.0.3' in evidence['incomplete_reason']
        assert generator.actions == ['disable']

    def test_an_exec_that_raises_does_not_end_the_run(self):
        '''The run has already converged and that measurement is on disk-bound
        evidence a lost churn sequence must not take with it.
        '''
        generator = FakeGenerator(raises=RuntimeError('no such container'))
        events, evidence = self.run([100, 90, 100], generator)
        assert evidence['sequence_complete'] is False
        assert 'no such container' in evidence['incomplete_reason']

    def test_a_stall_is_reported_with_its_partial_evidence(self):
        generator = FakeGenerator()
        q = Queue()
        for index in range(6):
            q.put(monitor_sample(100, 100.0 + index))
        recorder = ChurnEventRecorder(
            99.0, producer='bgperf_monitor', sample_interval_s=1.0,
            requested_bursts=1, offered_withdrawals=10, distinct_withdrawals=10)
        tracker = ChurnBurstTracker(1, 100, 10, stall_samples=2)
        events, evidence = bgperf2.run_churn_bursts(
            q, 'bgperf_monitor', recorder, tracker, [generator])
        assert evidence['sequence_complete'] is False
        assert 'stalled' in evidence['incomplete_reason']
        assert churn_metrics(events)['bursts'][0]['complete'] is False

    def test_the_failure_message_names_a_bounded_number_of_sessions(self):
        '''It reaches the CSV's MSG column, which is one unquoted field in a
        joined row. The count is always stated, so a truncated list cannot
        make a wide failure look narrow.
        '''
        generator = FakeGenerator(
            failures={'peer{0}'.format(i): 'syntax error' for i in range(50)})
        _, evidence = self.run([100, 90, 100], generator)
        reason = evidence['incomplete_reason']
        assert '50 session(s)' in reason
        assert 'and 47 more' in reason


class TestReportingTheBursts:
    def a_section(self, **overrides):
        section = {
            'requested_bursts': 1, 'completed_bursts': 1,
            'offered_withdrawals': 20, 'distinct_withdrawals': 10,
            'sequence_complete': True, 'incomplete_reason': None,
            'bursts': [{'burst': 1, 'complete': True, 'withdraw_s': 3.0,
                        'withdraw_resolution_s': 1.0, 'reannounce_s': 5.0,
                        'reannounce_resolution_s': 1.0, 'burst_s': 8.0,
                        'burst_resolution_s': 1.0}],
        }
        section.update(overrides)
        return section

    def test_no_churn_prints_nothing(self):
        assert bgperf2.describe_churn_metrics(None) == []

    def test_both_halves_are_named(self):
        line = bgperf2.describe_churn_metrics(self.a_section())[0]
        assert 'in 3.0s' in line and 'in 5.0s' in line

    def test_an_interval_of_one_poll_is_not_a_duration(self):
        '''A burst is issued just after a sample and can only be seen at the
        next, so one poll is an upper bound. Printing it as `1.0s` publishes
        the monitor's cadence as the daemon's reaction time, on a run where a
        faster daemon would print the same number.
        '''
        section = self.a_section(bursts=[dict(
            self.a_section()['bursts'][0], withdraw_s=1.0,
            withdraw_resolution_s=1.0)])
        assert 'within the 1.0s poll resolution' in \
            bgperf2.describe_churn_metrics(section)[0]

    def test_an_unfinished_burst_says_so(self):
        section = self.a_section(
            completed_bursts=0, sequence_complete=False,
            incomplete_reason='churn burst 1/1 stalled',
            bursts=[dict(self.a_section()['bursts'][0], complete=False,
                         reannounce_s=None, burst_s=None)])
        lines = bgperf2.describe_churn_metrics(section)
        assert 'not completed' in lines[0]
        assert 'stalled' in lines[-1]

    def test_an_incomplete_sequence_is_always_named(self):
        '''The run is published as converged -- it did converge -- so this is
        the only place the printed output says the second workload did not run.
        '''
        section = self.a_section(sequence_complete=False,
                                 incomplete_reason='no generator can churn')
        assert any('no generator can churn' in line
                   for line in bgperf2.describe_churn_metrics(section))

    def test_the_workload_is_described_before_the_run(self):
        described = bgperf2.describe_churn_workload(5, 2, 10, 2)
        assert '2 burst(s)' in described
        assert '50 path(s)' in described
        assert '10 distinct prefix(es)' in described

    def test_no_churn_is_described_as_nothing(self):
        assert bgperf2.describe_churn_workload(0, 1, 10, 10) is None


class TestTheRowCannotBeShifted:
    '''A churn failure quotes birdc's own reply, and rows are joined with no
    quoting -- so a comma in `MSG` is extra fields and every column after it,
    `filters` through the three provenance columns, moves for every reader.
    '''

    def test_a_comma_in_a_message_cannot_add_a_field(self):
        assert bgperf2.row_message(
            'syntax error, unexpected CF_SYM_UNDEFINED, expecting X') == \
            'syntax error; unexpected CF_SYM_UNDEFINED; expecting X'

    def test_a_newline_in_a_message_cannot_add_a_row(self):
        assert bgperf2.row_message('one\ntwo') == 'one two'

    def test_no_message_is_an_empty_cell(self):
        assert bgperf2.row_message(None) == ''

    def test_the_row_keeps_its_width_through_a_churn_failure(self, bench_args,
                                                             bench_stats):
        bench_stats['fail_msg'] = (
            "churn disable was not carried out by 1 session(s): t 10.0.0.3: "
            'syntax error, unexpected CF_SYM_UNDEFINED, expecting X')
        header = [name.strip() for name in bgperf2.stats_header().split(',')]
        row = bgperf2.create_output_stats(bench_args, 'v', bench_stats)
        assert len(row) == len(header)
        assert ',' not in str(row[header.index('MSG')])
        assert 'syntax error; unexpected' in str(row[header.index('MSG')])


class TestNamingTheRun:
    def stem(self, **overrides):
        args = Namespace(target='bird', label=None, version=None,
                         tester_type='bird', prefix_num=100, neighbor_num=10,
                         filter_test=None, path_diversity=1, receivers=0,
                         churn_prefixes=0, churn_bursts=1)
        for name, value in overrides.items():
            setattr(args, name, value)
        return bgperf2.bench_output_prefix(args)

    def test_no_churn_keeps_the_name_it_always_had(self):
        assert self.stem() == 'bird_bird_100_10'

    def test_the_block_and_the_count_are_both_in_the_stem(self):
        '''Nothing else in the stem moves with either: two tests differing only
        in how much they withdraw, or in how many times, would write every
        per-run artifact over each other -- the `filter_test` failure.
        '''
        assert self.stem(churn_prefixes=4, churn_bursts=2) == \
            'bird_bird_100_10_ch4x2'

    def test_the_burst_count_alone_does_not_rename_a_run(self):
        assert self.stem(churn_bursts=3) == 'bird_bird_100_10'


class TestTheBatchPath:
    def test_a_cell_carries_the_workload(self):
        cells = bgperf2.expand_batch_cells(
            a_test(churn_prefixes=50, churn_bursts=3), [{'name': 'bird'}])
        assert cells[0]['churn_prefixes'] == 50
        assert cells[0]['churn_bursts'] == 3

    def test_a_cell_defaults_to_no_churn(self):
        cells = bgperf2.expand_batch_cells(a_test(), [{'name': 'bird'}])
        assert cells[0]['churn_prefixes'] == 0
        assert cells[0]['churn_bursts'] == 1

    def test_the_default_cell_id_keeps_its_shape(self):
        '''An in-flight batch written by an older build resumes instead of
        costing the operator every completed cell.
        '''
        cell = bgperf2.expand_batch_cells(a_test(), [{'name': 'bird'}])[0]
        assert 'churn' not in bgperf2.batch_cell_id('t', cell)

    def test_a_churn_cell_id_carries_both_keys(self):
        cell = bgperf2.expand_batch_cells(
            a_test(churn_prefixes=50, churn_bursts=3), [{'name': 'bird'}])[0]
        identity = bgperf2.batch_cell_id('t', cell)
        assert '"churn_prefixes":50' in identity
        assert '"churn_bursts":3' in identity

    def test_the_description_names_the_workload(self):
        cell = bgperf2.expand_batch_cells(
            a_test(churn_prefixes=50, churn_bursts=3), [{'name': 'bird'}])[0]
        assert 'churn=50x3' in bgperf2.batch_cell_description(cell)

    def test_the_description_is_unchanged_without_churn(self):
        cell = bgperf2.expand_batch_cells(a_test(), [{'name': 'bird'}])[0]
        assert 'churn' not in bgperf2.batch_cell_description(cell)

    def test_a_test_key_written_under_a_target_is_refused(self):
        with pytest.raises(SystemExit) as e:
            bgperf2.check_batch_test(
                a_test(targets=[{'name': 'bird', 'churn_prefixes': 10}]))
        assert 'churn_prefixes' in str(e.value)

    def test_an_oversize_block_is_refused_before_the_first_container(self):
        with pytest.raises(SystemExit) as e:
            bgperf2.check_batch_test(a_test(churn_prefixes=1001))
        assert '1001' in str(e.value)

    def test_every_prefix_count_on_the_axis_is_checked(self):
        '''Not just the first: a block that fits one entry and not the next is
        easy to write, and finding that out at cell three is hours lost.
        '''
        with pytest.raises(SystemExit):
            bgperf2.check_batch_test(
                a_test(prefixes=[1_000, 10], churn_prefixes=100))

    def test_every_filter_on_the_axis_is_checked(self):
        with pytest.raises(SystemExit) as e:
            bgperf2.check_batch_test(
                a_test(filter_test=['None', 'transit'], churn_prefixes=10))
        assert 'transit' in str(e.value)

    def test_every_generator_in_the_test_is_checked(self):
        with pytest.raises(SystemExit) as e:
            bgperf2.check_batch_test(a_test(
                churn_prefixes=10,
                targets=[{'name': 'bird'},
                         {'name': 'frr_c', 'tester_type': 'bgpdump2',
                          'mrt_file': '/x'}]))
        assert 'bgpdump2' in str(e.value)

    def test_a_scenario_target_is_refused(self):
        with pytest.raises(SystemExit) as e:
            bgperf2.check_batch_test(a_test(
                churn_prefixes=10,
                targets=[{'name': 'bird', 'file': 'scenario.yaml'}]))
        assert 'scenario file' in str(e.value)

    def test_a_repeat_target_is_refused(self):
        '''`-r` builds no tester objects, so there is nothing to issue a burst
        through and nothing rewrites the generator config the churn protocol
        lives in. Every cell would name a churn workload and withdraw nothing.
        '''
        with pytest.raises(SystemExit) as e:
            bgperf2.check_batch_test(a_test(
                churn_prefixes=10,
                targets=[{'name': 'bird', 'repeat': True}]))
        assert 'repeat' in str(e.value)

    def test_the_scope_is_applied_before_the_block_is_checked(self):
        '''`-n 10 -p 1000 --prefix-scope total` gives each peer 100 prefixes,
        so a block of 500 is larger than what a peer announces even though it
        is half the table.
        '''
        with pytest.raises(SystemExit) as e:
            bgperf2.check_batch_test(
                a_test(prefix_scope='total', churn_prefixes=500))
        assert '100' in str(e.value)

    def test_a_scenario_target_refuses_a_burst_count_too(self):
        '''The generator set is empty when every target names a file, so the
        combination loop below checks nothing -- this refusal is the only
        thing standing in front of it.
        '''
        with pytest.raises(SystemExit) as e:
            bgperf2.check_batch_test(a_test(
                churn_bursts=5,
                targets=[{'name': 'bird', 'file': 'scenario.yaml'}]))
        assert 'churn_bursts' in str(e.value)

    def test_a_repeat_target_refuses_a_whole_churn_workload(self):
        with pytest.raises(SystemExit) as e:
            bgperf2.check_batch_test(a_test(
                churn_prefixes=10, churn_bursts=5,
                targets=[{'name': 'bird', 'repeat': True}]))
        assert 'repeat' in str(e.value)

    def test_a_burst_count_beside_repeat_names_the_burst_count(self):
        '''Not the repeat. `churn_bursts: 5` with no block is a burst count
        with nothing to churn, and being sent to remove the repeat brings the
        operator back to the same fault -- the rule a typo'd `prefix_scope`
        beside a diversity already follows.
        '''
        with pytest.raises(SystemExit) as e:
            bgperf2.check_batch_test(a_test(
                churn_bursts=5, targets=[{'name': 'bird', 'repeat': True}]))
        assert 'nothing to churn' in str(e.value)

    def test_a_misspelt_key_is_refused(self):
        with pytest.raises(SystemExit):
            bgperf2.check_batch_test(a_test(churn_prefix=10))


class TestProvenance:
    def args(self, **overrides):
        args = Namespace(target='bird', label=None, version=None,
                         tester_type='bird', prefix_num=100, neighbor_num=10,
                         filter_test=None, path_diversity=1, receivers=0,
                         churn_prefixes=4, churn_bursts=2, repetition=None,
                         file=None, results_dir=None)
        for name, value in overrides.items():
            setattr(args, name, value)
        return args

    def test_the_manifest_records_the_workload(self, tmp_path):
        args = self.args(results_dir=str(tmp_path))
        bgperf2.write_provenance(args, {}, 'stem')
        doc = json.loads((tmp_path / 'stem.versions.json').read_text())
        assert doc['run']['churn_prefixes'] == 4
        assert doc['run']['churn_bursts'] == 2

    def test_a_scenario_run_records_null(self, tmp_path):
        '''Provenance never guesses: churn is refused under -f, so a 0 there
        would be an assertion about a workload bgperf2 did not build.
        '''
        args = self.args(results_dir=str(tmp_path), file='scenario.yaml',
                         churn_prefixes=0, churn_bursts=1)
        bgperf2.write_provenance(args, {}, 'stem')
        doc = json.loads((tmp_path / 'stem.versions.json').read_text())
        assert doc['run']['churn_prefixes'] is None
        assert doc['run']['churn_bursts'] is None

    def test_the_event_artifact_records_it_too(self, tmp_path):
        '''Both `run` blocks, for the reason recorded for path_diversity: this
        document is what findings.py reads, and the only other carrier is the
        `ch4x2` in the filename.
        '''
        args = self.args(results_dir=str(tmp_path))
        doc = bgperf2.write_event_artifact(args, [], 'stem', 'converged')
        assert doc['run']['churn_prefixes'] == 4
        assert doc['run']['churn_bursts'] == 2


class TestTheUnrunSequence:
    """A run that asked for bursts and issued none still says so.

    The fallback lives in `write_event_artifact()` rather than at the one call
    site that needs it, because that call site is inside `bench()`'s monitor
    loop where no Docker-free test can reach it -- so every test here drives
    the function that builds every run's document.
    """

    def args(self, **overrides):
        args = Namespace(target='bird', label=None, version=None,
                         tester_type='bird', prefix_num=100, neighbor_num=10,
                         filter_test=None, path_diversity=1, receivers=0,
                         churn_prefixes=4, churn_bursts=2, repetition=None,
                         file=None, results_dir=None)
        for name, value in overrides.items():
            setattr(args, name, value)
        return args

    def test_a_failed_run_still_says_it_asked_for_churn(self, tmp_path):
        '''An artifact with `run.churn_prefixes: 4` and no `churn` section
        reads as a run that asked for none -- the ambiguity the section is
        published from evidence alone to remove. Asserted through the function
        that builds every run's document, not through the helper: the one call
        site that needs this is inside `bench()`'s monitor loop, where no
        Docker-free test can reach it, so a fix written there is one an
        unrelated edit can undo with the suite still green.
        '''
        args = self.args(results_dir=str(tmp_path))
        doc = bgperf2.write_event_artifact(args, [], 'stem', 'failed')
        assert doc['churn']['sequence_complete'] is False
        assert 'did not converge' in doc['churn']['incomplete_reason']
        assert doc['run']['churn_prefixes'] == 4

    def test_a_converged_run_that_ran_no_burst_says_so_too(self, tmp_path):
        '''Any other path that reaches the artifact without a driven sequence
        -- there is none today, and this is what keeps one from being added in
        silence.
        '''
        args = self.args(results_dir=str(tmp_path))
        doc = bgperf2.write_event_artifact(args, [], 'stem', 'converged')
        assert doc['churn']['incomplete_reason'] == 'no churn burst was issued'

    def test_a_driven_sequence_is_never_replaced_by_the_fallback(self,
                                                                 tmp_path):
        args = self.args(results_dir=str(tmp_path))
        doc = bgperf2.write_event_artifact(
            args, [], 'stem', 'converged',
            churn={'sequence_complete': True, 'incomplete_reason': None})
        assert doc['churn']['sequence_complete'] is True

    def test_a_run_with_no_churn_has_no_section(self, tmp_path):
        args = self.args(results_dir=str(tmp_path), churn_prefixes=0,
                         churn_bursts=1)
        doc = bgperf2.write_event_artifact(args, [], 'stem', 'failed')
        assert 'churn' not in doc

    def test_an_unissued_sequence_is_not_printed_as_none(self, tmp_path):
        '''`0 of None burst(s) completed` is what reading an events-derived
        count that no event supplied produces.
        '''
        args = self.args(results_dir=str(tmp_path))
        doc = bgperf2.write_event_artifact(args, [], 'stem', 'failed')
        lines = bgperf2.describe_churn_metrics(doc['churn'])
        assert lines == ['churn: no burst was issued; the run did not '
                         'converge, so no churn burst was issued']


class TestGuardOrder:
    def test_the_guards_run_before_any_docker_call(self, monkeypatch):
        '''bench()'s argument guards are covered by a suite that deliberately
        needs no Docker daemon, so a Docker call above them makes that suite
        depend on machine state.
        '''
        order = []
        monkeypatch.setattr(bgperf2, 'target_image',
                            lambda *a, **k: order.append('docker') or 'img')
        monkeypatch.setattr(bgperf2, 'remove_target_containers',
                            lambda: order.append('docker'))
        monkeypatch.setattr(bgperf2, 'get_ctn_names',
                            lambda *a, **k: order.append('docker') or [])
        args = Namespace(dir='/tmp', bench_name='x', docker_network_name=None,
                         file=None, target='bird', version=None, image=None,
                         repeat=False, neighbor_num=10, prefix_num=100,
                         tester_type='bird', mrt_file=None, mrt_injector=None,
                         prefix_scope='per-peer', path_diversity=1,
                         receivers=0, churn_prefixes=101, churn_bursts=1,
                         filter_test=None)
        with pytest.raises(SystemExit) as e:
            bgperf2.bench(args)
        assert '101' in str(e.value)
        assert order == [], 'a Docker call ran before the churn guard'

    def test_a_scenario_run_refuses_a_burst_count_too(self):
        '''`resolve_churn()` runs only where a scenario is generated, so a
        refusal keyed on the block alone let `--churn-bursts 5` through: the
        run did no bursts and recorded `churn_bursts: null` in both manifests.
        '''
        args = Namespace(dir='/tmp', bench_name='x', docker_network_name=None,
                         file='scenario.yaml', target='bird', version=None,
                         image=None, repeat=False, neighbor_num=10,
                         prefix_num=100, tester_type='bird', mrt_file=None,
                         mrt_injector=None, prefix_scope='per-peer',
                         path_diversity=1, receivers=0, churn_prefixes=0,
                         churn_bursts=5, filter_test=None)
        with pytest.raises(SystemExit) as e:
            bgperf2.bench(args)
        assert '--churn-bursts' in str(e.value)

    def test_a_scenario_run_refuses_churn(self):
        args = Namespace(dir='/tmp', bench_name='x', docker_network_name=None,
                         file='scenario.yaml', target='bird', version=None,
                         image=None, repeat=False, neighbor_num=10,
                         prefix_num=100, tester_type='bird', mrt_file=None,
                         mrt_injector=None, prefix_scope='per-peer',
                         path_diversity=1, receivers=0, churn_prefixes=4,
                         churn_bursts=1, filter_test=None)
        with pytest.raises(SystemExit) as e:
            bgperf2.bench(args)
        assert '--churn-prefixes' in str(e.value)

    def test_repeat_refuses_churn(self, monkeypatch):
        monkeypatch.setattr(bgperf2, 'target_image',
                            lambda *a, **k: pytest.fail('resolved an image'))
        args = Namespace(dir='/tmp', bench_name='x', docker_network_name=None,
                         file=None, target='bird', version=None, image=None,
                         repeat=True, neighbor_num=10, prefix_num=100,
                         tester_type='bird', mrt_file=None, mrt_injector=None,
                         prefix_scope='per-peer', path_diversity=1,
                         receivers=0, churn_prefixes=4, churn_bursts=1,
                         filter_test=None)
        with pytest.raises(SystemExit) as e:
            bgperf2.bench(args)
        assert 'repeat' in str(e.value)
