# What the run was waiting for

The only thing allowed to name a limiting component, and the six rules that stop it guessing.

**Read this before editing:** `findings.py`, `bgperf2.py` (`write_event_artifact()`)

These are invariants, not background: every rule here was written because the obvious alternative was tried and published a wrong number quietly. `CLAUDE.md` carries the one-line index; this file carries the argument.

---

## What the run was waiting for — `findings.py`

The intervals in `docs/invariants/tester-offering.md` and `docs/invariants/export-timing.md`
exist to answer one question, and `findings.py` is the only
thing allowed to answer it. It derives a `findings` section into every
`<prefix>.events.json` and prints its verdict as the last line of a run. Pure
and Docker-free like `contention.py`, `convergence.py` and `churn.py`, and it reads the
*artifact* rather than the event stream, so it cannot reason about a duration
the artifact did not publish.

`limiting_component` is `tester`, `target_or_monitor`, `unresolved`, or
`inconclusive`, and the last two are not the same refusal: `inconclusive` means
the deciding measurement was never made (no generator that can be asked, a
generator that never completed, a monitor that never reached the check-point),
`unresolved` means it was made and something forbids attributing it. Collapsing
them hides which one the operator can do something about. Each finding carries
the rule it applied (`policy`) and the durations it applied it to (`evidence`),
because a verdict that cannot be argued with is a validity boolean with extra
words.

Six rules hold the thing up:

- **Half the offered table must cross the measured interval before that
  interval may be read as the generator's send** — or the generator must have
  timed its own send. This is what keeps a queue-side counter from becoming a
  verdict *without the policy having to know which generator produced it*. BIRD
  2.19 puts between 0 and ~15% of its table inside that interval depending only
  on where the first poll landed, so it fails both tests and the run is
  `unresolved` with `injection_boundary_unresolved` — including its large
  positive tail, which would otherwise be charged to the target while the
  generator was still draining its sessions. An MRT injector fails the first
  test and passes the second, so a 10,000-prefix walk that is over before the
  first poll can still show a target tail.
- **A confounder withholds the verdict, not the evidence.** A tester-limited
  run on a saturated host still publishes the `tester_limited` finding and
  reports `unresolved`, naming host saturation as what decided it. `min idle%`
  is host-wide and includes bgperf2's own load, so it says the machine had
  nothing spare and not whose work that was — per-role, time-aligned CPU is
  what would say more, and it does not exist.
- **Backpressure names no component, and only the counts of *being blocked*
  qualify.** BIRD 3 reports `TX pending` bytes at every poll and a session with
  something queued is what a working session looks like, so reading queue depth
  as backpressure would withhold every BIRD 3 verdict there is. Only
  `max_blocked_writes` and `max_send_stalls` are read, and which end of a
  blocked write was at fault is not in those numbers.
- **An unsampled minimum is not a measurement.** `min_free` starts at a
  sentinel above every real value so the first sample can only lower it; a run
  whose memory sampler never fired would otherwise publish a machine with a
  petabyte free. `host_evidence()` maps it back to `None`.
- **Tester log errors and timeouts are deliberately not inputs.**
  `finish_bench()` writes the artifact *before* scanning those logs, on purpose,
  and a finding is worth less than the atomic write of the evidence it would be
  derived from.
- **A policy that raises costs the verdict, not the evidence.**
  `write_event_artifact()` catches: by the time the findings run, that document
  is the only record a converged run happened, and the failure is published in
  the shape of a verdict (`inconclusive`, naming the exception) rather than as
  an absent section that would read as a run with nothing to say.

`docs/measurement-dictionary.md` lists every finding and when it fires.
