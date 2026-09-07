#!/usr/bin/env python3
#
# Copyright (C) 2015, 2016 Nippon Telegraph and Telephone Corporation.
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

import argparse
import hashlib
import json
import os
import random
import sys
import threading
import yaml
import time
import shutil
import netaddr
import datetime
from collections import defaultdict
from pathlib import Path
from argparse import ArgumentParser, REMAINDER
from itertools import chain, islice
from requests.exceptions import ConnectionError
from pyroute2 import IPRoute
from socket import AF_INET
from nsenter import Namespace
from psutil import virtual_memory
from subprocess import check_output
import matplotlib.pyplot as plt
import numpy as np
from base import *
from exabgp import ExaBGP, ExaBGP_MRTParse
from gobgp import GoBGP, GoBGPTarget
from bird import BIRD, BIRDTarget
from frr import FRRoutingTarget
from frr_compiled import FRRoutingCompiled, FRRoutingCompiledTarget
from rustybgp import RustyBGP, RustyBGPTarget
from openbgp import OpenBGP, OpenBGPTarget
from flock import Flock, FlockTarget
from srlinux import SRLinux, SRLinuxTarget
from junos import Junos, JunosTarget
from eos import Eos, EosTarget
from tester import ExaBGPTester, BIRDTester
from mrt_tester import GoBGPMRTTester, ExaBGPMrtTester
from bgpdump2 import Bgpdump2, Bgpdump2Tester
from monitor import Monitor
from convergence import ConvergenceTracker
from contention import (describe_contention, foreign_cpu_percent,
                        free_space_bytes, is_memory_backed, own_process_tree,
                        sample_processes)
from findings import derive_findings, describe_findings, policy_failure
from measurements import (MonitorEventRecorder, TesterEventRecorder,
                          event_artifact, monitor_metrics,
                          tester_fleet_metrics, tester_metrics)
from settings import dckr
from summary import describe_batch_summary, summarize_batch
from queue import Queue
from mako.template import Template
from packaging import version
from docker.types import IPAMConfig, IPAMPool
import re

# The daemons bgperf2 can build images for, keyed by the name used on the
# command line (`update <name>`) and in batch yaml. Adding a daemon here is
# what makes `prepare`, `update`, `doctor` and --version know about it.
BUILDABLE_IMAGES = {
    'exabgp': ExaBGP,
    'exabgp_mrtparse': ExaBGP_MRTParse,
    'gobgp': GoBGP,
    'bird': BIRD,
    'rustybgp': RustyBGP,
    'openbgp': OpenBGP,
    'flock': Flock,
    'frr_c': FRRoutingCompiled,
    'bgpdump2': Bgpdump2,
}

# What `prepare` builds, in order. Flock and the commercial NOSes are left out:
# they are downloaded rather than compiled.
PREPARE_IMAGES = ['exabgp', 'exabgp_mrtparse', 'gobgp', 'bird', 'rustybgp',
                  'openbgp', 'frr_c', 'bgpdump2']

# Targets `bench -t` accepts. The class both selects the daemon's behaviour and
# supplies the image naming used to resolve --version.
# The class each image runs as when it is a load generator rather than the
# target. `verify` probes through these so it exercises the MRO bench really
# builds -- probing a daemon base class is exactly the blind spot that let
# rustybgp read its version with GoBGP's parser: correct on the base, wrong
# through the real subclass.
TESTER_CLASSES = {
    'exabgp': ExaBGPTester,
    'exabgp_mrtparse': ExaBGPMrtTester,
    'bgpdump2': Bgpdump2Tester,
    'bird': BIRDTester,
    'gobgp': GoBGPMRTTester,
}

TARGET_CLASSES = {
    'gobgp': GoBGPTarget,
    'bird': BIRDTarget,
    'frr_c': FRRoutingCompiledTarget,
    'rustybgp': RustyBGPTarget,
    'openbgp': OpenBGPTarget,
    'flock': FlockTarget,
    'srlinux': SRLinuxTarget,
    'junos': JunosTarget,
    'eos': EosTarget,
}


def target_image(target, version=None, image=None):
    '''Resolve the docker image a bench run should use.

    An explicit --image always wins -- it is the escape hatch for an image
    bgperf2 did not build. Otherwise the version selects a tag, and a missing
    one raises ImageNotBuilt with the command that would create it.
    '''
    if image:
        return image
    return TARGET_CLASSES[target].require_image(version)


def run_name(args):
    '''Name a run for the CSV and for graph filenames.

    An explicit label wins; otherwise a version has to appear in the name or
    two versions of the same daemon are indistinguishable in the results.

    A repetition is part of a run's identity, not a footnote to it: this is the
    CSV's name column and the label on every graph bar, and `bench_output_prefix()`
    builds each of the run's filenames from it, so two passes of one cell sharing
    a name leaves two rows nothing can tell apart and has the second replace the
    first's files. `batch()` sets `repetition` only when a test asks for more than
    one pass, so a single-pass batch keeps the names it has always had -- and the
    cell id agrees with it, or resume can mix the two.
    '''
    name = args.target
    if 'label' in args and args.label:
        name = args.label
    else:
        version = getattr(args, 'version', None)
        if version:
            name = '{0} {1}'.format(args.target, version)
    repetition = getattr(args, 'repetition', None)
    if repetition:
        name = '{0} #{1}'.format(name, repetition)
    return name


def bench_output_prefix(args):
    '''The filename stem every artifact a run writes is built from.

    One function because a run's evidence is only preserved if every piece of
    it is named by the same dimensions: `<prefix>.events.json`,
    `<prefix>.versions.json` and the per-run PNGs are written with `os.replace`
    or a plain `open(..., 'w')`, so any dimension the batch iterates and this
    stem omits means the last cell along it silently replaces the others.

    `filter_test` is one of those dimensions -- `benchmarks/2026-filters.yaml`
    runs the same target and table under three policies -- and it is appended
    only when set, so an unfiltered run keeps the name it has always had.
    '''
    parts = [run_name(args).replace(' ', '_'),
             str(getattr(args, 'tester_type', None)),
             str(args.prefix_num),
             str(args.neighbor_num)]
    filter_test = getattr(args, 'filter_test', None)
    if filter_test:
        parts.append(str(filter_test).replace(' ', '_'))
    # Path diversity is the other dimension a batch can hold constant per test
    # while two tests in one config differ along it, and nothing else in this
    # stem carries it -- the peer count and the per-peer prefix count are the
    # same for a disjoint run and a run whose peers compete. Appended only when
    # it is not the default, so an existing run keeps the name it has always
    # had.
    diversity = getattr(args, 'path_diversity', None) or DEFAULT_PATH_DIVERSITY
    if diversity != DEFAULT_PATH_DIVERSITY:
        parts.append('pd{0}'.format(diversity))
    return '_'.join(parts)


# How `-p/--prefix-num` is read. `per-peer` is what bgperf has always meant by
# it, and multiplies: `-n 50 -p 100000` is five million routes. `total` reads it
# as the whole table and splits it across the sessions.
PREFIX_SCOPES = ('per-peer', 'total')

# Generators that play back an MRT file rather than synthesising prefixes. For
# these `-p` is already the size of the whole table -- `gen_conf()` sets the
# monitor check-point from it directly rather than multiplying -- so a scope
# has nothing to divide and asking for one is a mistake worth naming.
MRT_TESTER_TYPES = ('gobgp', 'bgpdump2')

# Every generator `-g` accepts, and the single source for the CLI's `choices`.
# `gen_conf()` branches on `not in ('exa', 'bird')` rather than on
# MRT_TESTER_TYPES, so an unrecognised value is treated as an MRT injector: a
# typo'd `tester_type: brid` on a batch target -- which bypasses argparse
# entirely -- reached that branch and died at its bare `exit(1)`, taking the
# rest of the matrix with it.
SYNTHETIC_TESTER_TYPES = ('exa', 'bird')
TESTER_TYPES = SYNTHETIC_TESTER_TYPES + MRT_TESTER_TYPES


def resolve_prefix_scope(scope, neighbor_num, prefix_num, tester_type=None):
    """The per-peer prefix count a run should generate, from what was asked for.

    Sessions and table size are one axis today, and that is the gap this
    closes. `gen_conf()` gives every neighbour its own `gen_paths(p)` off a
    shared iterator, so the peers get disjoint prefixes and the table is
    `n * p`: a batch sweeping `neighbors: [10, 25, 50]` at a fixed `prefixes`
    is sweeping the table size at the same time, and nothing downstream can
    separate "50 sessions were slower" from "five times the routes were
    slower". `2026-core-synth.yaml` is exactly this shape -- its four cells
    hold 500k, 1M, 2.5M and 5M routes.

    Under `total` the peer count moves and the table does not. The result is
    normalised to a per-peer count here, before anything reads it, because
    `-n 50 -p 100000 --prefix-scope total` and `-n 50 -p 2000` are the same
    workload and must produce the same row: the CSV column is called
    `prefixes per peer`, `bench_output_prefix()` names artifacts from
    `prefix_num`, and `create_graph()` groups bars by it. A scope that
    survived into those would have to be a new dimension in all three.

    The division has to be exact, and an inexact one is refused rather than
    rounded or spread. A remainder means the peers do not all offer the same
    table, so `prefixes per peer` is a number that is not true of any of them,
    each neighbour's `check-points` differs, and the monitor's own check-point
    stops being `n * p`. Refusing costs a message before the first container;
    the alternative is a column that quietly means something else for those
    rows.
    """
    if scope in (None, 'per-peer'):
        return prefix_num
    if scope not in PREFIX_SCOPES:
        raise ValueError("unknown prefix scope '{0}': expected one of {1}".format(
            scope, ', '.join(PREFIX_SCOPES)))
    if tester_type in MRT_TESTER_TYPES:
        raise ValueError(
            "--prefix-scope total does not apply to the '{0}' tester: it plays "
            'back an MRT file, so -p is already the whole table and there is '
            'nothing to divide across the peers'.format(tester_type))
    if neighbor_num < 1:
        raise ValueError('--prefix-scope total needs at least one peer to '
                         'divide the table across, got {0}'.format(neighbor_num))
    if prefix_num < neighbor_num:
        raise ValueError(
            '--prefix-scope total: {0} prefixes across {1} peers leaves peers '
            'with none. A session that offers nothing is not a peer under '
            'test'.format(prefix_num, neighbor_num))
    if prefix_num % neighbor_num:
        per_peer = prefix_num // neighbor_num
        # Prefix counts always -- both are exact by construction. Peer counts
        # only where a usable one exists, since a table with no divisor near
        # the asked-for count has nothing to offer and saying so is better
        # than naming one nobody would run.
        peers = _divisors_near(prefix_num, neighbor_num)
        advice = "use {0} or {1} prefixes".format(
            per_peer * neighbor_num, (per_peer + 1) * neighbor_num)
        if peers:
            advice += ', or {0} peers'.format(
                ' or '.join(str(n) for n in peers))
        raise ValueError(
            '--prefix-scope total: {0} prefixes do not divide evenly across '
            '{1} peers ({2} each, {3} left over). An uneven split makes the '
            "CSV's `prefixes per peer` untrue of every peer; {4}".format(
                prefix_num, neighbor_num, per_peer, prefix_num % neighbor_num,
                advice))
    return prefix_num // neighbor_num


# How far *above* the asked-for peer count the search will look -- a distance,
# not an absolute ceiling. Only the upward half needs bounding: the scan
# otherwise walked to `prefix_num` itself, offering five million peers after a
# fifth of a second of searching, and a suggestion far above what the operator
# asked for is not one whatever it costs. Downward it is already bounded by the
# asked-for count, and a divisor below that is by construction a number the
# operator was willing to be near -- 1443 for someone who asked for 1500 is
# useful advice, so it is deliberately not capped.
MAX_SUGGESTED_PEERS = 512


def _is_positive_count(value):
    """A whole number of 1 or more, the one rule both entry points apply.

    `True` is an `int` in Python and is not a peer count.
    """
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _divisors_near(prefix_num, neighbor_num):
    """Peer counts closest to the one asked for that divide this table.

    A message that only says the division failed leaves the operator doing
    arithmetic on a 1,050,000-prefix RIB; a workable number either side is the
    whole fix. One peer is excluded for the same reason a five-million-peer
    suggestion is: a suggestion the operator cannot act on is worse than none,
    because it reads as the tool having thought about it.
    """
    # Never past two prefixes per peer, at either end: a peer count equal to
    # the table size divides it exactly and offers each session a single
    # route, which is the same kind of unusable advice as suggesting five
    # million peers, and the next divisor down is the first that is not.  Only
    # reachable on a table small enough to be within MAX_SUGGESTED_PEERS of
    # the asked-for count.
    most = prefix_num // 2
    below = next((n for n in range(min(neighbor_num - 1, most), 1, -1)
                  if prefix_num % n == 0), None)
    # A distance above the asked-for count, not an absolute cap: an absolute
    # one offers nothing at all to anybody who asked for more than it, so a
    # 513-peer request got no upward suggestion even though 625 divides.
    ceiling = min(most, neighbor_num + MAX_SUGGESTED_PEERS)
    above = next((n for n in range(neighbor_num + 1, ceiling + 1)
                  if prefix_num % n == 0), None)
    return [n for n in (below, above) if n]


# How many peers announce each block of prefixes. 1 is what bgperf has always
# generated: every peer takes its own block off the shared iterator, so the
# peers are disjoint and the table is `n * p`. Above 1 the peers are grouped and
# every peer in a group announces the *same* block, so the target holds that
# many competing paths for each of those prefixes and has to select between
# them -- which is the work `n * p` disjoint prefixes never asks it to do.
DEFAULT_PATH_DIVERSITY = 1


def path_diversity_groups(neighbor_num, diversity):
    """How many distinct prefix blocks a fleet of this shape announces.

    The one place this arithmetic lives, because two things a hundred lines
    apart have to agree about it: the block `gen_conf()` gives each neighbour,
    and the monitor's check-point. The monitor counts what the target
    *re-advertises*, which is one best path per prefix -- so the check-point is
    the number of distinct prefixes, `groups * p`, and not the number offered,
    `n * p`. Wrong in one direction it is a run that can never converge and
    polls until `STUCK_SAMPLES`; wrong in the other it reports CONVERGED on a
    fraction of the table, which is the failure with no symptom.

    It refuses an inexact division rather than truncating it. Every operator
    path reaches `resolve_path_diversity()` first and gets a message naming
    peer counts that work, so a raise here is a rule that was applied nowhere
    -- and the alternative is a fleet whose last group announces a block with
    fewer competing paths than the rest, silently.
    """
    if not _is_positive_count(diversity) or neighbor_num % diversity:
        raise ValueError(
            'path diversity {0!r} does not divide {1!r} peers into equal '
            'groups'.format(diversity, neighbor_num))
    return neighbor_num // diversity


def _diversity_divisors_near(neighbor_num, diversity):
    """Group sizes closest to the one asked for that divide this fleet.

    Both ends are usable here and neither needs the bounding
    `_divisors_near()` applies to peer counts: 1 is the disjoint workload
    bgperf has always run and `neighbor_num` itself is every peer announcing
    one shared block, so both are answers rather than degenerate advice. The
    search is over the divisors of a peer count rather than of a full-table
    RIB, so it is cheap enough to enumerate whole.
    """
    divisors = [d for d in range(1, neighbor_num + 1) if neighbor_num % d == 0]
    below = max((d for d in divisors if d < diversity), default=None)
    above = min((d for d in divisors if d > diversity), default=None)
    return [d for d in (below, above) if d]


def resolve_path_diversity(diversity, neighbor_num, tester_type=None,
                           prefix_scope=None):
    """How many peers announce each prefix block, checked before any container.

    `gen_conf()` has only ever generated disjoint prefixes, so every peer under
    test announces routes nobody else has and the target never runs a best-path
    selection between competing paths. That is not what a router does with a
    full table: the same prefix arrives from several neighbours and the work is
    choosing between them, holding the losers, and re-running the choice when
    one is withdrawn. A benchmark that never presents a second path for a
    prefix measures reception and re-advertisement and calls it convergence.

    Above 1 the peers are dealt into groups of `diversity` and each group
    announces one shared block, so the fleet offers `n * p` paths for
    `(n / diversity) * p` distinct prefixes.

    Four things are refused rather than interpreted, and each is silent if it
    is not:

    - **An MRT generator**, where `gen_conf()` synthesises no paths at all --
      the diversity of an MRT run is whatever the file holds -- and the monitor
      check-point comes straight from `-p`. Accepting it would print a
      diversity into the manifest of a run that had none.
    - **`--prefix-scope total`**, because `the whole table` then has two
      readings that differ by exactly this number: the paths offered, and the
      distinct prefixes the target ends up holding. Both are defensible and
      neither is written down, so the combination is refused rather than
      guessed at -- the reading would reach the `prefixes per peer` column, the
      cell identity and every artifact name.
    - **More diversity than there are peers**, which cannot be honoured at all.
    - **An inexact division**, for the same reason `resolve_prefix_scope()`
      refuses one: the remainder group announces a block with fewer competing
      paths than the rest, so `diversity` is a number true of none of the
      table, and the monitor's check-point stops being `groups * p`.

    Returns the diversity itself. `path_diversity_groups()` turns it into the
    block count, which is the number the monitor and the accounting care about.
    """
    if diversity is None:
        return DEFAULT_PATH_DIVERSITY
    if not _is_positive_count(diversity):
        raise ValueError(
            '--path-diversity must be a whole number of 1 or more, got '
            '{0!r}'.format(diversity))
    if diversity == DEFAULT_PATH_DIVERSITY:
        # The workload bgperf has always run, and the default every existing
        # command line and batch config carries implicitly. None of the
        # refusals below may fire on it or they refuse runs that predate this
        # flag entirely.
        return DEFAULT_PATH_DIVERSITY
    if tester_type in MRT_TESTER_TYPES:
        raise ValueError(
            "--path-diversity does not apply to the '{0}' tester: it plays "
            'back an MRT file, so its paths are whatever that file holds and '
            'none of them are generated here'.format(tester_type))
    # A *recognised* scope that is not the default. An unrecognised one is a
    # typo, and blaming the combination for it sends the operator to remove the
    # diversity -- after which the same `prefix_scope: totl` produces the
    # "unknown prefix scope" it should have produced first time. A refusal has
    # to name the fault, not the nearest rule it happens to trip.
    if prefix_scope in PREFIX_SCOPES and prefix_scope != 'per-peer':
        raise ValueError(
            '--path-diversity {0} and --prefix-scope {1} are not defined '
            'together: under path diversity a fleet offers n * p paths for '
            '(n / {0}) * p distinct prefixes, so `the whole table` has two '
            'readings that differ by {0} and neither is written down. State '
            'the per-peer count under the default per-peer scope '
            'instead'.format(diversity, prefix_scope))
    if not _is_positive_count(neighbor_num):
        raise ValueError(
            '--path-diversity needs a whole number of peers to group, got '
            '{0!r}'.format(neighbor_num))
    if diversity > neighbor_num:
        raise ValueError(
            '--path-diversity {0} asks {0} peers to announce each block and '
            'there are {1}'.format(diversity, neighbor_num))
    if neighbor_num % diversity:
        # There is always advice: `diversity` is at least 2 here and 1 divides
        # every peer count, so the downward end is never empty.
        groups = _diversity_divisors_near(neighbor_num, diversity)
        raise ValueError(
            '--path-diversity {0} does not divide {1} peers into equal groups '
            '({2} left over). The remainder group would announce a block with '
            'fewer competing paths than the rest, so {0} paths per prefix '
            'would be true of none of the table; use {3} instead, or a peer '
            'count that {0} divides'.format(
                diversity, neighbor_num, neighbor_num % diversity,
                ' or '.join(str(d) for d in groups)))
    return diversity


def gen_mako_macro():
    # `block` is what makes several peers announce competing paths for the same
    # prefixes: called without one, every call takes the next `num` addresses
    # off the shared iterator and the peers are disjoint, which is what bgperf
    # has always generated. Called with one, the first peer of a group cuts the
    # block and the rest of the group is handed the same list, so a group's
    # prefixes are identical and different groups stay disjoint. The argument
    # is omitted entirely at the default diversity, so what an existing run
    # *renders* is byte-identical to what it has always rendered -- only this
    # preamble differs, and nothing reads it but Mako.
    return '''<%
    import netaddr
    from itertools import islice

    it = netaddr.iter_iprange('100.0.0.0','160.0.0.0')
    blocks = {}

    def gen_paths(num, block=None):
        if block is None:
            return list('{0}/32'.format(ip) for ip in islice(it, num))
        if block not in blocks:
            blocks[block] = list('{0}/32'.format(ip) for ip in islice(it, num))
        return blocks[block]
%>
'''

def rm_line():
    #print('\x1b[1A\x1b[2K\x1b[1D\x1b[1A')
    pass


def gc_thresh3():
    gc_thresh3 = '/proc/sys/net/ipv4/neigh/default/gc_thresh3'
    with open(gc_thresh3) as f:
        return int(f.read().strip())


def doctor(args):
    ver = dckr.version()['Version']
    if ver.endswith('-ce'):
        curr_version = version.parse(ver.replace('-ce', ''))
    else:
        curr_version = version.parse(ver)
    min_version = version.parse('1.9.0')
    ok = curr_version >= min_version
    print('docker version ... {1} ({0})'.format(ver, 'ok' if ok else 'update to {} at least'.format(min_version)))

    for name in PREPARE_IMAGES:
        cls = BUILDABLE_IMAGES[name]
        built = cls.built_versions()
        print('{0} image'.format(name), end=' ')
        if img_exists(cls.image_tag()):
            print('... ok')
        else:
            print('... not found. if you want to bench {0}, run `bgperf2 prepare -t {0}`'.format(name))

        # Which versions exist matters as much as whether the daemon does --
        # a batch naming a version that was never built cannot run at all.
        extra = [v for v in built if v != 'latest']
        if extra:
            print('    versions built: {0}'.format(', '.join(extra)))
        missing = [v for v in cls.VERSIONS if sanitize_tag(v) not in built]
        if missing:
            print('    not built: {0}   (bgperf2 prepare -t {1})'.format(', '.join(missing), name))

    for name in ['flock', 'srlinux', 'junos', 'eos']:
        cls = TARGET_CLASSES[name]
        tags = cls.built_versions()
        print('{0} image ... {1}'.format(
            name, '{0} ({1})'.format(cls.IMAGE_REPO, ', '.join(tags)) if tags else 'not found'))

    print('/proc/sys/net/ipv4/neigh/default/gc_thresh3 ... {0}'.format(gc_thresh3()))


VERIFY_CONTAINER_PREFIX = 'bgperf_verify_'

# Signature of a gcov-instrumented binary, as an ERE for grep -E inside the
# image (no image is required to ship nm or strings). '.gcda' only counts where
# a non-letter follows it: a bare '\.gcda' also matches Go's runtime.gcdata and
# reported every gobgp image as instrumented.
GCOV_PATTERN = r'__gcov|\.gcda([^a-zA-Z]|$)'


def looks_like_sha(ref):
    '''A git object name, as opposed to a release number or a branch.'''
    return bool(re.fullmatch(r'[0-9a-f]{6,40}', ref))


def expect_version_in_banner(cls, version):
    '''Should the daemon's banner be expected to carry this version label?

    Only for a release the daemon names. resolve_ref() passes anything it does
    not recognize through as a raw ref, so `update gobgp --version master` is
    supported and produces bgperf/gobgp:master -- whose banner says '3.38.0' and
    never the word 'master'. Demanding a match there fails a perfectly good
    image, so a branch or a bare sha is not checked at all.
    '''
    version = str(version)
    return bool(re.fullmatch(r'\d+(\.\d+)+', version)) or version in cls.VERSIONS


def version_matches(reported, version, ref):
    '''Does `reported` look like it came from the build `version` names?

    The version is matched on a numeric boundary, not as a bare substring: a
    plain `in` makes '3.1' match 'BIRD version 3.13', so an image tagged 3.1 but
    built from v3.13 would verify clean -- the same 10.1-vs-10.10 confusion
    BatchLoader exists to prevent, in the one check meant to catch a wrong ref.
    A following '.' is still fine, because FRR 10.7 legitimately reports 10.7.0.

    The resolved ref is tried too, since a daemon's banner is not obliged to
    carry the label bgperf files it under: rustybgp 2026-02 reports
    'rustybgpd v0.2.0-0cc685c882', naming the commit rather than the label. A
    sha is matched as a prefix -- the daemon prints a longer abbreviation than
    the one written in VERSION_REFS.
    '''
    def anchored(needle):
        return re.search(r'(?<![\d.])' + re.escape(needle) + r'(?!\d)', reported)

    if anchored(version):
        return True
    for cand in (ref, ref.rsplit('/', 1)[-1], ref.lstrip('v')):
        if not cand:
            continue
        if looks_like_sha(cand):
            if cand in reported:
                return True
        elif anchored(cand):
            return True
    return False


def probe_image(cls, tag):
    '''Start a throwaway container from `tag` and ask the daemon about itself.

    Returns a list of (ok, label, detail). The container runs `sleep` rather
    than the image's own command: nothing here needs the daemon running, and
    starting it would need a config and, for some images, privileges.
    '''
    results = []
    name = VERIFY_CONTAINER_PREFIX + sanitize_tag(tag).replace('/', '_')
    if ctn_exists(name):
        dckr.remove_container(name, force=True)
    # entrypoint=[] clears the image's own: `command` is *appended* to an
    # ENTRYPOINT, not run instead of it, and exabgp and bgpdump2 both set
    # ENTRYPOINT ["/bin/bash"] -- so the container would run `bash sleep 600`,
    # fail to open a script called 'sleep', and exit while dckr.start() still
    # reported success. Every later exec would then fail with "not running" and
    # a healthy image would read as unprobeable.
    dckr.create_container(image=tag, command=['sleep', '600'], entrypoint=[],
                          detach=True, stdin_open=True, name=name)
    try:
        dckr.start(container=name)

        # The probe deliberately goes through the class bench instantiates, not
        # the daemon base class: rustybgp's version parser was only wrong via
        # RustyBGPTarget's MRO, and was correct when the base was asked directly.
        probe = cls.__new__(cls)
        probe.name = name

        if cls.VERSION_NEEDS_DAEMON:
            results.append((None, 'version', 'needs a running daemon; not probed'))
        else:
            try:
                cls.get_version_cmd(probe)
                implemented = True
            except NotImplementedError:
                implemented = False
            if not implemented:
                # A declared gap, not a broken image: some testers never grew a
                # version command. Worth showing -- provenance records UNKNOWN
                # for them -- but failing on it would make `verify` always red
                # and so worth nothing.
                results.append((None, 'version',
                                'no version command implemented; provenance records UNKNOWN'))
            else:
                reported = probe.version_string()
                ok = not reported.startswith(VERSION_UNKNOWN)
                results.append((ok, 'version', reported))

        if cls.DAEMON_BINARY:
            results.extend(check_binary(name, cls.DAEMON_BINARY))
    finally:
        dckr.remove_container(name, force=True)
    return results


def check_binary(container, path):
    '''Build-hygiene checks on the daemon binary itself.

    gcov instrumentation is the one that has actually bitten: every frr_c image
    carried it for years, so FRR was timed as an instrumented binary against
    everyone else's optimized one -- 103% CPU against 45% on identical source.
    It is invisible at runtime apart from 'profiling: ... .gcda' lines in the
    log, which read as noise.

    Detected by grep on the binary so no image needs nm or strings. The pattern
    matches the gcov runtime symbol prefix, plus '.gcda' only where a non-letter
    follows: a bare '\\.gcda' also matches Go's runtime.gcdata and reported
    every gobgp image as instrumented. Both halves were checked against a
    purpose-built pair -- gcc -fprofile-arcs -ftest-coverage scores 2, the same
    source without it scores 0 -- because a detector that never fires is worse
    than none.
    '''
    # `|| true` because grep exits 1 when the count is zero, which an earlier
    # `test -f X && grep ... || echo MISSING` turned into a bogus MISSING for
    # every clean binary.
    script = ('if [ -f {path} ]; then grep -acE \'{pat}\' {path} || true; '
              'else echo MISSING; fi').format(path=path, pat=GCOV_PATTERN)
    i = dckr.exec_create(container=container, cmd=['sh', '-c', script], stderr=True)
    out = dckr.exec_start(i['Id'], stream=False, detach=False).decode('utf-8').strip()
    if out == 'MISSING':
        return [(False, 'binary', '{0} not found in the image'.format(path))]
    try:
        hits = int(out.split()[-1])
    except (ValueError, IndexError):
        return [(None, 'binary', 'could not be checked: {0!r}'.format(out))]
    if hits:
        return [(False, 'instrumentation',
                 'gcov-instrumented ({0} matches in {1}); rebuild it, '
                 'benchmarks are not comparable'.format(hits, path))]
    return [(True, 'instrumentation', 'clean')]


def verify(args):
    '''Check that every built image reports its own version correctly.

    The test suite deliberately cannot touch Docker, so nothing else covers the
    seam where a parser meets a real container -- and that is where the bugs
    have been: rustybgp read its version with GoBGP's parser and recorded
    UNKNOWN on every run, openbgpd looked for bgpctl under a path that does not
    exist in the image. Both pass every unit test. A full bench catches them,
    but nobody runs one per change; this takes a second per image.
    '''
    names = args.target or sorted(BUILDABLE_IMAGES)
    versions = parse_versions(getattr(args, 'versions', None))
    if versions and len(names) != 1:
        sys.exit('--versions needs exactly one -t/--target: version names mean different '
                 'things to different daemons')

    failed = []
    checked = 0
    for name in names:
        buildable = BUILDABLE_IMAGES[name]
        # Probe through every class that really runs this image -- the target
        # and the tester have different MROs, and it was an MRO that broke
        # rustybgp. De-duplicated so a daemon that is only ever one role is
        # still probed once, via the base class.
        roles = []
        for label, table in (('target', TARGET_CLASSES), ('tester', TESTER_CLASSES)):
            cls = table.get(name)
            if cls is not None and cls not in [c for _, c in roles]:
                roles.append((label, cls))
        if not roles:
            roles = [('image', buildable)]

        built = buildable.built_versions()
        wanted = versions or [None if v == 'latest' else v for v in built]
        if not wanted:
            print('{0} ... nothing built'.format(name))
            continue

        print(name)
        for v in wanted:
            shown = v or 'latest'
            try:
                tag = buildable.image_tag(v)
            except VersionNotSupported:
                # Only reachable for an explicitly named version, so it is a
                # bad request rather than something to pass over quietly.
                msg = '{0} has no selectable versions'.format(name)
                print('  {0:<12} {1:<28} FAIL  {2}'.format(shown, '-', msg))
                failed.append(('{0}:{1}'.format(name, shown), msg))
                continue
            if not img_exists(tag):
                # Never built is only an error when this version was asked for
                # by name: reporting success for a version nothing checked is
                # the one result a caller must not be able to trust.
                if versions:
                    print('  {0:<12} {1:<28} FAIL  not built'.format(shown, tag))
                    failed.append((tag, 'not built'))
                else:
                    print('  {0:<12} {1:<28} not built'.format(shown, tag))
                continue
            checked += 1
            for role, cls in roles:
                try:
                    results = probe_image(cls, tag)
                except Exception as e:
                    print('  {0:<12} {1:<28} FAIL  could not probe as {2}: {3}'.format(
                        shown, tag, role, e))
                    failed.append((tag, 'as {0}: {1}'.format(role, e)))
                    continue

                for ok, label, detail in results:
                    mark = 'ok  ' if ok else ('--  ' if ok is None else 'FAIL')
                    print('  {0:<12} {1:<28} {2}  {3} {4}: {5}'.format(
                        shown, tag, mark, role, label, detail))
                    if ok is False:
                        failed.append((tag, '{0} {1}: {2}'.format(role, label, detail)))

                # A tag that names a release should report that release. This
                # catches an image built from the wrong ref, or a repackaged one
                # whose upstream tag moved underneath it.
                reported = next((d for ok, l, d in results if l == 'version' and ok), None)
                if (v and reported and expect_version_in_banner(buildable, v)
                        and not version_matches(reported, str(v), buildable.resolve_ref(v))):
                    msg = 'tagged {0} but reports {1!r}'.format(v, reported)
                    print('  {0:<12} {1:<28} FAIL  {2} version: {3}'.format(shown, tag, role, msg))
                    failed.append((tag, msg))

    print()
    if failed:
        print('{0} problem(s) across {1} image(s):'.format(len(failed), checked))
        for tag, msg in failed:
            print('  {0:<28} {1}'.format(tag, msg))
        sys.exit(1)
    if not checked:
        # "all ok" over nothing checked is worse than saying so.
        sys.exit('nothing was checked -- no matching images are built')
    print('{0} image(s) checked, all ok'.format(checked))


def images(args):
    '''Show what can be benched right now, and what each version resolves to.

    'which versions do I have built' is the question you ask before writing a
    batch config, and `docker images` cannot answer the second half of it --
    that bgperf/frr_c:10.1 came from stable/10.1.
    '''
    for name in sorted(BUILDABLE_IMAGES):
        cls = BUILDABLE_IMAGES[name]
        built = cls.built_versions()
        print('{0} ({1})'.format(name, cls.IMAGE_REPO))
        known = list(dict.fromkeys(['latest'] + list(cls.VERSIONS) + built))
        for v in known:
            version = None if v == 'latest' else v
            try:
                tag = cls.image_tag(version)
            except VersionNotSupported:
                continue
            # built_versions() returns sanitized tags, so a version containing a
            # character sanitize_tag() rewrites ('stable/8' -> 'stable_8') would
            # otherwise always read as not built. doctor already compares this way.
            print('  {0:<12} {1:<28} {2:<18} {3}'.format(
                v, tag, cls.resolve_ref(version),
                'built' if sanitize_tag(v) in built else 'not built'))
        print()

    print('downloaded out of band (tag them yourself):')
    for name in ['srlinux', 'junos', 'eos']:
        cls = TARGET_CLASSES[name]
        tags = cls.built_versions()
        print('  {0:<10} {1:<28} {2}'.format(
            name, cls.IMAGE_REPO, ', '.join(tags) if tags else 'nothing tagged'))


def dockerfile(args):
    '''Print the recipe a version would build, without building it.'''
    cls = BUILDABLE_IMAGES[args.image]
    print(cls.render_dockerfile(args.version))


def parse_versions(value):
    '''Split a --versions list. Accepts commas and/or whitespace.'''
    if not value:
        return []
    return [v for v in re.split(r'[,\s]+', value.strip()) if v]


def prepare(args):
    '''Build daemon images.

    Bare `prepare` builds one image per daemon, tracking its default branch.
    Version images are opt-in behind -t, because a daemon's whole version list
    is hours of compiling -- `doctor` names what is missing and how to get it.
    '''
    names = args.target or PREPARE_IMAGES
    versions = parse_versions(getattr(args, 'versions', None))
    # One explicit list cannot span daemons -- `-t bird -t frr_c --versions 10.4`
    # would build bgperf/bird:10.4 from the nonexistent ref v10.4.
    if versions and len(names) != 1:
        sys.exit('--versions needs exactly one -t/--target: version names mean different '
                 'things to different daemons')

    for name in names:
        if name not in BUILDABLE_IMAGES:
            sys.exit('{0} is not built by bgperf2; known images: {1}'.format(
                name, ', '.join(sorted(BUILDABLE_IMAGES))))

    plan = []
    for name in names:
        cls = BUILDABLE_IMAGES[name]
        # The unversioned image tracks the daemon's default branch; the version
        # tags sit beside it so a batch can compare releases.
        wanted = [None] + list(versions or (cls.VERSIONS if args.target else ()))
        for v in wanted:
            tag = cls.image_tag(v)
            # A PULL_BASE daemon's unversioned tag is repackaged straight from a
            # moving upstream tag, so "already built" says nothing about whether
            # it is current -- skipping it is what let bgperf/openbgp:latest sit
            # at 8.8 for months after 9.2 shipped. Rebuild it every time and let
            # the layer cache make that cheap when upstream has not moved.
            existed = img_exists(tag)
            if args.force or not existed or cls.pulls_base(tag):
                plan.append((cls, v, tag, existed))

    if not plan:
        print('everything requested is already built (use -f to rebuild)')
        return

    print('building {0} image(s):'.format(len(plan)))
    for cls, v, tag, existed in plan:
        print('  {0:<28} from {1}{2}'.format(
            tag, cls.resolve_ref(v), ' (refresh)' if existed and not args.force else ''))
    print()

    # A plan can be eight daemons and several hours. bird/gobgp/rustybgp all
    # track moving default branches, so one transient upstream breakage used to
    # be enough to lose every image after it -- keep going and report at the
    # end, but still exit non-zero so the failure cannot pass for success.
    failures = []
    for cls, v, tag, existed in plan:
        try:
            # pulls_base() implies force: build_dockerfile() skips an existing
            # tag otherwise, so the image would be planned and then not built,
            # and the re-pull it was planned for would never happen.
            cls.build_version(v, force=args.force or cls.pulls_base(tag),
                              nocache=args.no_cache)
        except ImageBuildFailed as e:
            # Refreshing an image we already have is best effort. Only a
            # PULL_BASE tag gets here unforced, and the whole point of that
            # rebuild is to reach the registry -- so being offline or rate
            # limited must not turn a working setup into a failed prepare and
            # a non-zero exit. Keep the image that is already on disk and say
            # so; the run stays reproducible either way, because the version
            # actually used is read from the container and recorded.
            if existed and not args.force:
                print('WARNING: could not refresh {0}, keeping the image already '
                      'on disk: {1}'.format(tag, e.message))
                continue
            print('FAILED: {0}'.format(e))
            failures.append((tag, e))

    if failures:
        print()
        print('{0} of {1} image(s) failed to build:'.format(len(failures), len(plan)))
        for tag, e in failures:
            print('  {0:<28} {1}'.format(tag, e.message))
        sys.exit(1)

    #don't do anything for srlinux, junos, eos because it's just a download out of band


def update(args):
    names = sorted(BUILDABLE_IMAGES) if args.image == 'all' else [args.image]

    # --versions used to shadow --version silently, so `--version 10.7
    # --versions 8.5,9.1` built 8.5 and 9.1 and never mentioned dropping 10.7.
    if args.version and args.versions:
        sys.exit('--version and --versions are redundant: pass one or the other')

    versions = parse_versions(args.versions) or [args.version]

    # A version string means something different to each project, so one list
    # cannot span them: `update all --version 10.7` would try v10.7 on bird and
    # gobgp and abort on flock partway through, after wasting real builds.
    if any(versions) and args.image == 'all':
        sys.exit('--version/--versions needs a single image, not `all`: version names mean '
                 'different things to different daemons')

    # --checkout only applies to the unversioned build; silently dropping it
    # would ship a mislabeled image (tagged 10.7, built from some other ref).
    if any(versions) and args.checkout:
        sys.exit('--checkout and --version are mutually exclusive: a version already selects '
                 'its ref (use --checkout alone to build a raw ref into the default tag)')

    for name in names:
        cls = BUILDABLE_IMAGES[name]
        for v in versions:
            if v:
                cls.build_version(v, force=True, nocache=args.no_cache)
            else:
                # No version: rebuild the default tag, honouring an explicit
                # --checkout for a ref that has no version name (a sha, say).
                cls.build_image(force=True, tag=cls.image_tag(),
                                checkout=args.checkout or cls.DEFAULT_REF,
                                nocache=args.no_cache)

def remove_target_containers():
    # Derived from TARGET_CLASSES so registering a target in one place is
    # enough. A target missing from this list leaves its container behind and
    # the next bench fails on the duplicate name -- FRRoutingTarget is included
    # explicitly because frr_c inherits its container name from it.
    for target_class in set(TARGET_CLASSES.values()) | {FRRoutingTarget}:
        if ctn_exists(target_class.CONTAINER_NAME):
            print('removing target container', target_class.CONTAINER_NAME)
            dckr.remove_container(target_class.CONTAINER_NAME, force=True)

def remove_old_containers():
    if ctn_exists(Monitor.CONTAINER_NAME):
        print('removing monitor container', Monitor.CONTAINER_NAME)
        dckr.remove_container(Monitor.CONTAINER_NAME, force=True)

    for i, ctn_name in enumerate (get_ctn_names()):
        if ctn_name.startswith(ExaBGPTester.CONTAINER_NAME_PREFIX) or \
            ctn_name.startswith(ExaBGPMrtTester.CONTAINER_NAME_PREFIX) or \
            ctn_name.startswith(GoBGPMRTTester.CONTAINER_NAME_PREFIX) or \
            ctn_name.startswith(Bgpdump2Tester.CONTAINER_NAME_PREFIX) or \
            ctn_name.startswith(BIRDTester.CONTAINER_NAME_PREFIX):
            print(f"removing tester container {i} {ctn_name}")
            if i > 0:
                rm_line()
            dckr.remove_container(ctn_name, force=True)


def controller_idle_percent(queue):
    '''collect stats on the whole machine that is running the tests'''
    def stats():
        output = {}
        output['who'] = 'controller'

        while True:
            if controller_stop.is_set():
                return
            utilization = check_output(['mpstat', '1' ,'1']).decode('utf-8').split('\n')[3]
            g = re.match(r'.*all\s+.*\d+\s+(\d+\.\d+)', utilization).groups()
            output['idle'] = float(g[0])
            output['time'] = datetime.datetime.now()
            queue.put(output)
            # dont' sleep because mpstat is already taking 1 second to run

    t = Thread(target=stats)
    t.daemon = True
    t.start()

PREFLIGHT_SAMPLE_SECONDS = 0.5


def warn_if_machine_is_busy():
    '''Say up front if something else is already using the machine.

    A run that starts on a busy box produces a plausible-looking row that
    cannot be compared with the others, and the only trace is a slightly low
    min_idle. Better to say so before spending the minutes.

    Two samples half a second apart, because CPU has to be measured as a delta
    -- see contention.py on why a lifetime average cannot answer this.
    '''
    try:
        first = sample_processes()
        # Time the real window, not the nominal sleep: walking /proc on a box
        # with thousands of processes -- exactly the busy machine this is
        # looking for -- adds enough to overstate the percentage and print a
        # spurious warning.
        started = time.time()
        time.sleep(PREFLIGHT_SAMPLE_SECONDS)
        second = sample_processes()
        complaint = describe_contention(first, second, time.time() - started,
                                        own_pids=own_process_tree(second))
    except Exception:
        return
    if complaint:
        print('WARNING: this machine is busy -- ' + complaint)
        print('         timings will not be comparable with runs made on an idle machine')


def warn_if_log_dir_is_in_ram(config_dir):
    '''Warn when the bench directory is tmpfs, because the logs go into RAM.'''
    try:
        with open('/proc/mounts') as f:
            mounts = f.read()
    except OSError:
        return
    # realpath, not abspath: /var/tmp is a symlink to /tmp on some images,
    # which is precisely the case this check is kept for, and abspath
    # normalizes without following symlinks -- so the path handed to
    # is_memory_backed() would match no tmpfs mount line and the warning would
    # be silently suppressed on exactly the host that needs it.
    if not is_memory_backed(os.path.realpath(config_dir), mounts):
        return
    print('WARNING: {0} is on a memory-backed filesystem, so tester and target '
          'logs consume RAM.'.format(config_dir))
    print('         A 50-peer 100k-prefix BIRD run writes several GB there, which '
          'lowers the recorded')
    print('         min free mem without the daemon using it. Pass -d/--dir with a '
          'disk-backed path.')


# Enough room for the largest log volume this project has measured: a 50-peer
# 100k-prefix BIRD run writes about 5GB of tester logs even after the log-class
# fix, and an FRR full-table MRT run puts bgpd.log past 1GB on its own. The
# floor is not an estimate of a particular run -- the two ends of that range
# differ by 30x and the estimate would have to know what each generator logs --
# it is the point below which a routine large cell can fill the filesystem.
#
# Which matters more than a failed run: /var/tmp is on the root filesystem on
# most hosts, so filling it takes Docker, journald and the rest of the machine
# with it, hours into a batch, and the artifacts of the cells that already
# finished are what gets lost.
LOG_SPACE_FLOOR_GB = 10


def warn_if_log_dir_is_short_on_space(config_dir):
    """Warn when the bench directory's filesystem has little room left."""
    free = free_space_bytes(config_dir)
    if free is None:
        return
    free_gb = free / float(1 << 30)
    if free_gb >= LOG_SPACE_FLOOR_GB:
        return
    print('WARNING: {0} has {1:.1f}GB free, under the {2}GB a large run can '
          'write.'.format(config_dir, free_gb, LOG_SPACE_FLOOR_GB))
    print('         Tester and target logs are bind-mounted there: a 50-peer '
          '100k-prefix BIRD run')
    print('         writes ~5GB, and a full-table MRT run puts bgpd.log past '
          '1GB. Pass -d/--dir with')
    print('         a path on a larger filesystem, or free space before '
          'starting.')


def warn_if_trace_io_reaches_no_generator(args, conf):
    '''Say when --tester-trace-io was asked for and nothing acts on it.

    Only bgpdump2 reads `trace-io`, so the flag is a no-op for a BIRD or ExaBGP
    generator, for the other MRT injectors, and for a `-f` scenario, which
    bypasses gen_conf() entirely. In every one of those the run finishes with
    `backpressure: available: false` and the same "no blocked-write counter"
    reason a genuinely mute generator gives -- so an operator who asked for the
    evidence and did not get it cannot tell which of the two happened.
    '''
    if not getattr(args, 'tester_trace_io', False):
        return
    if any(t and t.get('trace-io') and t.get('mrt_injector') == 'bgpdump2'
           for t in conf.get('testers') or []):
        return
    print('WARNING: --tester-trace-io does nothing for this run. Only bgpdump2 '
          'reports blocked')
    print('         writes, so backpressure will be recorded as unavailable, '
          'the same as for a')
    print('         generator that has no counter at all.')


def controller_foreign_cpu(queue, interval=5):
    '''Track CPU used by anything that is not part of the benchmark.

    min_idle already records that the machine was busy, but not who made it
    busy -- and bgperf's own load moves that number too, so it cannot separate
    "the daemon worked hard" from "something else was running".

    CPU is a delta across `interval`, so the first sample arrives one interval
    in. The tests pass a short one to stay fast.
    '''
    def stats():
        output = {'who': 'controller'}
        previous = sample_processes()
        previous_at = time.time()
        while True:
            # wait() rather than sleep() so the thread stops the moment the run
            # ends instead of lingering for the rest of its poll interval
            if controller_stop.wait(interval):
                return
            try:
                current = sample_processes()
            except Exception:
                # never let a sampling hiccup take down a running benchmark
                continue
            now = time.time()
            output['foreign_cpu'] = foreign_cpu_percent(
                previous, current, now - previous_at,
                own_pids=own_process_tree(current))
            output['time'] = datetime.datetime.now()
            queue.put(dict(output))
            previous, previous_at = current, now

    t = Thread(target=stats)
    t.daemon = True
    t.start()


def controller_memory_free(queue):
    '''collect stats on the whole machine that is running the tests'''
    def stats():
        output = {}
        output['who'] = 'controller'

        while True:
            if controller_stop.is_set():
                return
            free = check_output(['free', '-m']).decode('utf-8').split('\n')[1]
            g = re.match(r'.*\d+\s+(\d+)', free).groups()
            output['free'] = float(g[0]) * 1024 * 1024
            output['time'] = datetime.datetime.now()
            queue.put(output)
            controller_stop.wait(1)

    t = Thread(target=stats)
    t.daemon = True
    t.start()

# Stops the controller sampling threads at the end of a run. This used to be a
# plain module-level bool that finish_bench() assigned without `global`, so the
# assignment created a local and the threads never stopped -- and batch() calls
# bench() in-process once per cell, so a 40-run batch finished with 40 mpstat
# loops, 40 `free` loops and 40 `ps` loops still polling. bgperf was
# manufacturing the very contention it now reports, growing run over run.
# Runs are strictly sequential, so one module-level Event is enough.
controller_stop = threading.Event()


def monitor_sample_monotonic_s(info, fallback_clock=None):
    '''Read a producer timestamp, falling back for legacy queue messages.'''
    if 'monotonic_s' in info:
        return info['monotonic_s']
    return (fallback_clock or time.monotonic)()


# The cadence `Monitor.stats()` is asked for between two `gobgp neighbor -j`
# execs -- passed into that loop, not merely asserted about it, so the floor
# published with every monitor-owned resolution cannot drift away from the
# sleep the loop actually takes. It is the cadence asked for, and so the floor of the resolution
# rather than the resolution itself: a poll costs a read before it waits.
# Every derived interval is quantised by the gap the loop actually achieved,
# which each event carries instead of assuming this.
MONITOR_POLL_INTERVAL_S = 1

# The generators are polled at the monitor's own cadence, so the two sides of
# a run are read at the same resolution -- which is what makes the interval
# between a generator's completion and the monitor's required count a
# measurement rather than the difference between two instruments.
TESTER_POLL_INTERVAL_S = MONITOR_POLL_INTERVAL_S

# The starting value for the free-memory minimum, above any real reading so the
# first sample can only lower it. An untouched sentinel therefore means the
# sampler never fired, which host_evidence() reports as "not measured" rather
# than as a machine with a petabyte free.
UNSAMPLED_MIN_FREE = 1_000_000_000_000_000


def observe_tester_sample(info, recorders, errors):
    '''Feed one polled generator sample to its recorder.

    A recorder that rejects a sample -- a poll that went backwards, or one
    whose session keys changed -- is retired here with the reason kept for the
    artifact. The events it already holds stay usable, and a fault in the
    measurement wiring never ends a run that is otherwise producing a result.
    '''
    recorder = recorders.get(info['who'])
    if recorder is None or info['who'] in errors:
        return False
    try:
        # measurements.MeasurementEventError is a ValueError; the rest of what
        # observe() rejects (a bad counter, a value that is not an offering)
        # raises the plain builtin kinds.
        recorder.observe(info['monotonic_s'], info['tester_offering'])
    except (ValueError, TypeError) as e:
        errors[info['who']] = str(e)
        return False
    return True


def note_tester_read_failure(info, failures):
    '''Count a poll that could not be read, keeping the first reason.

    Deliberately not the dict that retires a recorder: a read can fail once
    while the container is still coming up and succeed for the rest of the run,
    and retiring the generator's measurement over that would throw away the
    evidence the poll exists to collect.
    '''
    record = failures.setdefault(
        info['who'], {'polls': 0, 'first_reason': info['tester_offering_error']})
    record['polls'] += 1
    return record


def tester_lifecycle_summary(recorders, errors, read_failures=None):
    '''Merged generator events, and the evidence that is not an event.'''
    read_failures = read_failures or {}
    events = []
    evidence = {}
    for name, recorder in recorders.items():
        events.extend(recorder.events)
        detail = {'backpressure': recorder.backpressure}
        if name in errors:
            detail['observation_error'] = errors[name]
        if name in read_failures:
            detail['read_failures'] = read_failures[name]
        evidence[name] = detail
    return events, evidence


def bench(args):
    output_stats = {}
    config_dir = '{0}/{1}'.format(args.dir, args.bench_name)
    dckr_net_name = args.docker_network_name or args.bench_name + '-br'

    # Resolve the target image before anything is torn down: a typo'd --version
    # should cost nothing, and everything below this point destroys the previous
    # run's containers and config dir, which CLAUDE.md keeps around on purpose so
    # a failure can be investigated.
    #
    # Only a -f scenario can declare the target remote, and a remote target has
    # no local image to resolve, so that case waits until the scenario is parsed.
    target_image_name = None
    if not args.file:
        target_image_name = target_image(args.target, getattr(args, 'version', None), args.image)

    # Also before the teardown, and before anything reads `prefix_num`: the
    # row, the artifact names and the scenario all take the per-peer count, so
    # the division happens once, here. A scope that cannot be applied should
    # cost a message rather than the previous run's containers, for the same
    # reason the image is resolved above. batch() has already divided by the
    # time it gets here, which is why it passes `per-peer` explicitly.
    if not args.file:
        # `check_batch_test()` refuses these on the batch path; nothing did
        # here. `resolve_prefix_scope()` is the single normalisation point but
        # it only rejects them under `total`, so `bench -n 0` reached
        # `gen_conf()` untouched, which builds a scenario with no testers and a
        # monitor check-point of `int(0 * 0.99)` -- satisfied at zero routes,
        # so the run writes a row that reads as a converged benchmark.
        for flag, value in (('-n/--neighbor-num', args.neighbor_num),
                            ('-p/--prefix-num', args.prefix_num)):
            if not _is_positive_count(value):
                sys.exit('{0} must be a whole number of 1 or more, got '
                         '{1!r}'.format(flag, value))
        check_generator_matches_workload(args)
        # Before the scope, so a run asking for both is told they are not
        # defined together rather than being told the arithmetic of a
        # combination that is refused anyway.
        try:
            args.path_diversity = resolve_path_diversity(
                getattr(args, 'path_diversity', None), args.neighbor_num,
                getattr(args, 'tester_type', None),
                getattr(args, 'prefix_scope', None))
        except ValueError as e:
            sys.exit(str(e))
    if args.file and (getattr(args, 'path_diversity', None)
                      or DEFAULT_PATH_DIVERSITY) != DEFAULT_PATH_DIVERSITY:
        # Same rule as the scope beside it, and above the teardown for the same
        # reason: a scenario file states each neighbour's paths, so grouping
        # them here would do nothing at all, and doing nothing quietly is worse
        # than the silence about `-n` and `-p` it joins.
        sys.exit('--path-diversity has nothing to group under -f: a scenario '
                 "file states each neighbour's paths itself")
    if args.file and getattr(args, 'prefix_scope', None) not in (None, 'per-peer'):
        # `-n`/`-p` are already ignored under `-f`, and this would be too --
        # but the whole point of the flag is that the number means something
        # different, so accepting it where it does nothing is worse than the
        # existing silence about the two it joins.
        sys.exit('--prefix-scope has nothing to divide under -f: a scenario '
                 'file states each neighbour\'s prefixes itself')
    if not args.file:
        try:
            args.prefix_num = resolve_prefix_scope(
                getattr(args, 'prefix_scope', None), args.neighbor_num,
                args.prefix_num, getattr(args, 'tester_type', None))
        except ValueError as e:
            sys.exit(str(e))

    remove_target_containers()

    if not args.repeat:
        remove_old_containers()

        if os.path.exists(config_dir):
            shutil.rmtree(config_dir, ignore_errors=True)

    # Only once the previous run's containers are gone. batch() reuses this
    # process for every cell, so checking earlier would see the last cell's own
    # target daemon still running and report it as somebody else's job.
    warn_if_machine_is_busy()
    warn_if_log_dir_is_in_ram(config_dir)
    warn_if_log_dir_is_short_on_space(config_dir)

    bench_start = time.time()
    if args.file:
        with open(args.file) as f:
            conf = yaml.safe_load(Template(f.read()).render())
    else:
        conf = gen_conf(args)

        if not os.path.exists(config_dir):
            os.makedirs(config_dir)
        with open('{0}/scenario.yaml'.format(config_dir), 'w') as f:
            f.write(conf)
        conf = yaml.safe_load(Template(conf).render())

    # After the scenario is parsed, so this covers a -f run too -- which is one
    # of the ways the flag reaches nothing.
    warn_if_trace_io_reaches_no_generator(args, conf)

    # A remote target is not a container bgperf2 starts, so it has no image --
    # resolving one would fail a remote run on the default target's image.
    is_remote = bool(conf['target'].get('remote'))
    if target_image_name is None and not is_remote:
        target_image_name = target_image(args.target, getattr(args, 'version', None), args.image)

    bridge_found = False
    for network in dckr.networks(names=[dckr_net_name]):
        if network['Name'] == dckr_net_name:
            print('Docker network "{}" already exists'.format(dckr_net_name))
            bridge_found = True
            break
    if not bridge_found:
        subnet = conf['local_prefix']
        print('creating Docker network "{}" with subnet {}'.format(dckr_net_name, subnet))
        ipam = IPAMConfig(pool_configs=[IPAMPool(subnet=subnet)])
        network = dckr.create_network(dckr_net_name, driver='bridge', ipam=ipam)

    num_tester = sum(len(t.get('neighbors', [])) for t in conf.get('testers', []))
    if num_tester > gc_thresh3():
        print('gc_thresh3({0}) is lower than the number of peer({1})'.format(gc_thresh3(), num_tester))
        print('type next to increase the value')
        print('$ echo 16384 | sudo tee /proc/sys/net/ipv4/neigh/default/gc_thresh3')

    print('run monitor')
    m = Monitor(config_dir+'/monitor', conf['monitor'])
    m.monitor_for = args.target
    m.run(conf, dckr_net_name)


    ## I'd prefer to start up the testers and then start up the target  
    # however, bgpdump2 isn't smart enough to wait and rety connections so
    # this is the order
    testers = []
    mrt_injector = None
    if not args.repeat:
        valid_indexes = None
        asns = None
        for idx, tester in enumerate(conf['testers']):
            if 'name' not in tester:
                name = 'tester{0}'.format(idx)
            else:
                name = tester['name']
            if not 'type' in tester:
                tester_type = 'bird'
            else:
                tester_type = tester['type']
            if tester_type == 'exa':
                tester_class = ExaBGPTester
            elif tester_type == 'bird':
                tester_class = BIRDTester
            elif tester_type == 'mrt':
                if 'mrt_injector' not in tester:
                    mrt_injector = 'gobgp'
                else:
                    mrt_injector = tester['mrt_injector']
                if mrt_injector == 'gobgp':
                    tester_class = GoBGPMRTTester
                elif mrt_injector == 'exabgp':
                    tester_class = ExaBGPMrtTester
                elif mrt_injector == 'bgpdump2':
                    tester_class = Bgpdump2Tester
                else:
                    print('invalid mrt_injector:', mrt_injector)
                    sys.exit(1)

            else:
                print('invalid tester type:', tester_type)
                sys.exit(1)


            t = tester_class(name, config_dir+'/'+name, tester)
            if not mrt_injector:
                print('run tester', name, 'type', tester_type)
            else:
                print('run tester', name, 'type', tester_type, mrt_injector)
            if idx > 0:
                rm_line()
            t.run(conf['target'], dckr_net_name)
            testers.append(t)


            # have to do some extra stuff with bgpdump2
            #  because it's sending real data, we need to figure out
            #  wich neighbor has data and what the actual ASN is
            if tester_type == 'mrt' and mrt_injector == 'bgpdump2' and not valid_indexes:
                print("finding asns and such from mrt file")
                valid_indexes = t.get_index_valid(args.prefix_num)
                asns = t.get_index_asns()

                for test in conf['testers']:
                    test['bgpdump-index'] = valid_indexes[test['mrt-index'] % len(valid_indexes)]
                    neighbor = next(iter(test['neighbors'].values()))
                    neighbor['as'] = asns[test['bgpdump-index']]

                # TODO: this needs to all be moved to it's own object and file
                #  so this stuff isn't copied around
                str_conf = gen_mako_macro() + yaml.dump(conf, default_flow_style=False)
                with open('{0}/scenario.yaml'.format(config_dir), 'w') as f:
                    f.write(str_conf)

    if is_remote:
        print('target is remote ({})'.format(conf['target']['local-address']))

        ip = IPRoute()

        # r: route to the target
        r = ip.get_routes(dst=conf['target']['local-address'], family=AF_INET)
        if len(r) == 0:
            print('no route to remote target {0}'.format(conf['target']['local-address']))
            sys.exit(1)

        # intf: interface used to reach the target
        idx = [t[1] for t in r[0]['attrs'] if t[0] == 'RTA_OIF'][0]
        intf = ip.get_links(idx)[0]
        intf_name = intf.get_attr('IFLA_IFNAME')

        # raw_bridge_name: Linux bridge name of the Docker bridge
        # TODO: not sure if the linux bridge name is always given by
        #       "br-<first 12 characters of Docker network ID>".
        raw_bridge_name = args.bridge_name or 'br-{}'.format(network['Id'][0:12])

        # raw_bridges: list of Linux bridges that match raw_bridge_name
        raw_bridges = ip.link_lookup(ifname=raw_bridge_name)
        if len(raw_bridges) == 0:
            if not args.bridge_name:
                print(('can\'t determine the Linux bridge interface name starting '
                      'from the Docker network {}'.format(dckr_net_name)))
            else:
                print(('the Linux bridge name provided ({}) seems nonexistent'.format(
                      raw_bridge_name)))
            print(('Since the target is remote, the host interface used to '
                    'reach the target ({}) must be part of the Linux bridge '
                    'used by the Docker network {}, but without the correct Linux '
                    'bridge name it\'s impossible to verify if that\'s true'.format(
                        intf_name, dckr_net_name)))
            if not args.bridge_name:
                print(('Please supply the Linux bridge name corresponding to the '
                      'Docker network {} using the --bridge-name argument.'.format(
                          dckr_net_name)))
            sys.exit(1)

        # intf_bridge: bridge interface that intf is already member of
        intf_bridge = intf.get_attr('IFLA_MASTER')

        # if intf is not member of the bridge, add it
        if intf_bridge not in raw_bridges:
            if intf_bridge is None:
                print(('Since the target is remote, the host interface used to '
                      'reach the target ({}) must be part of the Linux bridge '
                      'used by the Docker network {}'.format(
                          intf_name, dckr_net_name)))
                sys.stdout.write('Do you confirm to add the interface {} '
                                 'to the bridge {}? [yes/NO] '.format(
                                     intf_name, raw_bridge_name
                                    ))
                try:
                    answer = input()
                except:
                    print('aborting')
                    sys.exit(1)
                answer = answer.strip()
                if answer.lower() != 'yes':
                    print('aborting')
                    sys.exit(1)

                print('adding interface {} to the bridge {}'.format(
                    intf_name, raw_bridge_name
                ))
                br = raw_bridges[0]

                try:
                    ip.link('set', index=idx, master=br)
                except Exception as e:
                    print(('Something went wrong: {}'.format(str(e))))
                    print(('Please consider running the following command to '
                          'add the {iface} interface to the {br} bridge:\n'
                          '   sudo brctl addif {br} {iface}'.format(
                              iface=intf_name, br=raw_bridge_name)))
                    print('\n\n\n')
                    raise
            else:
                curr_bridge_name = ip.get_links(intf_bridge)[0].get_attr('IFLA_IFNAME')
                print(('the interface used to reach the target ({}) '
                      'is already member of the bridge {}, which is not '
                      'the one used in this configuration'.format(
                          intf_name, curr_bridge_name)))
                print(('Please consider running the following command to '
                        'remove the {iface} interface from the {br} bridge:\n'
                        '   sudo brctl addif {br} {iface}'.format(
                            iface=intf_name, br=curr_bridge_name)))
                sys.exit(1)
    else:
        target_class = TARGET_CLASSES[args.target]
        print('run', run_name(args))
        target = target_class('{0}/{1}'.format(config_dir, args.target), conf['target'],
                              image=target_image_name)

        target.run(conf, dckr_net_name)

    time.sleep(1)

    output_stats['monitor_wait_time'] = m.wait_established(conf['target']['local-address'])
    output_stats['cores'], output_stats['memory'] = get_hardware_info()
    # target_class is only bound in the local branch above; a remote run used to
    # die here with NameError. Pre-existing, but the remote path is now something
    # bench() explicitly supports resolving for.
    if not is_remote and target_class == EosTarget:
        print("Waiting extra 10 seconds for EOS ")
        time.sleep(10)

    bench_clock_started_s = time.monotonic()
    lifecycle = MonitorEventRecorder(
        bench_clock_started_s, producer=m.name,
        sample_interval_s=MONITOR_POLL_INTERVAL_S)

    q = Queue()

    # Let the previous run's samplers go before starting this run's. batch()
    # reuses this process for every cell, so without the clear the new threads
    # would exit immediately on a flag the last run left set.
    controller_stop.clear()

    m.stats(q, interval=MONITOR_POLL_INTERVAL_S)
    controller_idle_percent(q)
    controller_memory_free(q)
    controller_foreign_cpu(q)
    if not is_remote:
        target.stats(q)
        target.neighbor_stats(q)


    # want to launch all the neighbors at the same(ish) time
    # launch them after the test starts because as soon as they start they can send info at least for mrt
    #  does it need to be in a different place for mrt than exabgp?
    for i in range(len(testers)):
        testers[i].launch()
        if i > 0:
            rm_line()
        print(f"launched {i+1} testers")
        # if args.prefix_num >= 100_000:
        #     time.sleep(1)

    # Ask the generators themselves what they have put on the wire. This is
    # measured at the tester, so an injection interval is evidence rather than
    # something inferred from when the monitor happened to see prefixes -- the
    # legacy `testers (s)` column is that inference, and it cannot tell a slow
    # generator from a slow target. Polling starts after launch because nothing
    # is running in those containers until start.sh has been exec'd.
    tester_lifecycles = {}
    tester_observation_errors = {}
    tester_read_failures = {}
    for t in testers:
        if not getattr(t, 'REPORTS_OFFERING', False):
            continue
        tester_lifecycles[t.name] = TesterEventRecorder(
            bench_clock_started_s, producer=t.name,
            sample_interval_s=TESTER_POLL_INTERVAL_S)
        t.offering_stats(q, controller_stop, TESTER_POLL_INTERVAL_S)

    f = open(args.output, 'w') if args.output else None
    cpu = 0
    mem = 0

    output_stats['max_cpu'] = 0
    output_stats['max_mem'] = 0
    output_stats['first_received_time'] = datetime.timedelta(0)
    output_stats['min_idle'] = 100
    output_stats['min_free'] = UNSAMPLED_MIN_FREE
    output_stats['max_foreign_cpu'] = 0
    # finish_bench() fills these in once the clock has stopped; a run with no
    # testers (a remote target) never gets there, and they are printed and
    # written into the row unconditionally.
    output_stats['tester_errors'] = 0
    output_stats['tester_timeouts'] = 0

    output_stats['required'] = conf['monitor']['check-points'][0]
    bench_stats = []
    neighbors_checked = 0
    neighbors_received_full = 0
    percent_idle = 0
    mem_free = 0

    recved = 0
    tracker = ConvergenceTracker()
    while True:
        info = q.get()

        if not is_remote and info['who'] == target.name:
            if 'neighbors_checked' in info:
                if len(info['neighbors_checked']) > 0 and all(value == True for value in info['neighbors_checked'].values()):
                    neighbors_checked = sum(1 if value == True else 0 for value in info['neighbors_checked'].values())
                    tracker.note_neighbors_checkpoint()
                else:
                    neighbors_checked = sum(1 if value == True else 0 for value in info['neighbors_checked'].values())
            elif 'neighbors_received_full' in info:

                if len(info['neighbors_received_full']) >= 1 and all(value == True for value in info['neighbors_received_full'].values()):
                    neighbors_received_full = sum(1 if value == True else 0 for value in info['neighbors_received_full'].values())
                    tracker.note_neighbors_checkpoint()
                else:
                    neighbors_received_full = sum(1 if value == True else 0 for value in info['neighbors_received_full'].values())
            else:
                cpu = info['cpu']
                mem = info['mem']
                output_stats['max_cpu'] = cpu if cpu > output_stats['max_cpu'] else output_stats['max_cpu']
                output_stats['max_mem'] = mem if mem > output_stats['max_mem'] else output_stats['max_mem']

        if info['who'] == 'controller':
            if 'free' in info:
                mem_free = info['free']
                output_stats['min_free'] = mem_free if mem_free < output_stats['min_free'] else output_stats['min_free']
            elif 'idle' in info:
                percent_idle = info['idle']
                output_stats['min_idle'] = percent_idle if percent_idle < output_stats['min_idle'] else output_stats['min_idle']
            elif 'foreign_cpu' in info:
                foreign = info['foreign_cpu']
                if foreign > output_stats['max_foreign_cpu']:
                    output_stats['max_foreign_cpu'] = foreign
        if 'tester_offering' in info:
            observe_tester_sample(info, tester_lifecycles,
                                  tester_observation_errors)
        elif 'tester_offering_error' in info:
            note_tester_read_failure(info, tester_read_failures)

        if info['who'] == m.name:

            sample_monotonic_s = monitor_sample_monotonic_s(info)
            elapsed = datetime.timedelta(
                seconds=sample_monotonic_s - bench_clock_started_s)
            output_stats['elapsed'] = elapsed
            recved = info['afi_safis'][0]['state']['accepted'] if 'accepted' in info['afi_safis'][0]['state'] else 0
            lifecycle.observe(sample_monotonic_s, int(recved), info['checked'])
            measured = monitor_metrics(lifecycle.events)
            if measured['first_prefix_s'] is not None:
                output_stats['first_received_time'] = datetime.timedelta(
                    seconds=measured['first_prefix_s'])
            
            status = tracker.update(elapsed.seconds, recved, neighbors_checked,
                                    neighbors_received_full, info['checked'])

            if elapsed.seconds > 0:
                rm_line()

            print('elapsed: {0}sec, cpu: {1:>4.2f}%, mem: {2}, mon recved: {3}, neighbors_received: {4}, neighbors_accepted: {5}, %idle {6}, free mem {7}'.format(elapsed.seconds, 
                    cpu, mem_human(mem), recved, neighbors_received_full, neighbors_checked, percent_idle, mem_human(mem_free)))
            bench_stats.append([elapsed.seconds, float(f"{cpu:>4.2f}"), mem, recved, neighbors_checked, percent_idle, mem_free])
            f.write('{0}, {1}, {2}, {3}\n'.format(elapsed.seconds, cpu, mem, recved)) if f else None
            f.flush() if f else None

            if status == ConvergenceTracker.FAILED:
                output_stats['recved'] = recved
                output_stats['fail_msg'] = tracker.fail_msg
                f.close() if f else None
                print("FAILED")
                return finish_bench(
                    args, output_stats, bench_stats, bench_start, target, m,
                    testers, fail=True, lifecycle_events=lifecycle.events,
                    tester_lifecycles=tester_lifecycles,
                    tester_observation_errors=tester_observation_errors,
                    tester_read_failures=tester_read_failures)

            if status == ConvergenceTracker.CONVERGED:
                lifecycle.confirm_convergence(sample_monotonic_s)
                assurance = tracker.assurance_samples
                output_stats['recved'] = recved

                f.close() if f else None

                # Drop the trailing assurance samples: the run was already done
                # by then, we were only confirming the count had stopped moving.
                # TODO: recalculate all min/max stats after removing these
                #  should move to always calculating based on bench_stats
                print(f"last recevied: {tracker.last_recved_count}")
                output_stats['elapsed'] = datetime.timedelta(
                    seconds=int(output_stats['elapsed'].seconds) - assurance + 1)
                bench_stats = bench_stats[0:len(bench_stats)-assurance]
                return finish_bench(
                    args, output_stats, bench_stats, bench_start, target, m,
                    testers, lifecycle_events=lifecycle.events,
                    tester_lifecycles=tester_lifecycles,
                    tester_observation_errors=tester_observation_errors,
                    tester_read_failures=tester_read_failures)

            if elapsed.seconds % 120 == 0 and elapsed.seconds > 1:
                # The same stem the final graphs use. Built from args.target
                # alone, these dropped the label, the version, the filter and
                # the repetition, so a long run's in-progress graphs were
                # overwritten by the next cell of the same daemon.
                create_bench_graphs(bench_stats, prefix=bench_output_prefix(args),
                                    results_dir=args.results_dir)


def collect_provenance(args, target, monitor, testers):
    '''Version and image of every daemon that took part in the run.

    The target alone does not describe a result: the testers generate the load
    and the monitor is the instrument every timing is read from, so all three
    have to be recorded for anyone else to reproduce the numbers. Reading them
    is only possible while the containers are still up.
    '''
    def describe(daemon, container):
        return {'daemon': daemon,
                'image': normalize_image_name(container.image),
                'version': container.version_string()}

    provenance = {
        'target': describe(args.target, target),
        'monitor': describe('gobgp', monitor),
        'testers': [],
    }
    # A run can be a hundred tester containers off one image. Ask one per
    # distinct image and record how many ran, rather than exec'ing into each.
    by_image = {}
    for t in testers:
        key = normalize_image_name(t.image)
        if key not in by_image:
            by_image[key] = describe(getattr(args, 'tester_type', None) or 'tester', t)
            by_image[key]['count'] = 0
        by_image[key]['count'] += 1
    provenance['testers'] = list(by_image.values())
    return provenance


def write_provenance(args, provenance, prefix):
    '''Write the full build manifest beside the run's other output.

    The CSV carries the headline versions so runs can be compared at a glance;
    this carries the whole set, including the image each container ran from.
    '''
    doc = dict(provenance)
    doc['run'] = {
        'name': run_name(args),
        'date': datetime.date.today().strftime('%Y-%m-%d'),
        'peers': args.neighbor_num,
        'prefixes_per_peer': args.prefix_num,
        'tester_type': getattr(args, 'tester_type', None),
        # How many peers announced each prefix block, and only where bgperf2
        # is what decided that: under `-f` the scenario file states each
        # neighbour's paths, so a 1 here would be an assertion about a
        # workload bgperf2 did not build. Provenance never guesses.
        'path_diversity': (None if getattr(args, 'file', None) else
                           getattr(args, 'path_diversity', None)
                           or DEFAULT_PATH_DIVERSITY),
        # Which pass over the matrix this row came from, or None for a batch
        # that made one pass. The name carries it too, but a summary over
        # repetitions should not have to parse a label to group them.
        'repetition': getattr(args, 'repetition', None),
        'filter_test': getattr(args, 'filter_test', None),
    }
    path = results_path(args.results_dir, prefix + '.versions.json')
    with open(path, 'w') as f:
        json.dump(doc, f, indent=2, sort_keys=True)
        f.write('\n')
    return path


def host_evidence(output_stats):
    '''The run-level evidence that is not an event, for the findings policy.

    These come from the controller's own sampler threads rather than from any
    container, so they never enter the lifecycle stream -- but a busy or
    nearly-full machine is exactly the case where the intervals in that stream
    must not be attributed to a daemon.

    The two minima start at sentinels so the first sample can only lower them,
    which means an untouched sentinel is "never sampled" and not "the machine
    was idle". Free memory says so; `min_idle` at 100 is left as it is, since
    an idle host and an unsampled one lead to the same finding: none.
    '''
    free = output_stats.get('min_free')
    return {
        'min_idle_percent': output_stats.get('min_idle'),
        'max_foreign_cpu_percent': output_stats.get('max_foreign_cpu'),
        'min_free_bytes': None if free == UNSAMPLED_MIN_FREE else free,
        'total_memory_bytes': output_stats.get('memory'),
    }


def write_event_artifact(args, events, prefix, status, testers=None,
                         host=None):
    '''Atomically preserve lifecycle evidence before post-run collection.

    Returns the document it wrote, so the caller can print the findings it
    derived rather than deriving them a second time from the same events.
    '''
    doc = event_artifact(events, status, testers=testers)
    # Derived from the finished document rather than from the events, so the
    # policy can only ever reason about intervals this artifact published.
    #
    # Caught, because this function's job is to preserve the evidence and the
    # findings are an opinion about it: by the time it runs, this document is
    # the only record that a converged run happened at all, and losing it to a
    # verdict that could not be formed would be the wrong half to drop.
    try:
        doc['findings'] = derive_findings(doc, host=host)
    except Exception as e:
        doc['findings'] = policy_failure(e)
    doc['run'] = {
        'name': run_name(args),
        'peers': args.neighbor_num,
        'prefixes_per_peer': args.prefix_num,
        'tester_type': getattr(args, 'tester_type', None),
        # Without this the document says `peers: 10, prefixes_per_peer: 1000`
        # for a run whose target held 2,000 distinct prefixes and whose monitor
        # required 1,980, and nothing in it can correct the reader: the only
        # other carrier is the `pd5` in the filename. Same rule as
        # `repetition` -- an artifact carries the dimension so a summary does
        # not have to parse a stem to recover it. `None` under `-f` for the
        # reason `write_provenance()` records `None` there.
        'path_diversity': (None if getattr(args, 'file', None) else
                           getattr(args, 'path_diversity', None)
                           or DEFAULT_PATH_DIVERSITY),
        'repetition': getattr(args, 'repetition', None),
        'filter_test': getattr(args, 'filter_test', None),
    }
    path = results_path(args.results_dir, prefix + '.events.json')

    def write(f):
        json.dump(doc, f, indent=2, sort_keys=True)
        f.write('\n')

    atomic_write(path, write)
    return doc


def finish_bench(args, output_stats, bench_stats, bench_start, target, m, testers=(), fail=False,
                 lifecycle_events=(), tester_lifecycles=None,
                 tester_observation_errors=None, tester_read_failures=None):

    bench_stop = time.time()
    output_stats['total_time'] = bench_stop - bench_start
    m.stop_monitoring = True
    target.stop_monitoring = True
    for t in testers:
        # The generator pollers watch controller_stop too, but they exec into
        # containers this run is about to walk away from, so they are told
        # twice rather than left racing the teardown.
        t.stop_monitoring = True
    controller_stop.set()

    tester_events, tester_evidence = tester_lifecycle_summary(
        tester_lifecycles or {}, tester_observation_errors or {},
        tester_read_failures or {})
    lifecycle_events = list(lifecycle_events) + tester_events

    bench_prefix = bench_output_prefix(args)
    artifact = write_event_artifact(
        args, lifecycle_events, bench_prefix,
        status='failed' if fail else 'converged',
        testers=tester_evidence, host=host_evidence(output_stats))

    # Scan the tester logs only after the clock has stopped. These used to run
    # in bench() before bench_stop, so walking every tester log line by line --
    # twice, once per needle, over logs that reach hundreds of MB on a 1M-prefix
    # MRT run -- was billed to total_time, a column create_batch_graphs() plots.
    tester_dirs = [t.host_dir for t in testers]
    tester_class = type(testers[0]) if testers else None
    if tester_class is not None:
        output_stats['tester_errors'] = tester_class.find_errors(tester_dirs)
        output_stats['tester_timeouts'] = tester_class.find_timeouts(tester_dirs)

    # Read every version before the containers go away -- this is the last
    # moment any of them can be asked.
    provenance = collect_provenance(args, target, m, testers)
    del m

    target_version = provenance['target']['version']

    print_final_stats(args, target_version, output_stats)
    print_tester_metrics(lifecycle_events, tester_evidence)
    # Last, because it is the one line that reads the rest of them together.
    for line in describe_findings(artifact['findings']):
        print(line)
    o_s = create_output_stats(args, target_version, output_stats, fail, provenance)
    print(stats_header())
    print(','.join(map(str, o_s)))
    print()
    # it would be better to clean things up, but often I want to to investigate where things ended up
    # remove_old_containers()
    # remove_target_containers()
    create_bench_graphs(bench_stats, prefix=bench_prefix, results_dir=args.results_dir)
    write_provenance(args, provenance, bench_prefix)
    return o_s



def print_tester_metrics(events, producers):
    '''Report each generator's own injection interval, or why there is none.

    Deliberately printed beside the legacy `testers (s)` column rather than
    instead of it: that column is elapsed minus time-to-first-prefix, which is
    a property of the target and monitor, and the two must not be read as
    versions of the same measurement.
    '''
    for producer in sorted(producers):
        measured = tester_metrics(events, producer)
        offered = measured['offered_prefixes']
        startup = measured['tester_startup_s']
        startup_text = 'unmeasured' if startup is None else f"{startup:.1f}s"
        if measured['injection_s'] is None:
            print(f"{producer}: ready after {startup_text}, injection unmeasured "
                  f"(no observed completion for every session)")
            continue
        # The generator's own measurement of its send, where it makes one. It
        # is named beside every polled interval rather than folded into one,
        # because it is not the same measurement: a different clock, and the
        # generator's own definition of sending. On an MRT walk that finishes
        # in a millisecond it is the only number either side can offer.
        reported = measured['reported_injection_s']
        own = '' if reported is None \
            else f"; the generator measured its own send at {reported:.6f}s"
        covered = measured['offered_in_interval']
        if offered is None:
            # A generator that reported its own completion on a poll whose
            # counters were not legible. The interval is real; how much crossed
            # it is unknown, and it is unknown for a different reason than the
            # counter reset below.
            print(f"{producer}: ready after {startup_text}, completed in "
                  f"{measured['injection_s']:.1f}s, offered count unavailable "
                  f"(no readable count at completion){own}")
            continue
        if covered is None:
            # The counter went backwards: BIRD clears a protocol's route-change
            # stats when it restarts, so a session that flapped reports fewer
            # offered prefixes at completion than at the first update. The
            # interval is real but nothing can be said about what crossed it --
            # and calling that 'shorter than one poll' would describe a long
            # injection as an instant one.
            print(f"{producer}: ready after {startup_text}, offered {offered} "
                  f"prefixes over {measured['injection_s']:.1f}s, rate "
                  f"unavailable (the generator's counter was reset mid-run){own}")
            continue
        rate = measured['offered_rate_pps']
        if rate is None and not measured['injection_s']:
            # There was no interval to divide by: the whole table was already
            # offered when the instrument first looked, so first update and
            # completion landed on the same poll. That is not an instant
            # injection, it is one this poll cadence cannot resolve, and it
            # must not read as a duration. Name the resolution the loop
            # actually achieved rather than the cadence it was asked for --
            # the read costs time before the wait, so 'one poll' is wider than
            # the interval, and understating it overstates what is known.
            resolution = measured['injection_resolution_s']
            bound = 'one poll' if resolution is None \
                else f"the {resolution:.1f}s poll resolution"
            print(f"{producer}: ready after {startup_text}, offered {offered} "
                  f"prefixes, injection shorter than {bound}{own}")
            continue
        if rate is None:
            # There is an interval, and none of the table crossed it: the
            # count was already final at the first poll that could read it and
            # the generator said it was done at a later one. A generator that
            # delivered everything must not be published at 0 prefixes/s.
            print(f"{producer}: ready after {startup_text}, offered {offered} "
                  f"prefixes, none of them inside the measured "
                  f"{measured['injection_s']:.1f}s (the table was offered "
                  f"before the first poll){own}")
            continue
        # The rate covers only the part of the table that arrived inside the
        # measured interval; printing that share keeps a tail slope from being
        # read as the generator's send rate.
        print(f"{producer}: ready after {startup_text}, offered {offered} "
              f"prefixes, {covered} of them in the measured "
              f"{measured['injection_s']:.1f}s ({rate:.0f} prefixes/s){own}")
    if len(producers) > 1:
        print_tester_fleet_metrics(events, producers)
    if producers:
        print_post_injection_tail(events, producers)


def print_post_injection_tail(events, producers):
    '''Report what the run spent after the whole workload had been offered.

    Printed once for the run rather than once per generator, and taken from
    the fleet, because the tail only starts when the *last* generator has
    finished: a per-generator tail on a ten-injector run is nine numbers that
    include waiting for another injector.

    Said in words rather than published as a bare signed number, because the
    two ends of it come from two 1s poll loops. A tail no larger than that
    resolution is not a short tail -- each end could have happened anywhere
    inside its own look, so the interval is not distinguishable from zero --
    and a negative one is not a fault, it is the ordinary shape of a run whose
    check-point was reached while the generators were still finishing.
    '''
    fleet = tester_fleet_metrics(events, producers)
    tail = fleet['post_injection_tail_s']
    resolution = fleet['post_injection_tail_resolution_s']
    if tail is None:
        # Named for what `incomplete_testers` actually means -- a generator
        # with no *bounded, completed* injection, which is a missing first
        # update as well as a missing completion. Saying "no completion" for
        # a generator that reported one and was never seen to offer anything
        # would name the wrong end.
        reason = 'a generator has no completed injection' \
            if fleet['incomplete_testers'] \
            else 'the monitor never reached the required count'
        print(f"post-injection tail unmeasured ({reason})")
    elif resolution is not None and abs(tail) <= resolution:
        print(f"post-injection tail not resolved at the {resolution:.1f}s poll "
              f"resolution (the last generator finished and the monitor "
              f"reached the required count within one look of each other)")
    elif tail < 0:
        print(f"post-injection tail: none, the monitor reached the required "
              f"count {-tail:.1f}s before the last generator finished "
              f"(injection and convergence overlapped)")
    else:
        print(f"post-injection tail: {tail:.1f}s from the last generator "
              f"finishing to the required count")


def print_tester_fleet_metrics(events, producers):
    '''Report whether the whole generator fleet offered the workload.

    A ten-injector MRT run prints ten lines above this one, and the fact that
    matters for the run is whether *every* one of them finished. Reading that
    off ten lines means noticing the single one that says `injection
    unmeasured`, which is the line a reader skims. This says it once, and names
    the generators that did not finish rather than reporting a fleet interval
    the ones that did could supply.
    '''
    fleet = tester_fleet_metrics(events, producers)
    count = fleet['testers']
    startup = fleet['tester_startup_s']
    startup_text = 'unmeasured' if startup is None else f"{startup:.1f}s"
    missing = fleet['incomplete_testers']
    if missing:
        named = ', '.join(missing[:4])
        if len(missing) > 4:
            named += f", and {len(missing) - 4} more"
        print(f"all {count} generators: {fleet['testers_complete']} reported "
              f"completion, last ready after {startup_text}, fleet injection "
              f"unmeasured (no completion from {named})")
        return
    # The longest of the generators' own measurements, not their sum: they send
    # at the same time, so adding them totals intervals that overlapped.
    reported = fleet['reported_injection_s']
    own = '' if reported is None \
        else (f"; the slowest generator measured its own send at "
              f"{reported:.6f}s")
    offered = fleet['offered_prefixes']
    covered = fleet['offered_in_interval']
    rate = fleet['offered_rate_pps']
    # One span from the earliest first update to the slowest completion, for
    # the same reason -- not a sum of the generators' intervals.
    injection = fleet['injection_s']
    if offered is None:
        print(f"all {count} generators: last ready after {startup_text}, all "
              f"complete over {injection:.1f}s, offered count unavailable (a "
              f"generator had no readable count at completion){own}")
        return
    if covered is None:
        print(f"all {count} generators: last ready after {startup_text}, "
              f"offered {offered} prefixes over {injection:.1f}s, rate "
              f"unavailable (a generator's counter was reset mid-run){own}")
        return
    if rate is None and not injection:
        resolution = fleet['injection_resolution_s']
        bound = 'one poll' if resolution is None \
            else f"the {resolution:.1f}s poll resolution"
        print(f"all {count} generators: last ready after {startup_text}, "
              f"offered {offered} prefixes, fleet injection shorter than "
              f"{bound}{own}")
        return
    if rate is None:
        # The MRT shape: every injector's walk finished before its own first
        # poll, and the span only records that they completed at different
        # polls. It is an interval nothing was measured crossing, which is not
        # the same as a slow fleet -- and 0 prefixes/s would say it was one.
        print(f"all {count} generators: last ready after {startup_text}, "
              f"offered {offered} prefixes, none of them inside the "
              f"{injection:.1f}s between the first and last completion (each "
              f"generator finished before it was first looked at){own}")
        return
    print(f"all {count} generators: last ready after {startup_text}, offered "
          f"{offered} prefixes, {covered} of them in the measured "
          f"{injection:.1f}s ({rate:.0f} prefixes/s){own}")


def print_final_stats(args, target_version, stats):
    
    print(f"{args.target}: {target_version}")
    print(f"Max cpu: {stats['max_cpu']:4.2f}, max mem: {mem_human(stats['max_mem'])}")
    print(f"Min %idle {stats['min_idle']}, Min mem free {mem_human(stats['min_free'])}")
    print(f"Time since first received prefix: {stats['elapsed'].seconds - stats['first_received_time'].seconds}")

    print(f"total time: {stats['total_time']:.2f}s")
    print(f"elasped time: {stats['elapsed'].seconds}s")
    print(f"tester errors: {stats['tester_errors']}")
    print(f"tester timeouts: {stats['tester_timeouts']}")
    print()

def stats_header():
    # NOTE: must stay in sync with the row built by create_output_stats();
    # tests/test_stats_contract.py enforces that they are the same length.
    #
    # The provenance columns are appended at the END on purpose:
    # create_batch_graphs() indexes this row positionally, so inserting a column
    # anywhere earlier silently shifts every graph and every existing CSV.
    return("name, target, version, peers, prefixes per peer, required, received, monitor (s), elapsed (s), prefix received (s), testers (s), total time, max cpu %, max mem (GB), min idle%, min free mem (GB), flags, date, cores, Mem (GB), tester errors, tester timeouts, failed, MSG, filters, max foreign cpu %, target image, tester version, monitor version")


def row_gb(value):
    '''Bytes as the CSV's GB column carries them.

    One function because `unsampled_row_values()` has to produce exactly what
    an unsampled `min_free` looks like in the row, and a second copy of the
    formatting would drift from this one without anything failing.
    '''
    return float(format(value / 1024 / 1024 / 1024, ".3f"))


def unsampled_row_values():
    '''Row values that mean "never sampled" rather than a measurement.

    `min_free` starts above every real value so the first sample can only
    lower it, so an untouched sentinel reaches the row as a machine with
    ~931,322 GB free. `host_evidence()` maps it back to None for the findings
    for this reason, and a summary needs the same: a cell where one pass of
    three lost its memory sampler -- `free` raising kills that thread while the
    run goes on -- would otherwise publish a mean of ~310,474 GB and a
    coefficient of variation of 173% on a 64 GB box, which reads as a finding
    about the daemon.

    `max_mem` is the same shape of sentinel reached the other way round: it
    starts at 0 so the first sample can only raise it, and the target's
    sampler is as easy to lose -- `Container.stats()` has no `try` around its
    `dckr.stats` walk, and its `mem` comes from a `.get('usage', 0)` that can
    return 0 with the thread still alive. A 3-pass cell reading 1.0, 0.0, 1.0
    publishes a coefficient of variation of 87% invented by a dead sampler,
    right beside the `min free mem (GB)` this function was added for -- so the
    document would report the memory numbers disagreeing wildly while
    declining to publish the other memory number. A peak under 0.5 MB is not
    something a daemon holding a BGP table can produce, so 0.0 is
    distinguishable here.

    `min_idle` and `max_cpu` are deliberately not here: `min_idle`'s sentinel
    is 100 and `max_cpu`'s rounds to 0 from any peak under 0.5%, both of which
    are values a real run can report, and for `min_idle` an idle host and an
    unsampled one are the same finding anyway.
    '''
    return {'min free mem (GB)': row_gb(UNSAMPLED_MIN_FREE),
            'max mem (GB)': row_gb(0)}


def create_output_stats(args, target_version, stats, fail=False, provenance=None):
    e = stats['elapsed'].seconds
    f = stats['first_received_time'].seconds
    d = datetime.date.today().strftime("%Y-%m-%d")
    out = [run_name(args), args.target, target_version, str(args.neighbor_num), str(args.prefix_num)]
    out.extend([stats['required'], stats['recved']])
    # Compatibility only: this is the interval after the first monitor-visible
    # prefix, not tester runtime or tester completion. Keep the historical
    # formula until a separately named lifecycle metric is appended.
    legacy_post_first_prefix = e - f
    out.extend([stats['monitor_wait_time'], e, f, legacy_post_first_prefix,
                float(format(stats['total_time'], ".2f"))])
    out.extend([round(stats['max_cpu']), row_gb(stats['max_mem'])])
    out.extend ([round(stats['min_idle']), row_gb(stats['min_free'])])
    out.extend(['-s' if args.single_table else '', d, str(stats['cores']), mem_human(stats['memory'])])
    out.extend([stats['tester_errors'],stats['tester_timeouts']])
    out.extend(['FAILED']) if fail else out.extend([''])
    out.extend([stats['fail_msg']]) if 'fail_msg' in stats else out.extend([''])
    out.extend([args.filter_test]) if 'filter_test' in args  and args.filter_test else out.extend([''])
    # Worst competition seen from outside the benchmark, as a percentage of one
    # core. Anything much above 0 means this row's timings cannot be compared
    # with rows measured on an idle machine -- min_idle alone cannot say that,
    # because bgperf's own load moves it too. Placed before the provenance
    # columns so those stay last, which test_provenance.py requires.
    out.extend([round(stats.get('max_foreign_cpu', 0))])
    # Which builds produced this row. The target's own version already sits in
    # the 'version' column; these say which image it came from and which builds
    # generated and measured the load.
    p = provenance or {}
    testers = p.get('testers') or []
    out.extend([(p.get('target') or {}).get('image', ''),
                '; '.join(sorted({t.get('version', '') for t in testers})),
                (p.get('monitor') or {}).get('version', '')])
    return out


DEFAULT_RESULTS_DIR = 'results'


def results_path(results_dir, filename):
    '''Resolve an output filename into results_dir, creating the directory if needed.

    Graphs and CSVs used to be written to the working directory, which meant they
    piled up in the repo root. Everything generated now goes under results_dir.
    '''
    directory = Path(results_dir or DEFAULT_RESULTS_DIR)
    directory.mkdir(parents=True, exist_ok=True)
    return str(directory / filename)


def create_ts_graph(bench_stats, stat_index=1, filename='ts.png', ylabel='%cpu', diviser=1,
                    results_dir=DEFAULT_RESULTS_DIR):
    plt.figure()
    #bench_stats.pop(0)
    data = np.array(bench_stats)
    plt.plot(data[:,0], data[:,stat_index]/diviser)
    
    #don't want to see 0 element of data, not an accurate measure of what's happening
    #plt.xlim([1, len(data)])
    plt.ylabel(ylabel)
    plt.xlabel('elapsed seconds')
    plt.show()
    plt.savefig(results_path(results_dir, filename))
    plt.close()
    plt.cla()
    plt.clf()


def create_bench_graphs(bench_stats, prefix='ts_data', results_dir=DEFAULT_RESULTS_DIR):
    for stat_index, suffix, ylabel, diviser in [
        (1, 'cpu', '%cpu', 1),
        (2, 'mem_used', 'GB', 1024*1024*1024),
        (3, 'mon_received', 'prefixes', 1),
        (4, 'neighbors', 'neighbors', 1),
        (5, 'machine_idle', '%', 1),
        (6, 'free_mem', 'GB', 1024*1024*1024),
    ]:
        create_ts_graph(bench_stats, stat_index=stat_index, filename=f"{prefix}_{suffix}.png",
                        ylabel=ylabel, diviser=diviser, results_dir=results_dir)

def create_graph(stats, test_name='total time', stat_index=8, test_file='total_time.png', ylabel='seconds',
                 results_dir=DEFAULT_RESULTS_DIR):
    labels = {}
    data = defaultdict(list)

    try:
        for stat in stats:
            labels[stat[0]] = True
            key = f"{stat[3]}n_{stat[4]}p"
            
            if stat[24]:
                 key =f"{key}_{stat[24]}"

            if len(stat) > 23 and stat[22] == 'FAILED':# this means that it failed for some reason
                data[key].append(0)
            else:
                data[key].append(float(stat[stat_index]))
    except IndexError as e:
        print(e)
        print(f"stat line failed: {stat}")
        print(f"stat_index {stat_index}")
        exit(-1)

    x = np.arange(len(labels))
  
    bars = len(data)
    width = 0.7 / bars
    plt.figure()
    for i, d in enumerate(data):
        plt.bar(x -0.2+i*width, data[d], width=width, label=d)

    plt.ylabel(ylabel)
    #plt.xlabel('neighbors_prefixes')
    plt.title(test_name)
    plt.xticks(x,labels.keys())
    plt.legend()

    plt.show()
    plt.savefig(results_path(results_dir, test_file))

class BatchLoader(yaml.SafeLoader):
    '''YAML loader that leaves version-shaped scalars alone.

    Plain yaml reads `10.10` as the float 10.1, which would quietly bench FRR
    10.1 when the config asked for 10.10. Nothing in a batch config is
    legitimately a float, so dropping the implicit float resolver costs
    nothing and keeps versions as the strings they were written as.
    '''


BatchLoader.yaml_implicit_resolvers = {
    ch: [(tag, regexp) for tag, regexp in resolvers if tag != 'tag:yaml.org,2002:float']
    for ch, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def expand_target_versions(targets):
    '''Turn `versions: [8.0, 9.0]` on a target into one entry per version.

    Comparing releases is the common case, and writing them out by hand means
    repeating the whole target block -- including the image tag, which is the
    part that is easy to get wrong.
    '''
    expanded = []
    for t in targets:
        versions = t.get('versions') or [t.get('version')]
        for v in versions:
            entry = dict(t)
            entry.pop('versions', None)
            if v is None:
                entry.pop('version', None)
            else:
                # yaml turns 10.1 into a float and 10 into an int; both have to
                # survive as the string the tag was built from.
                entry['version'] = str(v)
                if 'label' not in t:
                    entry['label'] = '{0} {1}'.format(t['name'], v)
                elif len(versions) > 1:
                    # An explicit label on a multi-version entry would name every
                    # run the same thing: duplicate rows in the CSV, per-run PNGs
                    # overwriting each other, and create_graph() raising a shape
                    # mismatch because it de-duplicates labels but not data.
                    entry['label'] = '{0} {1}'.format(t['label'], v)
            expanded.append(entry)
    return expanded


def batch_repetitions(test):
    '''How many times a test asks for its whole matrix to be run.

    Checked here rather than where it is used, because `batch()` validates the
    whole config before starting the first container: a `repetitions: 0` typo
    that ran nothing, or a `repetitions: "3"` that ran once, would otherwise be
    discovered hours in or not at all.
    '''
    value = test.get('repetitions', 1)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        sys.exit("test '{0}': repetitions must be a positive integer, got {1!r}".format(
            test.get('name'), value))
    return value


# Everything `batch()` needs from a test before it can expand or run it.
BATCH_TEST_KEYS = ('name', 'neighbors', 'prefixes', 'filter_test', 'targets')

# ... and everything else it will read. A key outside both is a typo, and the
# ones that matter here fail silently: `seeds: 7` under `order: shuffle` draws
# a fresh permutation on every invocation while looking pinned, and
# `repetitions` misspelt runs one pass of a matrix someone asked three of.
BATCH_TEST_OPTIONAL_KEYS = ('repetitions', 'order', 'seed', 'prefix_scope',
                            'path_diversity')


# Keys that mean something on a *test* and nothing on a target. There is no
# allowlist of target keys -- `batch()` reads a fixed field list and ignores
# the rest, and enumerating every valid one here would reject configs this
# change has no business rejecting -- but the reverse check is cheap and
# catches the mistake that actually happens. Every other knob an operator sets
# is a target key (`threads`, `tester_type`, `mrt_file`, `image`, `version`),
# so a test key written one level too deep is the natural slip, and each of
# these fails silently and expensively: `prefix_scope: total` under a target is
# ignored, and that target runs `neighbors x prefixes` routes -- 5,000,000
# instead of 100,000 at 50 peers -- converges, and writes rows and bars that
# read as a peer sweep.
BATCH_TEST_ONLY_KEYS = ('prefix_scope', 'repetitions', 'order', 'seed',
                        'neighbors', 'prefixes', 'filter_test',
                        'path_diversity')

# Target keys whose absence means something other than `None`. `batch()`
# otherwise gives every unset field `None`, and `gen_conf()` routes anything
# that is not `exa` or `bird` down the MRT branch, where a missing `mrt_file`
# is a bare `exit(1)` -- so a target that simply omitted `tester_type` passed
# every up-front check and then killed the whole batch part way through, which
# is the multi-hour failure those checks exist to prevent. The value is the
# CLI's own default for `-g`, so the two paths agree about what an unstated
# generator is.
#
# `filter_type` is here for the same reason and was found missing one round
# later: `batch()` handed `bench()` `None`, `gen_conf()` writes
# `'filter': {args.filter_type: assignment}`, and every target's config writer
# looks for the literal key `'in'` -- so a batch target with policy counts and
# no `filter_type` produced `filter: {null: [p2]}`, ran unfiltered, and
# reported as a filtered run.
BATCH_FIELD_DEFAULTS = {'tester_type': 'bird', 'filter_type': 'in'}


def mrt_keys_without_an_mrt_generator(tester_type, mrt_file=None,
                                      mrt_injector=None):
    """MRT intent stated on a run whose generator synthesises prefixes.

    One function because all four entry points have to refuse the same thing
    and the failure is silent on every one of them: `gen_conf()` takes the
    synthetic branch, never opens the file, and sets the monitor check-point to
    `n * p` rather than `p`, so the run converges and writes a row and
    artifacts with nothing recording that the table was never played back.
    """
    if tester_type not in SYNTHETIC_TESTER_TYPES:
        return []
    return [name for name, value in (('mrt_injector', mrt_injector),
                                     ('mrt_file', mrt_file)) if value]


def batch_target_defaults(target):
    """The defaults that apply to this target -- none, for a scenario target.

    `bench -f` reads the workload from the file, so a default here is not a
    fallback but an assertion about a run bgperf2 did not configure. And
    `tester_type` is not inert on that path even though the generator is:
    `write_provenance()` records it as `run.tester_type`, `collect_provenance()`
    labels the tester role with it, and `bench_output_prefix()` puts it in the
    stem. Defaulting it wrote `"tester_type": "bird"` into the versions
    manifest of a run that played back an MRT file, and named its artifacts
    `bird_bird_...`. Provenance never guesses; absent is the honest value.
    """
    return {} if target.get('file') else BATCH_FIELD_DEFAULTS


def batch_target_field(target, field):
    """What `batch()` will put on the synthesized args for this field.

    Read rather than written into the target: the target dict *is* part of the
    cell identity (`expand_batch_cells()` stores it, and the cell id is what
    `--resume` matches on), so filling a default into it renames every
    completed cell of every in-flight batch. An explicitly empty value has to
    read as absent here all the same, or this scan sees `None` where `batch()`
    will see the default and the two disagree about what generator a run uses.
    """
    value = target.get(field)
    return batch_target_defaults(target).get(field) if value is None else value


def check_batch_test(test):
    '''Reject a test that cannot be expanded, before any container starts.

    Same reason as `batch_repetitions()`, and it was the gap next to it:
    expansion would otherwise die on a bare `KeyError: 'filter_test'` -- which
    is exactly what `benchmarks/big-tests.yaml` did -- so a mistyped or omitted
    axis took the whole batch down with a traceback naming neither the test nor
    the key. An axis is required rather than defaulted, because a typo that
    quietly ran the matrix unfiltered is the failure this is here to prevent.
    '''
    missing = [key for key in BATCH_TEST_KEYS if key not in test]
    if missing:
        sys.exit("test '{0}': missing required {1}: {2}".format(
            test.get('name', '<unnamed>'),
            'key' if len(missing) == 1 else 'keys', ', '.join(missing)))
    known = set(BATCH_TEST_KEYS) | set(BATCH_TEST_OPTIONAL_KEYS)
    unknown = sorted(key for key in test if key not in known)
    if unknown:
        sys.exit("test '{0}': unrecognised {1}: {2}. Known keys: {3}".format(
            test['name'], 'key' if len(unknown) == 1 else 'keys',
            ', '.join(map(str, unknown)), ', '.join(sorted(known))))
    for key in ('neighbors', 'prefixes', 'filter_test', 'targets'):
        if not isinstance(test[key], list) or not test[key]:
            sys.exit("test '{0}': {1} must be a non-empty list, got {2!r}".format(
                test['name'], key, test[key]))
    # Both numeric axes really are numbers. A quoted entry -- `prefixes:
    # ["100000"]` -- otherwise reaches the arithmetic below as a bare
    # `TypeError`, which is the traceback naming neither the test nor the key
    # that this function exists to eliminate.
    # Whole numbers, and at least one of each. Zero and negative pass a bare
    # type check and are caught by `resolve_prefix_scope()` only under
    # `total`; under the default scope nothing caught them, and `gen_conf()`
    # then built a scenario with no testers and a monitor check-point of
    # `int(0 * 0.99)` -- satisfied at zero routes, so the cell wrote a row
    # that reads as a converged run. That is precisely the typo this function
    # exists to name before the first container.
    for key in ('neighbors', 'prefixes'):
        bad = [v for v in test[key] if not _is_positive_count(v)]
        if bad:
            sys.exit(
                "test '{0}': {1} must be whole numbers of 1 or more, got "
                '{2}'.format(test['name'], key,
                             ', '.join(repr(v) for v in bad)))
    # Every combination of the two axes, before the first container. Under
    # `prefix_scope: total` the split has to be exact for each of them, and a
    # matrix is where an inexact one is easy to write: `neighbors: [10, 25,
    # 50]` against 1,050,000 divides three times and against 100,000 twice.
    # Finding that out at cell four is hours lost to arithmetic.
    #
    # The tester comes from the targets, and one MRT target poisons the whole
    # test rather than just its own cells: `prefixes` is a single axis shared
    # by every target, so a test mixing an MRT generator with a synthetic one
    # under `total` cannot be right for both. Without this the batch path
    # accepted exactly what the CLI refuses -- `expand_batch_cells()` would
    # divide a 1,050,000-prefix MRT table by its peer count, `gen_conf()` sets
    # the monitor check-point straight from `-p` for those generators, and the
    # run reports CONVERGED at a tenth of the table with nothing in the row or
    # the artifacts saying so.
    for target in test['targets']:
        # A name first: everything below reports against it, and
        # `', '.join()` on a target that has neither name nor label raised a
        # bare TypeError -- the traceback naming neither the test nor the key
        # that this function exists to eliminate, produced by the checks added
        # to eliminate it.
        if not isinstance(target, dict) or not target.get('name'):
            sys.exit("test '{0}': every target needs a `name`, got {1!r}".format(
                test['name'], target))
        # Every generator check below exempts a scenario target: it never
        # reaches `gen_conf()`, so its generator is inert and none of the
        # advice these print would change what runs.
        scenario = bool(target.get('file'))
        tester = batch_target_field(target, 'tester_type')
        if not scenario and tester not in TESTER_TYPES:
            sys.exit(
                "test '{0}': target {1!r} has tester_type {2!r}; expected one "
                'of {3}. A batch target bypasses argparse, and config '
                'generation treats anything it does not recognise as an MRT '
                'injector'.format(test['name'], target['name'], tester,
                                  ', '.join(TESTER_TYPES)))
        # A target that named an MRT file or injector and not a generator.
        # Before `tester_type` had a default this failed loudly -- `None` took
        # `gen_conf()`'s MRT branch and `bench()` stopped at `invalid
        # mrt_injector: None`. The default turned that into a *synthetic BIRD
        # run*: `mrt_file` never read, the monitor check-point `n * p` instead
        # of `p`, and a converged row and artifacts with nothing saying the
        # table was never played back. A default that makes a wrong workload
        # quiet is worse than the crash it replaced, so the intent stated by
        # these two keys is checked against the generator that will run.
        # `gen_conf()` derives the injector from `tester_type` and never reads
        # `mrt_injector`, so one that disagrees is not a second opinion -- it
        # is a line the run ignores. `tester_type: gobgp` beside
        # `mrt_injector: bgpdump2` played back through gobgp, against a 0.93
        # check-point factor instead of 0.99, and wrote a row that reads as a
        # bgpdump2 run.
        injector = target.get('mrt_injector')
        if not scenario and injector and injector != tester:
            sys.exit(
                "test '{0}': target {1!r} sets mrt_injector {2!r} and "
                'tester_type {3!r}. Config generation derives the injector '
                'from tester_type, so {2!r} would never run'.format(
                    test['name'], target['name'], injector, tester))
        # A `file:` target is exempt here for the same reason it is exempt
        # from the mrt_file check below: it never reaches `gen_conf()`, so its
        # generator is inert and the advice this prints -- set `tester_type` --
        # would not change what runs. Rejecting it fails a config that works.
        named_mrt = [] if scenario else mrt_keys_without_an_mrt_generator(
            tester, target.get('mrt_file'), target.get('mrt_injector'))
        if named_mrt:
            sys.exit(
                "test '{0}': target {1!r} carries {2} but runs the {3!r} "
                'generator, which synthesises prefixes and never reads them. '
                'Set tester_type to one of {4}'.format(
                    test['name'], target['name'], ' and '.join(named_mrt),
                    tester, ', '.join(MRT_TESTER_TYPES)))
        misplaced = sorted(k for k in target if k in BATCH_TEST_ONLY_KEYS)
        if misplaced:
            sys.exit(
                "test '{0}': target {1!r} carries {2} {3}, which {4} only "
                'meaningful on the test itself and {5} ignored here. Move '
                '{6} up one level.'.format(
                    test['name'], target.get('label') or target.get('name'),
                    'key' if len(misplaced) == 1 else 'keys',
                    ', '.join(misplaced),
                    'is' if len(misplaced) == 1 else 'are',
                    'is' if len(misplaced) == 1 else 'are',
                    'it' if len(misplaced) == 1 else 'them'))
    # Both workload knobs below are meaningless against a target that names a
    # scenario file, and for the same reason: the file states what each
    # neighbour offers, so neither would change what runs.
    scenarios = [t.get('label') or t['name'] for t in test['targets']
                 if t.get('file')]
    scope = test.get('prefix_scope')
    if scope not in (None, 'per-peer') and scenarios:
        # `bench()` refuses this, and its refusal is unreachable from here:
        # `batch()` pins `prefix_scope: per-peer` on the synthesized args
        # because the division has already happened. So a scenario target under
        # `total` would divide `prefixes`, record the divided count in the cell
        # id, the `prefixes per peer` column and every artifact name, and then
        # run whatever workload the file describes.
        sys.exit(
            "test '{0}': prefix_scope has nothing to divide for {1}, which "
            'name a scenario file: the file states each neighbour\'s '
            'prefixes itself'.format(test['name'], ', '.join(scenarios)))
    diversity = test.get('path_diversity')
    if diversity not in (None, DEFAULT_PATH_DIVERSITY) and scenarios:
        # And `bench()`'s own refusal is unreachable from here too, for a
        # different reason: `batch()` synthesizes the args itself, so a
        # scenario target reaches `bench()` with `-f` set and the value still
        # on it, and nothing between here and the run would say the grouping
        # was ignored.
        sys.exit(
            "test '{0}': path_diversity has nothing to group for {1}, which "
            'name a scenario file: the file states each neighbour\'s paths '
            'itself'.format(test['name'], ', '.join(scenarios)))
    mrt = sorted({batch_target_field(t, 'tester_type') for t in test['targets']
                  if batch_target_field(t, 'tester_type') in MRT_TESTER_TYPES})
    # The other half of the same guard. `gen_conf()` ends an MRT run with no
    # file at a bare `exit(1)`, and that `SystemExit` travels out of `bench()`
    # and out of `batch()`, killing the matrix at whichever cell reached it.
    # Defaulting an omitted `tester_type` closed one shape of that failure and
    # this is the other; both are known here, before the first container.
    # A `file:` target never reaches `gen_conf()` -- `bench()` loads the
    # scenario instead -- so its generator is inert and refusing it would
    # reject a config that would have run.
    fileless = [t.get('label') or t['name'] for t in test['targets']
                if batch_target_field(t, 'tester_type') in MRT_TESTER_TYPES
                and not t.get('file') and not t.get('mrt_file')]
    if fileless:
        sys.exit(
            "test '{0}': {1} {2} an MRT generator and no mrt_file. The run "
            'would end at `exit(1)` inside config generation, taking the rest '
            'of the batch with it'.format(
                test['name'], ', '.join(fileless),
                'names' if len(fileless) == 1 else 'name'))
    # Every peer count on the axis, for the same reason the scope is checked
    # against every combination below: a matrix is where a division that works
    # for one entry and not the next is easy to write -- `neighbors: [10, 25,
    # 50]` divides by 5 three times and by 4 not at all -- and finding that out
    # at cell three is hours lost.
    for neighbors in test['neighbors']:
        try:
            resolve_path_diversity(diversity, neighbors,
                                   mrt[0] if mrt else None, scope)
        except ValueError as e:
            sys.exit("test '{0}': {1}".format(test['name'], e))
    for neighbors in test['neighbors']:
        for prefixes in test['prefixes']:
            try:
                resolve_prefix_scope(scope, neighbors, prefixes,
                                     mrt[0] if mrt else None)
            except ValueError as e:
                sys.exit("test '{0}': {1}".format(test['name'], e))


def target_run_name(target):
    """What `run_name()` will call a run of this target entry.

    A batch target is not a bench Namespace, and the name has to be known
    before any run starts, so the same three fields are handed to the one
    function that decides it rather than to a second copy of its rules.
    """
    return run_name(argparse.Namespace(
        target=target['name'], label=target.get('label'),
        version=target.get('version')))


def check_batch_run_names(test, targets):
    """Reject two targets in one test that would run under the same name.

    A run name is only label, target and version, so two entries differing in
    anything else -- `threads: 1` against `threads: 4`, one MRT file against
    another, a stock image against a rebuilt one -- are one name. Everything
    downstream is keyed by it: `bench_output_prefix()` builds the stem for
    `<prefix>.events.json`, `<prefix>.versions.json` and the per-run PNGs, so
    the second cell replaces the first's evidence; the CSV grows rows nothing
    can tell apart; and `create_graph()` pairs one x tick with two bar heights
    and raises a shape mismatch at the end of a batch that has already run for
    hours. `expand_target_versions()` already guards the version axis this way,
    by labelling each version; this is the same failure reached along any other
    field, and the fix is the same one -- give one of them a `label`.
    """
    seen = {}
    for target in targets:
        name = target_run_name(target)
        if name in seen:
            sys.exit(
                "test '{0}': two targets would both run as '{1}': {2!r} and "
                '{3!r}. Give one of them a distinct `label`: a run name is what '
                'names its artifacts, its CSV row and its bar.'.format(
                    test.get('name'), name, seen[name], target))
        seen[name] = target


def expand_batch_cells(test, targets):
    '''Enumerate one test's matrix into the ordered list of runs it asks for.

    Repetitions repeat the whole matrix, not each cell: three back-to-back runs
    of one cell share a page cache, a thermal state and whatever else the
    machine happened to be doing for the last few minutes, so what they measure
    is partly that rather than the daemon. Running the matrix as a block also
    means an interrupted batch holds one observation of everything rather than
    every observation of the first few cells.

    The ordinal is a cell's position within one pass, so the same cell keeps
    the same ordinal in every repetition and `repetition` is the only thing
    that separates them. Neither is a position in the execution order, which is
    what lets that order be permuted later without moving any cell's identity.

    A single-pass test gets `repetition` None rather than 1, and that one value
    has to reach the cell id as well as the run name or the two disagree: a
    completed single-pass batch whose config then gained `repetitions: 3` would
    match its stored pass-1 ids, reuse those rows unchanged, and produce a CSV
    holding `bird` beside `bird #2` and `bird #3`. Adding repetitions changes
    what every row is, so it should cost a re-run rather than a mixed table.
    '''
    check_batch_test(test)
    repetitions = batch_repetitions(test)
    scope = test.get('prefix_scope')
    # Carried on the cell rather than read from the test at run time, because
    # the cell is what `--resume` matches on: a test whose `path_diversity` is
    # edited between runs describes a different workload, and a cell id that
    # did not say so would reuse rows measured against the old one.
    diversity = test.get('path_diversity') or DEFAULT_PATH_DIVERSITY
    cells = []
    for repetition in range(1, repetitions + 1):
        ordinal = 0
        for n in test['neighbors']:
            for p in test['prefixes']:
                for filter_test in test['filter_test']:
                    for t in targets:
                        cells.append({
                            'repetition': repetition if repetitions > 1 else None,
                            'ordinal': ordinal,
                            'neighbors': n,
                            # The per-peer count, resolved here rather than
                            # carried as a scope: `-n 50 -p 100000` under
                            # `total` and `-n 50 -p 2000` are the same
                            # workload, so they must produce the same cell
                            # identity, the same row, the same artifact names
                            # and the same bar. `check_batch_test()` has
                            # already refused an inexact division.
                            'prefixes': resolve_prefix_scope(scope, n, p),
                            'filter': filter_test,
                            'path_diversity': diversity,
                            'target': t,
                        })
                        ordinal += 1
    return cells


# How a test may sequence its cells. `matrix` is the enumeration order
# `expand_batch_cells()` produces; `shuffle` permutes it from a recorded seed.
BATCH_ORDERS = ('matrix', 'shuffle')


def batch_order(test):
    """How a test wants its cells sequenced, and the seed that fixes it.

    Matrix order runs every cell of one target next to every other cell of that
    target, so anything that drifts over a batch -- an ambient thermal ramp, a
    page cache filling, a neighbour's job starting an hour in -- lands on the
    axes in a pattern rather than as noise, and comes back out as a difference
    between the daemons. Permuting the order does not remove that drift, it
    stops it lining up with any one axis.

    Validated here, with the rest of the config, because it decides the order of
    hours of work: an unrecognised `order` that quietly ran the matrix would
    make a batch that looks like it randomised and did not.

    A seed under `order: matrix` is rejected rather than ignored, since a config
    that names a seed is asking to be permuted. An omitted seed is generated,
    not fixed at a constant: a default seed shared by every batch is one
    permutation, and a permutation nobody chose is exactly the pattern this
    exists to break. It is recorded in the progress file, so the sequence stays
    reproducible after the fact and a resumed batch keeps the order it planned.
    """
    order = test.get('order', 'matrix')
    if order not in BATCH_ORDERS:
        sys.exit("test '{0}': order must be one of {1}, got {2!r}".format(
            test.get('name'), ', '.join(BATCH_ORDERS), order))
    seed = test.get('seed')
    if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int)):
        sys.exit("test '{0}': seed must be an integer, got {1!r}".format(
            test.get('name'), seed))
    if order == 'matrix':
        if seed is not None:
            sys.exit("test '{0}': seed applies to order: shuffle, and this test "
                     'runs in matrix order'.format(test.get('name')))
        return order, None
    if seed is None:
        seed = random.SystemRandom().getrandbits(32)
    return order, seed


def describe_batch_sequence(order, seed):
    """One phrase for a sequence, so the planned one and a superseded one read
    the same way. Matrix order has no seed to name."""
    if order == 'matrix' or seed is None:
        return order
    return '{0} seed {1}'.format(order, seed)


def batch_shuffle_key(seed, test_name, cell):
    """Where one cell sorts under one seed.

    A digest of the seed and the cell's own identity, rather than
    `random.shuffle` on a seeded PRNG: the point of recording a seed is that
    the sequence can be reconstructed later, and a Mersenne Twister draw is a
    property of the interpreter that produced it as much as of the seed. A
    digest is fixed by the two strings alone.
    """
    material = '{0}:{1}'.format(seed, batch_cell_id(test_name, cell))
    return hashlib.sha256(material.encode('utf-8')).hexdigest()


def order_batch_cells(test_name, cells, order, seed):
    """Sequence one test's cells for execution, without moving what any of them is.

    Permutation happens inside a repetition, never across one. A repetition is
    a block on purpose -- an interrupted batch then holds one observation of
    everything rather than every observation of the first few cells -- and
    dealing the passes together would take that back. Each pass draws its own
    permutation, because the digest is keyed by the cell id and that carries the
    repetition: one permutation reused for every pass would apply the same
    position bias three times and the repetitions could not average it out.

    Identity is untouched. `ordinal` stays a cell's place in the matrix and the
    cell id says nothing about when it ran, so a resumed batch matches its
    completed cells whatever order either pass ran in.
    """
    if order != 'shuffle':
        return list(cells)
    blocks = {}
    for cell in cells:
        blocks.setdefault(cell['repetition'], []).append(cell)
    sequenced = []
    for block in blocks.values():
        sequenced.extend(sorted(
            block, key=lambda cell: batch_shuffle_key(seed, test_name, cell)))
    return sequenced


def batch_report_rows(test_name, cells, completed):
    """The rows of a test, in matrix order, whatever order they ran in.

    Execution order is a property of the run; matrix order is what the CSV and
    the graphs are read in. `create_graph()` needs the second one: it keys the x
    axis off the row names it sees and appends one bar height per row, pairing
    the two positionally, which only holds while each (peers, prefixes, filter)
    group arrives with its targets in the same order. A shuffled batch that
    reported in execution order would hand it bars under the wrong labels, or a
    length mismatch, at the end of a batch that has already run for hours.
    """
    rows = []
    for cell in cells:
        cell_id = batch_cell_id(test_name, cell)
        if cell_id in completed:
            rows.append(completed[cell_id])
    return rows


def batch_summary_groups(test_name, cells, completed):
    """Every pass of one matrix cell, gathered under that cell's identity.

    Grouped by `ordinal`, which is a cell's place in the matrix and the one
    field a repetition does not change, so the passes of one cell come
    together whatever order they ran in.

    Both levels are then sorted rather than left in the order they arrived --
    by ordinal, and by repetition inside a cell -- so this returns matrix order
    even when handed a sequenced list, and a metric's `values` read pass 1
    first. Same reason `batch_report_rows()` reports in matrix order:
    execution order is a property of the run, not of the report, and a summary
    whose cells were dealt in shuffle order would sit under a CSV and a set of
    bars that were not.

    The identity comes from the cell rather than from the rows, because it is
    known whether or not any pass produced one: a cell whose every pass failed
    still has to say which cell it was. The whole target entry is carried, not
    just the run name, since `threads`, `mrt_file` and `image` are what a run
    was asked for and none of them reach the name.
    """
    groups = {}
    for cell in cells:
        ordinal = cell['ordinal']
        if ordinal not in groups:
            groups[ordinal] = {
                'ordinal': ordinal,
                'name': target_run_name(cell['target']),
                # How a cell is named in a printed line, from the one function
                # that already decides it: `name` alone is the target, and two
                # cells of one target differ only in their axes.
                'description': batch_cell_description(cell),
                'identity': {'peers': cell['neighbors'],
                             'prefixes': cell['prefixes'],
                             'filter': cell['filter'],
                             'target': cell['target']},
                'passes': [],
            }
        groups[ordinal]['passes'].append({
            'repetition': cell['repetition'],
            'row': completed.get(batch_cell_id(test_name, cell))})
    ordered = [groups[ordinal] for ordinal in sorted(groups)]
    for group in ordered:
        # A single-pass cell carries `repetition: None`, and it is the only
        # pass there is.
        group['passes'].sort(key=lambda p: p['repetition'] or 0)
    return ordered


def write_batch_summary(path, document):
    def write(f):
        # allow_nan=False: `json.dump` would otherwise write a NaN or an
        # Infinity as a bare word that jq and most non-Python parsers reject,
        # turning an unreadable document into a named failure instead.
        json.dump(document, f, indent=2, sort_keys=True, default=str, allow_nan=False)
        f.write('\n')
    atomic_write(path, write)


def publish_batch_summary(path, test_name, cells, completed, repetitions,
                          describe=True):
    """Write the per-cell summary beside the CSV, and return its printed lines.

    Wrapped, for the reason `write_event_artifact()` catches its own findings:
    the summary is derived from rows that are already on disk, so a
    summariser that raises must cost the summary and not the evidence -- at
    the end of a batch that has already run for hours.

    A failure always returns a line, whether or not the caller asked for the
    description: this is the only report that the document beside the CSV is
    not the one describing it.
    """
    try:
        document = summarize_batch(test_name, [f.strip() for f in stats_header().split(',')],
                                   batch_summary_groups(test_name, cells, completed),
                                   repetitions=repetitions,
                                   unavailable=unsampled_row_values())
        write_batch_summary(path, document)
    except Exception as e:
        return ['summary unavailable: {0}: {1}'.format(type(e).__name__, e)]
    if not describe:
        return []
    try:
        return describe_batch_summary(document, path=path)
    except Exception as e:
        # Describing the document is the other half of the same rule, and it
        # was outside the guard: a raise here aborts batch() after the CSV is
        # written but before create_batch_graphs() and before every remaining
        # test in the yaml -- costing the rows this wrapper exists to protect,
        # and more of them than the summariser ever could.
        #
        # Its own line rather than `summary unavailable`, which would be false:
        # the document is on disk, and only the description of it failed.
        return ['summary written to {0}, but describing it raised {1}: {2}'.format(
            path, type(e).__name__, e)]


def check_batch_images(targets):
    '''Fail before the first run if any image in the batch is missing.

    A batch is hours of work; finding out at target number six that its image
    was never built means throwing away everything after it.
    '''
    missing = []
    for t in targets:
        if t.get('file'):
            # A hand-written scenario can declare the target remote, in which
            # case there is no local image to check. bench() sorts it out once
            # the scenario is parsed.
            continue
        if t['name'] not in TARGET_CLASSES:
            missing.append("unknown target '{0}'".format(t['name']))
            continue
        if t.get('image'):
            if not img_exists(t['image']):
                missing.append("{0}: image '{1}' does not exist".format(t['name'], t['image']))
            continue
        try:
            TARGET_CLASSES[t['name']].require_image(t.get('version'))
        except (ImageNotBuilt, VersionNotSupported) as e:
            missing.append(str(e))
    if missing:
        sys.exit('\n'.join(['this batch cannot run:'] + ['  ' + m for m in missing]))


def batch(args):
    """ runs several tests together, produces all the stats together and creates graphs
    requires a yaml file to describe the batch of tests to run

    it iterates through a list of targets, number of neighbors and number of prefixes
    other variables can be set, but not iterated through
    """
    with open(args.batch_config, 'r') as f:
        batch_config = yaml.load(f, Loader=BatchLoader)

    # Expand and check every test before running any of them. Checking each test
    # as it came up still let a missing image in test 3 surface only after tests
    # 1 and 2 had run, which is the multi-hour wait this is meant to prevent.
    expanded = []
    for test in batch_config['tests']:
        # Before anything reads the test, including `test['targets']` itself:
        # `check_batch_test()` exists so a missing or mistyped axis is named
        # rather than arriving as a bare KeyError, and every read that comes
        # first is a way to get that KeyError anyway.
        check_batch_test(test)
        targets = expand_target_versions(test['targets'])
        check_batch_run_names(test, targets)
        order, seed = batch_order(test)
        expanded.append((test, targets, expand_batch_cells(test, targets), order, seed))
    # One entry per target, not per cell: a repeated matrix asks about the same
    # images every pass, and reporting a missing image once per repetition
    # buries the list this exists to print.
    check_batch_images([t for _, targets, _, _, _ in expanded for t in targets])

    for test, _targets, cells, order, seed in expanded:
        repetitions = batch_repetitions(test)
        progress_path = results_path(args.results_dir, f"{test['name']}.progress.json")
        summary_path = results_path(args.results_dir, f"{test['name']}.summary.json")
        resume = getattr(args, 'resume', False)
        document = load_batch_progress_document(progress_path) if resume else {'cells': {}}
        completed = document['cells']
        if not resume and os.path.exists(progress_path):
            os.unlink(progress_path)
        if not resume and os.path.exists(summary_path):
            # The rows of a discarded batch are replaced by its successor's
            # first checkpoint, but a summary that then fails to write would
            # leave the previous run's document -- three passes that no longer
            # exist -- beside the rewritten CSV.
            os.unlink(summary_path)
        # A progress file written before ordering existed names no order, and
        # there was only one to have run in: reading it as matrix is what makes
        # the comparison below honest rather than vacuous.
        recorded = {'order': document.get('order') or 'matrix',
                    'seed': document.get('seed')}
        superseded = list(document.get('previous_seeds') or [])
        if (resume and test.get('seed') is None
                and recorded['order'] == order and recorded['seed'] is not None):
            # Recover the drawn seed rather than dealing the remaining cells
            # again: an interrupted run resumed under a fresh permutation has
            # run two orders, and neither of them is the one it recorded. A
            # seed the config states is left alone -- changing it by hand is an
            # instruction to re-sequence, not a resume to be corrected.
            seed = recorded['seed']
        elif (resume and completed
                and (recorded['order'], recorded['seed']) != (order, seed)):
            # The cells already on disk ran under the recorded sequence. The
            # document is rewritten from scratch on every checkpoint, so a
            # superseded seed that is simply dropped leaves the file describing
            # an order that some of its own rows did not run in.
            superseded.append(recorded)
            print('order: {0} completed cell(s) ran under {1}; keeping that as '
                  'a superseded sequence'.format(
                      len(completed), describe_batch_sequence(**recorded)))
        if order != 'matrix':
            print('order: {0} (recorded in {1})'.format(
                describe_batch_sequence(order, seed), progress_path))
        # Written before the first cell so the seed survives a batch that dies
        # in it, and so --resume finds the sequence rather than drawing another.
        write_batch_progress(progress_path, completed, order=order, seed=seed,
                             previous_seeds=superseded)
        # Written before the first cell too, so the file describes *this*
        # batch's cells from the outset rather than leaving a previous run's
        # summary in place -- a stale document claiming three passes that were
        # discarded is worse than no document. Nothing is printed yet.
        for line in publish_batch_summary(summary_path, test['name'], cells,
                                          completed, repetitions,
                                          describe=False):
            print(line)
        for cell in order_batch_cells(test['name'], cells, order, seed):
            t = cell['target']
            cell_id = batch_cell_id(test['name'], cell)
            if cell_id in completed:
                print("resume: skipping completed cell: {0}".format(
                    batch_cell_description(cell, repetitions)))
                continue

            a = argparse.Namespace(**vars(args))
            a.func = bench
            if 'image' in t:
                a.image = t['image']
            else:
                a.image = None
            a.output = None
            a.target = t['name']
            a.prefix_num = cell['prefixes']
            a.neighbor_num = cell['neighbors']
            # Already per-peer: `expand_batch_cells()` applied the test's
            # `prefix_scope` when it built the cell, because the cell identity,
            # the CSV row and the artifact names all have to be the per-peer
            # count. Passing the scope through as well would divide twice.
            a.prefix_scope = 'per-peer'
            # From the cell, not from the test: the cell is what the id, the
            # row and the artifact names were built from, and reading the test
            # again here would let a config edited mid-batch run a cell under a
            # diversity its own id does not record.
            a.path_diversity = cell.get('path_diversity') or DEFAULT_PATH_DIVERSITY
            a.filter_test = cell['filter'] if cell['filter'] != 'None' else None
            # None for a single-pass test, so its rows, graphs and event
            # artifacts keep the names they have always had; set for every pass
            # of a repeated one, including the first, because a run named
            # `bird 2.19.2` sitting beside `bird 2.19.2 #2` reads as a
            # different thing rather than as the first of three.
            a.repetition = cell['repetition']
            # read any config attribute that was specified in the yaml batch file
            a.local_address_prefix = t['local_address_prefix'] if 'local_address_prefix' in t else '10.10.0.0/16'
            for field in ['single_table', 'docker_network_name', 'repeat', 'file', 'target_local_address',
                            'label', 'target_local_address', 'monitor_local_address', 'target_router_id',
                            'monitor_router_id', 'target_config_file', 'filter_type','mrt_injector', 'mrt_file',
                            'tester_type', 'license_file', 'version', 'threads',
                            'tester_trace_io']:
                # Keyed on the value, not on the key being present: a target
                # written `tester_type:` with nothing after it parses as None,
                # which is the very slip the default exists to catch, and a
                # presence test skips the default for exactly that case.
                value = t.get(field)
                setattr(a, field,
                        batch_target_defaults(t).get(field) if value is None
                        else value)

            for field in ['as_path_list_num', 'prefix_list_num', 'community_list_num', 'ext_community_list_num']:
                setattr(a, field, t[field]) if field in t else setattr(a, field, 0)
            completed[cell_id] = bench(a)

            # Checkpoint both files atomically after every cell. If the process
            # dies later, --resume can skip every cell whose result made it to
            # disk -- including a repetition interrupted part way through, since
            # a cell's identity does not depend on how many of its siblings ran.
            write_batch_progress(progress_path, completed, order=order, seed=seed,
                                 previous_seeds=superseded)
            write_batch_csv(results_path(args.results_dir, f"{test['name']}.csv"),
                            batch_report_rows(test['name'], cells, completed))
            # Kept current cell by cell, like the CSV: a batch that dies in its
            # third pass should still say what its first two measured.
            for line in publish_batch_summary(summary_path, test['name'], cells,
                                              completed, repetitions,
                                              describe=False):
                print(line)

        # A crash after the progress checkpoint but before its matching CSV
        # replacement can leave the CSV one cell behind. Rebuild it even when
        # resume skipped every cell.
        results = batch_report_rows(test['name'], cells, completed)
        write_batch_csv(results_path(args.results_dir, f"{test['name']}.csv"), results)

        print()
        print(stats_header())
        for stat in results:
            print(','.join(map(str, stat)))

        # Every pass's row is above; this says what they do and do not agree
        # about. The rows are never replaced by it -- a summary that hid the
        # observations behind it would be a number nobody could check. A
        # single-pass test with nothing to report prints nothing at all.
        summary_lines = publish_batch_summary(summary_path, test['name'], cells,
                                              completed, repetitions)
        if summary_lines:
            print()
            for line in summary_lines:
                print(line)

        create_batch_graphs(results, test['name'], results_dir=args.results_dir)


def batch_cell_id(test_name, cell):
    """Return a stable, human-inspectable identity for one batch matrix cell.

    Keyed by what the cell is, never by when it ran: `ordinal` is its position
    within one pass over the matrix and `repetition` says which pass, so
    resume keeps matching when the execution order changes and two passes of
    one cell are told apart by the one field that differs.

    A single-pass test carries no `repetition` key at all, which is what a cell
    id looked like before repetitions existed. That is deliberate: an in-flight
    batch written by an older build resumes exactly as it did, instead of
    finding no id it recognises and silently re-running hours of finished work.
    """
    identity = {
        'test': test_name,
        'ordinal': cell['ordinal'],
        'neighbors': cell['neighbors'],
        'prefixes': cell['prefixes'],
        'filter': cell['filter'],
        'target': cell['target'],
    }
    if cell['repetition'] is not None:
        identity['repetition'] = cell['repetition']
    # Omitted at the default for the same reason `repetition` is omitted for a
    # single-pass test: a disjoint cell's id keeps exactly the shape it had
    # before this flag existed, so an in-flight batch written by an older build
    # resumes instead of costing the operator every completed cell, and
    # `BATCH_PROGRESS_SCHEMA_VERSION` does not have to move.
    diversity = cell.get('path_diversity') or DEFAULT_PATH_DIVERSITY
    if diversity != DEFAULT_PATH_DIVERSITY:
        identity['path_diversity'] = diversity
    return json.dumps(identity, sort_keys=True, separators=(',', ':'), default=str)


def batch_cell_description(cell, repetitions=1):
    target = cell['target']
    version = target.get('version')
    target_name = target.get('label') or target['name']
    if version and version not in target_name:
        target_name = '{0} {1}'.format(target_name, version)
    described = '{0}, peers={1}, prefixes={2}, filter={3}'.format(
        target_name, cell['neighbors'], cell['prefixes'], cell['filter'])
    diversity = cell.get('path_diversity') or DEFAULT_PATH_DIVERSITY
    if diversity != DEFAULT_PATH_DIVERSITY:
        # Named only when it is not the disjoint workload, so every existing
        # printed line and every summary description is unchanged.
        described = '{0}, paths per prefix={1}'.format(described, diversity)
    if repetitions > 1:
        described = '{0}, repetition {1}/{2}'.format(
            described, cell['repetition'], repetitions)
    return described


# Unchanged by repetitions: a single-pass cell id has the shape it always had,
# so a file written by an older build still resumes rather than costing the
# operator every completed cell.
BATCH_PROGRESS_SCHEMA_VERSION = 1


def load_batch_progress_document(path):
    """The whole progress file: the completed cells, and how they were sequenced.

    The sequencing keys are optional, so a file written before ordering existed
    still loads at the same schema version and resumes as it always did.
    """
    if not os.path.exists(path):
        return {'cells': {}}
    with open(path, 'r') as f:
        document = json.load(f)
    if (document.get('schema_version') != BATCH_PROGRESS_SCHEMA_VERSION
            or not isinstance(document.get('cells'), dict)):
        raise ValueError('unsupported or malformed batch progress file: {0}'.format(path))
    return document


def load_batch_progress(path):
    return load_batch_progress_document(path)['cells']


def atomic_write(path, write):
    temp_path = '{0}.tmp'.format(path)
    try:
        with open(temp_path, 'w') as f:
            write(f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def write_batch_progress(path, completed, order=None, seed=None, previous_seeds=None):
    document = {'schema_version': BATCH_PROGRESS_SCHEMA_VERSION, 'cells': completed}
    if order is not None:
        document['order'] = order
    if previous_seeds:
        # Sequences some of these rows ran under before the config was edited.
        # Kept because the file is rewritten whole on every checkpoint, so
        # anything not carried forward is gone.
        document['previous_seeds'] = previous_seeds
    if seed is not None:
        # The one durable record of the sequence a batch ran in. It is written
        # before the first cell, not after it: a seed that only appeared once a
        # cell had finished would be missing from exactly the runs that died
        # early, and a resumed batch would draw a new one.
        document['seed'] = seed

    def write(f):
        json.dump(document, f, indent=2, sort_keys=True)
        f.write('\n')
    atomic_write(path, write)


def write_batch_csv(path, results):
    def write(f):
        f.write(stats_header() + '\n')
        for stat in results:
            f.write(','.join(map(str, stat)) + '\n')
    atomic_write(path, write)

def create_batch_graphs(results, name, results_dir=DEFAULT_RESULTS_DIR):
    # stat_index values are positions in the row built by create_output_stats();
    # changing that row's layout silently mislabels every graph below.
    for test_name, stat_index, suffix, ylabel in [
        ('total time', 11, 'total_time', 'seconds'),
        ('elapsed', 8, 'elapsed', 'seconds'),
        # index 7 is monitor_wait_time -- the wait for the monitor's session to
        # the target to establish. This plotted index 9 (first-received time)
        # under the 'neighbor' label, which is a different measurement.
        ('neighbor', 7, 'neighbor', 'seconds'),
        ('route reception', 10, 'route_reception', 'seconds'),
        ('max cpu', 12, 'max_cpu', '%'),
        ('max mem', 13, 'max_mem', 'GB'),
        ('min idle', 14, 'min_idle', '%'),
        ('min free mem', 15, 'min_free', 'GB'),
        ('tester errors', 20, 'tester_error', 'errors'),
        ('prefixes at monitor', 6, 'monitor_prefixes', 'seconds'),
    ]:
        create_graph(results, test_name=test_name, stat_index=stat_index,
                     test_file=f"bgperf_{name}_{suffix}.png", ylabel=ylabel,
                     results_dir=results_dir)

def mem_human(v):
    if v > 1024 * 1024 * 1024:
        return '{0:.2f}GB'.format(float(v) / (1024 * 1024 * 1024))
    elif v > 1024 * 1024:
        return '{0:.2f}MB'.format(float(v) / (1024 * 1024))
    elif v > 1024:
        return '{0:.2f}KB'.format(float(v) / 1024)
    else:
        return '{0:.2f}B'.format(float(v))

def get_hardware_info():
    cores = os.cpu_count()
    mem = virtual_memory().total
    return cores, mem

def gen_conf(args):
    ''' This creates the scenario.yml that other things need to read to produce device config
    '''
    neighbor_num = args.neighbor_num
    prefix = args.prefix_num
    as_path_list = args.as_path_list_num
    prefix_list = args.prefix_list_num
    community_list = args.community_list_num
    ext_community_list = args.ext_community_list_num
    tester_type = args.tester_type
    # Validated at every entry point rather than here, exactly as
    # `prefix_scope` is: this reads what was asked for and
    # `path_diversity_groups()` refuses to do the arithmetic if it is not a
    # number the fleet can be dealt into.
    diversity = getattr(args, 'path_diversity', None) or DEFAULT_PATH_DIVERSITY


    local_address_prefix = netaddr.IPNetwork(args.local_address_prefix)

    if args.target_local_address:
        target_local_address = netaddr.IPAddress(args.target_local_address)
    else:
        target_local_address = local_address_prefix.broadcast - 1

    if args.monitor_local_address:
        monitor_local_address = netaddr.IPAddress(args.monitor_local_address)
    else:
        monitor_local_address = local_address_prefix.ip + 2

    if args.target_router_id:
        target_router_id = netaddr.IPAddress(args.target_router_id)
    else:
        target_router_id = target_local_address

    if args.monitor_router_id:
        monitor_router_id = netaddr.IPAddress(args.monitor_router_id)
    else:
        monitor_router_id = monitor_local_address

    filter_test = args.filter_test if 'filter_test' in args else None
    
    conf = {}
    conf['local_prefix'] = str(local_address_prefix)
    conf['target'] = {
        'as': 1000,
        'router-id': str(target_router_id),
        'local-address': str(target_local_address),
        'single-table': args.single_table,
    }
    if getattr(args, 'threads', None):
        conf['target']['threads'] = args.threads

    if args.license_file:
        conf['target']['license_file'] = args.license_file

    if args.target_config_file:
        conf['target']['config_path'] = args.target_config_file
    
    if filter_test:
        conf['target']['filter_test'] = filter_test
        print(f"FILTERING: {filter_test}")

    conf['monitor'] = {
        'as': 1001,
        'router-id': str(monitor_router_id),
        'local-address': str(monitor_local_address),
        # What the target re-advertises, which is one best path per distinct
        # prefix -- `groups * p`, not the `n * p` paths the fleet offers. At
        # the default diversity there is one group per peer and this is the
        # `n * p` it has always been.
        'check-points': [prefix * path_diversity_groups(neighbor_num,
                                                        diversity)],
    }

    mrt_injector = None
    if tester_type == 'gobgp' or tester_type == 'bgpdump2':
        mrt_injector = tester_type
        

    if mrt_injector:
        conf['monitor']['check-points'] = [prefix]

    if mrt_injector == 'gobgp': #gobgp doesn't send everything with mrt
        conf['monitor']['check-points'][0] = int(conf['monitor']['check-points'][0] * 0.93)
    else: #args.target == 'bird': # bird seems to reject severalhandfuls of routes
        conf['monitor']['check-points'][0] = int(conf['monitor']['check-points'][0] * 0.99)

    it = netaddr.iter_iprange('90.0.0.0', '100.0.0.0')

    conf['policy'] = {}

    assignment = []

    if prefix_list > 0:
        name = 'p1'
        conf['policy'][name] = {
            'match': [{
                'type': 'prefix',
                'value': list('{0}/32'.format(ip) for ip in islice(it, prefix_list)),
            }],
        }
        assignment.append(name)

    if as_path_list > 0:
        name = 'p2'
        conf['policy'][name] = {
            'match': [{
                'type': 'as-path',
                'value': list(range(10000, 10000 + as_path_list)),
            }],
        }
        assignment.append(name)

    if community_list > 0:
        name = 'p3'
        conf['policy'][name] = {
            'match': [{
                'type': 'community',
                'value': list('{0}:{1}'.format(int(i/(1<<16)), i%(1<<16)) for i in range(community_list)),
            }],
        }
        assignment.append(name)

    if ext_community_list > 0:
        name = 'p4'
        conf['policy'][name] = {
            'match': [{
                'type': 'ext-community',
                'value': list('rt:{0}:{1}'.format(int(i/(1<<16)), i%(1<<16)) for i in range(ext_community_list)),
            }],
        }
        assignment.append(name)

    neighbors = {}
    configured_neighbors_cnt = 0
    for i in range(3, neighbor_num+3+2):
        if configured_neighbors_cnt == neighbor_num:
            break
        curr_ip = local_address_prefix.ip + i
        if curr_ip in [target_local_address, monitor_local_address]:
            print(('skipping tester\'s neighbor with IP {} because it collides with target or monitor'.format(curr_ip)))
            continue
        router_id = str(local_address_prefix.ip + i)
        neighbors[router_id] = {
            'as': 1000 + i,
            'router-id': router_id,
            'local-address': router_id,
            # Keyed on the count of configured neighbours rather than on
            # `i`, which skips the target's and monitor's addresses: an
            # off-by-one there would put one group's peers either side of a
            # block boundary and quietly change how many competing paths each
            # prefix gets. The one-argument form at the default diversity
            # renders exactly the scenario body it always has.
            'paths': ('${{gen_paths({0})}}'.format(prefix)
                      if diversity == DEFAULT_PATH_DIVERSITY
                      else '${{gen_paths({0}, {1})}}'.format(
                          prefix, configured_neighbors_cnt // diversity)),
            'count': prefix,
            'check-points': prefix,
            'filter': {
                args.filter_type: assignment,
            },
        }
        configured_neighbors_cnt += 1

    print(f"Tester Type: {tester_type}")
    if tester_type == 'exa' or tester_type == 'bird':
        conf['testers'] = [{
            'name': 'tester',
            'type': tester_type,
            'neighbors': neighbors,
        }]
    else:
        conf['testers'] = neighbor_num*[None]
        
        mrt_file = args.mrt_file 
        if not mrt_file:
            print("Need to provide an mrtfile to send")
            exit(1)
        for i in range(neighbor_num):
            router_id = str(local_address_prefix.ip + i+3)
            conf['testers'][i] = {
                'name': f'mrt-injector{i}',
                'type': 'mrt',
                'mrt_injector': mrt_injector,
                'mrt-index': i,
                'trace-io': bool(getattr(args, 'tester_trace_io', False)),
                'neighbors': {
                    router_id: {
                        'as': 1000+i+3,
                        'local-address': router_id,
                        'router-id': router_id,
                        'mrt-file': mrt_file,
                        'only-best': True,
                        'count': prefix,
                        'check-points': int(conf['monitor']['check-points'][0])

                    }
                }
            }

    yaml.Dumper.ignore_aliases = lambda *args : True
    return gen_mako_macro() + yaml.dump(conf, default_flow_style=False)


def check_generator_matches_workload(args):
    """Refuse a generator and a workload that do not go together, both ways.

    Each direction fails differently and neither was refused here. With
    `--mrt-file` and a synthetic generator the run is *quietly wrong*: `-t
    frr_c -n 10 -p 1050000 --mrt-file rib.mrt` with `-g bgpdump2` forgotten
    offers 10.5M synthetic routes against a check-point of `n * p * 0.99`,
    converges, and publishes a row that reads like the MRT run it is not.

    With an MRT generator and no file it is loud but *late*: `gen_conf()` ends
    at a bare `exit(1)`, and by then `bench()` has run
    `remove_target_containers()`, `remove_old_containers()` and `rmtree()` over
    the config directory -- the previous run's containers and logs, which this
    repository keeps deliberately so a failure can be investigated. That is
    what the guards above the teardown are for, and this belongs with them.
    """
    tester = getattr(args, 'tester_type', None)
    mrt_file = getattr(args, 'mrt_file', None)
    named = mrt_keys_without_an_mrt_generator(tester, mrt_file)
    if named:
        sys.exit(
            '--mrt-file is set and -g/--tester-type is {0!r}, which '
            'synthesises prefixes and never reads it. Use one of {1}'.format(
                tester, ', '.join(MRT_TESTER_TYPES)))
    if tester in MRT_TESTER_TYPES and not mrt_file:
        sys.exit(
            '-g/--tester-type is {0!r}, which plays back an MRT file, and no '
            '--mrt-file was given'.format(tester))


def config(args):
    # The same guard `bench()` applies, and this is the path that most needs
    # it: `bench -f` deliberately skips the check on the reasoning that a
    # scenario file states its own neighbours, so a scenario stating *none* --
    # `check-points: [0]` and no testers, satisfied at zero routes -- passes
    # straight through. The tool that would have produced that file is this
    # one.
    for flag, value in (('-n/--neighbor-num', args.neighbor_num),
                        ('-p/--prefix-num', args.prefix_num)):
        if not _is_positive_count(value):
            sys.exit('{0} must be a whole number of 1 or more, got {1!r}'.format(
                flag, value))
    check_generator_matches_workload(args)
    try:
        args.path_diversity = resolve_path_diversity(
            getattr(args, 'path_diversity', None), args.neighbor_num,
            getattr(args, 'tester_type', None),
            getattr(args, 'prefix_scope', None))
    except ValueError as e:
        sys.exit(str(e))
    try:
        args.prefix_num = resolve_prefix_scope(
            getattr(args, 'prefix_scope', None), args.neighbor_num,
            args.prefix_num, getattr(args, 'tester_type', None))
    except ValueError as e:
        sys.exit(str(e))
    conf = gen_conf(args)

    with open(args.output, 'w') as f:
        f.write(conf)

def create_args_parser(main=True):
    parser = ArgumentParser(description='BGP performance measuring tool')
    parser.add_argument('-b', '--bench-name', default='bgperf2')
    parser.add_argument('-d', '--dir', default='/var/tmp')
    s = parser.add_subparsers()
    parser_doctor = s.add_parser('doctor', help='check env')
    parser_doctor.set_defaults(func=doctor)

    parser_images = s.add_parser('images', help='list daemon versions and which are built')
    parser_images.set_defaults(func=images)

    parser_verify = s.add_parser(
        'verify', help='start each built image and check it reports its own version')
    parser_verify.add_argument('-t', '--target', action='append', choices=sorted(BUILDABLE_IMAGES),
                               help='check only this image; repeatable. default: all built images')
    parser_verify.add_argument('--versions', type=str,
                               help='comma-separated versions to check instead of every built one; '
                                    'requires -t')
    parser_verify.set_defaults(func=verify)

    parser_dockerfile = s.add_parser('dockerfile',
                                     help='print the Dockerfile a version would build')
    parser_dockerfile.add_argument('image', choices=sorted(BUILDABLE_IMAGES))
    parser_dockerfile.add_argument('--version', type=str,
                                   help='version to render; default: the unversioned build')
    parser_dockerfile.set_defaults(func=dockerfile)

    parser_prepare = s.add_parser('prepare', help='prepare env')
    parser_prepare.add_argument('-f', '--force', action='store_true', help='build even if the container already exists')
    parser_prepare.add_argument('-n', '--no-cache', action='store_true')
    parser_prepare.add_argument('-t', '--target', action='append', choices=sorted(BUILDABLE_IMAGES),
                                help='build only this image; repeatable. default: all of them')
    parser_prepare.add_argument('--versions', type=str,
                                help='comma-separated versions to build instead of the daemon\'s '
                                     'default list; requires -t')
    parser_prepare.set_defaults(func=prepare)

    parser_update = s.add_parser('update', help='rebuild bgp docker images')
    parser_update.add_argument('image', choices=sorted(BUILDABLE_IMAGES) + ['all'])
    parser_update.add_argument('--version', type=str,
                               help='daemon version to build, e.g. 10.1 for FRR or 2.19.2 for '
                                    'BIRD; tagged as <image>:<version> and selectable with '
                                    '`bench --version`')
    parser_update.add_argument('--versions', type=str,
                               help='comma-separated list of versions to build in one go')
    parser_update.add_argument('-c', '--checkout', default=None,
                               help='raw git ref to build into the default (unversioned) tag')
    parser_update.add_argument('-n', '--no-cache', action='store_true')
    parser_update.set_defaults(func=update)

    def add_gen_conf_args(parser):
        parser.add_argument('-n', '--neighbor-num', default=100, type=int)
        parser.add_argument('-p', '--prefix-num', default=100, type=int)
        parser.add_argument('-l', '--filter-type', choices=['in', 'out'], default='in')
        parser.add_argument('-a', '--as-path-list-num', default=0, type=int)
        parser.add_argument('-e', '--prefix-list-num', default=0, type=int)
        parser.add_argument('-c', '--community-list-num', default=0, type=int)
        parser.add_argument('-x', '--ext-community-list-num', default=0, type=int)
        parser.add_argument('-s', '--single-table', action='store_true')
        parser.add_argument('--prefix-scope', choices=PREFIX_SCOPES,
                            default='per-peer',
                            help='how to read --prefix-num. per-peer (the '
                                 'default, and what bgperf has always meant) '
                                 'gives every peer that many prefixes, so the '
                                 'table is peers x prefixes. total reads it as '
                                 'the whole table and splits it evenly across '
                                 'the peers, which is how to raise the session '
                                 'count without also raising the route count. '
                                 'Must divide exactly, and does not apply to '
                                 'the MRT testers, where -p is already the '
                                 'whole table')
        parser.add_argument('--path-diversity', type=int,
                            default=DEFAULT_PATH_DIVERSITY,
                            help='how many peers announce each block of '
                                 'prefixes. 1 (the default, and what bgperf '
                                 'has always generated) gives every peer its '
                                 'own block, so the peers are disjoint and the '
                                 'target never selects between competing '
                                 'paths. Above 1 the peers are dealt into '
                                 'groups of that size and each group announces '
                                 'one shared block, so the fleet offers '
                                 'peers x prefixes paths for '
                                 '(peers / diversity) x prefixes distinct '
                                 'prefixes. Must divide the peer count '
                                 'exactly, and does not apply to the MRT '
                                 'testers or under --prefix-scope total')
        parser.add_argument('--threads', type=int,
                            help='worker threads the target should use. BIRD 3 runs with one '
                                 'worker unless told otherwise, so a 2.x-vs-3.x comparison needs '
                                 'this to mean anything. Ignored by daemons with no such setting')

        parser.add_argument('--tester-trace-io', action='store_true',
                            help='ask the generators for blocked-write evidence. Only bgpdump2 '
                                 'has any, behind its IO log class, and that class also logs '
                                 'every BGP message the injector receives, which inflates both '
                                 'reported_injection_s (the echo lengthens the walk the generator '
                                 'is timing) and injection_s (the log outgrows what one poll '
                                 'reads). Use it to find out whether a generator was blocked, '
                                 'not to time one, and never compare timings across it')

        parser.add_argument('--target-config-file', type=str,
                            help='target BGP daemon\'s configuration file')
        parser.add_argument('--local-address-prefix', type=str, default='10.10.0.0/16',
                            help='IPv4 prefix used for local addresses; default: 10.10.0.0/16')
        parser.add_argument('--target-local-address', type=str,
                            help='IPv4 address of the target; default: the last address of the '
                                 'local prefix given in --local-address-prefix')
        parser.add_argument('--target-router-id', type=str,
                            help='target\' router ID; default: same as --target-local-address')
        parser.add_argument('--monitor-local-address', type=str,
                            help='IPv4 address of the monitor; default: the second address of the '
                                 'local prefix given in --local-address-prefix')
        parser.add_argument('--monitor-router-id', type=str,
                            help='monitor\' router ID; default: same as --monitor-local-address')
        parser.add_argument('--filter_test', choices=['transit', 'ixp'], default=None)

    parser_bench = s.add_parser('bench', help='run benchmarks')
    parser_bench.add_argument('-t', '--target', choices=sorted(TARGET_CLASSES), default='bird')
    parser_bench.add_argument('-v', '--version', type=str,
                              help='version of the target daemon to bench, e.g. 10.1; uses the '
                                   'image built by `prepare`/`update`. default: the unversioned '
                                   'image, which tracks the daemon\'s default branch')
    parser_bench.add_argument('-i', '--image', help='specify custom docker image')
    parser_bench.add_argument('--mrt-file', type=str, 
                              help='mrt file, requires absolute path')
    parser_bench.add_argument('--license_file', type=str, help='filename of license necesary for EOS', default=None)
    parser_bench.add_argument('-g', '--tester-type', choices=sorted(TESTER_TYPES), default='bird')
    parser_bench.add_argument('--docker-network-name', help='Docker network name; this is the name given by \'docker network ls\'')
    parser_bench.add_argument('--bridge-name', help='Linux bridge name of the '
                              'interface corresponding to the Docker network; '
                              'use this argument only if bgperf can\'t '
                              'determine the Linux bridge name starting from '
                              'the Docker network name in case of tests of '
                              'remote targets.')
    parser_bench.add_argument('-r', '--repeat', action='store_true', help='use existing tester/monitor container')
    parser_bench.add_argument('-f', '--file', metavar='CONFIG_FILE')
    parser_bench.add_argument('-o', '--output', metavar='STAT_FILE')
    parser_bench.add_argument('--results-dir', default=DEFAULT_RESULTS_DIR,
                              help='directory for generated graphs and CSVs; '
                                   'default: {}'.format(DEFAULT_RESULTS_DIR))
    add_gen_conf_args(parser_bench)
    parser_bench.set_defaults(func=bench)

    parser_config = s.add_parser('config', help='generate config')
    parser_config.add_argument('-o', '--output', default='bgperf.yml', type=str)
    # `gen_conf()` reads `tester_type` and `mrt_file`, and only `bench` declared
    # them, so `config` raised AttributeError on every invocation -- a
    # documented subcommand that could not be run at all. Same defaults as
    # `bench`, so the scenario it prints is the one a bench would have used.
    parser_config.add_argument('-g', '--tester-type',
                               choices=sorted(TESTER_TYPES),
                               default='bird')
    parser_config.add_argument('--mrt-file', type=str,
                               help='mrt file, requires absolute path')
    parser_config.add_argument('--license_file', type=str, default=None,
                               help='filename of license necesary for EOS')
    add_gen_conf_args(parser_config)
    parser_config.set_defaults(func=config)

    parser_batch = s.add_parser('batch', help='run batch benchmarks')
    parser_batch.add_argument('-c', '--batch_config', type=str, help='batch config file')
    parser_batch.add_argument('--results-dir', default=DEFAULT_RESULTS_DIR,
                              help='directory for generated graphs and CSVs; '
                                   'default: {}'.format(DEFAULT_RESULTS_DIR))
    parser_batch.add_argument('--resume', action='store_true',
                              help='resume a partial batch by skipping cells with durable results')
    parser_batch.set_defaults(func=batch)

    return parser

if __name__ == '__main__':
    
    parser = create_args_parser()

    args = parser.parse_args()

    try:
        func = args.func
    except AttributeError:
        parser.error("too few arguments")

    try:
        args.func(args)
    except (ImageNotBuilt, VersionNotSupported, ImageBuildFailed) as e:
        # A missing, unselectable or unbuildable image is a setup mistake, not a
        # crash -- the message already carries the command that fixes it.
        sys.exit(str(e))
