"""Discard only messages already excluded from BIRD tester health."""
import os
import select
import shutil
import subprocess
import time
import pytest

from tester import BIRD_LOG_FILTER, BIRDTester, _is_bird_protocol_error

pytestmark = pytest.mark.skipif(shutil.which('gawk') is None,
                                reason='GNU awk required by the generator image')


def test_filter_preserves_health_counts_and_flushes_live_lines(tmp_path):
    lines = [
        '<INFO> Started', '<RMT> Invalid route 10.0.0.0/8 withdrawn',
        '<RMT> Bad NEXT_HOP attribute', '<RMT> Received: Cease',
        '<ERR> Invalid route configuration', '<WARN> NEXT_HOP unavailable',
    ]
    log = tmp_path / 'peer.log'
    with log.open('w') as output:
        process = subprocess.Popen(['gawk', BIRD_LOG_FILTER], stdin=subprocess.PIPE,
                                   stdout=output, text=True)
        try:
            process.communicate('\n'.join(lines * 10000) + '\n', timeout=10)
            assert process.returncode == 0
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
    retained = log.read_text().splitlines()
    assert retained == [lines[i] for _ in range(10000) for i in (0, 3, 4, 5)]
    assert BIRDTester.find_errors([str(tmp_path)]) == sum(
        _is_bird_protocol_error(line) for line in lines) * 10000


def test_live_flush_identity_and_partial_line_boundary():
    from contention import foreign_cpu_percent
    process = subprocess.Popen(['gawk', BIRD_LOG_FILTER], stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE)
    try:
        process.stdin.write(b'<RMT> Received: Cease\n')
        process.stdin.flush()
        assert select.select([process.stdout], [], [], 3)[0]
        assert process.stdout.readline() == b'<RMT> Received: Cease\n'
        comm = open(f'/proc/{process.pid}/comm').read().strip()
        assert comm == 'bgperf-bird-log'
        before = {str(process.pid): (comm, 1, 0), '900': ('gawk', 1, 0)}
        after = {str(process.pid): (comm, 1, 200), '900': ('gawk', 1, 200)}
        assert foreign_cpu_percent(before, after, 1, clock_ticks=100) == 200
        # EOF must not manufacture a newline that changes scanner acceptance.
        output, _ = process.communicate(b'<RMT> Invalid ro', timeout=3)
        assert output == b'<RMT> Invalid ro'
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def test_generated_startup_filters_before_disk_and_removes_fifo(tmp_path):
    # Execute the actual startup with a stand-in daemon that holds the FIFO
    # open after its launcher exits, just as daemonized BIRD does.
    tester = BIRDTester.__new__(BIRDTester)
    tester.host_dir = tester.guest_dir = str(tmp_path / 'work with spaces')
    work = tmp_path / 'work with spaces'
    work.mkdir()
    tester.conf = {'neighbors': {'p': {'router-id': '10.0.0.1'}}}
    fake = tmp_path / 'bird'
    fake.write_text('''#!/bin/bash
pipe="${2%.conf}.log.pipe"
exec 3>"$pipe"
printf '%s\\n' '<RMT> Invalid route 10.0.0.0/8 withdrawn' '<RMT> Received: Cease' >&3
''')
    fake.chmod(0o755)
    subprocess.run(['bash', '-c', tester.get_startup_cmd()], check=True,
                   env=dict(os.environ, PATH=str(tmp_path) + ':' + os.environ['PATH']),
                   timeout=5)
    # Wait for filter EOF instead of sleeping or assuming scheduler order.
    deadline = time.monotonic() + 3
    log = work / '10.0.0.1.log'
    while time.monotonic() < deadline:
        if log.exists() and '<RMT> Received: Cease\n' in log.read_text():
            break
        time.sleep(.01)
    assert log.read_text() == '<RMT> Received: Cease\n'
    assert not list(work.glob('*.pipe'))
