# bgperf2 Architecture and Benchmark Roadmap

## Purpose

This document proposes a medium- and long-term direction for `bgperf2`. It is
written from an implementor's perspective: the goal is to improve the
trustworthiness and extensibility of the benchmark without committing to a
large rewrite before the current harness has been characterized.

The central recommendation is:

> First establish what the existing benchmark measures and how repeatable it
> is. Then introduce explicit experiment and result contracts, and extract the
> execution machinery behind those contracts. Add broader BGP workloads only
> after the harness can distinguish generator, target, and observer limits.

This is a roadmap, not a promise that every item should be implemented. Each
phase has an exit criterion intended to prevent architecture work from running
ahead of demonstrated needs.

## Current Evidence and Its Limits

As of August 2026:

- The unit suite has 280 passing tests. It covers substantial pure logic around
  versions, batch expansion and resume, parsing, provenance, contention,
  statistics, and convergence detection. However, a fresh test collection in
  a sandbox without Docker-socket access attempted to negotiate with the
  daemon from `settings.py`. The suite passed when socket access was allowed.
  The intended Docker-free import/test property is therefore not reliably met
  and should be repaired rather than assumed.
- The `2026-baseline` campaign has completed smoke, core synthetic, and core
  MRT suites: 10 smoke rows, 56 synthetic rows, and 14 MRT rows.
- One core MRT row, BIRD 3.3.2 with default threads, is recorded as failed
  after a sustained received-route-count drop.
- In many completed rows, `testers (s)` is close to `elapsed (s)`. This is
  evidence that injection may be a material part of the measured time. It is
  not, by itself, proof that every such run is invalid: the two clocks have
  related endpoints and their exact meanings need to be verified.
- Some runs recorded material foreign CPU use. Those rows should not be used
  as clean comparisons without review.
- The campaign is primarily a single run per matrix cell. It establishes that
  the workflow operates and exposes large differences, but it does not yet
  quantify variance or support fine-grained rankings.

The existing data is therefore sufficient to prioritize harness validation and
software cleanup. It is not sufficient to choose an elaborate replacement
architecture or claim small performance differences between daemons.

## Principles

### Correctness precedes throughput

A run is useful only when the expected BGP state is reached. Performance
results must be accompanied by correctness checks, including session state,
expected route state, withdrawals, and daemon health.

### Separate results from validity judgments

Observed measurements are facts about a run. Whether a run is suitable for a
particular comparison is a policy decision. Store both, rather than discarding
measurements or encoding validity only in a free-form flag.

### Preserve raw evidence

Derived values such as maximum CPU and convergence time should be
recomputable. Keep the experiment definition, rendered configuration, image
identity, lifecycle events, samples, logs, and verdict inputs together.

### Prefer incremental seams over a rewrite

The current problems are dominated by coupling and implicit data contracts,
not demonstrated Python runtime limitations. New interfaces should first be
introduced around existing behavior. Components should be replaced only when
profiling or new requirements justify it.

### Keep ordinary tests independent of Docker

Importing `bgperf2` and running unit tests must continue to require neither a
Docker daemon nor elevated privileges. Docker integration tests should be a
separate, explicitly selected layer.

### Make benchmarks reproducible, not merely repeatable

Repeating the same command is insufficient if images, host load, input data, or
completion rules changed. Every result must identify those inputs precisely.

## Immediate Work: Establish a Trustworthy Baseline

This work should precede a large workload expansion. It can proceed alongside
small, low-risk refactors.

### 1. Write down the measurement contract

For each existing output field, document:

- the event that starts its clock;
- the event that stops its clock;
- the sampling interval and clock source;
- which process reports the event;
- whether the value includes setup, assurance, or teardown time;
- behavior when a session resets or the route count falls;
- whether the metric is comparable between synthetic and MRT workloads.

In particular, verify the definitions and relationship of `monitor (s)`,
`elapsed (s)`, `prefix received (s)`, `testers (s)`, and `total time` before
using their proximity as an automatic injection-bound verdict.

Exit criterion: every published column has an unambiguous definition and a
unit test for its calculation where the calculation is non-trivial.

### 2. Characterize variance and order effects

Select a small calibration set rather than repeating the whole matrix:

- one fast and one slow target;
- one synthetic and one MRT workload;
- at least one small and one moderately large cell;
- five runs per cell initially, increasing only if the observed variance makes
  that necessary;
- interleaved or randomized target order;
- explicit recording of cold versus warm runs.

Report medians and dispersion. Do not select a universal repetition count in
advance: derive it from the effect size that the project intends to detect.

Exit criterion: the project can state the approximate run-to-run variation for
the canonical workloads and define what constitutes a meaningful regression.

### 3. Calibrate the traffic and observation path

The earlier proposal suggested a generator-to-monitor or pass-through control.
That is useful only if its topology and work are close enough to the real path.
Implement calibration in stages:

1. Measure the tester's standalone generation/playback rate.
2. Measure tester-to-monitor ingestion with clearly documented differences
   from a real target run.
3. Compare available tester implementations on the same workload.
4. If possible, add rate limiting so input rate becomes a controlled variable.
5. Measure monitor saturation independently, including polling overhead.

A pass-through result is a lower bound on harness time, not a number that can
simply be subtracted from target convergence time.

Exit criterion: for each canonical workload, the result can identify whether
the tester, target, monitor, or an unresolved combination is the limiting
component.

### 4. Tighten run qualification

Define machine-readable findings, initially including:

- tester error or timeout;
- target or observer crash;
- session loss;
- unexpected final route state;
- received-route regression;
- foreign CPU contention;
- low free memory or swapping;
- possible injection or observer limitation;
- missing or unverified provenance.

Avoid a single permanent `valid` boolean. Suitability depends on the question:
a contended run is unsuitable for CPU comparison but may still reproduce a
correctness failure. Store findings and derive verdicts such as `accepted`,
`accepted_with_warnings`, `failed`, or `inconclusive` under a named policy.

Exit criterion: campaign review can be performed from structured fields while
retaining the evidence behind every decision.

### 5. Resolve known anomalies before broadening the matrix

Investigate, without assuming the target is at fault:

- the failed BIRD 3.3.2 default-thread MRT row;
- high-foreign-CPU OpenBGPD rows;
- why GoBGP entries are currently removed from the working copies of the 2026
  suite definitions;
- import-time Docker client initialization, which can make test collection
  depend on access to a running daemon;
- whether tester and monitor versions are sufficiently pinned and verified;
- any cell where completion is dominated by a known harness ceiling.

Exit criterion: each anomaly is either fixed, reproducibly classified, or
explicitly excluded with a recorded reason.

## Near-Term Architecture: Create Testable Seams

The main risk is attempting to design a general framework in one change. The
safer approach is to extract one boundary at a time while preserving existing
CLI behavior and benchmark output.

### 1. Introduce typed internal records

Replace new uses of loosely shaped dictionaries, `argparse.Namespace`, queue
messages with optional keys, and positional result lists at internal
boundaries. Python dataclasses are sufficient; adding a large validation
framework is optional.

Initial records should cover:

- `ExperimentSpec`: normalized user intent;
- `ExperimentPlan`: resolved images, topology, and ordered phases;
- `Observation`: timestamped route, session, resource, or lifecycle event;
- `RunFinding`: structured warning or failure evidence;
- `RunResult`: measurements, findings, provenance, and artifact references.

Do not require every daemon adapter to migrate at once. Add compatibility
conversion at the current boundaries and migrate incrementally.

### 2. Make results named and versioned

Introduce a canonical, versioned JSON result document. Continue producing the
existing CSV while users and graph tooling migrate. CSV should become a
derived view rather than the source of truth.

The result document should contain:

- schema and tool versions;
- normalized experiment specification;
- daemon versions, image tags, and immutable image IDs or digests;
- host, kernel, Docker, CPU, memory, and resource-control information;
- lifecycle and BGP event timestamps;
- final metrics with units;
- findings and the verdict policy used;
- references to raw samples, logs, and rendered configuration.

Large time series need not be embedded in the JSON. A separate CSV or JSON
Lines artifact is adequate initially. Parquet should be considered only if
volume or analysis needs justify another dependency.

Exit criterion: graphing and campaign review use field names rather than
hard-coded result-list indexes, and an old result remains readable after schema
changes through an explicit compatibility path.

### 3. Extract the run lifecycle

Refactor `bench()` around explicit stages:

```text
validate -> prepare -> start -> establish -> stimulate -> observe
         -> quiesce -> collect -> clean up
```

Each stage should record start, end, status, and diagnostics. Cleanup should be
attempted through `try`/`finally`, while preserving enough state to investigate
a failure. Avoid changing all orchestration behavior during the extraction.

The lifecycle runner should depend on a narrow runtime interface. A fake
runtime can then drive lifecycle and failure-path tests without Docker.

Exit criterion: normal completion, timeout, observer failure, tester failure,
target failure, and cleanup failure are covered by Docker-free tests and
produce complete `RunResult` objects.

### 4. Separate observation from completion policy

Observers report facts: route counts, peer states, resource samples, and
process exits. Completion policies decide whether those facts mean converged,
failed, or still running.

Preserve `ConvergenceTracker` as tested policy logic, but feed it explicit
observations. Different workloads will require different policies; initial
table convergence, sustained churn, and graceful restart cannot share one
received-count-stability rule.

Exit criterion: a recorded or synthetic observation stream can be replayed
through a completion policy deterministically.

### 5. Add a layered test strategy

Maintain distinct test layers:

1. Pure unit tests, always run and Docker-free.
2. Schema, configuration, and adapter contract tests using fixtures.
3. Full lifecycle tests using a fake runtime.
4. Tiny per-adapter Docker checks, explicitly selected.
5. Hardware qualification and performance campaigns, never treated as
   deterministic CI tests.

Golden configuration tests should be used selectively. They are valuable for
daemon syntax but can become noisy if they snapshot incidental formatting.

## Experiment Language

### Do not build a new programming language yet

The repository already has two declarative inputs:

- scenario YAML for topology and routes, with Mako as an escape hatch;
- batch YAML for matrix expansion.

The next step should be a versioned experiment schema compiled into
`ExperimentPlan`, not a parser, interpreter, or general-purpose DSL. YAML is a
reasonable syntax as long as it is validated before any containers are
changed.

The schema should express five concepts:

1. Topology and implementations.
2. Initial route and policy state.
3. Ordered actions or phases.
4. Measurements and completion conditions.
5. Correctness assertions and run-qualification requirements.

For example:

```yaml
schema: bgperf2/v1alpha1
name: withdraw-and-restore

topology:
  target:
    implementation: frr_c
    version: "10.7"
  peers:
    count: 50
    generator: bird

phases:
  - name: establish
    wait:
      sessions: all
      timeout: 2m

  - name: initial-table
    advertise:
      synthetic:
        prefixes_per_peer: 100000
        rate: unlimited
    wait:
      condition: stable-routes
      duration: 20s
      timeout: 10m

  - name: withdraw
    withdraw:
      fraction: 0.10
      selection: deterministic

  - name: restore
    advertise:
      withdrawn_routes: true

measure:
  - convergence_time
  - target_cpu
  - target_memory
  - final_route_count

assert:
  - sessions_established: 50
  - final_rib: expected

qualify:
  max_foreign_cpu_percent: 10
  swapping: forbidden
```

This example is directional, not a schema specification. Terms such as
`stable-routes`, `unlimited`, and `expected` must not be implemented until
their semantics are precise. Assertions should preferably be structured
objects, not an expression language.

### Migration constraints

- Continue accepting existing scenario and batch files during migration.
- Keep Mako compatibility initially, but treat rendered Mako scenarios as
  opaque legacy input if they cannot be statically validated.
- Do not combine matrix expansion, workload behavior, and daemon-native config
  in a single schema layer.
- Add reuse through named workload profiles or YAML references only after
  repetition is observed. Avoid loops, embedded Python, and user-defined
  functions in the first version.
- Version the schema from its first checked-in example, even while it is alpha.

Exit criterion: at least initial-table and one dynamic workload can be
expressed without target-specific conditionals in the experiment document.

## Workload Expansion

Do not implement every BGP feature as an independent benchmark. Select
workloads that answer a performance question, have a correctness oracle, and
can be driven consistently across at least two target implementations.

### First dynamic workloads

Implement these in order:

1. Bulk withdrawal and restore of a deterministic route subset.
2. Rate-controlled sustained announce/withdraw churn.
3. Simultaneous session establishment and teardown.
4. A single peer flap and a bounded multi-peer flap storm.

These exercise the new phase/action model without immediately requiring every
optional BGP capability.

Each workload needs:

- a defined start event and completion condition;
- expected intermediate and final route/session state;
- input-rate accounting;
- target, tester, and observer capability declarations;
- behavior for unsupported capabilities;
- a small correctness test before performance-scale execution.

### Later workload families

Add only when the engine and adapters can support them coherently:

- best-path changes and path exploration;
- many paths per prefix and ECMP/multipath;
- AS-path, community, large-community, MED, and local-preference changes;
- prefix-list, AS-path, and community-policy scale;
- route refresh and policy re-evaluation;
- graceful restart and stale-route handling;
- Add-Path;
- route-reflector topologies;
- RPKI origin-validation mixes;
- slow-peer and backpressure behavior.

Features such as route flap damping are implementation-dependent or no longer
universally recommended. They should not become canonical cross-daemon tests
without a clear comparability contract.

IPv6 workloads are not a small schema addition. They require coordinated work
in address and prefix generation, peering, monitoring, MRT playback, daemon
adapters, and expected-route accounting.

## Medium-Term Delivery Arc

The dates below are deliberately omitted. Benchmark development competes for
scarce machine time, and calendar estimates would imply more certainty than the
current evidence supports.

### Milestone A: defensible existing benchmark

- Measurement dictionary completed.
- Calibration and variance study completed.
- Known 2026 anomalies classified.
- Qualification findings stored consistently.
- Canonical workloads and minimum detectable regression documented.

Deliverable: a baseline report that states both results and limitations.

### Milestone B: durable data and lifecycle

- Typed experiment, observation, finding, and result records.
- Versioned canonical result JSON plus raw samples.
- Existing CSV generated from named fields.
- Explicit lifecycle with reliable failure artifacts and cleanup.
- Fake-runtime lifecycle tests.

Deliverable: existing initial-table benchmarks run through the new internal
contracts without a CLI compatibility break.

### Milestone C: composable experiments

- Validated alpha experiment schema.
- Capability discovery or validation for targets, testers, and observers.
- Phase/action execution model.
- Bulk withdrawal/restore workload.
- Rate-controlled churn workload.

Deliverable: two dynamic workloads expressed without adding special-case loops
to `bench()`.

### Milestone D: statistically useful regression testing

- Repetition and order-randomization support.
- Summaries with uncertainty rather than single-value rankings.
- Hardware qualification profile.
- Explicit performance-regression policy.
- Comparison tooling across versions and result schema revisions.

Deliverable: a repeatable release or commit comparison with an auditable
accept/reject decision.

## Longer-Term Direction

Once Milestones A through D demonstrate demand, consider:

- multi-target, route-reflector, and hierarchical topologies;
- generators distributed across multiple hosts;
- CPU affinity, NUMA placement, and explicit resource-isolation profiles;
- BMP or daemon-native structured event collection;
- plugin interfaces for target adapters, traffic drivers, observers, and
  completion policies;
- automated version or commit bisection;
- curated, redistributable input corpora and self-contained result bundles;
- separate scorecards for correctness, latency, throughput, resource use, and
  scale limits.

Distributed execution should not be attempted merely to reach higher load. It
introduces clock synchronization, network-path, coordination, and artifact
collection problems. Require a demonstrated single-host generator ceiling and
a workload that needs to exceed it first.

## Language and Component Strategy

Do not rewrite the orchestrator in another language at this stage.

Python is appropriate for experiment validation, Docker orchestration, daemon
adapters, lifecycle control, and analysis. A rewrite would consume the tests
and compatibility effort needed to validate the benchmark while leaving its
measurement ambiguities unresolved.

Use another language for a bounded component only when all of the following
are true:

1. Profiling identifies that component as a relevant limit.
2. Its input, output, timing, and failure protocol can be specified.
3. A replacement can be compared against the existing implementation.
4. Operational complexity is justified by a required workload.

Likely candidates are a high-rate, rate-controlled BGP traffic generator or a
high-volume event collector. Go and Rust are both plausible; language choice
should follow ecosystem support and measured requirements rather than becoming
an architectural objective.

If distributed agents are eventually needed, communicate through a small,
versioned protocol and keep the Python process as the experiment coordinator.

## Explicit Non-Goals for the Next Milestones

- Rewriting all existing daemon adapters.
- Replacing Docker before it is shown to prevent a required measurement.
- Building a general-purpose programming language.
- Supporting every optional BGP capability uniformly.
- Treating performance campaigns as deterministic CI.
- Producing a single composite score that hides correctness or workload
  differences.
- Publishing rankings based on a single run per cell or differences smaller
  than established variance.

## Recommended Next Three Changes

1. Add a measurement dictionary and a small calibration suite with repeated,
   interleaved runs. This tests the assumptions behind the roadmap.
2. Introduce named `RunResult` and `RunFinding` records and emit a versioned
   JSON artifact alongside the unchanged CSV. This removes the most fragile
   positional contract without changing orchestration.
3. Extract completion and failure handling behind an observation stream and
   add a fake lifecycle runner. Use that seam to implement bulk
   withdrawal/restore as the first dynamic workload.

After each change, rerun the Docker-free unit suite. Run only the smallest
relevant Docker verification or benchmark, and record explicitly whether it
was run. Review the diff before committing, as required by the repository's
quality gate.
