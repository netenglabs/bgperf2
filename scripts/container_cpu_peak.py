#!/usr/bin/env python3
'''Sample named containers' CPU from their cgroups, and report each one's peak.

Measurement plan 7a check 4 publishes the sink's peak CPU beside the GoBGP
monitor's old 380%. Nothing in a run samples the monitor's CPU: `max cpu %`
is the target's. This reads each container's cgroup v2 `cpu.stat`
(`usage_usec`) from the host once per interval and reports the peak, the mean,
and the number of intervals. It costs no `docker exec`, so it adds nothing
inside the containers it measures.

A percentage is CPU time over wall time for one interval, so 100% is one core,
the scale `max cpu %` uses. The peak is the busiest interval. With a 1 s
interval it is a 1 s average, not an instantaneous maximum, and it is printed
with the interval for that reason.

Each container *instance* is reported separately, keyed by name and short id.
A batch recreates `bgperf_monitor` for every cell, so the same name covers
many instances. It runs until none of the named containers has been running
for `--gone-after` seconds (one empty poll is only the gap between two cells),
or until `--duration` or SIGINT/SIGTERM, then prints one JSON line per
instance.

Usage: scripts/container_cpu_peak.py [--interval 1] [--duration S] NAME...
'''
import argparse
import json
import os
import signal
import sys
import time

CGROUP_ROOTS = ('/sys/fs/cgroup/system.slice/docker-{0}.scope',
                '/sys/fs/cgroup/docker/{0}')


def usage_usec(container_id):
    '''The container's cumulative CPU time in microseconds, or None.'''
    for root in CGROUP_ROOTS:
        try:
            with open(os.path.join(root.format(container_id), 'cpu.stat')) as f:
                for line in f:
                    key, _, value = line.partition(' ')
                    if key == 'usage_usec':
                        return int(value)
        except OSError:
            continue
    return None


class Tracker:
    '''Peak and mean CPU for one container instance, from cumulative readings.'''

    def __init__(self, name, cid):
        self.name, self.cid = name, cid
        self.last = None
        self.peak_pct = None
        self.total_pct = 0.0
        self.intervals = 0

    def observe(self, wall_s, usage):
        if usage is None:
            return
        if self.last is not None:
            dt = wall_s - self.last[0]
            if dt > 0:
                pct = 100.0 * (usage - self.last[1]) / 1e6 / dt
                self.peak_pct = pct if self.peak_pct is None else max(self.peak_pct, pct)
                self.total_pct += pct
                self.intervals += 1
        self.last = (wall_s, usage)

    def summary(self, interval):
        return {'name': self.name, 'id': self.cid[:12],
                'peak_cpu_pct': None if self.peak_pct is None else round(self.peak_pct, 1),
                'mean_cpu_pct': (round(self.total_pct / self.intervals, 1)
                                 if self.intervals else None),
                'intervals': self.intervals, 'interval_s': interval}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('names', nargs='+')
    parser.add_argument('--interval', type=float, default=1.0)
    parser.add_argument('--duration', type=float, default=None)
    parser.add_argument('--gone-after', type=float, default=60.0,
                        help='without --duration, stop once none of the '
                             'named containers has run for this long (a '
                             'batch recreates them between cells, so one '
                             'empty poll is not the end)')
    args = parser.parse_args(argv)

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from settings import dckr

    trackers = {}
    stop = []
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.append(True))
    started = time.monotonic()
    seen_any = False
    last_seen = started
    while not stop:
        tick = time.monotonic()
        running = {c['Names'][0].lstrip('/'): c['Id']
                   for c in dckr.containers(filters={'status': 'running'})}
        wanted = {n: running[n] for n in args.names if n in running}
        if wanted:
            seen_any = True
            last_seen = tick
        for name, cid in wanted.items():
            tracker = trackers.setdefault(cid, Tracker(name, cid))
            tracker.observe(time.monotonic(), usage_usec(cid))
        if (seen_any and not wanted and args.duration is None
                and tick - last_seen >= args.gone_after):
            break
        if args.duration is not None and tick - started >= args.duration:
            break
        time.sleep(max(0.0, args.interval - (time.monotonic() - tick)))
    for tracker in trackers.values():
        print(json.dumps(tracker.summary(args.interval)), flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
