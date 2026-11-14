# Native bench/batch throughput support

Status: proposed implementation plan; no engine behavior changed by this document.
The selected work is an audit and plan first. This document authorizes no builds,
image acquisition, benchmark execution, scheduling, publication or deployment.

## Problem and existing baseline

`bench` already executes a measurement and `batch` already executes large YAML
matrices, including repetitions, deterministic ordering, immutable images and
fixed-input MRT bindings. Preserve those interfaces and the existing lifecycle.
Portable recipes remain useful for reproduction, correctness and investigation;
routine large performance sweeps should not require a recipe packaging chain
for every cell.

A caller can already use one native batch per finite stage and automate the
transitions between stages externally. **The first one-command native suite
coordinator does not require an engine rewrite or these proposed optimizations.**
Host qualification, quiet/resource policy, finite campaign authorization,
scientific headroom selection and cross-stage orchestration belong to consumers.
The engine should supply clear native execution, phase and offline artifacts.

## Proposed work, after the initial coordinator

### A. Make matrix inspection genuinely offline

Route native `batch --list-cells` and structural validation through the existing
pure `batch_cells.py` layer before Docker or Matplotlib initialization. Planning
must preserve canonical cell keys, target versions, workloads, order and seeds.
It must never probe Docker, build/download images, render plots or create result
identities. Syntax/structure validation is distinct from runtime image/input/host
availability checks. Runtime preflight still verifies all selected role images
and workload bindings before the first cell.

Do not introduce a private-project entry point or require a lab installation.
Decide the smallest CLI change from current parser/import boundaries before
implementation. Preserve existing command output contracts and ordinary runtime
initialization for commands that need it.

### B. Record operational phase timing without redefining measurements

Add an attempt-bound phase journal for admission, setup, replay release,
measurement completion, post-check/capture, rendering, owned cleanup and terminal
state. Reuse existing event timestamps wherever they already establish a boundary;
record new operational boundaries outside the measured clock when possible.
Retain monotonic durations plus UTC for correlation. Missing/interrupted phases
remain explicit. Multi-process records must not imply a shared monotonic origin
without a recorded host/clock binding.

Keep the published CSV, convergence tracker, sample/assurance rules, input checks,
offering checks and exact-set qualification unchanged. Operational wall phases
are additional metadata, never substitute timings. This enables evidence-based
optimization rather than attributing all post-measurement time to plotting.

### C. Defer graph rendering explicitly

Add an opt-in way to collect complete original data and defer all per-cell and
aggregate graphs until after the selected measurement stage/suite. Default
behavior stays compatible. The current `batch --cells --no-report` suppresses
aggregate reporting only; `finish_bench()` still renders per-bench graphs.

Before omitting graphs, persist every timeseries/plot input currently available
only in memory, plus event/version/stats artifacts and column definitions. Supply
a documented offline reconstruction path. A report/render failure must be
separate from an already completed measured original. Rendering never overlaps
a successor's active measurement. CSVs, stats, expected sets, images, seeds and
original identities must be identical with the option enabled.

Measure the actual rendering share before advertising a speedup. Independent
checks and cleanup remain required; a deferred-plot flag must not become a
shortcut around them.

### D. Generalize native cell control to synthetic performance workloads

The present `--control-dir` handshake is specific to fixed-input MRT cells.
Reuse its bounded admission, pre-replay release, cancellation and owned-terminal
semantics for other supported local bench/batch workloads. Keep one lifecycle;
do not add a second synthetic measurement implementation. External supervisors
continue to own quiet/resource policy and campaign budgets.

Keep commands without opt-in control compatible, and reject unsupported modes
before side effects. No implicit retries, service, scheduler, host qualification
or safe-capacity claim follows from receiving a release token. Public artifacts
must distinguish completed measurement, failed qualification and uncertain cleanup.

## Validation and acceptance

- Offline planning works with no Docker socket and an unwritable Matplotlib
  config directory, creates no files and preserves established matrix keys/order.
- Modeled phase journals account for success, failure, cancellation, missing
  receipts and cleanup uncertainty without changing legacy statistic rows or
  measurement boundaries.
- Deferred rendering reconstructs required figures from saved data; original
  values/provenance are unchanged. Render failure cannot silently remeasure a
  completed original or mark it scientifically accepted.
- Generic control supports serial local synthetic and MRT batches; malformed,
  stale, foreign, duplicate and late releases refuse; cancellation and cleanup
  precede any successor.
- Run focused tests and required quality/review gates for each reviewed change
  set. Real runtime qualification is a separately selected small finite case;
  do not rerun an entire completed campaign just to exercise a new coordinator.

## Deliberate limits

Do not weaken input hashing, exact prefix identity, offering witnesses, pressure,
cleanup, immutable source/image bindings or serial measurement to reduce wall
time. Do not cache live image/input identity based only on path, mtime or tag.
Safe reuse of immutable parsed specs or verification receipts needs an explicit
content/implementation/coverage binding and its own mutation/refusal tests.

Calibration reduction, trial counts, scientific exclusions, export expectations
and optional continuation after isolated daemon identity failures are experiment
or orchestration decisions; they are not engine throughput defaults. No statistic
is recalibrated and no prior original is reclassified by this plan.
