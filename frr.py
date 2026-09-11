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

def neighbors_state(summary):
    '''The two per-neighbour dicts, from one parsed `sh ip bgp summary json`.

    Pure, so the parsing is covered by a suite that needs no Docker; the read
    itself is `FRRoutingTarget.summary_json()`. `neighbors_received` is always
    empty here -- FRR has no received-prefix counter, and whether a neighbour
    has finished sending is decided from End-of-RIB in `bgpd.log` instead.
    '''
    neighbors_accepted = {}
    neighbors_received = {}
    if not summary:
        return neighbors_received, neighbors_accepted
    peers = (summary.get('ipv4Unicast') or {}).get('peers') or {}
    for name, peer in peers.items():
        # Indexed, not `.get()`: FRR keeps `pfxRcd` in the document for a peer
        # that is not Established and reports it as 0 (measured on 8.5), so a
        # missing key means the field has been renamed or dropped, not that a
        # session is down. Skipping it would leave `neighbors_accepted` empty
        # on every poll with nothing saying so -- the run still converges
        # through End-of-RIB -- which is exactly how BIRD 3's `RX limit`
        # regression stayed hidden. Raising reaches `neighbor_stats()`'s guard
        # and is published as a sampler read failure.
        neighbors_accepted[name] = peer['pfxRcd']
    return neighbors_received, neighbors_accepted


def table_witness(summary, monitor_address=None, expected_peerings=None):
    '''What FRR itself says it has sent the monitor.

    Deliberately narrower than `bird.table_witness()`, which also publishes
    `best_paths` and `imported_paths`. Those two are what
    `ConvergenceTracker`'s witness rule reads, and this function withholds them
    on purpose rather than for want of a number: FRR does report a table size
    (`ribCount` in this summary, `Total Prefixes` in `show bgp ipv4 unicast
    statistics`), but the two disagree -- 1,081,000 against 1,080,985 on one
    measured run -- and neither has been established to mean "prefixes holding
    a selected best path", which is what BIRD's `preferred` sum means and what
    the rule compares against its own peak. A witness that is subtly wrong is
    worse than none: it would excuse monitor declines it has no standing to
    excuse. Supplying `None` is the documented way to attest to nothing
    (`convergence.py` returns "does not attest" for it), so adding this changes
    nothing about how an FRR run converges.

    `imported_paths` is published, and means here what it means for BIRD: the
    paths the target accepted from its peers, summed. `pfxRcd` is FRR's count
    of prefixes accepted from that peer -- post-policy, which is the useful
    sense -- so a target discarding most of what it is offered reports a small
    sum. That is the only size floor an MRT run has: the monitor's count and
    `exported_to_monitor` are the two ends of one link and agree whenever the
    link works, so on their own they cannot tell a whole table from a tenth of
    one.

    `exported_to_monitor` needs no such interpretation. `pfxSnt` on the
    monitor's own session is the count of prefixes FRR believes it has sent
    that peer -- the target's end of the very session the monitor reads -- and
    is the number that says whether the two ends of one session agree. It was
    measured against a real run: FRR reported 961,201 sent while the monitor
    reported 961,201 accepted.

    Withheld unless that session is Established and carries an integer count,
    on `bird.table_witness()`'s rule: a partial read looks exactly like a table
    that shrank, which is the one thing a witness exists to rule on.
    '''
    peers = ((summary or {}).get('ipv4Unicast') or {}).get('peers') or {}
    exported_to_monitor = None
    imported_total = 0
    measured = 0
    for address, peer in peers.items():
        if not isinstance(peer, dict) or peer.get('state') != 'Established':
            continue
        received = peer.get('pfxRcd')
        if isinstance(received, int) and not isinstance(received, bool):
            measured += 1
            imported_total += received
        if monitor_address and address == monitor_address:
            sent = peer.get('pfxSnt')
            if isinstance(sent, int) and not isinstance(sent, bool):
                exported_to_monitor = sent
    complete = expected_peerings is not None and measured == expected_peerings
    return {
        # NOT comparable with BIRD's `peerings`, and the difference is visible
        # in the artifact. BIRD counts the protocols it is *showing*, so on a
        # dynamic-neighbour target that number climbs as sessions connect and a
        # reader watches it approach `peerings_expected`. FRR configures static
        # neighbours, so every configured peer is in this document from the
        # first poll whatever its state, and `peerings` equals
        # `peerings_expected` immediately. Only `peerings_measured` moves --
        # it counts the Established sessions that reported a count -- so that
        # is the one to read when `imported_paths` is withheld and the question
        # is which sessions were not reporting.
        'peerings': len(peers),
        'peerings_expected': expected_peerings,
        'peerings_measured': measured,
        'best_paths': None,
        'imported_paths': imported_total if complete else None,
        'exported_to_monitor': exported_to_monitor,
    }


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

        neighbors = self.scenario_neighbors(sort=False)
        
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
    
    # FRR answers with `exported_to_monitor` and withholds the two sums; see
    # table_witness() above. The flag says "this daemon has a gauge", which is
    # what lets `target_table_unmeasured()` tell a poll that produced no sample
    # from a daemon that was never going to produce one -- without it an FRR
    # run whose target poll thread died would publish the artifact of a daemon
    # with no witness at all, and the MRT correctness check would read that as
    # "nothing to cross-check against" and qualify the row.
    REPORTS_TABLE_WITNESS = True

    def summary_json(self):
        '''One `sh ip bgp summary json` read, parsed, or None.

        None covers both ways the read can fail to produce a summary, which are
        the same two the callers always had to tolerate: bgpd is not answering
        yet, because polling starts before it is up, and vtysh emits plain-text
        errors while bgpd is still starting. Split out from
        `get_neighbors_state()` so one read can serve both the neighbour
        counters and the export witness -- see `sample_target_state()`.
        '''
        output = self.local("vtysh -c 'sh ip bgp summary json'")
        if not output:
            return None
        try:
            return json.loads(output.decode('utf-8'))
        except json.JSONDecodeError:
            return None

    def get_neighbors_state(self):
        return neighbors_state(self.summary_json())

    def sample_target_state(self):
        '''The neighbour verdicts and the export witness, off one CLI read.

        FRR is asked for `sh ip bgp summary json` every poll already, and the
        witness is in the same document, so taking the base implementation
        would exec twice a second into the container being measured -- and
        would date the two halves to two different instants, on a number whose
        only job is to be compared against another number. BIRD's override
        exists for the same two reasons.

        The End-of-RIB scan stays where it is: it reads `bgpd.log`, not the
        summary, so it is a second source either way.
        '''
        summary = self.summary_json()
        received, accepted = neighbors_state(summary)
        full, checked = self.classify_neighbor_counts(received, accepted)
        assert(all(value == False for value in full.values()))
        full = self._get_EOR_from_log(full)
        assert(len(full) == len(checked))
        return full, checked, table_witness(
            summary, self.monitor_neighbor_address(),
            # Every session the scenario configured, BIRD's rule: a sum that
            # silently loses a peering looks exactly like a table that shrank.
            expected_peerings=len(self.scenario_neighbors(sort=False)))

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
        # FRR has no received-prefix counter, so whether a neighbour has
        # finished sending is decided from End-of-RIB in bgpd.log. That work
        # lives in sample_target_state(), which reads the summary once and
        # serves both halves; this stays as the base class's named entry point
        # and delegates, rather than keeping a second copy of the sequence for
        # a later fix to land in.
        full, checked, _witness = self.sample_target_state()
        return full, checked

