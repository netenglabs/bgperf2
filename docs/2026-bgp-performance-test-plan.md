# 2026 BGP Performance Test Plan

## Purpose

This document is the execution-oriented companion to [`docs/bgp-performance-history-summary.md`](./bgp-performance-history-summary.md).

It focuses on:

- what to test now,
- what versions to include,
- what should run on the local 64 GB server,
- what should be deferred to larger-memory hardware,
- and how to update the MRT data used for playback.

## Scope

The practical open-source/versioned targets supported by this repo today are:

- BIRD
- FRR compiled
- OpenBGPD
- RustyBGP
- GoBGP

The broader target registry in [`bgperf2.py`](../bgperf2.py) also includes `junos`, `eos`, and `srlinux`, but those are not part of the open-source/versioned sweep plan because they depend on external images and a different operational setup.

## Current Version Matrix

Use this as the main comparison set.

### BIRD explicit versions

- `2.19.2`
- `3.3.2`

Defined in [`bird.py`](../bird.py).

Unversioned default image:

- the default branch image (`bgperf/bird:latest`)

### FRR compiled explicit versions

- `8.5`
- `9.1`
- `10.0`
- `10.7`

Defined in [`frr_compiled.py`](../frr_compiled.py).

Unversioned default image:

- the default branch image (`bgperf/frr_c:latest`)

### OpenBGPD explicit versions

- `8.8`
- `9.2`

Defined in [`openbgp.py`](../openbgp.py).

Unversioned default image:

- the upstream `latest`-tracking image (`bgperf/openbgp:latest`)

### RustyBGP explicit versions

- `2026-02`

Defined in [`rustybgp.py`](../rustybgp.py).

Unversioned default image:

- the default branch image (`bgperf/rustybgp:latest`)

### GoBGP explicit versions

- `3.35.0`
- `3.37.0`

Defined in [`gobgp.py`](../gobgp.py).

Unversioned default image:

- the default branch image (`bgperf/gobgp:latest`)

## What the Saved 2026 Results Already Suggest

The saved results in [`results/all-daemons.csv`](../results/all-daemons.csv) suggest that version differences are large enough to justify a full sweep.

Examples:

- FRR `10.7` is much faster than the explicit `8.5/9.1/10.0` versions on the larger saved synthetic tests, but slower on the saved `10-peer` full-table MRT case.
- BIRD `3.3.2` is sensitive to thread count and should not be benchmarked without saying how many worker threads were configured.
- RustyBGP’s unversioned default image looks materially worse than explicit version `2026-02` in several saved runs, especially for memory.

That means the sweep should be organized by workload class, not by an assumption that “newer is better”.

## Operational Ground Rules

Before any sweep:

```bash
./bgperf2.py doctor
./bgperf2.py images
./bgperf2.py verify
```

Then build what is missing:

```bash
./bgperf2.py prepare
./bgperf2.py prepare -t bird --versions 2.19.2,3.3.2
./bgperf2.py prepare -t frr_c --versions 8.5,9.1,10.0,10.7
./bgperf2.py prepare -t openbgp --versions 8.8,9.2
./bgperf2.py prepare -t rustybgp --versions 2026-02
./bgperf2.py prepare -t gobgp --versions 3.35.0,3.37.0
```

The checked-in batch configs for this plan are:

- [`benchmarks/2026-smoke.yaml`](../benchmarks/2026-smoke.yaml)
- [`benchmarks/2026-core-synth.yaml`](../benchmarks/2026-core-synth.yaml)
- [`benchmarks/2026-core-mrt.yaml`](../benchmarks/2026-core-mrt.yaml)
- [`benchmarks/2026-filters.yaml`](../benchmarks/2026-filters.yaml)

For every benchmark run:

- use a disk-backed bench directory such as `/var/tmp/bgperf`,
- avoid a tmpfs-backed `/tmp`,
- make sure the machine is otherwise idle,
- record `max foreign cpu %`,
- and keep the monitor/tester/target image versions in the final artifacts.

The repo now also has helper scripts for this workflow:

- [`scripts/prepare_mrt.sh`](../scripts/prepare_mrt.sh)
- [`scripts/preflight_2026_suite.sh`](../scripts/preflight_2026_suite.sh)
- [`scripts/run_2026_suite.sh`](../scripts/run_2026_suite.sh)

## Core 64 GB Sweep

This is the main plan for the local AMD server with 64 GB RAM.

The goal is not to run the biggest possible test first. The goal is to get a clean, reproducible cross-version comparison at scales that are large enough to be meaningful and still comfortable on this host.

### Phase 0: sanity and reproducibility

For each target family:

- confirm images exist,
- confirm they report the expected versions,
- run one tiny smoke test.

Suggested smoke test:

- `10 peers x 100 prefixes`

This is not for publication. It is only to catch broken images or obvious harness problems before larger runs.

Run it with:

```bash
./bgperf2.py -d /var/tmp/bgperf batch -c benchmarks/2026-smoke.yaml
```

Or through the suite runner:

```bash
scripts/run_2026_suite.sh smoke --run-id 2026-baseline --workdir /var/tmp/bgperf
```

### Phase 1: core synthetic matrix

Run every open-source target/explicit-version and each daemon’s unversioned default image on:

- `10 peers x 50k`
- `10 peers x 100k`
- `50 peers x 50k`
- `50 peers x 100k`

Why these four:

- the 10-peer tests are quick controls,
- the 50-peer tests expose per-neighbor scaling,
- and the saved 2026 data already shows that these sizes differentiate FRR, BIRD, and RustyBGP versions.

### Phase 1 special handling

#### BIRD

Run BIRD `3.3.2` in two modes:

- default worker-thread behavior
- explicit `threads: 4`

If a public comparison needs one canonical BIRD 3 line item, use the explicit threaded result and state it clearly.

#### GoBGP

Include GoBGP in the sweep, but do not let it dominate runtime.

If it is clearly noncompetitive or unstable in the first half of the matrix, keep the result and reduce later cells rather than spending disproportionate time on it.

### Phase 2: core MRT realism matrix

Run every open-source target/explicit-version and each daemon’s unversioned default image on:

- `10 peers x full current Route Views table`

This is the highest-value realism test that still fits the 64 GB server comfortably.

It should be treated as the main “real-world-ish” comparison.

### Phase 3: 64 GB extension set

Only after Phases 1 and 2 are stable:

- MRT `20 peers x full table` for BIRD, FRR, RustyBGP first
- synthetic `100 peers x 10k` for all open-source daemons
- synthetic `100 peers x 50k` only if runs remain stable and clean

These are useful, but they are no longer the baseline comparison set.

The checked-in synthetic and MRT configs are runnable as:

```bash
./bgperf2.py -d /var/tmp/bgperf batch -c benchmarks/2026-core-synth.yaml
./bgperf2.py -d /var/tmp/bgperf batch -c benchmarks/2026-core-mrt.yaml
```

Or through the suite runner:

```bash
scripts/run_2026_suite.sh core-synth --run-id 2026-baseline --workdir /var/tmp/bgperf
scripts/run_2026_suite.sh core-mrt --run-id 2026-baseline --workdir /var/tmp/bgperf
```

## Filter Test Add-On

Filtering should be treated as a reduced secondary matrix, not part of the first baseline sweep.

Suggested filter matrix:

- `10 peers x full-table MRT`
- `50 peers x 100k synthetic`

For each:

- no filter
- “transit” style filter
- “ixp” style filter

The point is not to produce a universal “best filter daemon” result. The point is to see whether version changes materially alter policy-processing cost.

Run it with:

```bash
./bgperf2.py -d /var/tmp/bgperf batch -c benchmarks/2026-filters.yaml
```

Or through the suite runner:

```bash
scripts/run_2026_suite.sh filters --run-id 2026-baseline --workdir /var/tmp/bgperf
```

## Missing But Valuable Future Add-Ons

These would improve the benchmark story after the baseline sweep is complete.

### Withdrawal tests

- full-table withdraw
- partial withdraw
- mixed update/withdraw churn

### Incremental steady-state tests

- load the table
- then replay a smaller delta
- measure convergence after steady state, not just cold start

### Route-server/route-reflector tests

- many peers
- moderate policy
- more realistic export patterns

### Multi-host validation

Use a small validation subset where:

- testers are on one host,
- target is on another,
- monitor is on another

This would tell us how much the single-host setup is biasing the results.

## Tests for Larger-Memory Hardware

The 64 GB server should not be the default platform for every large test.

### 192 GB class hardware

Use this tier for:

- `50 to 100 peers x full current MRT table`
- larger OpenBGPD full-table tests
- broader FRR and BIRD multi-version full-table scaling
- more ambitious filter testing on real tables

This is the right tier for “large but still comparative”.

### 384 GB class hardware

Use this tier for:

- `150+ peers x full current MRT table`
- RustyBGP capacity pushes
- any attempt to revisit the “1000 full-table neighbors” direction
- long-running failure-cliff exploration

This is the right tier for “find the limit”.

### What bigger hardware is buying

Mostly:

- headroom,
- less risk that the host is the real bottleneck,
- and clearer separation between daemon limits and harness limits.

It is not automatically buying more representative results for single-thread-bound daemons.

## Recommended Result Categories

A new write-up should separate these categories explicitly.

### Moderate realistic performance

Focus on:

- `10 peers x full table`
- `50 peers x 50k`
- `50 peers x 100k`

### Memory efficiency

Focus on:

- target process memory
- minimum free host memory
- and whether log/tmpfs artifacts contaminated the reading

### Capacity and failure cliffs

Focus on:

- when runs stop converging
- when peers stop establishing
- and when memory or harness behavior becomes the limiting factor

Keeping these categories separate will make the new results easier to interpret than a single “fastest daemon” storyline.

## MRT Update for 2026

The old 2021 work used an August 2021 Route Views table. The repo already moved toward August 2026 data in [`README.md`](../README.md), which is correct because the routing table has grown significantly since 2021.

Use at least a 2026 `route-views2` RIB.

For reproducibility, the checked-in batch configs in this repo pin a specific known-good baseline file from Friday, August 8, 2026:

```bash
mkdir -p mrt
curl -o mrt/rib.bz2 \
  https://archive.routeviews.org/route-views2/bgpdata/2026.08/RIBS/rib.20260808.0000.bz2
bunzip2 mrt/rib.bz2 && mv mrt/rib mrt/rib.20260808.0000
```

Before any sweep, verify what the chosen RIB actually contains:

```bash
docker run --rm --entrypoint= -v $PWD/mrt/rib.20260808.0000:/root/mrt_file \
  bgperf/bgpdump2 /usr/local/sbin/bgpdump2 -c /root/mrt_file
```

The helper wrapper for that step is:

```bash
scripts/prepare_mrt.sh mrt/rib.20260808.0000
```

That validation step is required because:

- different peers in the dump can carry different prefix counts,
- not every peer is a full-feed peer,
- and the benchmark should not assume a fixed “full table” size without checking.

The Route Views naming pattern remains:

```text
https://archive.routeviews.org/route-views2/bgpdata/YYYY.MM/RIBS/rib.YYYYMMDD.HHMM.bz2
```

If the goal is strict reproducibility against the checked-in batch configs, keep using `rib.20260808.0000`.

If the goal is to refresh to a newer August 2026 table on or after Thursday, August 20, 2026, use this procedure instead:

1. Check the `route-views2` August 2026 `RIBS/` listing or a Route Views/BGPKit status page for the newest available `rib.YYYYMMDD.HHMM.bz2`.
2. Download that exact file into `mrt/`.
3. Run the `bgpdump2 -c` validation command above to confirm how many full-feed peers it contains.
4. Copy [`benchmarks/2026-core-mrt.yaml`](../benchmarks/2026-core-mrt.yaml) and [`benchmarks/2026-filters.yaml`](../benchmarks/2026-filters.yaml) to local variants and update `mrt_file:` consistently.

The important point is to pin the exact RIB filename used for any published comparison, not to mix “latest at the time” with a drifting implicit filename.

## Suggested Execution Order

Use this order to keep risk and runtime under control.

1. `doctor`, `images`, `verify`
2. validate the MRT input with [`scripts/prepare_mrt.sh`](../scripts/prepare_mrt.sh)
3. preflight the selected suites with [`scripts/preflight_2026_suite.sh`](../scripts/preflight_2026_suite.sh) or let the runner do it
4. smoke-test every target family
5. run [`benchmarks/2026-core-synth.yaml`](../benchmarks/2026-core-synth.yaml)
6. run [`benchmarks/2026-core-mrt.yaml`](../benchmarks/2026-core-mrt.yaml)
7. run any local extension config derived from the core matrix
8. run [`benchmarks/2026-filters.yaml`](../benchmarks/2026-filters.yaml)
9. larger-memory runs only after the 64 GB baseline is clean

## Bottom Line

The best next step is a disciplined, version-aware 64 GB sweep, not an immediate return to the largest possible stress tests.

The minimum high-value set is:

- synthetic `10 peers x 50k`
- synthetic `10 peers x 100k`
- synthetic `50 peers x 50k`
- synthetic `50 peers x 100k`
- MRT `10 peers x current full table`

Run that across all open-source explicit versions plus each daemon’s unversioned default image, treat BIRD 3 threading explicitly, validate the pinned MRT file before use, and keep larger-memory work for the capacity-cliff phase rather than the baseline comparison phase.
