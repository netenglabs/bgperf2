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

## CPU Attribution Boundary

The legacy resource fields do not identify which benchmark role exhausted
CPU. `max cpu %` is the maximum sampled CPU use of the target container, while
`min idle%` is the minimum sampled idle percentage for the whole host. Tester,
monitor, controller, and kernel CPU are not reported separately, and the two
published extrema are not time-aligned evidence that can be subtracted.

Reliable component attribution requires time-aligned CPU measurements for the
target, tester, and monitor, together with host-wide CPU and explicit treatment
of controller and kernel overhead. Until that instrumentation exists, a run
with near-zero host idle may receive a `host CPU saturated` finding, but its
limiting component must remain `unresolved`. In particular, target-container
CPU near one logical core is consistent with single-core pressure, but a
maximum alone does not show whether that pressure was sustained or prove that
the tester caused the remaining host load.

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

Status: complete on 2026-08-20. The legacy CSV dictionary, public/operator
documentation, implementation comment, and regression contract now agree.

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

Status: complete on 2026-08-20. Monitor queue observations now carry monotonic
timestamps, the controller boundary converts them to typed events and named
durations, and an ordered event artifact is written atomically for converged
and tracked-failure runs.

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

Status: in progress. The Docker-free half landed on 2026-09-02 — `bird.py` now
parses `birdc show protocols all` by column name, `tester_offering()` summarises
what a generator says it put on the wire, and `measurements.TesterEventRecorder`
turns polled sessions into `tester_session_ready`/`tester_first_update`/
`tester_last_update`/`tester_complete` with `tester_metrics()` deriving
`tester_startup_s`, `injection_s`, `offered_prefixes` and `offered_rate_pps`.
Both parser and recorder are covered against real 2.19 and 3.3.2 captures.

Remaining: poll the tester containers during `bench()`, merge the tester events
into the run artifact, and run the one-tester/one-target Docker verification the
exit criterion asks for. `post_injection_tail_s` is deliberately still absent —
it spans tester and monitor events and needs a signed interval helper, since the
contract allows it to be negative when injection and convergence overlap.

Two findings worth carrying forward:

- BIRD 3 inserts `RX limit` and `limit` columns into the route-change-stats
  table, so the column that is `accepted` on 2.19 is `RX limit` on 3.3.2. Read
  these tables by name; a positional read returns a plausible wrong number.
- Blocked-write evidence is version-dependent. BIRD 3 reports `TX pending: N
  bytes` and `Pending N attribute sets with total M prefixes to send`; 2.19 has
  neither. The synthetic tester runs the unversioned `bgperf/bird` image, which
  is 2.19, so backpressure is recorded as unavailable-with-a-reason rather than
  as zero.

#### Defect found while instrumenting: BIRD 3 targets report accepted = 0

Not fixed here, because it changes target-side convergence input rather than
tester instrumentation and needs its own verification against both series.

`bird.tfsm` reads the `Import updates` row positionally
(`${received}\s+\S+\s+\S+\s+\S+\s+${accepted}`), which is the same
column-shift described above. Run against the recorded 3.3.2 capture it yields
`accepted` of 0 for all three neighbours where the true values are 0, 100 and
100. So for any BIRD 3 target `neighbors_accepted` is always 0,
`neighbors_checked` never goes all-True, and the `neighbors_checked` route to
`note_neighbors_checkpoint()` in `bench()` is dead code. Runs still converge
through `neighbors_received_full` (the `received` capture reads column 1 and is
correct), so this is quiet rather than fatal, but the per-second progress line
prints a wrong accepted count and one of the two convergence checkpoints does
not fire on half the BIRD matrix.

`bird.parse_protocols()` is the fix — `BIRDTarget.get_neighbors_state()` should
read it instead of the TextFSM template. This blocks meaningful BIRD 2 vs 3
comparison and should land before Phase 5A.

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
- Apply the CPU attribution boundary above: host saturation without time-aligned
  per-role CPU evidence leaves the limiting component unresolved.
- Keep the raw durations and the named qualification policy beside every
  verdict.

#### Tests

- Deliberately rate-limited tester is classified as tester-limited.
- Deliberately delayed target/monitor tail is not classified as tester-limited.
- Near-zero host idle without per-role CPU evidence is classified as host CPU
  saturation with the limiting component unresolved.
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

### Phase 5A: Add BIRD architecture workload controls

#### Work

- Add a peer-scaling workload that can increase session count while keeping
  total route count modest.
- Add a path-diversity mode in which multiple peers announce competing paths
  for the same prefixes instead of always generating disjoint prefixes.
- Add configurable export fan-out so one target table can feed multiple
  receiver sessions without treating the extra receivers as route sources.
- Add bounded withdrawal/reannouncement bursts with explicit operation counts
  and completion events.
- Add a loaded-table policy reload/recalculation action and record its start,
  completion, resulting route counts, and CPU interval.
- Preserve independent ingress, table-selection, export, and monitor timing so
  parallel work is not collapsed into one end-to-end number.

These controls target BIRD 3's documented worker-thread responsibilities:
BGP protocols, routing-table maintenance, and decoupled exports. They are
generic benchmark primitives, not BIRD-specific shortcuts.

#### Tests

- Prefix overlap and competing-path accounting.
- Multiple receiver counts without multiplying ingress counts.
- Deterministic churn operation generation and completion.
- Policy reload completion, failure, and final-state validation.
- Small Docker checks for each topology before a combined calibration.

#### Exit criterion

A bounded fake/runtime suite can distinguish high peer count, competing-path
selection, export fan-out, policy recalculation, and churn while preserving
correct final route counts and timing events.

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
- the BIRD architecture workload controls pass their topology and accounting
  tests;
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
7. Add peer-scaling, path-diversity, export-fan-out, policy-reload, and churn
   workload controls.
8. Run controlled and real calibration checks.
9. Open the release gate for the 64 GB timing validation campaign.

## Bottom Line

The next implementation work is not a rewrite and not a larger benchmark. It
is a sequence of small, tested changes that makes tester completion observable,
keeps old results readable, and creates a release gate for the new campaign.
Use the same continuation prompt after every reviewed change set.
