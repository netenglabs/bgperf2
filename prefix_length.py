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


# The one generator a shorter prefix is generated for. ExaBGP's route writer
# would take any length, but its images are unpinned at both the interpreter
# and the ExaBGP release and report no version, so a run on one cannot say
# which generator it measured; and the policy workload's per-block attributes
# are BIRD static-protocol export filters, which ExaBGP has no equivalent of.
PREFIX_LENGTH_TESTER_TYPES = ('bird',)


def resolve_prefix_length(length, tester_type=None, distinct_prefixes=None,
                          local_address_prefix=None, mrt_tester_types=(),
                          prefix_list_num=0):
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
    if distinct_prefixes is not None:
        exclude = (local_address_prefix,) if local_address_prefix else ()
        available = capacity(length, exclude)
        if distinct_prefixes > available:
            raise ValueError(
                '--prefix-length {0} can supply {1:,} distinct prefixes from '
                'public unicast space and this table needs {2:,}; use fewer '
                'peers or prefixes per peer'.format(
                    length, available, distinct_prefixes))
    return length
