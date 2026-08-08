'''Telling bgperf's own load apart from someone else's.

A benchmark sharing its machine reports numbers that look fine and are not
comparable with anything. min_idle records that the box was busy but not who
made it busy, and bgperf's own daemons move that number too.

The measurement is a delta between two samples. `ps -eo pcpu` was tried first
and is wrong for this: it reports cputime divided by process lifetime, so a
process that finished a heavy job an hour ago still reads high, and -- the case
that matters -- a long-lived process that starts burning four cores for the 95
seconds of a run barely moves its average and stays invisible.
'''
import pytest

from contention import (
    CONTENTION_PERCENT,
    describe_contention,
    foreign_cpu_percent,
    own_process_tree,
    parse_proc_stat,
    sample_processes,
    top_foreign,
)


TICKS = 100          # SC_CLK_TCK on Linux; pinned so the tests are arithmetic


def sample(**procs):
    '''{pid: (comm, ppid, ticks)} from pairs like p1=('julia', 500).

    Everything is parented to pid 1 so it never looks like one of bgperf's own
    processes; own_process_tree() is exercised separately.
    '''
    return {pid: (comm, '1', ticks) for pid, (comm, ticks) in procs.items()}


def test_cpu_is_measured_between_samples_not_over_process_lifetime():
    '''The regression that motivated the rewrite.

    A process alive for hours with a low average that suddenly burns two cores
    for the interval has to register as two cores.
    '''
    before = sample(p1=('julia', 1_000_000))
    after = sample(p1=('julia', 1_000_000 + 2 * TICKS * 10))   # 2 cores x 10s
    assert foreign_cpu_percent(before, after, 10, clock_ticks=TICKS) == pytest.approx(200.0)


def test_a_process_busy_before_the_run_counts_for_nothing():
    '''The other half: huge lifetime CPU, but idle across the interval.'''
    before = sample(p1=('julia', 50_000_000))
    after = sample(p1=('julia', 50_000_000))
    assert foreign_cpu_percent(before, after, 10, clock_ticks=TICKS) == 0
    assert describe_contention(before, after, 10, clock_ticks=TICKS) is None


def test_benchmark_processes_are_not_counted_as_competition():
    '''An idle machine running a heavy benchmark is still an idle machine.'''
    before = sample(p1=('bgpd', 0), p2=('gobgpd', 0), p3=('bgpdump2', 0))
    after = sample(p1=('bgpd', 400 * TICKS), p2=('gobgpd', 100 * TICKS),
                   p3=('bgpdump2', 50 * TICKS))
    assert foreign_cpu_percent(before, after, 10, clock_ticks=TICKS) == 0
    assert describe_contention(before, after, 10, clock_ticks=TICKS) is None


@pytest.mark.parametrize('daemon', ['flockd', 'rpd', 'Bgp', 'sr_bgp_mgr', 'mgmtd'])
def test_every_target_daemon_is_recognised_as_ours(daemon):
    '''A target whose daemon is missing from the allowlist reports its own load
    as contention, so every one of its rows looks incomparable.'''
    before = sample(p1=(daemon, 0))
    after = sample(p1=(daemon, 400 * TICKS))
    assert foreign_cpu_percent(before, after, 10, clock_ticks=TICKS) == 0


def test_foreign_processes_are_summed_and_named():
    before = sample(p1=('julia', 0), p2=('julia', 0), p3=('bgpd', 0))
    after = sample(p1=('julia', 300 * TICKS), p2=('julia', 100 * TICKS),
                   p3=('bgpd', 900 * TICKS))
    assert foreign_cpu_percent(before, after, 100, clock_ticks=TICKS) == pytest.approx(400.0)

    complaint = describe_contention(before, after, 100, clock_ticks=TICKS)
    assert 'julia' in complaint
    assert '4.0 cores' in complaint
    assert 'bgpd' not in complaint      # never blame the benchmark


def test_threshold_is_one_core():
    def at(percent):
        before = sample(p1=('julia', 0))
        after = sample(p1=('julia', int(percent / 100.0 * TICKS * 10)))
        return describe_contention(before, after, 10, clock_ticks=TICKS)

    assert at(CONTENTION_PERCENT - 5) is None
    assert at(CONTENTION_PERCENT + 5) is not None


def test_short_lived_processes_are_charged_up_to_the_interval():
    '''A parallel build is thousands of sub-second processes that never appear
    in two consecutive samples. Skipping anything without a baseline scored a
    fully saturated machine at exactly 0.
    '''
    after = sample(p1=('cc1', 5 * TICKS))      # 5s of CPU, first time seen
    assert foreign_cpu_percent({}, after, 10, clock_ticks=TICKS) == pytest.approx(50.0)


def test_a_first_seen_process_cannot_be_charged_more_than_the_interval():
    '''Cap it, so something that somehow predates the sample is not billed for
    its whole lifetime the way `ps` would.'''
    after = sample(p1=('julia', 10_000_000))
    assert foreign_cpu_percent({}, after, 10, clock_ticks=TICKS) == pytest.approx(100.0)


def test_a_recycled_pid_is_treated_as_a_new_process():
    '''Differencing against the old occupant would produce a negative or
    nonsensical delta, so it is charged its own CPU like any first sighting.'''
    before = sample(p1=('julia', 5_000))
    after = sample(p1=('perl', 10))          # same pid, different process
    assert foreign_cpu_percent(before, after, 10, clock_ticks=TICKS) == pytest.approx(1.0)


def test_zero_or_negative_interval_is_not_divided_by():
    before = sample(p1=('julia', 0))
    after = sample(p1=('julia', 500))
    assert foreign_cpu_percent(before, after, 0, clock_ticks=TICKS) == 0


def test_top_foreign_is_ordered_and_limited():
    before = sample(p1=('julia', 0), p2=('matlab', 0), p3=('R', 0))
    after = sample(p1=('julia', 300 * TICKS), p2=('matlab', 100 * TICKS),
                   p3=('R', 200 * TICKS))
    top = top_foreign(before, after, 100, limit=2, clock_ticks=TICKS)
    assert [comm for _, comm in top] == ['julia', 'R']


def test_extra_allowed_processes_are_excluded():
    before = sample(p1=('julia', 0))
    after = sample(p1=('julia', 500 * TICKS))
    assert foreign_cpu_percent(before, after, 10, extra_allowed=('julia',),
                               clock_ticks=TICKS) == 0


class TestParseProcStat:
    def test_reads_utime_and_stime(self):
        # fields: pid (comm) state ppid pgrp session tty tpgid flags
        #         minflt cminflt majflt cmajflt utime stime
        line = '42 (bgpd) S 1 42 42 0 -1 4194304 100 0 0 0 700 300 0 0'
        assert parse_proc_stat(line) == ('bgpd', '1', 1000)

    def test_command_containing_spaces_and_parens(self):
        '''comm is not split on, because a real one can contain both.'''
        line = '7 (my (odd) proc) S 1 7 7 0 -1 0 0 0 0 0 5 5 0 0'
        assert parse_proc_stat(line) == ('my (odd) proc', '1', 10)

    def test_kernel_threads_are_skipped(self):
        '''ksoftirqd and kworker do the benchmark's *own* veth and bridge
        softirq work, so charging them would put competition on the row of a
        machine nobody else is using.'''
        # flags field carries PF_KTHREAD (0x00200000 = 2097152)
        line = '9 (ksoftirqd/0) S 2 0 0 0 -1 2129473 0 0 0 0 500 500 0 0'
        assert parse_proc_stat(line) is None
        assert parse_proc_stat(line, skip_kernel_threads=False) == ('ksoftirqd/0', '2', 1000)

    def test_userspace_process_with_other_flags_is_kept(self):
        line = '42 (julia) S 1 42 42 0 -1 4194304 0 0 0 0 700 300 0 0'
        assert parse_proc_stat(line) == ('julia', '1', 1000)

    @pytest.mark.parametrize('line', ['', 'garbage', '42 (bgpd) S 1 2', '42 bgpd S'])
    def test_unparsable_lines_return_none_rather_than_raise(self, line):
        '''Processes exit while being read; one race must not end the run's
        contention record.'''
        assert parse_proc_stat(line) is None


def test_sample_processes_reads_the_real_proc(tmp_path):
    '''Smoke test against a fake /proc, plus the real one.'''
    pid_dir = tmp_path / '123'
    pid_dir.mkdir()
    (pid_dir / 'stat').write_text('123 (julia) S 1 1 1 0 -1 0 0 0 0 0 10 5 0 0')
    (tmp_path / 'not-a-pid').mkdir()
    assert sample_processes(str(tmp_path)) == {'123': ('julia', '1', 15)}

    real = sample_processes()
    assert real, 'reading /proc produced nothing'
    assert all(isinstance(v, tuple) and len(v) == 3 for v in real.values())


def test_missing_proc_root_is_not_fatal():
    assert sample_processes('/nonexistent-proc') == {}


class TestOwnProcessTree:
    '''bgperf2's own Python cannot be recognised by name -- somebody else's
    `python3 train.py` looks identical -- so it is excluded by descent.
    '''

    def tree_sample(self):
        # 100 is bgperf2; it spawned 200 (mpstat) which spawned 300.
        # 900 is an unrelated job that happens to also be python3.
        return {
            '100': ('python3', '1', 0),
            '200': ('mpstat', '100', 0),
            '300': ('sh', '200', 0),
            '900': ('python3', '1', 0),
        }

    def test_collects_descendants(self):
        assert own_process_tree(self.tree_sample(), root_pid=100) == {'100', '200', '300'}

    def test_someone_elses_python_is_not_ours(self):
        assert '900' not in own_process_tree(self.tree_sample(), root_pid=100)

    def test_a_neighbouring_python_job_is_counted_as_contention(self):
        '''The hole that made the whole feature lie: with `python3` in the
        allowlist, an eight-core `python3 train.py` was filtered out and the
        row recorded a clean 0.
        '''
        before = {'900': ('python3', '1', 0), '100': ('python3', '1', 0)}
        after = {'900': ('python3', '1', 8 * TICKS * 10),   # 8 cores for 10s
                 '100': ('python3', '1', 5 * TICKS * 10)}   # bgperf2 itself
        own = own_process_tree(after, root_pid=100)
        pct = foreign_cpu_percent(before, after, 10, clock_ticks=TICKS, own_pids=own)
        assert pct == pytest.approx(800.0)

        complaint = describe_contention(before, after, 10, clock_ticks=TICKS, own_pids=own)
        assert 'python3' in complaint and '8.0 cores' in complaint

    def test_cycles_do_not_hang(self):
        '''A pid whose parent is itself must not loop forever.'''
        looped = {'5': ('a', '5', 0), '6': ('b', '5', 0)}
        assert own_process_tree(looped, root_pid=5) == {'5', '6'}
