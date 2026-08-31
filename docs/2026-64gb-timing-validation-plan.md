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
- work directory: `/var/tmp/bgperf`
- host class: local 64 GB server
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
- Use `/var/tmp/bgperf`; do not place heavy working data on tmpfs.
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

## Execution Blocks

The follow-up runner should expose `next` behavior and durable `COMPLETE`
markers in this fixed order.

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
