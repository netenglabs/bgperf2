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
import os
import sys
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
            if args.force or not img_exists(tag):
                plan.append((cls, v, tag))

    if not plan:
        print('everything requested is already built (use -f to rebuild)')
        return

    print('building {0} image(s):'.format(len(plan)))
    for cls, v, tag in plan:
        print('  {0:<28} from {1}'.format(tag, cls.resolve_ref(v)))
    print()

    # A plan can be eight daemons and several hours. bird/gobgp/rustybgp all
    # track moving default branches, so one transient upstream breakage used to
    # be enough to lose every image after it -- keep going and report at the
    # end, but still exit non-zero so the failure cannot pass for success.
    failures = []
    for cls, v, tag in plan:
        try:
            cls.build_version(v, force=args.force, nocache=args.no_cache)
        except ImageBuildFailed as e:
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
    stop_monitoring = False
    def stats():
        output = {}
        output['who'] = 'controller'

        while True:
            if stop_monitoring == True:
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

def controller_memory_free(queue):
    '''collect stats on the whole machine that is running the tests'''
    stop_monitoring = False
    def stats():
        output = {}
        output['who'] = 'controller'

        while True:
            if stop_monitoring == True:
                return
            free = check_output(['free', '-m']).decode('utf-8').split('\n')[1]
            g = re.match(r'.*\d+\s+(\d+)', free).groups()
            output['free'] = float(g[0]) * 1024 * 1024
            output['time'] = datetime.datetime.now()
            queue.put(output)
            time.sleep(1)

    t = Thread(target=stats)
    t.daemon = True
    t.start()

stop_monitoring = False

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

    m.stats(q)
    controller_idle_percent(q)
    controller_memory_free(q)
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
                tester_dirs = [t.host_dir for t in testers]
                output_stats['tester_errors'] = tester_class.find_errors(tester_dirs)
                output_stats['tester_timeouts'] = tester_class.find_timeouts(tester_dirs)
                f.close() if f else None
                print("FAILED")
                return finish_bench(args, output_stats, bench_stats, bench_start, target, m, fail=True)

            if status == ConvergenceTracker.CONVERGED:
                assurance = tracker.assurance_samples
                output_stats['recved'] = recved
                tester_dirs = [t.host_dir for t in testers]
                output_stats['tester_errors'] = tester_class.find_errors(tester_dirs)
                output_stats['tester_timeouts'] = tester_class.find_timeouts(tester_dirs)

                f.close() if f else None

                # Drop the trailing assurance samples: the run was already done
                # by then, we were only confirming the count had stopped moving.
                # TODO: recalculate all min/max stats after removing these
                #  should move to always calculating based on bench_stats
                print(f"last recevied: {tracker.last_recved_count}")
                output_stats['elapsed'] = datetime.timedelta(
                    seconds=int(output_stats['elapsed'].seconds) - assurance + 1)
                bench_stats = bench_stats[0:len(bench_stats)-assurance]
                return finish_bench(args, output_stats, bench_stats, bench_start, target, m)

            if elapsed.seconds % 120 == 0 and elapsed.seconds > 1:
                bench_prefix = f"{args.target}_{args.tester_type}_{args.prefix_num}_{args.neighbor_num}"
                create_bench_graphs(bench_stats, prefix=bench_prefix, results_dir=args.results_dir)


def finish_bench(args, output_stats, bench_stats, bench_start,target, m, fail=False):
 
    bench_stop = time.time()
    output_stats['total_time'] = bench_stop - bench_start
    m.stop_monitoring = True
    target.stop_monitoring = True
    stop_monitoring = True
    del m

    target_version = target.exec_version_cmd()
  
    print_final_stats(args, target_version, output_stats)
    o_s = create_output_stats(args, target_version, output_stats, fail)
    print(stats_header())
    print(','.join(map(str, o_s)))
    print()
    # it would be better to clean things up, but often I want to to investigate where things ended up
    # remove_old_containers() 
    # remove_target_containers()
    pre = run_name(args).replace(' ', '_')
    bench_prefix = f"{pre}_{args.tester_type}_{args.prefix_num}_{args.neighbor_num}"
    create_bench_graphs(bench_stats, prefix=bench_prefix, results_dir=args.results_dir)
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
    return("name, target, version, peers, prefixes per peer, required, received, monitor (s), elapsed (s), prefix received (s), testers (s), total time, max cpu %, max mem (GB), min idle%, min free mem (GB), flags, date, cores, Mem (GB), tester errors, tester timeouts, failed, MSG, filters")


def create_output_stats(args, target_version, stats, fail=False):
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
