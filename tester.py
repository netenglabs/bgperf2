# Copyright (C) 2016 Nippon Telegraph and Telephone Corporation.
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

from base import Tester
from exabgp import ExaBGP
from bird import BIRD
import os
from  settings import dckr


class ExaBGPTester(Tester, ExaBGP):

    CONTAINER_NAME_PREFIX = 'bgperf_exabgp_tester_'

    def __init__(self, name, host_dir, conf, image='bgperf/exabgp'):
        super(ExaBGPTester, self).__init__(name, host_dir, conf, image)

    def configure_neighbors(self, target_conf):
        peers = list(self.conf.get('neighbors', {}).values())

        for p in peers:
            with open('{0}/{1}.conf'.format(self.host_dir, p['router-id']), 'w') as f:
                local_address = p['local-address']
                config = '''neighbor {0} {{
    peer-as {1};
    router-id {2};
    local-address {3};
    local-as {4};
    static {{
'''.format(target_conf['local-address'], target_conf['as'],
               p['router-id'], local_address, p['as'])
                f.write(config)
                for path in p['paths']:
                    f.write('      route {0} next-hop {1};\n'.format(path, local_address))
                f.write('''   }
}''')

    def get_startup_cmd(self):
        startup = ['''#!/bin/bash
ulimit -n 65536''']
        peers = list(self.conf.get('neighbors', {}).values())
        for p in peers:
            startup.append('''env exabgp.log.destination={0}/{1}.log \
exabgp.daemon.daemonize=true \
exabgp.daemon.user=root \
exabgp {0}/{1}.conf'''.format(self.guest_dir, p['router-id']))
        return '\n'.join(startup)


class BIRDTester(Tester, BIRD):

    CONTAINER_NAME_PREFIX = 'bgperf_bird_tester_'

    def __init__(self, name, host_dir, conf, image='bgperf/bird'):
        super(BIRDTester, self).__init__('bgperf_bird_' + name, host_dir, conf, image)

    def configure_neighbors(self, target_conf):
        peers = list(self.conf.get('neighbors', {}).values())

        for p in peers:
            with open('{0}/{1}.conf'.format(self.host_dir, p['router-id']), 'w') as f:
                local_address = p['local-address']
                config = '''log "{5}/{2}.log" all;
#debug protocols all;
router id {2};
protocol device {{}}
protocol bgp {{
source address {3};
connect delay time 1;
interface "eth0";
strict bind;
ipv4 {{ import none; export all; }};
local {3} as {4};
neighbor {0} as {1};
}}
protocol static {{ ipv4;
'''.format(target_conf['local-address'], target_conf['as'],
               p['router-id'], local_address, p['as'], self.guest_dir)
                f.write(config)
                for path in p['paths']:
                    f.write('      route {0} via {1};\n'.format(path, local_address))
                f.write('}')

    def get_startup_cmd(self):
        startup = [f'''#!/bin/bash
ulimit -n 65536
#sleep 2
#(ip link; ip addr) > {self.guest_dir}/ip-a.log
''']
        peers = list(self.conf.get('neighbors', {}).values())
        for p in peers:
            startup.append('''bird -c {0}/{1}.conf -s {0}/{1}.ctl >>{0}/{1}.log 2>&1\n'''.format(self.guest_dir, p['router-id']))
        return '\n'.join(startup)

