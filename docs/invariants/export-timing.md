# Asking the other end what it got

Export-side timing: what the receiver fan-out was served, and when.

**Read this before editing:** `bgperf2.py` (`controller_export_stats()`, `finish_bench()`), `monitor.py` (`Receiver`), `measurements.py` (`ExportEventRecorder`)

These are invariants, not background: every rule here was written because the obvious alternative was tried and published a wrong number quietly. `CLAUDE.md` carries the one-line index; this file carries the argument.

---

## Asking the other end what it got — export timing

`bench()` polls every receiver at the monitor's own cadence and publishes an
`export` section in `<prefix>.events.json`. Without it, **a `--receivers 20` run
and a `--receivers 0` run differ in exactly one published number** — `elapsed
(s)` — with whatever the fan-out cost the target inside it, indistinguishable
from a slow daemon. Ingress is measured at the generators and convergence at the
monitor; export was measured nowhere, which is the end-to-end collapse Phase 5A's
last work item is about.

`Receiver.accepted_prefixes()` is the read and it is deliberately not `stats()`,
which stays refused: `stats()` feeds the queue every published timing comes from,
and a receiver in it would be an unlabelled second `recved` series. This one
answers `controller_export_stats()`, which keeps it in `ExportEventRecorder` and
in a section of its own. `EventPhase.EXPORT` exists for the same reason one level
down — a reader grouping the stream by phase must not find several first-prefix
intervals under `convergence` with nothing saying which one the row describes.

- **The check-point is the run's own** (`conf['monitor']['check-points'][0]`),
  the same yardstick the monitor is judged by. Deriving one from what the monitor
  has seen so far would couple the two instruments, and the whole point of
  reading a receiver is that its answer does not depend on the monitor's. A
  policy that makes that count unreachable leaves the receivers incomplete
  exactly as it leaves `convergence_s` null.
- **One loop for the whole fan-out, not a thread per receiver.** A round reads
  each receiver in turn, so the controller is inside one container at a time.
  The alternative keeps the nominal cadence by putting N concurrent `docker
  exec`s on the host — and the run that wants this measurement is the one whose
  host is already loaded, so the instrument would become part of what it
  reports. A serialised round costs resolution instead, and the resolution is
  published: a 6-receiver 1M-prefix run measured a 3.8s round.
- **Every receiver in a round shares the round's timestamp, and the cost of that
  is bounded rather than hidden.** A round takes real time, so a receiver read
  late in it is dated to the round's start and can appear to reach a state up to
  one round-gap before one read early in it — which is what the 6-receiver run
  showed. That gap *is* each event's `poll_resolution_s`, and `export_spread_s`
  is compared against the wider of the two bounding it, so a fan-out served
  simultaneously can be off by at most one gap and can never be published as a
  *resolved* spread. Verified: spread 3.849s against resolution 3.849s, printed
  as "within the poll resolution of each other".
- **The fan-out is served when its *slowest* receiver has the table**, and one
  receiver that never got there leaves every fleet interval null with its name
  in `incomplete_receivers` — `tester_fleet_metrics()`'s all-or-nothing rule,
  reached from the export side. The export *start* is gated separately: a
  fan-out where every session was seen taking prefixes and one never finished
  has a real start, and that is exactly the run where a reader wants it.
- **Every configured receiver appears in every round**, with `None` where the
  read failed — the generator poll's rule, and here it is what stops the
  receivers that happen to answer from satisfying "the whole fan-out has the
  table". A failed read does not erase what that receiver was already seen
  holding; the last count read from each is published as `accepted_prefixes`,
  which is the only thing that says how far a receiver that never finished got.
- **`monitor_delta_s` is signed**, for the reason `post_injection_tail_s` is: the
  monitor is one export session among several and nothing orders them, so a
  receiver reaching the table first is ordinary. It is deliberately measured
  against the monitor rather than against the generators — a generator-relative
  export tail is `post_injection_tail_s + monitor_delta_s`, and publishing it
  here would repeat `tester_fleet_metrics()`'s completion rule in a second place
  where the two could drift apart.
- **The poll ends itself once every receiver holds the table**, since a round
  cannot be batched: continuing to convergence spends an exec per receiver per
  second on sessions with nothing left to say. That load is invisible to
  `max foreign cpu %` — not because it is bgperf2's own process tree (the read
  runs *inside* the receiver container, where `own_process_tree()` does not
  reach), but because `gobgp` is in `contention.BGPERF_PROCESSES`, the by-name
  allowlist, exactly as `birdc` is. A poll whose CLI were *not* in that
  frozenset would be charged to that column as somebody else's load. It is
  also why **every** round waits at least as long as it took
  (`EXPORT_POLL_MAX_DUTY`), not only one that overran the cadence: four
  receivers at a 200ms read give a 0.8s round inside a 1s cadence, 80% of the
  window spent inside containers without ever tripping an overrun. The
  instrument runs inside the window it measures, nothing bounds the receiver
  count, and it may never spend more than half its time inside containers. The
  cost is resolution — the 6-receiver run's 3.8s rounds now publish a 7.1s gap
  — and every interval publishes the resolution that bounds it. Nothing is
  lost: both events are recorded on or before the round that satisfies the
  rule, in that round rather than queued for someone else to record.
- **The poll takes one closing round when the window shuts.** The gap between
  rounds is wider than the window that follows the check-point: at six
  receivers it is a round plus its floor, against the five monitor polls
  between the check-point and convergence. Ending on the stop event without a
  last look would publish a fan-out served in that gap as one that was never
  served — the same false conclusion review found for the churn case, reached
  from the other side. The closing read is stamped when it is taken and carries
  the gap since the previous round as its resolution, which is the honest
  statement of when it could have happened. `finish_bench()` waits for it after
  the clock has stopped, for `EXPORT_POLL_TEARDOWN_WAIT_S` plus an allowance
  per receiver, since a flat wait long enough for six expires on fifty.
- **Export timing and a post-convergence workload are not measured in the same
  run**, and that is the settled answer rather than a gap. The poll's window
  closes at convergence, which is exactly where churn and the reload begin, so
  every way of making them coexist costs something published: letting the poll
  run on puts N `docker exec`s inside a burst's 1.0s-resolution withdrawal and
  the reload's CPU interval; waiting for it puts that wait inside `total time`
  — a graphed column, moving with the *instrument's* fan-out — and leaves the
  workload's recorder dating its first sample across the wait, so a withdrawal
  resolved to a second is published as "within the 25.0s poll resolution".
  Eight rounds of review found that seam from five different sides. A run that
  asks for both keeps the fan-out — the receivers exist, hold the table and
  cost the target its export work — and withholds the *timing* by name, on the
  rule `--prefix-scope total` under `--path-diversity` and churn beside a
  reload already follow. Choosing an order and paying for it is its own change
  set.
- **The window is the delivery of the table**, closing at convergence — the
  same window `elapsed (s)`, `max cpu %` and `max mem (GB)` describe. It closes
  there because the run does: nothing waits for the fan-out afterwards, and a
  wait that grew with the receiver count would land inside `total time`. A
  receiver not served by then is reported incomplete with the count it last
  held, and the printed line names the window, because "2 of 3" alone reads as
  a broken session. **`monitor_delta_s`'s positive side is bounded by that
  window** — convergence is 5 polls past the check-point, so a fan-out slower
  than that is reported incomplete rather than as a large lag, and what
  separates that from a stalled session is each receiver's `accepted_prefixes`.
  Giving the positive side a bound would mean a post-convergence phase that
  waits for the fan-out: a separate decision, like `total` under
  `--path-diversity`. The stop event is per run and never cleared, unlike
  `controller_stop`, so a round still in flight at the end of a batch cell
  cannot find that event clear again at the start of the next one.
- **This is the one sampler that does not go through the run's queue**, and the
  reason is that nothing would reliably take its messages out again: `bench()`'s
  monitor loop stops the instant convergence is declared, and `run_churn_bursts()`
  and `run_policy_reload()` read that queue afterwards and skip anything that is
  not a monitor sample. A round completing near the end of a run — and a round
  takes seconds at the fan-out sizes this measures — would be queued and never
  observed, publishing a receiver that had been served as one that never was,
  with the previous round's stale count beside it. The poll thread is its
  recorder's only writer instead, and `finish_bench()` waits
  `EXPORT_POLL_TEARDOWN_WAIT_S` for a round still in flight before reading it —
  **after** `bench_stop`, on the rule the tester log scan follows, so a wait
  that grows with the receiver count cannot reach `total time`.
- **Nothing about the CSV moves.** `elapsed (s)` is the monitor's convergence and
  must keep meaning that in every row; what the fan-out cost is printed beside
  the row and published in the artifact, on churn's and the reload's rule. A run
  with no receivers keeps exactly the document it has always produced. A run
  that *had* receivers and could not measure them — the check-point is 99% of
  the table, so `-p 1` gives 0, and a threshold of 0 would stamp every receiver
  complete on the first round — publishes an `unmeasured_reason` instead:
  absent is what an older build wrote, so silence could not be told from a
  build that never took the measurement.

**What still cannot be separated is table selection.** With this in place a run
decomposes into ingress (measured at the generators), the target's own work, and
export (measured at the receivers) — but best-path selection happens inside the
target and the only external observable is when a session sees the result. No
daemon-agnostic instrument can split it out of the target-side interval, so it is
stated here rather than implied by an interval that quietly contains it.
