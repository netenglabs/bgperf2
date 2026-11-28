'''The generated import policy on a `bench` run (policy phase 1, step 5).

No daemon is involved: these check the refusals, the scenario `gen_conf()`
renders, the target configs written from it, the checkpoints and the count
guard. Whether each daemon applies the policy is the live check's job.
'''
import json
import os
from argparse import Namespace

import pytest
import yaml
from mako.template import Template

import bgperf2
import bird
import frr
import import_policy as ip
import policy_render as pr
from test_tester_attributes import scenario_args as attribute_args


BOTH = ('prefix', 'as-path', 'community')


def scenario_args(**overrides):
    args = attribute_args(policy_rules=0, policy_match=None, policy_hit=None)
    for name, value in overrides.items():
        setattr(args, name, value)
    return args


def policy_args(rules=3, match='as-path', hit='last', **overrides):
    overrides.setdefault('tester_attributes', True)
    return scenario_args(policy_rules=rules, policy_match=match,
                         policy_hit=hit, **overrides)


def rendered(args):
    return yaml.safe_load(Template(bgperf2.gen_conf(args)).render())


def target_from(scenario, cls, tmp_path):
    target = cls.__new__(cls)
    target.host_dir = str(tmp_path)
    target.conf = scenario['target']
    target.scenario_global_conf = scenario
    target.write_config()
    return (tmp_path / cls.CONFIG_FILE_NAME).read_text()


class TestResolving:
    def resolve(self, rules=5, match='as-path', hit='first', **kwargs):
        kwargs.setdefault('target', 'bird')
        kwargs.setdefault('supported_matches', BOTH)
        return ip.resolve_import_policy(rules, match, hit, **kwargs)

    def test_no_rules_is_no_policy(self):
        assert ip.resolve_import_policy(0) == (0, None, None)
        assert ip.resolve_import_policy(None) == (0, None, None)

    def test_a_policy_is_its_three_dimensions(self):
        assert self.resolve(peers=2, prefixes=8) == (5, 'as-path', 'first')

    @pytest.mark.parametrize('match, hit', [(None, 'first'), ('prefix', None),
                                            (None, None)])
    def test_neither_dimension_has_a_default(self, match, hit):
        with pytest.raises(ip.ImportPolicyConfigurationError,
                           match='neither has a default'):
            self.resolve(match=match, hit=hit)

    @pytest.mark.parametrize('match, hit, named', [
        ('prefix', None, '--policy-match has'),
        (None, 'miss', '--policy-hit has'),
        ('prefix', 'miss', '--policy-match and --policy-hit have')])
    def test_a_dimension_without_rules_is_refused(self, match, hit, named):
        with pytest.raises(ip.ImportPolicyConfigurationError, match=named):
            ip.resolve_import_policy(0, match, hit)

    @pytest.mark.parametrize('rules', [-1, ip.MAX_POLICY_RULES + 1, 2.5,
                                       True, '5'])
    def test_the_rule_count_is_a_whole_number_in_range(self, rules):
        with pytest.raises(ip.ImportPolicyConfigurationError,
                           match='--policy-rules'):
            self.resolve(rules=rules)

    def test_a_target_without_a_renderer_is_refused(self):
        with pytest.raises(ip.ImportPolicyConfigurationError,
                           match="'openbgp' target has no renderer"):
            self.resolve(target='openbgp', supported_matches=None)

    def test_a_match_type_the_target_does_not_render_is_refused(self):
        with pytest.raises(ip.ImportPolicyConfigurationError,
                           match='it renders prefix'):
            self.resolve(supported_matches=('prefix',))

    @pytest.mark.parametrize('kwargs, message', [
        ({'receivers': 1}, '--receivers'),
        ({'tester_type': 'exa'}, 'BIRD generator'),
        ({'tester_type': 'bgpdump2'}, 'BIRD generator'),
        ({'path_diversity': 2}, '--path-diversity'),
        ({'churn_prefixes': 2}, '--churn-prefixes'),
        ({'filter_test': 'transit'}, '--filter_test'),
        ({'policy_reload_blocks': 1}, '--policy-reload-blocks'),
        ({'scenario_filters': ('-a/--as-path-list-num',)}, '-a/--as-path'),
        ({'peers': 2, 'prefixes': 3}, 'at least 4 prefixes'),
        ({'target_config_file': 'my.conf'}, '--target_config_file'),
    ])
    def test_every_refusal_names_its_flag(self, kwargs, message):
        with pytest.raises(ip.ImportPolicyConfigurationError, match=message):
            self.resolve(**kwargs)

    def test_the_attributes_refusals_say_the_policy_turned_them_on(self):
        with pytest.raises(ip.ImportPolicyConfigurationError,
                           match='--policy-rules turns on --tester-attributes'):
            self.resolve(path_diversity=2)

    def test_a_hand_written_target_config_is_refused_from_the_args(self):
        # The target would run that file and never render the policy.
        args = policy_args(target='bird', target_config_file='my.conf')
        with pytest.raises(ip.ImportPolicyConfigurationError,
                           match='--target_config_file'):
            bgperf2.resolve_import_policy_args(args)

    def test_bird_and_frr_render_every_match_type(self):
        for target in ('bird', 'frr_c'):
            assert bgperf2.target_policy_matches(target) == ip.POLICY_MATCHES

    @pytest.mark.parametrize('target', ['openbgp', 'rustybgp', 'holo',
                                        'no-such-target'])
    def test_other_targets_render_none(self, target):
        assert bgperf2.target_policy_matches(target) is None


class TestTheScenario:
    def test_without_a_policy_nothing_changes(self):
        assert bgperf2.gen_conf(attribute_args()) == bgperf2.gen_conf(
            scenario_args())
        assert ip.SCENARIO_KEY not in rendered(scenario_args())['target']

    @pytest.mark.parametrize('length', [32, 24])
    def test_the_target_carries_the_policys_arguments(self, length):
        conf = rendered(policy_args(rules=7, match='prefix', hit='miss',
                                    neighbor_num=3, prefix_num=10,
                                    prefix_length=length))
        spec = conf['target'][ip.SCENARIO_KEY]
        assert spec == {'rules': 7, 'match': 'prefix', 'hit': 'miss',
                        'peers': 3, 'prefixes': 10, 'prefix-length': length,
                        'exclude': [] if length == 32 else [PEERING]}

    @pytest.mark.parametrize('length', [32, 24])
    def test_the_rebuilt_prefix_policy_names_the_walks_addresses(self, length):
        '''The policy the target rebuilds must be the one the model built
        against the walk the generator was given.'''
        args = policy_args(match='prefix', hit='first', neighbor_num=3,
                           prefix_num=10, prefix_length=length)
        spec = rendered(args)['target'][ip.SCENARIO_KEY]
        assert ip.policy_from_scenario(spec) == ip.build_policy(
            3, 'prefix', 'first', 3, 10, length,
            () if length == 32 else (PEERING,))

    def test_every_checkpoint_is_the_expected_count(self):
        conf = rendered(policy_args(neighbor_num=3, prefix_num=10))
        expected = ip.expected_counts(3, 3, 10)
        # Exact, without the 0.99 allowance a run with no policy has.
        assert conf['monitor']['check-points'] == [expected.accepted] == [24]
        for n in conf['testers'][0]['neighbors'].values():
            assert n['check-points'] == expected.accepted_per_peer[0] == 8
            assert n['offered-check-point'] == 10

    def test_the_generator_carries_the_blocks(self):
        for n in rendered(policy_args())['testers'][0]['neighbors'].values():
            assert n['policy-blocks']

    def test_an_unresolved_policy_is_refused(self):
        with pytest.raises(ValueError, match='generator attributes'):
            bgperf2.gen_conf(policy_args(tester_attributes=False))

    @pytest.mark.parametrize('spec', [
        {'rules': 1},
        dict(ip.scenario_import_policy(1, 'as-path', 'first', 1, 4, 32),
             extra=1),
        'as-path'])
    def test_a_malformed_entry_is_refused(self, spec):
        with pytest.raises(ip.ImportPolicyConfigurationError,
                           match='must hold exactly'):
            ip.policy_from_scenario(spec)


PEERING = '10.10.0.0/16'


class TestTheTargetConfigs:
    @pytest.mark.parametrize('match', BOTH)
    def test_bird_imports_through_the_rendered_filter(self, tmp_path, match):
        args = policy_args(match=match)
        text = target_from(rendered(args), bird.BIRDTarget, tmp_path)
        policy = ip.policy_from_scenario(
            rendered(args)['target'][ip.SCENARIO_KEY])
        assert pr.render_bird_policy(policy) in text
        assert 'import filter {0};'.format(pr.BIRD_FILTER_NAME) in text
        # Defined before the protocol that names it.
        assert text.index('filter ' + pr.BIRD_FILTER_NAME + '\n') < \
            text.index('protocol bgp everything')

    def test_bird_without_a_policy_imports_all(self, tmp_path):
        text = target_from(rendered(scenario_args()), bird.BIRDTarget,
                           tmp_path)
        assert 'import all;' in text
        assert pr.BIRD_FILTER_NAME not in text

    @pytest.mark.parametrize('match', BOTH)
    def test_frr_attaches_the_route_map_to_every_session(self, tmp_path,
                                                         match):
        args = policy_args(match=match, neighbor_num=3)
        scenario = rendered(args)
        text = target_from(scenario, frr.FRRoutingTarget, tmp_path)
        policy = ip.policy_from_scenario(scenario['target'][ip.SCENARIO_KEY])
        assert pr.render_frr_policy(policy) in text
        # Every list and the route-map exist before a session names them.
        assert text.index(pr.render_frr_policy(policy)) < \
            text.index('router bgp')
        attached = [line for line in text.splitlines()
                    if line.strip().endswith(
                        'route-map {0} in'.format(pr.FRR_ROUTE_MAP))]
        sessions = frr.FRRoutingTarget.scenario_neighbors(
            target_session(scenario), sort=False)
        assert len(attached) == len(sessions) == 4

    def test_frr_without_a_policy_is_unchanged(self, tmp_path):
        text = target_from(rendered(scenario_args()), frr.FRRoutingTarget,
                           tmp_path)
        assert text.startswith('hostname bgpd\npassword zebra\nrouter bgp')
        assert pr.FRR_ROUTE_MAP not in text

    def test_a_target_without_a_renderer_refuses_the_entry(self, tmp_path):
        import base

        class Plain(base.Target):
            pass

        target = Plain.__new__(Plain)
        target.conf = rendered(policy_args())['target']
        with pytest.raises(ValueError, match='no renderer'):
            target.import_policy()


def target_session(scenario):
    target = frr.FRRoutingTarget.__new__(frr.FRRoutingTarget)
    target.conf = scenario['target']
    target.scenario_global_conf = scenario
    return target


class TestTheReceivedGate:
    '''`received` is pre-policy, so a policy must not shorten what it is held
    to: three quarters of a peer's table is not all of it.'''

    def counts(self, received, accepted):
        scenario = rendered(policy_args(neighbor_num=1, prefix_num=8))
        target = target_session(scenario)
        rid = next(iter(scenario['testers'][0]['neighbors']))
        return target.classify_neighbor_counts({rid: received},
                                               {rid: accepted})

    def test_received_is_held_to_the_offered_count(self):
        full, checked = self.counts(received=6, accepted=6)
        assert list(full.values()) == [False]
        assert list(checked.values()) == [True]

    def test_the_whole_table_received_is_full(self):
        full, checked = self.counts(received=8, accepted=6)
        assert list(full.values()) == [True]
        assert list(checked.values()) == [True]

    def test_accepted_is_held_to_the_expected_count(self):
        _, checked = self.counts(received=8, accepted=5)
        assert list(checked.values()) == [False]

    def test_every_policy_target_reads_through_the_offered_count(self):
        # Under a policy `get_test_counts()` returns the accepted count; an
        # adapter comparing `received` with it directly (as flock and srlinux
        # do) would call a peer complete at three quarters of its table.
        import inspect
        import base
        for name, cls in bgperf2.TARGET_CLASSES.items():
            if not cls.IMPORT_POLICY_MATCHES:
                continue
            for klass in cls.__mro__:
                if klass in (base.Target, base.Container, object):
                    continue
                for attr, member in vars(klass).items():
                    if not inspect.isfunction(member):
                        continue
                    assert 'get_test_counts(' not in inspect.getsource(
                        member), '{0}: {1}.{2}'.format(
                            name, klass.__name__, attr)


class TestTheCountGuard:
    def test_no_policy_is_never_judged(self):
        assert ip.count_failure(0, 5, 10) is None

    def test_the_exact_count_passes(self):
        assert ip.count_failure(3, 24, 24) is None

    @pytest.mark.parametrize('received, sign', [(23, '-1'), (30, '+6')])
    def test_any_other_count_withholds_the_timing(self, received, sign):
        message = ip.count_failure(3, received, 24)
        assert 'timing withheld' in message
        assert '({0})'.format(sign) in message
        # It goes into a CSV cell, which `row_message()` would rewrite.
        assert bgperf2.row_message(message) == message.replace(',', ';')


class TestTheStatsRow:
    def row(self, args, size=None):
        import datetime
        stats = {'elapsed': datetime.timedelta(seconds=9),
                 'first_received_time': datetime.timedelta(seconds=2),
                 'required': 24, 'recved': 24, 'monitor_wait_time': 1,
                 'total_time': 12.0, 'max_cpu': 1, 'max_mem': 1 << 30,
                 'min_idle': 90, 'min_free': 1 << 33, 'cores': 4,
                 'memory': 1 << 34, 'tester_errors': 0,
                 'tester_timeouts': 0, 'policy_size': size}
        header = [f.strip() for f in bgperf2.stats_header().split(',')]
        row = bgperf2.create_output_stats(args, 'v', stats)
        assert len(row) == len(header)
        return dict(zip(header, row))

    def args(self, **overrides):
        args = TestNamingAndProvenance().args(**overrides)
        args.prefix_num, args.neighbor_num = 10, 3
        return args

    def test_a_policy_row_names_all_three_dimensions_and_its_size(self):
        named = self.row(self.args(policy_rules=7, policy_match='prefix',
                                   policy_hit='miss'),
                         size=pr.RenderedSize(rules=7, bytes=1234))
        assert (named['policy rules'], named['policy match'],
                named['policy hit'], named['policy bytes']) == \
            (7, 'prefix', 'miss', 1234)

    def test_its_baseline_row_reads_no_policy(self):
        named = self.row(self.args(tester_attributes=True))
        assert (named['policy rules'], named['policy match'],
                named['policy hit'], named['policy bytes']) == (0, '', '', '')

    def test_an_unmeasured_size_is_blank_not_zero(self):
        named = self.row(self.args(policy_rules=7, policy_match='prefix',
                                   policy_hit='miss'))
        assert named['policy bytes'] == ''

    def test_the_provenance_columns_stay_last(self):
        header = [f.strip() for f in bgperf2.stats_header().split(',')]
        assert header[-7:-3] == ['policy rules', 'policy match',
                                 'policy hit', 'policy bytes']

    @pytest.mark.parametrize('cls', [bird.BIRDTarget, frr.FRRoutingTarget])
    def test_the_target_records_what_it_wrote(self, tmp_path, cls):
        scenario = rendered(policy_args(rules=4, match='community'))
        target = cls.__new__(cls)
        target.host_dir = str(tmp_path)
        target.conf = scenario['target']
        target.scenario_global_conf = scenario
        target.write_config()
        policy = ip.policy_from_scenario(scenario['target'][ip.SCENARIO_KEY])
        render = (pr.render_bird_policy if cls is bird.BIRDTarget
                  else pr.render_frr_policy)
        assert target.import_policy_size == pr.RenderedSize(
            rules=4, bytes=len(render(policy).encode('utf-8')))

    def test_a_target_with_no_policy_records_none(self, tmp_path):
        target = bird.BIRDTarget.__new__(bird.BIRDTarget)
        target.host_dir = str(tmp_path)
        scenario = rendered(scenario_args())
        target.conf = scenario['target']
        target.scenario_global_conf = scenario
        target.write_config()
        assert target.import_policy_size is None


class TestTheEventArtifact:
    def test_withheld_timing_is_null_and_named(self):
        import measurements
        doc = measurements.event_artifact([], 'failed',
                                          timing_withheld_reason='short by 1')
        assert doc['measurements'] and all(
            value is None for value in doc['measurements'].values())
        assert doc['measurements_withheld_reason'] == 'short by 1'

    def test_an_ordinary_run_keeps_its_document(self):
        import measurements
        assert 'measurements_withheld_reason' not in \
            measurements.event_artifact([], 'converged')

    def test_the_findings_say_withheld_not_never_reached(self):
        # The nulled intervals must not read as a monitor that never got
        # there: an over-accepting policy went past the check-point.
        import findings
        import measurements
        doc = measurements.event_artifact(
            [], 'failed', timing_withheld_reason='over by 6')
        doc['tester_fleet'] = {'incomplete_testers': [], 'testers': 1,
                               'testers_complete': 1, 'complete_s': 1.0}
        result = findings.derive_findings(doc)
        names = [f['finding'] for f in result['findings']]
        assert 'timing_withheld' in names
        assert 'missing_timing_evidence' not in names
        assert result['limiting_component'] == findings.UNRESOLVED
        assert result['decided_by'] == 'timing_withheld'
        assert 'over by 6' in result['reason']

    def test_the_writer_passes_it_through(self, tmp_path):
        args = TestNamingAndProvenance().args(results_dir=str(tmp_path))
        bgperf2.write_event_artifact(args, [], 'run', 'failed',
                                     timing_withheld_reason='short by 1')
        with open(tmp_path / 'run.events.json') as f:
            assert json.load(f)['measurements_withheld_reason'] == 'short by 1'


class TestNamingAndProvenance:
    def args(self, **overrides):
        args = Namespace(monitor='gobgp', target='bird', label=None,
                         version=None, tester_type='bird', prefix_num=1_000,
                         neighbor_num=10, filter_test=None, file=None,
                         path_diversity=1)
        for name, value in overrides.items():
            setattr(args, name, value)
        return args

    def test_no_policy_keeps_its_stem(self):
        assert bgperf2.bench_output_prefix(self.args()) == 'bird_bird_1000_10'
        assert bgperf2.bench_output_prefix(self.args(policy_rules=0)) == \
            'bird_bird_1000_10'

    @pytest.mark.parametrize('match, hit, part', [
        ('as-path', 'last', 'po1000asplast'),
        ('prefix', 'first', 'po1000pfxfirst'),
        ('community', 'miss', 'po1000commiss')])
    def test_the_stem_carries_all_three(self, match, hit, part):
        assert bgperf2.bench_output_prefix(self.args(
            tester_attributes=True, policy_rules=1000, policy_match=match,
            policy_hit=hit)) == 'bird_bird_1000_10_ta_' + part

    @pytest.mark.parametrize('match, hit', [(None, 'last'), ('as-path', None),
                                            ('regex', 'last')])
    def test_an_unresolved_policy_has_no_name(self, match, hit):
        with pytest.raises(ValueError, match='--policy-match and --policy-hit'):
            bgperf2.bench_output_prefix(self.args(
                tester_attributes=True, policy_rules=10, policy_match=match,
                policy_hit=hit))

    def test_every_stem_is_distinct(self):
        stems = {bgperf2.bench_output_prefix(self.args(
            tester_attributes=True, policy_rules=n, policy_match=m,
            policy_hit=h)) for n in (1, 10) for m in BOTH
            for h in ip.POLICY_HITS}
        assert len(stems) == 2 * 3 * 3

    @pytest.mark.parametrize('writer', ['provenance', 'events'])
    def test_both_run_blocks_record_it(self, tmp_path, writer):
        policy = self.args(tester_attributes=True, policy_rules=5,
                           policy_match='community', policy_hit='first')
        for args, expected in (
                (policy, {'rules': 5, 'match': 'community', 'hit': 'first',
                          'expected_accepted': 7500,
                          'expected_accepted_per_peer': 750}),
                (self.args(), None),
                (self.args(policy_rules=0), None)):
            args.results_dir = str(tmp_path)
            if writer == 'provenance':
                path = bgperf2.write_provenance(args, {}, 'run')
            else:
                bgperf2.write_event_artifact(args, [], 'run', 'converged')
                path = tmp_path / 'run.events.json'
            with open(path) as f:
                assert json.load(f)['run']['import_policy'] == expected


class TestTheEntryPoints:
    def bench_args(self, **overrides):
        args = Namespace(dir='/tmp', bench_name='x', docker_network_name=None,
                         file=None, target='bird', version=None, image=None,
                         repeat=False, neighbor_num=10, prefix_num=100,
                         prefix_scope='per-peer', tester_type='bird',
                         mrt_file=None, mrt_injector=None, path_diversity=1,
                         local_address_prefix=PEERING, policy_rules=5,
                         policy_match='as-path', policy_hit='first')
        for name, value in overrides.items():
            setattr(args, name, value)
        return args

    def test_the_parser_defaults_to_no_policy(self):
        parser = bgperf2.create_args_parser(main=False)
        for command in ('bench', 'config'):
            args = parser.parse_args([command])
            assert (args.policy_rules, args.policy_match,
                    args.policy_hit) == (0, None, None)
        args = parser.parse_args(['bench', '--policy-rules', '9',
                                  '--policy-match', 'prefix',
                                  '--policy-hit', 'miss'])
        assert (args.policy_rules, args.policy_match,
                args.policy_hit) == (9, 'prefix', 'miss')

    @pytest.mark.parametrize('flag, value', [('--policy-match', 'regex'),
                                             ('--policy-hit', 'middle')])
    def test_the_parser_refuses_unknown_values(self, flag, value):
        with pytest.raises(SystemExit):
            bgperf2.create_args_parser(main=False).parse_args(
                ['bench', flag, value])

    @pytest.mark.parametrize('overrides, message', [
        ({'target': 'openbgp'}, 'no renderer'),
        ({'policy_match': None}, 'neither has a default'),
        ({'policy_rules': 0}, 'nothing to describe'),
        ({'tester_type': 'exa'}, 'BIRD generator'),
        ({'path_diversity': 2}, '--path-diversity'),
        ({'churn_prefixes': 5}, '--churn-prefixes'),
        ({'receivers': 2}, '--receivers'),
        ({'filter_test': 'transit'}, '--filter_test'),
        ({'policy_reload_blocks': 1}, '--policy-reload-blocks'),
        ({'as_path_list_num': 3}, '-a/--as-path-list-num'),
        ({'prefix_num': 3}, 'at least 4 prefixes'),
    ])
    def test_bench_refuses_what_resolving_refuses(self, overrides, message):
        with pytest.raises(SystemExit, match=message):
            bgperf2.bench(self.bench_args(**overrides))

    def test_bench_checks_the_fleet_after_the_scope(self):
        with pytest.raises(SystemExit, match='at least 4 prefixes'):
            bgperf2.bench(self.bench_args(prefix_num=30, prefix_scope='total'))

    def test_bench_refuses_it_under_repeat(self):
        with pytest.raises(SystemExit,
                           match='--policy-rules cannot be used with -r'):
            bgperf2.bench(self.bench_args(repeat=True))

    @pytest.mark.parametrize('overrides, named', [
        ({}, '--policy-rules, --policy-match, --policy-hit'),
        ({'policy_rules': 0, 'policy_match': None}, '--policy-hit')])
    def test_bench_refuses_it_under_a_scenario_file(self, overrides, named):
        with pytest.raises(SystemExit, match=named + ': a policy cannot'):
            bgperf2.bench(self.bench_args(file='scenario.yaml', **overrides))

    def test_bench_refuses_a_scenario_file_carrying_one(self, tmp_path,
                                                        monkeypatch):
        def torn_down():
            raise AssertionError('reached the teardown')
        monkeypatch.setattr(bgperf2, 'remove_target_containers', torn_down)
        scenario = tmp_path / 's.yaml'
        scenario.write_text(bgperf2.gen_conf(policy_args()))
        with pytest.raises(SystemExit, match="carries 'import-policy'"):
            bgperf2.bench(self.bench_args(
                file=str(scenario), policy_rules=0, policy_match=None,
                policy_hit=None))

    def test_a_stray_offered_check_point_is_refused(self):
        scenario = rendered(policy_args())
        del scenario['target'][ip.SCENARIO_KEY]
        with pytest.raises(ValueError, match="carries 'offered-check-point'"):
            bgperf2.check_scenario_import_policy(scenario)

    def test_a_plain_scenario_passes(self):
        bgperf2.check_scenario_import_policy(rendered(scenario_args()))

    def test_config_refuses_it(self):
        with pytest.raises(SystemExit, match='--policy-rules.*config writes'):
            bgperf2.config(self.bench_args(output='/dev/null'))

    def test_native_controlled_cells_refuse_it(self):
        import native_mrt
        args = Namespace(file=None, repeat=False, tester_type='bird',
                         monitor='sink', policy_rules=5, image=None,
                         generator_image=None, observer_image=None)
        with pytest.raises(ValueError, match='plain transit'):
            native_mrt.synthetic_spec(args)


def a_test(**overrides):
    test = {'name': 'policy', 'neighbors': [4], 'prefixes': [100],
            'filter_test': ['None'], 'targets': [{'name': 'bird'}]}
    test.update(overrides)
    return test


POLICY_AXES = {'policy_rules': [0, 10], 'policy_match': ['prefix', 'as-path'],
               'policy_hit': ['first', 'last']}


def policy_test(**overrides):
    return a_test(**dict(POLICY_AXES, **overrides))


def cells_of(test):
    bgperf2.check_batch_test(test)
    return bgperf2.expand_batch_cells(test, test['targets'])


class TestTheBatch:
    '''The policy as matrix axes (step 7).'''

    def test_a_test_without_the_keys_has_no_policy(self):
        [cell] = cells_of(a_test())
        args = bgperf2.batch_cell_args(Namespace(), cell)
        assert (args.policy_rules, args.policy_match,
                args.policy_hit) == (0, None, None)
        assert not args.tester_attributes
        assert 'policy_rules' not in cell

    def test_the_baseline_is_one_cell_and_every_point_is_another(self):
        cells = cells_of(policy_test())
        points = [(c.get('policy_rules', 0), c.get('policy_match'),
                   c.get('policy_hit')) for c in cells]
        assert points == [(0, None, None),
                          (10, 'prefix', 'first'), (10, 'prefix', 'last'),
                          (10, 'as-path', 'first'), (10, 'as-path', 'last')]
        assert [c['ordinal'] for c in cells] == list(range(5))
        # The baseline is the attributes-only run, so every cell has them.
        assert all(c['tester_attributes'] for c in cells)

    def test_a_cell_runs_its_own_point(self):
        cell = cells_of(policy_test())[4]
        args = bgperf2.batch_cell_args(Namespace(), cell)
        assert (args.policy_rules, args.policy_match,
                args.policy_hit) == (10, 'as-path', 'last')
        assert args.tester_attributes

    def test_every_point_has_its_own_id_stem_and_description(self):
        cells = cells_of(policy_test())
        ids = {bgperf2.batch_cell_id('policy', c) for c in cells}
        assert len(ids) == len(cells)
        descriptions = [bgperf2.batch_cell_description(c) for c in cells]
        assert len(set(descriptions)) == len(cells)
        assert ', policy=10 as-path last,' in descriptions[4]
        assert 'policy=' not in descriptions[0]
        stems = set()
        for c in cells:
            args = bgperf2.batch_cell_args(Namespace(tester_type='bird'), c)
            stems.add(bgperf2.bench_output_prefix(args))
        assert len(stems) == len(cells)

    def test_a_test_without_a_policy_keeps_its_ids(self):
        # The ids an in-flight batch resumes on.
        [cell] = cells_of(a_test())
        assert json.loads(bgperf2.batch_cell_id('policy', cell)) == {
            'test': 'policy', 'ordinal': 0, 'neighbors': 4, 'prefixes': 100,
            'filter': 'None', 'target': {'name': 'bird'}, 'monitor': 'sink'}

    def test_targets_of_one_point_stay_side_by_side(self):
        test = policy_test(policy_rules=[10], policy_match=['prefix'],
                           targets=[{'name': 'bird'}, {'name': 'frr_c'}])
        cells = cells_of(test)
        assert [(c['policy_hit'], c['target']['name']) for c in cells] == [
            ('first', 'bird'), ('first', 'frr_c'),
            ('last', 'bird'), ('last', 'frr_c')]

    def test_the_summary_keeps_points_apart(self):
        cells = cells_of(policy_test())
        groups = bgperf2.batch_summary_groups('policy', cells, {})
        assert 'policy' not in groups[0]['identity']
        assert groups[4]['identity']['policy'] == {
            'rules': 10, 'match': 'as-path', 'hit': 'last'}
        import summary
        keys = {summary._comparison_key(g) for g in groups}
        assert len(keys) == len(groups)

    @pytest.mark.parametrize('present', ['policy_rules', 'policy_match',
                                         'policy_hit'])
    def test_one_key_alone_is_refused(self, present):
        with pytest.raises(SystemExit, match='needs all three'):
            bgperf2.check_batch_test(a_test(**{present: POLICY_AXES[present]}))

    @pytest.mark.parametrize('key, value, message', [
        ('policy_rules', 10, 'must be a non-empty list'),
        ('policy_match', [], 'must be a non-empty list'),
        ('policy_rules', [10, 10], 'repeats 10'),
        ('policy_hit', ['last', 'last'], "repeats 'last'"),
        ('policy_rules', [0], 'only the baseline'),
        ('policy_rules', [-1, 10], 'whole numbers'),
        ('policy_rules', ['10'], 'whole numbers'),
        ('policy_rules', [True], 'whole numbers'),
        ('policy_match', ['regex'], 'policy match must be one of'),
        ('policy_hit', ['middle'], 'policy hit must be one of'),
        ('policy_rules', [70000], 'between 1 and 65533'),
    ])
    def test_a_bad_axis_is_refused_before_any_cell(self, key, value, message):
        with pytest.raises(SystemExit, match=message):
            bgperf2.check_batch_test(policy_test(**{key: value}))

    @pytest.mark.parametrize('key', bgperf2.BATCH_POLICY_KEYS)
    def test_a_target_key_is_refused_not_ignored(self, key):
        with pytest.raises(SystemExit, match='Move it up one level'):
            bgperf2.check_batch_test(a_test(
                targets=[{'name': 'bird', key: POLICY_AXES[key]}]))

    def test_a_target_without_a_renderer_is_refused(self):
        with pytest.raises(SystemExit, match="target 'openbgp'.*no renderer"):
            bgperf2.check_batch_test(policy_test(
                targets=[{'name': 'bird'}, {'name': 'openbgp'}]))

    @pytest.mark.parametrize('overrides, message', [
        ({'filter_test': ['None', 'transit']}, 'filter'),
        ({'receivers': 2}, '--receivers'),
        ({'path_diversity': 2}, 'path-diversity'),
        ({'tester_attributes': False}, 'tester_attributes is false'),
        ({'targets': [{'name': 'bird', 'repeat': True}]}, 'repeat'),
        ({'targets': [{'name': 'bird', 'tester_type': 'exa'}]}, 'exa'),
        ({'targets': [{'name': 'bird', 'target_config_file': '/x.conf'}]},
         'target_config_file'),
    ])
    def test_what_the_command_line_refuses_is_refused_here(self, overrides,
                                                           message):
        with pytest.raises(SystemExit, match=message):
            bgperf2.check_batch_test(policy_test(**overrides))

    def test_the_baseline_is_checked_too(self):
        # Its refusals are the attributes': an MRT generator has none, even
        # where no policy point would reach it first.
        with pytest.raises(SystemExit, match='the policy_rules 0 baseline'):
            bgperf2.check_batch_policy(
                policy_test(targets=[{'name': 'bird', 'tester_type': 'exa'}]),
                [], [], [None], None, 1, 0, 0)

    def test_a_scenario_file_target_is_refused(self, tmp_path):
        scenario = tmp_path / 's.yaml'
        scenario.write_text(bgperf2.gen_conf(policy_args()))
        with pytest.raises(SystemExit, match="carries 'import-policy'"):
            bgperf2.check_batch_test(a_test(
                targets=[{'name': 'bird', 'file': str(scenario)}]))
        plain = tmp_path / 'plain.yaml'
        plain.write_text(bgperf2.gen_conf(bgperf2.create_args_parser().parse_args(
            ['config', '-n', '2', '-p', '1000'])))
        with pytest.raises(SystemExit, match='scenario file'):
            bgperf2.check_batch_test(policy_test(
                targets=[{'name': 'bird', 'file': str(plain)}]))

    def test_a_policy_test_beside_a_repeat_test_is_refused(self):
        with pytest.raises(SystemExit, match='tester_attributes and'):
            bgperf2.check_batch_prefix_length_and_repeat([
                policy_test(), a_test(name='r', targets=[
                    {'name': 'bird', 'repeat': True}])])


def policy_row(name, rules, match, hit, elapsed, failed=''):
    header = [f.strip() for f in bgperf2.stats_header().split(',')]
    # Every bar graph's column a number, as a real row's are.
    row = [0] * len(header)
    row[header.index('filters')] = ''
    for column, value in (('name', name), ('peers', '4'),
                          ('prefixes per peer', '100'), ('failed', failed),
                          ('policy rules', rules), ('policy match', match),
                          ('policy hit', hit), ('elapsed (s)', elapsed),
                          ('max cpu %', 50), ('max mem (GB)', 1.5)):
        row[header.index(column)] = value
    return row


class TestThePolicyGraphs:

    def test_each_line_starts_at_its_baseline(self):
        rows = [policy_row('bird', 0, '', '', 10),
                policy_row('bird', 100, 'prefix', 'last', 14),
                policy_row('bird', 10, 'prefix', 'last', 11),
                policy_row('bird', 10, 'prefix', 'first', 10.5)]
        series = bgperf2.batch_policy_graph_series(rows, 'elapsed (s)')
        assert series == {
            'bird prefix last, 4n_100p': [(0, 10.0), (10, 11.0), (100, 14.0)],
            'bird prefix first, 4n_100p': [(0, 10.0), (10, 10.5)]}

    def test_a_failed_point_is_a_gap_not_a_zero(self):
        rows = [policy_row('bird', 0, '', '', 10),
                policy_row('bird', 10, 'prefix', 'last', 11, failed='FAILED'),
                policy_row('bird', 100, 'prefix', 'last', 14)]
        series = bgperf2.batch_policy_graph_series(rows, 'elapsed (s)')
        assert series == {'bird prefix last, 4n_100p': [(0, 10.0), (100, 14.0)]}

    def test_an_unsampled_peak_is_a_gap_not_a_zero(self):
        dead = policy_row('bird', 10, 'prefix', 'last', 11)
        header = [f.strip() for f in bgperf2.stats_header().split(',')]
        dead[header.index('max mem (GB)')] = bgperf2.row_gb(0)
        rows = [policy_row('bird', 0, '', '', 10), dead,
                policy_row('bird', 100, 'prefix', 'last', 14)]
        assert bgperf2.batch_policy_graph_series(rows, 'max mem (GB)') == {
            'bird prefix last, 4n_100p': [(0, 1.5), (100, 1.5)]}
        # The other columns of that row are still drawn.
        assert len(bgperf2.batch_policy_graph_series(
            rows, 'elapsed (s)')['bird prefix last, 4n_100p']) == 3

    def test_the_passes_of_a_repeated_test_are_one_line_at_their_median(self):
        rows = [policy_row('bird #1', 0, '', '', 10),
                policy_row('bird #1', 10, 'prefix', 'last', 11),
                policy_row('bird #2', 0, '', '', 12),
                policy_row('bird #2', 10, 'prefix', 'last', 15),
                policy_row('bird #3', 0, '', '', 11),
                policy_row('bird #3', 10, 'prefix', 'last', 13)]
        assert bgperf2.batch_policy_graph_series(rows, 'elapsed (s)') == {
            'bird prefix last, 4n_100p': [(0, 11.0), (10, 13.0)]}

    def test_a_test_without_a_policy_draws_none(self, tmp_path):
        rows = [policy_row('bird', 0, '', '', 10)]
        assert bgperf2.batch_policy_graph_series(rows, 'elapsed (s)') == {}
        bgperf2.create_batch_policy_graphs(rows, 't', results_dir=str(tmp_path))
        assert not list(tmp_path.iterdir())

    def test_every_line_has_its_own_colour_and_style(self):
        styles = bgperf2.batch_policy_line_styles(40)
        assert len(set(styles)) == 40
        # Past ten lines the colours repeat, so the style must not.
        assert styles[10][0] == styles[0][0]
        assert styles[10][1] != styles[0][1]

    def test_the_graphs_are_drawn_beside_the_bars(self, tmp_path):
        rows = [policy_row('bird', 0, '', '', 10),
                policy_row('frr_c', 0, '', '', 12),
                policy_row('bird', 10, 'prefix', 'last', 11),
                policy_row('frr_c', 10, 'prefix', 'last', 15)]
        bgperf2.create_batch_graphs(rows, 't', results_dir=str(tmp_path))
        drawn = {p.name for p in tmp_path.iterdir()}
        assert {'bgperf_t_policy_elapsed.png', 'bgperf_t_policy_max_cpu.png',
                'bgperf_t_policy_max_mem.png', 'bgperf_t_elapsed.png'} <= drawn
        assert {os.path.basename(p) for p in bgperf2.batch_graph_paths(
            't', str(tmp_path))} == drawn


FIXTURES = __import__('pathlib').Path(__file__).parent / 'fixtures'

# The run frr10_7_policy_running_config.txt was captured from:
# `bench -t frr_c --version 10.7 -n 2 -p 1000 --prefix-length 24
#  --policy-rules 3 --policy-match prefix --policy-hit last`.
CAPTURED_FRR_POLICY = {'rules': 3, 'match': 'prefix', 'hit': 'last',
                       'peers': 2, 'prefixes': 1000, 'prefix-length': 24,
                       'exclude': ['10.10.0.0/16']}
CAPTURED_FRR_SESSIONS = ['10.10.0.2', '10.10.0.3', '10.10.0.4']


def running_config_from(policy, sessions):
    '''What FRR prints for the rendered policy: seq numbers inserted, the
    as-path and community lists after `router bgp`, route-map blocks closed by
    `exit`.'''
    before, after, seqs = [], [], {}
    for line in pr.frr_policy_lines(policy):
        line = line.rstrip('\n')
        m = frr._FRR_LIST_LINE.match(line)
        if m:
            seqs[m.group(2)] = seqs.get(m.group(2), 0) + 5
            printed = '{0} {1} seq {2} {3}'.format(
                m.group(1), m.group(2), seqs[m.group(2)], m.group(3))
            (before if m.group(1) == 'ip prefix-list' else after).append(
                printed)
        elif line.startswith('route-map'):
            before.extend(['exit', '!', line])
        else:
            before.append(line)
    bgp = ['router bgp 1000', ' address-family ipv4 unicast'] + [
        '  neighbor {0} route-map {1} in'.format(s, pr.FRR_ROUTE_MAP)
        for s in sessions] + [' exit-address-family', 'exit', '!']
    return '\n'.join(['!'] + before + ['exit', '!'] + bgp + after + ['end'])


class TestThePolicyLoadedCheck:
    '''Step 6: a daemon that dropped its policy must not look fast.'''

    def test_the_captured_frr_config_is_the_rendered_policy(self):
        policy = ip.policy_from_scenario(CAPTURED_FRR_POLICY)
        text = (FIXTURES / 'frr10_7_policy_running_config.txt').read_text()
        assert frr.policy_loaded_failure(
            policy, text, CAPTURED_FRR_SESSIONS) is None

    @pytest.mark.parametrize('match', BOTH)
    @pytest.mark.parametrize('hit', ip.POLICY_HITS)
    def test_every_shape_reads_back_as_loaded(self, match, hit):
        policy = ip.build_policy(4, match, hit, 2, 8, 24, ('10.10.0.0/16',))
        sessions = ['10.10.0.2', '10.10.0.3']
        assert frr.policy_loaded_failure(
            policy, running_config_from(policy, sessions), sessions) is None

    def captured(self):
        return (ip.policy_from_scenario(CAPTURED_FRR_POLICY),
                (FIXTURES / 'frr10_7_policy_running_config.txt').read_text())

    def test_a_skipped_list_entry_is_named(self):
        policy, text = self.captured()
        text = text.replace(
            'ip prefix-list BGPERF-IMPORT-R2 seq 40 permit 1.3.232.0/21 '
            'ge 24 le 24\n', '')
        failure = frr.policy_loaded_failure(policy, text,
                                            CAPTURED_FRR_SESSIONS)
        assert '1 of 29 list entries missing' in failure
        assert '1.3.232.0/21' in failure

    def test_a_list_entry_the_policy_lacks_is_named(self):
        policy, text = self.captured()
        text = text.replace(
            '!\nroute-map BGPERF-IMPORT deny 1',
            'ip prefix-list BGPERF-IMPORT-R0 seq 10 permit 0.0.0.0/0 le 32\n'
            '!\nroute-map BGPERF-IMPORT deny 1')
        assert '1 list entries not in the policy' in frr.policy_loaded_failure(
            policy, text, CAPTURED_FRR_SESSIONS)

    @pytest.mark.parametrize('old, new, named', [
        # A rule's match line skipped: the entry then matches everything.
        (' match ip address prefix-list BGPERF-IMPORT-R0\n', '',
         '1 of the 5 rendered entries changed, e.g. sequence 2'),
        # A rule's action flipped.
        ('route-map BGPERF-IMPORT deny 3\n',
         'route-map BGPERF-IMPORT permit 3\n',
         '1 of the 5 rendered entries changed, e.g. sequence 3'),
        # A whole entry missing.
        ('route-map BGPERF-IMPORT deny 2\n match ip address prefix-list '
         'BGPERF-IMPORT-R0\nexit\n', '',
         '1 of the 5 rendered entries missing, e.g. sequence 2'),
        # An entry the policy never had: counted on its own, not out of 5.
        ('route-map BGPERF-IMPORT permit 5\n',
         'route-map BGPERF-IMPORT permit 5\nexit\n!\n'
         'route-map BGPERF-IMPORT deny 9\n',
         '1 entries not in the policy, e.g. sequence 9'),
    ])
    def test_a_route_map_that_differs_is_named(self, old, new, named):
        policy, text = self.captured()
        assert old in text
        failure = frr.policy_loaded_failure(policy, text.replace(old, new),
                                            CAPTURED_FRR_SESSIONS)
        assert 'route-map BGPERF-IMPORT: ' + named in failure

    def test_examples_come_in_their_own_order(self):
        policy = ip.build_policy(12, 'as-path', 'last', 2, 8, 24, ())
        sessions = ['10.10.0.2', '10.10.0.10', '10.10.0.3', '10.10.0.11']
        text = running_config_from(policy, [])
        failure = frr.policy_loaded_failure(
            policy, '\n'.join(line for line in text.splitlines()
                              if not line.startswith('route-map')), sessions)
        # Numeric, not string, order: 1, 2, 3 -- never 1, 10, 11.
        assert 'missing, e.g. sequence 1, 2, 3 and 11 more' in failure
        assert "'10.10.0.2', '10.10.0.3', '10.10.0.10' and 1 more" in failure

    @pytest.mark.parametrize('line, entry', [
        # Printed by FRR 10.7 on 2026-11-26 for lists added by hand to a
        # running bgpd: the two kinds that print after `router bgp`.
        ('bgp as-path access-list BGPERF-IMPORT-R0 seq 5 permit _4200000001_',
         ('bgp as-path access-list', 'BGPERF-IMPORT-R0', 'permit _4200000001_')),
        ('bgp community-list standard BGPERF-IMPORT-R3 seq 5 permit 64514:3',
         ('bgp community-list standard', 'BGPERF-IMPORT-R3',
          'permit 64514:3')),
    ])
    def test_real_frr_list_lines_parse(self, line, entry):
        lists, _, _ = frr._frr_policy_items([line], pr.FRR_ROUTE_MAP)
        assert lists == {entry: 1}

    def test_a_session_without_the_route_map_is_named(self):
        policy, text = self.captured()
        text = text.replace(
            '  neighbor 10.10.0.3 route-map BGPERF-IMPORT in\n', '')
        failure = frr.policy_loaded_failure(policy, text,
                                            CAPTURED_FRR_SESSIONS)
        assert failure.endswith("sessions without route-map BGPERF-IMPORT "
                                "in: '10.10.0.3'")

    def test_no_reply_is_a_failure(self):
        policy, _ = self.captured()
        assert 'list entries missing' in frr.policy_loaded_failure(
            policy, '', CAPTURED_FRR_SESSIONS)

    def test_other_lists_and_route_maps_are_not_its_business(self):
        policy, text = self.captured()
        text = text.replace('!\nend', 'ip prefix-list OTHER seq 5 permit any\n'
                            'route-map OTHER permit 10\nexit\n!\nend')
        assert frr.policy_loaded_failure(policy, text,
                                         CAPTURED_FRR_SESSIONS) is None

    def bird_text(self, listener='bgperf_import_policy',
                  sessions='bgperf_import_policy'):
        '''The BIRD 3 fixture with each BGP protocol's input filter set.'''
        lines = (FIXTURES / 'bird3_show_protocols_all.txt').read_text() \
            .splitlines()
        out, protocol = [], None
        for line in lines:
            if line and not line[0].isspace():
                protocol = line.split()[0]
            if line.strip().startswith('Input filter:') and protocol and (
                    protocol == 'everything' or protocol.startswith('dynbgp')):
                value = listener if protocol == 'everything' else sessions
                line = line.split(':')[0] + ':   ' + value
            out.append(line)
        return '\n'.join(out)

    def test_bird_importing_through_the_filter_is_loaded(self):
        assert bird.policy_loaded_failure(self.bird_text()) is None

    def test_the_captured_bird_output_is_loaded(self):
        # BIRD 2.17.1, live, community/miss: the listener while DOWN and
        # every session print the filter by name.
        text = (FIXTURES / 'bird2_policy_show_protocols_all.txt').read_text()
        assert bird.policy_loaded_failure(text) is None
        assert 'dynbgp2 (ACCEPT)' in bird.policy_loaded_failure(
            text.replace('Input filter:   bgperf_import_policy\n'
                         '    Output filter:  ACCEPT\n'
                         '    Routes:         750', 'Input filter:   ACCEPT\n'
                         '    Output filter:  ACCEPT\n'
                         '    Routes:         750', 1))

    def test_the_parser_reads_the_input_filter(self):
        protocols = bird.parse_protocols(self.bird_text())
        assert protocols['everything']['channels']['ipv4']['input_filter'] \
            == 'bgperf_import_policy'
        assert protocols['kernel1']['channels']['ipv4']['input_filter'] \
            == 'REJECT'

    @pytest.mark.parametrize('listener, sessions, named', [
        ('ACCEPT', 'bgperf_import_policy', 'everything (ACCEPT)'),
        ('bgperf_import_policy', 'ACCEPT', 'dynbgp1 (ACCEPT)'),
    ])
    def test_bird_importing_anything_else_is_named(self, listener, sessions,
                                                    named):
        failure = bird.policy_loaded_failure(self.bird_text(listener,
                                                            sessions))
        assert named in failure

    def test_bird_with_no_listener_is_a_failure(self):
        assert 'no `neighbor range`' in bird.policy_loaded_failure('')

    @pytest.mark.parametrize('cls', [bird.BIRDTarget, frr.FRRoutingTarget])
    def test_a_run_without_a_policy_asks_nothing(self, cls):
        target = cls.__new__(cls)
        target.conf = {}
        target.local = lambda *a, **kw: pytest.fail('asked the daemon')
        assert target.policy_loaded_failure() is None

    def test_an_adapter_without_a_check_fails_closed(self):
        import base

        class Rendering(base.Target):
            IMPORT_POLICY_MATCHES = ip.POLICY_MATCHES

        target = Rendering.__new__(Rendering)
        target.conf = rendered(policy_args())['target']
        assert 'no way to confirm' in target.policy_loaded_failure()

    def test_every_policy_target_has_its_own_check(self):
        import base
        for name, cls in bgperf2.TARGET_CLASSES.items():
            if cls.IMPORT_POLICY_MATCHES:
                assert cls.policy_loaded_failure is not \
                    base.Target.policy_loaded_failure, name

    def test_the_frr_target_asks_its_running_config(self):
        scenario = rendered(policy_args(match='community'))
        target = target_session(scenario)
        asked = []

        def local(cmd, **kw):
            asked.append(cmd)
            policy = target.import_policy()
            return running_config_from(policy, [
                n['local-address'] for n in
                target.scenario_neighbors(sort=False)]).encode()
        target.local = local
        assert target.policy_loaded_failure() is None
        assert asked == ["vtysh -c 'show running-config'"]
