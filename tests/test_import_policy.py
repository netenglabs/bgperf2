'''The generated import policy model of policy phase 1, step 2.

No daemon is involved. The oracle below evaluates the abstract policy route by
route -- guard, generated rules in order, default -- against prefixes taken
from a scenario `gen_conf()` actually rendered, so the expected counts are
checked against the table a run would announce rather than against the
model's own arithmetic.
'''
import ipaddress
from argparse import Namespace
from itertools import islice

import pytest
import yaml
from mako.template import Template

import bgperf2
import import_policy as ip
import prefix_length as pl


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


def rendered_neighbors(peers, prefixes, length):
    conf = yaml.safe_load(Template(bgperf2.gen_conf(scenario_args(
        neighbor_num=peers, prefix_num=prefixes,
        prefix_length=length))).render())
    return list(conf['testers'][0]['neighbors'].values())


def rendered_peer_paths(peers, prefixes, length):
    '''Each peer's announced prefixes, in the order the scenario renders them.

    That is walk-slice order. It is not AS order: neighbours are rendered
    sorted by router-id text, so it diverges from ten peers on.
    '''
    return [n['paths'] for n in rendered_neighbors(peers, prefixes, length)]


def block_routes(block, peer_paths):
    offset = block.first - block.peer * len(peer_paths[block.peer])
    return peer_paths[block.peer][offset:offset + block.count]


def rule_matches(policy, rule, block, route):
    if policy.match == 'as-path':
        return any(asn in block.as_path for asn in rule.values)
    if policy.match == 'community':
        return any(c in block.communities for c in rule.values)
    net = ipaddress.IPv4Network(route)
    return net.prefixlen == policy.prefix_length and any(
        net.subnet_of(ipaddress.IPv4Network(v)) for v in rule.values)


def evaluate(policy, block, route):
    '''(action, who decided): 'guard', a generated rule's position, or 'default'.'''
    if rule_matches(policy, policy.guard, block, route):
        return policy.guard.action, 'guard'
    for rule in policy.rules:
        if rule_matches(policy, rule, block, route):
            return rule.action, rule.position
    return policy.default_action, 'default'


SHAPES = [(1, 4), (3, 10), (5, 7), (2, 33)]


class TestBlocks:
    def test_each_peer_is_cut_into_contiguous_blocks_covering_its_list(self):
        blocks = ip.policy_blocks(3, 10)
        assert len(blocks) == 3 * ip.BLOCKS_PER_PEER
        for peer in range(3):
            mine = [b for b in blocks if b.peer == peer]
            assert mine[0].first == peer * 10
            for a, b in zip(mine, mine[1:]):
                assert b.first == a.first + a.count
            assert sum(b.count for b in mine) == 10

    def test_sizes_are_even_with_the_larger_blocks_first(self):
        assert ip.block_sizes(8) == (2, 2, 2, 2)
        assert ip.block_sizes(10) == (3, 3, 2, 2)
        assert ip.block_sizes(7) == (2, 2, 2, 1)

    def test_the_last_block_of_every_peer_is_rejected_and_nothing_else(self):
        for peers, prefixes in SHAPES:
            blocks = ip.policy_blocks(peers, prefixes)
            assert [b.index for b in blocks if b.rejected] == [
                p * ip.BLOCKS_PER_PEER + ip.BLOCKS_PER_PEER - 1
                for p in range(peers)]

    def test_attributes_name_the_block_and_its_class_only(self):
        blocks = ip.policy_blocks(4, 8)
        assert len({b.as_path for b in blocks}) == len(blocks)
        assert len({b.communities for b in blocks}) == len(blocks)
        for b in blocks:
            klass = ip.REJECT_PATH_ASN if b.rejected else ip.ACCEPT_PATH_ASN
            assert b.as_path == (ip.BLOCK_PATH_ASN_BASE + b.index, klass)
            value = (ip.REJECT_COMMUNITY_VALUE if b.rejected
                     else ip.ACCEPT_COMMUNITY_VALUE)
            assert b.communities == ((ip.COMMUNITY_BLOCK_ASN, b.index),
                                     (ip.COMMUNITY_CLASS_ASN, value))

    def test_generated_asns_are_private_32_bit_and_communities_fit_16_bits(self):
        blocks = ip.policy_blocks(ip.MAX_BLOCKS // ip.BLOCKS_PER_PEER, 4)
        for asn in (ip.ACCEPT_PATH_ASN, ip.REJECT_PATH_ASN,
                    blocks[-1].as_path[0],
                    ip.FILLER_PATH_ASN_BASE + ip.MAX_POLICY_RULES):
            assert 4200000000 <= asn <= 4294967294
        assert blocks[-1].as_path[0] < ip.FILLER_PATH_ASN_BASE
        assert ip.FILLER_PATH_ASN_BASE + ip.MAX_POLICY_RULES < 4294967295
        assert blocks[-1].communities[0][1] <= 0xFFFF

    @pytest.mark.parametrize('peers', [3, 12])
    @pytest.mark.parametrize('length', [32, 24])
    def test_blocks_are_the_slices_the_scenario_announces(self, length, peers):
        '''`peer` is a walk slice, and slice `k` must be the `k`-th list the
        scenario renders, or every block is labelled with someone else's
        routes.'''
        peer_paths = rendered_peer_paths(peers, 10, length)
        walk = ([str(ipaddress.IPv4Address(pl.HISTORICAL_WALK_FIRST + i)) + '/32'
                 for i in range(peers * 10)] if length == 32
                else list(islice(pl.walk(24, (PEERING,)), peers * 10)))
        for block in ip.policy_blocks(peers, 10):
            assert block_routes(block, peer_paths) == \
                walk[block.first:block.first + block.count]

    def test_walk_slices_are_not_in_as_order(self):
        '''The trap `Block.peer` documents: from ten peers on, AS order and
        slice order differ, so nothing may map a block to a peer by its AS.'''
        neighbors = rendered_neighbors(10, 4, 32)
        assert [n['as'] for n in neighbors] != sorted(n['as'] for n in neighbors)
        assert neighbors[0]['paths'][0] == '100.0.0.0/32'


class TestExpectedCounts:
    def test_no_policy_expects_the_whole_table(self):
        counts = ip.expected_counts(0, 3, 10)
        assert counts.accepted_per_peer == (10, 10, 10)
        assert counts.accepted == counts.offered == 30
        assert counts.rejected == 0

    def test_no_policy_keeps_todays_small_runs(self):
        '''`-n1 -p1` is the fastest bench and must stay expressible.'''
        assert ip.expected_counts(0, 1, 1).accepted == 1

    @pytest.mark.parametrize('peers,prefixes', SHAPES)
    def test_the_last_quarter_block_of_each_peer_is_rejected(self, peers, prefixes):
        counts = ip.expected_counts(1000, peers, prefixes)
        rejected_each = prefixes // ip.BLOCKS_PER_PEER
        assert counts.accepted_per_peer == (prefixes - rejected_each,) * peers
        assert counts.rejected == peers * rejected_each
        assert counts.offered == peers * prefixes

    @pytest.mark.parametrize('peers,prefixes', SHAPES)
    def test_every_peer_keeps_routes_and_loses_some(self, peers, prefixes):
        '''A peer expected to hold 0 cannot be told from a dead session, and
        one losing nothing makes the policy invisible on its checkpoint.'''
        counts = ip.expected_counts(1, peers, prefixes)
        for offered, accepted in zip(counts.offered_per_peer,
                                     counts.accepted_per_peer):
            assert 0 < accepted < offered

    def test_the_count_does_not_depend_on_rules_match_or_hit(self):
        assert len({ip.expected_counts(n, 3, 10) for n in (1, 2, 500)}) == 1


class TestThePolicy:
    def test_it_is_deterministic(self):
        for match in ip.POLICY_MATCHES:
            for hit in ip.POLICY_HITS:
                a = ip.build_policy(50, match, hit, 3, 10, 24, (PEERING,))
                b = ip.build_policy(50, match, hit, 3, 10, 24, (PEERING,))
                assert a == b

    @pytest.mark.parametrize('match', ip.POLICY_MATCHES)
    def test_shape(self, match):
        policy = ip.build_policy(5, match, 'first', 2, 8)
        assert len(policy.rules) == 5
        assert [r.position for r in policy.rules] == list(range(5))
        assert policy.guard.position is None
        assert policy.guard.action == ip.REJECT
        assert policy.default_action == ip.ACCEPT

    @pytest.mark.parametrize('hit,deciding', [('first', 0), ('last', 6),
                                              ('miss', None)])
    @pytest.mark.parametrize('match', ip.POLICY_MATCHES)
    def test_exactly_one_rule_accepts_and_it_is_where_hit_says(
            self, match, hit, deciding):
        policy = ip.build_policy(7, match, hit, 2, 8)
        assert policy.deciding == deciding
        assert [r.position for r in policy.rules if r.action == ip.ACCEPT] == \
            ([] if deciding is None else [deciding])

    def test_one_rule_makes_first_and_last_the_same_policy(self):
        assert ip.build_policy(1, 'community', 'first', 2, 8).rules == \
            ip.build_policy(1, 'community', 'last', 2, 8).rules

    @pytest.mark.parametrize('match', ip.POLICY_MATCHES)
    def test_filler_values_are_distinct(self, match):
        policy = ip.build_policy(300, match, 'miss', 2, 8, 24, (PEERING,))
        values = [v for r in policy.rules for v in r.values]
        assert len(values) == len(set(values)) == 300

    def test_prefix_fillers_lie_outside_both_walks(self):
        for length in (32, 24):
            policy = ip.build_policy(ip.MAX_POLICY_RULES, 'prefix', 'miss',
                                     1, 4, length)
            last = ipaddress.IPv4Network(policy.rules[-1].values[0])
            assert last.subnet_of(ip.FILLER_PREFIX_SPACE)
            assert last.prefixlen == length
        assert int(ip.FILLER_PREFIX_SPACE.network_address) > \
            pl.HISTORICAL_WALK_LAST
        assert int(ip.FILLER_PREFIX_SPACE.network_address) >= pl.WALK_END


ORACLE_SHAPES = [(1, 4, 32), (3, 10, 32), (3, 10, 24), (2, 7, 24), (11, 5, 32)]


class TestTheOracle:
    '''Every route of a rendered table, through guard, rules and default.'''

    @pytest.mark.parametrize('peers,prefixes,length', ORACLE_SHAPES)
    @pytest.mark.parametrize('hit', ip.POLICY_HITS)
    @pytest.mark.parametrize('match', ip.POLICY_MATCHES)
    def test_every_route_is_decided_where_the_model_says(
            self, match, hit, peers, prefixes, length):
        rules = 6
        policy = ip.build_policy(rules, match, hit, peers, prefixes, length,
                                 (PEERING,))
        peer_paths = rendered_peer_paths(peers, prefixes, length)
        accepted = [0] * peers
        for block in ip.policy_blocks(peers, prefixes):
            for route in block_routes(block, peer_paths):
                action, by = evaluate(policy, block, route)
                if block.rejected:
                    assert (action, by) == (ip.REJECT, 'guard')
                    continue
                expected_by = 'default' if hit == 'miss' else policy.deciding
                assert (action, by) == (ip.ACCEPT, expected_by)
                accepted[block.peer] += 1
        assert tuple(accepted) == \
            ip.expected_counts(rules, peers, prefixes).accepted_per_peer

    @pytest.mark.parametrize('peers,prefixes,length', ORACLE_SHAPES)
    @pytest.mark.parametrize('match', ip.POLICY_MATCHES)
    def test_under_miss_no_generated_rule_matches_anything(
            self, match, peers, prefixes, length):
        policy = ip.build_policy(40, match, 'miss', peers, prefixes, length,
                                 (PEERING,))
        peer_paths = rendered_peer_paths(peers, prefixes, length)
        for block in ip.policy_blocks(peers, prefixes):
            for route in block_routes(block, peer_paths):
                for rule in policy.rules:
                    assert not rule_matches(policy, rule, block, route)

    @pytest.mark.parametrize('length', [32, 24])
    @pytest.mark.parametrize('hit', ['first', 'last'])
    def test_rules_before_the_deciding_one_match_nothing(self, hit, length):
        policy = ip.build_policy(5, 'prefix', hit, 3, 10, length, (PEERING,))
        peer_paths = rendered_peer_paths(3, 10, length)
        for block in ip.policy_blocks(3, 10):
            for route in block_routes(block, peer_paths):
                for rule in policy.rules:
                    if rule.position != policy.deciding:
                        assert not rule_matches(policy, rule, block, route)


class TestWalkRanges:
    def test_the_historical_bounds_are_the_scenario_preamble(self):
        '''Not a second definition of the /32 walk: checked against it.'''
        preamble = bgperf2.gen_mako_macro()
        first = str(ipaddress.IPv4Address(pl.HISTORICAL_WALK_FIRST))
        last = str(ipaddress.IPv4Address(pl.HISTORICAL_WALK_LAST))
        assert "iter_iprange('{0}','{1}')".format(first, last) in preamble

    def test_a_32_slice_is_one_range(self):
        start = pl.HISTORICAL_WALK_FIRST
        assert pl.walk_address_ranges(32, 5, 3) == [(start + 5, start + 8)]

    def test_the_32_walk_ends_where_the_preamble_does(self):
        span = pl.HISTORICAL_WALK_LAST - pl.HISTORICAL_WALK_FIRST + 1
        assert pl.walk_address_ranges(32, span - 1, 1)
        with pytest.raises(ValueError, match='ends at 160.0.0.0'):
            pl.walk_address_ranges(32, span - 1, 2)

    def test_a_24_slice_matches_the_walk_across_a_skipped_span(self):
        '''A skipped span splits a slice into two ranges, entry for entry.'''
        exclude = ('1.0.2.0/28',)
        walk = list(islice(pl.walk(24, exclude), 5))
        ranges = pl.walk_address_ranges(24, 1, 3, exclude)
        assert len(ranges) == 2
        covered = [str(ipaddress.IPv4Network((a, 24)))
                   for s, e in ranges for a in range(s, e, 256)]
        assert covered == walk[1:4]
        assert '1.0.2.0/24' not in covered

    def test_a_24_slice_steps_over_loopback(self):
        '''Without enumerating the 8M prefixes before it: the walk below
        127.0.0.0 is 1/8 to 126/8 less 10/8 and 100.64/10.'''
        index = (126 * 65536) - 65536 - 16384 - 1
        assert pl.walk_address_ranges(24, index - 1, 3, (PEERING,)) == [
            (int(ipaddress.IPv4Address('126.255.254.0')),
             int(ipaddress.IPv4Address('127.0.0.0'))),
            (int(ipaddress.IPv4Address('128.0.0.0')),
             int(ipaddress.IPv4Address('128.0.1.0')))]

    def test_a_24_slice_from_the_start(self):
        assert [ipaddress.IPv4Network((s, 24)) for s, _ in
                pl.walk_address_ranges(24, 0, 2)] == \
            [ipaddress.IPv4Network('1.0.0.0/24')]
        assert list(islice(pl.walk(24), 2)) == ['1.0.0.0/24', '1.0.1.0/24']

    def test_a_24_slice_beyond_capacity_is_refused(self):
        cap = pl.capacity(24, (PEERING,))
        with pytest.raises(ValueError, match='cannot supply'):
            pl.walk_address_ranges(24, cap - 1, 2, (PEERING,))

    @pytest.mark.parametrize('first,count', [(-1, 1), (0, 0), (True, 1),
                                             (0, 1.0)])
    def test_bad_slices_are_refused(self, first, count):
        with pytest.raises(ValueError):
            pl.walk_address_ranges(24, first, count)

    def test_the_peering_subnet_is_skipped_as_the_walk_skips_it(self):
        walk = list(islice(pl.walk(24, ('1.0.1.0/28',)), 3))
        ranges = pl.walk_address_ranges(24, 0, 3, ('1.0.1.0/28',))
        nets = [str(ipaddress.IPv4Network((s, 24))) for s, e in ranges
                for s in range(s, e, 256)]
        assert nets == walk
        assert '1.0.1.0/24' not in nets


class TestRefusals:
    @pytest.mark.parametrize('rules', [0, -1, True, 2.0, ip.MAX_POLICY_RULES + 1])
    def test_rule_count(self, rules):
        with pytest.raises(ip.ImportPolicyConfigurationError,
                           match='policy rules'):
            ip.build_policy(rules, 'prefix', 'first', 1, 4)

    def test_expected_counts_refuses_a_bad_rule_count(self):
        with pytest.raises(ip.ImportPolicyConfigurationError):
            ip.expected_counts(-1, 1, 4)
        with pytest.raises(ip.ImportPolicyConfigurationError):
            ip.expected_counts(True, 1, 4)

    @pytest.mark.parametrize('match', ['as_path', 'large-community', None])
    def test_match(self, match):
        with pytest.raises(ip.ImportPolicyConfigurationError,
                           match='policy match'):
            ip.build_policy(1, match, 'first', 1, 4)

    @pytest.mark.parametrize('hit', ['middle', None, 0])
    def test_hit(self, hit):
        with pytest.raises(ip.ImportPolicyConfigurationError,
                           match='policy hit'):
            ip.build_policy(1, 'prefix', hit, 1, 4)

    @pytest.mark.parametrize('prefixes', [1, 3])
    def test_fewer_prefixes_than_blocks(self, prefixes):
        '''The rejected block would be empty and the policy invisible.'''
        with pytest.raises(ip.ImportPolicyConfigurationError,
                           match='at least 4 prefixes per peer'):
            ip.expected_counts(1, 2, prefixes)

    def test_more_blocks_than_a_community_can_number(self):
        peers = ip.MAX_BLOCKS // ip.BLOCKS_PER_PEER
        assert ip.expected_counts(1, peers, 4).accepted == peers * 3
        with pytest.raises(ip.ImportPolicyConfigurationError,
                           match='at most 16,384 peers'):
            ip.expected_counts(1, peers + 1, 4)

    @pytest.mark.parametrize('length', [16, 24.0, '24', True])
    def test_unsupported_prefix_length(self, length):
        with pytest.raises(ip.ImportPolicyConfigurationError,
                           match='prefix length'):
            ip.build_policy(1, 'community', 'first', 1, 4, length)

    def test_a_prefix_table_beyond_the_walk(self):
        cap = pl.capacity(24, (PEERING,))
        with pytest.raises(ip.ImportPolicyConfigurationError,
                           match='cannot supply'):
            ip.build_policy(1, 'prefix', 'first', 1, cap + 4, 24, (PEERING,))
