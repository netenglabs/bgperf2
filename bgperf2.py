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
import json
import os
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
                        is_memory_backed, own_process_tree, sample_processes)
from settings import dckr
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
    '''
    if 'label' in args and args.label:
        return args.label
    version = getattr(args, 'version', None)
    if version:
        return '{0} {1}'.format(args.target, version)
    return args.target


def gen_mako_macro():
    return '''<%
    import netaddr
    from itertools import islice

    it = netaddr.iter_iprange('100.0.0.0','160.0.0.0')

    def gen_paths(num):
        return list('{0}/32'.format(ip) for ip in islice(it, num))
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
    if not is_memory_backed(os.path.abspath(config_dir), mounts):
        return
    print('WARNING: {0} is on a memory-backed filesystem, so tester and target '
          'logs consume RAM.'.format(config_dir))
    print('         A 50-peer 100k-prefix BIRD run writes several GB there, which '
          'lowers the recorded')
    print('         min free mem without the daemon using it. Pass -d/--dir with a '
          'disk-backed path.')


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

    start = datetime.datetime.now()

    q = Queue()

    # Let the previous run's samplers go before starting this run's. batch()
    # reuses this process for every cell, so without the clear the new threads
    # would exit immediately on a flag the last run left set.
    controller_stop.clear()

    m.stats(q)
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

    f = open(args.output, 'w') if args.output else None
    cpu = 0
    mem = 0

    output_stats['max_cpu'] = 0
    output_stats['max_mem'] = 0
    output_stats['first_received_time'] = start - start
    output_stats['min_idle'] = 100
    output_stats['min_free'] = 1_000_000_000_000_000
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
        if info['who'] == m.name:

            elapsed = info['time'] - start
            output_stats['elapsed'] = elapsed
            recved = info['afi_safis'][0]['state']['accepted'] if 'accepted' in info['afi_safis'][0]['state'] else 0
            
            status = tracker.update(elapsed.seconds, recved, neighbors_checked,
                                    neighbors_received_full, info['checked'])

            if elapsed.seconds > 0:
                rm_line()

            print('elapsed: {0}sec, cpu: {1:>4.2f}%, mem: {2}, mon recved: {3}, neighbors_received: {4}, neighbors_accepted: {5}, %idle {6}, free mem {7}'.format(elapsed.seconds, 
                    cpu, mem_human(mem), recved, neighbors_received_full, neighbors_checked, percent_idle, mem_human(mem_free)))
            bench_stats.append([elapsed.seconds, float(f"{cpu:>4.2f}"), mem, recved, neighbors_checked, percent_idle, mem_free])
            f.write('{0}, {1}, {2}, {3}\n'.format(elapsed.seconds, cpu, mem, recved)) if f else None
            f.flush() if f else None

            if recved > 0 and output_stats['first_received_time'] == start - start:
                output_stats['first_received_time'] = elapsed

            if status == ConvergenceTracker.FAILED:
                output_stats['recved'] = recved
                output_stats['fail_msg'] = tracker.fail_msg
                f.close() if f else None
                print("FAILED")
                return finish_bench(args, output_stats, bench_stats, bench_start, target, m, testers, fail=True)

            if status == ConvergenceTracker.CONVERGED:
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
                return finish_bench(args, output_stats, bench_stats, bench_start, target, m, testers)

            if elapsed.seconds % 120 == 0 and elapsed.seconds > 1:
                bench_prefix = f"{args.target}_{args.tester_type}_{args.prefix_num}_{args.neighbor_num}"
                create_bench_graphs(bench_stats, prefix=bench_prefix, results_dir=args.results_dir)


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
    }
    path = results_path(args.results_dir, prefix + '.versions.json')
    with open(path, 'w') as f:
        json.dump(doc, f, indent=2, sort_keys=True)
        f.write('\n')
    return path


def finish_bench(args, output_stats, bench_stats, bench_start, target, m, testers=(), fail=False):

    bench_stop = time.time()
    output_stats['total_time'] = bench_stop - bench_start
    m.stop_monitoring = True
    target.stop_monitoring = True
    controller_stop.set()

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
    o_s = create_output_stats(args, target_version, output_stats, fail, provenance)
    print(stats_header())
    print(','.join(map(str, o_s)))
    print()
    # it would be better to clean things up, but often I want to to investigate where things ended up
    # remove_old_containers()
    # remove_target_containers()
    pre = run_name(args).replace(' ', '_')
    bench_prefix = f"{pre}_{args.tester_type}_{args.prefix_num}_{args.neighbor_num}"
    create_bench_graphs(bench_stats, prefix=bench_prefix, results_dir=args.results_dir)
    write_provenance(args, provenance, bench_prefix)
    return o_s



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


def create_output_stats(args, target_version, stats, fail=False, provenance=None):
    e = stats['elapsed'].seconds
    f = stats['first_received_time'].seconds
    d = datetime.date.today().strftime("%Y-%m-%d")
    out = [run_name(args), args.target, target_version, str(args.neighbor_num), str(args.prefix_num)]
    out.extend([stats['required'], stats['recved']])
    out.extend([stats['monitor_wait_time'], e, f , e-f, float(format(stats['total_time'], ".2f"))])
    out.extend([round(stats['max_cpu']), float(format(stats['max_mem']/1024/1024/1024, ".3f"))])
    out.extend ([round(stats['min_idle']), float(format(stats['min_free']/1024/1024/1024, ".3f"))])
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
    expanded = [(test, expand_target_versions(test['targets'])) for test in batch_config['tests']]
    check_batch_images([t for _, targets in expanded for t in targets])

    for test, targets in expanded:
        results = []
        for n in test['neighbors']:
            for p in test['prefixes']:
                for filter in test['filter_test']:
                    for t in targets:
                        a = argparse.Namespace(**vars(args))
                        a.func = bench
                        if 'image' in t:
                            a.image = t['image']
                        else:
                            a.image = None
                        a.output = None
                        a.target = t['name']
                        a.prefix_num = p
                        a.neighbor_num = n
                        a.filter_test = filter if filter != 'None' else None
                        # read any config attribute that was specified in the yaml batch file
                        a.local_address_prefix = t['local_address_prefix'] if 'local_address_prefix' in t else '10.10.0.0/16'
                        for field in ['single_table', 'docker_network_name', 'repeat', 'file', 'target_local_address',
                                        'label', 'target_local_address', 'monitor_local_address', 'target_router_id',
                                        'monitor_router_id', 'target_config_file', 'filter_type','mrt_injector', 'mrt_file',
                                        'tester_type', 'license_file', 'version', 'threads']:
                            setattr(a, field, t[field]) if field in t else setattr(a, field, None)

                        for field in ['as_path_list_num', 'prefix_list_num', 'community_list_num', 'ext_community_list_num']:
                            setattr(a, field, t[field]) if field in t else setattr(a, field, 0)
                        results.append(bench(a))

                        # update this each time in case something crashes
                        with open(results_path(args.results_dir, f"{test['name']}.csv"), 'w') as f:
                            f.write(stats_header() + '\n')
                            for stat in results:
                                f.write(','.join(map(str, stat)) + '\n')

        print()
        print(stats_header())
        for stat in results:
            print(','.join(map(str, stat)))


        create_batch_graphs(results, test['name'], results_dir=args.results_dir)

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
        'check-points': [prefix * neighbor_num],
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
            'paths': '${{gen_paths({0})}}'.format(prefix),
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


def config(args):
    conf = gen_conf(args)

    with open(args.output, 'w') as f:
        f.write(conf)

def create_args_parser(main=True):
    parser = ArgumentParser(description='BGP performance measuring tool')
    parser.add_argument('-b', '--bench-name', default='bgperf2')
    parser.add_argument('-d', '--dir', default='/tmp')
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
        parser.add_argument('--threads', type=int,
                            help='worker threads the target should use. BIRD 3 runs with one '
                                 'worker unless told otherwise, so a 2.x-vs-3.x comparison needs '
                                 'this to mean anything. Ignored by daemons with no such setting')

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
    parser_bench.add_argument('-g', '--tester-type', choices=['exa', 'bird', 'gobgp', 'bgpdump2'], default='bird')
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
    add_gen_conf_args(parser_config)
    parser_config.set_defaults(func=config)

    parser_batch = s.add_parser('batch', help='run batch benchmarks')
    parser_batch.add_argument('-c', '--batch_config', type=str, help='batch config file')
    parser_batch.add_argument('--results-dir', default=DEFAULT_RESULTS_DIR,
                              help='directory for generated graphs and CSVs; '
                                   'default: {}'.format(DEFAULT_RESULTS_DIR))
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
