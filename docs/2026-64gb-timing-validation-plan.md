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

    **Blocks 0-2 cannot be checked against this rule**, and that is stated
    rather than left to be discovered: `instance_facts()` landed on 2026-09-10
    with the rule itself, so `host.instance` is absent from all three of their
    manifest entries and from Block 2's carried one. What those blocks have is
    CPU model, vCPU count, memory and hostname, which agree across all four
    entries; the instance type they ran under is not recorded anywhere and
    cannot be recovered. Blocks 3 onward record it.
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

### Block 2: high-load synthetic repetition 1 of 3 -- **ran 2026-09-10, not accepted**

Ran at bgperf2 `4b43ebf`, work directory `/data/bgperf-work`, from
`benchmarks/2026-timing-synth-rep1.yaml`: 14 target configurations at 50 peers
x 100,000 prefixes per peer (5,000,000 distinct prefixes), BIRD generator, no
policy, one cell at a time, `order: shuffle` seed 20262. Every configured run
produced a row. **12 of 14 qualified**; the block did not meet its exit
criterion and is recorded here as run rather than accepted.

**It took two attempts on two hosts.** The first measured ten rows on
`ip-172-31-21-79` and was ended by an EC2 spot reclaim between cells; the
replacement instance `ip-172-31-18-191` measured the remaining four. Both are
in `metadata/manifest.json` -- the second under `blocks.block2-synthetic-rep1`,
the first under its `previous_entries`, with the ten run names it accounts for.
That merge did not exist when the reclaim happened and the first host's record
was overwritten by the resume; it was rebuilt from a copy taken before the
resume and is marked `reconstructed`. From the next block onward
`campaign_merge_block_facts.py` writes it.

| run | host | `elapsed (s)` | `max cpu %` | `max mem (GB)` | `min free mem (GB)` | verdict |
|---|---|---|---|---|---|---|
| bird 2.19.2 | 1st | 91 | 102 | 0.561 | 49.9 | **rejected** -- 1 tester error |
| bird 3.3.2 (default threads) | 2nd | 117 | 102 | 1.087 | 49.0 | qualified |
| bird 3.3.2 (4 threads) | 1st | 108 | 200 | 1.110 | 48.9 | qualified |
| bird default (2.19.0-master) | 1st | 91 | 101 | 0.558 | 50.0 | **rejected** -- 2 tester errors |
| frr_c 8.5 | 1st | 91 | 112 | 8.254 | 42.5 | qualified |
| frr_c 9.1 | 1st | 94 | 112 | 8.199 | 42.5 | qualified |
| frr_c 10.0 | 1st | 90 | 111 | 7.655 | 43.6 | qualified |
| frr_c 10.7 | 1st | 84 | 112 | 6.284 | 44.3 | qualified |
| frr default | 2nd | 84 | 113 | 5.733 | 45.1 | qualified |
| openbgp 8.8 | 1st | 620 | 110 | 37.437 | 12.4 | qualified |
| openbgp 9.2 | 2nd | 733 | 127 | 18.533 | 33.2 | qualified |
| openbgp default (9.2) | 1st | 724 | 126 | 18.688 | 33.1 | qualified |
| rustybgp 2026-02 | 2nd | 65 | 1074 | 12.252 | 38.3 | qualified |
| rustybgp default | 1st | 154 | 1161 | 16.861 | 37.9 | qualified |

Every row converged, received 5,000,000 against a required 4,950,000, carried
three-role plus tool provenance, and produced an ordered and complete event
stream with its generator complete. Every row's verdict is `unresolved` via
`injection_boundary_unresolved`, which is the expected shape here and not a
defect: the BIRD 2.19 generator's `Export updates accepted` is queue-side and
saturates before the first poll, so no run in this block can be attributed to a
component. That is a property of the generator, recorded in Phase 5A and
reached again from the campaign side; wire-side evidence needs a BIRD 3
generator, which the CLI cannot select today.

**What rejected the two rows, and what cannot be said about it.**
`tester_health` requires no tester error or timeout, and `find_errors()` counts
BIRD `<RMT>` log lines that are neither `NEXT_HOP` nor `Invalid route ...
withdrawn` -- so one and two such lines, out of 5,000,000 routes across 50
sessions, decided both rows. The lines themselves do not survive: `bench()`
wipes the work directory at the start of every cell, eleven cells ran after
them, and the host was reclaimed. The review therefore has a count and no text,
which is an exclusion with a number rather than the exclusion with evidence the
Acceptance Rules ask for (`bgperf2-7ou`). Both rejected rows are BIRD
2.19-family targets and both come from the first attempt; a scan of every CSV
under `results/` finds only one other non-zero `tester errors` value in the
project's history, so this is sporadic rather than a property of that target.

**A reproduction was attempted and did not reproduce it.** One `bird 2.19.2`
run at the same 50 x 100,000, outside the campaign tree and with its tester
logs kept, converged in 95s against the block's 91s with **0 tester errors**
and 0 timeouts, out of 247 million `<RMT>` lines -- all of them the
`Invalid route ... withdrawn` that `find_errors()` already excludes, which is
the target re-advertising to generators running `import none`. That is
consistent with sporadic and is not evidence that the two rejected rows were
benign: one negative run cannot be, and the lines that were counted are gone.
It does bound the cost of the tail -- those logs were **23 GB** for one run,
against the ~5 GB this repository records for that shape, so a block's work
directory needs headroom nearer 25 GB per cell than 5.

**An accidental cross-host control, and it is small.** `openbgp default` and
`openbgp 9.2` are the same upstream release reached through two image tags --
`bgperf/openbgp:latest` and `:9.2`, different image IDs, both reporting 9.2 --
and the shuffle put one on each host. They agree to **1.2% on `elapsed (s)`**
(724 against 733), 0.8% on `max mem (GB)` (18.688 against 18.533) and 0.5% on
`min free mem (GB)`. That bounds host *plus* image build *plus* shuffled
position together, not the host alone, so it is an upper bound and not a
measurement of the replacement's effect -- but it is the only evidence this
campaign has on the question, and at ~1% it is well inside what the variance
rule is built to separate. It is not a substitute for reading Block 9's three
passes.

Three things the block cost, stated rather than left in the artifacts:

- **Two rows carry foreign CPU an order of magnitude above the block's floor,
  and the cause was the session reviewing it.** `bird 3.3.2 (default threads)`
  and `openbgp 9.2` report `max foreign cpu %` 9 against 1-4 everywhere else;
  both ran while this session was editing documents and running `bd` on the
  same host. Nine percent is 0.09 cores, an order of magnitude under the
  threshold that would withhold a verdict -- Block 1 recorded the same shape
  for its calibration watcher -- and `openbgp 9.2` is one half of the cross-host
  pair above, which agreed to 1.2% while carrying it. It is still contention the
  benchmark manufactured, and the rule it produces is that a block's review
  waits for the block.
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
  swapped.

The block's remaining decision is the operator's and is not taken here: accept
with `accept 2 --with-exclusions` naming the two rows, or re-measure the block
with `--force`, which would also give it one host and clean contention at the
cost of discarding twelve rows that qualified.

### Blocks 3-11

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
