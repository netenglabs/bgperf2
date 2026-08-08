# Host contention detection for a benchmark run.
#
# bgperf2 measures wall-clock convergence and CPU on the machine it runs on, so
# anything else using that machine lands directly in the results. It is not a
# theoretical worry: FRR 8.5, 9.1 and 10.0 came within 0.11s of each other over
# a 95s run, so a competing job of a few cores is more than enough to invent a
# version ranking that never existed. The existing min_idle column shows the
# machine was busy but not *who* was busy, and bgperf's own load moves that
# number too.
#
# CPU is measured as a delta between two samples, NOT with `ps -eo pcpu`.
# ps reports a lifetime average -- cputime divided by how long the process has
# been alive -- which fails in both directions here. A process that finished a
# heavy job an hour ago still reports a high number and would condemn a clean
# run; far worse, a long-lived process that starts burning four cores for the
# 95 seconds of a run barely moves its average at all and would be invisible.
# Measured on a real box: a process alive 16821s with 1475s of CPU reads 8.7%,
# and four cores for 95s would take it to about 11%.
#
# Kept free of Docker and privileges so the test suite can cover it.

import os

# Processes that belong to the benchmark or to the harness driving it. Anything
# else counts as competition.
#
# Every daemon a target can run has to be listed, or that target's own load is
# reported as contention and every one of its rows looks incomparable.
#
# The commercial NOSes are the weak spot: cEOS and SR Linux each run dozens of
# agents and the lists below are the main ones, not the complete set. Those
# images are downloaded out of band and cannot be checked here, so treat a
# nonzero max foreign cpu % on a crpd/ceos/srlinux row as "probably its own
# agents" and add the names rather than assuming the machine was busy.
BGPERF_PROCESSES = frozenset((
    # FRR
    'bgpd', 'zebra', 'staticd', 'watchfrr', 'mgmtd', 'vtysh', 'watchquagga',
    # other open-source targets and the load generators
    'gobgpd', 'gobgp', 'bird', 'birdc', 'rustybgpd', 'rustybgp',
    'openbgpd', 'bgpd.openbsd', 'bgpctl', 'bgplgd', 'exabgp', 'bgpdump2',
    'flockd', 'flock',
    # commercial NOSes: Junos cRPD, Arista cEOS, Nokia SR Linux
    'rpd', 'mgd', 'na-grpcd', 'na_grpcd', 'jsd', 'lmpd', 'ppmd', 'bfdd',
    'Bgp', 'ConfigAgent', 'EosSdk', 'Sysdb', 'Fru', 'Launcher', 'ProcMgr',
    'Ebra', 'Rib', 'Ira', 'Lag', 'Stp', 'SuperServer', 'Arp', 'StageMgr',
    'sr_bgp_mgr', 'sr_linux_mgr', 'sr_cli', 'sr_device_mgr', 'sr_app_mgr',
    'sr_fib_mgr', 'sr_chassis_mgr', 'sr_aaa_mgr', 'sr_xdp_cpm', 'sdk_mgr',
    # NOTE: interpreters are deliberately absent. `python`, `python3`, `sh` and
    # `bash` were in this list at first, and that is a hole big enough to make
    # the whole feature lie: /proc/<pid>/comm for a script-driven workload is
    # the interpreter, so a neighbouring `python3 train.py` burning eight cores
    # was filtered out and the row recorded 0 -- a positive all-clear on the
    # exact case this exists to catch. bgperf2's own Python is excluded by PID
    # instead, via own_process_tree().
    # container plumbing
    'docker', 'dockerd', 'containerd', 'containerd-shim',
    'containerd-shim-runc-v2', 'runc', 'docker-proxy',
))

# Foreign CPU above this is reported. One core's worth: below that, timings are
# not meaningfully perturbed on a machine with many cores.
CONTENTION_PERCENT = 100.0

# Fields of /proc/<pid>/stat, counted from after the comm field. The comm can
# contain spaces and parentheses, so everything is measured from the last ')'
# rather than by splitting the whole line. flags is field 9, utime 14, stime 15.
_PPID_AFTER_COMM = 1
_FLAGS_AFTER_COMM = 6
_UTIME_AFTER_COMM = 11
_STIME_AFTER_COMM = 12

# PF_KTHREAD. Kernel threads are excluded because the ones that show up during
# a run -- ksoftirqd, kworker, the veth and bridge softirq work -- are doing
# *the benchmark's own* network traffic. Charging them as competition would put
# a nonzero number in max foreign cpu % on a machine that is entirely the
# user's, which is precisely the reading the column is supposed to rule out.
PF_KTHREAD = 0x00200000

try:
    CLOCK_TICKS = os.sysconf('SC_CLK_TCK')
except (ValueError, OSError):        # pragma: no cover - every Linux has it
    CLOCK_TICKS = 100


def parse_proc_stat(text, skip_kernel_threads=True):
    '''Pull (command, ppid, cpu_ticks) out of the contents of /proc/<pid>/stat.

    Returns None for anything unparsable, and for kernel threads, rather than
    raising: this runs in a sampling thread against processes that exit while
    being read, and losing the whole run's contention record over one such race
    would be worse than missing one process.
    '''
    open_paren = text.find('(')
    close_paren = text.rfind(')')
    if open_paren < 0 or close_paren < open_paren:
        return None
    comm = text[open_paren + 1:close_paren]
    fields = text[close_paren + 1:].split()
    if len(fields) <= _STIME_AFTER_COMM:
        return None
    try:
        if skip_kernel_threads and int(fields[_FLAGS_AFTER_COMM]) & PF_KTHREAD:
            return None
        ppid = fields[_PPID_AFTER_COMM]
        ticks = int(fields[_UTIME_AFTER_COMM]) + int(fields[_STIME_AFTER_COMM])
    except ValueError:
        return None
    return comm, ppid, ticks


def own_process_tree(sample, root_pid=None):
    '''PIDs of bgperf2 itself and everything it spawned.

    Identifying our own Python by command name is not possible -- somebody
    else's `python3 train.py` has the same name -- so the harness and the
    helpers it shells out to (mpstat, free, ps) are excluded by descent from
    this process instead.
    '''
    root = str(root_pid if root_pid is not None else os.getpid())
    children = {}
    for pid, (_, ppid, _) in sample.items():
        children.setdefault(ppid, []).append(pid)

    tree = set()
    pending = [root]
    while pending:
        pid = pending.pop()
        if pid in tree:
            continue
        tree.add(pid)
        pending.extend(children.get(pid, ()))
    return tree


def sample_processes(proc_root='/proc'):
    '''{pid: (command, ppid, cpu_ticks)} for every userspace process.'''
    sample = {}
    try:
        entries = os.listdir(proc_root)
    except OSError:
        return sample
    for entry in entries:
        if not entry.isdigit():
            continue
        try:
            with open(os.path.join(proc_root, entry, 'stat')) as f:
                parsed = parse_proc_stat(f.read())
        except (OSError, UnicodeDecodeError):
            continue          # process exited between listdir and open
        if parsed:
            sample[entry] = parsed
    return sample


def foreign_processes(previous, current, elapsed_seconds, extra_allowed=(),
                      clock_ticks=None, own_pids=None):
    '''(percent_of_one_core, command) for each competing process.

    Percentages come from CPU actually consumed between the two samples, so a
    process that was busy before the run started contributes nothing.
    '''
    if elapsed_seconds <= 0:
        return []
    ticks = clock_ticks or CLOCK_TICKS
    allowed = BGPERF_PROCESSES.union(extra_allowed)
    own = own_pids if own_pids is not None else set()
    # A process cannot have used more than the whole interval on one core, so
    # this bounds what a first-seen process can be charged.
    interval_ticks = ticks * elapsed_seconds
    busy = []
    for pid, (comm, _ppid, now_ticks) in current.items():
        if comm in allowed or pid in own:
            continue
        was = previous.get(pid)
        if was is None or was[0] != comm:
            # No baseline: the process started during the interval. Charging
            # nothing meant a parallel build -- the canonical "someone else is
            # on the box" case, thousands of sub-second cc1 processes that
            # never appear in two consecutive samples -- scored exactly 0 on a
            # fully saturated machine. Charge what it used, capped at the
            # interval so a process that somehow predates the sample cannot be
            # billed for its whole lifetime.
            delta = min(now_ticks, interval_ticks)
        else:
            delta = now_ticks - was[2]
        if delta <= 0:
            continue
        busy.append((delta / ticks / elapsed_seconds * 100.0, comm))
    return busy


def foreign_cpu_percent(previous, current, elapsed_seconds, extra_allowed=(),
                        clock_ticks=None, own_pids=None):
    '''Total %CPU used between two samples by processes outside the benchmark.

    100.0 means one core's worth, so this exceeds 100 on a busy multi-core box.
    '''
    return sum(pct for pct, _ in foreign_processes(
        previous, current, elapsed_seconds, extra_allowed, clock_ticks, own_pids))


def top_foreign(previous, current, elapsed_seconds, limit=3, extra_allowed=(),
                clock_ticks=None, own_pids=None):
    '''The heaviest competing processes, for naming names in a warning.'''
    ranked = sorted(foreign_processes(previous, current, elapsed_seconds,
                                      extra_allowed, clock_ticks, own_pids),
                    reverse=True)
    return ranked[:limit]


def describe_contention(previous, current, elapsed_seconds, extra_allowed=(),
                        clock_ticks=None, own_pids=None):
    '''One line naming who is competing, or None if the machine is quiet.'''
    percent = foreign_cpu_percent(previous, current, elapsed_seconds,
                                  extra_allowed, clock_ticks, own_pids)
    if percent < CONTENTION_PERCENT:
        return None
    names = ', '.join('{0} {1:.0f}%'.format(comm, pct) for pct, comm in top_foreign(
        previous, current, elapsed_seconds, extra_allowed=extra_allowed,
        clock_ticks=clock_ticks, own_pids=own_pids))
    return ('{0:.0f}% CPU ({1:.1f} cores) used by processes outside the '
            'benchmark: {2}'.format(percent, percent / 100.0, names))
