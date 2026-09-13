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

from base import Tester, scan_log_lines
from exabgp import ExaBGP
from bird import (BIRD, CHURN_PROTOCOL, SESSION_MARKER, churn_failures,
                  split_session_output, tester_offering)
from churn import split_churn_paths
from measurements import TesterOffering
from  settings import dckr
from subprocess import check_output, Popen, PIPE


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


def _is_bird_protocol_error(line):
    '''Whether one BIRD tester log line is a real protocol error.

    The target re-advertises everything it learns, including back to the
    testers that sent it. Testers run `import none`, so they reject all of it
    and log "Invalid route ... withdrawn" for each -- normal operation, not an
    error, and it dwarfs anything real (10 peers x 900 reflected routes =
    9000). Excluded like NEXT_HOP already was.
    '''
    if '<RMT>' not in line:
        return False
    return 'NEXT_HOP' not in line and 'Invalid route' not in line


class BIRDTester(Tester, BIRD):

    CONTAINER_NAME_PREFIX = 'bgperf_bird_tester_'
    REPORTS_OFFERING = True
    # The only generator that can churn: its table is prefixes bgperf2
    # generated, so a bounded block of them can be given a protocol of its own
    # and switched off and on again with birdc.
    SUPPORTS_CHURN = True

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
                # The churn block is the tail of this peer's own list, and it
                # goes into a protocol of its own so a burst can withdraw and
                # re-announce exactly it. At the default -- no churn -- the
                # split returns every path and nothing, so this writes the
                # single unnamed static protocol it always wrote and an
                # existing run's generator config is byte-identical.
                stable, churning = split_churn_paths(
                    p['paths'], p.get('churn-prefixes'))
                f.write(config)
                for path in stable:
                    f.write('      route {0} via {1};\n'.format(path, local_address))
                f.write('}')
                if churning:
                    f.write('\nprotocol static {0} {{ ipv4;\n'.format(
                        CHURN_PROTOCOL))
                    for path in churning:
                        f.write('      route {0} via {1};\n'.format(
                            path, local_address))
                    f.write('}')

    def _churn_peers(self):
        '''The peers this generator was given a churn block for.

        A peer with no block has no `churn` protocol, so asking birdc to
        disable one answers `syntax error` -- which `churn_failures()` reports,
        correctly, as a burst that was not issued. Skipping them here is what
        keeps that from happening on a run where churn was never asked for.
        '''
        return [p for p in self._peers() if p.get('churn-prefixes')]

    def churn_command(self, action):
        '''One shell command that switches every peer's churn block.

        One `docker exec` for the whole fleet, for the reason
        `get_offerings_cmd()` uses one: an exec is ~50ms, and at 50 peers a
        burst issued peer by peer would take seconds to reach the last of them
        -- so the fleet would withdraw in a staircase and the interval measured
        would be that staircase rather than the target's reaction to it.
        '''
        parts = []
        for p in self._churn_peers():
            key = p['router-id']
            parts.append("echo '{0}{1}'".format(SESSION_MARKER, key))
            # `|| true` so one dead socket does not abort the loop and cost the
            # peers that would have answered. The reply is what decides
            # success, not the exit status, which this discards.
            parts.append("birdc -s {0}/{1}.ctl '{2} {3}' 2>&1 || true".format(
                self.guest_dir, key, action, CHURN_PROTOCOL))
        return ['sh', '-c', '; '.join(parts)]

    def churn(self, action):
        '''Issue one churn command to every peer, and report who did not do it.

        A failed exec is raised rather than swallowed, like `get_offerings()`:
        a burst nobody performed has no symptom except the monitor's count not
        moving, which arrives as a stall minutes later and reads as a stuck
        target.
        '''
        peers = self._churn_peers()
        if not peers:
            return {}
        output = self.local(self.churn_command(action)).decode('utf-8', 'replace')
        return churn_failures(output, [p['router-id'] for p in peers], action)

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
    def find_errors(log_dirs=(), samples=None):
        '''Count real protocol errors across the tester logs, by
        `_is_bird_protocol_error()`.

        Takes the tester host directories rather than assuming a fixed path, so
        it still works with -b/--bench-name and -d/--dir.

        The scan is `scan_log_lines()`, which withholds a partial final line.
        That matters more here than anywhere else it is used: the exclusion
        in `_is_bird_protocol_error()` is a substring test against a message
        BIRD writes once per reflected route, so a truncated copy of the single
        commonest line in the log reads as a protocol error.
        '''
        return scan_log_lines(log_dirs, _is_bird_protocol_error, samples)
