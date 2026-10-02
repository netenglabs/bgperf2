'''Per-role CPU from each container's cgroup (comparison plan Phase 4 item 1).

The rules under test are the ones that keep the series honest: CPU is a delta
between two reads, never a cumulative reading; a role's interval is published
only when every member was read at both ends; an unread member, a counter
that went backwards and a role that could not be resolved are each said, never
summed around; and the section changes no verdict.
'''
import threading
import time

import bgperf2
import findings
import measurements
import role_cpu
from role_cpu import RoleCpuRecorder


def member(name, cpuset='0-7'):
    return {'name': name, 'cgroup_dir': '/cg/' + name,
            'cpuset_requested': cpuset, 'cpuset_effective': cpuset}


def test_parse_cpu_stat_reads_usage_usec():
    text = 'usage_usec 26283\nuser_usec 19427\nsystem_usec 6856\n'
    assert role_cpu.parse_cpu_stat(text) == 26283
    assert role_cpu.parse_cpu_stat('user_usec 5\n') is None


def test_cgroup_v2_path_and_v1_refusal():
    assert role_cpu.cgroup_v2_path(
        '0::/system.slice/docker-abc.scope\n') == '/system.slice/docker-abc.scope'
    v1 = '12:cpu,cpuacct:/docker/abc\n0::/\n'
    assert role_cpu.cgroup_v2_path(v1) == '/'
    assert role_cpu.cgroup_v2_path('12:cpu,cpuacct:/docker/abc\n') is None


def test_cgroup_dir_for_pid_reads_through_proc(tmp_path):
    proc = tmp_path / 'proc' / '42'
    proc.mkdir(parents=True)
    (proc / 'cgroup').write_text('0::/system.slice/docker-abc.scope\n')
    cg = tmp_path / 'cg' / 'system.slice' / 'docker-abc.scope'
    cg.mkdir(parents=True)
    (cg / 'cpu.stat').write_text('usage_usec 1000\n')
    (cg / 'cpuset.cpus.effective').write_text('0-7\n')
    path = role_cpu.cgroup_dir_for_pid(42, proc_root=str(tmp_path / 'proc'),
                                       cgroup_root=str(tmp_path / 'cg'))
    assert path == str(cg)
    assert role_cpu.read_usage_usec(path) == 1000
    assert role_cpu.read_effective_cpuset(path) == '0-7'


def test_missing_usage_is_an_error_never_zero(tmp_path):
    (tmp_path / 'cpu.stat').write_text('user_usec 5\n')
    try:
        role_cpu.read_usage_usec(str(tmp_path))
    except ValueError:
        pass
    else:
        raise AssertionError('a cpu.stat with no usage_usec read as a value')


def test_cpuset_size():
    assert role_cpu.cpuset_size('0-7') == 8
    assert role_cpu.cpuset_size('0-7,10,12-13') == 11
    assert role_cpu.cpuset_size(None) is None
    assert role_cpu.cpuset_size('x') is None


def test_cpu_is_a_delta_summed_over_the_role():
    rec = RoleCpuRecorder(100.0, {'testers': [member('t0'), member('t1')]})
    # Large cumulative values from before the run must not leak in.
    rec.observe(100.0, {'t0': 9_000_000, 't1': 5_000_000})
    rec.observe(102.0, {'t0': 10_000_000, 't1': 6_000_000})
    testers = rec.section()['roles']['testers']
    [interval] = testers['intervals']
    assert interval == {'start_s': 0.0, 'end_s': 2.0, 'cpu_percent': 100.0}
    assert testers['peak_cpu_percent'] == 100.0
    assert testers['cpu_seconds'] == 2.0
    assert testers['cores'] == 8
    assert testers['pinned'] is True


def test_a_role_missing_one_member_is_unread_not_smaller():
    rec = RoleCpuRecorder(0.0, {'testers': [member('t0'), member('t1')]})
    rec.observe(0.0, {'t0': 0, 't1': 0})
    rec.observe(1.0, {'t0': 500_000}, {'t1': 'FileNotFoundError: gone'})
    rec.observe(2.0, {'t0': 1_000_000, 't1': 900_000})
    testers = rec.section()['roles']['testers']
    first, second = testers['intervals']
    assert first['cpu_percent'] is None and first['unread'] == ['t1']
    assert second['cpu_percent'] is None and second['unread'] == ['t1']
    assert testers['intervals_unread'] == 2
    assert testers['peak_cpu_percent'] is None
    # The window total would charge t1 for less of the run than t0.
    assert testers['cpu_seconds'] is None
    assert testers['containers'][1]['first_error'] == 'FileNotFoundError: gone'


def test_a_counter_that_went_backwards_is_not_negative_work():
    rec = RoleCpuRecorder(0.0, {'target': [member('tgt')]})
    rec.observe(0.0, {'tgt': 5_000_000})
    rec.observe(1.0, {'tgt': 1_000})
    [interval] = rec.section()['roles']['target']['intervals']
    assert interval['cpu_percent'] is None
    assert 'backwards' in interval['unread_reason']


def test_unpinned_and_unmeasured_roles_are_stated():
    rec = RoleCpuRecorder(0.0, {'monitor': [member('mon', cpuset=None)]},
                          unmeasured={'target': 'the target is remote'})
    rec.observe(0.0, {'mon': 0})
    rec.observe(1.0, {'mon': 250_000})
    roles = rec.section()['roles']
    assert roles['target'] == {'unmeasured_reason': 'the target is remote'}
    assert roles['monitor']['pinned'] is False
    assert roles['monitor']['intervals'][0]['cpu_percent'] == 25.0
    # A role this run never had is absent, not unmeasured.
    assert 'receivers' not in roles


def test_section_states_its_clock_and_unit():
    section = RoleCpuRecorder(0.0, {}).section()
    assert section['clock'] == 'monotonic'
    assert section['origin'] == 'bench_clock_started'
    assert section['unit'] == 'percent of one core'
    assert section['roles'] == {}


def test_poll_thread_samples_stamps_before_read_and_stops():
    reads = []

    def reader(members):
        reads.append(time.monotonic())
        return {'tgt': int(len(reads) * 100_000)}, {}

    rec = RoleCpuRecorder(time.monotonic(), {'target': [member('tgt')]},
                          interval_s=0.02)
    stop = threading.Event()
    t = bgperf2.controller_role_cpu(rec, stop, interval=0.02, reader=reader)
    deadline = time.time() + 5
    while len(reads) < 3 and time.time() < deadline:
        time.sleep(0.01)
    stop.set()
    t.join(timeout=5)
    assert not t.is_alive(), 'the cgroup poll outlived its stop'
    intervals = rec.section()['roles']['target']['intervals']
    assert len(intervals) >= 2
    assert all(i['cpu_percent'] is not None for i in intervals)
    # The published resolution is the gap achieved, never the one asked for.
    assert all(i['end_s'] > i['start_s'] for i in intervals)


def test_a_reader_that_raises_marks_the_pass_unread():
    def reader(members):
        raise OSError('cgroup filesystem went away')

    rec = RoleCpuRecorder(0.0, {'target': [member('tgt')]})
    stop = threading.Event()
    stop.set()  # one pass, then stop
    bgperf2.controller_role_cpu(rec, stop, reader=reader).join(timeout=5)
    target = rec.section()['roles']['target']
    assert 'cgroup filesystem went away' in target['containers'][0]['first_error']


def test_event_artifact_carries_role_cpu_only_when_supplied():
    events = measurements.MonitorEventRecorder(0.0).events
    plain = measurements.event_artifact(events, 'failed')
    assert 'role_cpu' not in plain
    rec = RoleCpuRecorder(0.0, {'target': [member('tgt')]})
    doc = measurements.event_artifact(events, 'failed',
                                      role_cpu=rec.section())
    assert doc['role_cpu']['roles']['target']['intervals'] == []


def test_findings_do_not_read_role_cpu():
    # Phase 4 item 1 publishes the series and changes no verdict.
    import inspect
    assert 'role_cpu' not in inspect.getsource(findings)
