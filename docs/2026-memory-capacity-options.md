# 2026 Memory Capacity Options

## Status and Scope

This note records what 128, 192, 256, and 384 GB hosts would add beyond the
current 64 GB server. It is a planning aid, not an amendment to the active
[`2026 64 GB Timing Validation Campaign Plan`](./2026-64gb-timing-validation-plan.md).
That campaign retains its 64 GB ceiling, and larger-memory work must not begin
until the measurement implementation release gate and the 64 GB validation
work establish trustworthy timing and bottleneck attribution.

The estimates below are conservative memory-only envelopes derived from the
completed `2026-baseline` observations. They are not promises that a workload
will complete correctly or produce an interpretable timing result.

## Recommendation

- **256 GB is the best general-purpose tier.** It is the first tier that makes
  a broadly comparable 100-full-table-peer matrix credible while retaining the
  campaign's 20% free-memory guardrail.
- **128 GB is the minimum meaningful upgrade.** It captures much of the
  immediate value by making approximately 50 full-table peers and 10 million
  synthetic routes practical.
- **192 GB is useful for large comparative work**, but it is not as clean a
  breakpoint as 256 GB. Prefer it when it is materially less expensive.
- **384 GB is primarily a capacity-cliff platform.** It is important when the
  objective is to find failure limits, but it is not necessary for the main
  version-comparison story.

Near-term, completing the measurement implementation is more important than
acquiring any of these memory tiers. More RAM cannot repair missing tester
completion evidence or distinguish target time from generator and monitor
time.

## Observed Anchors

The active campaign flags a row when minimum free memory falls below 20% of
recorded host memory. Two completed baseline observations provide useful
planning anchors:

1. The worst current `50 peers x 100k synthetic` row was OpenBGPD 8.8. On the
   60.73 GB host it left 10.166 GB free, so host-wide peak use was 50.564 GB.
   The target itself peaked at 37.439 GB.
2. The worst current `10 full-internet peers using bgpdump2` row by host-wide
   memory was the RustyBGP default image. It left 40.485 GB free, so host-wide
   peak use was 20.245 GB. The target itself peaked at 11.46 GB.

The source rows are stored in the campaign's gitignored local result tree:

- `results/2026/2026-baseline/core-synth/2026-core-synth.csv`
- `results/2026/2026-baseline/core-mrt/2026-core-mrt.csv`

The numeric anchors are transcribed above because generated campaign results
are intentionally not committed.

The selected rows have complete, numeric, in-range memory fields. The full MRT
CSV also contains failed or under-required observations for other targets, so
it must not be treated as a clean timing comparison. This note uses its memory
anchor only; it does not reinterpret the legacy `testers (s)` field or draw a
timing conclusion from it.

## Capacity Envelope

For a host with `R` GB of memory, the 20% guardrail leaves `0.8 x R` GB as the
maximum planned host-wide use. Direct proportional scaling from the observed
anchors gives:

```text
full-table peer envelope = 10 x (0.8 x R) / 20.245
synthetic route envelope = 5 million x (0.8 x R) / 50.564
```

Full-table peers are rounded down to the nearest five. A full-table peer
advertises the pinned approximately 1.05 million-prefix table, so peer scaling
primarily adds paths for the same prefix set. Synthetic route counts are total
distinct routes across peers.

| Host memory | Approximate full-table peers | Approximate synthetic routes | Planning role | Importance |
|---:|---:|---:|---|---|
| 128 GB | 50 | 10 million | Minimum meaningful upgrade | High |
| 192 GB | 75 | 15 million | Large comparative work | High |
| 256 GB | 100 | 20 million | General-purpose large-test host | Very high |
| 384 GB | 150 | 30 million | Failure-cliff and capacity research | Medium generally; essential for limit-finding |

These projections assume approximately linear memory growth. Real daemons and
the harness can have fixed costs, nonlinear allocator behavior, duplicated
paths, delayed reclamation, or failure before memory becomes the limiting
resource. Every new workload must therefore calibrate upward from a smaller
cell and stop on the normal memory, swap, correctness, contention, or tester
evidence guardrail.

## What Each Tier Adds

### 128 GB

This is the first upgrade that materially changes the feasible test set:

- approximately 50 full-table peers across the current target set;
- approximately 100 peers x 100k synthetic routes in memory terms;
- larger OpenBGPD full-table tests;
- bounded real-table policy, withdrawal, and path-diversity experiments.

OpenBGPD 8.8 at 100 x 100k would be close to the projected 20% guardrail, so it
must be treated as a calibrated, daemon-specific cell rather than assumed to
fit the full matrix.

### 192 GB

This is the historical "large but still comparative" tier:

- comfortable 50-full-table-peer cross-version and filter matrices;
- a conservative all-target envelope of approximately 75 full-table peers;
- selected 100-full-table-peer runs for more memory-efficient daemons;
- more ambitious policy, partial/full withdrawal, and churn work on real
  tables;
- broader FRR, BIRD, and OpenBGPD full-table scaling.

The older test plan assigns 50 to 100 full-table peers to this class. Current
data supports the lower part of that range comfortably, but the 100-peer end
should remain calibrated and daemon-specific.

### 256 GB

This is the strongest all-round tier:

- an approximately 100-full-table-peer all-target comparison envelope, or
  about 105 million incoming paths from the pinned table;
- approximately 20 million synthetic routes in memory terms;
- broad route-server and route-reflector fan-out matrices;
- competing-path selection, policy reload, withdrawal, and churn at 50 to 100
  full-table peers;
- enough headroom to distinguish more daemon memory cliffs from the host's own
  guardrail.

This tier provides the clearest qualitative step beyond the 64 GB campaign. If
one larger host will be kept for repeated use, 256 GB is the recommended size.

### 384 GB

This tier changes the objective from comparative scaling to finding limits:

- approximately 150 full-table peers across the target set, with further
  daemon-specific pushes where memory remains clean;
- RustyBGP and OpenBGPD capacity-cliff exploration;
- a return to the historical 1,000-neighbor direction;
- long-running stability, reclamation, and failure-mode experiments;
- combined high-path-count, policy, fan-out, and churn stress.

It does not establish that 1,000 full-table peers will fit. The checked-in
[`big-tests.yaml`](../benchmarks/big-tests.yaml) note concerns 1,000 peers x
1,000 prefixes on a 384 GB machine, plus still-larger peer counts with much
smaller per-peer tables. A 1,000-full-table-peer experiment would be a separate
capacity investigation with no assurance of completion.

## RAM Is Not the Only Ceiling

Completed OpenBGPD 9.2/default and RustyBGP default `50 x 100k synthetic`
observations reached only 1% to 2% host idle. The corresponding FRR observations
retained roughly 20% to 43% host idle while the FRR target container peaked near
one logical CPU. That is consistent with a target-core ceiling rather than
whole-host exhaustion, although a maximum alone does not show how long the
target stayed at the ceiling. A historical `100 x 100k` FRR observation did
reach 0% host idle while its target container peaked near 1.2 logical CPUs,
showing additional benchmark or host load without identifying which component
produced it.

The published `max cpu %` and `min idle%` values are independent extrema:
`max cpu %` covers only the target container, `min idle%` covers the whole host,
and the current results do not separately sample tester, monitor, controller,
or kernel CPU. Do not subtract the extrema or label the tester as the limiting
component from these fields alone. Reliable attribution requires time-aligned
per-role CPU samples; until those exist, record near-zero host idle as
`host CPU saturated; component unresolved`.

On the same CPU, more RAM would store more state but would not automatically
produce trustworthy convergence timings. High-peer synthetic work may require
more physical cores or separation of testers, target, and monitor across
hosts. More cores will not make a single-core-limited BGP daemon itself scale,
but they can preserve headroom for the rest of the benchmark.

The larger-memory tiers therefore have their highest value for:

- full-table path count and best-path state;
- OpenBGPD memory behavior;
- route-server or route-reflector export state;
- policy state and re-evaluation;
- withdrawal, churn, and memory-reclamation behavior;
- separating daemon memory limits from host memory limits.

They have less value for basic cold-start version comparisons that already fit
comfortably on 64 GB, and they do not automatically make single-thread-bound
daemons faster or more representative.

## Execution Order

1. Complete the measurement implementation release gate.
2. Complete and review the bounded 64 GB timing validation campaign.
3. Use its repeated memory, CPU, tester, and monitor evidence to revise these
   envelopes.
4. If larger hardware is available, calibrate one workload dimension at a
   time and preserve the 20% memory guardrail.
5. Prefer 256 GB for a durable general-purpose host, 128 GB for the lowest-cost
   meaningful upgrade, and 384 GB only when capacity-cliff work is a recurring
   objective.

If cloud hardware is used, keep host type and CPU allocation fixed within each
comparison curve. Cloud instance sizes can change CPU allocation along with
memory, so different sizes are different host classes and must not be treated
as a memory-only comparison. Check the current
[`M8a instance specifications`](https://aws.amazon.com/ec2/instance-types/m8a/)
before scheduling rather than relying on a saved price or availability table.
