# Termination detection

When a run is CONVERGED, when it is FAILED, and the five rules that were each broken once.

**Read this before editing:** `convergence.py`, `bgperf2.py` (the monitor loop that feeds `update()`)

These are invariants, not background: every rule here was written because the obvious alternative was tried and published a wrong number quietly. `CLAUDE.md` carries the one-line index; this file carries the argument.

---

## Termination detection

Lives in `convergence.py` as `ConvergenceTracker`, deliberately separated from `bench()`'s container
plumbing so the rules are testable without Docker (`tests/test_convergence.py`).

The naive check ("stop when received == expected") only works for synthetic prefix generation. With
MRT playback the total unique prefix count is unknown (peers' tables overlap), and with filtering
enabled the accepted count is deliberately lower than what was sent. So the tracker instead waits for
the count to go *stable*: `ASSURANCE_SAMPLES` (20) without change, or 5 if the configured checkpoint
was already hit. Those trailing samples are subtracted from the reported elapsed time afterward.

It also detects failure: a count that stops moving for `STUCK_SAMPLES` (600), a drop of >1% sustained
over 10 samples, or nothing arriving at all within 15s. `bench()` feeds it one sample per monitor
poll via `update()` and acts on the returned status; `note_neighbors_checkpoint()` is called from the
target branch when every neighbor has finished sending.

Three rules here are load-bearing and were each broken at some point. Any change to `update()`
should be checked against all of them:

1. **Stability is tracked on every sample, including ones below the peak.** It used to sit behind
   the regression branch, so a count that came to rest under an earlier peak by *less than*
   `DROP_FRACTION` advanced neither the stability counter nor the stuck counter: the run could
   neither converge nor fail, and polled forever with the target idle. Every one of the four FRR
   MRT runs settles 0.07–0.43% below its peak, so this hung the entire FRR test, not an edge case.
2. **Regression is measured against the high-water mark, not the previous sample** — otherwise a
   count resting below its peak compares equal to the sample before it and a real slide is missed.
3. **A count sitting more than `DROP_FRACTION` below its peak must not be reported CONVERGED**,
   however steady it looks. Every real run reaches the neighbor checkpoint, which shortens the
   assurance window to 5 samples — fewer than the 10 the regression streak needs — so without that
   gate a run that lost half its routes and held there was reported CONVERGED at sample 6, with the
   loss visible only as a low `received` column. None of the original drop tests set the
   checkpoint, so this was uncovered; `test_a_big_drop_still_fails_once_the_checkpoint_is_set`
   pins it now.

Both halves of the regression rule apply to the same samples: the streak counts only samples that
are themselves past `DROP_FRACTION`. If sub-threshold wobble armed the streak instead, one later
sample past the threshold would fail the run instantly.

**A fourth rule reads the second witness, and it is what made 10-injector MRT runs reproducible.**
`update()` optionally takes the target's own table gauge -- `best_paths`, the count of distinct
prefixes the target holds, described in `docs/invariants/target-state.md` -- beside each monitor
sample: **a
monitor decline past `DROP_FRACTION` is not route loss while the target's own `best_paths` is
within `DROP_FRACTION` of its peak.** The monitor counts what the target re-advertises to one
session; `best_paths` counts what it holds, and a genuine loss takes both down together -- so the
same constant serves both counts and nothing is fitted to one RIB. Measured over eight
10 x 1,050,000 runs: monitor declines of 1.18%-1.76% against a target that was 0.00%-0.19% below
its own peak on the samples excused. Before it, 4 of 5 runs of `2026-calibration-mrt.yaml` failed
and `summary.py` published `0 of 3 passes observed`; after it, 5 of 5 single runs converged.

- **It applies to the drop streak *and* to the convergence gate.** Excusing the samples only keeps
  such a run alive -- with the gate unchanged, a table settled 1.5% below its own transient peak
  polls on to `STUCK_SAMPLES` and fails anyway.
- **Four things do not attest**: a withheld sum (`None` -- what a peering still coming up or a
  partial read gives), a reading with no timestamp, a reading carried for `WITNESS_CARRY_SAMPLES`
  monitor samples without being re-read, and a target that holds nothing and never held anything.
  The carry bound is `ASSURANCE_SAMPLES_AFTER_CHECKPOINT` and it bounds how long such a reading
  keeps a run *alive*, nothing about the verdict: a target poll thread that dies (`bgperf2-sl1`)
  freezes the witness, and that has now been seen for real -- a batch pass whose target container
  vanished excused a "100% export change" for three samples before the bound cut it off. The run
  still failed. **A CONVERGED verdict separately requires a reading taken on the deciding sample**,
  because a witness that freezes partway through the assurance window is still inside the carry
  bound when the window closes; that costs at most one poll, since the count is flat by then.
- **A run the witness alone is keeping alive still ends**, after `WITNESS_EXCUSED_LIMIT`
  (= `STUCK_SAMPLES`) consecutive excused samples, and the message names the witness. A count that
  declines a little on *every* sample resets the drop streak through the excuse and the stability
  counter through changing, so the first version of this rule left such a run with no terminating
  path at all -- and `bench()` has no run timeout, so under `batch()` that is the rest of the
  matrix.
- **A monitor count of zero never attests**, which is the rule that accident added. Zero is not a
  decline in what the target exports; it is the absence of the session every published timing is
  read from, which the target-side witness cannot see. Churn's "a collapsed count is not a
  withdrawal", from the other side of convergence.
- **The convergence gate additionally requires the sample's own `checked` flag.** A target holding
  its whole table is exactly what a *broken monitor session* looks like from the target's side, so
  without it this gate would report CONVERGED for a run whose monitor sat at zero -- the case the
  gate was added for, reached from the other side. The cost is stated rather than hidden: a run
  whose monitor never reaches the check-point (a filtered run) cannot be carried by the witness,
  and a monitor that stops seeing the run is failed as stuck rather than as a drop.
- **Nothing in the CSV moves**, and `MSG` is left alone: `elapsed (s)` is still the monitor's
  convergence in every row. What the rule did is printed once beside the run and published as
  `target_table.witness_rule` -- and only when it did something, so a run it never touched writes
  the document it always wrote.
- `tests/test_convergence_mrt_replay.py` replays the four recorded runs and pins that the monitor
  alone fails three of them, that all four converge once the target is asked, and that the same
  series with the target's own count falling still fails. `results/` is gitignored, so the series
  lives in the test.

**A fifth rule says which witnesses may end a run, and it is the one that failed a finished run for
half an hour.** The target's own per-neighbour counters exist to **shorten** the assurance window
from `ASSURANCE_SAMPLES` (20) to `ASSURANCE_SAMPLES_AFTER_CHECKPOINT` (5); they are not what makes
convergence possible. The gate required `neighbors_checkpoint` outright, so a target that delivered
its whole table — with the monitor confirming it — had no terminating path but `STUCK_SAMPLES`.

Measured: Block 2 of the timing campaign, `rustybgp default` at 50 × 100,000. The monitor reached the
check-point at 137.34s holding 5,000,000 against a required 4,950,000, the run polled on for a
further ~2,000 seconds, and it was failed as `stuck received count 5000000 neighbors_checked 16` —
`elapsed (s)` 2194 for a run that had finished at 137. RustyBGP reported ≥ 100,000 accepted for 16 of
its 50 peers while demonstrably holding the whole table.

This is the BIRD 3 defect one layer on. BIRD 3 reported `accepted` 0 for every neighbour, which
killed one route to the checkpoint *quietly* — those runs still converged through
`neighbors_received_full`. Here both routes are dead at once, and a gate with one input fails the
run rather than waiting longer.

- **Either checkpoint opens the gate; neither being set does not.** `recved_checkpoint` is the
  monitor having actually reached the configured count, so a target that never delivered still has
  neither witness and still fails. Nothing converges a run on stability alone — a target parked at a
  tenth of its table is exactly as steady as one that finished.
- **The short window needs both witnesses.** `assurance_samples` keyed on `recved_checkpoint` alone,
  which was harmless only because the gate separately required the other one: a run with a single
  witness could not converge at all, so the window it would have used never came up. Twenty samples
  is the price of one account of the run, and five is what a second account buys.
- **The looser gate does not weaken the zero-monitor case.** The drop branch still requires this
  sample's own `checked`, and a collapsed session is not at or above the check-point, so a run whose
  monitor went to zero while the target held everything is still failed rather than converged.
- **A run decided on one witness says so**, in the artifact's top-level `convergence_rule`, absent
  for every run that had both. Nothing in the stats row can carry it: `elapsed (s)` is the monitor's
  convergence either way, so a run decided on one account of itself is otherwise indistinguishable
  afterwards from one decided on two. **Top-level and not under `target_table`**, which exists only
  for a daemon that reports a table witness — BIRD and FRR. Filed there it was dropped for every
  other daemon, RustyBGP included, which is the one this rule was written for: the run that provoked
  it would have published nothing at all about how it was decided.

- **A run with no neighbour reading at all still terminates**, which took a second change. The
  stability counter advanced only while `neighbors_checked` or `neighbors_received_full` was above
  zero, so a sampler that failed on its *first* read left both at zero for the whole run — and
  `STUCK_SAMPLES` keys on that same counter, so the run reached neither verdict and polled forever.
  With no bench timeout, under `batch()`, that is the rest of the matrix. `recved > 0` is the third
  way of knowing the run is under way; a count of zero is untouched, since
  `NO_PROGRESS_DEADLINE_SECONDS` already trips that. 16 of 50 peers reporting and 0 of 50 are the
  same defect, and the fix for one has to cover the other.

**What the looser gate costs, stated rather than hidden.** `recved_checkpoint` latches on the first
sample at or above the check-point and never clears, and the check-point is a fraction (99%, or 93%
for a GoBGP MRT run) of a *declared* total. So on a multi-generator run whose target never reports
its neighbours, the monitor's count can plateau — a late injector replaying prefixes that overlap
what is already in the table adds nothing to it — and twenty stable samples then end the run while
that injector is still sending. The old gate held such a run until every generator reported done.

Three things bound it. It reaches only targets whose per-neighbour counters are broken, since every
other run still gets `neighbors_checkpoint` and is decided exactly as before. The window is the full
twenty samples rather than the five a second witness buys, which is the reason the two constants were
separated. And the run says so: `convergence_rule` names it, and `tester_fleet`'s `injection_s` and
signed `post_injection_tail_s` are what a reader checks it against — a tail that is negative by more
than the poll gap is a run whose generators were still sending. Closing it properly means giving the
tracker the offering evidence, which it does not currently see; until then this paragraph is the
honest version.

One consequence worth stating: this makes `bgperf2-sl1` — a target poll thread that dies and freezes
the neighbour counts — cost a longer assurance window instead of the whole run, *provided* at least
one reading arrived. A sampler that never reads at all is the case the second change above covers.

