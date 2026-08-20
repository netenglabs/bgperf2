# BGP Performance History Summary

## Purpose

This document summarizes the six-post 2021 BGP performance series and relates it to the current state of this repository and its saved results.

It is meant to answer:

- what this project has been doing,
- which tests were actually the most useful,
- what each daemon seemed good or bad at,
- what the hardware and memory constraints were,
- and what gaps remained in the original work.

For the actionable 2026 execution plan, see [`docs/2026-bgp-performance-test-plan.md`](./2026-bgp-performance-test-plan.md).

## Source Material

### The six-post series

This summary is based on these six posts:

1. [`2021-07-26-comparing-open-source-bgp-stacks.md`](/home/jpietsch/elegantnetwork.github.io/_posts/2021-07-26-comparing-open-source-bgp-stacks.md)
2. [`2021-08-09-followup-measuring-BGP-stacks.md`](/home/jpietsch/elegantnetwork.github.io/_posts/2021-08-09-followup-measuring-BGP-stacks.md)
3. [`2021-08-30-comparing-open-source-bgp-internet-routes.md`](/home/jpietsch/elegantnetwork.github.io/_posts/2021-08-30-comparing-open-source-bgp-internet-routes.md)
4. [`2021-09-21-bird-on-bird-bgp-perf-episode4.md`](/home/jpietsch/elegantnetwork.github.io/_posts/2021-09-21-bird-on-bird-bgp-perf-episode4.md)
5. [`2021-10-25-bgp-perf5-1000-internet-neighbors.md`](/home/jpietsch/elegantnetwork.github.io/_posts/2021-10-25-bgp-perf5-1000-internet-neighbors.md)
6. [`2021-11-19-bgperf-first-try-at-filtering.md`](/home/jpietsch/elegantnetwork.github.io/_posts/2021-11-19-bgperf-first-try-at-filtering.md)

### Current repo material

The current repo already captures several later lessons and some 2026 reruns:

- [`README.md`](../README.md)
- [`CLAUDE.md`](../CLAUDE.md)
- [`results/all-daemons.csv`](../results/all-daemons.csv)
- [`results/bird-synth.csv`](../results/bird-synth.csv)
- [`results/bird-mrt-2026.csv`](../results/bird-mrt-2026.csv)
- [`results/frr-synth.csv`](../results/frr-synth.csv)
- [`results/frr-mrt-2026.csv`](../results/frr-mrt-2026.csv)
- [`results/rustybgp-synth.csv`](../results/rustybgp-synth.csv)
- [`results/rustybgp-mrt-2026.csv`](../results/rustybgp-mrt-2026.csv)

`results/` does not appear to contain every artifact behind every blog post. It does contain enough to see the newer cross-version direction and several saved 2026 comparison runs.

## What This Project Has Been Doing

`bgperf2` is a forked and heavily modified `bgperf` workflow for benchmarking BGP daemons in Docker containers. The harness creates:

- a `target` daemon under test,
- one or more `tester` daemons or MRT injectors,
- and a GoBGP `monitor` that measures how many routes the target re-advertises.

The project started as a way to compare open-source BGP stacks with simple route injection. Over time it became a broader attempt to answer several different questions:

- How do these daemons behave with more prefixes?
- How do they behave with more neighbors?
- How do they behave with real internet routes instead of unique synthetic `/32`s?
- How much do the test harness and tester choice affect the result?
- Where are the scaling cliffs?
- How do versions of the same daemon improve or regress over time?

That last question is the important new capability in the repo today.

## Chronological Summary of the Work

### 1. Initial open-source comparison

The first post compared BIRD, FRRouting, and GoBGP with fairly simple tests:

- 10 neighbors x 10k routes,
- 100 neighbors x 10k routes,
- 5 neighbors x 100k routes,
- 5 neighbors x 1M routes,
- 500-neighbor cases,
- and one failed attempt at 10M routes.

Main conclusions at the time:

- BIRD and FRR were usually close in simple scale tests.
- GoBGP used much more CPU and was usually slower than expected.
- FRR neighbor-establishment results were initially skewed by using a dev build by mistake.
- BIRD was badly penalized when bgperf created a separate table per neighbor instead of a single shared table.

This post was useful because it found the first real results, but its biggest value was exposing methodological problems early.

### 2. Systematic follow-up and more daemons

The follow-up post made the testing more systematic and added:

- RustyBGP,
- OpenBGPD,
- more regular parameter sweeps,
- and automated graphing/batch iteration.

This stage was especially useful for revealing:

- strong per-neighbor scaling differences,
- large memory differences between daemons,
- and the fact that OpenBGPD was often the memory outlier.

Important results from this phase:

- OpenBGPD became obviously expensive in memory at high neighbor counts.
- FRR 8 appeared to carry a per-neighbor memory tax relative to FRR 7.5.1 and BIRD.
- RustyBGP sometimes looked attractive in memory, but not consistently in elapsed time.
- Synthetic “1M routes” tests were recognized as unrealistic because they used unique routes rather than shared internet prefixes with best-path competition.

### 3. Internet-route MRT playback

The third post fixed the biggest realism gap in the earlier tests by using Route Views MRT dumps.

Two different MRT generators were tried:

- `bgpdump2`
- GoBGP MRT playback

This was a major step forward because it exercised:

- best-path computation,
- repeated paths across peers,
- and more realistic full-table behavior.

Main results:

- `bgpdump2` was fast enough to stress the target.
- GoBGP as MRT generator was often slow enough to become the bottleneck itself.
- BIRD generally looked best in these tests.
- FRR remained competitive.
- OpenBGPD was slower and more memory-hungry under heavier stress.
- RustyBGP showed inconsistent behavior and completion issues.

This post also showed a key benchmark truth that remains important:

If the tester is the bottleneck, then the test is not measuring the target.

### 4. “Bird on Bird” and tester effects

The fourth post changed the generator story by adding BIRD as a tester in place of ExaBGP for many synthetic tests.

This turned out to matter a lot. It exposed behavior that ExaBGP had been masking:

- BIRD itself had meaningful issues at very high neighbor counts.
- The order in which bgperf started target, tester, and monitor affected what “elapsed time” really meant.
- Some earlier conclusions were partly shaped by tester startup and tester throughput rather than by the target alone.

This post also tightened failure detection:

- fail if counters stall for too long,
- fail if received prefixes drop repeatedly,
- and surface tester errors more explicitly.

It also revisited MRT behavior:

- OpenBGPD’s `enforce neighbor-as` behavior needed config adjustment for these tests.
- RustyBGP improved significantly in some MRT cases after upstream changes.
- Very aggressive hold timers caused failures across multiple daemons.

This was one of the most useful posts methodologically. It showed that the harness itself was part of the experiment.

### 5. 1000-neighbor and large full-table limits

The fifth post pushed toward “how far can this go?” territory with large numbers of peers and full internet tables.

This stage was important mostly because it separated:

- target daemon scaling limits,
- host memory limits,
- and harness/tester limits.

Important conclusions:

- Memory was more important than CPU for many of these extreme tests.
- The 64 GB AMD system was enough for moderate large-table work, but not enough for all extreme cases.
- FRR ran into memory limits and/or high-neighbor completion problems before some others.
- OpenBGPD could finish some large tests, but with very high memory usage and very long times.
- RustyBGP could be extremely fast in some full-table tests, but there were still monitoring and scaling pathologies.

This was also where the project clearly started using multiple hardware classes intentionally rather than incidentally.

### 6. First filter tests

The filtering post addressed the most common feature request: benchmark policy, not just raw prefix ingest.

This was useful less because it produced a clean winner, and more because it exposed the complexity of fair policy testing:

- different daemons report filtered vs accepted routes differently,
- completion detection becomes harder when the monitor should receive fewer routes than the target receives,
- and equivalent policy across daemons is harder to define than simple neighbor/prefix counts.

The first-pass filters were based on NLNOG filter guide patterns and tested “transit” and “ixp” style behavior.

Main conclusions:

- Filtering is testable, but much harder to make fair.
- The first-pass filters did not create strong, simple conclusions about which daemon is “best at filtering”.
- FRR 8 looked better than 7.5.1 in some cases.
- RustyBGP still had rough edges in completion accounting.

## What Tests Were Most Useful

The most useful tests were the ones that isolated distinct capabilities instead of rolling everything into one number.

### Most useful

#### MRT playback with `bgpdump2`

This was the best realism test because it exercised:

- best-path behavior,
- full-table ingest,
- and the ability to keep up with a very fast route source.

It was the best test for differentiating:

- BIRD vs FRR under realistic full-table load,
- OpenBGPD’s memory/performance tradeoff,
- and whether RustyBGP’s multi-core design actually paid off.

#### Many-neighbor, low-prefix synthetic tests

These were the best tests for exposing:

- per-neighbor scaling,
- session-establishment behavior,
- per-peer memory tax,
- and pathologies around timers and large peer counts.

These tests were especially useful for:

- revealing BIRD’s weakness at very high neighbor counts,
- showing OpenBGPD’s memory growth,
- and surfacing FRR’s and RustyBGP’s scaling quirks.

#### Extreme capacity tests

These were useful not because they represent common deployments, but because they revealed failure modes:

- gets stuck,
- never converges,
- runs out of memory,
- fails to establish peers,
- or blocks the state-monitoring path.

These tests were valuable for engineering, not just for performance charts.

### Useful but easy to misread

#### GoBGP as MRT generator

These tests were informative only when the generator was not obviously slower than the target. In many cases, especially at lower peer counts, they measured tester throughput rather than target performance.

#### Small synthetic tests

These are still worth keeping as smoke tests, but they often fail to differentiate the stacks meaningfully.

### Least realistic

#### Unique-prefix “1M route” tests

These are still useful as stress tests, but they are not realistic internet-routing tests because they bypass the best-path question and inflate route cardinality by making every route unique.

## What the Historical Work Says About Each Daemon

### BIRD

Historically:

- very strong on memory efficiency,
- often among the fastest on full-table MRT tests,
- and generally one of the best baseline implementations in these experiments.

Weaknesses that showed up:

- very high neighbor counts,
- the “table per neighbor” trap,
- and later the need to pay attention to BIRD 3 worker-thread configuration.

### FRRouting

Historically:

- usually competitive with BIRD,
- often close enough that tester bottlenecks could hide the difference,
- and generally strong in mainstream, practical scenarios.

Weaknesses that showed up:

- version sensitivity,
- some high-neighbor/session-establishment pathologies,
- and higher memory usage than BIRD.

### OpenBGPD

Historically:

- functional, but slower under heavier stress,
- repeatedly the memory outlier,
- and sometimes requiring target-specific config adjustment for fair testing.

The most important pattern was not “OpenBGPD is always bad”, but “OpenBGPD reaches memory cliffs sooner.”

### RustyBGP

Historically:

- the most interesting design,
- the most inconsistent story,
- and the one most likely to show dramatic speedups in some tests while still having rough edges in others.

Strengths:

- some very fast full-table MRT runs,
- the clearest chance to benefit from multi-core hardware.

Weaknesses:

- completion/accounting problems in some phases,
- monitoring/API path issues under heavy scale,
- and sometimes surprising regressions depending on version and test shape.

### GoBGP

Historically as a target:

- high CPU use,
- underwhelming elapsed times,
- and little evidence in this project that its resource use translated into wins.

Historically as infrastructure:

- very useful as monitor,
- sometimes useful as tester,
- but sometimes a tester bottleneck.

## Hardware and Memory Lessons

### The 64 GB AMD server

The 64 GB AMD system was the primary development and testing platform in the 2021 work, and it remains highly useful.

It was enough for:

- most synthetic tests,
- moderate multi-peer full-table tests,
- systematic comparisons at practical scales,
- and many of the tests that best differentiated the daemons.

It was not enough for everything:

- some FRR large full-table peer-count tests ran out of memory,
- OpenBGPD could hit memory cliffs,
- and the harness itself could consume too much memory in ExaBGP-heavy runs.

The repo has since learned two important operational lessons that matter as much as raw RAM:

- keep the bench directory off tmpfs,
- and record foreign CPU contention so close results are not fake.

### Larger EC2 systems

The larger EC2 boxes were useful mostly because they made memory stop being the first problem:

- M5/M5z class systems made larger full-table neighbor-count tests feasible.
- 192 GB and 384 GB class systems were useful for extreme scaling and failure-mode exploration.

The larger systems did not fundamentally change the ranking of single-thread-bound daemons. They mostly made bigger experiments possible.

### The real bottleneck hierarchy

Across the series, the bottlenecks were usually:

1. memory,
2. target correctness/stability under stress,
3. harness/tester throughput,
4. then CPU.

That is an important framing point for future testing. Raw CPU count alone is not the main constraint for most of this project.

## What the Current 2026 Saved Results Add

The repo now supports explicit version comparison directly. The explicit open-source version set in code is:

- BIRD: `2.19.2`, `3.3.2`
- FRR compiled: `8.5`, `9.1`, `10.0`, `10.7`
- OpenBGPD: `8.8`, `9.2`
- RustyBGP: `2026-02`
- GoBGP: `3.35.0`, `3.37.0`

In addition, each daemon also has an unversioned default image that tracks its configured default ref or upstream tag:

- BIRD, FRR compiled, RustyBGP, GoBGP: default branch image
- OpenBGPD: upstream `latest` tag

The saved 2026 runs in [`results/all-daemons.csv`](../results/all-daemons.csv) already show why this matters.

### BIRD in 2026

The 2026 data says:

- BIRD remains very memory-efficient.
- `2.19.2` and `latest` are still strong baselines.
- BIRD `3.3.2` is sensitive to thread count.

Examples from saved results:

- On synthetic `50 peers x 100k`, BIRD `2.19.2` took `106s` at about `0.56 GB`.
- BIRD `3.3.2` with `1 thread` took `150s` at about `1.08 GB`.
- BIRD `3.3.2` with `4 threads` improved to `110s`, but still did not clearly beat `2.19.2`.
- On MRT `10 peers x ~1.05M`, BIRD `3.3.2` with `1 thread` even has a saved failure, while `4 threads` completes in about the same elapsed time as older BIRD.

Implication:

BIRD 3 needs explicit thread treatment in any serious comparison. Publishing BIRD 3 results without saying how many worker threads were configured is not enough.

### FRR in 2026

The 2026 data shows a mixed story:

- FRR `10.7` is much better on the larger synthetic tests.
- FRR `10.7` is worse on the saved `10-peer` full-table MRT test.

Examples:

- Synthetic `50 peers x 50k`:
  - FRR `8.5`, `9.1`, `10.0` are all around `38s`
  - FRR `10.7` is `28s`
- Synthetic `50 peers x 100k`:
  - FRR `8.5`, `9.1`, `10.0` are around `77-79s`
  - FRR `10.7` is `56s`
- MRT `10 peers x ~1.05M`:
  - FRR `8.5`, `9.1`, `10.0` are around `69-70s`
  - FRR `10.7` is `98s`

Implication:

FRR has not simply “improved linearly with time.” It looks workload-sensitive by version, which makes a version sweep especially worth doing.

### RustyBGP in 2026

The saved 2026 results are also mixed:

- RustyBGP `2026-02` looks better than `latest` in the saved runs.
- `latest` is slower and much more memory-hungry in both synthetic and MRT cases.

Examples:

- Synthetic `50 peers x 100k`:
  - `2026-02`: `46s`, `11.5 GB`
  - `latest`: `79s`, `12.6 GB`
- MRT `10 peers x ~1.05M`:
  - `2026-02`: `26s`, `2.0 GB`
  - `latest`: `24s`, `11.3 GB`

Implication:

RustyBGP still looks like the daemon most likely to produce dramatic changes, but also the daemon most likely to justify careful sanity checks around version behavior.

## What Tests Should Have Been Added Earlier

The biggest missing categories are not “more of the same”, but new dimensions that matter operationally.

### Withdrawal tests

The work focused heavily on initial ingest. That is only half the operational problem.

Useful missing tests:

- full-table withdraw,
- partial withdraw,
- mixed update/withdraw churn,
- and route flap patterns.

### Incremental-update tests

Real deployments care about what happens after the table is loaded.

Useful missing tests:

- start from steady state,
- replay a delta from a real update feed,
- measure churn convergence rather than only cold-start convergence.

### Route-server and route-reflector style tests

Many practical users of these daemons care more about:

- many peers,
- moderate policy,
- partial overlap,
- and reflected/exported behavior

than about “N peers each send a full table at boot”.

### Better policy complexity tests

The filtering post was good, but only a first step.

Missing useful policy categories:

- larger prefix lists,
- AS-path regex scaling,
- community and large-community policies,
- RPKI/ROV if supported,
- and mixed import/export policy sets.

### Multi-host isolation tests

Single-host tests are practical and repeatable, but they mix:

- tester load,
- target load,
- monitor load,
- host memory pressure,
- and file I/O.

The project would benefit from a small validation set where testers, target, and monitor live on separate hosts.

### IPv6

The repo is still effectively IPv4-only. That is a known limitation, but it is still a missing benchmark dimension.
