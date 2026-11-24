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

'''How long each synthetic prefix is, and where the table is drawn from.

Every synthetic table bgperf2 has generated is `/32` host routes walked up
from 100.0.0.0, and that walk is left exactly as it is: it has been running
long enough that a 50 x 100,000 table already walks through 100.64.0.0/10, so
"skipping reserved space" at `/32` would change the prefixes of runs that have
been published. `/32` is the default and renders the scenario it always has.

A shorter length is a different table shape -- a prefix-list over `/24`s does
not cost what one over `/32`s does, and real tables are mostly `/24` and
shorter -- so it is a workload of its own. Its walk is drawn from public
unicast space with the special-purpose ranges taken out, because a daemon may
treat a loopback or link-local prefix as invalid and drop it without counting
it, and the run would then read as a target that lost routes. The run's own
peering subnet is taken out too: a route covering it would capture the next
hop every route in the run is announced with.

Docker-free and bgperf2-free, like `policy.py` and `churn.py`, so the walk and
its refusals are covered by a suite that needs no daemon. The scenario's Mako
preamble imports this module to draw the walk, so what a run announces and
what the capacity check counted are one piece of code.
'''

import ipaddress
import re


# Every synthetic run before this control existed, and the one rendered
# unchanged.
DEFAULT_PREFIX_LENGTH = 32

# What may be asked for. 24 is the most common length in a real table; others
# are refused rather than guessed at until something needs them.
SUPPORTED_PREFIX_LENGTHS = (24, 32)

# The space a shorter-than-/32 walk is drawn from: 1.0.0.0 up to, and not
# including, the multicast block.
WALK_START = int(ipaddress.IPv4Address('1.0.0.0'))
WALK_END = int(ipaddress.IPv4Address('224.0.0.0'))

# Special-purpose IPv4 space (RFC 6890 and the usual bogon list) taken out of
# the walk. Each is a range a daemon or its default policy may treat as
# invalid, and a prefix dropped without being counted is a convergence
# shortfall nobody asked for.
RESERVED_NETWORKS = (
    '0.0.0.0/8',          # "this network"
    '10.0.0.0/8',         # RFC 1918
    '100.64.0.0/10',      # RFC 6598 shared address space
    '127.0.0.0/8',        # loopback
    '169.254.0.0/16',     # link local
    '172.16.0.0/12',      # RFC 1918
    '192.0.0.0/24',       # IETF protocol assignments
    '192.0.2.0/24',       # TEST-NET-1
    '192.88.99.0/24',     # 6to4 relay anycast
    '192.168.0.0/16',     # RFC 1918
    '198.18.0.0/15',      # benchmarking
    '198.51.100.0/24',    # TEST-NET-2
    '203.0.113.0/24',     # TEST-NET-3
    '224.0.0.0/3',        # multicast, reserved and broadcast
)


def _is_whole_number(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _excluded_spans(length, exclude):
    '''The integer ranges no prefix of `length` may start in, merged.

    A network shorter than `length` is taken out whole. A network longer than
    it -- a `/28` peering subnet under a `/24` walk -- takes out the whole
    `length` block containing it, since any prefix of that length overlapping
    the subnet covers it.
    '''
    size = 1 << (32 - length)
    spans = []
    for network in tuple(RESERVED_NETWORKS) + tuple(exclude or ()):
        net = ipaddress.IPv4Network(network, strict=False)
        start = int(net.network_address) // size * size
        end = -(-(int(net.broadcast_address) + 1) // size) * size
        spans.append((start, end))
    spans.sort()
    merged = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _allowed_spans(length, exclude):
    spans = []
    cursor = WALK_START
    for start, end in _excluded_spans(length, exclude):
        if end <= cursor:
            continue
        if start > cursor:
            spans.append((cursor, min(start, WALK_END)))
        cursor = max(cursor, end)
        if cursor >= WALK_END:
            break
    if cursor < WALK_END:
        spans.append((cursor, WALK_END))
    return [(s, e) for s, e in spans if e > s]


def _check_walk_length(length):
    if length == DEFAULT_PREFIX_LENGTH:
        # The /32 walk is the historical one in `gen_mako_macro()` and is not
        # drawn from here; offering a second /32 walk would be two definitions
        # of the table every published run used.
        raise ValueError('the /32 walk is the historical one in the scenario '
                         'preamble and is not drawn from this module')
    if length not in SUPPORTED_PREFIX_LENGTHS:
        raise ValueError('unsupported prefix length {0!r}'.format(length))


def walk(length, exclude=()):
    '''Every `/length` prefix the table may use, in ascending order, as text.

    Deterministic from `length` and `exclude` alone, so two runs of one cell
    announce the same prefixes and nothing needs a seed.
    '''
    _check_walk_length(length)
    size = 1 << (32 - length)
    for start, end in _allowed_spans(length, exclude):
        for base in range(start, end, size):
            yield '{0}/{1}'.format(ipaddress.IPv4Address(base), length)


def capacity(length, exclude=()):
    '''How many distinct prefixes the walk at `length` can supply.'''
    _check_walk_length(length)
    size = 1 << (32 - length)
    return sum((end - start) // size
               for start, end in _allowed_spans(length, exclude))


# The historical `/32` walk, stated as bounds so a policy can name a slice of
# it without generating it. These are not a second definition of that walk:
# `gen_mako_macro()` holds it, and the suite renders that preamble and checks
# these bounds against what it announces.
HISTORICAL_WALK_FIRST = int(ipaddress.IPv4Address('100.0.0.0'))
# `iter_iprange()` includes its upper bound.
HISTORICAL_WALK_LAST = int(ipaddress.IPv4Address('160.0.0.0'))


def walk_address_ranges(length, first, count, exclude=()):
    '''The address ranges holding walk entries `first` .. `first + count - 1`.

    Half-open `(start, end)` integer ranges in ascending order, whose union is
    exactly those `count` prefixes' addresses. One range unless the slice
    crosses a span the walk skips. Works at every supported length, the
    historical `/32` walk included, so a prefix-matching policy can cover a
    block of the table without enumerating it.

    `exclude` does not apply at `/32`, whose walk skips nothing.
    '''
    if not _is_whole_number(first) or first < 0:
        raise ValueError('walk index must be a whole number of 0 or more, '
                         'got {0!r}'.format(first))
    if not _is_whole_number(count) or count < 1:
        raise ValueError('walk slice must hold at least one prefix, '
                         'got {0!r}'.format(count))
    if length == DEFAULT_PREFIX_LENGTH:
        start = HISTORICAL_WALK_FIRST + first
        if start + count - 1 > HISTORICAL_WALK_LAST:
            raise ValueError('the /32 walk ends at {0} and cannot supply '
                             'entries {1} to {2}'.format(
                                 ipaddress.IPv4Address(HISTORICAL_WALK_LAST),
                                 first, first + count - 1))
        return [(start, start + count)]
    _check_walk_length(length)
    size = 1 << (32 - length)
    ranges = []
    skip, remaining = first, count
    for start, end in _allowed_spans(length, exclude):
        held = (end - start) // size
        if skip >= held:
            skip -= held
            continue
        take = min(held - skip, remaining)
        lo = start + skip * size
        ranges.append((lo, lo + take * size))
        remaining -= take
        skip = 0
        if not remaining:
            return ranges
    raise ValueError('the /{0} walk can supply {1:,} prefixes and cannot '
                     'supply entries {2} to {3}'.format(
                         length, capacity(length, exclude), first,
                         first + count - 1))


# The one generator a shorter prefix is generated for. ExaBGP's route writer
# would take any length, but its images are unpinned at both the interpreter
# and the ExaBGP release and report no version, so a run on one cannot say
# which generator it measured; and the policy workload's per-block attributes
# are BIRD static-protocol export filters, which ExaBGP has no equivalent of.
PREFIX_LENGTH_TESTER_TYPES = ('bird',)


def walk_exclusions(local_address_prefix=None, addresses=()):
    '''Everything a shorter walk must stay clear of beyond reserved space.

    The run's peering subnet, and any target or monitor address configured
    explicitly -- one outside that subnet is allowed, and a `/24` covering it
    would capture the next hop of the session it carries partway through the
    run. Unset addresses are skipped; the defaults lie inside the subnet.
    One helper, so `gen_conf()`'s walk and every capacity check exclude the
    same space.
    '''
    exclude = [str(local_address_prefix)] if local_address_prefix else []
    exclude.extend(str(ipaddress.IPv4Address(str(a))) + '/32'
                   for a in addresses if a)
    return tuple(exclude)


# A generator config's announced route: BIRD's `route P via A;` and ExaBGP's
# `route P next-hop A;` are the forms bgperf2 writes. Any line opening with
# `route` is taken as one, so a form nobody expected is refused rather than
# skipped.
_ROUTE_LINE = re.compile(r'^\s*route\s+(\S+)')


def announced_prefix_length(lines):
    '''The length of the first route a generator config announces, or None.

    Every synthetic route a generator holds has one length, so the first is
    the table's. Reads only up to it: a config holds one line per prefix.
    A route whose prefix cannot be read raises `ValueError`: skipping it
    would let the check that asked pass without having been made.
    '''
    for line in lines:
        match = _ROUTE_LINE.match(line)
        if match:
            try:
                return ipaddress.ip_network(match.group(1),
                                            strict=False).prefixlen
            except ValueError:
                raise ValueError('unreadable route {0!r}'.format(
                    line.strip())) from None
    return None


def resolve_prefix_length(length, tester_type=None, distinct_prefixes=None,
                          local_address_prefix=None, mrt_tester_types=(),
                          prefix_list_num=0, filter_test=None, addresses=()):
    '''The validated prefix length, checked before any container starts.

    Refused rather than interpreted, each because it would otherwise be
    silent:

    - **Anything not in `SUPPORTED_PREFIX_LENGTHS`**, including a quoted value
      from a batch yaml and `True`, which is an `int` in Python.
    - **An MRT generator**: it plays back the file's own prefixes and nothing
      is synthesised, so a length here would be recorded in the manifest of a
      run that had none.
    - **Any other synthetic generator** (see `PREFIX_LENGTH_TESTER_TYPES`).
    - **`-e/--prefix-list-num`**: its entries are `/32`s from 90.0.0.0, so
      at another length they could never match a route, and a large walk
      runs through 90.0.0.0/8 and would cover them. It would publish the
      cost of a list unlike the table it was measured against.
    - **A `--filter_test` policy**: `filters/*` were written against `/32`
      tables and select by length -- `ixp` drops anything longer than `/24`,
      so at `/32` it rejects the whole table and at `/24` it accepts all of
      it, and the two runs would differ by more than the length they name.
    - **A table larger than the walk can supply**, which would otherwise end
      with the generators announcing fewer prefixes than the check-point the
      monitor waits for.

    `distinct_prefixes` is the number of distinct prefixes the fleet offers --
    blocks times prefixes per peer -- and is only checked when given.
    '''
    if length is None:
        return DEFAULT_PREFIX_LENGTH
    if not _is_whole_number(length) or length not in SUPPORTED_PREFIX_LENGTHS:
        raise ValueError(
            '--prefix-length must be one of {0}, got {1!r}'.format(
                ', '.join(str(n) for n in SUPPORTED_PREFIX_LENGTHS), length))
    if length == DEFAULT_PREFIX_LENGTH:
        # Every run before this control existed. None of the refusals below
        # may fire on it, or they refuse runs that predate the flag.
        return DEFAULT_PREFIX_LENGTH
    if tester_type in mrt_tester_types:
        raise ValueError(
            "--prefix-length does not apply to the '{0}' tester: it plays "
            'back an MRT file, so its prefixes are whatever that file holds '
            'and none of them are generated here'.format(tester_type))
    if tester_type is not None and tester_type not in PREFIX_LENGTH_TESTER_TYPES:
        raise ValueError(
            "--prefix-length {0} is generated only by the {1} tester, not "
            "'{2}'".format(length, ' or '.join(PREFIX_LENGTH_TESTER_TYPES),
                           tester_type))
    if prefix_list_num:
        raise ValueError(
            '--prefix-length {0} cannot be used with -e/--prefix-list-num: '
            'its entries are /32s and would match none of a /{0} '
            'table'.format(length))
    if filter_test not in (None, 'None'):
        raise ValueError(
            '--prefix-length {0} cannot be used with --filter_test {1}: the '
            'filters select by prefix length, so the same filter does '
            'different work on a /{0} table than on a /32 one'.format(
                length, filter_test))
    if distinct_prefixes is not None:
        exclude = walk_exclusions(local_address_prefix, addresses)
        available = capacity(length, exclude)
        if distinct_prefixes > available:
            raise ValueError(
                '--prefix-length {0} can supply {1:,} distinct prefixes from '
                'public unicast space and this table needs {2:,}; use fewer '
                'peers or prefixes per peer'.format(
                    length, available, distinct_prefixes))
    return length
