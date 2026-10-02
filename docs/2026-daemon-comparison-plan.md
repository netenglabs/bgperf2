# 2026 daemon comparison plan

**Status: Phases 0, 1 and 2 done; Phase 3 in progress (started 2026-10-02 on an on-demand `m7a.4xlarge`, EPYC 9R14). Written 2026-09-29.**

**Epic:** `bgperf2-0y5`

This plan exists to publish one thing: **a comparison of the open-source BGP daemons and their
versions that says what changed between releases and can be defended**. Before that, it has to
settle what the 2026-09-15 timing-validation report
(`results/2026/2026-timing-validation/block12-final-report/`) could not.

It is a plan document in the sense `CLAUDE.md` describes, driven by the `2026-daemon-comparison`
skill (`continue the 2026 daemon comparison`). Progress is recorded here, under each phase's
`Progress` line. Each phase carries one `**Tracked by:** … · **Status:** …` line, whose status is
`not started`, `in progress`, `done` or `not needed`. `scripts/check_plan_beads.py` fails when a
status disagrees with its bead's, when the epic has a child no phase names, or when a bead starts
carrying reasoning. The `bd` items link to this document's sections and hold no reasoning of their
own.

**Hardware, in one paragraph.** **Everything before Phase 3 runs on the development host as it
stands.** On 2026-10-01 that is 8 vCPU / 30 GiB, AMD EPYC 9R45: smaller than the campaign class
and a different CPU. That is the operator's choice: get as far as possible on this instance, and
provision another only for performance testing. Work done here must never need a row that
compares with the campaign's:
- source and artifact reads;
- code changes and their tests;
- `-n1 -p1` smoke runs;
- image builds;
- diagnostics that compare only against controls re-run on this same host, like the 1.3
  memory bisect.

**Phase 3 is the first point that needs another EC2 instance.** It runs on a freshly provisioned
`m7a.4xlarge` (16 vCPU / 61.44 GiB AMD EPYC 9R14), the campaign host class. **Confirm the class with
`lscpu` before the first row.** Beyond that, new hardware is needed only if the gate in §5 says so.
Then we rent **three `m7a.4xlarge` hosts in one cluster placement group**, to separate generator,
target and monitor. **More memory is not needed for this comparison at all.** It is needed only for
the capacity-cliff work in §7, which is a different question from "what changed between versions".

---

## 1. What the existing evidence already supports

This section records where things stand, so no later phase re-derives it.

**Synthetic, 50 peers × 100k prefixes: publishable.** At least three passes per version, on one
host class:

- **FRR 10.7** converges faster than 8.5 / 9.1 / 10.0 (85 s vs 91–95 s) and holds a quarter
  less memory (5.772 vs 7.646 GB).
- **OpenBGPD 9.2** halves 8.8's peak memory (18.5 vs 37.4 GB) and is slower on this workload
  (733 vs 624 s).
- **BIRD 3.3.2** is slower than 2.19.2 on every workload except policy recalculation.
- **RustyBGP master** has regressed from the 2026-02 build: 2.3× slower on synthetic, 4.9× the
  memory on MRT. The memory regression bisects to one commit, `bd40d626` (Phase 1.3).

Caveat that travels with it: the report names no limiting component for any synthetic cell
(`unresolved (injection_boundary_unresolved)`).

**Full-internet MRT, 10 peers × 1.05 M: not publishable as daemon measurements.** Stated
precisely, because it was easy to overstate:

| cells | verdict | what it does and does not say |
|---|---|---|
| 4 BIRD, `rustybgp default` | `tester` | the generators were still sending when the monitor reached the count. It does **not** say bgpdump2 was slow: a generator blocked by a target that is not draining it produces the same measurement (`docs/invariants/findings.md`). A 1.8× spread in fleet rate on identical generator config (345k/s vs 623k/s) points toward back-pressure. Nothing yet proves it. |
| 5 `frr_c` | `inconclusive` | the monitor never reached the check-point. FRR advertises ~9% less of the table, because one injected peer (AS 37100) tags every route NO_EXPORT and FRR's oldest-path tie-break selects it more often (`bgperf2-cw6`, Phase 1.1). So this is a counting question, not a timing one. |
| 3 OpenBGPD, `rustybgp 2026-02` | `target_or_monitor` | the generators finished 14.5–103.7 s before the end, so the generator is ruled out. The remaining time cannot be split between the target and the GoBGP monitor on one host. |

**Wrong in the published record:** two `2026-baseline` rows claim `-s/--single-table` affected
BIRD, when the code path that honours it never ran (`bgperf2-0ma`, in progress).

---

## 2. Phase 0 — land what already exists

**Tracked by:** `bgperf2-0y5.1` · **Status:** done

No runs.

1. ~~Review and commit the GoBGP removal (`cleanup/remove-gobgp-target`, `bgperf2-es0`). GoBGP is
   no longer a target or an MRT generator. It remains the monitor and the export receivers.~~
   **Merged 2026-09-29 (`fb69263`).**
2. ~~Finish `bgperf2-0ma` / `bgperf2-app`.~~ **Done 2026-09-29 (`9109bda`)**: `-s` is refused at
   every entry point, and the baseline's `bird -s` and `bird` rows are recorded as one config.

**Exit:** both merged. `-t gobgp` and `-g gobgp` are refused. No published row is known to be
wrong.

Progress: done 2026-09-29. Item 1 merged as `fb69263` (`bgperf2-es0`); item 2 is `9109bda`.

---

## 3. Phase 1 — questions answerable from existing evidence

**Tracked by:** `bgperf2-0y5.2` · **Status:** done

No new benchmark runs. Each item is a read of source or artifacts that already exist.

1. ~~**`bgperf2-cw6`: why does FRR advertise ~9% less of the MRT table?**~~ **Answered
   2026-10-01 (`e6d4f46`, decision log "Finding on 2026-10-01").** It is filtering FRR is
   entitled to, not a config bug. Injected peer AS 37100 (RIB index 10, injector 6) carries
   NO_EXPORT on all 1,050,000 of its routes, and the monitor and testers are all eBGP. A
   prefix whose best path is AS 37100's is advertised to nobody. BIRD and OpenBGPD break
   ties on router ID, which picks that path for 24,219 prefixes and predicts their
   1,056,779 to within 13. FRR prefers the oldest path, so its share (~120k) depends on
   arrival order. That matches its 956,893–961,057 spread across the 15 recorded rows.
   The check-point is unsound for this RIB for every daemon. The five `inconclusive`
   cells can be re-derived without a run: all 15 FRR rows carry a resolved
   `target_table.delivery` with `exported_final == monitor_final`. Cross-daemon MRT
   timing compares unequal export work, which is Phase 2.6.
2. ~~**`bgperf2-4pm`: what does GoBGP do to answer `gobgp neighbor -j`?**~~ **Source read
   2026-09-29 (`21ae46c`, decision log "Finding on 2026-09-29").** The accepted count is O(1).
   The O(table) walk is the received count, which bgperf2 never reads. `ListPeer` holds the
   server's exclusive lock throughout, so the monitor processes no UPDATE during it: ~30% of wall
   time at 1.05 M. No CLI read avoids it. All 27 MRT rows keep `monitor_lag_s` inside its bound.
   What remains is a decision, and it is the operator's — see Phase 2.1.
3. ~~**`bgperf2-nit`: RustyBGP master's 4.8× memory.**~~ **Answered 2026-10-01 (`fb5f58d`,
   decision log "Finding on 2026-10-01: RustyBGP's MRT memory regression is one commit").** It is
   one commit, `bd40d626` (2026-03-07, "remove global max_send, track all paths like Juniper"):
   its parent peaks at 3.10/3.12 GB and it peaks at 14.61/14.96 GB. The RIB now diffs and emits
   changes for every path of a prefix, not just the best. That costs only where prefixes have
   several paths, which is why synthetic shows no regression. The mechanism is inferred from the
   diff, not profiled. The bisect ran on the 8 vCPU development host against controls re-run there
   (2.47 vs 11.81 GB, reproducing Block 5).

**Exit:** each of the three has a recorded answer, or a named reason it cannot be answered
without new runs.

Progress: done 2026-10-01. Item 2 done 2026-09-29 (`21ae46c`), item 1 2026-10-01 (`e6d4f46`), item 3 2026-10-01 (`fb5f58d`).

---

## 4. Phase 2 — instrument changes on the current host

**Tracked by:** `bgperf2-0y5.3` · **Status:** done

Code changes, verified by the test suite and by `-n1 -p1` smoke runs.

1. ~~**Decision (operator): change the monitor, or keep it.**~~ **Answered by the operator
   2026-09-29: change it**, by replacing GoBGP with a purpose-built sink. The work is
   [measurement plan Phase 7](bgperf2-measurement-implementation-plan.md#phase-7-replace-the-monitor-with-a-purpose-built-sink)
   (`abce4a0`, epic `bgperf2-8gg.10`), not this plan's. The reasons are recorded in the decision
   log's Phase 7 section. The decisive one for *this* plan is resolution. In the timing-validation
   review, most cells' pass-to-pass stdev is 0.0–0.6 s against a 1 s poll, and several version
   pairs differ by one or two seconds (MRT 103/104, 80/81, 25/27). The current monitor cannot
   resolve the differences this plan exists to publish. A second reason: a sink ingests far
   faster than any target, so it may resolve the `target_or_monitor` cells on one host, which is
   what the §5 gate would otherwise send to Phase 4.
2. ~~**Pin each role to its own cores (new).**~~ **Done 2026-10-01, `1a1bdf9`:** `--pin` on
   `bench` and `pin:` on a batch test; rules in `docs/invariants/workload-controls.md`. Smoke runs on
   this host (BIRD 2.19.2, `-n1 -p1`): pinned `target=0-3,monitor=4-5,testers=6-7` and unpinned both
   converged, under distinct stems, and `docker inspect` showed each cpuset applied. Today target, generators, monitor and receivers
   share all 16 vCPU, and the monitor can out-consume the target. **Pin the sink, not GoBGP.**
   GoBGP's per-poll table walk and its garbage collection spread across every core it can
   reach. Squeezed onto two, each walk would likely take longer and hold the monitor's lock for
   longer. That is inferred from the source, not measured, and it is moot once the sink is the
   monitor. Add an opt-in per-role
   `cpuset`, for example `--pin target=0-7,monitor=8-9,testers=10-15`. It must:
   - be recorded in the run's provenance and reach `bench_output_prefix()` (a pinned run and an
     unpinned run are different cells);
   - be refused where it cannot hold: overlapping sets, more cores than the host has, a remote
     target — at all four entry points (`docs/invariants/workload-controls.md`).

   On `m7a` a vCPU is a physical core, not an SMT sibling. **Confirm this with `lscpu` on the
   host before relying on it.** If it holds, disjoint sets really are disjoint.
3. ~~**`bgperf2-ylb`: separate a slow generator from a back-pressured one.**~~ **Done 2026-10-01,
   `ad993ee`:** `generator_headroom` in `scripts/timing_variance_review.py`. It is a bound, not a
   separation: cells are grouped by the generator's recorded identity, and each cell's fastest
   uncontended self-timed send is compared with the fastest in its group. The definition and its
   refusals are in `docs/measurement-dictionary.md`, "What `tester_limited` does not separate".
   - **Validated against the controls, with the result it gets wrong pinned in the tests.** The
     starved target reads 6.0× the baseline, which is correct. The 4 mbit-capped generator reads
     16.33×, which is wrong. The statistic cannot see a constraint applied outside bgperf2's
     record, and it says so in its `basis`.
   - **On the Block 5–7 MRT series** (one group: 10 × 1.05 M, bgpdump2 `2.0.14 (a019184)`), the
     reference is 1.389 s, set by the OpenBGPD cells. The three OpenBGPD cells sit inside its own
     spread (1.389–1.394 s). Every other cell shows headroom:

     | cells | fastest self-timed send | × reference |
     |---|---|---|
     | RustyBGP 2026-02 | 3.03 s | 2.2 |
     | RustyBGP master | 12.4 s | 8.9 |
     | BIRD | 24.4–34.9 s | 17.6–25.1 |
     | FRR | 58.6–73.0 s | 42.2–52.5 |

     None of those passes was contended, and host idle never fell below 28% on the
     five `tester` cells. RustyBGP 2026-02 reached 3.0 s at 8% idle, so host CPU does not explain
     the gap either. **So the five `tester` MRT cells (four BIRD, RustyBGP master) were waiting on
     the target's ingest, not on the generator's ceiling**, under the stated premise.
     `findings.py` still says `tester` for them, by design.
   - What would turn the bound into an attribution is still per-role CPU. Phase 3's pinned rows
     narrow the premise, because the generator's cores are then part of its recorded identity.
   - The rule is reproduced by
     `scripts/timing_variance_review.py --run-root results/2026/2026-timing-validation --series mrt`.
4. ~~**Rebuild every image** with `prepare -f`.~~ **Done 2026-10-01:** before this, every current
   image reported `recipe unknown`, so the recipe-drift check could not vouch for any of them.
   `prepare -f -t <name>` was run for each of the eight `PREPARE_IMAGES`, which built 18 tags. Log:
   `/data/bgperf-work/logs/phase2.4-prepare-20261001T034909.log`. Afterwards `images` shows every
   matrix tag `built` with its recipe known, and `verify` reports **31 image(s) checked, all ok**.
   The 2084 tests pass. Read these before relying on the images:
   - **`-f` without `-n` reuses Docker's layer cache.** That is sound for the label: the cache
     is keyed on the instruction text, so a cached layer is what this recipe builds. But it
     means the `master`/`latest` tags keep the clone they were first built from:
     BIRD `2.19.0+branch.master.292a46adc54d`, RustyBGP `v0.2.0-9eeeebbd50`, GoBGP 4.9.0.
     They are not today's heads. The pinned versions are unaffected.
   - **The exabgp pair really did change.** Their `apt dist-upgrade` and unpinned
     `pip3 install exabgp` layers re-ran, so those two images hold whatever was current today.
     This is the open unpinned-exabgp issue `CLAUDE.md` describes. Provenance still records
     `UNKNOWN` for both.
   - `verify` cannot probe `frr_c`'s version without a running daemon (`--` in its output). Its
     instrumentation check is clean on all five tags.
   - `openbgp:latest` is 9.3, the same as the pinned 9.3 tag.
   - `prepare` builds with `rm=False` (`base.py` `build_dockerfile()`), so every build leaves
     its intermediate containers behind: 40 from this rebuild, now removed. Tracked as
     `bgperf2-os1`.
   - Phase 3 runs on another host, so these images carry over only if `/data` (Docker's root
     is `/data/docker`) moves with them (§5).
5. ~~**Fix the version matrix.**~~ **Done 2026-10-01, `2d7bb84`:** checked upstream by `git ls-remote`
   and the Docker Hub API. The only newer release is **OpenBGPD 9.3** (pushed 2026-09-30), now in
   `OpenBGP.VERSIONS`. FRR's newest is `frr-10.7.1`, a patch inside the `stable/10.7` we already
   build, with no 10.8 or 11 release. BIRD 2.19.2 and 3.3.2 are still the newest. Its image is
   built in item 4. At the time of this phase, check upstream for releases newer than
   those below, and add at most one per daemon:

   | daemon | carried forward | candidate additions |
   |---|---|---|
   | FRR (`frr_c`) | 8.5, 9.1, 10.0, 10.7, master | newest stable if newer than 10.7 |
   | BIRD | 2.19.2, 3.3.2 (default and 4 threads) | master; newest 3.x if newer |
   | OpenBGPD | 8.8, 9.2 | newest upstream tag if newer |
   | RustyBGP | 2026-02, master | — (see Phase 1.3) |

   GoBGP is not in the matrix (Phase 0).
6. ~~**Decision (operator): the MRT workload's NO_EXPORT peer (new, from Phase 1.1).**~~
   **Answered by the operator 2026-10-01: keep it, with obligations.** On the pinned RIB, one of
   the ten injected peers (AS 37100) tags every route NO_EXPORT. So each daemon exports a
   different share of the table: BIRD and OpenBGPD 1,056,779, FRR ~959k and varying by
   arrival order, RustyBGP the whole 1,081,178. Keeping the peer is the only option that
   leaves those differences visible in the data, and the only reversible one. Skipping the
   peer or stripping the community would erase RustyBGP's apparent NO_EXPORT deficiency and
   FRR's tie-break difference rather than resolve them. `compare-routerid` would change the
   daemon under test. The obligations that make "say so" enforced rather than promised:
   1. ~~**Every MRT cell is published with its export volume beside its time**
      (`bgperf2-0l7`, blocks Phase 3).~~ **Done 2026-10-01 (`cfcc105`).**
      `build_timing_report.py` publishes `received`, the monitor's accepted count when the
      run ended, as the column directly after `elapsed (s)`, for every cell, with each
      pass's value printed beside each pass's time. Rebuilt against the Block 12 review, it
      shows BIRD and OpenBGPD at 1,056,779, the FRR cells between 956,893 and 961,057 from
      pass to pass, and RustyBGP 2026-02 at 1,081,178.
   2. **Every behavioural difference and deficiency goes in §8's ledger**, with its evidence
      and its effect on the numbers. The publication carries the ledger.
   3. **RustyBGP's NO_EXPORT behaviour is confirmed from source** before it is published as a
      deficiency (`bgperf2-9su`, blocks Phase 3).
   4. **Triggers to revisit.** If cross-daemon MRT claims are to be published, or if the sink
      monitor shows FRR's run-to-run volume wobble moving its timing by more than the
      published resolution, add a "peer skipped" workload (index 14, AS 3130, 1,059,817
      routes, no NO_EXPORT) **beside** this one, never in place of it.

   The options not taken were: skip the peer, strip NO_EXPORT at the injector, set
   `bgp bestpath compare-routerid` on FRR, and (not in the original list) peer the monitor
   over iBGP.

**Exit:** tests green; a pinned smoke run and an unpinned smoke run both complete, with distinct
artifact names; all matrix images verify clean.

Progress: item 1 answered by the operator 2026-09-29 (change the monitor; the work is measurement
plan Phase 7). Item 6 answered by the operator 2026-10-01 (keep the NO_EXPORT peer, with obligations). Item 2 done 2026-10-01 (`1a1bdf9`), item 5 2026-10-01 (`2d7bb84`), item 3 2026-10-01 (`ad993ee`), item 4 2026-10-01 (images rebuilt, `verify` all ok), item 6 obligation 1 2026-10-01 (`cfcc105`, `bgperf2-0l7`). **Phase 2 done 2026-10-01**: tests green, pinned and unpinned smoke runs completed under distinct stems (item 2), all matrix images verify clean.

---

## 5. Phase 3 — re-run on the current host class, then the hardware gate

**Tracked by:** `bgperf2-0y5.4` · **Status:** in progress

**Requires measurement plan Phase 7 through 7b** (`bgperf2-8gg.10.2`). Phase 3 runs on the sink
monitor at its finer resolution. The sink has been the default since 7d (2026-10-02). Write this
phase's configs fresh, stating `monitor: sink`; do not copy one of the 2026 configs, which all
state `monitor: gobgp` because that is what they ran under.

**Host:** one `m7a.4xlarge`, the same class as the timing-validation campaign, **provisioned for
this phase**: the development host is not that class (see the hardware paragraph above). The
images Phase 2.4 built here carry over only if `/data`, Docker's root included, moves with them.
Otherwise rebuild them there and re-run `verify`. **The rows stand on their own.** They are not
comparable with that campaign: a different monitor is a different instrument, and on 2026-10-01 the
operator dropped the bridge block (measurement plan 7c) that would have made them so. The campaign's
rows are superseded, not deleted, and this phase is the re-bench. Nor are they comparable with
anything older (`benchmarks/baseline/baseline-benchmark.csv` was a different CPU).

Workloads, three passes each, matrix repeated as a whole (`docs/invariants/batch-passes.md`),
new run ID `2026-comparison`:

1. ~~synthetic 50 × 100k, pinned;~~ **Done 2026-10-02** (`03d824d`, `benchmarks/2026-comparison-synth.yaml`). 42 rows in `results/2026/2026-comparison/synth/`; see Progress.
2. MRT 10 × 1.05 M (bgpdump2), pinned;
3. **one bias check:** a small subset of both, unpinned, so pinned and unpinned can be compared
   on identical builds and the effect of co-location is measured rather than assumed.
~~4. Phase 7's bridge block (7c, `bgperf2-8gg.10.3`), in the same block as item 3.~~ **Dropped
   2026-10-01** with 7c itself. The operator chose to re-bench rather than bridge, so this phase
   needs no second monitor. GoBGP stays selectable for re-checking any one sink cell that looks
   wrong (`docs/bgperf2-measurement-decision-log.md`, Phase 7).

Every run is on-demand or checkpointed. A spot reclaim mid-block has already cost two blocks
their continuity (`docs/completed/2026-64gb-timing-validation-plan.md`).

### The hardware gate

After Phase 3, look at the MRT and fan-out cells and decide with this table:

| what Phase 3 shows | conclusion |
|---|---|
| MRT cells resolve to `target` (or are named cleanly), and the pinned/unpinned subset agrees within the published resolution | **No new hardware.** Co-location is not biasing the result. Publish from §6. |
| cells still resolve to `target_or_monitor`, **or** pinned and unpinned disagree by more than resolution | **Co-location is biasing the result.** Go to Phase 4 on new hardware. |
| export fan-out still shows host CPU saturation with the monitor and receivers pinned apart from the target | **Phase 4** — the receivers need their own host. |

Progress: started 2026-10-02 on an on-demand `m7a.4xlarge` (16 vCPU, AMD EPYC 9R14, one thread per core, confirmed with `lscpu` and the instance metadata). Docker's root `/data/docker` carried the Phase 2.4 images over, and `verify` reported 32 images checked, all ok. Item 1 config: `benchmarks/2026-comparison-synth.yaml`. Its matrix has no `openbgp default` cell, because `openbgp:latest` is 9.3.

Item 1, 2026-10-02 01:34–05:52 UTC: 14 cells × 3 passes, pinned `target=0-7,monitor=8-9,testers=10-15`, sink monitor, shuffle seed 202631. Log: `/data/bgperf-work/logs/2026-comparison-synth-20261002T013416.*`. All 42 rows received 5,000,000 against a required 4,950,000, and none failed. Per-cell `elapsed (s)`, the three passes and their median, from `2026-comparison-synth.summary.json`:

| cell | passes | median |
|---|---|---|
| BIRD 2.19.2 | 78, 76, 78 | 78 |
| BIRD 3.3.2 (default threads) | 99, 98, 99 | 99 |
| BIRD 3.3.2 (4 threads) | 78, 78, 77 | 78 |
| BIRD master | 78, 78, 77 | 78 |
| FRR 8.5 | 72, 72, 72 | 72 |
| FRR 9.1 | 72, 72, 72 | 72 |
| FRR 10.0 | 71, 71, 72 | 71 |
| FRR 10.7 | 45, 51, 46 | 46 |
| FRR master | 46, 47, 47 | 47 |
| OpenBGPD 8.8 | 610, 617, 605 | 610 |
| OpenBGPD 9.2 | 695, 690, 708 | 695 |
| OpenBGPD 9.3 | 714, 701, 701 | 701 |
| RustyBGP 2026-02 | 73, 76, 76 | 76 |
| RustyBGP master | 154, 168, 146 | 154 |

Read these with three things in mind:
- **Every row's limiting component is `unresolved`.** The cause is the same as in timing-validation Blocks 2–4: BIRD 2.19's offered count is queue-side, so at most 62,368 of the 5,000,000 offered prefixes crossed the measured interval in any row, far short of the half that attribution needs. This workload cannot attribute. The gate reads the MRT cells.
- **RustyBGP master sent `Hold timer expired` to its generator sessions** (`<RMT> bgp1: Error: Hold timer expired` in the BIRD tester logs, recorded in each run's `tester-health.json`). It happened on 1, 4 and 1 of the 50 sessions in passes 1–3, and every pass still converged with the full table. RustyBGP 2026-02 shows none. Neither build did it in timing-validation Blocks 2–4, which were unpinned at 16 cores and ran on GoBGP. Pinning and the monitor both changed between those runs, so the cause is not attributed. **Item 3's subset should include RustyBGP master** so the pinned/unpinned pair can separate the two.
- OpenBGPD 8.8's lowest `min free mem` was 17.8 GB (29% of the host), clear of the 20% floor.

The batch's own variance rule lists three pairs it cannot separate at n=3: FRR 10.7 against master, OpenBGPD 9.2 against 9.3, and RustyBGP 2026-02 against BIRD 2.19.2. For each it recommends `repetitions: 5`.

The controller spends about 2 min of single-threaded CPU per cell rendering and parsing the scenario before the measured interval starts. That is about 96 min of main-thread CPU across this batch, and 6% of one core during measurement. Tracked as `bgperf2-dyr`; it is outside this plan.

Item 2 config: `benchmarks/2026-comparison-mrt.yaml`, item 1's config with only the workload changed (10 bgpdump2 peers on `mrt/rib.20260808.0000`, `prefixes: 1_050_000`) and seed 202632. Launched 2026-10-02 after the operator confirmed it; results go to `results/2026/2026-comparison/mrt/`.

---

## 6. Phase 4 (conditional) — separate the roles across hosts

**Tracked by:** `bgperf2-0y5.5` · **Status:** not started

**Only if the gate in §5 says so.**

### What hardware, exactly

| host | role | instance | why this one |
|---|---|---|---|
| A | target | `m7a.4xlarge` (16 vCPU / 64 GiB) | **The same class as every existing row**, so the only thing that changes is separation. A different target host class would make every row incomparable and leave nothing to measure the bias against. |
| B | generators (bgpdump2, BIRD tester) | `m7a.4xlarge` | Headroom: the generator fleet alone, with nothing else competing for CPU. If Phase 2.3 shows injectors are CPU-bound even so, step up to `m7a.8xlarge` for **this host only** — the generator's host class is not part of the result. |
| C | monitor, export receivers | `m7a.4xlarge` | The monitor holds a full table and peaked at 380% CPU. Ten receivers each hold a copy of the table. Its own box removes it from the target's CPU. |

- **Placement:** all three in **one availability zone, one cluster placement group**, so
  propagation between hosts is consistent and small next to the 1 s poll.
- **Purchase:** **on-demand for the duration of a block**, not spot. Losing one of three hosts
  loses the run, and three spot hosts are three times as likely to be reclaimed.
- **Storage:** each host needs a durable, non-root, non-RAM bench directory
  (`docs/invariants/host-and-environment.md`). On the target host, the pinned RIB must be on
  that volume.
- **Check prices and availability when scheduling**, not from this document.

### What has to be built first

It is not a configuration change. bgperf2 today starts every container on one local Docker bridge
and only knows "remote target" through a hand-written scenario, **with no CPU or memory stats**.
Phase 4 needs:

1. a Docker endpoint per role, with the controller on one host (probably B or C);
2. routed peering between hosts in place of the local bridge;
3. target CPU and memory sampled from host A, and `contention.py`'s `/proc` sampler on **every**
   host, since each host can now be busy independently;
4. a decision on clocks. Timings are stamped by the controller, so they stay on one monotonic
   clock *if* every sample is still driven from the controller. That must be confirmed, not
   assumed. Otherwise use the Amazon Time Sync Service on all three hosts, and publish the
   measured offset.

**Exit:** the §5 bias-check subset re-run across three hosts. The difference against Phase 3 is
published as the single-host bias.

Progress: —

---

## 7. Not part of this plan: more memory

The comparison fits comfortably in 64 GB. The worst row, OpenBGPD 8.8 synthetic, peaked at
37.4 GB with 12.4 GB free. The worst MRT row was 11.5 GB. **More RAM changes no answer in this
plan.**

More memory becomes necessary only for **capacity-cliff** work: ~50+ full-table peers,
>10 M synthetic routes, or route-server / route-reflector export state. It is sized in
`docs/2026-memory-capacity-options.md` (128 GB minimum meaningful, 256 GB durable, 384 GB only for
recurring cliff work). One refinement to that document: **`r7a.4xlarge` (16 vCPU / 128 GiB) is
the memory-only step.** It keeps the vCPU count of the current host, whereas `m7a.8xlarge`
doubles cores as well. Its CPU is expected to be the same EPYC 9R14; confirm with `lscpu` before
the first row. If the CPU differs, it is a different host class and the timing rows do not
compare.

## 8. Known differences and deficiencies between daemons

The comparison publishes this ledger with its numbers. Each entry is a behaviour in which
the daemons differ, or a capability one of them lacks, together with its evidence and what
it does to the published figures. An entry is added when a difference is found, not when it
is explained. "Inferred" means the evidence is a count or a reading of config, and that a
named check would confirm it.

1. **NO_EXPORT on eBGP export.** BIRD, OpenBGPD and FRR withhold NO_EXPORT routes from eBGP
   neighbours, as RFC 1997 requires. **RustyBGP does not, and does not honour NO_ADVERTISE
   either.** This is confirmed from source on 2026-10-01 (`bgperf2-9su`), at master
   `783d6df` and at `0cc685c` (the 2026-02 build). On master, the export decision
   (`process_nlri_change`, `daemon/src/event/export.rs:609`) checks only:
   - echo back to the sending peer;
   - iBGP split horizon;
   - route-server isolation;
   - the RTC filter;
   - a user export policy.

   NO_EXPORT and NO_ADVERTISE exist only as names a user policy can match
   (`table/src/policy.rs`, `daemon/src/convert.rs:3915`). At `0cc685c`, `daemon/src/event.rs`
   contains no community handling at all. bgperf2 configures no export policy (`policy: {}`).
   Effect: on the MRT workload, RustyBGP exports ~24k more prefixes than BIRD and OpenBGPD,
   the whole 1,081,178-prefix union. Its MRT rows therefore include export work a compliant
   daemon would not do. Decision log "Finding on 2026-10-01".
2. **Tie-break between otherwise-equal eBGP paths.** FRR prefers the oldest path by default.
   BIRD and OpenBGPD prefer the lower router ID; that is *inferred* from a simulation that
   predicts their export count to within 13 prefixes. Effect: on the MRT workload, FRR
   exports ~97k fewer prefixes than BIRD and OpenBGPD, and the amount varies from run to run
   (956,893–961,057 across 15 rows), because which path is oldest depends on arrival order.
   Same source.
3. **What a target can report about its own table.** BIRD reports `best_paths`,
   `imported_paths` and `exported_to_monitor`. FRR reports the last two and withholds
   `best_paths` deliberately (`docs/invariants/target-state.md`). OpenBGPD and RustyBGP
   report none of the three (`Target.get_table_witness()` returns `None`). Effect: their
   convergence is judged on the monitor alone, and their export volume is known only as the
   monitor's count.
4. **FRR runs with `log stdout debug`**, which bgperf2 sets so End-of-RIB can be read from
   the log (`frr.py` `write_config()`). No other daemon is configured to log at debug level.
   `bgpd.log` passes 1 GB on a full-table run. The CPU and I/O this costs FRR is part of
   every FRR row and **has not been measured**.

---

## Tracking

Epic `bgperf2-0y5`. Phases, each blocked by the one before: Phase 0 `bgperf2-0y5.1` (also blocked by
`bgperf2-es0` and `bgperf2-0ma`), Phase 1 `bgperf2-0y5.2`, Phase 2 `bgperf2-0y5.3`, Phase 3 `bgperf2-0y5.4`,
Phase 4 `bgperf2-0y5.5`. Phase 3 is also blocked by measurement plan Phase 7b (`bgperf2-8gg.10.2`), and
it no longer carries Phase 7c, which was dropped on 2026-10-01. Phase 3 is also blocked by
`bgperf2-9su` and `bgperf2-0l7`, two of the obligations of Phase 2.6.
