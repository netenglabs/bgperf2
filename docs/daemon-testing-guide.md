# Guide to daemon comparison and capacity testing on 64 and 128 GB hosts

Use 64 GB for the common comparison matrix and initial capacity curves. Use
128 GB to extend interesting curves and investigate limits. Obtain more memory
only when an identified experiment cannot fit either tier and its next point
would answer a useful question.

This guide describes an experimental approach, not a scheduled campaign or an
amendment to an existing operator contract. The measured anchors below come
from the [2026 comparison evidence](2026-daemon-comparison-evidence.md) and
[report](2026-daemon-comparison-report.md). Proposed experiments are not results.
The report's "What to test next" section provides further context.

## Decide what question the test answers

Keep three questions separate:

1. **Comparison:** at the same workload and resource allocation, which build
   finishes sooner, uses less memory, and delivers the expected routes?
2. **Capacity:** within a fixed resource budget, how large a correct, stable
   workload can each build handle?
3. **Regression:** has a new build changed a specific previously observed
   problem?

A fast run with missing routes or incorrect protocol behavior is not equivalent
to a correct run. A memory-efficient implementation should be allowed to
continue its capacity curve after another implementation stops. Conversely,
compare speed at shared workload points, rather than comparing each daemon's
time at a different maximum workload.

## Use both synthetic prefixes and MRT playback

| Workload | Main value | Limitation |
|---|---|---|
| Synthetic prefixes from BIRD | Control sessions, destination count, competing paths, and repeatable operations | Simplified attributes; performance need not predict real-table behavior |
| MRT playback with bgpdump2 | Real AS paths, communities, and distributions of competing paths | Adding source peers also changes the route mix; a finite dump limits distinct source-peer coverage |

Synthetic tests can separate dimensions that are entangled in real tables:

- **Session count:** vary sessions while holding total distinct destinations
  constant using `prefix_scope: total`.
- **Destination count:** increase distinct prefixes while holding sessions
  constant.
- **Competing paths:** use `path_diversity` to vary paths per destination. Plan
  the arithmetic explicitly: changing diversity at fixed peers and prefixes
  changes the destination count too. Choose whether the experiment holds
  destinations or incoming paths constant, and report what else changes.
- **Operations on a loaded table:** controlled withdrawal/reannouncement and
  policy reload experiments.

The controls have compatibility restrictions; consult
[workload controls](invariants/workload-controls.md). In particular,
`prefix_scope: total` and `path_diversity` cannot be combined. The existing
churn and policy-reload mechanisms use synthetic BIRD generators; extending
them to MRT or unsupported targets requires implementation and validation.
Do not assume a larger host makes those operations available.

Fifty synthetic peers with 100,000 disjoint prefixes offer **five million
distinct destinations**. Fifty full-table MRT peers offer approximately
**50 million incoming paths to largely the same destination set**, assuming
roughly one million prefixes per peer. These stress different state.

Both workloads are necessary: in the measured comparison, OpenBGPD 9.2/9.3
used much less memory than 8.8 but finished later on the synthetic workload
and earlier on the MRT peer sweep. Neither workload alone gives the full
upgrade story.

## Establish reproducible conditions before measuring

- Pin each tested build to a revision or immutable binary identity. Record
  source commit, image identity, reported version, toolchain and dependency
  identity where available. Preserve the historical images. A `latest` or
  nightly label does not identify a build.
- Use the sink monitor for the new series. Historical GoBGP-monitor results
  are context, not points to pool with sink results.
- Record usable host memory, CPU model and topology, kernel, Docker version,
  CPU allocation, generator identities, configuration, and input checksums.
- Keep the host free of competing work. Build images and inspect large inputs
  before benchmarking. Run one benchmark at a time.
- Put the work directory on disk, outside the root filesystem and outside
  tmpfs. Preserve each run's artifacts before the work directory is reused.
- Choose a host-specific CPU layout with disjoint sets for all container
  roles when using `--pin`. Historical 32-core layouts cannot be copied onto
  a 16-core machine. Leave room for controller and kernel work where practical.
- Run a tiny smoke test first, then calibrate the proposed workload before
  launching repetitions.

For new capacity work, use a **20% available-memory reserve** as the starting
guardrail and record the threshold in the experiment definition. An existing
contract governs runs performed under that contract: the historical daemon
comparison lowered its threshold to 15%, while the memory-capacity planning
envelope retains 20%. This guide does not change either rule.

See [host and environment](invariants/host-and-environment.md) and
[provenance and verification](invariants/provenance-and-verify.md).

## Start with current RustyBGP on 64 GB

Compare a pinned current build with retained August and February builds on the
same host. Begin with the following checks; add other daemons at shared
workload points to put improvements in context.

| Question | Starting experiment | Evidence to retain |
|---|---|---|
| Has MRT memory growth changed? | Small calibration, then 10 and 17 full-table peers from the same nested rrc00 peer sets | Target-memory curve, host available-memory curve, delivered prefixes, completion evidence |
| Have synthetic delays and hold-timer expiries changed? | Calibrate upward to 50 peers × 100,000 distinct prefixes, in separate pinned and unpinned series | Timing distribution, tester-health logs, session resets, delivery and per-role CPU evidence |
| Has the no-delivery failure recurred? | Repeated startups and full runs under the arrangements being compared | Failed passes, startup/session evidence, daemon logs and exit status |
| Does it enforce NO_EXPORT and NO_ADVERTISE? | Small targeted export tests with explicit expected outcomes | Advertisements to eligible/ineligible receivers and session health |
| Is the long-AS_PATH edge case still handled correctly? | Replay the recorded boundary case | Encoded UPDATE or receiver evidence and resulting route disposition |

The historical issues have different build identities:

- **August:** accelerating MRT memory consumption and synthetic hold-timer
  expiries. Its target peaks were 11.386 GiB at 10 full-table peers and
  26.590 GiB at 17 peers.
- **September:** hold-timer expiries persisted in pinned synthetic runs; one
  unpinned pass failed with no delivered prefixes. A successful rerun did not
  erase that failed pass.
- **February:** malformed AS_PATH when prepending to a first segment already
  containing 255 ASes. Later tested builds handled that case correctly. This
  is a regression check, not an August defect.
- **Community handling:** source inspection found no automatic NO_EXPORT or
  NO_ADVERTISE enforcement in the named historical builds under the tested
  configuration. Verify current behavior dynamically; do not assume it changed.

The five-million-prefix synthetic comparison already ran on a nominal 64 GB
host. That establishes feasibility for those tested builds and conditions,
not a guarantee for a new build or a machine with fewer available CPU cores.

An improvement at 10 and 17 MRT peers is meaningful even if the machine cannot
reach the later cliff. Report “lower memory at the tested sizes,” rather than
“the capacity problem is fixed.” If headroom remains adequate, extend the
current build independently. August's 24-peer target peak was 47.877 GiB, so
that historical build is not a routine 64 GB comparison cell.

The existing [synthetic config](../benchmarks/2026-comparison-synth.yaml) and
[10-peer MRT config](../benchmarks/2026-comparison-rrc00-n10.yaml) are workload
references. Make new configs with immutable build labels, new artifact names,
and the actual host's CPU allocation. Do not execute their old layouts blindly.
Small protocol checks require a targeted test setup; they are not established
as automatic checks merely by running a normal `bench`.

## Extend capacity curves on 128 GB

Advance one workload dimension at a time. Use wider steps while there is ample
headroom, then smaller steps near a boundary. Inspect each calibration point
before committing to the next one.

For every build, record:

- the largest tested workload that completed correctly with adequate headroom;
- the next attempted point, if any, and the observed reason it was not accepted;
- whether the curve stopped because of the daemon, the benchmark apparatus,
  the host budget, or the available input data.

A last accepted point is a **tested lower bound on capacity**, not the maximum
supported peer count. A guardrail rejection is not proof the daemon crashed.
A finished run under severe memory pressure can retain useful memory evidence
while its timing is excluded from the accepted curve.

The August RustyBGP build demonstrates what 128 GB adds: its target used
73.829 GiB at 31 full-table peers, exceeding a 64 GB host by itself. That point
was accepted on the larger host. At 38 peers, the target reached 110.789 GiB
and host available memory fell to 1.314 GiB; all three timings were excluded.

At the same 38-peer workload, target peaks for other builds were much lower:

| Build | Peak target memory, GiB |
|---|---:|
| BIRD 3.3.2, default threads | 5.989 |
| FRR 10.7 | 20.813 |
| OpenBGPD 9.3 | 10.332 |
| RustyBGP February | 10.247 |
| RustyBGP August | 110.789 |

These observations justify continuing efficient implementations within the
128 GB budget. They do not establish their eventual limits or prove that the
whole 38-peer experiment would fit 64 GB for every other build.

The pinned rrc00 input has 38 distinct full-table source peers. Beyond that,
repeating peers adds sessions and duplicate source paths; it does not add new
real source-peer diversity. Find and validate additional input or define a
synthetic extension, and give the changed workload its own series.

## Compare speed and behavior before declaring that another daemon catches up

At shared workload points, compare elapsed time alongside delivered routes,
session stability, correctness, and resource consumption. RustyBGP February's
short MRT times are interesting, but differences in exported counts and
protocol behavior prevent treating the existing results as a universal ranking.

Use at least three complete matrix passes with recorded shuffled order for
initial comparisons. Add observations when spread or intermittent failures
make the answer unclear. Keep pinned and unpinned arrangements separate.
Repeating startups can detect a recurrence, but a small set with no failures
does not establish that an intermittent issue is gone.

Read tester completion and sample resolution beside elapsed time. Read
time-aligned per-role CPU when available; independent CPU extrema cannot
identify the limiting component. Existing role CPU samples omit controller
and kernel work, and do not automatically change a finding's verdict.
Use the findings' named refusals instead of filling unresolved attribution
with a guess. See [findings](invariants/findings.md).

Preserve failed passes separately from passes that have not run. Do not replace
a failure with a successful rerun, or publish absent measurements as zero.
See [batch passes](invariants/batch-passes.md).

## Request more memory only for a concrete unanswered question

Examples include an acceptable August RustyBGP 38-peer timing comparison,
continued nonlinear memory growth, or withdrawal/reload peaks that exceed
128 GB even though steady-state memory fits. These are distinct experiments.
Long-running churn, reclamation and recovery checks may need additional
instrumentation; the ordinary convergence row does not establish those results.

Size the next host from **whole-host** peak use, including generators,
receivers, logs/cache and the operation under test. With a 20% reserve:

```text
minimum usable host memory ≈ measured whole-host peak use / 0.8
```

Allow extra margin for growth between steps and sampling gaps. This is a
sizing estimate, not assurance that a workload will complete. August's
38-peer pressure makes 192 GB a plausible next calibration tier and 256 GB a
roomier choice. No measured evidence here establishes a general requirement
for 384 GB, 512 GB or 1 TB.

The older [memory-capacity options](2026-memory-capacity-options.md) projected
roughly 50 full-table peers on 128 GB and 100 on 256 GB from linear anchors.
August RustyBGP's accelerating curve means those figures cannot be promised
for a matrix including that build. Recalibrate each build rather than assuming
linear growth.

When moving to another host, rerun overlapping smaller points and keep the
series distinct. A larger cloud instance often adds CPU cores as well as RAM;
an improvement across hosts is not automatically a memory effect.

## What the resulting report should say

For each build and workload, report the tested identity, host and allocation,
correctness/delivery outcome, timing spread, target and whole-host memory,
session failures, and the last accepted capacity point with its stopping reason.
Identify which earlier symptoms recurred, which were absent in the new tests,
and which remain untested.

The intended outcome is a useful comparison on accessible hardware: most
experiments on 64 GB, selected extensions on 128 GB, and larger machines used
only to follow a specific unfinished capacity curve. It can establish both
whether current RustyBGP has improved and how other daemons compare, without
requiring every implementation to reach its ultimate limit first.
