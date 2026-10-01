#!/usr/bin/env python3
'''Drive one GoBGP speaker at the sink and at a GoBGP monitor, and compare.

Measurement plan 7a replaces the GoBGP monitor with a sink whose count must be
what GoBGP's `accepted` was. This is the hand-driven check every 7a change set
has run so far, kept so it is the same check each time. It starts, on a
scratch network:

- a GoBGP speaker (`bgperf/gobgp`), peered with both of the others;
- the sink, run as `monitor.SinkMonitor`, the class `bench --monitor sink` uses;
- a GoBGP monitor, run as `monitor.Monitor`, the class `bench` uses by default.

It then announces, withdraws and re-announces /24s on the speaker, and after
each step it waits until both monitors agree or the timeout passes. Both are
read through the classes' own `read_sample()`, the read `stats()` makes during
a run. It also reports how far the sink's monotonic clock is from this host's,
from the sink's own B line: 7a check 5, in its controller-side form.

This is a check of the instrument against the instrument, not of any target.
No benchmark runs, and nothing it prints is a published number.

Exits 0 when every step agreed, 1 when one did not, and 2 when it could not
run. The containers and the network are removed afterwards unless `--keep`.
'''
import argparse
import json
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Prefixes are 10.<100 + i // 256>.<i % 256>.0/24: never inside the scratch
# subnet, and at most 256 * 155 of them before the second octet would leave
# 10/8.
MAX_PREFIXES = 256 * 155

CONTAINER_PREFIX = 'parity_'
NETWORK = 'bgperf-parity-br'
SUBNET = '10.99.0.0/16'
SPEAKER = {'as': 1000, 'router-id': '10.99.0.10', 'local-address': '10.99.0.10'}
SINK = {'as': 1001, 'router-id': '10.99.0.20', 'local-address': '10.99.0.20'}
GOBGP = {'as': 1002, 'router-id': '10.99.0.30', 'local-address': '10.99.0.30'}


def parity_prefixes(n):
    '''The first `n` /24s this check announces, in order.'''
    if not 0 <= n <= MAX_PREFIXES:
        raise ValueError('between 0 and {0} prefixes, not {1}'.format(
            MAX_PREFIXES, n))
    return ['10.{0}.{1}.0/24'.format(100 + i // 256, i % 256) for i in range(n)]


def plan_steps(prefixes, withdraw, reannounce):
    '''The steps, each with the count both monitors must reach.

    A re-announcement of held prefixes with another next hop replaces them,
    so it leaves the count where the withdrawal put it. That is the case
    worth checking: a counter that adds on every announcement would read
    higher here.
    '''
    if not 0 <= withdraw <= prefixes:
        raise ValueError('cannot withdraw {0} of {1}'.format(withdraw, prefixes))
    held = prefixes - withdraw
    if not 0 <= reannounce <= held:
        raise ValueError('cannot re-announce {0} of the {1} still held'.format(
            reannounce, held))
    steps = [('announce', prefixes, prefixes)]
    if withdraw:
        steps.append(('withdraw', withdraw, held))
    if reannounce:
        steps.append(('reannounce', reannounce, held))
    return steps


def step_verdict(expected, sink_count, gobgp_count):
    '''`agree`, `disagree` (the two differ), or `short` (equal, but not there).'''
    if sink_count != gobgp_count:
        return 'disagree'
    if sink_count != expected:
        return 'short'
    return 'agree'


def settled(verdict, updates_before, updates, quiet_s, settle_s):
    '''Whether a step is finished, not merely agreeing.

    A count that agrees is not enough. A re-announcement of held prefixes
    leaves the count where it was, so both monitors "agree" before a single
    replacement has arrived. The step is over once the sink has taken at
    least one UPDATE since it began and nothing more for `settle_s`. Its
    UPDATE counter is the only witness here that the step's messages were
    delivered at all.
    '''
    return (verdict == 'agree' and updates > updates_before
            and quiet_s >= settle_s)


def gobgp_accepted(info):
    # gobgp omits `accepted` until the session has accepted something.
    return int(info['afi_safis'][0]['state'].get('accepted', 0))


def speaker_rib(speaker, op, prefixes, nexthop):
    '''Add or delete `prefixes` on the speaker's global RIB, in one exec.'''
    script = '\n'.join('gobgp global rib {0} {1} nexthop {2} -a ipv4'.format(
        op, p, nexthop) if op == 'add' else
        'gobgp global rib del {0} -a ipv4'.format(p) for p in prefixes)
    path = os.path.join(speaker.host_dir, 'rib-{0}.sh'.format(op))
    with open(path, 'w') as f:
        f.write('#!/bin/bash\nset -e\n' + script + '\n')
    os.chmod(path, 0o755)
    out = speaker.local('{0}/rib-{1}.sh'.format(speaker.guest_dir, op))
    if out:
        raise RuntimeError('speaker: `gobgp global rib {0}` said: {1}'.format(
            op, out.decode('utf-8', 'replace')[:400]))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('-n', '--prefixes', type=int, default=3000)
    parser.add_argument('--withdraw', type=int, default=None,
                        help='default: a third of --prefixes')
    parser.add_argument('--reannounce', type=int, default=None,
                        help='default: a quarter of what is still held')
    parser.add_argument('--timeout', type=float, default=60.0,
                        help='seconds each step may take to agree')
    parser.add_argument('--settle', type=float, default=2.0,
                        help='seconds without a new UPDATE at the sink before '
                             'a step that agrees is over')
    parser.add_argument('--dir', default='/data/bgperf-work/scratch/parity',
                        help='host directory for the three containers\' config')
    parser.add_argument('--json', action='store_true',
                        help='print the result as JSON')
    parser.add_argument('--keep', action='store_true',
                        help='leave the containers and network up')
    args = parser.parse_args(argv)

    withdraw = args.prefixes // 3 if args.withdraw is None else args.withdraw
    held = args.prefixes - withdraw
    reannounce = held // 4 if args.reannounce is None else args.reannounce
    try:
        prefixes = parity_prefixes(args.prefixes)
        steps = plan_steps(args.prefixes, withdraw, reannounce)
    except ValueError as e:
        parser.error(str(e))

    # Imported here so `--help` and the pure helpers need no Docker.
    from docker.types import IPAMConfig, IPAMPool
    import yaml
    from gobgp import GoBGP
    from monitor import Monitor, SinkMonitor
    from settings import dckr

    class Speaker(GoBGP):
        '''A GoBGP holding the routes, peered with both monitors.'''

        def run(self, peers, dckr_net_name):
            ctn = super(GoBGP, self).run(dckr_net_name)
            config = {
                'global': {'config': {'as': self.conf['as'],
                                      'router-id': self.conf['router-id']}},
                'neighbors': [{
                    'config': {'neighbor-address': p['local-address'],
                               'peer-as': p['as']},
                    'transport': {'config': {
                        'local-address': self.conf['local-address']}},
                } for p in peers],
            }
            with open(os.path.join(self.host_dir, 'gobgpd.conf'), 'w') as f:
                f.write(yaml.dump(config))
            with open(os.path.join(self.host_dir, 'start.sh'), 'w') as f:
                f.write('#!/bin/bash\ngobgpd -t yaml -f {0}/gobgpd.conf '
                        '> {0}/gobgpd.log 2>&1\n'.format(self.guest_dir))
            os.chmod(os.path.join(self.host_dir, 'start.sh'), 0o777)
            self.local('{0}/start.sh'.format(self.guest_dir), detach=True)
            return ctn

    names = [CONTAINER_PREFIX + n for n in ('speaker', 'sink', 'gobgp')]

    def clear():
        '''Remove this check's containers, then its network.

        Containers first: a network with endpoints cannot be removed, and a
        previous `--keep` run leaves exactly that. Each step is guarded, so a
        failed cleanup is reported rather than replacing the result.
        '''
        problems = []
        for name in names:
            try:
                dckr.remove_container(name, force=True)
            except Exception as e:                      # noqa: BLE001
                if 'No such container' not in str(e):
                    problems.append('{0}: {1}'.format(name, e))
        try:
            for net in dckr.networks(names=[NETWORK]):
                dckr.remove_network(net['Id'])
        except Exception as e:                          # noqa: BLE001
            problems.append('{0}: {1}'.format(NETWORK, e))
        return problems

    shutil.rmtree(args.dir, ignore_errors=True)

    speaker = Speaker(os.path.join(args.dir, 'speaker'), SPEAKER)
    speaker.name = CONTAINER_PREFIX + 'speaker'
    sink = SinkMonitor(os.path.join(args.dir, 'sink'), SINK)
    sink.name = CONTAINER_PREFIX + 'sink'
    gobgp = Monitor(os.path.join(args.dir, 'gobgp'), GOBGP)
    gobgp.name = CONTAINER_PREFIX + 'gobgp'
    for m in (sink, gobgp):
        m.monitor_for = 'parity speaker'

    result = {'prefixes': args.prefixes, 'steps': [], 'clock_offset_ns': None,
              'sink_version': None, 'gobgp_version': None}
    failed = False
    try:
        # Inside the guard, so a host this cannot be set up on exits 2.
        leftover = clear()
        if leftover:
            raise RuntimeError('could not clear a previous run: '
                               + '; '.join(leftover))
        dckr.create_network(NETWORK, driver='bridge', ipam=IPAMConfig(
            pool_configs=[IPAMPool(subnet=SUBNET)]))
        speaker.run([SINK, GOBGP], NETWORK)
        for m in (sink, gobgp):
            m.run({'target': SPEAKER}, NETWORK)
        for m in (sink, gobgp):
            m.wait_established(SPEAKER['local-address'], role=m.name)
        result['sink_version'] = sink.version_string()
        result['gobgp_version'] = gobgp.version_string()

        updates_before = sink.read_sample(time.monotonic())['sink']['updates']
        for name, count, expected in steps:
            if name == 'announce':
                speaker_rib(speaker, 'add', prefixes, SPEAKER['local-address'])
            elif name == 'withdraw':
                speaker_rib(speaker, 'del', prefixes[:count], None)
            else:
                # Held prefixes, another next hop: a replacement.
                speaker_rib(speaker, 'add', prefixes[withdraw:withdraw + count],
                            '10.99.0.11')
            started = time.monotonic()
            last_updates, last_change = updates_before, started
            while True:
                at = time.monotonic()
                sample = sink.read_sample(at)
                s = sample['afi_safis'][0]['state']['accepted']
                updates = sample['sink']['updates']
                if updates != last_updates:
                    last_updates, last_change = updates, at
                g = gobgp_accepted(gobgp.read_sample(at))
                verdict = step_verdict(expected, s, g)
                if settled(verdict, updates_before, updates, at - last_change,
                           args.settle):
                    break
                if at - started > args.timeout:
                    if verdict == 'agree':
                        # Agreeing on counts the step never moved is not a
                        # result: nothing showed its messages arrived.
                        verdict = 'undelivered'
                    break
                time.sleep(0.25)
            result['steps'].append({'step': name, 'count': count,
                                    'expected': expected, 'sink': s,
                                    'gobgp': g, 'verdict': verdict,
                                    'sink_updates': updates - updates_before,
                                    'waited_s': round(time.monotonic() - started, 3)})
            updates_before = updates
            failed = failed or verdict != 'agree'

        log = sink.reader.read()
        result['clock_offset_ns'] = log.clock_offset_ns(time.time_ns(),
                                                        time.monotonic_ns())
        result['sink_log'] = {'refused_messages': log.refused_messages,
                              'processes': log.processes,
                              'sessions_established': log.sessions_established}
    except Exception as e:                              # noqa: BLE001
        result['error'] = '{0}: {1}'.format(type(e).__name__, e)
    finally:
        if not args.keep:
            problems = clear()
            if problems:
                result['cleanup_problems'] = problems
                print('cleanup: ' + '; '.join(problems), file=sys.stderr)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print('sink:  {0}\ngobgp: {1}'.format(result['sink_version'],
                                               result['gobgp_version']))
        print('{0:<11} {1:>8} {2:>9} {3:>9} {4:>9}  {5}'.format(
            'step', 'count', 'expected', 'sink', 'gobgp', 'verdict'))
        for st in result['steps']:
            print('{step:<11} {count:>8} {expected:>9} {sink:>9} {gobgp:>9}  '
                  '{verdict} ({sink_updates} UPDATEs at the sink, settled in '
                  '{waited_s}s)'.format(**st))
        if result['clock_offset_ns'] is not None:
            print('sink clock offset from this host: {0:.1f} us'.format(
                result['clock_offset_ns'] / 1e3))
        if 'error' in result:
            print('could not run: {0}'.format(result['error']), file=sys.stderr)
    if 'error' in result:
        return 2
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
