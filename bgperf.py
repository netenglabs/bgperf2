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
from frr import FRRouting, FRRoutingTarget
from frr_compiled import FRRoutingCompiled, FRRoutingCompiledTarget
from rustybgp import RustyBGP, RustyBGPTarget
from openbgp import OpenBGP, OpenBGPTarget
from flock import Flock, FlockTarget
from tester import ExaBGPTester, BIRDTester
from mrt_tester import GoBGPMRTTester, ExaBGPMrtTester
from bgpdump2 import Bgpdump2, Bgpdump2Tester
from monitor import Monitor
from settings import dckr
from queue import Queue
from mako.template import Template
from packaging import version
from docker.types import IPAMConfig, IPAMPool
import re

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

    print('bgperf image', end=' ')
    if img_exists('bgperf/exabgp'):
        print('... ok')
    else:
        print('... not found. run `bgperf prepare`')

    for name in ['gobgp', 'bird', 'frr', 'frr_c', 'rustybgp', 'openbgp', 'flock']:
        print('{0} image'.format(name), end=' ')
        if img_exists('bgperf/{0}'.format(name)):
            print('... ok')
        else:
            print('... not found. if you want to bench {0}, run `bgperf prepare`'.format(name))

    print('/proc/sys/net/ipv4/neigh/default/gc_thresh3 ... {0}'.format(gc_thresh3()))


def prepare(args):
    ExaBGP.build_image(args.force, nocache=args.no_cache)
    ExaBGP_MRTParse.build_image(args.force, nocache=args.no_cache)
    GoBGP.build_image(args.force, nocache=args.no_cache)
    BIRD.build_image(args.force, nocache=args.no_cache)
    FRRouting.build_image(args.force,  nocache=args.no_cache)
    RustyBGP.build_image(args.force, nocache=args.no_cache)
    OpenBGP.build_image(args.force, nocache=args.no_cache)
    FRRoutingCompiled.build_image(args.force, nocache=args.no_cache)
    Bgpdump2.build_image(args.force, nocache=args.no_cache)



def update(args):
    if args.image == 'all' or args.image == 'exabgp':
        ExaBGP.build_image(True, checkout=args.checkout, nocache=args.no_cache)
    if args.image == 'all' or args.image == 'exabgp_mrtparse':
        ExaBGP_MRTParse.build_image(True, checkout=args.checkout, nocache=args.no_cache)
    if args.image == 'all' or args.image == 'gobgp':
        GoBGP.build_image(True, checkout=args.checkout, nocache=args.no_cache)
    if args.image == 'all' or args.image == 'bird':
        BIRD.build_image(True, checkout=args.checkout, nocache=args.no_cache)
    if args.image == 'all' or args.image == 'frr':
        FRRouting.build_image(True, checkout=args.checkout, nocache=args.no_cache)
    if args.image == 'all' or args.image == 'rustybgp':
        RustyBGP.build_image(True, checkout=args.checkout, nocache=args.no_cache)
    if args.image == 'all' or args.image == 'openbgp':
        OpenBGP.build_image(True, checkout=args.checkout, nocache=args.no_cache)
    if args.image == 'all' or args.image == 'flock':
        Flock.build_image(True, checkout=args.checkout, nocache=args.no_cache)
    if args.image == 'frr_c':
        FRRoutingCompiled.build_image(True, checkout=args.checkout, nocache=args.no_cache)
    if args.image == 'bgpdump2':
        Bgpdump2.build_image(True, checkout=args.checkout, nocache=args.no_cache)

def remove_target_containers():
    for target_class in [BIRDTarget, GoBGPTarget, FRRoutingTarget, FRRoutingCompiledTarget, RustyBGPTarget, OpenBGPTarget, FlockTarget]:
        if ctn_exists(target_class.CONTAINER_NAME):
            print('removing target container', target_class.CONTAINER_NAME)
            dckr.remove_container(target_class.CONTAINER_NAME, force=True)

def remove_old_containers():
    if ctn_exists(Monitor.CONTAINER_NAME):
        print('removing monitor container', Monitor.CONTAINER_NAME)
        dckr.remove_container(Monitor.CONTAINER_NAME, force=True)

    for ctn_name in get_ctn_names():
        if ctn_name.startswith(ExaBGPTester.CONTAINER_NAME_PREFIX) or \
            ctn_name.startswith(ExaBGPMrtTester.CONTAINER_NAME_PREFIX) or \
            ctn_name.startswith(GoBGPMRTTester.CONTAINER_NAME_PREFIX) or \
            ctn_name.startswith(Bgpdump2Tester.CONTAINER_NAME_PREFIX) or \
            ctn_name.startswith(BIRDTester.CONTAINER_NAME_PREFIX):
            print('removing tester container', ctn_name)
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
    
    remove_target_containers()

    if not args.repeat:
        remove_old_containers()

        if os.path.exists(config_dir):
            shutil.rmtree(config_dir)

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

    is_remote = True if 'remote' in conf['target'] and conf['target']['remote'] else False

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
        if args.target == 'gobgp':
            target_class = GoBGPTarget
        elif args.target == 'bird':
            target_class = BIRDTarget
        elif args.target == 'frr':
            target_class = FRRoutingTarget
        elif args.target == 'frr_c':
            target_class = FRRoutingCompiledTarget
        elif args.target == 'rustybgp':
            target_class = RustyBGPTarget
        elif args.target == 'openbgp':
            target_class = OpenBGPTarget
        elif args.target == 'flock':
            target_class = FlockTarget
        else:
            print(f"incorrect target {args.target}")
        print('run', args.target)
        if args.image:
            target = target_class('{0}/{1}'.format(config_dir, args.target), conf['target'], image=args.image)
        else:
            target = target_class('{0}/{1}'.format(config_dir, args.target), conf['target'])
        target.run(conf, dckr_net_name)

    time.sleep(1)

    output_stats['monitor_wait_time'] = m.wait_established(conf['target']['local-address'])
    output_stats['cores'], output_stats['memory'] = get_hardware_info()

    start = datetime.datetime.now()

    q = Queue()

    m.stats(q)
    controller_idle_percent(q)
    controller_memory_free(q)
    if not is_remote:
        target.stats(q)
        target.neighbor_stats(q)


    # want to launch all the neighbors at the same(ish) time
    # launch them after the test starts because as soon as they start they can send info at lest for mrt
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
    percent_idle = 0
    mem_free = 0

    recved_checkpoint = False
    neighbors_checkpoint = False
    last_recved = 0
    last_recved_count = 0
    last_neighbors_checked = 0
    recved = 0
    less_last_received = 0
    while True:
        info = q.get()

        if not is_remote and info['who'] == target.name:
            if 'neighbors_checked' in info:
                if all(value == True for value in info['neighbors_checked'].values()):    
                    neighbors_checked = sum(1 if value == True else 0 for value in info['neighbors_checked'].values())
                    neighbors_checkpoint = True
                else:
                    neighbors_checked = sum(1 if value == True else 0 for value in info['neighbors_checked'].values())
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
            
            if last_recved > recved:
                if neighbors_checked >= last_neighbors_checked:
                    less_last_received += 1
                else:
                    less_last_received = 0
                if less_last_received >= 10 and (last_recved - recved) / last_recved > .01: 
                   # breakpoint()
                    output_stats['recved'] = recved
                    f.close() if f else None
                    output_stats['fail_msg'] = f"FAILED: dropping received count {recved} neighbors_checked {neighbors_checked}"
                    output_stats['tester_errors'] = tester_class.find_errors() 
                    output_stats['tester_timeouts'] = tester_class.find_timeouts()      
                    print("FAILED")
                    o_s = finish_bench(args, output_stats, bench_stats, bench_start,target, m, fail=True) 
                    return o_s

            elif (recved > 0 or last_neighbors_checked > 0) and recved == last_recved:
                last_recved_count +=1
            else:
                last_recved = recved
                last_recved_count = 0

            if neighbors_checked != last_neighbors_checked:
                last_neighbors_checked = neighbors_checked
                last_recved_count = 0

            if elapsed.seconds > 0:
                rm_line()

            print('elapsed: {0}sec, cpu: {1:>4.2f}%, mem: {2}, mon recved: {3}, neighbors: {4}, %idle {5}, free mem {6}'.format(elapsed.seconds, 
                    cpu, mem_human(mem), recved, neighbors_checked, percent_idle, mem_human(mem_free)))
            bench_stats.append([elapsed.seconds, float(f"{cpu:>4.2f}"), mem, recved, neighbors_checked, percent_idle, mem_free])
            f.write('{0}, {1}, {2}, {3}\n'.format(elapsed.seconds, cpu, mem, recved)) if f else None
            f.flush() if f else None

            if recved > 0 and output_stats['first_received_time'] == start - start:
                output_stats['first_received_time'] = elapsed

            if recved_checkpoint and neighbors_checkpoint:
                output_stats['recved']= recved       
                output_stats['tester_errors'] = tester_class.find_errors() 
                output_stats['tester_timeouts'] = tester_class.find_timeouts() 
                f.close() if f else None
                o_s = finish_bench(args, output_stats,bench_stats, bench_start,target, m)  
                return o_s


            if info['checked']:
                recved_checkpoint = True

        
            if elapsed.seconds % 120 == 0 and elapsed.seconds > 1:
                bench_prefix = f"{args.target}_{args.tester_type}_{args.prefix_num}_{args.neighbor_num}"
                create_bench_graphs(bench_stats, prefix=bench_prefix)       

        if last_recved_count == 600: # Too many of the same counts in a row, not progressing
            output_stats['recved']= recved          
            f.close() if f else None
            output_stats['fail_msg'] = f"FAILED: stuck received count {recved} neighbors_checked {neighbors_checked}"
            output_stats['tester_errors'] = tester_class.find_errors()
            output_stats['tester_timeouts'] = tester_class.find_timeouts() 
            print("FAILED")
            o_s = finish_bench(args, output_stats,bench_stats, bench_start,target, m, fail=True)  
            return o_s



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
    bench_prefix = f"{args.target}_{args.tester_type}_{args.prefix_num}_{args.neighbor_num}"
    create_bench_graphs(bench_stats, prefix=bench_prefix)
    return o_s



def print_final_stats(args, target_version, stats):
    
    print(f"{args.target}: {target_version}")
    print(f"Max cpu: {stats['max_cpu']:4.2f}, max mem: {mem_human(stats['max_mem'])}")
    print(f"Min %idle {stats['min_idle']}, Min mem free {mem_human(stats['min_free'])}")
    print(f"Time since first received prefix: {stats['elapsed'].seconds - stats['first_received_time'].seconds}")

    print(f"total time: {stats['total_time']:.2f}s")
    print(f"tester errors: {stats['tester_errors']}")
    print(f"tester timeouts: {stats['tester_timeouts']}")
    print()

def stats_header():
    return("name, target, version, peers, prefixes per peer, required, received, monitor (s), elapsed (s), prefix received (s), testers (s), total time, max cpu %, max mem (GB), min idle%, min free mem (GB), flags, date,cores,Mem (GB), tester errors, failed, MSG")


def create_output_stats(args, target_version, stats, fail=False):
    e = stats['elapsed'].seconds
    f = stats['first_received_time'].seconds 
    d = datetime.date.today().strftime("%Y-%m-%d")
    if 'label' in args and args.label:
        name = args.label
    else:
        name = args.target
    out = [name, args.target, target_version, str(args.neighbor_num), str(args.prefix_num)]
    out.extend([stats['required'], stats['recved']])
    out.extend([stats['monitor_wait_time'], e, f , e-f, float(format(stats['total_time'], ".2f"))])
    out.extend([round(stats['max_cpu']), float(format(stats['max_mem']/1024/1024/1024, ".3f"))])
    out.extend ([round(stats['min_idle']), float(format(stats['min_free']/1024/1024/1024, ".3f"))])
    out.extend(['-s' if args.single_table else '', d, str(stats['cores']), mem_human(stats['memory'])])
    out.extend([stats['tester_errors'],stats['tester_timeouts']])
    if fail:
        out.extend(['FAILED'])
    else:
        out.extend([''])
    if 'fail_msg' in stats:
        out.extend([stats['fail_msg']])
    else:
        out.extend([''])
    return out


def create_ts_graph(bench_stats, stat_index=1, filename='ts.png', ylabel='%cpu', diviser=1):
    plt.figure()
    #bench_stats.pop(0)
    data = np.array(bench_stats)
    plt.plot(data[:,0], data[:,stat_index]/diviser)
    
    #don't want to see 0 element of data, not and accurate measure of what's happening
    #plt.xlim([1, len(data)])
    plt.ylabel(ylabel)
    plt.xlabel('elapsed seconds')
    plt.show()
    plt.savefig(filename)
    plt.close()
    plt.cla()
    plt.clf()


def create_bench_graphs(bench_stats, prefix='ts_data'):
    create_ts_graph(bench_stats, filename=f"{prefix}_cpu.png")
    create_ts_graph(bench_stats, stat_index=2, filename=f"{prefix}_mem_used", ylabel="GB", diviser=1024*1024*1024)
    create_ts_graph(bench_stats, stat_index=3, filename=f"{prefix}_mon_received", ylabel='prefixes')
    create_ts_graph(bench_stats, stat_index=4, filename=f"{prefix}_neighbors", ylabel='neighbors')
    create_ts_graph(bench_stats, stat_index=5, filename=f"{prefix}_machine_idle", ylabel="%")
    create_ts_graph(bench_stats, stat_index=6, filename=f"{prefix}_free_mem", ylabel="GB", diviser=1024*1024*1024)

def create_graph(stats, test_name='total time', stat_index=8, test_file='total_time.png', ylabel='seconds'):
    labels = {}
    data = defaultdict(list)

    try:
        for stat in stats:
            labels[stat[0]] = True

            if len(stat) > 23 and stat[22] == 'FAILED':# this means that it failed for some reason
                data[f"{stat[3]}n_{stat[4]}p"].append(0)
            else:
                data[f"{stat[3]}n_{stat[4]}p"].append(float(stat[stat_index]))
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
    plt.savefig(test_file)

def batch(args):
    """ runs several tests together, produces all the stats together and creates graphs
    requires a yaml file to describe the batch of tests to run

    it iterates through a list of targets, number of neighbors and number of prefixes
    other variables can be set, but not iterated through
    """
    with open(args.batch_config, 'r') as f:
        batch_config = yaml.safe_load(f)

    for test in batch_config['tests']:
        results = []
        for n in test['neighbors']:
            for p in test['prefixes']:
                for t in test['targets']:
                    a = argparse.Namespace(**vars(args))
                    a.func = bench
                    a.image = None
                    a.output = None
                    a.target = t['name']

                    a.prefix_num = p
                    a.neighbor_num = n
                    # read any config attribute that was specified in the yaml batch file
                    a.local_address_prefix = t['local_address_prefix'] if 'local_address_prefix' in t else '10.10.0.0/16'
                    for field in ['single_table', 'docker_network_name', 'repeat', 'file', 'target_local_address',
                                    'label', 'target_local_address', 'monitor_local_address', 'target_router_id',
                                    'monitor_router_id', 'target_config_file', 'filter_type','mrt_injector', 'mrt_file',
                                    'tester_type']:
                        setattr(a, field, t[field]) if field in t else setattr(a, field, None)

                    for field in ['as_path_list_num', 'prefix_list_num', 'community_list_num', 'ext_community_list_num']:
                        setattr(a, field, t[field]) if field in t else setattr(a, field, 0)    
                    results.append(bench(a))

                    # update this each time in case something crashes
                    with open(f"{test['name']}.csv", 'w') as f:
                        f.write(stats_header() + '\n')
                        for stat in results:
                            f.write(','.join(map(str, stat)) + '\n')

        print()
        print(stats_header())
        for stat in results:
            print(','.join(map(str, stat)))


        create_batch_graphs(results, test['name'])

def create_batch_graphs(results, name):
    create_graph(results, test_name='total time', stat_index=11, test_file=f"bgperf_{name}_total_time.png")
    create_graph(results, test_name='elapsed', stat_index=8, test_file=f"bgperf_{name}_elapsed.png")
    create_graph(results, test_name='neighbor', stat_index=9, test_file=f"bgperf_{name}_neighbor.png")
    create_graph(results, test_name='route reception', stat_index=10, test_file=f"bgperf_{name}_route_reception.png")
    create_graph(results, test_name='max cpu', stat_index=12, test_file=f"bgperf_{name}_max_cpu.png", ylabel="%")
    create_graph(results, test_name='max mem', stat_index=13, test_file=f"bgperf_{name}_max_mem.png", ylabel="GB")
    create_graph(results, test_name='min idle', stat_index=14, test_file=f"bgperf_{name}_min_idle.png", ylabel="%")
    create_graph(results, test_name='min free mem', stat_index=15, test_file=f"bgperf_{name}_min_free.png", ylabel="GB")
    create_graph(results, test_name='tester errors', stat_index=20, test_file=f"bgperf_{name}_tester_error.png", ylabel="errors")

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

    if args.target_config_file:
        conf['target']['config_path'] = args.target_config_file
    
    if filter_test:
        conf['target']['filter-test'] = filter_test

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
    elif args.target == 'bird': # bird seems to reject severalhandfuls of routes
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
    parser.add_argument('-b', '--bench-name', default='bgperf')
    parser.add_argument('-d', '--dir', default='/tmp')
    s = parser.add_subparsers()
    parser_doctor = s.add_parser('doctor', help='check env')
    parser_doctor.set_defaults(func=doctor)

    parser_prepare = s.add_parser('prepare', help='prepare env')
    parser_prepare.add_argument('-f', '--force', action='store_true', help='build even if the container already exists')
    parser_prepare.add_argument('-n', '--no-cache', action='store_true')
    parser_prepare.set_defaults(func=prepare)

    parser_update = s.add_parser('update', help='rebuild bgp docker images')
    parser_update.add_argument('image', choices=['exabgp', 'exabgp_mrtparse', 'gobgp', 'bird', 'frr', 'frr_c', 
                                'rustybgp', 'openbgp', 'flock', 'bgpdump2', 'all'])
    parser_update.add_argument('-c', '--checkout', default='HEAD')
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
        parser.add_argument('--filter-test', choices=['transit', 'ixp'], default=None)

    parser_bench = s.add_parser('bench', help='run benchmarks')
    parser_bench.add_argument('-t', '--target', choices=['gobgp', 'bird', 'frr', 'frr_c', 'rustybgp', 'openbgp', 'flock'], default='gobgp')
    parser_bench.add_argument('-i', '--image', help='specify custom docker image')
    parser_bench.add_argument('--mrt-file', type=str, 
                              help='mrt file, requires absolute path')
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
    add_gen_conf_args(parser_bench)
    parser_bench.set_defaults(func=bench)

    parser_config = s.add_parser('config', help='generate config')
    parser_config.add_argument('-o', '--output', default='bgperf.yml', type=str)
    add_gen_conf_args(parser_config)
    parser_config.set_defaults(func=config)

    parser_batch = s.add_parser('batch', help='run batch benchmarks')
    parser_batch.add_argument('-c', '--batch_config', type=str, help='batch config file')
    parser_batch.set_defaults(func=batch)

    return parser

if __name__ == '__main__':
    
    parser = create_args_parser()

    args = parser.parse_args()

    try:
        func = args.func
    except AttributeError:
        parser.error("too few arguments")
    args.func(args)
