# Copyright (C) 2026 bgperf2 contributors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

'''Native BIRD and FRR text for a generated import policy.

`import_policy.build_policy()` builds the policy; this module writes it in each
daemon's own language and nothing else. It reads no scenario, attaches nothing
to a session and runs no daemon: placing the text in a target's config and
naming it on the sessions is the lifecycle's job.

**The two renderings must make each daemon do the same work.** Each policy
statement becomes exactly one test in each language, in the model's order --
guard, the `N` generated rules, then the default -- so a route meets the same
number of tests on BIRD and on FRR, and both stop at the same one:

- BIRD: one `filter`, one `if <test> then accept|reject;` per statement and a
  final `accept;`.
- FRR: one `route-map`, one entry per statement, each matching one list of its
  own, and a final `permit` entry with no match. FRR numbers entries 1 to
  65535, which is why `import_policy.MAX_POLICY_RULES` is 65533.

A statement holding several values tests them as one set in both: a BIRD
prefix set or `||` chain, an FRR list of several lines. The tests are:

- **prefix**: inside a covering CIDR *and* exactly the run's length -- BIRD
  `net ~ [P{L,L}]`, FRR `P ge L le L`, or plain `P` when the cover is itself
  `/L`, since FRR refuses a `ge` equal to the prefix's own length.
- **as-path**: the path **contains** the ASN anywhere -- BIRD's path mask
  `[= * A * =]`, FRR's boundary-anchored regex `_A_`. Neither stops at the
  first ASN, and the block's own ASN sits in front of the class ASN on every
  path, so a matcher that did would fail every rule.
- **community**: the route carries the standard community -- BIRD
  `(a, b) ~ bgp_community`, FRR a `standard` community-list line `a:b`. One
  line per value: a single FRR line naming two communities requires both.

The text is produced line by line, so a large policy is never held as one
string twice; `render_*()` joins it for callers that want a string.
'''

import ipaddress
from dataclasses import dataclass

import import_policy as _import_policy


BIRD_FILTER_NAME = 'bgperf_import_policy'
FRR_ROUTE_MAP = 'BGPERF-IMPORT'
FRR_GUARD_LIST = FRR_ROUTE_MAP + '-G'

# FRR route-map entry numbers: the guard first, then rule `i` at
# `FRR_FIRST_RULE_SEQ + i`, then the default.
FRR_GUARD_SEQ = 1
FRR_FIRST_RULE_SEQ = 2
FRR_MAX_SEQ = 65535


class PolicyRenderError(ValueError):
    '''Raised for a policy a renderer cannot write.'''


def frr_rule_list(position):
    '''The FRR list generated rule `position` matches.'''
    return '{0}-R{1}'.format(FRR_ROUTE_MAP, position)


def frr_default_seq(policy):
    return FRR_FIRST_RULE_SEQ + len(policy.rules)


def _statements(policy):
    '''The guard, then every generated rule, each with its FRR list name.'''
    yield FRR_GUARD_LIST, FRR_GUARD_SEQ, policy.guard
    for rule in policy.rules:
        yield (frr_rule_list(rule.position),
               FRR_FIRST_RULE_SEQ + rule.position, rule)


def _check(policy):
    if policy.match not in _import_policy.POLICY_MATCHES:
        raise PolicyRenderError(
            'no renderer for policy match {0!r}'.format(policy.match))
    for rule in (policy.guard,) + tuple(policy.rules):
        if rule.action not in (_import_policy.ACCEPT, _import_policy.REJECT):
            raise PolicyRenderError(
                'no rendering for rule action {0!r}'.format(rule.action))
        if not rule.values:
            # An empty set matches nothing in BIRD and is a syntax error or a
            # match-everything in FRR, depending on the list type.
            raise PolicyRenderError(
                'a policy rule must name at least one value')
    if policy.default_action not in (_import_policy.ACCEPT,
                                     _import_policy.REJECT):
        raise PolicyRenderError(
            'no rendering for default action {0!r}'.format(
                policy.default_action))
    # FRR's entry numbers come from the positions, so they must be the model's
    # own 0..N-1 in order, or FRR would merge or reorder entries BIRD keeps.
    if policy.guard.position is not None or \
            [rule.position for rule in policy.rules] != \
            list(range(len(policy.rules))):
        raise PolicyRenderError(
            'policy rules must sit at positions 0 to N-1 in order, '
            'and the guard at none')
    if frr_default_seq(policy) > FRR_MAX_SEQ:
        raise PolicyRenderError(
            'FRR numbers route-map entries up to {0}, and {1:,} rules need '
            '{2:,}'.format(FRR_MAX_SEQ, len(policy.rules),
                           frr_default_seq(policy)))
    if policy.match == 'prefix':
        # Checked for both daemons, so neither renders a policy the other
        # refuses.
        for rule in (policy.guard,) + tuple(policy.rules):
            for value in rule.values:
                _prefix_cover(value, policy.prefix_length)


def _prefix_cover(value, length):
    net = ipaddress.IPv4Network(value)
    if net.prefixlen > length:
        raise PolicyRenderError(
            'a /{0} cover cannot hold /{1} routes'.format(net.prefixlen,
                                                          length))
    return net


# --- BIRD --------------------------------------------------------------------

def _bird_test(policy, rule):
    if policy.match == 'prefix':
        return 'net ~ [ {0} ]'.format(', '.join(
            '{0}{{{1},{1}}}'.format(v, policy.prefix_length)
            for v in rule.values))
    if policy.match == 'as-path':
        return ' || '.join('bgp_path ~ [= * {0} * =]'.format(int(asn))
                           for asn in rule.values)
    return ' || '.join('({0}, {1}) ~ bgp_community'.format(int(a), int(b))
                       for a, b in rule.values)


def bird_policy_lines(policy):
    '''The policy as one BIRD `filter`, line by line, newline-terminated.'''
    _check(policy)
    yield 'filter {0}\n'.format(BIRD_FILTER_NAME)
    yield '{\n'
    for _, _, rule in _statements(policy):
        yield '  if {0} then {1};\n'.format(_bird_test(policy, rule),
                                            rule.action)
    yield '  {0};\n'.format(policy.default_action)
    yield '}\n'


def render_bird_policy(policy):
    return ''.join(bird_policy_lines(policy))


# --- FRR ---------------------------------------------------------------------

_FRR_ACTION = {_import_policy.ACCEPT: 'permit',
               _import_policy.REJECT: 'deny'}


def _frr_prefix_entry(value, length):
    net = _prefix_cover(value, length)
    if net.prefixlen == length:
        return str(net)
    return '{0} ge {1} le {1}'.format(net, length)


def _frr_list_lines(policy, name, rule):
    if policy.match == 'prefix':
        for value in rule.values:
            yield 'ip prefix-list {0} permit {1}\n'.format(
                name, _frr_prefix_entry(value, policy.prefix_length))
    elif policy.match == 'as-path':
        for asn in rule.values:
            yield 'bgp as-path access-list {0} permit _{1}_\n'.format(
                name, int(asn))
    else:
        for a, b in rule.values:
            yield 'bgp community-list standard {0} permit {1}:{2}\n'.format(
                name, int(a), int(b))


_FRR_MATCH = {'prefix': 'match ip address prefix-list {0}\n',
              'as-path': 'match as-path {0}\n',
              'community': 'match community {0}\n'}


def frr_policy_lines(policy):
    '''The policy as FRR lists and one `route-map`, line by line.

    The lists come first, because a route-map entry names a list that must
    already exist when the config is read.
    '''
    _check(policy)
    statements = list(_statements(policy))
    for name, _, rule in statements:
        yield from _frr_list_lines(policy, name, rule)
    for name, seq, rule in statements:
        yield 'route-map {0} {1} {2}\n'.format(
            FRR_ROUTE_MAP, _FRR_ACTION[rule.action], seq)
        yield ' ' + _FRR_MATCH[policy.match].format(name)
    yield 'route-map {0} {1} {2}\n'.format(
        FRR_ROUTE_MAP, _FRR_ACTION[policy.default_action],
        frr_default_seq(policy))


def render_frr_policy(policy):
    return ''.join(frr_policy_lines(policy))


# --- size ----------------------------------------------------------------------

@dataclass(frozen=True)
class RenderedSize:
    '''How big a rendered policy is: generated rules, and bytes of text.

    `rules` is the measured dimension, `N`, and excludes the guard and the
    default. `bytes` is the rendered text's UTF-8 length, which differs between
    daemons for one policy: it describes what the daemon had to parse, not
    how much work evaluating it is.
    '''

    rules: int
    bytes: int


def rendered_size(policy, lines):
    '''The size of `lines`, a rendering of `policy`, consumed as counted.'''
    return RenderedSize(rules=len(policy.rules),
                        bytes=sum(len(line.encode('utf-8')) for line in lines))
