# 2026 64 GB Timing Validation Campaign Plan

## Purpose

This plan defines the follow-up campaign that validates version differences
after timing instrumentation is repaired. It is deliberately bounded to the
existing local 64 GB host. No phase assumes that more RAM will become
available.

The campaign objective is:

> Repeat the highest-value synthetic and full-internet version comparisons
> with explicit tester completion timing, randomized order, and enough
> repetitions to distinguish stable differences from run-to-run noise.

This is not a continuation of `2026-baseline`. It uses new measurement
semantics and must use a new durable run identity.

## Dependency Gate

Do not start this campaign until the release gate in
[`bgperf2-measurement-implementation-plan.md`](./bgperf2-measurement-implementation-plan.md)
passes.

If the user invokes the campaign prompt before that gate passes, do not run a
benchmark. Report the first unmet gate and tell the user to use:

> continue the bgperf2 measurement implementation plan

## Fixed Campaign Identity

- run ID: `2026-timing-validation`
- results root: `results/2026`
- run root: `results/2026/2026-timing-validation`
- work directory: `/data/bgperf-work`
- host class: local 64 GB server -- settled on 2026-09-08 as **the machine this
  repository is checked out on**: 16 vCPU, 61.44 GiB, AMD EPYC 9R14
  (`m7a.4xlarge`). It is the closest available match to the host that produced
  `benchmarks/baseline/baseline-benchmark.csv`, matching it on memory (61.44
  GiB against 60.74) and **not on CPU**. The CPU difference
  costs nothing *within* this campaign, which re-runs its own comparisons under
  a new run identity -- but **no row here may be read against the
  `2026-baseline` CSV**, and nothing downstream refuses that comparison.

  **That machine is an EC2 spot instance, is reclaimed and replaced without
  warning, and more of the campaign will run on spot than not.** So "every
  block of this campaign runs there; a block run anywhere else is a second
  experiment" -- what this entry said until 2026-09-10 -- was never a rule the
  campaign could keep, and it had already been broken twice in silence when it
  was found: the manifest records `ip-172-31-23-67` for blocks 0 and 1,
  `ip-172-31-21-79` for block 2's first ten rows, and `ip-172-31-18-191` for
  the four rows that finished block 2 after the reclaim. Nothing failed, and
  nothing said so either. The rule that replaces it is the one the manifest can
  actually hold the campaign to:

  - **The host class is fixed; the host is recorded per block.** A replacement
    matching on **instance type, CPU model, vCPU count and memory** continues
    the campaign; anything else is a second experiment.
    `scripts/campaign_host_facts.py` writes those four into
    `metadata/manifest.json` under the block's own key -- instance type from
    IMDS, since it is the fact the rule turns on and the one fact `/proc`
    cannot show -- so the rule is checkable against the artifact it names
    rather than asserted here, which is how the two silent changes above were
    found at all. **Kernel, availability zone and instance ID are recorded and
    advisory**, deliberately: the root volume is fresh on every replacement, so
    a reclaim served from a newer AMI gives a different `uname -r` on identical
    hardware, and a rule that failed on it would order the whole campaign
    re-measured over a package update. A kernel change is a thing to *notice*
    when a block's numbers move, not a thing to refuse a block over.

    **Blocks 0-2 are only partly checkable against this rule**, and that is
    stated rather than left to be discovered: `instance_facts()` landed on
    2026-09-10 with the rule itself, so `host.instance` is absent from Blocks 0
    and 1 and from both of Block 2's carried `previous_entries`. Block 2's
    *final* entry does carry it (`m7a.4xlarge`, `i-0de8e1dd0d3dba94d`), because
    the third attempt -- the two re-measured rows -- ran at `020d7f5`, which is
    the revision that added it. So the instance type is recorded for the host
    that finished Block 2 and for nothing before it. What the earlier entries
    have is CPU model, vCPU count, memory and hostname, which agree across all
    four; the instance type those hosts ran under cannot be recovered. Blocks 3
    onward record it throughout.
  - **A host change *between* blocks is expected, recorded, and not a
    finding.** Blocks 2-4 and 5-7 are repetitions, and dispersion across
    passes is what the variance rule reads; an identically shaped replacement
    instance is part of that dispersion rather than a confound hidden inside a
    single comparison.
  - **A host change *within* a block is a finding, and belongs in that block's
    record.** A block's rows are read against each other and
    `create_batch_graphs()` draws them side by side, so a split there sits
    inside one comparison. It does not invalidate the block -- rows already
    measured are real, and discarding them buys one host at the price of an
    hour of machine time that the next reclaim may take anyway -- but the
    choice between resuming and re-measuring the block whole is the operator's,
    made out loud, per block, and the block's entry says which was taken and
    which rows each host produced.
  - **Only `/data` survives a reclaim.** It is a separate EBS volume, mounted
    from `/etc/fstab` by label with `nofail`, and it carries the repository,
    `results/`, Docker's `data-root` and `/home/ubuntu`. The root volume is
    fresh on every replacement, which is a second and harder reason the work
    directory is `/data/bgperf-work`: `/var/tmp` on this host is not merely
    small and shared with journald, it does not survive the instance. Verified
    on 2026-09-10 -- see the Block 2 record.

  A reclaim is "host instability" in the sense the 64 GB Safety Contract below
  means it, so it stops the active block and the block is reviewed before
  resuming. That review is where the third rule above is applied.
- MRT input: `mrt/rib.20260808.0000`
- address family: IPv4
- concurrent suites: never
- concurrent benchmark cells: never

The runner and manifest must capture the actual host memory, CPU, kernel,
Docker version, image identities, Git revision, measurement schema version,
order seed, and repetition ID. Do not assume those facts from this plan.

## 64 GB Safety Contract

- Preflight disk, available memory, swap use, images, and MRT input before each
  suite or repetition block.
- Run one benchmark cell at a time.
- Use `/data/bgperf-work`; do not place heavy working data on tmpfs, and do
  not use `/var/tmp` on this host -- it is on the 29 GB root, shared with
  journald and the OS, and a full-table MRT block can fill it hours in.
  (Docker's own storage is on `/data`, so it is not at risk; the root
  filesystem and the finished cells' artifacts are.)
- Flag a row when minimum free memory is below 20% of recorded host memory.
- Stop the active block after a low-memory row, swap growth, OOM, or host
  instability. Review before resuming.
- Do not increase peers or prefixes to compensate for an inconclusive result.
- Do not schedule historical larger-memory phases on this host.
- OpenBGPD 8.8 at `50 peers x 100k` is expected to approach the memory guardrail.
  Run it alone, preserve the result if it completes, and do not create a larger
  OpenBGPD cell.

## Target Matrix

Use these 14 target configurations unless the implementation gate records a
specific exclusion:

### BIRD

1. `2.19.2`
2. `3.3.2` with default worker-thread behavior
3. `3.3.2` with `threads: 4`
4. default image, with its reported version preserved

### FRR compiled

5. `8.5`
6. `9.1`
7. `10.0`
8. `10.7`
9. default image, with its reported version preserved

### OpenBGPD

10. `8.8`
11. `9.2`
12. default image

The default currently reports 9.2. Keep it as a provenance/default-tag check,
but do not count it as an independent software version in conclusions.

### RustyBGP

13. `2026-02`
14. default image, with its reported commit/version preserved

GoBGP is not in this target matrix. It remains the monitor. If it is restored
as a target later, add it through an explicit plan amendment rather than
silently changing this campaign.

## Canonical Workloads

### High-load synthetic

- 50 peers
- 100,000 unique IPv4 prefixes per peer
- BIRD tester
- no policy

This cell differentiated FRR versions, BIRD threading, RustyBGP builds, and
OpenBGPD resource use in `2026-baseline`. It is near the useful 64 GB ceiling
without requiring larger-memory hardware.

### Full-internet MRT

- 10 full-table peers
- approximately 1.05 million prefixes per peer from the pinned Route Views RIB
- ten bgpdump2 injectors, one per peer
- no policy

This is the primary realism workload. Reports and graph subtitles must call it
"10 full-internet peers using bgpdump2", not merely "10 × 1.05M".

## Statistical Contract

- Run three fresh repetitions of every canonical cell.
- Treat all three as new observations because the measurement schema differs
  from `2026-baseline`.
- Use a recorded deterministic seed or rotating block order so target versions
  do not always run in the same sequence.
- Preserve raw rows and event artifacts for every repetition.
- Summarize median, range, and coefficient of variation.
- Do not claim a meaningful version difference from overlapping noisy results
  merely because medians are ordered.
- Expand a comparison to five repetitions only when all existing rows pass
  qualification and observed variance could change the decision.
- Never expand the entire matrix automatically.

The base campaign contains:

- 14 configurations × 2 workloads × 3 repetitions = 84 cells.

The BIRD architecture screen below is additional and deliberately adaptive:
run one observation per screen cell, then repeat only the scenarios that
differentiate BIRD 2.19.2 from BIRD 3.3.2 or materially change CPU scaling.

One pass of the two workloads took about 98 minutes in `2026-baseline`. Three
fresh repetitions therefore imply roughly five hours of measured benchmark
time before review overhead. Run them in durable blocks rather than one
unattended monolith.

## Required Measurements and Findings

Every accepted row must include:

- target, tester, and monitor version/image identity;
- tester count;
- tester first-update and completion timestamps;
- injection duration and offered rate/count;
- first monitor-visible prefix;
- required route state reached;
- assurance duration;
- end-to-end convergence;
- target CPU and peak memory;
- host minimum idle and free memory;
- foreign CPU contention;
- tester errors/timeouts and missing peer completions;
- final route/session correctness;
- structured findings and qualification policy version.

**Amendment, 2026-09-11: what an MRT row below the check-point supplies.**
"Required route state reached" is keyed on `monitor_required_reached`, which
fires when the monitor's count reaches the run's check-point. For MRT playback
that check-point is `0.99 * -p` -- the per-injector cap, a guess, since ten
peers replay one RIB's overlapping views and their union is unknowable in
advance. Daemons legitimately export different shares of one RIB: measured on
the pinned file, RustyBGP 1,081,178, BIRD and OpenBGPD 1,056,779 each, every
FRR release ~961,000 and within 0.91% of each other across four releases and
master. So the requirement as written asks a daemon to meet a number nobody
could have set correctly, and five of each MRT block's fourteen rows cannot.

Such a row is accepted on `target_table.delivery` instead -- when the target
finished exporting and the monitor held it, derived off the completed series --
and this is stated here rather than left to the checker, because the campaign
may not silently re-define what a correct row is between blocks. What such a
row does **not** publish is `convergence_s`, `assurance_s` and
`post_injection_tail_s`, all three of which are intervals measured *from* that
event. It does publish `elapsed (s)`, every CPU, memory, contention and
correctness measurement, and `delivery`, which is derived for every run with an
export gauge and so is comparable across all fourteen rows rather than
appearing only where there is trouble.

The cost is bounded and recoverable. Every one of this plan's ten Primary
Questions is a within-daemon comparison, and all five FRR rows of a block carry
the same three absences, so none of those questions is affected; what cannot be
asked is FRR against BIRD on those three intervals specifically. And because
the artifacts retain the full per-poll series, an interval derived later off
`delivery` can be computed from the Block 5-7 artifacts already on disk,
without re-running a block. That is its own change set and is deliberately not
folded into this one, on the rule that a measurement ships before the rule that
consumes it.

The campaign must distinguish:

- tester-limited;
- post-injection target/monitor tail;
- observer uncertainty;
- host contention;
- memory pressure;
- correctness failure;
- missing measurement evidence.

## Block Progress

One line per block, moved when the block is accepted. `results/` is gitignored,
so this is the durable record of what was run and what it showed; the artifacts
themselves live under the run root and do not survive a fresh clone.

### Block 0: preflight and timing smoke -- **accepted 2026-09-08**

Ran at bgperf2 `0a334c0` on the campaign host, work directory
`/data/bgperf-work`, into `results/2026/2026-timing-validation/`.

- `doctor`: Docker 29.1.3, every image the 14 target configurations need is
  built (bird 2.19.2/3.3.2/default, frr_c 8.5/9.1/10.0/10.7/default, openbgp
  8.8/9.2/default, rustybgp 2026-02/default).
- `verify`: **19 images checked, all ok**, every daemon binary reported clean of
  gcov instrumentation. This is the check the unit suite cannot do and the one
  that would otherwise let an instrumented FRR into the matrix.
- Pinned MRT `mrt/rib.20260808.0000` (1,347,678,857 bytes) read by bgpdump2
  itself: maximum per-peer count **1,076,872**, consistent with the ~1.05M
  full-table peers Blocks 5-7 will replay.
- Synthetic smoke (4 peers x 10,000, BIRD 2.19.2, BIRD generator): converged,
  received 40,000 against a required 39,600, `elapsed (s)` 3.
- MRT smoke (2 bgpdump2 injectors x 10,000, BIRD 2.19.2): converged, received
  10,037 against a required 9,900 -- the union of two overlapping MRT peer
  tables is its own number, which is why an MRT row's offered count is evidence
  and not a target.
- Both rows **qualified** against the Acceptance Rules: three-role plus tool
  provenance, ordered and complete event streams, all generators complete,
  no tester error or timeout, peak foreign CPU 2%, min free memory 97% of the
  host.

What the two smokes show about the instrument, which is what this block is
for:

- **Both generators reported their own completion, and neither could time its
  own send at this size.** The BIRD generator offered all 40,000 prefixes by
  its first poll (`offered_in_interval` 0 of 40,000) -- the documented
  queue-side counter -- and the injectors' walks took 0.000844s and 0.011182s
  against a 1.0s poll. Both runs are therefore `unresolved`, by
  `injection_boundary_unresolved` and `injection_unresolved` respectively.
  **That is the expected verdict for these shapes and not a defect**: a run
  here that named a component would be the finding to investigate.
- **The signed post-injection tail did both jobs.** The synthetic run's was
  +1.006s against a 1.033s bound (inside the resolution, so no attribution);
  the MRT run's was **-0.257s** -- the monitor reached the required count
  before the slowest injector finished, which is ordinary at 99% of the table
  and is exactly the reading a clamp at zero would have destroyed.
- **The two injectors wrote 143,421 and 314,133 octets for the same 10,000
  prefixes**, confirming that the wire-side count is a property of the paths
  replayed rather than of the prefix count.
- The manifest records host memory (61.44 GiB), CPU (AMD EPYC 9R14, 16
  threads), kernel, Docker version, 19 image **IDs**, the bgperf2 revision and
  both schema versions, and the MRT input's size. Order seed and repetition ID
  have nothing to record here -- neither smoke declares repetitions or a
  shuffle -- and arrive with Blocks 2-7, whose configs are snapshotted under
  `metadata/configs/`.

### Block 1: generator calibration -- **accepted 2026-09-09**

Ran at bgperf2 `ad9c3de` on the campaign host, work directory
`/data/bgperf-work`. Four runs, one at a time, from two configs, each config
run twice with **byte-identical rendered input** (verified) and differing only
in which role `scripts/calibration_case.sh` starved from outside bgperf2.
bgperf2 is not told about the constraint and records nothing about it, so each
constrained case keeps the harness's own `case.log` beside its results.

| case | constraint | verdict | `elapsed (s)` |
|---|---|---|---|
| `tail-baseline/` | none | `unresolved` / `no_dominant_interval` | 3 |
| `observer-tail/` | monitor at 0.15 CPU | **`target_or_monitor`** / `post_injection_tail` | 16 |
| `tester-baseline/` | none | `tester` / `tester_limited` | 7 |
| `slow-tester/` | generators at 4 mbit egress | **`tester`** / `tester_limited` | 38 |

All four **qualified** against the Acceptance Rules: three-role plus tool
provenance, converged, ordered and complete event streams, both generators
complete in every run, no tester error or timeout, peak foreign CPU 5-10%, min
free memory 95-97% of the host. The pairs' route counts are identical within a
pair (100,222 against a required 99,000; 501,471 against 495,000), so nothing
about correctness moved with the constraint.

The block's exit criterion is met, and the two pairs meet it on different
evidence, which is the part worth keeping:

- **The tail pair separates on the verdict, and the generators prove where the
  constraint landed.** Fleet injection is 1.000s in both runs and the
  injectors' own numbers barely move (3,490,412 octets in both; 1,568,321
  against 1,559,052), while the signed tail goes from **-0.225s** to
  **+10.713s**. The unconstrained run has no interval to attribute and says so
  rather than naming a component -- the ambiguous case the criterion asks to be
  left unattributed -- and the constrained one names the observer end of
  `target_or_monitor`, which is what it starved.
- **Starving the observer degrades the instrument that measures it, and the
  published bound says so.** `post_injection_tail_resolution_s` went 1.032s ->
  2.096s: a monitor at 0.15 CPU is slower to answer `gobgp neighbor -j`, so its
  achieved cadence falls and the interval is qualified by the wider bound the
  loop actually achieved. The tail is still 5x that bound. That degradation is
  itself independent evidence the cap bound the container it named -- the
  target's own `max cpu %` cannot show it, since the target was untouched (29
  against 27).
- **The tester pair does not separate on the verdict, and was not qualified on
  one.** Both runs are `tester` via `tester_limited`: at 2 x 500,000 the
  unconstrained shape is already generator-bound. A slow-tester case cleared by
  its verdict would equally have been cleared by a constraint that bound
  nothing, which has happened on this host
  (`results/2026/phase6-calibration/interface-probe/`, where `tc` succeeded on
  a device the BGP session did not use). What qualifies it is that the imposed
  cap is recovered from the run's own numbers:

  | injector | unconstrained | at 4 mbit |
  |---|---|---|
  | `mrt-injector0` | 7,296,179 B / 1.290379s = **45.2 mbit** | 7,334,208 B / 14.111164s = **4.16 mbit** |
  | `mrt-injector1` | 16,196,887 B / 2.021436s = **64.1 mbit** | 16,000,488 B / 32.389886s = **3.95 mbit** |

  Both within 4% of a cap the tool knew nothing about, and reproducing Phase
  6's constrained numbers to five decimal places (14.111164 against 14.111817,
  32.389886 against 32.391424) on a run four weeks and one code revision later.
  The *unconstrained* rate is not reproducible in the same way -- 45.2 mbit
  here against 69.1 in Phase 6 for the same injector -- which is why it is
  published as a note and never asserted: it is the order of magnitude that
  separates a shaped session from an unshaped one, not the value.
- **Every generator has to recover the cap, not every generator that
  answered.** `octets_on_wire` is withheld unless every session in the
  container reported a written count and `reported_injection_s` is withheld for
  a multi-RIB session, so a generator dropped for want of one is a generator
  the case has no evidence about -- and clearing the case on the others would
  qualify it while an injector ran unshaped at 65 mbit. That is
  `calibration_case.sh`'s "counted per container, not something was
  constrained", on the reading side.
- **A constrained case is never resumed.** The progress file records that a
  cell completed and records nothing about whether the constraint bound, and
  the watcher that decides that cannot observe a cell it did not launch.

Two things the block cost that are worth stating. The calibration watcher is a
sibling of bgperf2 rather than a descendant, so its `docker`/`sudo`/`nsenter`
polling is charged to `max foreign cpu %`: 10% on the slow-tester case against
5-6% elsewhere, an order of magnitude under the threshold that would withhold a
verdict, but not nothing. And what stays unresolved is a property of the policy
rather than of this harness: a generator that is slow and a generator
back-pressured by a slow target produce the same evidence, and `tester_limited`
names `tester` for both (`bgperf2-bgg`).

### Block 2: high-load synthetic repetition 1 of 3 -- **accepted 2026-09-10**

Ran from `benchmarks/2026-timing-synth-rep1.yaml`: 14 target configurations at
50 peers x 100,000 prefixes per peer (5,000,000 distinct prefixes), BIRD
generator, no policy, one cell at a time, `order: shuffle` seed 20262. Work
directory `/data/bgperf-work`. **All 14 rows qualified.**

**It took three attempts on two hosts**, which is the first thing to know about
it. The first measured eight of the rows on `ip-172-31-21-79` and was ended by
an EC2 spot reclaim between cells. The replacement instance
`ip-172-31-18-191` resumed and measured four more, at which point two rows --
`bird 2.19.2` and `bird default` -- were rejected on `tester_health`; a third
attempt re-measured exactly those two and both came back clean. Every attempt
is in `metadata/manifest.json`: the last under
`blocks.block2-synthetic-rep1`, the earlier two under its `previous_entries`
with the rows each measured. The first two were measured at bgperf2 `4b43ebf`
and the last two rows at `020d7f5`, which changed the campaign scripts and the
plan documents and **no measurement code** -- the daemon under test, the
generator, the monitor and every published interval are identical across the
two revisions, and neither `check_timing_evidence.py` nor `summary.py` requires
the rows to agree on a revision.

| run | host | `elapsed (s)` | `max cpu %` | `max mem (GB)` | `min free mem (GB)` |
|---|---|---|---|---|---|
| bird 2.19.2 | 2nd | 90 | 101 | 0.559 | 49.4 |
| bird 3.3.2 (default threads) | 2nd | 117 | 102 | 1.087 | 49.0 |
| bird 3.3.2 (4 threads) | 1st | 108 | 200 | 1.110 | 48.9 |
| bird default (2.19.0-master) | 2nd | 92 | 101 | 0.559 | 49.8 |
| frr_c 8.5 | 1st | 91 | 112 | 8.254 | 42.5 |
| frr_c 9.1 | 1st | 94 | 112 | 8.199 | 42.5 |
| frr_c 10.0 | 1st | 90 | 111 | 7.655 | 43.6 |
| frr_c 10.7 | 1st | 84 | 112 | 6.284 | 44.3 |
| frr default | 2nd | 84 | 113 | 5.733 | 45.1 |
| openbgp 8.8 | 1st | 620 | 110 | 37.437 | 12.4 |
| openbgp 9.2 | 2nd | 733 | 127 | 18.533 | 33.2 |
| openbgp default (9.2) | 1st | 724 | 126 | 18.688 | 33.1 |
| rustybgp 2026-02 | 2nd | 65 | 1074 | 12.252 | 38.3 |
| rustybgp default | 1st | 154 | 1161 | 16.861 | 37.9 |

Every row converged, received 5,000,000 against a required 4,950,000, carried
three-role plus tool provenance, and produced an ordered and complete event
stream with its generator complete and no tester error or timeout. Every row's
verdict is `unresolved` via `injection_boundary_unresolved`, which is the
expected shape here and not a defect: the BIRD 2.19 generator's `Export updates
accepted` is queue-side and saturates before the first poll, so **no run in
this block can be attributed to a component**. That is a property of the
generator, recorded in Phase 5A and reached again from the campaign side; it
applies to Blocks 3 and 4 as well, and wire-side evidence would need a BIRD 3
generator, which the CLI cannot select today.

**What the two hosts cost, measured rather than argued.** The re-measurement
turned the host split into a controlled comparison, because it re-ran two
configurations that the *first* host had already measured:

| run | 1st host | 2nd host | difference |
|---|---|---|---|
| `bird 2.19.2` | 91s / 0.561 GB | 90s / 0.559 GB | 1.1% / 0.4% |
| `bird default` | 91s / 0.558 GB | 92s / 0.559 GB | 1.1% / 0.2% |

Same image, same configuration, same workload, different instance of the same
class. Independently, `openbgp default` and `openbgp 9.2` -- the same upstream
release through two image tags, which the shuffle happened to put one on each
host -- agree to 1.2% on `elapsed (s)` and 0.8% on `max mem (GB)`. Two
different constructions, both landing near 1%, which is well inside what the
variance rule is built to separate and is the campaign's own evidence for the
host-class rule in Fixed Campaign Identity. It is not a substitute for reading
Block 9's three passes.

**What rejected the two rows, and why re-measuring was the right answer.**
`tester_health` requires no tester error or timeout, and `find_errors()` counts
BIRD `<RMT>` log lines that are neither `NEXT_HOP` nor `Invalid route ...
withdrawn` -- so one and two such lines, out of 5,000,000 routes across 50
sessions, decided both rows. The lines themselves did not survive: `bench()`
wipes the work directory at the start of every cell, eleven cells ran after
them, and the host was reclaimed. Excluding those rows would therefore have
been an exclusion with a number rather than the exclusion with evidence the
Acceptance Rules ask for (`bgperf2-7ou`), and re-measuring two cells cost ten
minutes against the hour and a half a `--force` of the whole block would have
spent to discard twelve rows that had already qualified.

Two supporting observations. A separate `bird 2.19.2` run at the same size,
outside the campaign tree with its tester logs kept, also reported **0** tester
errors out of 247 million `<RMT>` lines -- all of them the excluded
`Invalid route ... withdrawn`, which is the target re-advertising to generators
running `import none`. And a scan of every CSV under `results/` finds one other
non-zero `tester errors` value in the project's history. Three clean runs of
these configurations do not prove the two counted lines were benign; what they
establish is that the condition is sporadic, and the rows in this block were
measured rather than excused.

**Re-measuring two cells is not a supported operation**, and what it took is
recorded because the next person to want it will find the same wall.
`--force` is the only re-measurement the runner offers and it discards the
whole block; `--resume` skips every cell the progress file holds, failed ones
included. The two cells were re-run by deleting their entries from
`<test>.progress.json` and the block's `RAN` marker, then re-entering through
`next`, which resumed onto the remaining twelve and ran exactly those two
through the normal harness -- preflight, `verify`, metadata capture, evidence
check, new marker. The one thing the harness could not fix afterwards is
attribution: the first host's carried entry still named the two rows it had
measured, and that was corrected by hand and marked `reconstructed`.

Three things the block cost, stated rather than left in the artifacts:

- **One row carries foreign CPU an order of magnitude above the block's floor,
  and the cause was the session reviewing it.** `bird 3.3.2 (default threads)`
  reports `max foreign cpu %` 9 against 1-4 elsewhere, from this session
  editing documents and running `bd` on the same host during that cell. Nine
  percent is 0.09 cores, an order of magnitude under the threshold that would
  withhold a verdict -- Block 1 recorded the same shape for its calibration
  watcher -- and the row qualified on every check. It is still contention the
  benchmark manufactured, and the rule it produces is that a block's review
  waits for the block. The two re-measured rows were run with the host left
  alone and came back at 4% and 2%.
- **The rustybgp target lost one `gobgp neighbor -j` read** and the run says so.
  The evidence is in that run's artifact at
  `instrument.target_neighbor_sampler` (`failed_reads` 1, with the gRPC error
  under `last_error`); `instrument_reads` is the *checker's* name for the check
  that reads it, and is what appears in `evidence/synthetic.txt`. The two are
  not the same string and neither finds the other. The consequence is that the
  neighbour checkpoint may have been reached late. That is the guard from
  `5251847` doing exactly what it was added for (`bgperf2-sl1`) -- before it,
  the sampler died silently and froze the counts.
- **OpenBGPD 8.8 approached the memory guardrail and cleared it**, as the
  config predicted: 37.4 GB peak, `min free mem` 12.4 GB, which is 20.2% of the
  61.44 GB host against a 20% floor. It ran alone, like every cell. Nothing
  swapped. Its own tester logs are the other pressure: one run of this shape
  writes ~23 GB into the work directory, against the ~5 GB
  `docs/invariants/host-and-environment.md` records,
  so a block needs headroom nearer 25 GB per cell.

### Block 3: high-load synthetic repetition 2 of 3 -- **accepted 2026-09-10**

Ran from `benchmarks/2026-timing-synth-rep2.yaml`: the same 14 target
configurations at 50 peers x 100,000 prefixes per peer, BIRD generator, no
policy, one cell at a time, `order: shuffle` seed 20263. Work directory
`/data/bgperf-work`. **All 14 rows qualified**, in one attempt, on one host, at
one revision (`acb3fa2`) -- `previous_entries` is empty, which is the first
thing this block has that Block 2 did not.

The config is repetition 1's with the test `name` and the `seed` changed and
nothing else; `diff` the two `tests:` mappings and that is all that comes back.
The *procedure* is shared rather than copied -- `run_synthetic_repetition()` in
the runner serves Blocks 2 and 3 -- because the three passes are read together
in Block 9 as the dispersion of one cell, so a step that drifted between them
would be a difference in how the passes were measured arriving inside the
statistic meant to measure run-to-run noise.

**The seed does not fix the order by itself**, which matters for anyone
rebuilding a pass later. `batch_shuffle_key()` digests
`<seed>:<batch_cell_id(test_name, cell)>`, so the permutation is a function of
the seed, the test `name` and every target field. Recovering this pass's
sequence needs this config, not the number alone; renaming a test while keeping
its seed re-sequences the block in silence. It is also the second reason
repetition 2 ran in a different order from repetition 1, so a shared
permutation was never a risk the seed rule alone had to carry.

| run | `elapsed (s)` | `max cpu %` | `max mem (GB)` | `min free mem (GB)` | `max foreign cpu %` |
|---|---|---|---|---|---|
| bird 2.19.2 | 90 | 101 | 0.559 | 49.5 | 2 |
| bird 3.3.2 (default threads) | 118 | 109 | 1.083 | 49.2 | 2 |
| bird 3.3.2 (4 threads) | 109 | 210 | 1.117 | 48.9 | 2 |
| bird default (2.19.0-master) | 91 | 102 | 0.559 | 49.8 | 3 |
| frr_c 8.5 | 92 | 112 | 8.279 | 42.5 | 2 |
| frr_c 9.1 | 95 | 112 | 8.197 | 42.5 | 2 |
| frr_c 10.0 | 91 | 112 | 7.646 | 43.3 | 4 |
| frr_c 10.7 | 85 | 111 | 5.772 | 45.0 | 2 |
| frr default | 86 | 113 | 5.719 | 44.9 | 2 |
| openbgp 8.8 | 624 | 114 | 37.435 | 12.4 | 2 |
| openbgp 9.2 | 727 | 126 | 18.713 | 33.1 | **51** |
| openbgp default (9.2) | 737 | 126 | 18.644 | 33.2 | 3 |
| rustybgp 2026-02 | 68 | 1074 | 12.641 | 37.8 | 2 |
| rustybgp default | 152 | 1153 | 12.963 | 41.7 | 7 |

Every row converged, received 5,000,000 against a required 4,950,000, carried
three-role plus tool provenance, and produced an ordered and complete event
stream with its generator complete and no tester error or timeout. Every
verdict is `unresolved` via `injection_boundary_unresolved`, exactly as in
repetition 1 and for the same reason: the BIRD 2.19 generator's `Export updates
accepted` is queue-side and saturates before the first poll, so no run in this
block can be attributed to a component. Six rows carry a `host_cpu_saturated`
note, against seven in repetition 1 and on much the same rows -- that is the
benchmark's own load, and it is a note rather than a rejection.

**The two passes reproduce on `elapsed (s)` and do not fully reproduce on
memory**, which is worth stating now even though the dispersion is Block 9's
question:

| run | rep 1 | rep 2 | `elapsed` | `max mem` |
|---|---|---|---|---|
| bird 2.19.2 | 90s / 0.559 GB | 90s / 0.559 GB | 0.0% | 0.0% |
| frr_c 10.7 | 84s / 6.284 GB | 85s / 5.772 GB | +1.2% | **-8.1%** |
| rustybgp 2026-02 | 65s / 12.252 GB | 68s / 12.641 GB | +4.6% | +3.2% |
| rustybgp default | 154s / 16.861 GB | 152s / 12.963 GB | -1.3% | **-23.1%** |

Twelve of the fourteen are within +/-2.4% on `elapsed (s)`, and the outlier is
`rustybgp 2026-02` at +4.6% -- three seconds on the block's shortest run, which
the shuffle placed second, on the coldest cache of the pass. `max mem (GB)` is
the column that moves: `rustybgp default` differs by 3.9 GB between passes and
`frr_c 10.7` by 0.5 GB, on identical images and identical workloads. Two
observations cannot say whether that is dispersion or an order effect, and this
is precisely what the third pass and the variance rule are for -- but a memory
comparison drawn from a single pass of either daemon would have been reported
with a confidence neither row supports.

Three things the block cost, stated rather than left in the artifacts:

- **One row carries half a core of foreign CPU that nothing can attribute.**
  `openbgp 9.2` reports `max foreign cpu %` 51 against 2-7% on the other
  thirteen. It qualified: `CONTENTION_PERCENT` is one core, so neither
  `findings.py`'s `foreign_cpu_contention` nor `warn_if_machine_is_busy()`
  fired -- and because the process names are published **only** as that
  finding's `evidence.processes`, a peak at half the threshold reaches the CSV
  as a number with no names at all. By review time the competitor had exited.
  This session was idle apart from a `tail -f | grep` on the runner's log
  during that cell, which is not half a core, so the honest answer is that the
  cause is unknown and unrecoverable. That is the "names travel with the
  number" rule failing from *below* the threshold rather than at it, and it is
  filed as `bgperf2-5si`. The row is kept: 51% is 0.51 cores against a 16-core
  host, its `elapsed (s)` is within 0.8% of repetition 1's, and excluding it
  would be an exclusion with a number rather than with evidence.
- **Two rows each lost a single neighbour-sampler read**, and both say so in
  `instrument.target_neighbor_sampler`. `rustybgp default` lost one to the
  gRPC error Block 2 also recorded; `openbgp 9.2` lost one to a
  `UnicodeDecodeError` on a 0x80 byte in `bgpctl -j show neighbor` output,
  which is new and is filed as `bgperf2-qhx`. Both are one read out of
  hundreds, both were contained by the guard from `5251847` rather than
  freezing the counts, and the consequence a lost read carries -- a neighbour
  checkpoint reached late -- lengthens the assurance window and shortens
  nothing. Both rows converged on the full 5,000,000.
- **OpenBGPD 8.8 cleared the memory guardrail by the same margin as before**:
  37.4 GB peak, `min free mem` 12.4 GB, 20.2% of the 61.44 GB host against a
  20% floor. Repetition 1 measured 12.4 GB as well. Nothing swapped. Two passes
  agreeing to within a tenth of a point on the row nearest a hard safety limit
  is the useful part: the margin is thin and it is also stable.

  **Corrected while Block 4 was being built:** this entry originally went on to
  say "the shuffle put it last here, on the fullest work directory of the pass,
  and it still cleared", and rep2's own config header made the same claim. It
  is false, and it was written where it would be read as evidence that the cell
  nearest the guardrail had survived worst-case pressure. `bench()` calls
  `shutil.rmtree()` on `<--dir>/<bench-name>` at the start of every cell that is
  not a `--repeat`, and `batch()` never sets `repeat` for these targets, so the
  fourteenth cell of a pass starts on the same empty work directory as the
  first -- the previous cell's ~23 GB of tester logs included. What accumulates
  across a block is `results/`, a few MB. The measurement is unaffected and the
  row stands; what changes is that a `min free mem` from this cell is
  comparable across the three passes wherever the shuffle happens to place it,
  which is what Block 9 needs of it. The wrong claim is quoted here rather than
  deleted, on the rule the decision log follows.

  `benchmarks/2026-timing-synth-rep2.yaml` keeps the wrong sentence, and that
  is deliberate rather than an oversight: `campaign_render_config` `cmp`s a
  config against its snapshot under `metadata/configs/original/` and refuses on
  any difference, so a comment-only edit to an accepted block's input would
  make a later `--force` re-run of Block 3 fail with "run ID already has a
  different original config". The correction lives here and in
  `2026-timing-synth-rep3.yaml`, which has not run yet.

The block's three leftover containers were removed after the evidence was
published -- `bench()` leaves the last cell's containers up, and this one held
an OpenBGPD target with a 5,000,000-route table, i.e. 37 GB of the host tied up
until whatever ran next. Nothing published depends on them.

### Block 4: high-load synthetic repetition 3 of 3 -- **accepted 2026-09-11**

Ran from `benchmarks/2026-timing-synth-rep3.yaml`: the same 14 target
configurations at 50 peers x 100,000 prefixes per peer, BIRD generator, no
policy, one cell at a time, `order: shuffle` seed 20264. Work directory
`/data/bgperf-work`. The config is repetitions 1 and 2's with the test `name`
and the `seed` changed and nothing else, and the procedure is the same
`run_synthetic_repetition()` that served Blocks 2 and 3.

**All 14 rows qualified, on the second attempt, at revision `5494806`.** One
host throughout (`i-0de8e1dd0d3dba94d`, `m7a.4xlarge`) for both attempts, so
`previous_entries` is empty -- the first attempt's rows were pruned from the
manifest when `--force` deleted them, which is the behaviour that keeps the
manifest from naming results that no longer exist.

| run | `elapsed (s)` | `max cpu %` | `max mem (GB)` | `min free mem (GB)` | `max foreign cpu %` |
|---|---|---|---|---|---|
| bird 2.19.2 | 90 | 101 | 0.559 | 49.6 | 7 |
| bird 3.3.2 (default threads) | 116 | 110 | 1.086 | 48.9 | 8 |
| bird 3.3.2 (4 threads) | 109 | 200 | 1.117 | 49.2 | 5 |
| bird default (2.19.0-master) | 93 | 102 | 0.558 | 49.5 | 6 |
| frr_c 8.5 | 96 | 108 | 8.273 | 42.3 | 9 |
| frr_c 9.1 | 95 | 111 | 8.166 | 42.7 | 5 |
| frr_c 10.0 | 93 | 109 | 7.640 | 43.2 | 9 |
| frr_c 10.7 | 86 | 110 | 5.717 | 44.7 | 12 |
| frr default | 86 | 112 | 5.708 | 44.8 | 7 |
| openbgp 8.8 | 625 | 115 | 37.437 | 12.4 | 13 |
| openbgp 9.2 | 747 | 126 | 18.536 | 33.0 | 11 |
| openbgp default (9.2) | 752 | 124 | 18.630 | 33.2 | 10 |
| rustybgp 2026-02 | 66 | 1149 | 12.572 | 37.8 | 14 |
| rustybgp default | 148 | 1152 | 13.194 | 39.7 | 7 |

Every row converged, received 5,000,000 against a required 4,950,000, carried
three-role plus tool provenance, produced an ordered and complete event stream
with its generator complete, and reported **zero** tester errors and timeouts.
Every verdict is `unresolved` via `injection_boundary_unresolved`, as in both
earlier passes and for the same reason. Seven rows carry a `host_cpu_saturated`
note -- the benchmark's own load -- against six in repetition 2 and seven in
repetition 1. `max foreign cpu %` is 5-14% across all fourteen, with no repeat
of repetition 2's unattributable 51% on `openbgp 9.2`. One row, `rustybgp
default`, lost a single neighbour-sampler read to the same gRPC error Blocks 2
and 3 recorded (`bgperf2-sl1`); it is one read of hundreds, it was contained by
the guard rather than freezing the counts, and the row converged on the full
table.

**The first attempt and why it was discarded.** The block first ran at
`ce1d814` and produced 14 rows, 12 of which qualified. `rustybgp default` and
`bird default` were rejected on `tester_health` with 2 and 1 tester errors --
the first nonzero counts in 28 rows of Blocks 2 and 3 -- and both had converged
on the full 5,000,000 with complete generator evidence. Nothing could say what
those three lines were: `bench()` rmtree's the work directory at the start of
the next cell, so the counts reached the CSV and the logs behind them were gone
before anyone read the rows, and a re-measure would have destroyed them
identically. That is `bgperf2-7ou`, and rather than accept an exclusion nobody
could argue with or re-measure blind, the capture was built first (`5494806`,
`<prefix>.tester-health.json`) and the block re-run under it. The errors did not
recur -- all 14 rows clean -- which is itself the useful result: they are
transient rather than a property of those configurations, and if they appear in
a later block the lines will now be on disk and quoted in the rejection.

**What the discarded attempt measured, recorded here because nothing else
holds it.** `--force` deleted its artifacts and pruned its rows from the
manifest, so these four numbers exist only in this paragraph, and two of them
decide a question Block 9 would otherwise get wrong:

| run | rep 1 | rep 2 | rep 3 attempt 1 (discarded) | rep 3 accepted |
|---|---|---|---|---|
| `frr_c 10.7` `max mem` | 6.284 | 5.772 | **6.268** | 5.717 |
| `rustybgp default` `max mem` | 16.861 | 12.963 | **13.787** | 13.194 |

`frr_c 10.7` is **bimodal, and neither mode is a host or an order effect**.
Both rep 3 attempts ran the same image at the same shuffle position (14) on the
same instance, and came out 9.6% apart -- 6.268 and 5.717 -- landing one in
each cluster (~6.27-6.28 and ~5.72-5.77). The Block 3 record left this open as
"dispersion or an order effect"; it is neither, and a three-pass `stdev` will
describe it as ordinary spread when the underlying distribution has two modes.
It is worth reading the per-pass observations rather than the summary statistic
for this row. Note also that both of Block 2's memory outliers (this row and
`rustybgp default`) were measured on the first of that block's two hosts -- but
only 2 of that host's 8 rows are outliers and the other 6 agree closely with
the later passes, and the discarded attempt reproduces `frr_c 10.7`'s high mode
on the *second* host, so the reclaim does not explain either.

`rustybgp default` is the block's widest cell either way: 16.861 / 12.963 /
13.194 across the three accepted passes is a 15.3% CV, and the discarded
13.787 sits inside that range. Three of the four measurements are 12.96-13.79
and repetition 1's 16.861 stands apart from all of them.

**Everything else reproduces tightly.** `elapsed (s)` CV is at or under 2.8% on
all fourteen rows and at or under 2% on twelve; `max mem (GB)` CV is at or under
0.6% on twelve of fourteen, the exceptions being the two rows above.
`openbgp 8.8` -- the row nearest the 20% free-memory guardrail -- measured
`min free mem` 12.392, 12.409 and 12.4 GB across the three passes at shuffle
positions 7, 14 and 4, with the discarded attempt's 12.434 GB as a fourth
reading. A 42 MB spread over four runs at three positions: the margin is thin
(20.2%) and it is not moving, and its independence from position is the
empirical form of the correction below.

**Corrected in this block:** the "fullest work directory" claim in the Block 3
record and in rep 2's config header. See that entry.

### Block 5: full-internet MRT repetition 1 of 3 -- **accepted 2026-09-11**

Runs from `benchmarks/2026-timing-mrt-rep1.yaml`: the plan's 14 target
configurations against the pinned Route Views RIB `mrt/rib.20260808.0000`, ten
bgpdump2 injectors on 10 full-internet peers, no policy, one pass, one cell at
a time, `order: shuffle` seed 20265 -- the campaign's mechanical year+block
rule, continuing 20262/20263/20264. Work directory `/data/bgperf-work`. The
procedure is `run_mrt_repetition()`, shared by Blocks 5-7 the way
`run_synthetic_repetition()` is shared by Blocks 2-4 and for the same reason.

**`prefixes: 1_050_000` is the whole table in this block, not a per-peer
block**, and it is the one axis that does not mean here what it means in Blocks
2-4. `gen_conf()` takes the monitor's check-point straight from `-p` for an MRT
injector rather than computing `n * p`, because the ten peers replay one RIB's
overlapping views instead of disjoint blocks off a shared iterator. So
`required` is 1,039,500 here against 4,950,000 there, and the CSV's `prefixes
per peer` column is the whole table in Blocks 5-7. Block 9 must not read the
two blocks' prefix axes as one scale.

**Ten of the fourteen rows have no second witness, and that is the block's
known risk.** `ConvergenceTracker`'s fourth rule -- a monitor decline past
`DROP_FRACTION` is not route loss while the target's own `best_paths` is within
`DROP_FRACTION` of its peak -- is what made this exact workload reproducible,
and it needs the target's own table gauge. Only BIRD answers:
`Target.get_table_witness()` returns `None` and `bird.py` is the sole override.
The four series `tests/test_convergence_mrt_replay.py` replays are all BIRD
3.3.2, and three of them were reported FAILED by a monitor-only rule. Whether
`frr_c` (5 rows), `openbgp` (3) and `rustybgp` (2) overshoot the same way on
ten overlapping full tables was **not** known from any recorded run, so it was
measured before the block was launched rather than discovered fourteen cells
in.

**What the probe found: the witness is not needed here, and something else is
in the way.** Six runs on the campaign host against the pinned RIB, outside the
campaign run root (results in a scratchpad, so nothing below is a campaign
row):

| target | received | vs required 1,039,500 | elapsed |
|---|---|---|---|
| bird 3.3.2 (control) | 1,056,779 | clears | 46s |
| openbgp 9.2 | 1,056,779 | clears | 79s |
| rustybgp 2026-02 | 1,081,178 | clears | 25s |
| frr_c 10.7, pass 1 | 961,276 | **short by 78,224** | 103s |
| frr_c 10.7, pass 2 | 961,201 | **short by 78,299** | 103s |
| frr_c 8.5 | 958,234 | **short by 81,266** | 103s |

No witness-less target failed the way the BIRD series did: none of them
overshot and settled past `DROP_FRACTION`, and OpenBGPD settled on exactly the
1,056,779 the recorded BIRD runs do. So the monitor-only rule handles this
workload for all three families, and Block 5 does not need the gauge extended
to them. That was the question; this is the answer.

**FRR is short, reproducibly, and it is not losing routes.** Asked directly
while a converged run was still up, `show bgp ipv4 unicast statistics` reports
1,080,985 prefixes and 10,497,949 paths -- the same two numbers BIRD's own
table witness reports for this workload -- while `show bgp ipv4 unicast summary
json` reports `pfxSnt` 961,201 to every one of its eleven peers, the monitor
included. FRR's export counter and the monitor agree exactly. So FRR holds the
whole table and withholds ~119,784 prefixes from export, identically to every
peer, with no export policy in the generated `bgpd.conf`. Two FRR versions
three releases apart do it within 0.3% of each other, so it is version-wide and
all five `frr_c` rows of each MRT block are affected. The mechanism is not
identified -- `bgperf2-cw6`.

That is a different blocker from the one this section was written about, and it
is not a convergence-rule question: the runs converge. It is a correctness
question, because `check_timing_evidence.py` rejects a row whose `received` is
below `required`, and `required` here is `0.99 * -p` -- a proxy derived from
the injector cap, not from the union the RIB actually holds. **It is left
unanswered rather than answered cheaply.** Lowering the MRT check-point to fit
would be a rule fitted to the run in front of it, which is how all three
convergence rules were broken; and the campaign may not silently re-define what
a correct row is between blocks. **Measured next, and it changes the reading above.** Justin's question -- do
daemons not all advertise different amounts anyway, and does FRR do this across
versions -- is answered yes twice, which moves the fault from FRR to the
yardstick. All five FRR configurations, same host, same RIB, same day:

| FRR | advertises | `elapsed (s)` |
|---|---|---|
| 8.5 | 958,234 | 103 |
| 9.1 | 958,962 | 103 |
| 10.0 | 965,159 | 102 |
| 10.7 | 961,276 / 961,201 | 103 |
| default (10.8.0-dev) | 956,337 | 87 |

A **0.91%** spread across four releases and master, against the 9% that
separates FRR from BIRD and OpenBGPD. So FRR is self-consistent and the five
`frr_c` rows of an MRT block are doing the same work as each other; what
differs is FRR against other daemons, which is a real property of best-path
selection and export rules rather than a fault in any row. Across the four
daemons the same RIB yields three distinct totals -- 1,081,178 (RustyBGP),
1,056,779 (BIRD and OpenBGPD, agreeing exactly) and ~961,000 (FRR).

**Every one of this plan's ten Primary Questions is a within-daemon
comparison**, so none of them is damaged by that. `required` is the only thing
that objects, and it asks an absolute question -- "did this daemon advertise at
least 99% of the injector cap" -- that no single number can ask fairly of four
daemons whose export rules differ. It is a check-point, and it works as one:
the four other daemons reach it and FRR converges without it, on the neighbour
checkpoint and stability. It is its use as a *correctness test* in
`check_timing_evidence.py` that does not carry over to MRT.

What FRR's 9% is remains unexplained and is still worth explaining
(`bgperf2-cw6`); "daemons differ" covers the 2.3% between RustyBGP and the
other two comfortably and covers 9% less well. But unexplained is not
incorrect, and it does not block a within-daemon comparison.

These rows also preview Question 2: 10.7 is not slower than 8.5, 9.1 or 10.0 on
full-internet playback -- all four are 102-103s -- and master is ~15% faster at
87s. Preliminary, one pass each, outside the campaign run root.

**Settled 2026-09-11, and the answer was already in the blog series this
project comes from.** The filtering post met the identical problem -- "when
filtering, we now don't know when all the prefixes that will be sent have been
received because we don't know what will get filtered" -- and answered it by
moving the completion criterion off the monitor's absolute count and onto the
target's own account, in two halves: the target has received everything from
every neighbour, and the target has sent it on to the monitor. The first half
has been in the code ever since as the End-of-RIB neighbour checkpoint. The
second half had no reader, which is why `monitor_required_reached` still keyed
on an absolute. MRT playback is the same shape one case over.

So the fix was not a new rule but the missing reader plus the existing rule
applied to a second case:

- `frr.table_witness()` publishes `exported_to_monitor` (the monitor session's
  own `pfxSnt`) and `imported_paths` (the per-peer `pfxRcd` sum), off the
  `sh ip bgp summary json` FRR's neighbour counters already come from -- one
  exec, one instant. It withholds `best_paths` deliberately: FRR's two
  table-size numbers disagree and neither is established to mean "prefixes
  holding a selected best path", and `None` is how `convergence.py` is told to
  attest to nothing, so **how an FRR run converges did not change**.
- `monitor_required_reached` was **not** changed, and that is the part of this
  that did not work. See "What was tried and backed out" below.
- MRT correctness is consistency plus a size floor, not an absolute: the
  monitor's count against the target's own export count, and the target's
  accepted-path count against what the generators offered. The check-point is neither necessary nor
  sufficient on its own -- it is about 4% below the union the ten peers hold --
  so the floor applies as well as it wherever there is a gauge, and clearing it
  is the fallback where there is none, which is how OpenBGPD and RustyBGP rows
  are still judged.

**Verified on the campaign host**, three targets on the pinned RIB, all
qualified: `bird 3.3.2` 1,056,779 both ends, `frr_c 10.7` 958,217 both ends
with 10,497,949 of 10,500,000 offered paths accepted, `openbgp 9.2` 1,056,779
at or above the check-point. FRR recovered `convergence_s`, `assurance_s` and
`post_injection_tail_s` -- the four Required Measurements it had been losing --
and a real `limiting_component` (`target_or_monitor`) in place of
`inconclusive`.

**What was tried and backed out: a second rule for
`monitor_required_reached`.** The event fires when the monitor's count reaches
the check-point, so a daemon that never reaches it -- FRR, here -- publishes no
`convergence_s`, `assurance_s` or `post_injection_tail_s` at all. A second rule
was built on the target's own account (neighbour checkpoint set, plus the
monitor caught up to an export count that had stopped moving) and verified: all
three targets qualified and FRR recovered the four measurements and a real
`limiting_component`. It was then removed, and the two reasons are worth
keeping because they bound what a correct version has to do:

1. The first version required only `monitor_accepted >= exported`, which is not
   delivery while the target is still exporting. The witness is resampled onto
   the monitor's polls and can be seconds old, so a fast climb lets the monitor
   overtake a stale export count and the event fires near the start of the run.
   It did not bite the measured FRR case only because bgpdump2's injectors were
   blocked on FRR draining -- 75s to complete against OpenBGPD's 2.4s -- so
   End-of-RIB and the checkpoint arrived at the end. Adding "export flat across
   two consecutive reads" fixed that case.
2. It did not fix the class. The neighbour checkpoint says every generator has
   *sent* everything, not that the target has finished *exporting*, so one poll
   in which the export count does not advance with the monitor drained to that
   same number still stamps the event mid-delivery -- at a fraction of the
   table, permanently, since the event is recorded once and nothing in the
   artifact says which rule supplied it.

A mis-dated headline timing is worse than a missing one, and this rule had two
design flaws found in two rounds, so it is not being patched a third time under
a deadline. **The sound version is retrospective**: whether the target finished
exporting is only decidable once the series is complete, and the artifact is
written at the end. That means a derived measurement computed off the recorded
`target_table` series -- named as its own thing, not synthesised into the event
stream as though it had been observed -- plus `event_coverage` accepting it in
place of an event that legitimately cannot fire. That is its own change set.

So an MRT row from a daemon below the check-point still publishes none of the
three intervals, and `check_timing_evidence.py` still rejects it on
`event_coverage`. **Block 5's five `frr_c` rows are therefore still blocked**,
for a reason one layer in from where this started: not a bad correctness test
any more, but four measurements that genuinely are not being taken.

**The derived measurement has since landed: `target_table.delivery`**
(`measurements.delivery_metrics()`), the first of the two change sets that
release this hold. It is the earliest reading of the terminal export plateau at
or after which the monitor holds it -- retrospective, so "and it never changed
again" is checked against the completed series rather than assumed from the
samples in hand, which is precisely what both backed-out rules could not do. It
withholds with a named reason rather than estimating, on ten conditions: no
gauge or no samples, a final count of zero, a truncated series, a plateau of a
single reading, a withheld poll inside the plateau, a carried reading in it, a
plateau that cannot be dated at all, a stale reading past the carry bound, a
monitor that never drew level with the target's own export count, and samples
carrying no times.

**Five of those ten came out of review of the first version**, each
reproduced against the shipped function rather than argued: an all-zero series
resolved as a completed delivery at its first poll (`0 >= 0` draws the monitor
level, and `bench()` writes a FAILED run's samples exactly like a converged
one's); a frozen sampler resolved, because the age bound does not implement the
rule it states -- a dead poll thread's carried readings are 1s..5s old and all
*within* bound, so carried is now decided on the read timestamps; a withheld
poll inside the plateau was invisible to that same age rule; a crossing that
happened on a withheld poll returned `monitor_never_drawn_level` for a session
the document's own `monitor_final` disproved; and samples without times fell
through to a null reason beside a null answer. None of the 34 resolved runs
moves as a result, which is the point: the refusals added are for shapes the
recorded evidence does not contain and a failed or interrupted run does.

**And one of those five fixes was itself wrong, which a second review round
found.** The carried-reading refusal was written strictly -- every sample in
the plateau had to be its own read -- on the evidence that all 34 resolved runs
satisfy it. That evidence only covers one sign. The target's poll and the
monitor's are independent loops, so whenever the target's CLI read is the
*slower* of the two a reading spans two monitor samples and is carried twice;
11 of the 39 recorded runs contain such a duplicate somewhere in their series,
and it is likeliest on precisely the large-table runs this measurement exists
for. Strictness would therefore have withheld `delivery` from the Block 5 rows
it was built to rescue, while naming a dead sampler that was alive. The rule is
now two *distinct* reads -- `still_changing`'s rule in read-space -- with the
age bound covering staleness. Recorded because the shape of the mistake is the
reusable part: a bound justified by the runs in front of it, which covered one
direction of a two-directional race.

Two further findings from that round were declined rather than fixed, with the
evidence that decided them:

- **The last reading is the table, not the peak.** A run whose export settles
  below its peak is dated to where it settled. 11 of the 39 recorded runs end
  1.35%-1.55% under their peak and every one settles on exactly 1,056,779 --
  what BIRD and OpenBGPD both converge to on this RIB -- so the peak is a
  convergence overshoot and the last reading is the true table. Taking the peak
  would wait for the monitor to draw level with a count the target does not
  hold, withholding every MRT run. A target that delivered and then really lost
  routes is dated to the loss, and is failed by `ConvergenceTracker`'s drop
  rule and rejected by the checker before that number is read.
- **Whether the table was the right size is not judged there.**
  `delivery_metrics()` is handed samples and no denominator, so a target
  stalled at a fraction of the RIB has a terminal plateau like any other. That
  is `check_timing_evidence.py`'s call, which knows the check-point and what
  the generators offered. The zero case is refused for a different reason --
  the rule degenerates, since `0 >= 0` makes the monitor trivially level --
  and that is the line between the two.

Validated against the 39 recorded artifacts on this host that carry a witness
series. 34 resolve and 5 withhold, and the five now say which of two things
happened to them rather than sharing one reason: four are pre-`witness_age_s`
artifacts whose readings cannot be dated at all (`gauge_undated`), and the
fifth is a calibration MRT run whose target sampler froze and was carried for
18.1s (`gauge_carried_across_plateau`) -- the frozen-sampler case the rule
exists for, found in the recorded evidence rather than constructed. In every resolved run `complete_s` lands at or after
that run's own `monitor_required_reached` and at or before its
`convergence_confirmed`, which is the invariant a sound answer has to hold.

**Not *strictly* between, and the exception is the ordinary case rather than a
defect.** An earlier draft of this paragraph claimed strict ordering; 5 of the
34 resolved runs break it, by 140 to 499 *nanoseconds*. Those are runs where
the monitor drew level with the target's export count on the very poll that
crossed the check-point -- the same-poll case described below -- so the two
numbers are one instant, and which side of it they land on is decided by
`target_table.samples` storing `monotonic_s` rounded to six places while the
event carries the raw value. A comparison of the two must therefore be written
as an ordering at poll resolution, never as a strict inequality; anything
tighter is reading the rounding.

It is emphatically **not** `convergence_s`, and the same artifacts say why: on a
synthetic run the check-point is the whole table and the two land on the same
poll, while on MRT playback the check-point is the per-injector cap and the
target keeps exporting well past it -- 16.85s against 36.36s on one recorded
2-injector 500,000-prefix run. Publishing the derived point as `convergence_s`
would move every MRT row by that gap. It is therefore derived for *every* run
with an export gauge, so the column is comparable across daemons rather than
appearing only on the rows that lost the event.

**The hold is released, and what released it.** `check_events()` now accepts a
*resolved* `target_table.delivery` in place of `monitor_required_reached`, for
an MRT run only, and `BLOCK_HELD[5]` is gone. Three limits hold that up: only
for an MRT generator, since a synthetic run's check-point is `n * p` and a
target that misses it lost routes -- tested by membership in
`MRT_TESTER_TYPES`, because a `-f` run records `tester_type: null` and states
its own check-point too; only for that one event, since the other three are
recorded by every run that got that far; and only when `delivery` resolved,
since a withheld one would replace a missing measurement with an absent one.
The Required Measurements amendment above says what such a row does and does
not carry.

**Verified on the campaign host before the hold was lifted, and the check was
not a formality.** Review of the release objected that the premise had never
been observed: all 39 recorded artifacts carrying a witness series are BIRD
except one synthetic FRR row, so *no* FRR MRT run had ever been shown to
produce a `delivery` that resolves. The concern was specific and plausible --
FRR's witness comes from `vtysh` against a 1.05M-prefix `bgpd`, and because FRR
never reaches the check-point its assurance window is 20 samples rather than 5,
so the plateau is long and every sample of it must be freshly read. A stale or
repeated read anywhere in those 20 would withhold `delivery`, `event_coverage`
would fail again, and re-measuring would need `--force`, discarding the nine
rows that did qualify. That is exactly the cost the hold existed to prevent.

So one `frr_c` 10.7 cell was run on the pinned RIB, ten bgpdump2 injectors,
outside the campaign run root (scratchpad results, so this is not a campaign
row). It converged at 957,086 against the 1,039,500 check-point -- the Block 5
shape -- and:

- `delivery` **resolved**: `complete_s` 93.948s, `plateau_samples` 21, and all
  21 are distinct reads with a maximum age of **0.68s** against the 5s bound.
  FRR's `vtysh` read is comfortably fast enough at full-table size; the
  objection was sound and does not materialise.
- `exported_final` and `monitor_final` agree exactly at 957,086, and the target
  accepted 10,497,949 of the 10,500,000 paths offered.
- `check_timing_evidence.py` returns **QUALIFIED**, with `event_coverage`
  reading "no monitor_required_reached -- the MRT check-point is a guess this
  daemon's export share does not meet -- but the target finished delivering at
  93.948s and the monitor held 957086 of its 957086", and with the consistency
  check and the size floor both passing on their own evidence rather than on
  the substitution.
- `findings` stays `inconclusive`, as the amendment above says it will.

One cell is not five, and Blocks 6 and 7 re-run the same shape twice more; what
this establishes is that the mechanism works on the daemon it was built for,
which is what the hold was waiting on. A row that does withhold `delivery` is
handled by `accept --with-exclusions` with this evidence beside it.

**The paragraphs below were written while the hold stood**, and are kept as
they were:

**Nothing reads it yet and the hold stands.** Shipping the measurement one
change set ahead of the rule that consumes it is deliberate -- the same
discipline `target_table` itself was shipped under, and the reason all three
convergence rules were broken was rules fitted to the evidence in front of
them. The second change set teaches `event_coverage` to accept it in place of
the event that legitimately cannot fire, and releases `BLOCK_HELD[5]`.

**The block stays held, on the new objection rather than the old one.** The
`BLOCK_HELD` entry was briefly cleared here -- the question that held it is
answered -- and that was wrong: `next` would then have selected block 5, spent
hours on 14 full-table cells, and rejected 5 of them on `event_coverage`, which
is the outcome the hold exists to prevent. Worse, re-running afterwards needs
`--force`, which discards the 9 rows that qualified, because `--resume` skips
whatever the progress file already holds. The entry is restored with its reason
rewritten to the measurements that are not being taken. Release it in the change
set that lands the derived measurement above.

Block 5 was built and **held**, and what
to do with the five FRR rows -- run and exclude them with this evidence, or
settle an MRT correctness rule first -- is an operator decision recorded before
any block spends hours reproducing it three times. Justin chose to hold on
2026-09-11.

"Held" is enforced, not described. `BLOCK_HELD` in the runner refuses block 5
with the paragraph above and exit 2, `status` reports it as `held` rather than
`not-started`, and `next` will not select it -- because the campaign contract
tells an unattended session to run the next block, and a record saying "held"
that nothing checks is a record that gets overtaken by the contract. Running it
anyway takes `--run-held-block`, which is recorded in that block's `RAN` marker
as `held_override`, since a block run past a standing objection is not the same
result as one run without one. Releasing it means deleting the `BLOCK_HELD`
entry in the change set that settles the decision.

**Two corrections to the campaign's own inputs landed with this block**, both
found by review of it and both about a file rather than a measurement:

- `mrt_facts()` recorded a size and no digest, while the runner's comments
  claimed a digest. The three MRT repetitions are read together as the
  dispersion of one cell, which is only true if all three replayed the same
  bytes -- and the RIB is an out-of-band download on a volume that outlives the
  instance without being immutable, so a re-downloaded or substituted RIB of
  the same length was indistinguishable. It now records `sha256` beside
  `size_bytes`. Blocks 0-4 have size only; the digest starts here.
- The RIB that was validated by `prepare_mrt.sh` and recorded in the manifest
  was `${MRT_FILE:-mrt/rib.20260808.0000}` -- the `--mrt-file` override, else a
  constant -- and not the `mrt_file:` entries the batch actually replays. The
  two agree today and would have agreed only by coincidence in any later block
  built from a different RIB, where an unparseable file would have reached all
  fourteen rows with the check green and the manifest would have attributed the
  pass to a file the block never opened. Both now read the rendered config
  (`config_mrt_files`), which also folds the override case into the ordinary
  one, since `campaign_render_config` has already applied it by then. A
  synthetic block's manifest entry consequently carries no `mrt_inputs` key at
  all rather than one naming a RIB it never opened.

**Result, 2026-09-11: 14 of 14 rows qualified**, on
`m7a.4xlarge` / EPYC 9R14 / 16 threads / 61.44 GiB, one host throughout
(`previous_entries` empty), RIB sha256 `f6c87b21...73d0`. `RAN` is written;
`COMPLETE` is not, so this is the reviewed block boundary and `next` refuses to
re-run it. No tester errors, no timeouts, no failed rows. Peak foreign CPU 29%
on one row and 4-15% on the rest, all far under the one-core threshold.

**This is the first MRT block in which the `frr_c` rows qualify**, and the
mechanism behaved with margin rather than marginally. All five carry no
`monitor_required_reached` and all five resolved `delivery`: 93.1-94.4s over a
21-sample plateau that is 21 *distinct* reads, oldest witness age 0.61-0.69s
against the 5s bound. The review objection that FRR's `vtysh` read against a
1.05M-prefix `bgpd` might be too slow to sustain a 20-sample plateau is
answered: it is roughly seven times faster than it would need to be.

The three-path design shows up cleanly in one block: BIRD reaches the
check-point *and* has a gauge, so it carries both the events and a derived
`delivery` (the column stays comparable); FRR has a gauge and no event, and
qualifies on the substitution; OpenBGPD and RustyBGP have the event and no
gauge, publish no `delivery` section at all, and write exactly the document
they always did.

| target | received | elapsed (s) | max cpu % | max mem (GB) |
|---|---|---|---|---|
| rustybgp default | 1,081,180 | 26 | 826 | **11.472** |
| rustybgp 2026-02 | 1,081,178 | 25 | 1145 | 2.372 |
| bird default (2.19.0-master) | 1,056,779 | 31 | 101 | 1.203 |
| bird 2.19.2 | 1,056,779 | 32 | 101 | 1.207 |
| bird 3.3.2 (4 threads) | 1,056,779 | 37 | 308 | 1.597 |
| bird 3.3.2 (default threads) | 1,056,779 | 42 | 170 | 1.590 |
| openbgp default | 1,056,779 | 79 | 199 | 3.022 |
| openbgp 9.2 | 1,056,779 | 80 | 198 | 3.021 |
| openbgp 8.8 | 1,056,779 | 122 | 158 | 4.969 |
| frr default (10.8.0-dev) | 957,260 | 102 | 133 | 5.970 |
| frr_c 8.5 | 959,882 | 103 | 203 | 4.996 |
| frr_c 9.1 | 960,860 | 103 | 203 | 5.275 |
| frr_c 10.0 | 959,306 | 103 | 203 | 5.178 |
| frr_c 10.7 | 956,893 | 103 | 135 | 5.956 |

**The export-share finding reproduces exactly**, which matters because the
release rests on it: three distinct totals from one RIB. BIRD and OpenBGPD
agree on 1,056,779 to the route across all seven of their rows; RustyBGP holds
1,081,178/1,081,180; FRR spans 956,893-960,860, a **0.41%** spread across four
releases and master against the 9% that separates FRR from the others. Every
prior probe said the same thing, now on campaign rows.

**Two observations for Block 9, both single-pass and neither yet a claim.**
Blocks 6 and 7 supply the repetitions, and one observation cannot be separated
from run-to-run variance by the plan's own variance rule:

- **RustyBGP master holds 4.8x the memory of the 2026-02 build for the same
  table** -- 11.472 GB against 2.372 GB, on 1,081,180 against 1,081,178
  prefixes and 26s against 25s. Two distinct commits
  (`v0.2.0-9eeeebbd50` against `v0.2.0-0cc685c882`), so this is a clean
  version comparison and not an image mix-up. It also pulls `min free mem` to
  44.58 GB, the lowest in the block, which is worth watching at this table size
  on a 64 GB host.
- **BIRD 3.3.2 is slower than 2.19.2 on full-internet playback** -- 42s at its
  default single worker, 37s with `threads 4`, against 32s for 2.19.2 at 101%
  CPU. Threading helps 3.3.2 against itself and does not recover the 2.19.2
  number, at 308% CPU to do it. This is Primary Question 1 territory and the
  synthetic blocks may not say the same thing.

`findings` reports `inconclusive` for all five FRR rows, as the Required
Measurements amendment above says it will: `limiting_component` needs
`convergence_s`, which is measured from the event that cannot fire.
`bgperf2-rqp` tracks deriving that from `delivery`, back-fillable onto these
artifacts without re-measuring.

### Block 6: full-internet MRT repetition 2 of 3 -- **accepted 2026-09-11**

Runs from `benchmarks/2026-timing-mrt-rep2.yaml`: the same 14 target
configurations, the same pinned Route Views RIB `mrt/rib.20260808.0000`, ten
bgpdump2 injectors on 10 full-internet peers, no policy, one pass, one cell at
a time, `order: shuffle` seed 20266 -- the campaign's year+block rule,
continuing 20265. Work directory `/data/bgperf-work`. Procedure is
`run_mrt_repetition()`, unchanged from Block 5.

The config's `tests:` mapping differs from repetition 1's in exactly two lines,
the test `name` and the `seed`, which is the diffability Block 9 depends on.
The header is rewritten to what Block 5 *measured* rather than what it
predicted -- rep1's said all five `frr_c` rows were expected to be rejected on
`received < required`, and they now qualify on a resolved `delivery`. That is
not drift: the mapping is what must not move between passes.

**Result, 2026-09-11: 14 of 14 rows qualified**, on the same instance Block 5
ran on (`i-08c8b32e512905f84`, `m7a.4xlarge` / EPYC 9R14 / 16 threads / 61.44
GiB), one host throughout (`previous_entries` absent), RIB sha256
`f6c87b21...73d0` -- byte-identical to the file Block 5 replayed, which is what
the digest was added for. No tester errors, no timeouts, no failed rows. Peak
foreign CPU 2% on eleven rows, 4%, 7% and 12% on the other three, all far under
the one-core threshold. Lowest `min free mem` 44.5 GB (72%), on `rustybgp
default` as in Block 5.

**Every row reproduces, and so does every verdict.** `findings` returns the
identical `limiting_component` and rule for all fourteen rows -- `tester
(tester_limited)` for the four BIRD rows and `rustybgp default`,
`target_or_monitor (post_injection_tail)` for the three OpenBGPD rows and
`rustybgp 2026-02`, `inconclusive (missing_timing_evidence)` for the five
`frr_c` rows. `received` is within 0.4% on every row and identical to the route
on all seven BIRD and OpenBGPD rows (1,056,779) and both RustyBGP rows
(1,081,178 / 1,081,180).

| row | elapsed b5/b6 | received b5/b6 | max mem b5/b6 |
|---|---|---|---|
| rustybgp 2026-02 | 25 / 25 | 1,081,178 / 1,081,178 | 2.372 / 2.336 |
| rustybgp default | 26 / 27 | 1,081,180 / 1,081,180 | **11.472 / 11.540** |
| bird default | 31 / 31 | 1,056,779 / 1,056,779 | 1.203 / 1.202 |
| bird 2.19.2 | 32 / 32 | 1,056,779 / 1,056,779 | 1.207 / 1.203 |
| bird 3.3.2 (4 threads) | 37 / 40 | 1,056,779 / 1,056,779 | 1.597 / 1.585 |
| bird 3.3.2 (default threads) | 42 / 45 | 1,056,779 / 1,056,779 | 1.590 / 1.584 |
| openbgp default | 79 / 81 | 1,056,779 / 1,056,779 | 3.022 / 3.018 |
| openbgp 9.2 | 80 / 80 | 1,056,779 / 1,056,779 | 3.021 / 3.021 |
| openbgp 8.8 | 122 / 124 | 1,056,779 / 1,056,779 | 4.969 / 4.965 |
| frr default (10.8.0-dev) | **102 / 89** | 957,260 / 959,701 | 5.970 / 5.952 |
| frr_c 8.5 | 103 / 103 | 959,882 / 961,057 | 4.996 / 4.997 |
| frr_c 9.1 | 103 / 103 | 960,860 / 959,309 | 5.275 / 5.271 |
| frr_c 10.0 | 103 / 104 | 959,306 / 959,084 | 5.178 / 5.174 |
| frr_c 10.7 | 103 / 104 | 956,893 / 960,724 | 5.956 / 5.949 |

**Both of Block 5's single-pass observations now have a second reading, and
both hold.** Neither is a claim until Block 7 supplies the third, per the
plan's own variance rule, but neither looks like run-to-run noise:

- **RustyBGP master holds 4.9x the memory of the 2026-02 build** -- 11.540 GB
  against 2.336 GB, on the same 1,081,180/1,081,178 prefixes and 27s against
  25s. The two readings of each build are 0.6% and 1.5% apart, so the 4.9x is
  not dispersion. `bgperf2-nit`.
- **BIRD 3.3.2 is slower than 2.19.2 on full-internet playback** -- 45s at its
  default single worker and 40s with `threads 4`, against 32s for 2.19.2. Both
  3.3.2 rows moved *up* by 3s between passes while both 2.19.2-family rows did
  not move at all, so the gap widened rather than closed.

**The witness rule fired again on the same row**, which turns Block 5's
observation into a reproducible property: `bird 3.3.2 (default threads)`
converged only through `ConvergenceTracker`'s fourth rule, 7 excused samples
over a 1.50% monitor decline while the target's own best-path count stayed
within 0.15% of its peak (Block 5: 8 samples, 1.64% against 0.03%). No other
row in either block needed it. So the overshoot this workload produces is
BIRD 3.3.2's at its default thread count specifically, in both passes, and a
monitor-only rule would have failed that row twice.

**The FRR substitution behaved as in Block 5, with the same margin.** All five
rows carry no `monitor_required_reached` and all five resolved `delivery`:
plateaus of 21 samples, `monitor_lag_s` 0.0 on every one, `exported_final`
equal to `monitor_final` to the route, at 94.5-95.2s for the four pinned
releases and 80.5s for master. The export-share finding reproduces to the same
three totals from one RIB -- 1,056,779 (BIRD and OpenBGPD), ~1,081,178
(RustyBGP), 959,084-961,057 (FRR, a 0.21% spread across four releases and
master, tighter than Block 5's 0.41%).

**One row moved, and it moved in both instruments together.** `frr default`
(10.8.0-dev) came in at 89s against Block 5's 102s, a 12.7% drop, with
`delivery.complete_s` moving 93.13s -> 80.51s by almost exactly the same
amount. So this is the run genuinely finishing sooner rather than a measurement
artefact, and it is the only FRR row with any dispersion -- the four pinned
releases are 103-104s in both passes. Master is the unpinned build of the five,
so it is also the only one whose binary could differ between passes. It did
not: `bgperf/frr_c:latest` was built 2026-09-02 and nothing has rebuilt it
since, both passes report `FRRouting 10.8.0-dev-my-manual-build`, and both were
run from a tree that ran no `prepare`. Note what that argument rests on --
provenance records the image *tag* and the daemon's own version string, not an
image digest, and a rebuilt `:latest` reporting the same `-dev` string would be
indistinguishable in these documents. The gcov trap one layer up, and worth a
digest in `collect_provenance()` rather than this paragraph. Block 7 decides
whether 89 or 102 is the outlier.

### Block 7: full-internet MRT repetition 3 of 3 -- **accepted 2026-09-11**

Runs from `benchmarks/2026-timing-mrt-rep3.yaml`: the same 14 target
configurations, the same pinned Route Views RIB `mrt/rib.20260808.0000`, ten
bgpdump2 injectors on 10 full-internet peers, no policy, one pass, one cell at
a time, `order: shuffle` seed 20267 -- the campaign's year+block rule,
continuing 20266 and 20265. Work directory `/data/bgperf-work`. Procedure is
`run_mrt_repetition()`, unchanged from Blocks 5 and 6.

The config's `tests:` mapping differs from both earlier passes' in exactly two
lines, the test `name` and the `seed`, verified by diff against each. The
header is rewritten to what Block 6 measured and adds a fifth section naming
the four two-reading observations this pass exists to settle -- written down so
the review is a comparison rather than a fresh reading, and explicitly not
pinned as an expectation.

**Result, 2026-09-11: 14 of 14 rows qualified**, on the same instance Blocks 5
and 6 ran on (`i-08c8b32e512905f84`, `m7a.4xlarge` / EPYC 9R14 / 16 threads /
61.44 GiB), one host throughout (`previous_entries` absent), RIB sha256
`f6c87b21...73d0` -- byte-identical across all three passes, which is what the
digest was added for. No tester errors, no timeouts, no failed rows, all ten
injectors complete with 10,500,000 prefixes offered on every row. Peak foreign
CPU 2-5%, far under the one-core threshold. Lowest `min free mem` 44.63 GB
(72.6%), on `rustybgp default` as in both earlier passes; no swap.

**The verdict pattern reproduces for the third time**, row for row: `tester
(tester_limited)` for the four BIRD rows and `rustybgp default`,
`target_or_monitor (post_injection_tail)` for the three OpenBGPD rows and
`rustybgp 2026-02`, `inconclusive (missing_timing_evidence)` for the five
`frr_c` rows. All five `frr_c` rows again carry no `monitor_required_reached`
and again resolve `delivery` -- plateaus of 20-21 samples, `monitor_lag_s` 0.0,
`exported_final` equal to `monitor_final` to the route.

| row | elapsed b5/b6/b7 | received b5/b6/b7 | max mem b5/b6/b7 |
|---|---|---|---|
| rustybgp 2026-02 | 25/25/25 | 1,081,178 x3 | 2.372/2.336/2.328 |
| rustybgp default | 26/27/27 | 1,081,180 x3 | **11.472/11.540/11.389** |
| bird default | 31/31/32 | 1,056,779 x3 | 1.203/1.202/1.202 |
| bird 2.19.2 | 32/32/**37** | 1,056,779 x3 | 1.207/1.203/1.203 |
| bird 3.3.2 (4 threads) | 37/40/40 | 1,056,779 x3 | 1.597/1.585/1.590 |
| bird 3.3.2 (default threads) | 42/45/48 | 1,056,779 x3 | 1.590/1.584/1.581 |
| openbgp default | 79/81/81 | 1,056,779 x3 | 3.022/3.018/3.024 |
| openbgp 9.2 | 80/80/82 | 1,056,779 x3 | 3.021/3.021/3.017 |
| openbgp 8.8 | 122/124/123 | 1,056,779 x3 | 4.969/4.965/4.967 |
| frr default (10.8.0-dev) | **102/89/88** | 957,260/959,701/957,758 | 5.970/5.952/5.958 |
| frr_c 8.5 | 103/103/103 | 959,882/961,057/957,395 | 4.996/4.997/4.992 |
| frr_c 9.1 | 103/103/103 | 960,860/959,309/957,544 | 5.275/5.271/5.273 |
| frr_c 10.0 | 103/104/103 | 959,306/959,084/960,067 | 5.178/5.174/5.170 |
| frr_c 10.7 | 103/104/104 | 956,893/960,724/958,513 | 5.956/5.949/5.949 |

**All four of the carried observations now have a third reading.** Block 9
applies the variance rule; what the three passes say on their own:

- **RustyBGP master holds 4.9x the memory of the 2026-02 build.** 11.472 /
  11.540 / 11.389 GB against 2.372 / 2.336 / 2.328 GB, on the same 1,081,180
  and 1,081,178 prefixes every pass and 25-27s either way. Each build's three
  readings span 1.3% and 1.9%; the ratio is 4.83-4.94x. Not dispersion.
  `bgperf2-nit`.
- **BIRD 3.3.2 is slower than 2.19.2 on full-internet playback**, in all three
  passes: 42/45/48s at its default single worker and 37/40/40s with
  `threads 4`, against 32/32/37s for 2.19.2 and 31/31/32s for `bird default`
  (2.19.0+master). The 3.3.2 default-threads row is the slowest BIRD row in
  every pass and the only one that rises in every pass.
- **The witness rule fires on `bird 3.3.2 (default threads)` and on nothing
  else**, three passes for three: 8 excused samples over a 1.64% monitor
  decline (target within 0.03% of its own peak), then 7 over 1.50% (0.15%),
  then 2 over 2.31% (0.00%). Three readings make the overshoot a property of
  that configuration rather than an incident, and a monitor-only rule would
  have failed that row in all three blocks. The other ten witness-less rows
  have still never needed it.
- **`frr default`: Block 5's 102s is the outlier.** 102/89/88s, with
  `delivery.complete_s` at 93.13/80.51/80.69s moving with it, so the two later
  passes agree to 1s and 0.18s respectively and Block 5 stands 13-14s above
  both. The four pinned FRR releases are 103-104s in all three passes, so the
  dispersion is master's alone. The caveat from Block 6 is unchanged and
  unresolved: `bgperf/frr_c:latest` is the one unpinned binary of the five,
  provenance records the image tag and the daemon's `-dev` version string but
  no digest, and a rebuild between passes would be invisible in these
  documents. Nothing rebuilt it (image created 2026-09-02, both later passes
  run from trees that ran no `prepare`), but the argument rests on that rather
  than on the artifact.

**One row moved that had not moved before, and the move is entirely after the
check-point.** `bird 2.19.2` came in at 37s against 32/32. Decomposed against
the same row's two earlier artifacts:

| | b5 | b6 | b7 |
|---|---|---|---|
| `monitor_required_reached` | 21.958s | 22.098s | 22.192s |
| `monitor_last_change` (= `delivery.complete_s`) | 29.280s | 29.443s | **33.859s** |
| `convergence_confirmed` | 36.544s | 36.787s | 41.147s |
| `assurance_s` | 14.585s | 14.688s | **18.955s** |

So the monitor crossed the check-point at the same moment in all three passes
-- 0.23s apart across the series -- and what took 4.4s longer was the last
~5,500 prefixes of the table arriving after it. The target's own export gauge
agrees to the millisecond, which is what rules out the instrument: `delivery`
is derived from the target's series and `monitor_last_change` from the
monitor's, and they land on the same number. `elapsed (s)` carries it because
it subtracts the assurance *sample count* and not the window's duration. The
host was clean for that cell (2% peak foreign CPU, 54.8 GB free), so nothing in
the row explains it, and one reading of three is not a finding. It is noted
here because Block 9 will see a 32/32/37 cell whose dispersion is entirely in
its tail and none of it in delivery, and that is a different thing from a
target that got slower.

**The MRT series is complete and every daemon family held its export share.**
Three totals from one RIB, unchanged across three passes: 1,056,779 (BIRD and
OpenBGPD, identical to the route in all nine rows), ~1,081,178 (RustyBGP), and
957,395-961,057 (FRR, a 0.38% spread across four releases and master over all
three passes). FRR's ~8% withholding from export (`bgperf2-cw6`) reproduces
unchanged and is still unexplained.

**Two review findings were deliberately not applied before this block ran.**
`/code-review` on the Block 7 change set found nothing in that change set and
two defects in code already on master: `delivery_metrics()` dates
`plateau_start_s` to the monitor poll that carried the export reading rather
than to the witness read, so `complete_s` is biased late by the witness age and
`monitor_lag_s` collapses to 0.0 structurally (`bgperf2-bq2`); and an MRT row
accepted on a resolved `delivery` has nothing bounding its exported share
against the table it holds, so a target exporting half the RIB would qualify
(`bgperf2-ctm`). Both change how an MRT row is measured or judged, and applying
either between passes 2 and 3 would judge the third pass of one cell by a rule
the first two were not judged by -- which is what the Required Measurements
amendment above forbids. Both are derivable retroactively from the Block 5-7
artifacts on disk, so the cost of waiting is nothing. Land them before Block 9
reads the three passes.

### Blocks 10-11

Not started. Each block's configs and procedure are its own change set. Blocks
8 and 9 are recorded under Execution Blocks below, where their sections are.

## Execution Blocks

The follow-up runner should expose `next` behavior and durable `COMPLETE`
markers in this fixed order.

That runner is `scripts/run_timing_validation_block.sh`, and it carries the
campaign identity above as its defaults:

```bash
scripts/run_timing_validation_block.sh status     # what each block's state is
scripts/run_timing_validation_block.sh next       # run the first unaccepted block
scripts/run_timing_validation_block.sh accept 0 --note "..."
```

**It writes two markers, not one.** A block writes `RAN` when its mechanical
work finished; only an operator's `accept` writes `COMPLETE`, and `next`
advances past `COMPLETE` alone. The exit criteria below are review criteria --
a session that died between the batch and the review would otherwise leave a
block that looks exactly like a reviewed one, and the campaign would never come
back to it.

**`RAN` records that the work ran, whatever the evidence said.** It used to be
written only when every check qualified, which made a block with one rejected
row unreachable from both sides: `accept` refuses a block with no `RAN`, and
`next` re-selected the block and re-ran it with `--resume`, which skips every
cell already in the progress file *including the failed ones* -- so the block
measured nothing, exited 0, and failed the identical check, with the one cell
worth re-measuring the only one resume would never re-run.

**"or explicit durable exclusions with evidence" is a command, not a
disposition.** A block whose evidence rejected a row is accepted with
`accept N --with-exclusions --note "why"`, and the `COMPLETE` marker names the
rejected rows, read from the verdicts rather than from a count of failed
checker invocations -- Blocks 2-7 make one call covering 14 runs, so that count
is 1 whether one row was rejected or fourteen. **A run that never happened is
not an exclusion.** The checker also fails on a shortfall, and a block that
produced 9 artifacts for 14 configurations is unfinished work; the two are
reported apart, on the rule this campaign applies at every other level of
aggregation. Re-measuring is `--force`, which discards that block's previous
results and artifacts along with its markers and progress -- a single cell
cannot be re-run on its own.

**A block that has not been built refuses rather than improvising.** Each
block's configs and procedure are their own change set, written when the
campaign reaches that block; a runner that guessed at a matrix would produce
rows indistinguishable from the right ones.

**Benchmark blocks qualify their own rows before claiming to have run.**
`scripts/check_timing_evidence.py` applies the Acceptance Rules below to every
run in a block's results directory -- provenance for all three roles and for
the bgperf2 revision that measured them, converged status, ordered and complete
event stream, complete tester evidence, no tester error or timeout, no material
foreign CPU contention, free memory above this campaign's 20% guardrail, and a
limiting component that was assigned or explicitly left unresolved. It reads
the published documents and re-derives no measurement: a checker that
recomputed one would be a second implementation, and the two would disagree on
exactly the runs anyone cared about. Its verdicts land in
`<block>/evidence/*.json`.

### Block 0: preflight and timing smoke

- Run `doctor`, `images`, and `verify`.
- Validate the pinned MRT.
- Confirm the measurement schema release gate.
- Run one tiny BIRD synthetic timing smoke.
- Run one minimal bgpdump2 MRT timing smoke.
- Confirm tester completion, counts, event order, and provenance.

Exit criterion: both tester types produce complete, internally consistent
timing evidence without low memory or contention.

### Block 1: generator calibration

- Run the controlled slow-tester case.
- Run the controlled target/monitor-tail case.
- Measure standalone or tester-to-monitor generation only where topology and
  limitations are explicitly documented.
- Do not subtract pass-through time from target time.

Exit criterion: the qualification policy identifies the two controlled limits
correctly and leaves ambiguous cases inconclusive.

### Blocks 2–4: high-load synthetic repetitions 1–3

- Run all 14 configurations once per block.
- Use the recorded order seed/rotation for that repetition.
- Review every completed block before starting the next.
- Stop on low memory, swap growth, foreign contention, or tester evidence gaps.

Exit criterion per block: 14 reviewed rows or explicit durable exclusions with
evidence.

### Blocks 5–7: full-internet MRT repetitions 1–3

- Run all 14 configurations once per block using ten bgpdump2 injectors.
- Keep the exact pinned RIB and full-feed peer selection stable.
- Review all ten injector completions and counts for every row.

Exit criterion per block: 14 reviewed rows or explicit durable exclusions with
evidence.

### Block 8: BIRD architecture screen -- **accepted 2026-09-12, 18/21 qualified, 3 excluded**

The baseline's initial-table cells do not reproduce the workload BIRD 3 was
designed to scale. BIRD's documented worker group runs BGP protocols,
routing-table maintenance, and exports, while BIRD 3 also decouples exports
from imports. Three configurations -- BIRD `2.19.2`, `3.3.2` at its own default
single worker, and `3.3.2` with `threads: 4` -- across five bounded scenarios,
one observation each, from five configs run into five results directories:

| scenario | config | workload |
|---|---|---|
| peers | `benchmarks/2026-timing-bird-peers.yaml` | 50, 250, 500 peers x 2,000 |
| diversity | `benchmarks/2026-timing-bird-diversity.yaml` | 50 peers, `path_diversity: 50`, 5,000,000 paths for 100,000 prefixes |
| fanout | `benchmarks/2026-timing-bird-fanout.yaml` | 50 peers x 20,000, `receivers: 10` |
| reload | `benchmarks/2026-timing-bird-reload.yaml` | 50 x 50,000, `policy_reload_blocks: 10` |
| churn | `benchmarks/2026-timing-bird-churn.yaml` | 50 x 50,000, `churn_prefixes: 5_000`, `churn_bursts: 3` |

`order: shuffle` seed 20268 in all five -- the campaign's year+block rule,
continuing 20267. Work directory `/data/bgperf-work`. Procedure is
`run_bird_architecture_screen()`: one preflight, one `verify`, one metadata
capture over all five rendered configs, then each scenario run and checked
before the next starts.

**Separate directories are load-bearing, not tidiness.**
`check_timing_evidence.py` pairs an artifact with its CSV row by the cell's
identity, and the workload controls are deliberately not CSV columns -- so the
reload and churn scenarios, both 50 x 50,000 with the same three run names,
are indistinguishable in one CSV. In one directory their six rows would be
three ambiguous pairs and every one would be rejected.

**Result, 2026-09-12: 18 of 21 rows qualified**, on the same instance Blocks 5-7
ran on (`i-08c8b32e512905f84`, `m7a.4xlarge` / EPYC 9R14 / 16 threads /
61.44 GiB), one host throughout (`previous_entries` absent). All 19 built images
verified clean of gcov instrumentation before the first container. **Every count
is exact in all 21 runs** -- 100,000 / 500,000 / 1,000,000 / 2,500,000 received
against the offered table, and 5,000,000 paths held for exactly 100,000 selected
prefixes in the diversity cells. No failed rows, no timeouts. Peak foreign CPU
0-7%, far under the one-core threshold. Lowest `min free mem` 48.65 GB (79%),
on the fan-out rows where ten GoBGP receivers each hold the table; no swap.

**Three rows carry a `host_cpu_saturated` note** -- the benchmark's own load,
and a note rather than a rejection, as in Blocks 5-7 (seven, six and seven
rows). Here they are *exactly* the three fan-out rows and no others, which is
the scenario itself rather than a property of the host: the target, the
generator and ten GoBGP receivers share 16 threads, and no other scenario in
this block runs more than one consumer. It confounds attribution, which costs
this block nothing -- every row is already `unresolved` on the generator, and
the fan-out bullet below reads only the spread between three rows measured
under the same condition.

#### What the five scenarios measured

`elapsed (s)` is the monitor's convergence in every row, as everywhere else in
this campaign; the reload, churn and export numbers are from the artifacts.

| scenario | metric | 2.19.2 | 3.3.2 default | 3.3.2 threads 4 |
|---|---|---|---|---|
| peers 50 | elapsed | 4 | 5 | 5 |
| peers 250 | elapsed | **112** | 54 | **49** |
| peers 500 | elapsed | **281** | 201 | **177** |
| diversity | elapsed | **7** | 13 | **19** |
| fanout | elapsed | **23** | 31 | 29 |
| fanout | slowest receiver | 19.67s | 35.32s | 28.32s |
| reload | `reload_s` | **22.44** | **12.43** | 12.82 |
| reload | reload CPU mean | 89.3% | **40.7%** | 94.9% |
| churn | mean `withdraw_s` | 5.83 | 6.05 | **4.92** |
| churn | mean `reannounce_s` | **6.22** | 8.28 | 8.42 |
| max cpu % | (all scenarios) | ~101 | ~102-112 | **166-223** |

**The screen separates BIRD 3 on the axis it was built for and finds it behind
on two others.** This is the first evidence in this campaign of BIRD 3 beating
BIRD 2 at anything: every canonical cell in Blocks 2-7 is a single large table
arriving over 10 or 50 sessions, where 3.3.2 is slower in every pass.

- **Session count is where BIRD 3 wins, and the win grows with it.** At 50
  peers the three are indistinguishable at the instrument's 1s resolution --
  which is why the plan sweeps upward rather than reading a single cell. At 250
  peers 3.3.2 is 2.07x faster at its default and 2.29x with four threads; at
  500 peers 1.40x and 1.59x. The thread setting buys a further 9-10% at both.
- **Competing-path selection is where it loses most, and threads make it
  worse.** 7s / 13s / 19s for the identical 5,000,000 paths, so 3.3.2 is 1.9x
  slower at its default and 2.7x slower with four threads while drawing 223%
  CPU. Best-path selection is the one thing in the worker group's documented
  remit that this scenario isolates, and adding workers cost time.
  The 4-thread run's `best_paths` peaks at 100,804 before settling to exactly
  100,000 -- a transient overcount the single-worker runs do not produce.
- **Policy recalculation is the cleanest win and the only one that is also
  cheaper.** 22.44s against 12.43s, and 3.3.2 at its default does it at 40.7%
  mean CPU against 2.19.2's 89.3% -- half the time for less than half the CPU.
  Four threads buys nothing (12.82s against 12.43s, inside the 2.0s resolution)
  while more than doubling CPU. All three preserved their sessions and converted
  exactly 2,500,000 accepted prefixes to 2,000,000. `command_s` was 32-41ms
  against a `reload_s` of 12-22s, which is why the two are never one number.
- **Churn splits by half.** 3.3.2 withdraws slightly faster with four threads
  (4.92s against 5.83s) and re-announces slower in both configurations (8.28s
  and 8.42s against 6.22s). Timing the two halves separately is what shows
  that; one end-to-end burst number would have read as a uniform 2s loss.
- **Export fan-out follows the canonical result rather than reversing it.** All
  ten receivers held 990,000 prefixes in every run. 3.3.2 default's fan-out
  shows a 12.2s spread across the ten against 0.0s for the other two, and its
  slowest receiver reached the table at 35.32s against 2.19.2's 19.67s. These
  are the three `host_cpu_saturated` rows, so the receiver intervals are a
  comparison between the three configurations under one shared condition and
  not a figure to read against another block's export timings.

#### Every row is `unresolved`, and that is the generator, not the runs

All 21 rows report `limiting_component: unresolved (injection_boundary_
unresolved)`. This is the documented BIRD 2.19 generator limitation, not a
property of this block: `Export updates accepted` is queue-side and saturates
before the instrument's first poll, so less than half the offered table crosses
the measured interval and the generator does not time its own send. Every
synthetic row in Blocks 2-4 reports the same thing. **Block 8 therefore supports
no attribution of any interval to a component**, and nothing above depends on
one -- `elapsed (s)`, `reload_s`, the burst halves, the export intervals and the
CPU and memory columns are all direct measurements.

#### The three excluded rows, which are two different things

`exclusion_counts: 3 rejected row(s), 0 shortfall(s)`. Every one was rejected on
`tester_health` alone; all three runs converged with exact counts.

- **`peers: bird 2.19.2` (500 peers) is a real finding about the daemon.**
  Twelve of 500 generator sessions logged `Error: Hold timer expired`, in twelve
  distinct logs, inside a 30s window of a 281s run. Neither 3.3.2 configuration
  produced one at the same peer count. This reads as the single-threaded daemon
  failing to service keepalives on part of a 500-session fleet while it works,
  which is the scheduling behaviour BIRD 3's workers exist to address -- and it
  is the same cell where 3.3.2 is 1.4-1.6x faster. Recorded as `bgperf2-599`.
  Whether a row carrying it may support the peer-scaling comparison is Block 9's
  call; the measurement itself is sound and the count is exact.
- **`peers: bird 3.3.2 (4 threads)` and `fanout: bird 2.19.2` are an instrument
  defect and measure nothing.** Their captured error lines are
  `<RMT> bgp1: Invalid ro` and `<RMT> bgp1: Invali` -- the last line of a tester
  log, partially written. `Tester.find_errors()` excludes
  `Invalid route ... withdrawn`, which is the target reflecting routes back at
  the generators and is normal operation, but it scans while the container is
  still writing and a truncated line fails that substring test. The FRR
  End-of-RIB reader and the bgpdump2 blaster reader both stop at the last
  complete line for exactly this reason; `find_errors()` has no such guard. In
  both rows `sampled_errors` equals `tester_errors`, so every counted error is
  one of these lines and nothing else was missed.

  **The fix is deferred rather than taken here, deliberately.** Blocks 2-7 were
  measured under the current definition of a tester error, and changing it
  between blocks puts a difference in how the passes were measured inside the
  statistics Block 9 exists to compute. The counterargument is that a false
  count is not a measurement worth preserving, and the fix only stops counting
  lines that were never errors. Either way it belongs in its own change set and
  before Block 10, which is the next block that runs benchmarks.

Exit criterion: each feasible scenario has correct counts and complete timing,
CPU, memory, and operation evidence, or a durable 64 GB exclusion. **Met for all
five scenarios**; no scenario proved infeasible on 64 GB, and no cell approached
the memory guardrail.

### Block 9: variance, version, and BIRD-screen review -- **accepted 2026-09-12**

For each workload and version comparison:

- calculate median, range, and coefficient of variation;
- review order effects and cold/warm metadata;
- separate end-to-end, injection, post-injection tail, CPU, and memory findings;
- select only decision-relevant comparisons for optional repetitions 4–5;
- select BIRD architecture scenarios for two additional repetitions when they
  separate versions/thread settings or expose a CPU-scaling change;
- write the selection and reason to durable metadata before running more.

Two defects found during Block 7 were settled before this block, and are
recorded here rather than only in the Block 7 record because this is the section
a session building Block 9 reads.

`bgperf2-bq2` is **fixed** (2026-09-11): `delivery_metrics()` dated
`plateau_start_s` to the monitor poll that carried the export reading rather
than to the witness read, which put both ends of `monitor_lag_s` on one clock
and collapsed it to 0.0 on 25 of the 27 resolved rows of Blocks 5-7. Re-derived
over all 27, **no `complete_s` moved**, so every number this block compares
stands as published; `monitor_lag_s` is now signed and carries
`monitor_lag_resolution_s`, and all 27 rows are inside their own bound. The
published artifacts keep the values they were written with -- re-derive if this
block reads the lag.

`bgperf2-ctm` is **closed by design** (2026-09-12): see the Acceptance Rules
amendment above. The export share is reported, not thresholded, because no
measured number exists to threshold it with and the daemon that would need the
bound publishes no denominator. What this block must not do is read `elapsed (s)`
across daemons with different export shares; within a daemon, which is what
every Primary Question asks, the share is constant to 0.4% across the three
passes.

Procedure is `run_variance_review()`, and this is the first block that measures
nothing. It runs no preflight, no `verify` and no container, and depends on no
Docker daemon at all: every number it publishes was published first by a block
that has already been accepted, and `scripts/timing_variance_review.py` reads
those documents and re-derives no measurement. The arithmetic is `summary.py`'s
-- the same module that writes each block's own `<test>.summary.json`, floors
the variance rule at the metric's resolution and refuses a dispersion over one
observation -- so the statistics here are the ones the campaign already
publishes, computed over three blocks instead of one.

**It writes no `evidence/` directory, deliberately.** Those documents are read
by `block_exclusion_report` as *rows a block excluded*, and `accept
--with-exclusions` turns them into durable exclusions; a failed review is not a
row to exclude, it is a block to re-run once the fault is fixed. So it lands in
the `no-evidence` class, where `--with-exclusions` is refused. The one thing
that must survive a `--force` re-run is the selection, which is why that lives
under `metadata/` and not in the block directory: it is written by the operator
*between* a first reading of the statistics and the run that validates them.

**Result, 2026-09-12: seven series reviewed, 0 errors, 2 notes**, on a third
instance of the campaign's host class (`i-03c5d7d55de1dc561`, `m7a.4xlarge` /
EPYC 9R14 / 16 threads / 61.44 GiB) -- which changes nothing here, since the
block reads documents rather than running containers. All seven input blocks
carry a COMPLETE marker, every cell of every canonical pass is present, and no
cell's passes disagree about the target image, the tester version, the monitor
version or `required`.

#### The three passes, and what they separate

`elapsed (s)`, three passes per cell, by the plan's own variance rule -- two
cells are separated when their medians differ by more than the sum of their
standard deviations, floored at the 1s resolution of the metric:

| | synthetic | full-internet MRT |
|---|---|---|
| separated from every rival | 5 of 14 | 5 of 14 |
| `expand` | 9 of 14 | 9 of 14 |
| of those, no dispersion can separate from the nearest rival | 6 | 8 |
| widest `elapsed (s)` CV | 2.84% (`frr_c 8.5`) | 8.57% (`bird 2.19.2`) |

That third row is the block's most useful single result and it is arithmetic on
the rule rather than a new measurement: the rule floors the combined deviation
at the metric's resolution, so for a pair whose medians are one second apart on
a number counted off a 1s poll, *no* dispersion produces a positive margin --
not five passes' worth, not fifty, not zero. Fourteen of the eighteen `expand`
verdicts are that pair, read against each cell's **nearest** rival with a
dispersion rather than the one that bound its verdict, since `separated` is a
claim about every cell drawn beside it.

**The claim is about the dispersion and not about the future**, which is worth
stating precisely because the stronger version is so easy to write: more passes
move a median as well as tightening a spread, so nothing here says those pairs
can never be separated. What it says is that expanding them is a bet on a
median moving rather than on the variance the plan's condition names -- and the
plan expands a comparison only when "observed variance could change the
decision". So the review publishes
`expansion.dispersion_could_decide: false` beside each of those fourteen, and
`validate_selection()` refuses a selection that names one.

#### What the passes already answer

Eight of the ten Primary Questions are settled by three passes and need no
repetitions; 9 and 10 are what the selections below are for. Every one is a
within-daemon comparison, which is what makes it readable across daemons that
export different shares of one RIB.

- **Question 1 -- FRR 10.7's synthetic improvement repeats, and it is
  separated from every pinned release.** Medians 85s against 91s (10.0), 95s
  (9.1) and 92s (8.5), with margins of 3.47s, 8.42s and 3.35s over the combined
  deviations. The interval that carries it is `convergence_s` (71.9s against
  79.2s for 10.0), and about a second of it is reaching the first
  monitor-visible prefix (3.09s against 4.12s). **No component attribution is
  available and none is claimed**: every synthetic row in the campaign is
  `unresolved (injection_boundary_unresolved)` because the BIRD generator's
  offered count is queue-side and saturates before the first poll -- the review
  publishes `offered_in_interval` beside `injection_s` for that reason, and it
  is 0 on all fourteen cells.
- **Question 2 -- FRR 10.7 is not measurably slower on MRT playback, and no
  number of passes can make it so.** 104s against 103s for all three pinned
  earlier releases, deviations of 0.0-0.58s, a 1s gap against a 1s resolution.
  The four pinned releases are 103-104s in all three passes.
- **Question 3 -- BIRD 3 threading buys target processing time, and costs
  roughly twice the CPU for it.** 117s -> 109s synthetic and 45s -> 40s MRT,
  both separated, at 102-110% -> 200-210% and ~178% -> ~318% CPU. Whether it
  changes tester backpressure cannot be read off the MRT rows, because those
  rows are tester-limited (below).
- **Question 4 -- OpenBGPD 9.2's memory reduction is stable, and its
  end-to-end time is workload-specific rather than longer.** 37.437 / 37.435 /
  37.437 GB for 8.8 against 18.533 / 18.713 / 18.536 GB for 9.2 on the
  synthetic workload, a 50.5% reduction with CVs of 0.005% and 0.55%; 4.97 GB
  against 3.02 GB on MRT. On time, 9.2 is *slower* synthetically (733s against
  624s) and *faster* on MRT (80s against 123s), and in both workloads the
  whole of the difference is after the first monitor-visible prefix -- which is
  1.03s for every OpenBGPD row synthetically and 2.06s for every one on MRT.
  Decomposed on MRT: 30.4s of the 43s sits in the post-injection tail and the
  rest in the assurance window.
- **Question 5 -- OpenBGPD 8.8 is safe at the guardrail, and it is not
  moving.** `min free mem` 12.392 / 12.409 / 12.400 GB, 20.2% of host memory,
  a 17 MB spread over three passes run at shuffle positions 7, 14 and 4, no
  swap on any of them.
- **Question 6 -- the RustyBGP pinned/default difference is workload-specific,
  in both directions.** Synthetic: the master build is 2.3x slower (152s
  against 66s) for comparable memory. MRT: the two are 27s and 25s and the
  master build holds **4.9x** the memory (11.472 / 11.540 / 11.389 GB against
  2.372 / 2.336 / 2.328 GB), each build's three readings within 1.9%.
- **Questions 7 and 8 -- yes, and not separably.** On MRT the generator limits
  the five fastest rows: `tester (tester_limited)` for all four BIRD rows and
  `rustybgp default`, in all three passes. The three OpenBGPD rows and
  `rustybgp 2026-02` are `target_or_monitor (post_injection_tail)`, which is
  the measurement declining to separate the target from the monitor; no number
  of passes changes that, since it is a property of where the instrument sits.
  Every synthetic row is `unresolved` on the generator, so the synthetic
  workload answers neither question.

#### Order, hosts and images

- **No order effect dominates either workload.** Ranking each cell's passes by
  its own execution position: synthetic 4 rise, 4 fall, 5 neither, 1 tied; MRT
  2 rise, 1 falls, 8 neither, 3 tied. Fourteen cells over three passes is a
  description and not a test, and the review says so where it prints it. The
  empirical version of the same claim is `openbgp 8.8`'s 17 MB of `min free
  mem` spread across positions 7, 14 and 4. Positions are rebuilt from each
  pass's recorded seed -- the progress file's keys *are* the cell ids
  `order_batch_cells()` digested -- and `tests/test_variance_review.py` pins
  that against the controller's own permutation.
- **Blocks 2-8 ran on two instances of one class**, `i-0de8e1dd0d3dba94d`
  (blocks 2-4) and `i-08c8b32e512905f84` (blocks 5-8), which is the host-class
  rule working as intended. The two report `MemTotal` 4 kB apart -- 64,425,440
  against 64,425,436 -- so the review compares memory with a tolerance and
  everything else in the class exactly; an exact test there would report a
  host-class change over 0.000006% and reject the rule on the case it was
  written for.
- **The unpinned binaries did not move, and that is now an artifact rather
  than an argument.** Every one of the 19 `bgperf/*` images carries the
  identical image id in all nine blocks, `bgperf/frr_c:latest` included
  (`6f0f67a1cc71`). The Block 6 and 7 records had to reason from "nothing ran
  `prepare`" precisely because provenance records an image *tag* and the
  daemon's own version string, and a rebuilt `:latest` reporting the same
  `-dev` string would be invisible in a stats row. The manifest's per-block
  image ids answer it directly, and that closes the caveat those records left
  open: `frr default`'s 102/89/88s on MRT is one slow run, not a different
  binary.

#### What Block 10 will run, and what it will not

Recorded in `metadata/block10-selection.json`, which
`scripts/timing_variance_review.py` validates every time the block runs: each
selection carries a hypothesis, a variance reason and a requested pass count,
each declined comparison carries its reason, no selection may name a cell whose
existing row was excluded by an accepted block, and the canonical matrix may not
be named whole.

**Three selected, all in the BIRD architecture screen** -- which is what the
plan anticipated when it called the screen "deliberately adaptive", and it is
where one observation per cell means the variance rule currently withholds every
verdict:

| selection | cells | passes | why |
|---|---|---|---|
| `bird-session-scaling-250-peers` | the three 250-peer cells | 3 | 112s against 54s and 49s: gaps of 58s and 63s against a 1s resolution, and Question 9's central claim |
| `bird-competing-path-selection` | the three diversity cells | 3 | 7s / 13s / 19s for identical work, the only measurement in the campaign where more CPU bought more time |
| `bird-policy-recalculation` | the three reload cells | 3 | `reload_s` 22.44s at 89.3% CPU against 12.43s at 40.7%; the variance rule says nothing about these cells at all, because the measurement is not `elapsed (s)` |

**Seven declined, each with its reason in the same document.** Four are worth
restating here because they answer questions earlier blocks left open:

- **The 500-peer comparison cannot be expanded**, which is Block 8's explicit
  question for this block. Two of its three rows were excluded on
  `tester_health`, so "all existing rows pass qualification" is not met.
  The two exclusions are not the same thing: `bird 2.19.2`'s twelve hold-timer
  expiries are a real property of the single-threaded daemon under a 500-session
  fleet (`bgperf2-599`) and the row is preserved and excluded only from the
  comparison it cannot support, exactly as the plan requires; `bird 3.3.2 (4
  threads)` was rejected on a truncated tester log line and measures nothing.
  Re-measuring is not an expansion, and the second of the two should be fixed
  first.
- **The fan-out comparison cannot be expanded either**, for the same rule --
  `fanout: bird 2.19.2` carries the same truncated-line defect -- and
  repetitions would reproduce rather than remove the `host_cpu_saturated`
  condition all three of its rows share.
- **`openbgp default` against `openbgp 9.2` is not a version comparison.**
  Both cells run OpenBGPD 9.2: `bgperf/openbgp:latest` and `bgperf/openbgp:9.2`
  are two image ids built from one upstream tag three seconds apart, and both
  report `9.2`. Their unseparated verdict is the expected result, and the pair
  is six readings of 9.2 per workload rather than two cells of three.
- **The churn halves are already read three times each and the difference is at
  the sampler's resolution.** Re-announce is 6.10 / 6.12 / 6.44s for 2.19.2
  against 8.14-8.54s for both 3.3.2 configurations, with no overlap, while the
  withdraw halves overlap completely -- but each burst is resolved only to
  +/-2.0-2.4s, and repeating the *run* does not sharpen an interval whose
  resolution is the poll gap. A faster churn sampler would.

**One prerequisite for Block 10, carried forward from Block 7 and Block 8.**
`Tester.find_errors()` scans while the container is still writing, so a
partially written last line fails the `Invalid route ... withdrawn` exclusion
and is counted as an error. It cost three of Block 8's rows and it will cost
Block 10's too: all three selected scenarios re-run the same generator. Blocks
2-7 were deliberately measured under the current definition and the statistics
above are computed over them, so the fix belongs in its own change set -- but it
belongs before Block 10 rather than after it, which is what Block 8's record
said and what this block's selection now depends on.

**Six `/code-review` rounds ran over this block's own change set**, and every
round found something the round before it had introduced. Twenty-six findings
were acted on; the two that would have corrupted this block's output:
`check_timing_evidence.load_json()` *returns* None for a file it cannot read
rather than raising, so every unreadable document was dereferenced instead of
named -- and a pass that FAILED was published as an observation, beside a
summary that had counted it out, which would have put a failed run's intervals
in the decomposition and invented a coefficient of variation out of it. No row
in blocks 2-8 failed, so that one changed no number here: all 49 cells report
every pass observed. Two more mattered to the *selection*: the expansion
prospect asked the binding rival rather than the nearest one, and then -- in
the fix for that -- ruled against medians drawn from a single observation,
which is every BIRD screen cell and so exactly the three expansions this block
selects. They passed only because their gaps are 58s, 12s and 16s.

**One operational caution, learned the hard way while testing the runner's
messages.** `next` against a scratch `--results-root` finds no COMPLETE markers
and runs **block 0 for real** -- containers, MRT replay and all -- and leaves
its last cell's containers up afterwards (`bgperf2-mzy`). Nothing of the
campaign was touched and the containers were removed, but drive a scratch root
with `block-N` rather than `next`, and mark the earlier blocks complete first
if the message under test is `next`'s.

Exit criterion: every optional repetition has a named hypothesis and variance
reason, or the campaign advances with no optional repeats. **Met**: three
selected with hypotheses and variance reasons, seven declined with reasons, and
the document is machine-checked against the rows rather than trusted.

### Block 10: selected repetitions

- Run only the preselected comparison cells.
- Never expand workload size.
- Stop after the selected rows are complete and reviewed.

Exit criterion: selected comparisons have five qualified observations or are
declared inconclusive with a reason.

For canonical initial-table comparisons, these are repetitions 4–5. For the
BIRD architecture screen, run repetitions 2–3 first and expand to five only
when variance could change the conclusion.

### Block 11: final report

The report must include:

- an answer-first executive summary;
- explicit target versions and BIRD thread settings;
- separate synthetic and full-internet bgpdump2 sections;
- median and dispersion, with raw observations preserved;
- timing decomposition rather than the legacy `testers (s)` field;
- CPU and memory comparisons;
- low-memory and contention findings;
- what can and cannot be attributed to the target;
- useful graphs with full workload labels;
- a machine-readable source artifact and standalone HTML output.

Exit criterion: the report passes calculation, source, chart, and narrative QA,
and no claim depends on the legacy `testers (s)` interpretation.

## Primary Questions

The campaign should answer:

1. Does FRR 10.7's high-load synthetic improvement repeat, and which interval
   accounts for it?
2. Does FRR 10.7 remain slower on full-internet MRT playback?
3. Does BIRD 3 threading change target processing time, tester backpressure, or
   only resource use?
4. Is OpenBGPD 9.2's memory reduction stable, and does its longer end-to-end
   time remain after timing decomposition?
5. Does OpenBGPD 8.8 remain safe enough to test at the 64 GB guardrail?
6. Are RustyBGP pinned/default differences stable or workload-specific?
7. Is BIRD or bgpdump2 actually limiting any canonical cell?
8. Is the GoBGP monitor limiting any canonical cell?
9. Does BIRD 3 overtake BIRD 2 when the workload stresses peer scheduling,
   competing-path selection, export fan-out, policy recalculation, or churn?
10. Which BIRD workload dimensions convert additional CPU into lower elapsed
    or operation-completion time?

## Explicitly Deferred on 64 GB

- More than 10 full-internet peers.
- Larger synthetic cells than `50 × 100k`.
- Historical 192/384 GB capacity-cliff experiments; see
  [`2026-memory-capacity-options.md`](./2026-memory-capacity-options.md) for the
  deferred 128/192/256/384 GB planning envelopes.
- Broad route-server or route-reflector matrices.
- Full withdrawal/churn matrices beyond the bounded BIRD architecture screen.
- Multi-host execution unless needed for a small diagnostic validation.
  Spreading one campaign over several machines on purpose is what this
  excludes; being handed a replacement machine of the same shape after a
  spot reclaim is not, and is governed by the host-class rule under Fixed
  Campaign Identity.
- IPv6.

These are not rejected permanently. They require a later plan amendment or
different hardware and must not be smuggled into this campaign.

## Acceptance Rules

A row may support version comparison only when:

- final route/session state is correct;
- required tester events and counts are complete;
- target/tester/monitor provenance is verified;
- no tester error or timeout occurred;
- no material foreign CPU contention occurred;
- memory remained above the named guardrail without swap growth;
- the measurement policy can assign or explicitly leave unresolved the
  limiting component.

Do not delete rejected rows. Preserve them with findings and exclude them only
from the comparisons they cannot support.

**Amendment, 2026-09-12: how much of one RIB a daemon advertises is a
measurement, not a validity test.** An MRT run has no external statement of how
big the table should be -- ten injectors replay one file's overlapping views and
their union is unknowable in advance -- so a rule that judges the *amount* has
to judge it against a guess. The guess is `0.99 * -p`, the per-injector cap, and
three daemons settle on three different counts from the pinned file: 1,081,178
(RustyBGP), 1,056,779 (BIRD and OpenBGPD), ~958,000 (every FRR release). A row
is therefore accepted on **the target's own account of having finished**, and
the amount is reported beside it rather than tested:

- **Ingress is bounded, by measured numbers on both sides.** Every generator
  must report its walk complete, and the target's own accepted-path count is
  checked against what the generators say they offered -- 10,499,716 of
  10,500,000 on one measured `frr_c` row, 0.003% short. Nothing here is a
  guess.
- **Egress is flagged, retrospectively.** The target's export gauge must go
  terminally flat with the monitor level (`target_table.delivery`), and the
  monitor's count must agree with the target's own count of what it sent on
  that session.
- **The share is published, not thresholded** (`export_share`). No measured
  number exists to threshold it with: FRR ends this workload ~11.4% below what
  it holds and BIRD withholds 2.24% of its own table on the same RIB, so both
  constants this project has measured (1%) are too tight and anything above
  them would be chosen to clear the daemons in front of it -- which is how all
  three convergence rules were broken. A row whose daemon publishes no
  best-path gauge says so by name, since an absent check reads as one that
  passed.

**What this accepts**, stated so it is not discovered later: a daemon that
imports a whole RIB and advertises half of it qualifies, with the half reported.
Its `elapsed (s)` is then a convergence time for half a table and is not
comparable with a full exporter's -- which is already true of FRR against BIRD
at 11.4% against 2.24%, and is why every one of this plan's Primary Questions is
a within-daemon comparison. **What it does not cover** is a daemon whose share
*moves* between versions or passes, which would corrupt a within-daemon
comparison; that is `bgperf2-yar`, a cross-pass agreement check in
`summary.py`, and it needs no invented constant because the yardstick is the
same cell's other passes.

**"The target says it is done" must never mean End-of-RIB.** FRR logs that when
its *generators* finish sending; it says nothing about FRR having finished
exporting. A rule built on it stamps completion mid-delivery, permanently and at
a fraction of the table -- it was built, verified and removed, and the
retrospective `delivery` is the sound version. See the measurement decision
log.

## Continuation Prompt

After the measurement implementation release gate passes, use this exact
prompt in a new session:

> continue the 64 GB timing validation campaign

The operator contract for that prompt is:

1. Inspect the release gate, manifest, `COMPLETE` markers, progress data, raw
   rows, logs, and active benchmark processes.
2. Never run benchmark suites or cells concurrently.
3. If a block is active, monitor it. If interrupted, resume it with the same
   run ID, schema version, seed, and repetition identity.
4. Otherwise run or complete exactly one next block under
   `2026-timing-validation`.
5. Perform prerequisites needed by that block, but do not advance into a
   second block.
6. Review correctness, tester evidence, provenance, contention, memory, and
   timing decomposition before accepting the block.
7. Stop at the reviewed block boundary and tell the user to use the exact same
   prompt next time.
