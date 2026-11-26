'''The BIRD and FRR renderers of the generated import policy (policy phase 1, step 4).

No daemon is involved. Two kinds of test:

- **Exact text** for small policies, so a change to what a daemon is given is a
  change to a fixture someone has to read.
- **Equivalence**: the rendered BIRD and FRR text are each read back by a small
  evaluator of that language, and every route of a table `gen_conf()` rendered
  is run through both. Each must reach the same decision *at the same
  statement* as the model's own oracle (`test_import_policy.evaluate`), which
  is the plan's one required proof: the two daemons are given the same work.

The evaluators understand exactly the forms the renderers write and refuse
anything else, so a renderer that drifted into a new form fails here rather
than being read loosely. That the daemons themselves accept the text was
checked against BIRD 2.19.2, 3.3.2, 2.17.1 (`latest`) and FRR 8.5, 10.7 when the renderers were
written; the suite cannot run a daemon.
'''
import dataclasses
import ipaddress
import re

import pytest

import import_policy as ip
import policy_render as pr
from test_import_policy import (
    ORACLE_SHAPES, PEERING, block_routes, evaluate, rendered_peer_paths)


# --- reading BIRD back ---------------------------------------------------------

_BIRD_IF = re.compile(r'^  if (.+) then (accept|reject);$')
_BIRD_END = re.compile(r'^  (accept|reject);$')
_BIRD_PREFIX_SET = re.compile(r'^net ~ \[ (.+) \]$')
_BIRD_PREFIX_ITEM = re.compile(r'^(\d+\.\d+\.\d+\.\d+/\d+)\{(\d+),(\d+)\}$')
_BIRD_PATH = re.compile(r'^bgp_path ~ \[= \* (\d+) \* =\]$')
_BIRD_COMMUNITY = re.compile(r'^\((\d+), (\d+)\) ~ bgp_community$')


def bird_test(text):
    '''A predicate over (net, path, communities) for one BIRD test.'''
    m = _BIRD_PREFIX_SET.match(text)
    if m:
        items = []
        for item in m.group(1).split(', '):
            im = _BIRD_PREFIX_ITEM.match(item)
            assert im, item
            items.append((ipaddress.IPv4Network(im.group(1)),
                          int(im.group(2)), int(im.group(3))))
        return lambda net, path, comms: any(
            lo <= net.prefixlen <= hi and net.subnet_of(cover)
            for cover, lo, hi in items)
    terms = text.split(' || ')
    asns = [_BIRD_PATH.match(t) for t in terms]
    if all(asns):
        wanted = {int(a.group(1)) for a in asns}
        return lambda net, path, comms: any(a in wanted for a in path)
    comms = [_BIRD_COMMUNITY.match(t) for t in terms]
    assert all(comms), text
    wanted = {(int(c.group(1)), int(c.group(2))) for c in comms}
    return lambda net, path, communities: any(c in wanted
                                              for c in communities)


def read_bird(text):
    '''[(predicate or None, action)] in order; None is the final action.'''
    lines = text.split('\n')
    assert lines[0] == 'filter ' + pr.BIRD_FILTER_NAME
    assert lines[1] == '{'
    assert lines[-2:] == ['}', '']
    statements = []
    for line in lines[2:-2]:
        m = _BIRD_IF.match(line)
        if m:
            statements.append((bird_test(m.group(1)), m.group(2)))
            continue
        m = _BIRD_END.match(line)
        assert m and line is lines[-3], line
        statements.append((None, m.group(1)))
    return statements


def run_bird(statements, net, path, comms):
    '''(action, statement index) of the first statement that decides.'''
    for i, (test, action) in enumerate(statements):
        if test is None or test(net, path, comms):
            return action, i
    raise AssertionError('the filter fell off its end')


# --- reading FRR back ----------------------------------------------------------

_FRR_PREFIX = re.compile(
    r'^ip prefix-list (\S+) permit (\d+\.\d+\.\d+\.\d+/\d+)(?: ge (\d+) le (\d+))?$')
_FRR_PATH = re.compile(r'^bgp as-path access-list (\S+) permit (\S+)$')
_FRR_COMMUNITY = re.compile(
    r'^bgp community-list standard (\S+) permit (\d+):(\d+)$')
_FRR_ENTRY = re.compile(r'^route-map (\S+) (permit|deny) (\d+)$')
_FRR_MATCH = re.compile(
    r'^ match (ip address prefix-list|as-path|community) (\S+)$')

# FRR's `_` in an AS-path regex: the start or end of the path, or a separator.
_FRR_UNDERSCORE = r'(?:^|$|[,{}() ])'


def read_frr(text):
    '''(lists, entries): lists by name, entries as (seq, action, match).'''
    lists = {}
    entries = []
    for line in text.split('\n')[:-1]:
        m = _FRR_PREFIX.match(line)
        if m:
            net = ipaddress.IPv4Network(m.group(2))
            lo = int(m.group(3)) if m.group(3) else net.prefixlen
            hi = int(m.group(4)) if m.group(4) else net.prefixlen
            assert lo > net.prefixlen or (lo, hi) == (net.prefixlen,) * 2, line
            lists.setdefault(('prefix', m.group(1)), []).append((net, lo, hi))
            continue
        m = _FRR_PATH.match(line)
        if m:
            regex = re.compile(m.group(2).replace('_', _FRR_UNDERSCORE))
            lists.setdefault(('as-path', m.group(1)), []).append(regex)
            continue
        m = _FRR_COMMUNITY.match(line)
        if m:
            lists.setdefault(('community', m.group(1)), []).append(
                (int(m.group(2)), int(m.group(3))))
            continue
        m = _FRR_ENTRY.match(line)
        if m:
            assert m.group(1) == pr.FRR_ROUTE_MAP
            entries.append([int(m.group(3)), m.group(2), None])
            continue
        m = _FRR_MATCH.match(line)
        assert m and entries and entries[-1][2] is None, line
        kind = {'ip address prefix-list': 'prefix'}.get(m.group(1), m.group(1))
        assert (kind, m.group(2)) in lists, 'match names a list not yet defined'
        entries[-1][2] = (kind, m.group(2))
    seqs = [e[0] for e in entries]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
    return lists, entries


def frr_matches(lists, ref, net, path, comms):
    kind, _ = ref
    if kind == 'prefix':
        return any(lo <= net.prefixlen <= hi and net.subnet_of(cover)
                   for cover, lo, hi in lists[ref])
    if kind == 'as-path':
        text = ' '.join(str(a) for a in path)
        return any(r.search(text) for r in lists[ref])
    return any(c in lists[ref] for c in comms)


def run_frr(lists, entries, net, path, comms):
    '''(action, seq) of the first entry that decides.'''
    for seq, action, ref in entries:
        if ref is None or frr_matches(lists, ref, net, path, comms):
            return {'permit': ip.ACCEPT, 'deny': ip.REJECT}[action], seq
    raise AssertionError('the route-map fell off its end')


# --- one name for "who decided" across the three ----------------------------------

def bird_who(index, policy):
    if index == 0:
        return 'guard'
    if index <= len(policy.rules):
        return index - 1
    return 'default'


def frr_who(seq, policy):
    if seq == pr.FRR_GUARD_SEQ:
        return 'guard'
    if seq == pr.frr_default_seq(policy):
        return 'default'
    return seq - pr.FRR_FIRST_RULE_SEQ


def wire(block):
    '''A route's path and communities as the target sees them: the peer's own
    AS in front of the block's path.'''
    return (1001 + block.peer,) + block.as_path, block.communities


def policy_of(rules, match, hit, peers=2, prefixes=4, length=32):
    return ip.build_policy(rules, match, hit, peers, prefixes, length,
                           (PEERING,))


# --- the tests -------------------------------------------------------------------

class TestEquivalence:
    '''Every route of a rendered table meets the same statement on BIRD, FRR
    and the model.'''

    @pytest.mark.parametrize('peers,prefixes,length', ORACLE_SHAPES)
    @pytest.mark.parametrize('hit', ip.POLICY_HITS)
    @pytest.mark.parametrize('match', ip.POLICY_MATCHES)
    def test_bird_frr_and_the_model_decide_every_route_alike(
            self, match, hit, peers, prefixes, length):
        policy = ip.build_policy(6, match, hit, peers, prefixes, length,
                                 (PEERING,))
        bird = read_bird(pr.render_bird_policy(policy))
        lists, entries = read_frr(pr.render_frr_policy(policy))
        peer_paths = rendered_peer_paths(peers, prefixes, length)
        accepted = [0] * peers
        for block in ip.policy_blocks(peers, prefixes):
            path, comms = wire(block)
            for route in block_routes(block, peer_paths):
                net = ipaddress.IPv4Network(route)
                model = evaluate(policy, block, route)
                b_action, b_index = run_bird(bird, net, path, comms)
                f_action, f_seq = run_frr(lists, entries, net, path, comms)
                assert (b_action, bird_who(b_index, policy)) == model
                assert (f_action, frr_who(f_seq, policy)) == model
                accepted[block.peer] += model[0] == ip.ACCEPT
        assert tuple(accepted) == \
            ip.expected_counts(6, peers, prefixes).accepted_per_peer

    @pytest.mark.parametrize('match', ['as-path', 'community'])
    def test_a_rule_finds_its_value_anywhere_on_the_route(self, match):
        '''Containment, not position: a matcher that looked only at the first
        ASN, or only at the first community, would miss every class value.'''
        policy = policy_of(1, match, 'first')
        bird = read_bird(pr.render_bird_policy(policy))
        lists, entries = read_frr(pr.render_frr_policy(policy))
        net = ipaddress.IPv4Network('100.0.0.0/32')
        if match == 'as-path':
            routes = [((ip.ACCEPT_PATH_ASN,), ()),
                      ((7, ip.ACCEPT_PATH_ASN, 9), ()),
                      ((7, 9, ip.ACCEPT_PATH_ASN), ())]
        else:
            accept = (ip.COMMUNITY_CLASS_ASN, ip.ACCEPT_COMMUNITY_VALUE)
            routes = [((7,), (accept,)),
                      ((7,), ((1, 1), accept)),
                      ((7,), ((1, 1), (2, 2), accept))]
        for path, comms in routes:
            assert run_bird(bird, net, path, comms) == (ip.ACCEPT, 1)
            assert run_frr(lists, entries, net, path, comms) == (ip.ACCEPT, 2)

    def test_an_asn_is_matched_whole_not_as_a_substring(self):
        '''FRR's `_` anchors the regex at path boundaries; without it
        `4200000001` would match inside `14200000001`.'''
        policy = policy_of(1, 'as-path', 'first')
        lists, entries = read_frr(pr.render_frr_policy(policy))
        net = ipaddress.IPv4Network('100.0.0.0/32')
        for path in [(1, 14200000001), (1, 42000000012), (1, 142000000010)]:
            assert run_frr(lists, entries, net, path, ()) == (ip.ACCEPT, 3)
        assert run_frr(lists, entries, net, (1, ip.ACCEPT_PATH_ASN), ()) \
            == (ip.ACCEPT, 2)

    @pytest.mark.parametrize('length', [32, 24])
    def test_a_prefix_rule_takes_only_the_run_length(self, length):
        '''A route inside a cover but of another length falls through to the
        default in both renderings.'''
        policy = policy_of(1, 'prefix', 'first', length=length)
        bird = read_bird(pr.render_bird_policy(policy))
        lists, entries = read_frr(pr.render_frr_policy(policy))
        cover = ipaddress.IPv4Network(policy.rules[0].values[0])
        other = 31 if length == 32 else 25
        if other < cover.prefixlen:
            pytest.skip('no shorter route lies inside a /{0}'.format(
                cover.prefixlen))
        net = next(cover.subnets(new_prefix=other)) if other > cover.prefixlen \
            else cover.supernet(new_prefix=other)
        assert run_bird(bird, net, (1,), ()) == (ip.ACCEPT, 2)
        assert run_frr(lists, entries, net, (1,), ()) == (ip.ACCEPT, 3)


class TestShape:
    @pytest.mark.parametrize('hit', ip.POLICY_HITS)
    @pytest.mark.parametrize('match', ip.POLICY_MATCHES)
    def test_one_test_per_statement_in_each_language(self, match, hit):
        rules = 7
        policy = policy_of(rules, match, hit)
        bird = pr.render_bird_policy(policy).split('\n')
        assert sum(1 for line in bird if line.startswith('  if ')) == rules + 1
        frr = pr.render_frr_policy(policy).split('\n')
        entries = [line for line in frr if line.startswith('route-map ')]
        matches = [line for line in frr if line.startswith(' match ')]
        assert len(entries) == rules + 2
        assert len(matches) == rules + 1
        # Every entry but the default matches a list of its own.
        assert len(set(matches)) == len(matches)

    @pytest.mark.parametrize('match', ip.POLICY_MATCHES)
    def test_lists_are_defined_before_the_route_map(self, match):
        frr = pr.render_frr_policy(policy_of(3, match, 'last')).split('\n')
        first_entry = next(i for i, line in enumerate(frr)
                           if line.startswith('route-map '))
        assert not any(line.startswith(('ip ', 'bgp '))
                       for line in frr[first_entry:])

    def test_the_largest_policy_ends_on_frrs_last_entry_number(self):
        policy = ip.build_policy(ip.MAX_POLICY_RULES, 'community', 'miss', 1,
                                 4, 32)
        assert pr.frr_default_seq(policy) == pr.FRR_MAX_SEQ
        last = None
        for line in pr.frr_policy_lines(policy):
            last = line
        assert last == 'route-map {0} permit {1}\n'.format(
            pr.FRR_ROUTE_MAP, pr.FRR_MAX_SEQ)

    def test_lines_come_one_at_a_time(self):
        for render in (pr.bird_policy_lines, pr.frr_policy_lines):
            for line in render(policy_of(5, 'prefix', 'last', length=24)):
                assert line.endswith('\n') and line.count('\n') == 1


class TestExactText:
    def test_prefix_at_32(self):
        policy = policy_of(3, 'prefix', 'last')
        assert pr.render_bird_policy(policy) == (
            'filter bgperf_import_policy\n'
            '{\n'
            '  if net ~ [ 100.0.0.3/32{32,32}, 100.0.0.7/32{32,32} ] then reject;\n'
            '  if net ~ [ 240.0.0.0/32{32,32} ] then reject;\n'
            '  if net ~ [ 240.0.0.1/32{32,32} ] then reject;\n'
            '  if net ~ [ 100.0.0.0/31{32,32}, 100.0.0.2/32{32,32}, '
            '100.0.0.4/31{32,32}, 100.0.0.6/32{32,32} ] then accept;\n'
            '  accept;\n'
            '}\n')
        assert pr.render_frr_policy(policy) == (
            'ip prefix-list BGPERF-IMPORT-G permit 100.0.0.3/32\n'
            'ip prefix-list BGPERF-IMPORT-G permit 100.0.0.7/32\n'
            'ip prefix-list BGPERF-IMPORT-R0 permit 240.0.0.0/32\n'
            'ip prefix-list BGPERF-IMPORT-R1 permit 240.0.0.1/32\n'
            'ip prefix-list BGPERF-IMPORT-R2 permit 100.0.0.0/31 ge 32 le 32\n'
            'ip prefix-list BGPERF-IMPORT-R2 permit 100.0.0.2/32\n'
            'ip prefix-list BGPERF-IMPORT-R2 permit 100.0.0.4/31 ge 32 le 32\n'
            'ip prefix-list BGPERF-IMPORT-R2 permit 100.0.0.6/32\n'
            'route-map BGPERF-IMPORT deny 1\n'
            ' match ip address prefix-list BGPERF-IMPORT-G\n'
            'route-map BGPERF-IMPORT deny 2\n'
            ' match ip address prefix-list BGPERF-IMPORT-R0\n'
            'route-map BGPERF-IMPORT deny 3\n'
            ' match ip address prefix-list BGPERF-IMPORT-R1\n'
            'route-map BGPERF-IMPORT permit 4\n'
            ' match ip address prefix-list BGPERF-IMPORT-R2\n'
            'route-map BGPERF-IMPORT permit 5\n')

    def test_prefix_at_24(self):
        policy = ip.build_policy(2, 'prefix', 'first', 2, 8, 24, (PEERING,))
        assert pr.render_bird_policy(policy) == (
            'filter bgperf_import_policy\n'
            '{\n'
            '  if net ~ [ 1.0.6.0/23{24,24}, 1.0.14.0/23{24,24} ] then reject;\n'
            '  if net ~ [ 1.0.0.0/22{24,24}, 1.0.4.0/23{24,24}, '
            '1.0.8.0/22{24,24}, 1.0.12.0/23{24,24} ] then accept;\n'
            '  if net ~ [ 240.0.1.0/24{24,24} ] then reject;\n'
            '  accept;\n'
            '}\n')
        assert pr.render_frr_policy(policy) == (
            'ip prefix-list BGPERF-IMPORT-G permit 1.0.6.0/23 ge 24 le 24\n'
            'ip prefix-list BGPERF-IMPORT-G permit 1.0.14.0/23 ge 24 le 24\n'
            'ip prefix-list BGPERF-IMPORT-R0 permit 1.0.0.0/22 ge 24 le 24\n'
            'ip prefix-list BGPERF-IMPORT-R0 permit 1.0.4.0/23 ge 24 le 24\n'
            'ip prefix-list BGPERF-IMPORT-R0 permit 1.0.8.0/22 ge 24 le 24\n'
            'ip prefix-list BGPERF-IMPORT-R0 permit 1.0.12.0/23 ge 24 le 24\n'
            'ip prefix-list BGPERF-IMPORT-R1 permit 240.0.1.0/24\n'
            'route-map BGPERF-IMPORT deny 1\n'
            ' match ip address prefix-list BGPERF-IMPORT-G\n'
            'route-map BGPERF-IMPORT permit 2\n'
            ' match ip address prefix-list BGPERF-IMPORT-R0\n'
            'route-map BGPERF-IMPORT deny 3\n'
            ' match ip address prefix-list BGPERF-IMPORT-R1\n'
            'route-map BGPERF-IMPORT permit 4\n')

    def test_as_path(self):
        policy = policy_of(3, 'as-path', 'last')
        assert pr.render_bird_policy(policy) == (
            'filter bgperf_import_policy\n'
            '{\n'
            '  if bgp_path ~ [= * 4200000002 * =] then reject;\n'
            '  if bgp_path ~ [= * 4220000000 * =] then reject;\n'
            '  if bgp_path ~ [= * 4220000001 * =] then reject;\n'
            '  if bgp_path ~ [= * 4200000001 * =] then accept;\n'
            '  accept;\n'
            '}\n')
        assert pr.render_frr_policy(policy) == (
            'bgp as-path access-list BGPERF-IMPORT-G permit _4200000002_\n'
            'bgp as-path access-list BGPERF-IMPORT-R0 permit _4220000000_\n'
            'bgp as-path access-list BGPERF-IMPORT-R1 permit _4220000001_\n'
            'bgp as-path access-list BGPERF-IMPORT-R2 permit _4200000001_\n'
            'route-map BGPERF-IMPORT deny 1\n'
            ' match as-path BGPERF-IMPORT-G\n'
            'route-map BGPERF-IMPORT deny 2\n'
            ' match as-path BGPERF-IMPORT-R0\n'
            'route-map BGPERF-IMPORT deny 3\n'
            ' match as-path BGPERF-IMPORT-R1\n'
            'route-map BGPERF-IMPORT permit 4\n'
            ' match as-path BGPERF-IMPORT-R2\n'
            'route-map BGPERF-IMPORT permit 5\n')

    def test_community(self):
        policy = policy_of(3, 'community', 'last')
        assert pr.render_bird_policy(policy) == (
            'filter bgperf_import_policy\n'
            '{\n'
            '  if (64512, 2) ~ bgp_community then reject;\n'
            '  if (64514, 0) ~ bgp_community then reject;\n'
            '  if (64514, 1) ~ bgp_community then reject;\n'
            '  if (64512, 1) ~ bgp_community then accept;\n'
            '  accept;\n'
            '}\n')
        assert pr.render_frr_policy(policy) == (
            'bgp community-list standard BGPERF-IMPORT-G permit 64512:2\n'
            'bgp community-list standard BGPERF-IMPORT-R0 permit 64514:0\n'
            'bgp community-list standard BGPERF-IMPORT-R1 permit 64514:1\n'
            'bgp community-list standard BGPERF-IMPORT-R2 permit 64512:1\n'
            'route-map BGPERF-IMPORT deny 1\n'
            ' match community BGPERF-IMPORT-G\n'
            'route-map BGPERF-IMPORT deny 2\n'
            ' match community BGPERF-IMPORT-R0\n'
            'route-map BGPERF-IMPORT deny 3\n'
            ' match community BGPERF-IMPORT-R1\n'
            'route-map BGPERF-IMPORT permit 4\n'
            ' match community BGPERF-IMPORT-R2\n'
            'route-map BGPERF-IMPORT permit 5\n')

    def test_miss_decides_by_the_default(self):
        policy = policy_of(2, 'community', 'miss')
        assert pr.render_bird_policy(policy) == (
            'filter bgperf_import_policy\n'
            '{\n'
            '  if (64512, 2) ~ bgp_community then reject;\n'
            '  if (64514, 0) ~ bgp_community then reject;\n'
            '  if (64514, 1) ~ bgp_community then reject;\n'
            '  accept;\n'
            '}\n')


class TestSize:
    @pytest.mark.parametrize('match', ip.POLICY_MATCHES)
    def test_bytes_are_the_rendered_text_and_rules_are_n(self, match):
        policy = policy_of(9, match, 'last', length=24)
        for lines, render in ((pr.bird_policy_lines, pr.render_bird_policy),
                              (pr.frr_policy_lines, pr.render_frr_policy)):
            size = pr.rendered_size(policy, lines(policy))
            assert size == pr.RenderedSize(
                rules=9, bytes=len(render(policy).encode('utf-8')))


class TestRefusals:
    def test_more_rules_than_frr_can_number(self):
        policy = ip.build_policy(ip.MAX_POLICY_RULES, 'community', 'miss', 1,
                                 4, 32)
        extra = ip.Rule(position=ip.MAX_POLICY_RULES, action=ip.REJECT,
                        values=((ip.COMMUNITY_FILLER_ASN, 65533),))
        bigger = dataclasses.replace(policy, rules=policy.rules + (extra,))
        for render in (pr.render_bird_policy, pr.render_frr_policy):
            with pytest.raises(pr.PolicyRenderError, match='65,534 rules'):
                render(bigger)

    def test_a_rule_with_no_values(self):
        policy = policy_of(2, 'as-path', 'first')
        empty = dataclasses.replace(policy.rules[1], values=())
        broken = dataclasses.replace(policy,
                                     rules=(policy.rules[0], empty))
        with pytest.raises(pr.PolicyRenderError, match='at least one value'):
            pr.render_bird_policy(broken)

    def test_an_unknown_match(self):
        policy = dataclasses.replace(policy_of(2, 'as-path', 'first'),
                                     match='large-community')
        with pytest.raises(pr.PolicyRenderError, match='large-community'):
            pr.render_frr_policy(policy)

    def test_an_unknown_action(self):
        policy = policy_of(2, 'as-path', 'first')
        odd = dataclasses.replace(policy.rules[1], action='continue')
        with pytest.raises(pr.PolicyRenderError, match='continue'):
            pr.render_bird_policy(dataclasses.replace(
                policy, rules=(policy.rules[0], odd)))

    def test_a_cover_longer_than_the_routes(self):
        policy = policy_of(1, 'prefix', 'first', length=24)
        odd = dataclasses.replace(policy.rules[0], values=('1.0.0.0/25',))
        for render in (pr.render_frr_policy, pr.render_bird_policy):
            with pytest.raises(pr.PolicyRenderError, match='/25 cover'):
                render(dataclasses.replace(policy, rules=(odd,)))

    @pytest.mark.parametrize('positions', [(1, 0), (0, 0), (0, 2), (-1, 0)])
    def test_rule_positions_out_of_order(self, positions):
        policy = policy_of(2, 'as-path', 'first')
        rules = tuple(dataclasses.replace(rule, position=p)
                      for rule, p in zip(policy.rules, positions))
        for render in (pr.render_frr_policy, pr.render_bird_policy):
            with pytest.raises(pr.PolicyRenderError, match='positions'):
                render(dataclasses.replace(policy, rules=rules))

    def test_a_guard_with_a_position(self):
        policy = policy_of(1, 'as-path', 'first')
        guard = dataclasses.replace(policy.guard, position=0)
        for render in (pr.render_frr_policy, pr.render_bird_policy):
            with pytest.raises(pr.PolicyRenderError, match='positions'):
                render(dataclasses.replace(policy, guard=guard))
