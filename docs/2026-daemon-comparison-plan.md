# 2026 daemon comparison plan

**Status: Phase 0 done; Phase 1 next. Written 2026-09-29.**

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

**Hardware, in one paragraph.** Phases 0–4 need **no new hardware**. They run on the current
campaign host class (16 vCPU / 61.44 GiB AMD EPYC 9R14, `m7a.4xlarge`). New hardware is needed
at exactly one point, the gate in §5. Only if that gate says so do we rent **three `m7a.4xlarge`
hosts in one cluster placement group**, to separate generator, target and monitor. **More memory
is not needed for this comparison at all.** It is needed only for the capacity-cliff work in §7,
which is a different question from "what changed between versions".

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
  memory on MRT.

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

**Tracked by:** `bgperf2-0y5.2` · **Status:** in progress

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
3. **`bgperf2-nit`: RustyBGP master's 4.8× memory.** Bisect by build, not by benchmark: build two
   or three commits between `2026-02` and master and measure only memory. This is small.

**Exit:** each of the three has a recorded answer, or a named reason it cannot be answered
without new runs.

Progress: item 2 done 2026-09-29; item 1 done 2026-10-01 (`e6d4f46`). Item 3 remains.

---

## 4. Phase 2 — instrument changes on the current host

**Tracked by:** `bgperf2-0y5.3` · **Status:** not started

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
2. **Pin each role to its own cores (new).** Today target, generators, monitor and receivers
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
3. **`bgperf2-ylb`: separate a slow generator from a back-pressured one.** Generator-side
   evidence of whether an injector was blocked on write or busy encoding. Without it, the five
   `tester` MRT cells stay unreadable however many times they run.
4. **Rebuild every image** with `prepare -f`. Every current image reports `recipe unknown`, so the
   recipe-drift check cannot vouch for any of them. Then run `verify` and require all ok.
5. **Fix the version matrix.** At the time of this phase, check upstream for releases newer than
   those below, and add at most one per daemon:

   | daemon | carried forward | candidate additions |
   |---|---|---|
   | FRR (`frr_c`) | 8.5, 9.1, 10.0, 10.7, master | newest stable if newer than 10.7 |
   | BIRD | 2.19.2, 3.3.2 (default and 4 threads) | master; newest 3.x if newer |
   | OpenBGPD | 8.8, 9.2 | newest upstream tag if newer |
   | RustyBGP | 2026-02, master | — (see Phase 1.3) |

   GoBGP is not in the matrix (Phase 0).
6. **Decision (operator): the MRT workload's NO_EXPORT peer (new, from Phase 1.1).** On the
   pinned RIB, one of the ten injected peers (AS 37100) tags every route NO_EXPORT. So each
   daemon exports a different share of the table: BIRD and OpenBGPD 1,056,779, FRR ~959k
   and varying by arrival order, RustyBGP the whole 1,081,178. Options:
   - **Keep it, and say so.** Within-daemon comparisons stand. Cross-daemon MRT timing is
     published with the export volume beside it, never as like-for-like.
   - **Skip that peer index when choosing injectors.** The workload changes, so the
     comparison's MRT rows no longer match the timing-validation campaign's except through
     a bridge.
   - **Strip NO_EXPORT at the injector.** This needs a bgpdump2 change and makes the replay
     less faithful to the RIB.
   - **Set `bgp bestpath compare-routerid` on FRR.** FRR would then match BIRD and
     OpenBGPD deterministically. It is a non-default FRR config, and it does not help
     RustyBGP.

**Exit:** tests green; a pinned smoke run and an unpinned smoke run both complete, with distinct
artifact names; all matrix images verify clean.

Progress: item 1 answered by the operator 2026-09-29 (change the monitor; the work is measurement
plan Phase 7). No other Phase 2 work has started.

---

## 5. Phase 3 — re-run on the current host class, then the hardware gate

**Tracked by:** `bgperf2-0y5.4` · **Status:** not started

**Requires measurement plan Phase 7 through 7b** (`bgperf2-8gg.10.2`). Phase 3 runs on the sink
monitor at its finer resolution, passed explicitly as `--monitor sink` if 7d has not yet flipped
the default.

**Host:** one `m7a.4xlarge`, the same class as the timing-validation campaign. The rows are
comparable with that campaign **through Phase 7's bridge block** (a different monitor is a different
instrument), and with nothing older (`benchmarks/baseline/baseline-benchmark.csv` was a different CPU).

Workloads, three passes each, matrix repeated as a whole (`docs/invariants/batch-passes.md`),
new run ID `2026-comparison`:

1. synthetic 50 × 100k, pinned;
2. MRT 10 × 1.05 M (bgpdump2), pinned;
3. **one bias check:** a small subset of both, unpinned, so pinned and unpinned can be compared
   on identical builds and the effect of co-location is measured rather than assumed.
4. **Phase 7's bridge block (7c, `bgperf2-8gg.10.3`), in the same block as item 3**, so the host
   is taken once. It uses the same cells with `--monitor gobgp` added as a second axis. Monitor
   and pinning stay separate dimensions of the cell identity, so each effect is read on its own.
   It publishes the offset the instrument alone introduces, which is what lets these rows be read
   against the timing-validation campaign's.

Every run is on-demand or checkpointed. A spot reclaim mid-block has already cost two blocks
their continuity (`docs/completed/2026-64gb-timing-validation-plan.md`).

### The hardware gate

After Phase 3, look at the MRT and fan-out cells and decide with this table:

| what Phase 3 shows | conclusion |
|---|---|
| MRT cells resolve to `target` (or are named cleanly), and the pinned/unpinned subset agrees within the published resolution | **No new hardware.** Co-location is not biasing the result. Publish from §6. |
| cells still resolve to `target_or_monitor`, **or** pinned and unpinned disagree by more than resolution | **Co-location is biasing the result.** Go to Phase 4 on new hardware. |
| export fan-out still shows host CPU saturation with the monitor and receivers pinned apart from the target | **Phase 4** — the receivers need their own host. |

Progress: —

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

---

## Tracking

Epic `bgperf2-0y5`. Phases, each blocked by the one before: Phase 0 `bgperf2-0y5.1` (also blocked by
`bgperf2-es0` and `bgperf2-0ma`), Phase 1 `bgperf2-0y5.2`, Phase 2 `bgperf2-0y5.3`, Phase 3 `bgperf2-0y5.4`,
Phase 4 `bgperf2-0y5.5`. Phase 3 is also blocked by measurement plan Phase 7b (`bgperf2-8gg.10.2`), and
it carries Phase 7c (`bgperf2-8gg.10.3`) out in its first block.
