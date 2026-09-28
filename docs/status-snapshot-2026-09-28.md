# Where everything stands — snapshot, 2026-09-28

**This is a dated snapshot, not a source of truth.** Every fact below is copied from a
document, a marker, a `bd` item or an artifact that owns it, and each claim names where it
came from. If this file and its source disagree, the source is right and this file is stale.
It exists to answer "where are we, across all of it" in one read; it is not a condensed
`CLAUDE.md` and must not grow into one (see `CLAUDE.md`'s opening section on why a second
copy fails silently).

Written on the campaign host: 16 vCPU / 61.44 GiB AMD EPYC 9R14 (`m7a.4xlarge`), EC2 spot,
only `/data` survives a reclaim.

---

## 0. Short term vs long term, and which is which

Both splits are already written down; they had just drifted apart. The
`docs/2026-memory-capacity-options.md` "Execution Order" is the authoritative one, and
**its first two steps are now done**:

| # | step | state |
|---|---|---|
| 1 | complete the measurement implementation release gate | **done** — Phase 6, 2026-09-08 |
| 2 | complete and review the bounded 64 GB timing validation campaign | **done** — Block 12 accepted 2026-09-15 |
| 3 | use its repeated memory/CPU/tester/monitor evidence to revise these envelopes | **not done — this is the live next step** |
| 4 | if larger hardware is available, calibrate one dimension at a time, keep the 20% guardrail | not started |
| 5 | prefer 256 GB durable / 128 GB cheapest / 384 GB only for cliff work | not started |

So we are at the boundary between the two: **the short-term programme is finished**, and
nothing in the long-term programme has begun.

### Short term — on this host, no hardware needed

1. **`bgperf2-5p6`** — pick the gate notification channel (yours to decide).
2. **`bgperf2-cqi`** — spend limit; the reset date has passed, so unattended step 6 can be
   verified with one command.
3. **Unattended step 7** — `atomic_write()` directory fsync, and route `write_provenance()`
   through it. Small, and it is what makes a spot reclaim cost one cell instead of a
   truncated artifact.
4. **`bgperf2-bgg`** — make `tester_limited` separable. This is the highest-value measurement
   work left and it is why §4b.1 no longer asks for a faster generator.
5. **`bgperf2-0ma`** — `-s/--single-table` is inert for BIRD and two published baseline rows
   claim otherwise. A wrong published row.
6. **Step 3 above** — check the campaign's three-pass memory numbers against the capacity
   envelopes. Cheap: it is a read, not a run. (First pass done in §4e below; the anchors hold.)

### Long term — needs new workloads, more hosts, or more RAM

- the four never-run workload families (withdrawals, incremental steady-state,
  route-server/RR, multi-host) — §4c;
- the larger-memory tiers — §4e, and the answer there is *not yet, and not RAM first*.

---

## 1. The four plans, in one line each

| plan | state | continuation prompt |
|---|---|---|
| `docs/2026-bgp-performance-test-plan.md` | **superseded/complete.** Produced the `2026-baseline` campaign; its >64 GB phases are retained as historical design only | `continue the 2026 benchmark campaign` (nothing left to run) |
| `docs/bgperf2-measurement-implementation-plan.md` | **all phases complete** (0, 1, 2, 3, 4, 5, 5A, 6 — last on 2026-09-08). Two P3 design questions still open under the Phase 5A epic | `continue the bgperf2 measurement implementation plan` |
| `docs/completed/2026-64gb-timing-validation-plan.md` | **complete and archived 2026-09-28.** Blocks 0–12 all carry `RAN` **and** `COMPLETE`; Block 12 (final report) built and accepted 2026-09-15 | the prompt now reports completion and starts nothing |
| `docs/unattended-execution-plan.md` | **steps 0–5 done; step 6 explicitly NOT met; step 7 not started** | `continue the unattended execution plan` |

`bd stats`: 75 issues total, 46 closed, **29 open, 0 in progress, 0 blocked**.

### 1a. Measurement implementation plan — detail

Status lines from the plan itself:

- Phase 0 (published contract) — complete 2026-08-20
- Phase 1 (typed lifecycle events, monotonic clocks) — complete 2026-08-20
- Phase 2 (BIRD synthetic tester instrumentation) — complete 2026-09-02
- Phase 3 (bgpdump2 MRT playback, per-injector readiness + provenance) — complete 2026-09-03
- Phase 4 (conservative bottleneck findings) — complete 2026-09-03
- Phase 5 (repetitions, stable cell identity, resume, order control) — complete 2026-09-03
- Phase 5A (BIRD architecture workload controls: peer scaling, path diversity, export
  fan-out, churn bursts, policy reload, export timing) — complete 2026-09-08
- Phase 6 (calibration + release gate) — complete 2026-09-08

Still open under `bgperf2-8gg.7` (the Phase 5A epic), both P3 design questions rather than
code debt:

- `bgperf2-8gg.7.7` — define export timing *beside* a post-convergence workload, or keep
  withholding it. Today a run asking for both keeps the fan-out and withholds the timing by
  name (`docs/invariants/export-timing.md`).
- `bgperf2-8gg.7.6` — define `--prefix-scope total` under `--path-diversity`, or keep
  refusing it.

### 1b. Timing validation campaign — detail

All markers present under `results/2026/2026-timing-validation/`:

| block | what | accepted |
|---|---|---|
| 0 | preflight + timing smoke | 2026-09-08 |
| 1 | generator calibration | 2026-09-09 |
| 2–4 | high-load synthetic repetitions 1–3 | 2026-09-10 / 09-10 / 09-11 |
| 5–7 | full-internet MRT repetitions 1–3 | 2026-09-11 (all three) |
| 8 | BIRD architecture screen | 2026-09-12, **18/21 qualified, 3 excluded** |
| 9 | variance, version, BIRD-screen review | 2026-09-12 |
| 10 | selected repetitions | accepted (built 2026-09-12+) |
| 11 | screen-peers repetitions 4 and 5 | accepted |
| 12 | final report | built 2026-09-15, accepted |

Final report: `results/2026/2026-timing-validation/block12-final-report/report/report.{json,html}`,
rendered by `scripts/build_timing_report.py` from a review it regenerates itself.

Three rows excluded on tester health, all from Block 8
(`.../block12-final-report/review/problems.json`):
`bird_2.19.2 fanout (20000×50, rx10)`, `bird_2.19.2 peers (2000×500)`,
`bird_3.3.2 (4 threads) peers (2000×500)`.

Two blocks were measured across multiple attempts because the spot host was reclaimed
mid-block (block 2 = 3 attempts, block 10 = 2). Recorded as notes in the block records, not
grounds to discard — and all nine input blocks report `memory_total_kb` within 0.000006% of
each other, i.e. one host class throughout.

**Is it done? Yes — and by its own definition, not just by marker count.** The plan says so at
its Block 12 record: *"Ran and accepted 2026-09-15, and the campaign is complete."* 15 claims,
83 citations, all resolved mechanically against a regenerated review; 124 figures explicitly
withheld rather than guessed.

**All ten Primary Questions are dispositioned.** Eight are settled by the three passes
(Block 9's "What the passes already answer"), and 9–10 by the Block 10/11 selections. Two end
in refusals that are recorded as answers, which is the correct outcome and not a gap:

- **Q7 (is the generator limiting a canonical cell?) — yes**, five MRT rows: four BIRD plus
  `rustybgp default`, `tester (tester_limited)` in all three passes.
- **Q8 (is the GoBGP monitor limiting a canonical cell?) — not separably.** The three OpenBGPD
  rows and `rustybgp 2026-02` are `target_or_monitor (post_injection_tail)`; the plan states
  *"no number of passes changes that, since it is a property of where the instrument sits."*
- Every synthetic row is `unresolved (injection_boundary_unresolved)` — the BIRD generator's
  offered count is queue-side and saturates before the first poll, so `offered_in_interval` is
  0 on all fourteen cells — so **the synthetic workload answers neither Q7 nor Q8.**

Those two refusals are the entire case for what comes next: they are `bgperf2-bgg` and
`bgperf2-4pm`, and they bound how readable any *future* campaign on this host can be.

### 1c. Unattended execution plan — detail

Steps 0–5 (register contract, supervised driver, install/inspect beads, seed the three epics,
seed the measurement plan, seed the 64 GB campaign) were all taken on 2026-09-03.

**Step 6 (headless driver) is built but its exit criterion is NOT met.** Progress note dated
2026-09-15: every clause of the criterion is about a worker session actually running, and no
worker could start — `claude -p` exited 1 with *"You've hit your monthly spend limit … your
weekly limit resets Sep 18, 2am (UTC)"*. The driver stopped, left the tree, and did not
sleep, which is the correct failure path and not the criterion.

What exists and *is* verified:

- `scripts/notify_gate.sh` — verified as a path: delivered 0, unconfigured 78 (`EX_CONFIG`,
  distinct so the driver can tell "set this up" from "your channel is broken"), broken
  channel 1. **No fallback, deliberately** — a local log file is a gate nobody sees.
- `scripts/unattended_driver.sh` — refuses to run off `unattended/measurement` (re-checked
  inside the loop), refuses to start without a channel that just delivered a test message,
  and filters benchmark-labelled items out of the queue before a session is spent.
- `scripts/unattended_worker_prompt.md` — the discipline for an unread session: review until
  clean, full suite, never push, never master, never start a benchmark, gate rather than guess.
- `tests/test_unattended_driver.py` — pure, no `claude`, no Docker.

Also learned here: **`bd gate create --blocks <id>` does not exist.** `bd gate` is for formula
steps. The working spelling is the `human` label plus an ordinary dependency
(`bd create --labels=human`, then `bd dep add <item> <gate>`).

**Step 7 (survive a reclaimed host)** — not started, tracked as `bgperf2-82b`. Most of it
already exists and must not be rebuilt: `batch()` already checkpoints per cell, `--resume`
already skips durable cells, cell identity is already stable across passes and order. What is
missing is durability across a *hard* termination:

- `atomic_write()` fsyncs the temp file and `os.replace()`s it but **does not fsync the
  directory**, so a hard kill can leave the directory entry on the old file. One call, covers
  four records (progress file, batch CSV, batch summary, event artifacts).
- `write_provenance()` **does not go through `atomic_write()` at all** — plain `open(path,'w')`
  + `json.dump` for `<prefix>.versions.json` (`bgperf2.py:2943`), as do the per-run PNGs. A
  kill inside that dump leaves a *truncated* file, which is the worse hole.

### 1d. Two P1 human decisions are blocking, and both are the operator's

- **`bgperf2-cqi`** — raise the Claude spend limit or wait for the reset, before step 6 can be
  verified. Recommendation in the item: wait for the 2026-09-18 reset unless time-critical;
  the re-run is a single command (`scripts/unattended_driver.sh --once`). *The reset date has
  passed as of this snapshot, so this is now actionable.*
- **`bgperf2-5p6`** — which out-of-band channel should unattended gates page? Host has `curl`
  and `tmux`; no mail, sendmail, ntfy, notify-send or webhook. Recommended: an ntfy.sh topic
  (`BGPERF_NOTIFY_CMD='curl -sSf -d @- https://ntfy.sh/<topic>'`) — no account, no credential
  in the repo, replaceable later because the channel is only ever an env var. Explicitly not
  the worker's call: choosing where to page a human, and holding that credential, is the
  operator's.

### 1e. Git state

- Branch `unattended/measurement` = `master` + one commit (`46c716b`, the unattended driver,
  deliberately unverified and off master).
- `master` at `ce9dc0a`, level with `origin/master`.
- Stale branch `fix/sampler-reads-and-block2` at `4b43ebf`.

---

## 2. What we know about bgperf2 itself

The durable answer is `docs/invariants/*.md` — eleven-ish documents, each holding the
argument and the measurement that settled one rule, with `CLAUDE.md` carrying only an index
line per document and `.claude/hooks/invariants-guard.sh` naming the right document when a
governed source is edited. `tests/test_docs_index.py` fails if a document is missing,
unindexed, or governs nothing. The highest-value lessons, each of which cost a wrong
measurement:

**Measurement instrument**
- Timing is measured at the **monitor** (a GoBGP peer, `afi_safis[0].state.accepted`), so it
  captures full propagation, not reception. Routes flow tester → target → monitor.
- **Both poll loops stamp the sample before the read**, and the published resolution is the
  gap the loop *achieved*, not the one it asked for.
- One `docker exec` per poll, not one per peer — two reads are two execs and, worse, two
  instants.
- **A daemon with no gauge reports `None`, never 0.** A span nothing crossed is not a rate of
  zero. Nothing absent is published as a zero.
- **A pass that failed and a pass that has not run are never described by one clause.**
  Collapsed three times before the rule stuck.
- `inconclusive` (the deciding measurement was never made) and `unresolved` (it was made and
  something forbids attributing it) are different refusals.

**Parsing daemons**
- **Never read a BIRD stats table positionally** — BIRD 3 inserts columns, which silently made
  every BIRD 3 target report `accepted` 0 for every neighbour.
- FRR's End-of-RIB log read must be incremental and key its restart reset on **inode**: a 1 GB
  `bgpd.log` cost 4.14 s per 1 s poll and the run never finished.
- **"The target says it is done" must never mean End-of-RIB.** FRR logs that when its
  *generators* finish sending. A rule built on it stamps completion mid-delivery, permanently
  and at a fraction of the table. Built, verified, removed.
- Tester-health log scans go through `scan_log_lines()` and **stop at the last complete line** —
  the generator is still writing, and a truncated `Invalid route` reads as a protocol error.
  Any generator logging to redirected stdout needs `stdbuf -oL`.

**Host and environment**
- **Measure CPU as a delta between two `/proc` samples, never `ps -eo pcpu`** (wrong in both
  directions). **Never allowlist interpreters**; exclude bgperf2's own tree by pid, exclude
  kernel threads, charge a first-seen process rather than skipping it — each of those three
  made the tool report a clean machine while it was busy.
- The controller threads must actually stop on `controller_stop`. They once didn't, and
  bgperf was manufacturing the contention it reported.
- The bench directory must not be in RAM and must not be on the root filesystem — which is
  why the work directory is `/data/bgperf-work` (root here is 29 GB).

**Convergence**
- Five rules, each broken once: stability tracked on *every* sample; regression measured
  against the **high-water mark**, not the previous sample; a count more than `DROP_FRACTION`
  below peak is never CONVERGED however steady it looks; the target's own table witness
  excuses a monitor decline the target doesn't share — but a monitor count of zero never
  attests. The target's per-neighbour counters **shorten** the assurance window; they do not
  gate convergence (that's commit `ce9dc0a`, the current tip of master).

**Reporting**
- A cell's cross-pass identity is its axes and its target, **never its ordinal**. A repetition
  repeats the whole matrix, not each cell, and is part of a run's *name*.
- The report **computes no statistic of its own** — not a median, not a percentage, not a
  difference — and every claim names the series, cell, metric, field and value it rests on;
  the builder resolves each citation against the review and refuses the report if any is
  missing or disagrees. **That refusal fired eight times on the first real build**, every one
  a figure transcribed from a rounded table (`convergence_s` cited as 71.936246 where the
  review says 71.906846). `/code-review` then found nine more things, the first being the
  report printing `injection_s` as a bare `0` on 34 cells on a page whose preamble forbids it.
- `testers (s)` is **neither published nor cited** — a claim whose *text* merely names it is
  refused.

**Provenance traps (all the same shape)**
- `prepare` skips a tag that already exists, so a recipe change is invisible until someone
  forces a rebuild. This produced: gcov-instrumented FRR binaries (103% CPU instrumented vs
  45% clean on FRR 10.7, 4 peers × 25k); exabgp/bgpdump2 images on an archived Debian base;
  and a cached `openbgpd/openbgpd:latest` pinning `bgperf/openbgp:latest` at 8.8 long after
  9.2 shipped. `prepare`/`doctor`/`images` now detect recipe drift — but **every image built
  before that mechanism reports as unverifiable, not as current.**
- The exabgp pair is **still unpinned at both layers** (`FROM python:3-bookworm`,
  `pip_spec('')`) and ExaBGP implements no version command, so two builds months apart are
  indistinguishable. Known open issue.
- bgpdump2 reports `2.0.14 (<commit>)`, read at probe time from the clone the image carries,
  because the version half alone is not identity.

---

## 3. What we know about the BGP daemons

All figures below are from the accepted Block 12 report
(`results/2026/2026-timing-validation/block12-final-report/report/report.json`), measured on
one host class, 16 vCPU / 61.44 GiB, no swap.

### High-load synthetic (50 peers × 100,000 prefixes)

| daemon | convergence | note |
|---|---|---|
| RustyBGP pinned 2026-02 | **66 s** | fastest thing measured — bought with **1074% CPU** |
| FRR 10.7 | **85 s** | fastest conventional daemon, at 111% CPU |
| BIRD 2.19.2 | 90 s | |
| BIRD 3.3.2 | 117 s | slower than 2.19.2 |
| RustyBGP master | 152 s | 2.3× slower than its own pinned build |
| OpenBGPD 8.8 | 624 s | |
| OpenBGPD 9.2 | 733 s | 7–8× slower than FRR/BIRD |

- **FRR 10.7's improvement repeats and it is in convergence**: 85 s vs 91 s (10.0), 95 s
  (9.1), 92 s (8.5); `convergence_s` 71.9 vs 79.2 with `assurance_s` unchanged (16.2 vs 16.4).
  It also holds a quarter less memory: **5.772 GB vs 7.646 GB**.
- **OpenBGPD 9.2 halves peak memory** — 18.536 GB vs 8.8's 37.437 GB — and pays time for it
  on this workload. Three passes each.
- **OpenBGPD 8.8 is the row that comes closest to the 64 GB guardrail and stays inside it**:
  37.437 GB peak leaves 12.4 GB free; every other synthetic row leaves ≥ 33.098 GB. Safe to
  test at this size.
- No cell of the synthetic series has a limiting component the evidence supports naming.

### Full-internet MRT playback (10 peers, pinned 1.05 M-prefix Route Views RIB)

| daemon | convergence |
|---|---|
| RustyBGP pinned 2026-02 | 25 s |
| RustyBGP master | 27 s (but 11.472 GB vs 2.336 GB — **4.9× the memory for no gain**) |
| BIRD 2.19.2 | 32 s — **generator-limited, may not be read as a BIRD measurement** |
| BIRD 3.3.2 | 45 s |
| OpenBGPD 9.2 | 80 s |
| FRR master | 89 s |
| FRR 8.5 / 9.1 / 10.0 / 10.7 | 103–104 s — **one result, not four** (1 s difference at 1 s resolution) |
| OpenBGPD 8.8 | 123 s |

**Which component each MRT cell names, exactly** (`review/mrt.json`, `limiting_component`):

| cells | verdict | reason |
|---|---|---|
| 4 BIRD, plus `rustybgp default` | `tester` | generators still offering after the monitor reached the required count |
| 5 `frr_c` | `inconclusive` | the monitor never reached the required count, so there is no end to measure the generators against |
| 3 OpenBGPD, `rustybgp 2026-02` | `target_or_monitor` | the run continued 14.5–103.7 s after the last generator finished |

**No MRT row is a clean daemon measurement.**

**But `tester` here does not mean "bgpdump2 is too slow" — see §4b.1.** bgpdump2 is already the
fastest generator this repo has, and the fleet rate the review publishes varies 1.8× across
cells with byte-identical generator configuration: 345,720 prefixes/s on the `bird 2.19.2`
cell and 623,727 prefixes/s on the `rustybgp default` cell. A fleet that reached 623 k/s in one
cell was not at its ceiling in the cell where it managed 345 k/s.
- OpenBGPD 9.2 is *faster* than 8.8 here (80 s vs 123 s) — the opposite of the synthetic
  direction — and still uses less memory (3.021 GB vs 4.967 GB).

### BIRD 2 vs BIRD 3 — the campaign's headline negative result

**BIRD 3.3.2 is slower than 2.19.2 on every workload this campaign measured**, and the one
piece of contrary evidence was withdrawn at five passes:

- synthetic: 117 s vs 90 s
- MRT: 45 s vs 32 s
- competing-path selection: 13 s vs 7 s — and **4 threads makes it worse still, 19 s at 223%
  CPU**, the opposite of the peer-scaling shape on the same three binaries
- policy-reload run, end to end: 59 s vs 43 s
- peer scaling (250 sessions, 5 passes): medians 56 s (3.3.2) vs 58 s (2.19.2) — inside the
  1 s resolution, **unseparated at the expansion limit**. What five passes *do* establish is
  a dispersion asymmetry: 2.19.2 ranges 32–117 s where 3.3.2 is much tighter.

**The one dimension where BIRD 3 converts threads into less time is policy recalculation, and
it does it at less CPU rather than more**: 11.8 s (3.3.2 default threads) vs 23.64 s (2.19.2)
over ten blocks, on a sampler whose own resolution is ~2 s. Four threads buys nothing further
(12.15 s).

### Scenarios that are one observation per cell and stay that way

- **export fan-out** — 23 s / 31 s / 29 s with ten receivers. Block 9 declined to expand: one
  of three rows was excluded on tester health and all three carry host CPU saturation (a
  target + a generator + ten GoBGP receivers on sixteen threads), so repetitions would have
  reproduced the confound.
- **churn** — 42 s / 60 s / 55 s. Declined for a different reason: three bursts per run
  already give three reproducing readings of each half, and the difference sits at the churn
  sampler's own resolution. **A faster sampler would sharpen it; more passes would not.**

### Open daemon-behaviour questions (in `bd`, unanswered)

- `bgperf2-nit` (P2) — **RustyBGP master holds 4.8× the memory of the 2026-02 build** for the
  same full-internet table.
- `bgperf2-cw6` (P2) — **why does FRR advertise ~9% less of an MRT table than BIRD and
  OpenBGPD?**
- `bgperf2-599` (P3) — **BIRD 2.19.2 lets 12 of 500 generator sessions expire their hold
  timer** under a 500-peer load.
- `bgperf2-yar` (P2) — a daemon whose export share moves between passes or versions is not
  caught.

---

## 4. What more testing needs to happen

### 4a. Tool bugs that currently distort or block measurement (from `bd`)

P2, measurement-affecting:

- `bgperf2-0ma` — **`-s/--single-table` is completely inert for BIRD targets, and the baseline
  publishes two rows that claim otherwise.** Two published rows are wrong.
- `bgperf2-sl1` — `Container.neighbor_stats()` dies silently on one bad read, freezing the
  target's neighbour counts *and* the table witness.
- `bgperf2-mzy` — a bgperf2 run that outlives its bench competes with the next one, and
  nothing reaps it.
- `bgperf2-lze` — a target container vanished mid-run during a calibration batch pass.
- `bgperf2-afb` — **a calibration suite cannot be resumed**: `suite_key()` stamps a fresh
  directory every invocation.
- `bgperf2-494` — a split-block repetition has no repetition identity in its artifacts.
- `bgperf2-rqp` — derive assurance and post-injection tail off delivery, for MRT rows below
  the check-point.

P3, robustness and honesty of the record:

- `bgperf2-4pm` — **WATCH: the monitor costs more CPU than the daemon under test**
  (`gobgp neighbor -j` is O(table), polled 1/s). This is the measurement instrument competing
  with the thing measured.
- `bgperf2-s5e` — the churn sampler's ~2.2 s resolution *is* the limit on the BIRD churn
  comparison (see §3).
- `bgperf2-bgg` — `tester_limited` cannot tell a slow generator from one back-pressured by a
  slow target. This is what makes five MRT cells unreadable, and it is §4b.1.
- `bgperf2-rw5` — provenance records an image tag and a version string, **not a digest**.
- `bgperf2-wq2` — `delivery_metrics()` runs unguarded inside the event artifact; a raise
  there costs the whole document.
- `bgperf2-v6x` — a `-r/--repeat` run publishes `tester errors 0` without scanning any log.
- `bgperf2-qhx` — `Container.local()` decodes CLI output as strict UTF-8; one stray byte costs
  a poll.
- `bgperf2-5si` — a foreign-CPU peak below the finding threshold is published as a number
  with no names.
- `bgperf2-52e` — `Monitor.wait_established()` dies with a raw docker `APIError` if its
  container goes away.
- `bgperf2-app` — `BIRDTarget.gen_neighbor_config()` raises on **any** call (mixed
  format-string field numbering).
- `bgperf2-x90` — a tester log line with no newline is materialised whole, then discarded.

### 4b. Measurement gaps the campaign itself named

1. **Make `tester_limited` separable — do this before touching any generator** (`bgperf2-bgg`).
   The single largest limitation in the report is that no MRT row is a clean daemon
   measurement, and it is tempting to read the five `tester` cells as "the generator is too
   slow". That reading is not supported, for two reasons:

   - **bgpdump2 is already the fastest generator here.** Of the five in `TESTER_CLASSES`
     (`bird`, `exabgp` synthetic; `gobgp`, `exabgp_mrtparse`, `bgpdump2` MRT), the history
     summary records that GoBGP MRT playback "was often slow enough to become the bottleneck
     itself" while bgpdump2 "was fast enough to stress the target", and ExaBGP-mrtparse is a
     Python encoder. There is no faster one to switch to; a faster generator would have to be
     built or the playback pre-encoded.
   - **The evidence cannot tell a slow generator from a back-pressured one.** That is
     `bgperf2-bgg`, and `tester_limited` names `tester` for both. The 1.8× spread in measured
     fleet rate across cells on identical generator configuration (345 k/s on `bird 2.19.2`
     against 623 k/s on `rustybgp default`) is what that ambiguity looks like in this data:
     either BIRD 2.19.2 back-pressured the fleet, or the fleet happened to be slower in that
     cell, and nothing measured separates them.

   So the cheap, decisive next step is generator-side evidence of *why* a send was slow —
   whether the injector was blocked on write versus busy encoding — not a new generator.
   Block 1 already shows why the rate alone will not do it: the unconstrained per-injector
   rate is not reproducible run to run (45.2 mbit against 69.1 mbit for the same injector,
   four weeks apart), which is why it is published as an order of magnitude and never
   asserted. Only after that separation exists is "build or pre-encode a faster generator"
   a decision with evidence behind it.
2. **A faster churn sampler** — the comparison's limit is the ~2.2 s poll gap, not the number
   of passes.
3. **Export fan-out without host saturation** — needs either fewer receivers per host or a
   second host; repeating it on this host reproduces the confound.
4. **Table selection is still not externally separable** — stated out loud rather than folded
   into an interval that quietly contains it. Separating it needs a new observable.
5. The two Phase 5A design questions (§1a): export timing beside a post-convergence
   workload, and `--prefix-scope total` under `--path-diversity`.

### 4c. Workloads never run (from the 2026 test plan's "Missing But Valuable Future Add-Ons")

- **Withdrawal tests** — full-table withdraw, partial withdraw, mixed update/withdraw churn.
  (Churn bursts exist as a control; the withdraw *suite* was never run.)
- **Incremental steady-state tests** — load the table, replay a smaller delta, measure
  convergence after steady state rather than cold start.
- **Route-server / route-reflector tests** — many peers, moderate policy, realistic export.
- **Multi-host validation** — testers on one host, target on another, monitor on a third.
  This is the only thing that answers *how much the single-host setup is biasing every number
  above*, and it directly addresses `bgperf2-4pm` and the fan-out confound.
- **Larger-memory hardware** (192 GB and 384 GB classes) — designed in the 2026 test plan,
  retained as historical context, **not scheduled while the 64 GB host is the only one**.

### 4e. Do we need bigger hardware? Not yet, and not memory first

**Memory is not what is limiting us.** The 64 GB host held every workload the campaign ran,
and the one row that had to be checked rather than assumed stayed inside the guardrail:
OpenBGPD 8.8's 37.437 GB peak left 12.4 GB free (20.2%) on 61.44 GiB with no swap, and every
other synthetic row left ≥ 33.098 GB. On MRT playback the worst target peak was RustyBGP
master at 11.472 GB. Nothing was cut for want of RAM.

**What the campaign did get cut for was host CPU and host count.** Block 9 declined to expand
the export fan-out scenario because all three of its rows carry host CPU saturation — a
target, a generator and ten GoBGP receivers on sixteen threads — so repetitions would have
reproduced the confound rather than removed it. `bgperf2-4pm` is the same shape: the monitor
(`gobgp neighbor -j`, O(table), polled 1/s) can cost more CPU than the daemon under test. And
`docs/2026-memory-capacity-options.md` says it directly: *"More RAM cannot repair missing
tester completion evidence or distinguish target time from generator and monitor time"*, and
*"High-peer synthetic work may require more physical cores or separation of testers, target,
and monitor across hosts."*

So the next hardware that would change an answer is **more cores, or a second and third host**
(the multi-host validation in §4c) — not a bigger memory tier.

**The capacity envelopes still hold, which is step 3 of the execution order partly discharged.**
They were derived from `2026-baseline` anchors on a 60.73 GB host; the timing-validation
campaign re-measured the same two worst cases across three passes and reproduced them:

| anchor | baseline (planning doc) | timing validation (3 passes) |
|---|---|---|
| worst synthetic, target peak | OpenBGPD 8.8, 37.439 GB | OpenBGPD 8.8, 37.437 GB |
| worst synthetic, host-wide use | 50.564 GB | ~49.0 GB (12.4 GB free of 61.44) |
| worst MRT, target peak | RustyBGP default, 11.46 GB | RustyBGP master, 11.472 GB |

So the tier table needs no revision on this evidence. **If** a larger host is bought later, the
doc's standing recommendation is unchanged: 256 GB as the durable general-purpose tier
(~100 full-table peers, ~20 M synthetic routes), 128 GB as the minimum meaningful upgrade
(~50 peers, ~10 M routes), 384 GB only when capacity-cliff work is a recurring objective. And
a cloud caveat that matters here: instance sizes change CPU allocation along with memory, so
**different sizes are different host classes** and may not be compared as a memory-only curve.

### 4d. Durability and automation work

- Unattended step 6 verification, now unblocked by the spend-limit reset — needs
  `bgperf2-5p6` (notification channel) answered first, because the driver refuses to start
  without one.
- Unattended step 7: `atomic_write()` directory fsync, and route `write_provenance()` through
  it (§1c).

---

## 5. Gaps in this snapshot worth knowing

- **The `2026-baseline` campaign's raw suite rows are not on this host.** `results/` is
  gitignored, and `results/2026/2026-baseline/` holds only `metadata/` plus one 2026-09-08
  MRT calibration suite. Its manifest lists exactly one suite. The campaign's *findings*
  survive in `docs/bgp-performance-history-summary.md` and in the measurement plan's Current
  State section; the rows themselves went with an earlier host. Nothing downstream depends on
  them — the timing-validation campaign re-measured everything it publishes.
- **Baseline rows may never be compared across hosts.** `benchmarks/baseline/baseline-benchmark.csv`
  (51 data rows) was produced on a different CPU than this one. That rule is in the
  timing-validation skill and in memory.
- `docs/follow-ups.md` still holds two deliberately-descoped items (stamp the real
  pre-sanitize version as a build-time label; consolidate `doctor`/`images`/`prepare` status
  formatting). Its own header says they belong in `bd` now that `bd` works — that migration
  has not happened, and the file should empty out rather than grow.
