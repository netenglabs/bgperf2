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

from json.decoder import JSONDecodeError
from base import Container
from gobgp import GoBGP
import os
from  settings import dckr
import yaml
import json
from threading import Thread
import time
import datetime

def rm_line():
    print('\x1b[1A\x1b[2K\x1b[1D\x1b[1A')

class Monitor(GoBGP):

    CONTAINER_NAME = 'bgperf_monitor'

    def run(self, conf, dckr_net_name=''):
        ctn = super(GoBGP, self).run(dckr_net_name)
        config = {}
        # From `self.conf` rather than `conf['monitor']`: `Container.__init__`
        # was already handed this role's own dict, and reading it here is what
        # lets `Receiver` inherit this method unchanged instead of copying a
        # gobgpd config writer that would then drift from the monitor's.
        config['global'] = {
            'config': {
                'as': self.conf['as'],
                'router-id': self.conf['router-id'],
            },
        }
        config ['neighbors'] = [{'config': {'neighbor-address': conf['target']['local-address'],
                                            'peer-as': conf['target']['as']},
                                 'transport': {'config': {'local-address': self.conf['local-address']}},
                                 'timers': {'config': {'connect-retry': 10}}}]
        with open('{0}/{1}'.format(self.host_dir, 'gobgpd.conf'), 'w') as f:
            f.write(yaml.dump(config))
        self.config_name = 'gobgpd.conf'
        startup = '''#!/bin/bash
ulimit -n 65536
gobgpd -t yaml -f {1}/{2} -l {3} > {1}/gobgpd.log 2>&1
'''.format(self.conf['local-address'], self.guest_dir, self.config_name, 'info')
        filename = '{0}/start.sh'.format(self.host_dir)
        with open(filename, 'w') as f:
            f.write(startup)
        os.chmod(filename, 0o777)
        i = dckr.exec_create(container=self.name, cmd='{0}/start.sh'.format(self.guest_dir))
        dckr.exec_start(i['Id'], detach=True, socket=True)
        self.config = conf
        return ctn

    def local(self, cmd, stream=False):
        i = dckr.exec_create(container=self.name, cmd=cmd)
        return dckr.exec_start(i['Id'], stream=stream)

    def wait_established(self, neighbor, role='monitor'):
        n = 0
        while True:
            if n > 0:
                 rm_line()
            print(f"Waiting {n} seconds for {role}")

            neighbor_data = self.local('gobgp neighbor {0} -j'.format(neighbor)).decode('utf-8')

            try:
                neigh = json.loads(neighbor_data)
            except JSONDecodeError:
                neigh = {'state': {'session_state': 'failed'}}


            if ((neigh['state']['session_state'] == 'established') or
                (neigh['state']['session_state'] == 6)):

                return n
            time.sleep(1)

            n = n+1

    def stats(self, queue, interval=1):
        '''Poll the monitor's accepted count into the run's stats queue.

        `interval` is the cadence asked for between two `gobgp neighbor -j`
        execs, and only the floor of the resolution achieved: a poll reads
        before it waits. It is a parameter rather than a literal because the
        controller publishes it as the floor of every monitor-owned interval's
        resolution -- a hardcoded sleep here and a constant there would drift
        apart silently, and the resolution is what says whether an interval
        was resolved at all.
        '''
        self.stop_monitoring = False
        def stats():
            cps = self.config['monitor']['check-points'] if 'check-points' in self.config['monitor'] else []
            while True:
                if self.stop_monitoring:
                    return
                # Stamped before the exec, not after, for the reason the
                # tester poll loop gives: `gobgp neighbor -j` is a docker
                # exec, and dating the sample to when the read *finished*
                # would push every monitor event later by a whole read. That
                # end of `post_injection_tail_s` would then be late while the
                # generator's end is early, biasing the one interval that
                # spans both instruments -- and the sign of that interval is
                # the finding. Before the read is a lower bound on when the
                # count was true.
                sampled_at = time.monotonic()
                try:
                    info = json.loads(self.local('gobgp neighbor -j').decode('utf-8'))[0]
                except Exception as e:
                    print(f"Monitoring reading exception {self.monitor_for}: {e} ")
                    continue

                info['who'] = self.name
                state = info['afi_safis'][0]['state']
                if 'accepted'in state and len(cps) > 0 and int(cps[0]) <= int(state['accepted']):
                    #cps.pop(0)
                    info['checked'] = True
                else:
                    info['checked'] = False
                # Keep the wall timestamp for compatibility/debug correlation,
                # but durations are calculated from this monotonic observation
                # time at the queue boundary.
                info['time'] = datetime.datetime.now()
                info['monotonic_s'] = sampled_at
                queue.put(info)
                time.sleep(interval)

        t = Thread(target=stats)
        t.daemon = True
        t.start()


class Receiver(Monitor):
    '''A session the target exports its table to, and nothing else.

    Export fan-out is the third kind of session in a run. A tester is a route
    source and the monitor is the measurement instrument; a receiver is neither
    -- it announces nothing, so what it costs the target is one more copy of
    the RIB-out and one more set of updates to encode and send. Without it,
    "how much does a table cost to export" and "how much does it cost to
    receive" are one number in every result this tool has produced, and
    decoupled exports are one of the three responsibilities BIRD 3's worker
    threads exist to parallelise.

    It is a `Monitor` because the two are the same container doing the same
    thing -- a GoBGP peered with the target and importing everything -- and the
    only difference is that nothing reads this one. Subclassing rather than
    copying keeps the gobgpd config, the startup script and the establishment
    wait single-sourced; `stats()` is refused rather than inherited, because a
    receiver polled as though it were the instrument would publish a second,
    unlabelled `recved` series into the same queue the monitor feeds.

    It *is* read -- `accepted_prefixes()` is how the export side of a run is
    measured at all -- but into a recorder and an artifact section of its own,
    never into the stats queue the row is built from.

    Receivers are deliberately absent from `conf['testers']`, so
    `get_test_counts()` never waits on them for a table they will never send
    and the monitor's check-point does not move with their number.
    '''

    CONTAINER_NAME = None
    CONTAINER_NAME_PREFIX = 'bgperf_receiver'

    def __init__(self, index, host_dir, conf, image='bgperf/gobgp'):
        self.index = index
        Container.__init__(self, '{0}{1}'.format(self.CONTAINER_NAME_PREFIX, index),
                           image, host_dir, self.GUEST_DIR, conf)

    def stats(self, queue, interval=1):
        raise NotImplementedError(
            'a receiver is not an instrument: it announces nothing and is '
            'never polled as one. Read the monitor. What the target exported '
            'to this session is read with accepted_prefixes().')

    def accepted_prefixes(self):
        """How many prefixes the target has exported to this session so far.

        This is not `stats()` reached by another name, and the difference is
        the whole reason the fan-out can be measured at all. `stats()` feeds
        the run's stats queue, whose monitor samples are what `elapsed (s)`,
        `received` and every published timing are read from; a receiver polled
        into that queue would be a second, unlabelled `recved` series in it.
        This returns a count to a caller that keeps it in its own recorder and
        its own artifact section, where it can never be mistaken for the
        instrument's.

        An unreadable answer raises. The caller records that poll as unread
        rather than as a receiver holding nothing -- a session we failed to ask
        and a session that has been given no routes must not produce the same
        measurement.
        """
        # One `gobgp neighbor -j` per receiver per round: a receiver is its own
        # container, so unlike a BIRD tester's peers this cannot be collapsed
        # into a single exec. That cost is what `export_poll_can_stop()` exists
        # to bound.
        neighbors = json.loads(self.local('gobgp neighbor -j').decode('utf-8'))
        state = neighbors[0]['afi_safis'][0]['state']
        # Absent means zero, exactly as the monitor's own loop reads it: gobgp
        # omits the field until the session has accepted something.
        return int(state['accepted']) if 'accepted' in state else 0
