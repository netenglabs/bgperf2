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
import sys

from docker.errors import APIError

from base import CliDecodeError, Container, decode_cli_output


class SessionUnavailable(RuntimeError):
    '''A session this run requires cannot be asked whether it is established.'''

from gobgp import GoBGP
from sink import Sink, SinkLogError, SinkLogReader
import os
from  settings import dckr
import yaml
import json
from threading import Thread
import time
import datetime

def rm_line():
    print('\x1b[1A\x1b[2K\x1b[1D\x1b[1A')

class MonitorReadError(Exception):
    """`gobgp neighbor -j` on the monitor did not answer with a neighbour.

    Its own errors come back JSON-encoded, so a failed read parses into a `str`
    and indexing it yields a character rather than raising. Naming it keeps the
    diagnosis on the read instead of on whatever indexed the result next.
    """


class Instrument(object):
    '''The monitor role, whichever daemon fills it.

    A mixin, first in each monitor class's MRO, holding what the role is
    rather than what the daemon is: the container name, the poll loop that
    feeds the run's stats queue, and the failure counters that loop keeps.
    Each monitor supplies `read_sample()` and `wait_established()`.

    It is deliberately not a `GoBGP`. The sink's monitor takes its version
    command from `Sink`; through `Monitor` it would have reached
    `GoBGP.exec_version_cmd()` first and parsed its own banner as gobgpd's,
    which is the MRO bug that made rustybgp record UNKNOWN on every run.
    '''
    # The monitor is the instrument, so its read failing is a fact about the
    # measurement rather than about a target. Counted and reported on the same
    # rule as `Container.neighbor_stats()`.
    MONITOR_SAMPLE_REPORT_EVERY = 60
    monitor_sample_failures = 0
    monitor_sample_consecutive_failures = 0
    monitor_sample_last_error = None

    CONTAINER_NAME = 'bgperf_monitor'

    def read_sample(self, sampled_at):
        '''One sample, shaped as `gobgp neighbor -j`'s first neighbour.

        `sampled_at` is the `time.monotonic()` the loop stamped before the
        read. Anything that is not a count raises, and the loop records it as
        a failed read of the instrument, never as a monitor holding nothing.
        '''
        raise NotImplementedError()

    def stats(self, queue, interval=1):
        '''Poll the monitor's accepted count into the run's stats queue.

        `interval` is the cadence asked for between two reads, and only the
        floor of the resolution achieved: a poll reads
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
                # Everything that touches the payload is inside the guard, and
                # the guard is not the one that used to be here.
                #
                # `gobgp neighbor -j` answers with its *error* JSON-encoded, so
                # a failed read parses cleanly into a `str` -- and
                # `json.loads('"rpc error: ..."')[0]` is `'r'`, which does not
                # raise. The old `try` therefore caught nothing, and
                # `info['who'] = ...` on the very next line, outside it, killed
                # this thread for the rest of the run. That is the same payload
                # that killed the target's sampler and cost the campaign's
                # `rustybgp default` cell 2194s -- but here it lands on the
                # instrument every published timing is read from: `recved`
                # freezes, and `ConvergenceTracker` fails the run as stuck with
                # no target-side guard able to save it.
                try:
                    info = self.read_sample(sampled_at)
                    info['who'] = self.name
                    state = info['afi_safis'][0]['state']
                    if 'accepted'in state and len(cps) > 0 and int(cps[0]) <= int(state['accepted']):
                        #cps.pop(0)
                        info['checked'] = True
                    else:
                        info['checked'] = False
                    # Keep the wall timestamp for compatibility/debug
                    # correlation, but durations are calculated from this
                    # monotonic observation time at the queue boundary.
                    info['time'] = datetime.datetime.now()
                    info['monotonic_s'] = sampled_at
                    queue.put(info)
                    self.monitor_sample_consecutive_failures = 0
                except Exception as e:
                    self.monitor_sample_failures += 1
                    self.monitor_sample_consecutive_failures += 1
                    self.monitor_sample_last_error = '{0}: {1}'.format(
                        type(e).__name__, e)
                    if (self.monitor_sample_consecutive_failures == 1
                            or self.monitor_sample_consecutive_failures
                            % self.MONITOR_SAMPLE_REPORT_EVERY == 0):
                        print('WARNING: monitor read for {0} failed '
                              '({1} consecutive, {2} total): {3}'.format(
                                  self.monitor_for,
                                  self.monitor_sample_consecutive_failures,
                                  self.monitor_sample_failures,
                                  self.monitor_sample_last_error),
                              file=sys.stderr, flush=True)
                # Outside the guard, so a failing read waits like a succeeding
                # one. The old `continue` skipped it, and a persistent failure
                # then spun `docker exec` as fast as the host allowed -- inside
                # the container being measured, inflating `max cpu %` and
                # `min idle%` on the run whose timings are published, and
                # invisible to `max foreign cpu %` because `gobgp` is in
                # `contention.BGPERF_PROCESSES`.
                time.sleep(interval)

        t = Thread(target=stats)
        t.daemon = True
        t.start()


class Monitor(Instrument, GoBGP):
    '''The GoBGP monitor: `gobgp neighbor -j`, read by `docker exec`.'''

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

            cmd = 'gobgp neighbor {0} -j'.format(neighbor)
            # The missing arm beside the parse one below. That one is for a
            # bad *answer*, which is "not established yet" and retried; this is
            # for a failed *exec*, where there is nothing to wait for. Killing
            # bgperf_receiver2 during a 4x250000 establishment wait ended the
            # run in a docker-py traceback: dying is right, the shape was not.
            #
            # It names no cause, because `APIError` is every non-2xx the daemon
            # can answer with and not just "no such container" -- a host out of
            # pids answers `500 OCI runtime exec failed: resource temporarily
            # unavailable` for a container that is running perfectly well.
            try:
                raw = self.local(cmd)
            except APIError as exc:
                raise SessionUnavailable(
                    '{0} ({1}) could not be asked for its session state: '
                    'docker refused the exec with {2}. The {1} session cannot '
                    'be shown to be established, so the run cannot proceed as '
                    'configured.'.format(self.name, role, exc)) from exc

            # The third read of `gobgp neighbor -j` in this run, and it needs
            # the same guard as the other two for a reason the JSONDecodeError
            # arm does not cover: gobgp answers with its *error* JSON-encoded,
            # so `json.loads('"rpc error: code = Unavailable"')` succeeds and
            # returns a `str`. `neigh['state']` then raises TypeError, and this
            # one is not in a sampler thread -- it propagates out of `bench()`
            # before any teardown and kills the whole batch cell.
            #
            # This is also the read most likely to meet that payload: it runs
            # about a second after the container starts, which is exactly when
            # the RPC endpoint is least likely to be up. A session that is not
            # answering yet is what this loop is for, so a bad payload is
            # "not established yet", not an error.
            #
            # Which is why the decode sits inside this arm rather than ahead of
            # it: a partial or binary answer at that same moment is the same
            # event as an unparseable one, and decoding outside would have ended
            # the batch cell on the payload this loop exists to wait out.
            try:
                neigh = json.loads(decode_cli_output(
                    raw, container=self.name, cmd=cmd))
            except (JSONDecodeError, CliDecodeError):
                neigh = None
            if not isinstance(neigh, dict) or not isinstance(
                    neigh.get('state'), dict):
                neigh = {'state': {'session_state': 'failed'}}

            if ((neigh['state']['session_state'] == 'established') or
                (neigh['state']['session_state'] == 6)):

                return n
            time.sleep(1)

            n = n+1


    def read_sample(self, sampled_at):
        payload = json.loads(decode_cli_output(
            self.local('gobgp neighbor -j'),
            container=self.name, cmd='gobgp neighbor -j'))
        if not isinstance(payload, list) or not payload:
            raise MonitorReadError(
                '`gobgp neighbor -j` returned {0}, not a list of '
                'neighbours: {1!r}'.format(
                    type(payload).__name__, str(payload)[:200]))
        info = payload[0]
        if not isinstance(info, dict):
            raise MonitorReadError(
                '`gobgp neighbor -j` returned a {0} where a '
                'neighbour was expected: {1!r}'.format(
                    type(info).__name__, str(info)[:200]))
        return info


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
        neighbors = json.loads(decode_cli_output(
            self.local('gobgp neighbor -j'),
            container=self.name, cmd='gobgp neighbor -j'))
        state = neighbors[0]['afi_safis'][0]['state']
        # Absent means zero, exactly as the monitor's own loop reads it: gobgp
        # omits the field until the session has accepted something.
        return int(state['accepted']) if 'accepted' in state else 0


class SinkMonitor(Instrument, Sink):
    '''The purpose-built monitor (measurement plan Phase 7a).

    It holds the one session to the target and appends its count to
    `sink.log` in its bind-mounted directory; `read_sample()` reads that file
    on the host with `SinkLogReader`, so no read costs a `docker exec`. The
    sample is the one `Monitor.read_sample()` returns, and it goes through the
    same poll loop at the same cadence, so everything downstream of the queue
    runs unchanged. Using the sink's own timestamps is 7b, not this.
    '''

    LOG_NAME = 'sink.log'
    STDERR_NAME = 'sink.stderr'
    # How long the establishment wait gives a sink to write its first line
    # before calling it dead. The sink writes its format line before it does
    # anything else, so this bounds a sink that never started -- a bad flag,
    # a missing binary -- not a slow session.
    START_GRACE_S = 30

    def __init__(self, host_dir, conf, image='bgperf/sink'):
        super(SinkMonitor, self).__init__(host_dir, conf, image=image)
        self.reader = SinkLogReader(os.path.join(self.host_dir, self.LOG_NAME))

    def get_startup_cmd(self):
        target = self.config['target']
        return '''#!/bin/bash
ulimit -n 65536
exec {binary} -local-as {local_as} -peer-as {peer_as} -router-id {router_id} \\
    -local-address {local_address} -peer-address {peer_address} \\
    -connect-retry 10s -log {guest}/{log} > {guest}/{stderr} 2>&1
'''.format(binary=self.DAEMON_BINARY, local_as=self.conf['as'],
           peer_as=target['as'], router_id=self.conf['router-id'],
           local_address=self.conf['local-address'],
           peer_address=target['local-address'], guest=self.guest_dir,
           log=self.LOG_NAME, stderr=self.STDERR_NAME)

    def run(self, conf, dckr_net_name=''):
        # `Container.run()` asks the container for `ip addr` to find its
        # interface; the sink's image has no `ip`, the exec answers with an
        # error text rather than raising, and the default it then takes only
        # matters to a container with a second address, which a monitor never
        # has.
        ctn = Container.run(self, dckr_net_name)
        # Removed before the sink starts, never after. The log is opened for
        # append, and under `-r/--repeat` this directory survives from the
        # previous run: its lines would read as an earlier process of this
        # one, and the gap between the two runs as the instrument stalling.
        for name in (self.LOG_NAME, self.STDERR_NAME):
            try:
                os.remove(os.path.join(self.host_dir, name))
            except FileNotFoundError:
                pass
        self.reader = SinkLogReader(os.path.join(self.host_dir, self.LOG_NAME))
        self.config = conf
        self.exec_startup_cmd(detach=True)
        return ctn

    def stderr_tail(self, limit=400):
        try:
            with open(os.path.join(self.host_dir, self.STDERR_NAME), 'rb') as f:
                text = f.read().decode('utf-8', 'replace').strip()
        except OSError as e:
            return '(no stderr: {0})'.format(e)
        return text[-limit:] or '(stderr empty)'

    def wait_established(self, neighbor, role='monitor'):
        '''Wait for the log to say the session is up; return the seconds waited.

        `neighbor` is accepted for `Monitor`'s signature and not needed: the
        sink is configured with exactly one peer, the target.

        A sink that has not written yet is waited for, up to `START_GRACE_S`.
        Every other refusal ends the wait, unlike GoBGP's bad payload, which is
        retried: a malformed log, an unknown format or a sink that stopped
        writing will not become a session by waiting, and waiting for one
        forever is how a run hangs in "Waiting N seconds for monitor".
        '''
        n = 0
        while True:
            if n > 0:
                rm_line()
            print(f"Waiting {n} seconds for {role}")
            try:
                sample = self.reader.sample()
            except FileNotFoundError:
                sample = None
            except SinkLogError as exc:
                log = self.reader.log
                if log.processes or log.malformed_lines:
                    raise SessionUnavailable(
                        '{0} ({1}): its log cannot be read as a session: {2}. '
                        'stderr: {3}'.format(self.name, role, exc,
                                             self.stderr_tail())) from exc
                sample = None
            except OSError as exc:
                raise SessionUnavailable(
                    '{0} ({1}): its log could not be read: {2}'.format(
                        self.name, role, exc)) from exc
            if sample is None and n >= self.START_GRACE_S:
                raise SessionUnavailable(
                    '{0} ({1}) wrote no log line in {2}s, so it never started. '
                    'stderr: {3}'.format(self.name, role, n, self.stderr_tail()))
            if sample is not None and \
                    sample['state']['session_state'] == 'established':
                return n
            time.sleep(1)
            n = n + 1

    def read_sample(self, sampled_at):
        # The staleness check is made at the loop's own stamp, so the sample
        # and the clock it is judged by are the same instant.
        return self.reader.sample(now_ns=int(sampled_at * 1e9))


class SinkReceiver(SinkMonitor):
    '''An export receiver that is a sink (measurement plan 7a).

    `Receiver`'s contract, on the sink: a session the target exports its
    table to, which announces nothing and is never polled into the stats
    queue -- `stats()` is refused for the reason `Receiver.stats()` is. It is
    read with `accepted_prefixes()`, which reads its log on the host, so a
    round of the export poll no longer costs a `docker exec` per receiver.

    Every receiver was a full GoBGP holding its own copy of the table, which
    is how a `--receivers` run could trip `low_free_memory` on memory it
    consumed by design; a sink holds a prefix set.
    '''

    CONTAINER_NAME = None
    CONTAINER_NAME_PREFIX = Receiver.CONTAINER_NAME_PREFIX

    def __init__(self, index, host_dir, conf, image='bgperf/sink'):
        self.index = index
        Container.__init__(self, '{0}{1}'.format(self.CONTAINER_NAME_PREFIX, index),
                           image, host_dir, self.GUEST_DIR, conf)
        self.reader = SinkLogReader(os.path.join(self.host_dir, self.LOG_NAME))

    def stats(self, queue, interval=1):
        return Receiver.stats(self, queue, interval)

    def accepted_prefixes(self):
        """How many prefixes the target has exported to this session so far.

        Raises where the log cannot be read as a count -- not written, stale,
        malformed -- and the export poll records that round as unread, for
        the reason `Receiver.accepted_prefixes()` gives: a session we failed
        to ask and a session given no routes are different measurements.
        """
        return self.reader.sample()['afi_safis'][0]['state']['accepted']
