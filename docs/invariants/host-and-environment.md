# Host contention and the bench directory

Whether the machine was yours, and where the run is allowed to write.

**Read this before editing:** `contention.py`, `bgperf2.py` (`warn_if_machine_is_busy()`, `controller_foreign_cpu()`, `warn_if_log_dir_is_in_ram()`, `warn_if_log_dir_is_short_on_space()`, the controller threads)

These are invariants, not background: every rule here was written because the obvious alternative was tried and published a wrong number quietly. `CLAUDE.md` carries the one-line index; this file carries the argument.

---

## Host contention — `contention.py`

A benchmark sharing its machine reports numbers that look fine and are not comparable with
anything. The margins here are small enough that this decides results: FRR 8.5, 9.1 and 10.0
finished a 95s MRT run within **0.11s** of each other, so a competing job of a few cores invents a
version ranking out of nothing.

`contention.py` attributes busy CPU to processes outside `BGPERF_PROCESSES`. It is kept free of
Docker and privileges so the test suite covers it, like `convergence.py`. Two consumers:

- `warn_if_machine_is_busy()` names the offenders before the run starts. It is called **after**
  `remove_target_containers()`, not at the top of `bench()`: `batch()` reuses the process for every
  cell, so checking earlier sees the previous cell's own target daemon and blames it.
- `controller_foreign_cpu()` samples every 5s into the same queue as the other controller threads;
  `bench()` keeps the max and writes it as the **`max foreign cpu %`** column. The interval is a
  parameter so the tests can pass a short one — the first sample only arrives one interval in,
  because the measurement is a delta.

**The names travel with the number, and only ever together.** A confounder that withholds a verdict
has to be arguable, and for a while this one was not: four consecutive MRT calibration runs on this
host were withheld by "processes outside the benchmark used up to 1.1 cores" with nothing anywhere
saying which process, and by the time anyone looked it had exited. `foreign_cpu_report()` returns
the total and the heaviest commands from one pass, `note_foreign_cpu_sample()` replaces both or
neither — names from a different sample than the published peak are two moments reported as one —
and they reach `host_evidence()` and the finding's `evidence.processes`. Three details:

- **Aggregated by command, with a `process_count`.** The canonical competitor is a parallel build:
  thousands of sub-second `cc1` processes, none individually large. Ranked per pid that names three
  `cc1` at 1% each beside a total of 800%, which reads as though the names do not cover the number.
- **A peak whose competitors could not be named is still kept**, and publishes `null` rather than an
  empty list. Absent is also what an older build wrote, so an empty list would report both as a run
  that found nobody. Dropping the peak instead would understate the column that decides whether the
  row is comparable at all.
- **`findings.py` never re-derives them.** It reads the artifact, and the run that fires this
  finding is exactly the one whose competitor has since exited.

The identification that closed those four runs is worth keeping: **`python` on this host is
`venv/bin/python`, which is bgperf2 itself** — the system interpreter reports `python3`. A bare
`python` at one core is a *previous bgperf2 run that outlived its own bench* and is now competing
with the next one, which `own_process_tree()` cannot exclude because it is not a descendant. Check
for one before reading a contention number, and before starting a campaign block.

`min idle%` cannot replace this: bgperf's *own* daemons move it, so it cannot separate "the target
worked hard" from "something else was running."

**Measure CPU as a delta between two `/proc` samples, never `ps -eo pcpu`.** This was got wrong
first time round and the mistake is easy to repeat, because `ps` looks exactly like what you want.
It reports cputime divided by process *lifetime*, so it fails in both directions: a job that
finished an hour ago still reads high and condemns a clean run, and — the case the whole module
exists for — a long-lived process that starts burning four cores for a 95s run barely moves its
average. On a real box: alive 16821s, 1475s of CPU, reads 8.7%; four cores for 95s takes it to
about 11%, well under the one-core threshold. A lifetime average also barely moves within a run, so
sampling repeatedly and keeping the max adds nothing over sampling once.

Every daemon a target can run must be in `BGPERF_PROCESSES`, including the commercial NOSes
(`rpd`, `Bgp`, `sr_bgp_mgr`, …) and `flockd`. A missing name means that target's own load is
reported as contention and every one of its rows looks incomparable — the failure is silent and
looks like a real finding. cEOS and SR Linux run dozens of agents each and those lists are the
main ones, not complete.

Three more traps, each of which made the feature report a *clean* machine while it was busy — the
worst possible failure for something whose output is "0 means the machine was yours":

- **Never allowlist interpreters.** `python`, `python3`, `sh` and `bash` were in the list at first,
  and `/proc/<pid>/comm` for a script-driven workload is the interpreter — so a neighbouring
  `python3 train.py` on eight cores was filtered out entirely. bgperf2's own Python is excluded by
  PID via `own_process_tree()`, which walks descendants of `os.getpid()`.
- **Kernel threads are excluded** (`PF_KTHREAD`). The ones that appear during a run — `ksoftirqd`,
  `kworker` — are doing *the benchmark's own* veth and bridge softirq work.
- **A process with no baseline is charged, capped at the interval.** Skipping first-seen processes
  scored a fully saturated machine at 0, because a parallel build is thousands of sub-second `cc1`
  processes that never appear in two consecutive samples.

The column goes **before** the three provenance columns, not after: `test_provenance.py` requires
provenance to stay last, and every graph index in `create_batch_graphs()` points at a column before
either group, so both invariants hold.

**The controller threads must actually stop.** They are governed by the `controller_stop`
`threading.Event`: `bench()` clears it before starting the samplers, `finish_bench()` sets it. This
was previously a module-level bool that `finish_bench()` assigned *without* `global`, so the
assignment created a local and was a no-op — and since `batch()` calls `bench()` in-process once per
cell, a 40-run batch ended with 40 `mpstat` loops, 40 `free` loops and 40 `ps` loops still polling.
bgperf was manufacturing the contention it now reports, and it grew run over run, so later cells of
a long batch were quietly noisier than earlier ones. Two things follow: clearing the event at the
start of each run is required or every cell after the first gets a sampler that exits immediately
and a contention column stuck at 0, and the samplers wait on the event instead of `time.sleep()` so
they stop at once rather than lingering a poll interval. `tests/test_controller_threads.py` covers
both directions.

## The bench directory must not be in RAM

`-d/--dir` holds every role's config and logs, bind-mounted under it, and defaults to `/var/tmp` —
**not** `/tmp`, which is tmpfs on most systemd distros. A 50-peer 100k-prefix BIRD run wrote
**31GB** of tester logs there — half this machine's RAM — pulling the recorded `min free mem` from
56GB to **28.5GB** on a run whose target daemon used **0.56GB**. A published, graphed column was
measuring tester logging. The default stayed `/tmp` long after that was found, while every operator
contract and every doc told the operator to pass `-d /var/tmp/bgperf` — so the only runs that hit it
were the ones nobody had thought about, which is the wrong way round. (The contracts have since
moved on again, to `/data/bgperf-work`; the `-d` default stays `/var/tmp` because it must work on
any machine, so the gap between the default and the contract is permanent and is what
`warn_if_log_dir_is_in_ram()` and `warn_if_log_dir_is_short_on_space()` are for.)
`warn_if_log_dir_is_in_ram()` still runs at the start of every run, because `/var/tmp` is tmpfs on
some systems and `-d` can still name one; `is_memory_backed()` in `contention.py` is the pure part.

Moving off tmpfs traded that for a smaller failure, and `warn_if_log_dir_is_short_on_space()` covers
it: `/var/tmp` is on the **root** filesystem on most hosts, so a run that fills it takes Docker and
journald with it, hours into a batch, and what is lost is the finished cells' artifacts rather than
the current run. The floor is `LOG_SPACE_FLOOR_GB` (10) and is deliberately **not** an estimate of
the run in front of it: a 50-peer 100k-prefix BIRD run writes ~5GB of tester logs while a full-table
MRT run puts `bgpd.log` past 1GB, so those two ends differ by 30x and an estimate would have to know
what each generator logs. `free_space_bytes()` in `contention.py` is the pure part, and two details
in it decide whether the number means anything: it reads `f_bavail`, not `f_bfree` — the difference
is the reserve only root may use, and bgperf2 does not run as root — and it measures the nearest
**existing** ancestor, because `bench()` asks before it creates the directory, on purpose. A warning
about log volume is worth nothing once the logs are written.

Two things made it that large, and only one is fixed:

- The BIRD tester config used `log ... all`, which includes `trace` — every route event, ~7KB per
  prefix. It now names the classes `find_errors()` actually needs, about 6x less.
- What remains is `<RMT> Invalid route ... withdrawn`: the target re-advertises everything it
  learns back to the testers, which reject it. That is normal operation — `find_errors()` already
  excludes those lines — but they are class `remote`, which `find_errors()` needs, so they cannot be filtered
  out without blinding it. Stopping the target from exporting to testers would remove the noise but
  would also change the workload (no RIB-out to N peers), so it is left alone.
