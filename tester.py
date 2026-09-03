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
from bird import BIRD, SESSION_MARKER, split_session_output, tester_offering
from measurements import TesterOffering
from  settings import dckr
from subprocess import check_output, Popen, PIPE
import glob
import os


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
    REPORTS_OFFERING = True

    def __init__(self, name, host_dir, conf, image='bgperf/bird'):
        super(BIRDTester, self).__init__('bgperf_bird_' + name, host_dir, conf, image)

    def configure_neighbors(self, target_conf):
        peers = list(self.conf.get('neighbors', {}).values())

        for p in peers:
            with open('{0}/{1}.conf'.format(self.host_dir, p['router-id']), 'w') as f:
                local_address = p['local-address']
                # Log classes, not `all`. `all` includes trace, and a BIRD
                # tester traces every route event: 50 peers x 100k prefixes
                # wrote 700MB per peer, 31GB in total. /tmp is tmpfs on a
                # typical box, so that is 31GB of *RAM* -- it dragged the
                # recorded min_free from 56GB to 28.5GB on a run whose target
                # daemon used 0.56GB, making that column a measure of tester
                # logging rather than of the daemon. find_errors() only needs
                # <RMT>, and nothing reads the logs during a run.
                config = '''log "{5}/{2}.log" {{ info, remote, warning, error, auth, bug, fatal }};
#debug protocols all;
debug protocols {{states}};
router id {2};
protocol device {{}}
protocol bgp {{
    #hold time 5;
    source address {3};
    connect delay time 1;
    interface "{6}";
    strict bind;
    ipv4 {{ import none; export all; }};
    local {3} as {4};
neighbor {0} as {1};
}}
protocol static {{ ipv4;
'''.format(target_conf['local-address'], target_conf['as'],
               p['router-id'], local_address, p['as'], self.guest_dir, self.dev)
                f.write(config)
                for path in p['paths']:
                    f.write('      route {0} via {1};\n'.format(path, local_address))
                f.write('}')

    def _peers(self):
        return list(self.conf.get('neighbors', {}).values())

    def get_offerings_cmd(self):
        '''One shell command that asks every peer's `bird` what it has sent.

        A BIRD tester runs one daemon per neighbour on its own control socket,
        so a bare `birdc` in this container reaches no daemon at all -- each
        socket has to be named. They are read in a single exec rather than one
        per peer so the poll cost does not grow with the peer count.
        '''
        parts = []
        for p in self._peers():
            key = p['router-id']
            parts.append("echo '{0}{1}'".format(SESSION_MARKER, key))
            # `|| true` so one dead socket does not abort the rest of the loop
            # and cost us the peers that would have answered.
            parts.append(
                "birdc -s {0}/{1}.ctl 'show protocols all' 2>&1 || true".format(
                    self.guest_dir, key))
        return ['sh', '-c', '; '.join(parts)]

    def get_offerings(self):
        '''What each configured peer says it has offered, from its own CLI.

        Keyed by the peers in the run configuration, not by the sockets that
        answered: a peer whose daemon is not up yet, or whose read failed,
        reports offered=None and stays in the poll. Dropping it instead would
        let the peers that did answer satisfy completion on their own.
        '''
        expected = {p['router-id']: len(p.get('paths', ()))
                    for p in self._peers()}
        # A failed exec is raised, not swallowed. offering_stats() catches it
        # and records `tester_offering_error`, which is the only way the
        # artifact can say the generator could not be *asked*. Turning it into
        # an empty capture here reported every peer as not established, so a
        # run whose polls all failed produced the same artifact as a run whose
        # generator never came up -- the ambiguity this section exists to
        # remove -- and made that error path unreachable for the only generator
        # that uses it.
        output = self.local(self.get_offerings_cmd()).decode('utf-8', 'replace')
        sessions = split_session_output(output)

        offerings = {}
        for key, count in expected.items():
            text = sessions.get(key)
            if text is None:
                offerings[key] = TesterOffering(established=False, expected=count)
                continue
            # `expected` is the configured table size. tester_offering()'s own
            # `configured` is the generator's report of what it loaded -- a
            # cross-check, never the yardstick: taking it would make a
            # generator that loaded half its config look complete.
            observed = tester_offering(text)
            offerings[key] = TesterOffering(
                established=observed['established'],
                expected=count,
                offered=observed['offered'],
                configured=observed['configured'],
                tx_pending_bytes=observed['tx_pending_bytes'],
                pending_prefixes=observed['pending_prefixes'])
        return offerings

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

    @staticmethod
    def find_errors(log_dirs=()):
        '''Count real protocol errors across the tester logs.

        The target re-advertises everything it learns, including back to the
        testers that sent it. Testers run `import none`, so they reject all of
        it and log "Invalid route ... withdrawn" for each -- normal operation,
        not an error, and it dwarfs anything real (10 peers x 900 reflected
        routes = 9000). Excluded like NEXT_HOP already was.

        Takes the tester host directories rather than assuming /tmp/bgperf2, so
        it still works with -b/--bench-name and -d/--dir.
        '''
        errors = 0
        for log_dir in log_dirs:
            for log in glob.glob(os.path.join(log_dir, '*.log')):
                # An unreadable log is skipped rather than raised: this runs
                # once the run has converged but before its stats row is
                # written, so letting an OSError out discards the whole run
                # over a log file.
                try:
                    with open(log, errors='replace') as f:
                        for line in f:
                            if '<RMT>' not in line:
                                continue
                            if 'NEXT_HOP' in line or 'Invalid route' in line:
                                continue
                            errors += 1
                except OSError:
                    continue
        return errors