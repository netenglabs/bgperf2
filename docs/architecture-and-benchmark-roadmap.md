# Engine architecture roadmap

Historical engine design proposal from 07c6ff1b4001976865057f7ed92ca4b4ccc334a1.
Retained sections follow the accepted section ownership map. Proposed interfaces
are design direction, not a statement that they are implemented.
Cross-repository coordination lives in the optional private
[lab architecture](https://github.com/jopietsch/second-looks-lab/blob/main/docs/architecture/system-boundaries.md);
research priorities live in
[research](https://github.com/jopietsch/second-looks-labs-research/blob/main/bgp/2026/docs/architecture-and-benchmark-research.md).

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
