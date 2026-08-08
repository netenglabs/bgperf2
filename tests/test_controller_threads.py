'''The controller sampling threads have to stop when a run ends.

batch() calls bench() in-process once per cell, so a thread that never exits is
not a tidiness problem: a 40-run batch would finish with 40 mpstat loops, 40
`free` loops and 40 `ps` loops still polling, and bgperf would be generating the
very host contention it reports. finish_bench() used to assign a module-level
bool without `global`, which made the assignment a no-op and left every thread
running for the life of the process.

Only the `ps`-based sampler is exercised here -- `free` and `mpstat` add an
external dependency without testing anything different about the shutdown path.
'''
import queue
import threading
import time

import bgperf2


def test_foreign_cpu_thread_samples_then_stops():
    q = queue.Queue()
    before = threading.active_count()

    bgperf2.controller_stop.clear()
    bgperf2.controller_foreign_cpu(q, interval=0.05)

    deadline = time.time() + 5
    while q.empty() and time.time() < deadline:
        time.sleep(0.01)
    assert not q.empty(), 'sampler produced nothing'

    sample = q.get()
    assert sample['who'] == 'controller'
    assert 'foreign_cpu' in sample

    bgperf2.controller_stop.set()
    deadline = time.time() + 5
    while threading.active_count() > before and time.time() < deadline:
        time.sleep(0.01)
    assert threading.active_count() == before, 'sampler thread outlived the run'


def test_a_second_run_gets_a_working_sampler():
    '''The stop flag is cleared per run, so run N+1 still collects samples.

    A flag that is only ever set would leave every later cell of a batch with a
    sampler that exits immediately and a contention column stuck at 0.
    '''
    before = threading.active_count()
    bgperf2.controller_stop.set()          # as finish_bench() leaves it

    q = queue.Queue()
    bgperf2.controller_stop.clear()        # as bench() does on the next run
    bgperf2.controller_foreign_cpu(q, interval=0.05)

    deadline = time.time() + 5
    while q.empty() and time.time() < deadline:
        time.sleep(0.01)
    assert not q.empty(), 'second run collected no samples'

    bgperf2.controller_stop.set()
    deadline = time.time() + 5
    while threading.active_count() > before and time.time() < deadline:
        time.sleep(0.01)
