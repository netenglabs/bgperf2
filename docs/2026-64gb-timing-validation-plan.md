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
  writes ~23 GB into the work directory, against the ~5 GB `CLAUDE.md` records,
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

### Block 5: full-internet MRT repetition 1 of 3 -- **built, not yet run**

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

Block 5 is therefore built and **held**, and what
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

### Blocks 6-11

Not started. Each block's configs and procedure are its own change set.

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

### Block 8: BIRD architecture screen

The baseline's initial-table cells do not reproduce the workload BIRD 3 was
designed to scale. BIRD's documented worker group runs BGP protocols,
routing-table maintenance, and exports, while BIRD 3 also decouples exports
from imports. Screen these three configurations:

- BIRD `2.19.2`;
- BIRD `3.3.2` with default threads;
- BIRD `3.3.2` with `threads: 4`.

Run one reviewed observation for each configuration in each bounded scenario:

1. Peer scaling: 50, 250, then 500 peers with 2,000 unique prefixes per peer.
2. Path diversity: 50 peers advertising competing paths for the same 100,000
   prefixes (5 million paths, 100,000 selected prefixes).
3. Export fan-out: 50 ingress peers feeding 10 receiver sessions, with total
   selected prefixes capped at 1 million.
4. Loaded policy recalculation: reload a nontrivial import/export policy with
   50 peers × 50,000 prefixes already present.
5. Churn: withdraw and reannounce a deterministic 10% of a 50 × 50,000 table.

Calibrate upward within each named cap and stop immediately on the standard
memory guardrail. Do not substitute a larger initial-table workload: the point
is to expose independent protocol, route-selection, export, reload, and churn
work that can be scheduled across BIRD 3 worker threads.

Exit criterion: each feasible scenario has correct counts and complete timing,
CPU, memory, and operation evidence, or a durable 64 GB exclusion.

### Block 9: variance, version, and BIRD-screen review

For each workload and version comparison:

- calculate median, range, and coefficient of variation;
- review order effects and cold/warm metadata;
- separate end-to-end, injection, post-injection tail, CPU, and memory findings;
- select only decision-relevant comparisons for optional repetitions 4–5;
- select BIRD architecture scenarios for two additional repetitions when they
  separate versions/thread settings or expose a CPU-scaling change;
- write the selection and reason to durable metadata before running more.

Exit criterion: every optional repetition has a named hypothesis and variance
reason, or the campaign advances with no optional repeats.

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
