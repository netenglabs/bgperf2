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

'''A generated import policy, and what a target applying it must accept.

Policy phase 1 measures what an import policy costs a daemon that is loading a
table. This module is the daemon-free half of that: from the command line
alone -- rule count, match type, hit position, peers and prefixes per peer --
it builds the rules, the attributes each block of the table carries, and the
exact number of prefixes a target must accept, per peer and in total. No seed
and no external file is involved, so a reader can rebuild all of it from the
row. It renders nothing: native BIRD and FRR text is the renderers' job, and
an abstract policy is what lets their fixture tests show the two select the
same blocks.

**The shape is fixed, and only three things vary.** Every peer's prefix list is
cut into `BLOCKS_PER_PEER` contiguous blocks, and the last block of every peer
is rejected. The policy is evaluated in this order:

1. the **rejection guard**, which matches exactly the rejected blocks and
   rejects them;
2. the `N` **generated rules**, the measured dimension, in order;
3. the **default action**, accept.

The guard is outside the `N` because of `miss`. Under `miss` no generated rule
may match any route, so a policy made of generated rules alone would decide
every route by its one default action -- and a policy that rejects nothing
cannot be told from a daemon that ignored it, while one that rejects
everything cannot be told from a target with no sessions. Something outside
the `N` must therefore reject the fixed fraction, and it goes *first*: the
rejected routes leave there, so every route that reaches the generated rules
meets them exactly as `hit` says. With `first` the first generated rule
decides; with `last` every generated rule before the last is evaluated and
fails; with `miss` all `N` fail and the default decides. Placed last, the
guard would make every rejected route evaluate all `N` rules whatever `hit`
was, and diluted the very difference `hit` exists to show.

The guard uses the run's own match type. A policy mixing match types is a
non-goal of the phase, and a guard of another type would put a second match
type's cost into every run.

**Why the tail of every peer, not the tail of the fleet.** Rejecting whole
peers would leave some peer with an expected accepted count of 0, and a peer
whose every route was rejected cannot be told from a session that delivered
nothing -- the argument `policy.rejected_block_indexes()` makes for the whole
table, applied to each neighbour's own checkpoint. The tail rather than a
sample is churn's determinism rule.
'''

import ipaddress
from dataclasses import dataclass
from typing import Optional, Tuple

import prefix_length as _prefix_length


# Today's run, with no policy.
DEFAULT_POLICY_RULES = 0

# The most generated rules a policy may have, set by the tightest renderer so
# that every daemon can run every rule count. FRR numbers route-map entries
# 1 to 65535, and its rendering needs one entry for the guard, one per rule and
# one for the default action. (Every match type could supply more: a standard
# community's value half is 16 bits.)
MAX_POLICY_RULES = 65533

POLICY_MATCHES = ('prefix', 'as-path', 'community')
POLICY_HITS = ('first', 'last', 'miss')

ACCEPT = 'accept'
REJECT = 'reject'

# Every generated rule that is not the deciding one, and the guard, reject;
# the deciding rule and the default accept. The default is the same on every
# daemon and every hit position.
DEFAULT_ACTION = ACCEPT

# Each peer's list is cut into this many contiguous blocks, the last of which
# is rejected: a quarter of the blocks, and a quarter of the prefixes when the
# per-peer count divides by four (otherwise slightly less, since the larger
# blocks come first). Exact either way, because `expected_counts()` uses the
# block sizes themselves.
BLOCKS_PER_PEER = 4
REJECTED_BLOCKS_PER_PEER = 1

# A block's index goes into a standard community's 16-bit value half, which
# caps the fleet at 65,536 blocks.
MAX_BLOCKS = 1 << 16

# The generated AS-path values, all in the private 32-bit range
# (4200000000-4294967294) so none can be a peer's, the target's or the
# monitor's AS. Each block's path is `(BLOCK_ASN_BASE + block, class ASN)`,
# prepended by the generator; the peer's own AS goes in front of it on the
# wire. The block's own ASN is there so a block is identifiable on the wire and
# so the ASN a rule looks for is not the only one on the path: a matcher that
# stopped at the first ASN would otherwise look the same as one that scans.
ACCEPT_PATH_ASN = 4200000001
REJECT_PATH_ASN = 4200000002
BLOCK_PATH_ASN_BASE = 4210000000
FILLER_PATH_ASN_BASE = 4220000000

# The generated standard communities, `(ASN, value)` with private 16-bit ASNs.
# Each block carries its own `(COMMUNITY_BLOCK_ASN, block)` and its class's
# `(COMMUNITY_CLASS_ASN, ACCEPT_VALUE or REJECT_VALUE)`, for the reason a path
# carries two ASNs.
COMMUNITY_CLASS_ASN = 64512
COMMUNITY_BLOCK_ASN = 64513
COMMUNITY_FILLER_ASN = 64514
ACCEPT_COMMUNITY_VALUE = 1
REJECT_COMMUNITY_VALUE = 2

# Where a prefix rule that must match nothing draws its values: class E space,
# which neither the historical /32 walk (100.0.0.0 to 160.0.0.0) nor the
# shorter walks (below multicast) ever reach.
FILLER_PREFIX_SPACE = ipaddress.IPv4Network('240.0.0.0/4')


class ImportPolicyConfigurationError(ValueError):
    '''Raised for an import policy that cannot be built.'''


def _whole_number(name, value, minimum=0, maximum=None):
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum \
            or (maximum is not None and value > maximum):
        bound = ('between {0} and {1}'.format(minimum, maximum)
                 if maximum is not None
                 else '{0} or more'.format(minimum))
        raise ImportPolicyConfigurationError(
            '{0} must be a whole number {1}, got {2!r}'.format(
                name, bound, value))
    return value


def _check_fleet(peers, prefixes):
    _whole_number('peers', peers, minimum=1)
    _whole_number('prefixes per peer', prefixes, minimum=1)
    if prefixes < BLOCKS_PER_PEER:
        # A peer with fewer prefixes than blocks has an empty block, and the
        # last one is the rejected one: the policy would reject nothing that
        # peer offered and its expected count would equal its offered count.
        raise ImportPolicyConfigurationError(
            'an import policy cuts each peer\'s prefixes into {0} blocks and '
            'rejects the last, so it needs at least {0} prefixes per peer, '
            'got {1}'.format(BLOCKS_PER_PEER, prefixes))
    if peers * BLOCKS_PER_PEER > MAX_BLOCKS:
        raise ImportPolicyConfigurationError(
            'an import policy numbers its blocks in a 16-bit community value, '
            'so it supports at most {0:,} peers, got {1:,}'.format(
                MAX_BLOCKS // BLOCKS_PER_PEER, peers))


def _check_rules(rules, match, hit):
    _whole_number('policy rules', rules, minimum=1, maximum=MAX_POLICY_RULES)
    if match not in POLICY_MATCHES:
        raise ImportPolicyConfigurationError(
            'policy match must be one of {0}, got {1!r}'.format(
                ', '.join(POLICY_MATCHES), match))
    if hit not in POLICY_HITS:
        raise ImportPolicyConfigurationError(
            'policy hit must be one of {0}, got {1!r}'.format(
                ', '.join(POLICY_HITS), hit))


def block_sizes(prefixes):
    '''How many prefixes each of one peer's blocks holds, in list order.

    Contiguous and as equal as the count allows, the larger blocks first, so
    the rejected (last) block is never the larger one.
    '''
    _whole_number('prefixes per peer', prefixes, minimum=BLOCKS_PER_PEER)
    size, extra = divmod(prefixes, BLOCKS_PER_PEER)
    return tuple(size + 1 if i < extra else size
                 for i in range(BLOCKS_PER_PEER))


@dataclass(frozen=True)
class Block:
    '''One contiguous block of one peer's prefixes, and what it carries.

    `peer` is the position of the peer's slice in the walk: slice `k` is walk
    entries `k * prefixes` onwards. It is **not** the peer's position in AS
    order. The rendered scenario draws slices in the order its neighbours
    appear, and `yaml.dump` sorts them by router-id *text*, so from ten peers
    on the AS-1010 peer holds slice 0. A generator finds its own blocks by
    cutting its own `paths` with `block_sizes()`, and the slice index from
    where its first path sits in the walk; it never infers either from its AS.
    `first` is the block's first entry in the run's prefix walk, `count` its
    size.
    '''

    index: int
    peer: int
    position: int
    first: int
    count: int
    rejected: bool
    as_path: Tuple[int, ...]
    communities: Tuple[Tuple[int, int], ...]


def policy_blocks(peers, prefixes):
    '''Every block of the fleet's table, in walk order.

    Independent of the rule count, the match type and the hit position: the
    generator carries the same attributes whatever the policy, so changing the
    policy never changes what the generator sends.
    '''
    _check_fleet(peers, prefixes)
    sizes = block_sizes(prefixes)
    blocks = []
    for peer in range(peers):
        first = peer * prefixes
        for position, count in enumerate(sizes):
            index = peer * BLOCKS_PER_PEER + position
            rejected = position >= BLOCKS_PER_PEER - REJECTED_BLOCKS_PER_PEER
            blocks.append(Block(
                index=index, peer=peer, position=position, first=first,
                count=count, rejected=rejected,
                as_path=(BLOCK_PATH_ASN_BASE + index,
                         REJECT_PATH_ASN if rejected else ACCEPT_PATH_ASN),
                communities=(
                    (COMMUNITY_BLOCK_ASN, index),
                    (COMMUNITY_CLASS_ASN,
                     REJECT_COMMUNITY_VALUE if rejected
                     else ACCEPT_COMMUNITY_VALUE)),
            ))
            first += count
    return tuple(blocks)


def resolve_tester_attributes(enabled, tester_type='bird', path_diversity=1,
                              churn_prefixes=0, filter_test=None,
                              policy_reload_blocks=0, peers=None,
                              prefixes=None, scenario_filters=()):
    '''Whether the generator carries per-block attributes, or why it cannot.

    `--tester-attributes` makes the BIRD generator send every block with the
    AS path and communities `policy_blocks()` gives it, with no policy on the
    target, so the cost of carrying them can be measured on its own. It is
    refused wherever the blocks cannot be what the model says:

    - **any generator but BIRD**: ExaBGP has no per-block filter and an MRT
      generator plays back a file's own attributes;
    - **`--path-diversity`**: a prefix shared by a group would be one block
      to one peer and another to the next;
    - **churn**: its tail block would cut across the policy's blocks;
    - **`filter_test`**: the generated ASNs are private, so a bogon filter
      would reject every route;
    - **`--policy-reload-blocks`**, or the scenario `filter` matrix
      (`-a`, `-e`, `-c`, `-x`, named in `scenario_filters`): a policy on the
      target is a second variable in a run meant to measure the generator;
    - **a fleet the blocks cannot number**: fewer than `BLOCKS_PER_PEER`
      prefixes per peer, or more blocks than a community value holds.

    Raises `ImportPolicyConfigurationError`, whose message names the flag.
    '''
    if enabled in (None, False):
        return False
    if enabled is not True:
        raise ImportPolicyConfigurationError(
            '--tester-attributes must be true or false, got {0!r}'.format(
                enabled))
    if (tester_type or 'bird') != 'bird':
        raise ImportPolicyConfigurationError(
            '--tester-attributes needs the BIRD generator: the {0!r} tester '
            'cannot set attributes per block'.format(tester_type))
    if (path_diversity or 1) != 1:
        raise ImportPolicyConfigurationError(
            '--tester-attributes and --path-diversity are not defined '
            'together: a prefix several peers share would carry a different '
            "block's attributes from each")
    if churn_prefixes:
        raise ImportPolicyConfigurationError(
            '--tester-attributes and --churn-prefixes are not defined '
            "together: the churn block would cut across the policy's blocks")
    if filter_test not in (None, 'None'):
        raise ImportPolicyConfigurationError(
            '--tester-attributes and --filter_test {0} are not defined '
            'together: the generated ASNs are private, so the bogon filter '
            'would reject every route'.format(filter_test))
    if policy_reload_blocks:
        raise ImportPolicyConfigurationError(
            '--tester-attributes and --policy-reload-blocks are not defined '
            'together: a second policy on the target is a second variable')
    if scenario_filters:
        raise ImportPolicyConfigurationError(
            '--tester-attributes and {0} are not defined together: they put '
            'a policy on the target, a second variable in a run measuring '
            'the generator'.format(', '.join(scenario_filters)))
    if peers is not None and prefixes is not None:
        try:
            _check_fleet(peers, prefixes)
        except ImportPolicyConfigurationError as e:
            raise ImportPolicyConfigurationError(
                '--tester-attributes: {0}'.format(e)) from e
    return True


def scenario_policy_blocks(router_ids, prefixes):
    '''Each neighbour's blocks as the scenario carries them, keyed by router-id.

    The generator renders these as given and derives nothing, so what it
    announces is exactly what `policy_blocks()` modelled. Slices are dealt in
    sorted router-id *text* order because that is the order the rendered
    scenario draws them in: `yaml.dump` sorts the neighbour mapping before Mako
    evaluates a single `gen_paths()`. Dealing them in any other order would
    give a neighbour the attributes of a slice it does not announce.

    Each entry is `{'count', 'as-path', 'communities'}` in the peer's list
    order: `as-path` is outermost first, as it appears on the wire after the
    peer's own AS, and `communities` are `[ASN, value]` pairs.
    '''
    router_ids = sorted(router_ids)
    blocks = policy_blocks(len(router_ids), prefixes)
    scenario = {rid: [] for rid in router_ids}
    for block in blocks:
        scenario[router_ids[block.peer]].append({
            'count': block.count,
            'as-path': list(block.as_path),
            'communities': [list(c) for c in block.communities],
        })
    return scenario


@dataclass(frozen=True)
class ExpectedCounts:
    '''What the fleet offers and what a target applying the policy accepts.

    Per-peer tuples are indexed by walk slice (see `Block`), and every entry
    is the same, so a caller may pair them with neighbours in any order. With
    no policy every offered prefix is expected, which is today's checkpoint.
    '''

    offered_per_peer: Tuple[int, ...]
    accepted_per_peer: Tuple[int, ...]

    @property
    def offered(self):
        return sum(self.offered_per_peer)

    @property
    def accepted(self):
        return sum(self.accepted_per_peer)

    @property
    def rejected(self):
        return self.offered - self.accepted


def expected_counts(rules, peers, prefixes):
    '''The exact accepted count, per peer and in total.

    It depends on the fleet alone: the generated rules decide only the routes
    the guard let through, and every one of those is accepted whether the
    deciding rule or the default accepts it. That is what makes it a guard
    against unequal work across match types and hit positions -- every cell
    of one fleet shape expects the same count.
    '''
    _whole_number('policy rules', rules, maximum=MAX_POLICY_RULES)
    if not rules:
        _whole_number('peers', peers, minimum=1)
        _whole_number('prefixes per peer', prefixes, minimum=1)
        return ExpectedCounts(offered_per_peer=(prefixes,) * peers,
                              accepted_per_peer=(prefixes,) * peers)
    accepted = [0] * peers
    for block in policy_blocks(peers, prefixes):
        if not block.rejected:
            accepted[block.peer] += block.count
    return ExpectedCounts(offered_per_peer=(prefixes,) * peers,
                          accepted_per_peer=tuple(accepted))


@dataclass(frozen=True)
class Rule:
    '''One terminating rule: if a route matches any of `values`, `action`.

    `values` are ASNs for `as-path` (the rule matches a path containing one),
    `(ASN, value)` pairs for `community` (a route carrying one), and CIDR
    strings for `prefix` (a route whose prefix lies inside one and is exactly
    the run's prefix length long). `position` is the rule's place among the
    generated rules, and `None` for the guard.
    '''

    position: Optional[int]
    action: str
    values: Tuple


@dataclass(frozen=True)
class ImportPolicy:
    '''A generated import policy, renderer-independent.

    Evaluated as `guard`, then `rules` in order, then `default_action`.
    `deciding` is the position of the generated rule the accepted routes
    meet, or `None` under `miss`.
    '''

    match: str
    hit: str
    prefix_length: int
    guard: Rule
    rules: Tuple[Rule, ...]
    default_action: str
    deciding: Optional[int]


def _cover(ranges):
    '''The fewest CIDRs whose union is exactly these address ranges.'''
    cidrs = []
    for start, end in ranges:
        cidrs.extend(str(net) for net in ipaddress.summarize_address_range(
            ipaddress.IPv4Address(start), ipaddress.IPv4Address(end - 1)))
    return tuple(cidrs)


def _blocks_cover(blocks, length, exclude):
    ranges = []
    for block in blocks:
        ranges.extend(_prefix_length.walk_address_ranges(
            length, block.first, block.count, exclude))
    # Adjacent blocks of one class merge into one range, so the cover is no
    # larger than the address layout needs.
    merged = []
    for start, end in sorted(ranges):
        if merged and start == merged[-1][1]:
            merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))
    return _cover(merged)


def _filler_values(match, position, length):
    '''A value for generated rule `position` that no route in the table has.'''
    if match == 'as-path':
        return (FILLER_PATH_ASN_BASE + position,)
    if match == 'community':
        return ((COMMUNITY_FILLER_ASN, position),)
    size = 1 << (32 - length)
    base = int(FILLER_PREFIX_SPACE.network_address) + position * size
    return ('{0}/{1}'.format(ipaddress.IPv4Address(base), length),)


def build_policy(rules, match, hit, peers, prefixes, prefix_length=None,
                 exclude=()):
    '''The import policy for one run, deterministic from its arguments alone.

    `prefix_length` and `exclude` only shape the `prefix` match type, whose
    rules name the walk's own addresses. `exclude` must be exactly what the
    run's walk skips -- `prefix_length.walk_exclusions()` over the peering
    subnet and the explicitly set target and monitor addresses, the list
    `gen_conf()` renders with -- or every cover after the first difference is
    shifted onto the wrong prefixes. The length is validated for every type,
    so a run's arguments are checked the same way whatever it matches on.
    '''
    _check_rules(rules, match, hit)
    _check_fleet(peers, prefixes)
    length = (_prefix_length.DEFAULT_PREFIX_LENGTH if prefix_length is None
              else prefix_length)
    if not _prefix_length._is_whole_number(length) \
            or length not in _prefix_length.SUPPORTED_PREFIX_LENGTHS:
        raise ImportPolicyConfigurationError(
            'prefix length must be one of {0}, got {1!r}'.format(
                ', '.join(str(n) for n in
                          _prefix_length.SUPPORTED_PREFIX_LENGTHS),
                prefix_length))
    blocks = policy_blocks(peers, prefixes)
    accepted = [b for b in blocks if not b.rejected]
    rejected = [b for b in blocks if b.rejected]

    if match == 'as-path':
        accept_values = (ACCEPT_PATH_ASN,)
        guard_values = (REJECT_PATH_ASN,)
    elif match == 'community':
        accept_values = ((COMMUNITY_CLASS_ASN, ACCEPT_COMMUNITY_VALUE),)
        guard_values = ((COMMUNITY_CLASS_ASN, REJECT_COMMUNITY_VALUE),)
    else:
        try:
            accept_values = _blocks_cover(accepted, length, exclude)
            guard_values = _blocks_cover(rejected, length, exclude)
        except ValueError as e:
            raise ImportPolicyConfigurationError(str(e)) from e

    deciding = {'first': 0, 'last': rules - 1, 'miss': None}[hit]
    generated = tuple(
        Rule(position=i, action=ACCEPT, values=accept_values) if i == deciding
        else Rule(position=i, action=REJECT,
                  values=_filler_values(match, i, length))
        for i in range(rules))
    return ImportPolicy(
        match=match, hit=hit, prefix_length=length,
        guard=Rule(position=None, action=REJECT, values=guard_values),
        rules=generated, default_action=DEFAULT_ACTION, deciding=deciding)
