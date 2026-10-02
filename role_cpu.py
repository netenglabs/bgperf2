"""Per-role CPU, read from each container's cgroup on the controller's clock.

`min idle%` says the machine had nothing spare and not whose work that was,
and a container's `docker stats` stream says whose but on Docker's clock, one
container at a time, and only for the target. This reads every container the
run started -- target, monitor, generators, receivers -- from its cgroup v2
`cpu.stat`, in one pass per poll, and sums each role's members.

CPU is a **delta between two reads**, for the reason `contention.py` measures
`/proc` that way: `usage_usec` is cumulative, so one reading says what the
container has done since it started, which is not what it was doing during the
run. Each interval is published with the two instants that bound it, stamped
before the reads, so the resolution is the gap the loop achieved rather than
the one it asked for.

A role's interval is published only when every member was read at both ends.
A sum missing one generator is a smaller number, not an unknown one, and it
would read as the role doing less work. Such an interval is `None` with the
reason beside it.

This module publishes the series and decides nothing. A rule that reads it is
a separate decision (`docs/invariants/findings.md`), so nothing here is
imported by `findings.py`.

Kept free of Docker and privileges, like `contention.py`, so the test suite
covers it. bgperf2.py resolves each container's cgroup from its pid and hands
this module paths.
"""

import os
import threading

CGROUP_ROOT = '/sys/fs/cgroup'

# The monitor's cadence (MONITOR_POLL_INTERVAL_S), so a CPU interval and a
# monitor sample cover comparable stretches of the run. Reading a few dozen
# cgroup files costs well under a millisecond.
ROLE_CPU_INTERVAL_S = 1.0

ROLE_CPU_SOURCE = 'cgroup v2 cpu.stat usage_usec'

# The roles, in the order the section lists them. A role with no members in a
# given run (no receivers, a remote target) is absent or carries its reason.
ROLES = ('target', 'monitor', 'testers', 'receivers')


def parse_cpu_stat(text):
    """`usage_usec` from a cgroup v2 `cpu.stat`, or None if it is not there."""
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0] == 'usage_usec':
            try:
                return int(parts[1])
            except ValueError:
                return None
    return None


def cgroup_v2_path(proc_cgroup_text):
    """The unified-hierarchy path from a `/proc/<pid>/cgroup`, or None.

    A cgroup v2 process has exactly one line, `0::<path>`. A v1 host lists a
    line per controller and no `0::` line with a usable path, and gets None:
    its `cpuacct.usage` is a different file with a different unit, and
    reading it is not something this module has been checked against.
    """
    for line in proc_cgroup_text.splitlines():
        if line.startswith('0::'):
            path = line[3:].strip()
            return path or None
    return None


def cgroup_dir_for_pid(pid, proc_root='/proc', cgroup_root=CGROUP_ROOT):
    """The cgroup directory a process lives in, or raise saying why not.

    Read through the process rather than built from the container id, because
    the layout differs by Docker's cgroup driver -- `system.slice/docker-<id>.scope`
    under systemd, `docker/<id>` under cgroupfs -- and `/proc/<pid>/cgroup`
    names whichever one this host uses.
    """
    with open(os.path.join(proc_root, str(pid), 'cgroup')) as f:
        relative = cgroup_v2_path(f.read())
    if relative is None:
        raise ValueError('pid {0} has no cgroup v2 path; this host is not on '
                         'the unified hierarchy'.format(pid))
    path = os.path.join(cgroup_root, relative.lstrip('/'))
    if not os.path.exists(os.path.join(path, 'cpu.stat')):
        raise ValueError('{0} has no cpu.stat'.format(path))
    return path


def read_usage_usec(cgroup_dir):
    """One cumulative reading, or raise. Missing is an error, never zero."""
    with open(os.path.join(cgroup_dir, 'cpu.stat')) as f:
        usage = parse_cpu_stat(f.read())
    if usage is None:
        raise ValueError('cpu.stat in {0} has no usage_usec'.format(cgroup_dir))
    return usage


def read_effective_cpuset(cgroup_dir):
    """The cores the kernel actually lets this cgroup run on, or None."""
    try:
        with open(os.path.join(cgroup_dir, 'cpuset.cpus.effective')) as f:
            return f.read().strip() or None
    except OSError:
        return None


def cpuset_size(cpuset):
    """How many cores a cpuset list (`0-7,9`) names, or None if unparseable."""
    if not cpuset:
        return None
    cores = set()
    try:
        for part in cpuset.split(','):
            part = part.strip()
            if '-' in part:
                low, high = part.split('-', 1)
                cores.update(range(int(low), int(high) + 1))
            elif part:
                cores.add(int(part))
    except ValueError:
        return None
    return len(cores) or None


def read_members(members, reader=read_usage_usec):
    """One pass over every member: `(usage by name, error by name)`.

    A member that could not be read appears in the errors and not in the
    usage, so the two can never both claim it.
    """
    usage, errors = {}, {}
    for role_members in members.values():
        for member in role_members:
            name = member['name']
            try:
                usage[name] = reader(member['cgroup_dir'])
            except Exception as exc:  # a container that exited, a cgroup gone
                errors[name] = '{0}: {1}'.format(type(exc).__name__, exc)
    return usage, errors


class RoleCpuRecorder:
    """The per-role series for one run. The poll thread is its only writer.

    `members` maps a role to its containers, each a dict with `name`,
    `cgroup_dir`, `cpuset_requested` (what `--pin` asked Docker for, None when
    unpinned) and `cpuset_effective` (what the kernel reported when the run
    started). `unmeasured` maps a role this run has but could not read to the
    reason, so a role that was never asked and one that could not be answered
    are not the same absence.
    """

    def __init__(self, origin_s, members, unmeasured=None,
                 interval_s=ROLE_CPU_INTERVAL_S):
        self.origin_s = float(origin_s)
        self.members = {role: list(ms) for role, ms in members.items() if ms}
        self.unmeasured = dict(unmeasured or {})
        self.interval_s = interval_s
        self._lock = threading.Lock()
        self._previous = None  # (monotonic_s, usage, errors)
        self._first = {}       # name -> (monotonic_s, usage) first good read
        self._last = {}        # name -> (monotonic_s, usage) last good read
        self._unread = {}      # name -> True once any read failed
        self._intervals = {role: [] for role in self.members}
        self._first_error = {}
        self.poll_incomplete = None

    def observe(self, monotonic_s, usage, errors=None):
        errors = dict(errors or {})
        with self._lock:
            for name, error in errors.items():
                self._first_error.setdefault(name, error)
                self._unread[name] = True
            for name, value in usage.items():
                self._first.setdefault(name, (monotonic_s, value))
                self._last[name] = (monotonic_s, value)
            previous = self._previous
            self._previous = (monotonic_s, dict(usage), errors)
            if previous is None:
                return
            start_s, before, _ = previous
            elapsed = monotonic_s - start_s
            for role, role_members in self.members.items():
                self._intervals[role].append(self._interval(
                    role_members, start_s, monotonic_s, elapsed,
                    before, usage))

    def _interval(self, role_members, start_s, end_s, elapsed, before, after):
        interval = {'start_s': round(start_s - self.origin_s, 6),
                    'end_s': round(end_s - self.origin_s, 6),
                    'cpu_percent': None}
        unread = sorted(m['name'] for m in role_members
                        if m['name'] not in before or m['name'] not in after)
        if unread:
            interval['unread'] = unread
            return interval
        if elapsed <= 0:
            interval['unread_reason'] = 'the two reads share an instant'
            return interval
        deltas = [after[m['name']] - before[m['name']] for m in role_members]
        if any(delta < 0 for delta in deltas):
            # A cumulative counter that went backwards is a different cgroup
            # under the same name, not negative work.
            interval['unread_reason'] = 'a cumulative counter went backwards'
            return interval
        interval['cpu_percent'] = round(
            100.0 * sum(deltas) / 1e6 / elapsed, 3)
        return interval

    def _role_section(self, role, role_members, intervals):
        values = [i['cpu_percent'] for i in intervals
                  if i['cpu_percent'] is not None]
        names = [m['name'] for m in role_members]
        # CPU seconds across the whole window, only when every member was read
        # on every poll: a member missing from the first or last read would be
        # charged for a shorter window than the others.
        complete = all(name in self._first and not self._unread.get(name)
                       for name in names)
        cpu_seconds = None
        if complete:
            cpu_seconds = round(sum(self._last[n][1] - self._first[n][1]
                                    for n in names) / 1e6, 6)
        requested = sorted({m.get('cpuset_requested') or '' for m in role_members})
        effective = sorted({m.get('cpuset_effective') or '' for m in role_members})
        section = {
            'containers': [
                {'name': m['name'],
                 'cpuset_requested': m.get('cpuset_requested'),
                 'cpuset_effective': m.get('cpuset_effective'),
                 'first_error': self._first_error.get(m['name'])}
                for m in role_members],
            'pinned': all(m.get('cpuset_requested') for m in role_members),
            # One value when every member agrees, which is every run --pin
            # makes; otherwise None, and the per-container entries say why.
            'cpuset_effective': (effective[0] or None) if len(effective) == 1 else None,
            'cores': (cpuset_size(effective[0]) if len(effective) == 1
                      else None),
            'intervals': intervals,
            'intervals_read': len(values),
            'intervals_unread': len(intervals) - len(values),
            'peak_cpu_percent': max(values) if values else None,
            'cpu_seconds': cpu_seconds,
        }
        if len(requested) > 1:
            section['cpuset_requested_differs'] = True
        return section

    def section(self):
        with self._lock:
            roles = {}
            for role in ROLES:
                if role in self.members:
                    roles[role] = self._role_section(
                        role, self.members[role], list(self._intervals[role]))
                elif role in self.unmeasured:
                    roles[role] = {'unmeasured_reason': self.unmeasured[role]}
            for role, reason in self.unmeasured.items():
                if role not in roles:
                    roles[role] = {'unmeasured_reason': reason}
            section = {
                'clock': 'monotonic',
                'origin': 'bench_clock_started',
                'source': ROLE_CPU_SOURCE,
                'sample_interval_s': self.interval_s,
                # 100 is one core, as `docker stats` and the target's own CPU
                # column count it.
                'unit': 'percent of one core',
                'roles': roles,
            }
            if self.poll_incomplete:
                section['poll_incomplete'] = self.poll_incomplete
            return section
