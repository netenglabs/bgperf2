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
import os
import re

class FRRouting(Container):
    '''Shared base for FRR containers.

    This no longer builds an image of its own. It used to wrap the prebuilt
    frrouting/frr:v7.5.1 container as the `frr` target; that target is gone and
    frr_c (FRR built from a git checkout, see frr_compiled.py) replaces it. The
    class survives because FRRoutingTarget below holds all the FRR config
    generation and CLI parsing, which FRRoutingCompiledTarget inherits.
    '''
    CONTAINER_NAME = None
    GUEST_DIR = '/root/config'

    def __init__(self, host_dir, conf, image='bgperf/frr_c'):
        super(FRRouting, self).__init__(self.CONTAINER_NAME, image, host_dir, self.GUEST_DIR, conf)


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
        with open(REPO_ROOT / 'filters' / 'frr.conf') as file:
            return file.read()

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
        # The '|' and 'head -1' are argv words handed to vtysh, not a shell
        # pipe -- there is no shell here -- so the first line still has to be
        # taken below.
        return ['vtysh', '-c', 'show version', '|', 'head -1']

    def exec_version_cmd(self):
        ret = (super().exec_version_cmd() or '').strip()
        # Match the banner instead of trusting the first line. vtysh talks to
        # bgpd over a socket, so before bgpd answers this command succeeds and
        # prints 'Exiting: failed to connect to any daemons.' -- which the old
        # split('\n')[0] recorded verbatim as the FRR version. That is how the
        # word 'exec' became a BIRD version in the published baseline.
        m = re.search(r'^(FRRouting \S+)', ret, re.MULTILINE)
        if not m:
            raise VersionUnavailable(
                'unexpected output from `vtysh -c "show version"`: {0!r}'.format(ret))
        return m.group(1)
    
    def get_neighbors_state(self):
        neighbors_accepted = {}
        neighbors_received = {}
        neighbor_received_output = self.local("vtysh -c 'sh ip bgp summary json'")
        if not neighbor_received_output:
            # bgpd is not answering yet; polling starts before it is up
            return neighbors_received, neighbors_accepted

        try:
            summary = json.loads(neighbor_received_output.decode('utf-8'))
        except json.JSONDecodeError:
            # vtysh emits plain-text errors when bgpd is still starting
            return neighbors_received, neighbors_accepted

        peers = summary.get('ipv4Unicast', {}).get('peers', {})
        for n in peers:
            neighbors_accepted[n] = peers[n]['pfxRcd']
        return neighbors_received, neighbors_accepted

    # A bytes pattern, matched against the raw log without decoding it first.
    # No leading .* -- this is used with finditer, which scans.
    EOR_RE = re.compile(rb"rcvd End-of-RIB for IPv4 Unicast from (\d+\.\d+\.\d+\.\d+)")

    # Most a single poll will pull out of bgpd.log. This has to stay well above
    # the rate the log grows, not just above a typical poll: if the reader
    # cannot keep up, it only catches up once the log stops growing, which
    # delays note_neighbors_checkpoint() and inflates the reported elapsed time
    # -- corrupting a headline number rather than merely costing CPU. A 10-peer
    # 1.05M-prefix run writes 1.04GB over a ~70s injection, about 15MB/s, and a
    # bigger or faster run scales past that. Scanning is done in place with
    # finditer over a memoryview, so a large cap costs the read itself and no
    # extra copies; 256MB against a machine with tens of GB is invisible in the
    # min_free column.
    EOR_READ_MAX = 256 * 1024 * 1024

    # ...but no single read is that big. The cap bounds throughput per poll;
    # this bounds the allocation, so catching up on a backlog costs several
    # small reads rather than one enormous one.
    EOR_READ_BLOCK = 4 * 1024 * 1024

    def _get_EOR_from_log(self, neighbors):
        # we are looking at the log files for End-Of-RIB
        # 2021/11/05 16:34:38 BGP: bgp_update_receive: rcvd End-of-RIB for IPv4 Unicast from 10.10.0.3 in vrf default
        #
        # bench() polls this once a second for the whole run, and End-of-RIB is
        # only visible at all because write_config() sets `log stdout debug`,
        # so bgpd.log grows with the route count -- a 10-peer 1.05M-prefix MRT
        # run puts it past 1GB. This used to readlines() the entire file and
        # rematch every line on every poll, which made the measuring instrument
        # the bottleneck: ~15s of CPU per poll, the per-second progress line
        # stopped printing, and the run never terminated even though the target
        # had converged minutes earlier.
        #
        # Read only what was appended since the last poll and remember which
        # neighbors already reported, so a poll costs the new bytes rather than
        # the whole log.
        if not hasattr(self, '_eor_seen'):
            self._eor_seen = set()
            self._eor_log_pos = 0
            self._eor_log_id = None

        path = f"{self.host_dir}/bgpd.log"
        try:
            st = os.stat(path)
        except OSError:
            # bgpd has not created it yet; polling starts before it is up
            return neighbors

        # A fresh run replaces the log. Identify it by inode rather than by
        # size: a replacement that had already grown past the saved offset
        # would keep the old one and be read from the wrong place, and since
        # FRR reaches its checkpoint only through End-of-RIB, silently missing
        # those lines means the run never converges and burns the full
        # STUCK_SAMPLES timeout before failing.
        log_id = (st.st_dev, st.st_ino)
        if log_id != self._eor_log_id:
            self._eor_seen = set()
            self._eor_log_pos = 0
            self._eor_log_id = log_id

        if st.st_size > self._eor_log_pos:
            # Read in bounded blocks rather than one big read(). RSS matters
            # here -- this process's own memory feeds the recorded min_free
            # column -- so the total a poll may consume is capped, but no
            # single allocation is anywhere near that cap.
            consumed = 0
            with open(path, 'rb') as f:
                while consumed < self.EOR_READ_MAX:
                    f.seek(self._eor_log_pos)
                    block = f.read(min(self.EOR_READ_BLOCK,
                                       self.EOR_READ_MAX - consumed))
                    if not block:
                        break
                    # bgpd may be mid-write, so stop at the last complete line
                    # and resume from the start of the partial one next time
                    end = block.rfind(b'\n')
                    if end < 0:
                        if len(block) < self.EOR_READ_BLOCK:
                            break       # trailing partial line; wait for more
                        # a whole block with no newline at all would otherwise
                        # be re-read forever
                        self._eor_log_pos += len(block)
                        consumed += len(block)
                        continue
                    # Scan in place. Slicing, decoding and splitting into lines
                    # would hold three more copies at once, which is the whole
                    # thing the cap exists to avoid; finditer over a memoryview
                    # allocates only the matches.
                    for m_eor in self.EOR_RE.finditer(memoryview(block)[:end]):
                        self._eor_seen.add(m_eor.group(1).decode('ascii'))
                    self._eor_log_pos += end + 1
                    consumed += end + 1

        for addr in self._eor_seen:
            if addr in neighbors:
                neighbors[addr] = True

        return neighbors

    def get_neighbor_received_routes(self):
        # FRR doesn't have a counter to look at to see if all the prefixes have been sent
        # instead we have to look at the log file and see if End-of-RIB has been sent for the neighbor
        neighbors_received_full, neighbors_checked = super(FRRoutingTarget, self).get_neighbor_received_routes()

        assert(all(value == False for value in neighbors_received_full.values()))
        neighbors_received_full = self._get_EOR_from_log(neighbors_received_full)

        assert(len(neighbors_received_full) == len(neighbors_checked))

        return neighbors_received_full, neighbors_checked

