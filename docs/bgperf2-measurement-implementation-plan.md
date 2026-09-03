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

Status: complete on 2026-09-02. `bird.py` parses `birdc show protocols all` by
column name, `tester_offering()` summarises what a generator says it put on the
wire, and `measurements.TesterEventRecorder` turns polled sessions into
`tester_session_ready`/`tester_first_update`/`tester_last_update`/
`tester_complete` with `tester_metrics()` deriving `tester_startup_s`,
`injection_s`, `offered_prefixes`, `offered_in_interval` and
`offered_rate_pps`. `bench()` polls each generator that declares
`REPORTS_OFFERING` at the monitor's own 1s cadence, merges its events into the
one ordered `<prefix>.events.json` stream, and publishes the derived intervals
under a per-generator `testers` section beside `backpressure` and any
`observation_error`. Both parser and recorder are covered against real 2.19 and
3.3.2 captures.

`post_injection_tail_s` is deliberately still absent — it spans tester and
monitor events and needs a signed interval helper, since the contract allows it
to be negative when injection and convergence overlap.

Four things the wiring had to get right:

- **A BIRD tester runs one `bird` per peer, each on its own control socket.**
  `BIRDTester.get_startup_cmd()` launches `bird -c <guest_dir>/<router-id>.conf
  -s <guest_dir>/<router-id>.ctl` per neighbour, so a bare `birdc` inside a
  tester container reaches no daemon at all. `get_offerings()` names every
  socket and passes the results as one `TesterEventRecorder.observe()` call.
- **One `docker exec` per poll, not one per peer.** Every socket is read in a
  single `sh -c` loop whose sections are separated by `bird.SESSION_MARKER`,
  because an exec is ~50ms: at 50 peers a per-peer poll cannot keep up with a
  1s cadence and the controller becomes contention the run then reports as
  someone else's.
- **Every configured peer must appear in every poll**, with `offered=None` where
  the read failed. `observe()` rejects a poll whose session keys differ from the
  first one, because dropping a key would let `all(complete)` be satisfied by
  the peers that happen to remain.
- **`expected` comes from the scenario config**, `len(p['paths'])`, not from
  `tester_offering()['configured']`. The latter is the generator's own report of
  what it loaded and is a cross-check; using it as the yardstick would make a
  generator that loaded half its config look complete.

Three findings worth carrying forward:

- BIRD 3 inserts `RX limit` and `limit` columns into the route-change-stats
  table, so the column that is `accepted` on 2.19 is `RX limit` on 3.3.2. Read
  these tables by name; a positional read returns a plausible wrong number.
- Blocked-write evidence is version-dependent. BIRD 3 reports `TX pending: N
  bytes` and `Pending N attribute sets with total M prefixes to send`; 2.19 has
  neither. The synthetic tester runs the unversioned `bgperf/bird` image, which
  is 2.19, so backpressure is recorded as unavailable-with-a-reason rather than
  as zero.

- **BIRD 2.19's offered counter is queue-side, and saturates.** `Export
  updates accepted` counts a route when it is handed to the BGP protocol, not
  when it reaches the wire. In the 4-peer x 250k Docker verification the
  generator reported all 1,000,000 prefixes offered at 1.94s, while the monitor
  had seen 215,552 and the target itself held full tables from only 2 of the 4
  peers. So the *count* is exact and completion is positively observed, but the
  injection *duration* is not resolvable from this counter: repeated runs put
  between 0 and 153,744 of the million inside the measured interval purely
  according to where the first poll landed. Polling at 0.2s did not fix it, it
  made it worse — it reported a confident `21452 prefixes/s` that was the slope
  of the last 6,436 prefixes. `tester_metrics()` therefore publishes
  `offered_in_interval` beside `offered_rate_pps`, so a tail slope cannot be
  read as a send rate, and Phase 4 must not derive a tester-limited finding
  from a BIRD 2.19 rate. Wire-side evidence needs BIRD 3's `TX pending`, which
  means running the generator on `bgperf/bird:3.3.2`; the tester image is not
  selectable from the CLI today.

#### Docker verification

Run on 2026-09-02 on an 8-core / 30 GB host (not the 64 GB campaign host), with
`-d /var/tmp/bgperf` and results outside the campaign tree: `bench -t bird -n 1
-p 50000` and `bench -t bird -n 4 -p 250000`. Both reported the exact expected
offered count (50,000 and 1,000,000) from the generator's own CLI, an observed
`tester_complete` for every session, `tester_startup_s` of 1.1s and 1.9s, and
backpressure recorded as unavailable-with-a-reason on 2.19. No tester errors or
timeouts; foreign CPU 4-7%.

Review raised one contention question worth recording: the poll runs `sh -c`
inside the tester, and `sh` is deliberately absent from
`contention.BGPERF_PROCESSES` (interpreters are excluded because
`/proc/<pid>/comm` for a script-driven neighbour workload *is* the interpreter),
so a first-seen shell would be charged as foreign CPU. Measured rather than
argued: 46 polls in a 10s window — 5x the production rate — put zero `sh` or
`birdc` processes in either `/proc` sample and contributed 0.0% to
`foreign_cpu_percent`. The shell forks `birdc` and waits, so its own CPU is
nil and it is too short-lived to be sampled. Left as it is; allowlisting `sh`
would reopen the hole that made the whole feature report a clean machine while
a neighbouring `python3 train.py` used eight cores.

#### Defect found while instrumenting: BIRD 3 targets reported accepted = 0

Fixed on 2026-09-02, and `bird.tfsm` is deleted.

`bird.tfsm` read the `Import updates` row positionally
(`${received}\s+\S+\s+\S+\s+\S+\s+${accepted}`) — the same column shift
described above. So for any BIRD 3 target `neighbors_accepted` was always 0,
`neighbors_checked` never went all-True, and that route to
`note_neighbors_checkpoint()` in `bench()` was dead for half the BIRD matrix.
Runs still converged through `neighbors_received_full` (the `received` capture
read column 1 and was correct), which is why it stayed hidden: only the
per-second progress line looked wrong.

`BIRDTarget.get_neighbors_state()` now reads `bird.parse_protocols()`. Verified
on live output from both series, 3 peers x 200 prefixes:

| target | old template (accepted) | new parser (accepted) |
|---|---|---|
| bird 2.19 | 200, 200, 200 | 200, 200, 200 |
| bird 3.3.2 | 0, 0, 0 | 200, 200, 200 |

BIRD 2 is unchanged; BIRD 3 now reaches the neighbor checkpoint. This was a
prerequisite for meaningful BIRD 2 vs 3 comparison in Phase 5A.

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

Status: in progress. The injector's own evidence is readable, parsed, and
polled into the run's event stream; per-injector aggregation beyond that, and
provenance, are still open.

#### Progress on 2026-09-03: the injector log was empty, and now is not

`bgpdump2 --blaster` logs to stdout, which `start.sh` redirects into the
bind-mounted `bgpdump2.log`. Redirected stdout is block-buffered and nothing
ends the process but the container teardown, so **a converged two-injector run
left both logs at exactly 0 bytes** while the blaster was still running with its
walk finished. Every fact this phase needs was being written into a buffer no
one read. `start.sh` now runs the blaster under `stdbuf -oL -eL`; the same run
then produced complete logs for both injectors.

`bgpdump2.parse_blaster_log()` and `bgpdump2.tester_offering()` read that log,
covered against the two real captures in `tests/fixtures/bgpdump2_blaster*.log`
(2 injectors x 10,000 prefixes against a BIRD target). Earlier polls are modelled
by truncating those captures, including mid-line, since an incremental reader
meets exactly that.

Four things this settled:

- **Completion is the injector's own report, and it cannot be a count.** `-T`
  caps the table while the MRT file is read, so an injector holds whatever that
  MRT peer's table has; `offered >= expected` can stay false forever on an
  injector that has sent everything it holds. `measurements.TesterOffering`
  gained `send_complete` for a generator's own statement, and it decides
  completion in both directions — a generator that says it has not finished is
  not overruled by a count that reached `expected`. BIRD passes `None` and
  keeps the count-based rule. The signal is the `End-of-RIB` line rather than
  the `RIB walk complete` marker that precedes it: the marker is logged before
  the final `Sent ...` counters, so completing on it carries mid-walk counts,
  and in one capture it precedes the first `Sent` line entirely. That second
  case is refused twice over — `TesterEventRecorder` now holds
  `tester_complete` until an update has been observed, since a completion
  sorted ahead of `tester_first_update` makes `tester_metrics()` raise out of
  `finish_bench()` and kill a converged run.
- **Prefix counts are encode-side; the octet count is wire-side.** `prefixes
  sent` increments as prefixes are encoded into the 256KB session write buffer,
  `octets` only on a successful `write()`. A captured mid-walk line reads
  `Sent 2280 updates, 9981 prefixes sent, 0 prefixes withdrawn, 88 octets`. The
  BIRD 2.19 queue-side caveat applies to the prefix counts, with one wire-side
  number beside them.
- **`End-of-RIB, walk time` is the generator's own playback measurement**, and
  it resolves what the poll cadence cannot: one injector's entire 10,000-prefix
  walk took 1.03ms. It times one RIB, so it is published only for a single-RIB
  session; summing sequential walks would drop the gaps between them.
- The log's timestamps are local wall-clock with no year or zone, so they are
  parsed for nothing. Durations stay on the controller's monotonic clock.

Review of this change set also found a Phase 2 defect, fixed here:
`BIRDTester.get_offerings()` caught every exception from its `docker exec` and
read the failure as an empty capture, so `offering_stats()`'s
`tester_offering_error` path — and the artifact's `read_failures` evidence —
could never fire for the only generator that had one. A run whose polls all
failed produced the same artifact as a run whose generator never came up.

#### Progress on 2026-09-03: every injector now reports into the event stream

`Bgpdump2Tester` declares `REPORTS_OFFERING`, so the generic `bench()` poll
covers it: each injector gets its own `TesterEventRecorder`, and its
`tester_session_ready`/`tester_first_update`/`tester_last_update`/
`tester_complete` are merged into the one ordered `<prefix>.events.json` under
its container name, with the derived intervals beside them. No injector speaks
for another -- there is one producer per container and no aggregate, so a
missing completion stays visible as that injector's missing completion.

Three things this change set had to get right:

- **No `docker exec` at all.** The blaster's log is bind-mounted, so
  `BlasterLogReader` reads it from the host. Ten injectors polled once a second
  through `exec` would put the controller's own cost into the run it is
  measuring, which is what the BIRD poll's single-exec loop exists to avoid.
- **The read is incremental**, keeping a byte offset and stopping at the last
  complete line, for the reason `frr._get_EOR_from_log()` does: bgpdump2 logs a
  `Sent ...` line per `write()` to the socket, and a write carries whatever the
  socket would take -- one capture shows an 88-octet write -- so the line count
  is a property of how the peer drained the session and nothing bounds it in
  advance. `BlasterLog` accumulates facts across polls rather than reparsing,
  because `End-of-RIB` belongs to a `RIB for peer-index` line that arrived
  polls earlier and chunk-at-a-time parsing would drop the walk time it
  carries.
- **An unreadable log raises rather than reading as an empty one.** The log is
  the injector's only account of itself, so failing to read it is 'the
  generator could not be asked' -- `offering_stats()` records that as
  `read_failures` in the artifact, which is the distinction a silent empty
  reading would erase.

The poll names the single session `get_startup_cmd()` actually drives, from the
same `injected_neighbor()`, and `expected` is the configured `count`, never the
RIB size the log reports.

##### Docker verification

Run on 2026-09-03 on the 8-core / 30 GB host, `-d /var/tmp/bgperf` with results
outside the campaign tree: `bench -t bird -g bgpdump2 -n 2 -p 10000 --mrt-file
mrt/rib.20210801.0000`. Both injectors appear in `<prefix>.events.json` with all
four tester events, the exact expected 10,000 offered prefixes, `configured`
matching, `tester_startup_s` 1.33s, and backpressure recorded as
unavailable-with-a-reason. No read failures, no tester errors or timeouts,
foreign CPU 4%.

It also showed the measurement's own limit plainly: the walk takes about a
millisecond, so both injectors had finished before the first poll looked.
`injection_s` is 0.0 with `offered_in_interval` 0 and no rate, and the run
prints `injection shorter than one poll` -- the same unresolvable-injection
shape as BIRD 2.19, refusing to publish an instant injection. The generator's
own `End-of-RIB, walk time` (0.000995s) is the number that would resolve it,
and it is parsed but not yet carried into the artifact.

##### Defect to fix next: the published poll resolution is optimistic

Review of this change set found it in Phase 2 code. `Tester.offering_stats()`
stamps a sample before the read but then waits a full `interval` *after* it, so
the real cadence is `read + interval` while every event the recorder publishes
carries `sample_interval_s = 1` as its stated resolution. That field exists
precisely so an `injection_s` of 0.0 reads as *unresolved at this resolution*
rather than as instant, so understating it by the read time weakens the one
number that qualifies the others. It costs nothing for bgpdump2, whose poll is
a short file read, and grows with peer count for the BIRD tester, whose own
docstring says a 50-100 peer read "takes long enough to matter". Waiting to a
deadline instead of sleeping a fixed interval fixes the common case but not a
read slower than the interval, so the honest version records the cadence that
was actually achieved -- which is a change to shared timing code and belongs in
its own change set.

Left for the next change sets in this phase: carrying the injector's own
`walk_time_s` and wire-side `octets` into the artifact, since at MRT playback
speeds they are the only evidence a 1s poll cannot supply; an aggregate across
injectors that cannot let the fastest speak for the rest; blocked-write evidence
(`-t io` enables bgpdump2's `Partial write`/`Full write` lines, at the cost of a
log line per write); and bgpdump2 provenance, still `UNKNOWN (no version command
for Bgpdump2Tester)` although the binary answers `-V` with `Version: 2.0.14`.

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
