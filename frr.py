# Copyright (C) 2017 Network Device Education Foundation, Inc. ("NetDEF")
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

from base import *
import json
import re

class FRRouting(Container):
    CONTAINER_NAME = None
    GUEST_DIR = '/root/config'

    def __init__(self, host_dir, conf, image='bgperf/frr'):
        super(FRRouting, self).__init__(self.CONTAINER_NAME, image, host_dir, self.GUEST_DIR, conf)

    @classmethod
    def build_image(cls, force=False, tag='bgperf/frr', checkout='HEAD', nocache=False):
        cls.dockerfile = '''
FROM frrouting/frr:v7.5.1
'''.format(checkout)
        super(FRRouting, cls).build_image(force, tag, nocache)


class FRRoutingTarget(FRRouting, Target):

    CONTAINER_NAME = 'bgperf_frrouting_target'
    CONFIG_FILE_NAME = 'bgpd.conf'

    def write_config(self):

        config = """hostname bgpd
password zebra
router bgp {0}
bgp router-id {1}
no bgp ebgp-requires-policy
""".format(self.conf['as'], self.conf['router-id'])

        def gen_neighbor_config(n):
            local_addr = n['local-address']
            c = """  neighbor {0} remote-as {1}
  neighbor {0} advertisement-interval 1
  neighbor {0} disable-connected-check
  neighbor {0} timers 30 90
""".format(local_addr, n['as']) # adjust BGP hold-timers if desired
            if 'filter' in n:
                for p in (n['filter']['in'] if 'in' in n['filter'] else []):
                    c += '  neighbor {0} route-map {1} export\n'.format(local_addr, p)
            return c

        def gen_address_family_neighbor(n):
            local_addr = n['local-address']
            c = "    neighbor {0} activate\n".format(local_addr)
            c +="    neighbor {0} soft-reconfiguration inbound\n".format(local_addr)
            if 'filter_test' in self.conf:
                c +="    neighbor {0} route-map {1} in\n".format(local_addr, self.conf['filter_test'])
            return c

        neighbors = list(flatten(list(t.get('neighbors', {}).values()) for t in self.scenario_global_conf['testers'])) + [self.scenario_global_conf['monitor']]
        
        with open('{0}/{1}'.format(self.host_dir, self.CONFIG_FILE_NAME), 'w') as f:
            f.write(config)

            for n in neighbors:
                f.write(gen_neighbor_config(n))

            f.write("  address-family ipv4 unicast\n")
            for n in neighbors:
                f.write(gen_address_family_neighbor(n))
            f.write("  exit-address-family\n")

            if 'policy' in self.scenario_global_conf:
                seq = 10
                for k, v in self.scenario_global_conf['policy'].items():
                    match_info = []
                    for i, match in enumerate(v['match']):
                        n = '{0}_match_{1}'.format(k, i)
                        if match['type'] == 'prefix':
                            f.write(''.join('ip prefix-list {0} deny {1}\n'.format(n, p) for p in match['value']))
                            f.write('ip prefix-list {0} permit any\n'.format(n))
                        elif match['type'] == 'as-path':
                            f.write(''.join('bgp as-path access-list {0} deny _{1}_\n'.format(n, p) for p in match['value']))
                            f.write('bgp as-path access-list {0} permit .*\n'.format(n))
                        elif match['type'] == 'community':
                            f.write(''.join('bgp community-list standard {0} permit {1}\n'.format(n, p) for p in match['value']))
                            f.write('bgp community-list standard {0} permit\n'.format(n))
                        elif match['type'] == 'ext-community':
                            f.write(''.join('bgp extcommunity-list standard {0} permit {1} {2}\n'.format(n, *p.split(':', 1)) for p in match['value']))
                            f.write('bgp extcommunity-list standard {0} permit\n'.format(n))

                        match_info.append((match['type'], n))

                    f.write('route-map {0} permit {1}\n'.format(k, seq))
                    for info in match_info:
                        if info[0] == 'prefix':
                            f.write('match ip address prefix-list {0}\n'.format(info[1]))
                        elif info[0] == 'as-path':
                            f.write('match as-path {0}\n'.format(info[1]))
                        elif info[0] == 'community':
                            f.write('match community {0}\n'.format(info[1]))
                        elif info[0] == 'ext-community':
                            f.write('match extcommunity {0}\n'.format(info[1]))

                    seq += 10

            if 'filter_test' in self.conf:
                f.write(self.get_filter_test_config())

            # we need log level to debug so that we can find End-of-RIB
            f.write("log stdout debug\n") 

    def get_filter_test_config(self): 
        file = open("filters/frr.conf", mode='r')
        filters = file.read()
        file.close
        return filters

    def get_startup_cmd(self):
        return '\n'.join(
            ['#!/bin/bash',
             'ulimit -n 65536',
             'mv /etc/frr /etc/frr.old',
             'mkdir /etc/frr',
             'cp {guest_dir}/{config_file_name} /etc/frr/{config_file_name} && chown frr:frr /etc/frr/{config_file_name}',
             '/usr/lib/frr/bgpd -u frr -f /etc/frr/{config_file_name} -Z > {guest_dir}/bgpd.log 2>&1 &',
             #'cd /root/config',   
             #'perf record -F 99 -p 17 -g -- sleep 1300 > perf.out',
             #'perf script > /root/config/out.perf',
             ]
        ).format(
            guest_dir=self.guest_dir,
            config_file_name=self.CONFIG_FILE_NAME)
    
    def get_version_cmd(self):
        return ['vtysh', '-c', 'show version', '|', 'head -1']

    def exec_version_cmd(self):
        ret = super().exec_version_cmd()
        return ret.split('\n')[0]
    
    def get_neighbors_state(self):
        neighbors_accepted = {}
        neighbors_received = {}
        neighbor_received_output = self.local("vtysh -c 'sh ip bgp summary json'")
        if neighbor_received_output:
            neighbor_received_output = json.loads(neighbor_received_output.decode('utf-8'))

        for n in neighbor_received_output['ipv4Unicast']['peers'].keys():
            rcd = neighbor_received_output['ipv4Unicast']['peers'][n]['pfxRcd'] 
            neighbors_accepted[n] = rcd
        return neighbors_received, neighbors_accepted

    def _get_EOR_from_log(self, neighbors):
        # we are looking at the log files for End-Of-RIB
        # 2021/11/05 16:34:38 BGP: bgp_update_receive: rcvd End-of-RIB for IPv4 Unicast from 10.10.0.3 in vrf default

        with open(f"{self.host_dir}/bgpd.log") as f:
            log = f.readlines()
        EOR = re.compile(r".*rcvd End-of-RIB for IPv4 Unicast from (\d+\.\d+\.\d+\.\d+)")
        if len(log) > 1:
            for line in log:
                m_eor = EOR.match(line)
                if m_eor:
                    neighbors[m_eor.groups()[0]] = True

        return neighbors

    def get_neighbor_received_routes(self):
        # FRR doesn't have a counter to look at to see if all the prefixes have been sent
        # instead we have to look at the log file and see if End-of-RIB has been sent for the neighbor
        neighbors_received_full, neighbors_checked = super(FRRoutingTarget, self).get_neighbor_received_routes()

        assert(all(value == False for value in neighbors_received_full.values()))
        neighbors_received_full = self._get_EOR_from_log(neighbors_received_full)

        assert(len(neighbors_received_full) == len(neighbors_checked))

        return neighbors_received_full, neighbors_checked

