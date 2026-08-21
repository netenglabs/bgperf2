# bgperf2 Measurement Integrity Implementation Plan

## Purpose

This is the implementation plan for repairing `bgperf2` timing semantics and
adding the minimum campaign machinery needed for statistically useful version
comparisons. It is the focused implementation companion to
[`architecture-and-benchmark-roadmap.md`](./architecture-and-benchmark-roadmap.md).

The immediate problem is concrete: the CSV column named `testers (s)` is
currently calculated as `elapsed (s) - prefix received (s)`. It measures the
interval from the first monitor-visible prefix until convergence, not how long
the tester took to send the workload. It therefore cannot identify a tester
bottleneck.

The implementation objective is:

> Record tester, target/monitor, and assurance intervals from explicit events,
> preserve the legacy CSV without silently changing its meaning, and qualify
> bottlenecks only from measurements that can distinguish them.

## Relationship to the Follow-Up Campaign

The follow-up campaign is specified in
[`2026-64gb-timing-validation-plan.md`](./2026-64gb-timing-validation-plan.md).
That campaign must not begin until the release gate in this document passes.

The completed `2026-baseline` results remain historical end-to-end evidence.
Do not rewrite their CSV rows or reinterpret their `testers (s)` values as
tester completion times.

## Current State

The completed `2026-baseline` campaign established the implementation starting
point:

- all four planned suites completed;
- five known-bad observations have successful targeted reruns;
- the baseline contains useful end-to-end elapsed, CPU, memory, correctness,
  and provenance evidence;
- BIRD synthetic testing uses one BIRD tester container;
- full-internet MRT testing uses ten bgpdump2 injectors;
- bgpdump2 tester provenance currently lacks a reported version;
- the legacy `testers (s)` column does not record tester completion;
- the main comparison cells have one observation each and do not establish
  run-to-run variance.

This plan should repair those concrete gaps without reopening the completed
baseline campaign or broadening workload scope.

## Fixed Constraints

- Preserve the Docker-free import and unit-test property.
- Preserve existing CLI commands and continue emitting the legacy CSV during
  migration.
- Do not require more than the local 64 GB host.
- Run real Docker benchmarks only where the phase explicitly requires them.
- Never run benchmark suites concurrently.
- Preserve raw events and observations; derived metrics must be recomputable.
- Use monotonic clocks for durations. Wall-clock timestamps may accompany
  events for correlation but must not drive elapsed calculations.
- Treat tester limitation, target limitation, and observer limitation as
  findings supported by evidence, not conclusions inferred from two similar
  durations.

## Operational Ground Rules

Before each implementation change set:

```bash
git status --short
venv/bin/python -m pytest tests/ -q
```

Use focused tests while developing. Run the full unit suite before accepting a
change that touches shared timing, batch, convergence, result, or lifecycle
code. Run Docker verification only in the phases that call for it, using the
smallest realistic workload and `/var/tmp/bgperf`.

The implementation workflow is intentionally incremental:

- one reviewable change set per continuation;
- resume unfinished work before starting new work;
- no benchmark concurrency;
- no phase is complete until its tests and exit criterion pass;
- no follow-up campaign block runs from this plan;
- review the complete working diff before committing.

## One-Prompt Implementation Workflow

Use the stable operator prompt:

> continue the bgperf2 measurement implementation plan

Each invocation inspects durable state and completes no more than one smallest
reviewable change set from the first incomplete phase. It stops after tests and
review, then tells the user to use the same prompt again. This is the
implementation equivalent of the one-suite-at-a-time workflow used for
`2026-baseline`.

## Intended Measurement Contract

Every run should eventually expose these events when applicable:

| Event | Producer | Meaning |
|---|---|---|
| `bench_clock_started` | controller | Common monotonic origin for measured run phases |
| `tester_session_ready` | tester/controller | Tester is able to send updates |
| `tester_first_update` | tester | First workload update offered |
| `tester_last_update` | tester | Last workload update offered or queued successfully |
| `tester_complete` | tester | Generator has completed its defined send/flush contract |
| `monitor_first_prefix` | monitor | First nonzero accepted count observed |
| `monitor_required_reached` | convergence tracker | Required route threshold first reached |
| `monitor_last_change` | convergence tracker | Last accepted-count change before assurance |
| `convergence_confirmed` | convergence tracker | Assurance policy declares completion |

The initial derived intervals are:

- `tester_startup_s`: benchmark origin to tester readiness;
- `injection_s`: first tester update to tester completion;
- `first_prefix_s`: benchmark origin to first monitor-visible prefix;
- `post_injection_tail_s`: tester completion to required monitor state, allowed
  to be negative only when explicitly representing overlap and documented;
- `convergence_s`: benchmark origin to required monitor state;
- `assurance_s`: required state to confirmed completion;
- `total_time_s`: existing whole-run wall-clock duration, kept separate from
  the monotonic phase metrics;
- offered updates/prefixes and average offered rate;
- blocked-write/backpressure evidence where the tester can expose it.

MRT and synthetic testers may initially provide different levels of detail.
Unsupported events must be recorded as unavailable, not synthesized from
monitor timestamps.

## Result Compatibility Decision

Do not silently redefine the existing `testers (s)` CSV column. During the
migration:

1. Keep the column and document its historical formula as
   `post-first-prefix (legacy)`.
2. Add new named fields to the canonical structured result.
3. If CSV must expose new fields, append them at the end so positional graph
   code and old consumers do not shift.
4. Update graphs and reports to use named structured fields when available.
5. Add an explicit schema/tool version so old results remain interpretable.

## Implementation Sequence

### Phase 0: Correct the published contract

#### Work

- Add a measurement dictionary covering every existing stats column.
- Correct `README.md`, `CLAUDE.md`, and operator-facing documentation so
  `testers (s)` is not described as generator duration.
- Update the 2026 report generator and review logic to stop assigning an
  injection-bound verdict from the legacy column.
- Add a regression test for the legacy formula so its actual historical
  meaning cannot drift again unnoticed.

#### Likely files

- `README.md`
- `CLAUDE.md`
- `AGENTS.md`
- `bgperf2.py`
- `tests/test_stats_contract.py`
- a measurement dictionary under `docs/`

#### Exit criterion

Documentation, code comments, tests, and report language agree on the meaning
of every existing timing column.

### Phase 1: Introduce typed lifecycle events

#### Work

- Add a small typed event record using the standard library, preferably a
  dataclass plus an enum or stable string constants.
- Give every event a monotonic timestamp, producer, phase, and optional
  counters/details.
- Convert existing monitor and convergence timestamps at the queue boundary
  without migrating every daemon adapter at once.
- Keep compatibility conversion near the current `bench()` boundary.
- Persist an ordered event artifact even when a run fails.

#### Likely files

- a new pure module such as `measurements.py` or `events.py`
- `bgperf2.py`
- `convergence.py`
- focused unit tests under `tests/`

#### Tests

- Event ordering and monotonic-duration calculations.
- Missing/duplicate event behavior.
- Failure before first prefix and failure during assurance.
- Import and unit tests without Docker access.

#### Exit criterion

Existing monitor/convergence metrics are derived from named events in unit
tests, and a failed fake run still produces an event artifact.

### Phase 2: Instrument the BIRD synthetic tester

#### Work

- Define when the BIRD tester is ready, when it offers its first update, and
  when the configured table has been completely offered.
- Record expected and observed update/prefix counts.
- Record a completion signal through a file, control socket, log marker, or
  another explicit mechanism with a testable contract.
- Record blocked-write/backpressure evidence if BIRD exposes a reliable signal;
  otherwise record that it is unavailable.
- Do not treat container start or BGP establishment alone as injection
  completion.

#### Tests

- Parser tests using captured completion evidence.
- Timeout/missing-marker behavior.
- A tiny Docker verification with one tester and one target.

#### Exit criterion

A small synthetic run reports an independently observed injection interval and
the expected offered route count.

### Phase 3: Instrument bgpdump2 MRT playback

#### Work

- Make every injector report first-update and completion evidence.
- Aggregate ten peer injectors without allowing the fastest injector to hide a
  slow or failed peer.
- Record per-injector and aggregate start, finish, count, and rate.
- Add a bgpdump2 version command, build identity, or immutable image digest so
  `UNKNOWN` is no longer the only tester provenance.
- Keep MRT scanning/setup time separate from update playback.

#### Tests

- Pure aggregation tests for staggered completion, missing peers, and timeout.
- Captured-log parser tests.
- One minimal pinned-MRT Docker verification.

#### Exit criterion

A ten-peer MRT run reports all ten injector completions, aggregate injection
duration/rate, and reproducible bgpdump2 identity.

### Phase 4: Derive bottleneck findings conservatively

#### Work

- Add structured findings rather than a permanent validity boolean.
- Define candidate findings for tester limitation, target/monitor tail,
  observer uncertainty, foreign CPU contention, low memory, tester failure,
  and missing timing evidence.
- Require explicit completion and rate evidence for tester-limited findings.
- Treat TCP backpressure as an end-to-end interaction unless it can be assigned
  reliably to a component.
- Keep the raw durations and the named qualification policy beside every
  verdict.

#### Tests

- Deliberately rate-limited tester is classified as tester-limited.
- Deliberately delayed target/monitor tail is not classified as tester-limited.
- Missing tester completion produces `inconclusive`, not a guessed result.

#### Exit criterion

The qualification policy distinguishes controlled tester limitation from a
controlled post-injection convergence tail.

### Phase 5: Add repetitions and order control

#### Work

- Add explicit repetitions to batch configuration or a validation runner.
- Assign stable repetition IDs and preserve resume behavior.
- Support deterministic randomized order from a recorded seed, or a documented
  rotating/block order if randomization would complicate resume excessively.
- Preserve every raw observation.
- Produce median, min/max, dispersion, and coefficient of variation without
  hiding individual runs.
- Expand from three to five runs only under a named variance rule.

#### Tests

- Batch expansion and stable naming.
- Resume after interruption within a repetition.
- Seed reproducibility.
- Aggregation with failures and missing repetitions.
- Custom YAML version strings such as `10.10` remain strings.

#### Exit criterion

A fake-runtime batch can run three repetitions in deterministic mixed order,
resume safely, and produce auditable summary statistics.

### Phase 6: Calibration and release gate

#### Work

- Add the smallest realistic synthetic and MRT calibration configs.
- Demonstrate a controlled slow tester and a controlled target/observer tail.
- Run one BIRD synthetic and one bgpdump2 MRT calibration on the local host.
- Review CPU contention, memory, correctness, provenance, and event ordering.
- Record the measurement schema version used by the follow-up campaign.

#### Release gate

The follow-up campaign may begin only when all are true:

- actual tester completion is independently recorded for BIRD and bgpdump2;
- derived timing fields have unit tests;
- controlled calibration cases produce the expected findings;
- a real synthetic and MRT smoke run passes;
- results identify all tester images/builds;
- repetition and order controls pass resume tests;
- the full unit suite remains Docker-free;
- documentation and report generators use the new contract.

## Explicit Non-Goals

- Rewriting the orchestrator.
- Distributed execution before a single-host ceiling is demonstrated.
- Adding every dynamic BGP workload before initial-table timing is trustworthy.
- Buying or assuming access to larger-memory hardware.
- Re-running the completed baseline under changed semantics.
- Publishing a composite score.

## Review and Commit Discipline

Each phase should be a reviewable change set. Before committing:

1. Run focused unit tests.
2. Run the full unit suite when shared lifecycle or result code changed.
3. Run a real benchmark only when the phase requires Docker verification.
4. Review the working and staged diff.
5. State explicitly whether a real benchmark was run.
6. Keep `AGENTS.md` and `CLAUDE.md` aligned when the operator contract changes.

## Continuation Prompt Contract

Use this exact prompt in a new session:

> continue the bgperf2 measurement implementation plan

The operator contract for that prompt is:

1. Read this plan and inspect the working tree, recent commits, tests, and any
   durable phase notes.
2. Resume unfinished work before selecting a new phase.
3. Implement exactly one smallest reviewable change set from the first
   incomplete phase.
4. Run the proportionate tests and required Docker verification.
5. Review the complete diff and fix findings.
6. Stop after that change set is complete and reviewed.
7. Tell the user to use the exact same prompt for the next change set.

## Suggested Execution Order

1. Correct the published measurement contract.
2. Introduce typed lifecycle events and event artifacts.
3. Instrument the BIRD synthetic tester.
4. Instrument ten-peer bgpdump2 completion and provenance.
5. Derive conservative bottleneck findings.
6. Add repetitions, stable IDs, order control, and summaries.
7. Run controlled and real calibration checks.
8. Open the release gate for the 64 GB timing validation campaign.

## Bottom Line

The next implementation work is not a rewrite and not a larger benchmark. It
is a sequence of small, tested changes that makes tester completion observable,
keeps old results readable, and creates a release gate for the new campaign.
Use the same continuation prompt after every reviewed change set.
