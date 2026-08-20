# 2026 Benchmarking Tooling Implementation Plan

## Purpose

This plan describes the code and repo changes needed before running a broad 2026 BGP daemon benchmark sweep.

The goal is to make benchmark execution:

- reproducible,
- easier to run correctly,
- easier to resume,
- and better aligned with the actual benchmark questions we want to answer.

This plan is deliberately implementation-oriented. It is not the benchmark result plan itself. For the test matrix and hardware split, see [`docs/2026-bgp-performance-test-plan.md`](./2026-bgp-performance-test-plan.md).

## Scope

This plan covers five workstreams:

1. baseline execution tooling
2. input validation and preflight checks
3. reproducibility metadata capture
4. long-run robustness and resume behavior
5. benchmark-model improvements

The first four are execution infrastructure. The fifth changes what the benchmark can measure.

## Non-Goals

This plan does not include:

- new daemon targets,
- IPv6 support,
- remote multi-host execution,
- or a full policy-framework redesign.

Those may be worthwhile later, but they are outside the minimum work needed to make the 2026 sweep reliable.

## Design Principles

### 1. Keep the benchmark interface simple

A user should be able to run the planned suites with one obvious command per suite, or one obvious command for the whole sweep.

### 2. Prefer checked-in config over remembered shell history

If a suite matters, its batch YAML should live in the repo.

### 3. Prefer pinned inputs over “latest” behavior

Benchmarks should record exact image versions, exact MRT file names, and exact config inputs.

### 4. Make partial progress durable

Long-running sweeps should survive interruptions without making the operator reconstruct state manually.

### 5. Separate execution plumbing from benchmark semantics

Resume logic and metadata capture should not distort the benchmark model itself.

## Workstream 1: Baseline Execution Tooling

### Objective

Make the planned suites runnable in a consistent way without relying on manual command assembly.

### Deliverables

#### 1.1 Checked-in suite configs

Keep and finalize checked-in batch configs for:

- smoke tests
- core synthetic suite
- core MRT suite
- reduced filter suite

Existing candidate files:

- [`benchmarks/2026-smoke.yaml`](../benchmarks/2026-smoke.yaml)
- [`benchmarks/2026-core-synth.yaml`](../benchmarks/2026-core-synth.yaml)
- [`benchmarks/2026-core-mrt.yaml`](../benchmarks/2026-core-mrt.yaml)
- [`benchmarks/2026-filters.yaml`](../benchmarks/2026-filters.yaml)

#### 1.2 Suite runner

Add a small runner script, likely:

- [`scripts/run_2026_suite.sh`](../scripts/run_2026_suite.sh)

Responsibilities:

- choose a results root
- choose or accept a stable run ID
- choose a work directory
- run suites in a fixed order
- stop on failure by default
- optionally run a single named suite
- optionally skip selected suites

Suggested interface:

```bash
scripts/run_2026_suite.sh all
scripts/run_2026_suite.sh smoke
scripts/run_2026_suite.sh core-synth
scripts/run_2026_suite.sh core-mrt
scripts/run_2026_suite.sh filters
```

Environment or flags should allow overriding:

- run ID
- results root
- work directory
- MRT file path

#### 1.2.1 Run identity model

Resume requires a stable run identity. The runner must not invent a fresh run directory on every invocation if resume is expected to work.

Required behavior:

- accept an explicit run ID, for example `--run-id 2026-08-20-baseline`
- if no run ID is provided, print the generated run ID clearly before any suite starts
- require the same run ID to resume an earlier run

Recommended interface:

```bash
scripts/run_2026_suite.sh all --run-id 2026-08-20-baseline
scripts/run_2026_suite.sh core-mrt --run-id 2026-08-20-baseline
```

The run ID must map directly to:

```text
results/2026/<run-id>/
```

#### 1.3 Results layout convention

Choose and document a stable layout such as:

```text
results/2026/<run-id>/
  metadata/
  smoke/
  core-synth/
  core-mrt/
  filters/
```

The runner should create that directory structure.

#### 1.3.1 Artifact routing model

The runner must define exactly how `bgperf2.py batch` outputs land inside the per-run tree.

Required behavior:

- invoke each suite with its own suite-specific results directory
- do not rely on running into a shared directory and moving files afterward

Recommended suite invocation model:

```bash
./bgperf2.py -d /var/tmp/bgperf batch -c benchmarks/2026-core-synth.yaml \
  --results-dir results/2026/<run-id>/core-synth
```

This should be the default contract for:

- smoke
- core-synth
- core-mrt
- filters

Metadata should live under:

```text
results/2026/<run-id>/metadata/
```

and suite completion markers should live under each suite directory.

### Files Likely Touched

- new: `scripts/run_2026_suite.sh`
- existing: `benchmarks/2026-*.yaml`
- existing docs: `docs/2026-bgp-performance-test-plan.md`

### Validation

- run smoke suite end-to-end with one command
- run a single suite end-to-end with one command
- verify output lands in the expected directory structure

## Workstream 2: Input Validation and Preflight Checks

### Objective

Catch predictable mistakes before a suite burns hours of time.

### Deliverables

#### 2.1 MRT helper

Add a helper script, likely:

- [`scripts/prepare_mrt.sh`](../scripts/prepare_mrt.sh)

Responsibilities:

- verify an MRT file exists
- optionally download a named Route Views RIB if given a URL
- run the `bgpdump2 -c` validation command
- summarize peer counts
- summarize the highest full-feed peer count
- print the exact filename being validated

This script should not silently choose “latest”.

It should accept either:

- a local MRT file path
- or an explicit URL

#### 2.2 Preflight command or script

Add a preflight helper, likely:

- [`scripts/preflight_2026_suite.sh`](../scripts/preflight_2026_suite.sh)

Responsibilities:

- check that referenced images exist
- check that the MRT file exists
- check whether the chosen work directory is tmpfs-backed
- check free disk space
- check rough free memory
- run `./bgperf2.py doctor`

This can initially be a script rather than a new `bgperf2.py` subcommand.

#### 2.3 Explicit suite/input agreement checks

The preflight should also verify that:

- every `mrt_file:` referenced by a selected suite exists
- every explicit `version:` or `versions:` entry resolves to a built image
- every target with no explicit `version:` key resolves to its unversioned default image
- every results directory is writable

### Files Likely Touched

- new: `scripts/prepare_mrt.sh`
- new: `scripts/preflight_2026_suite.sh`
- maybe existing docs: `README.md`
- maybe existing docs: `docs/2026-bgp-performance-test-plan.md`

### Validation

- fail clearly when MRT file is missing
- fail clearly when an image is missing
- warn clearly when the work directory is tmpfs-backed
- succeed cleanly when prerequisites are satisfied

## Workstream 3: Reproducibility Metadata Capture

### Objective

Capture enough information with each suite run to make results reproducible and auditable later.

### Deliverables

#### 3.1 Suite manifest

For each run, write a manifest file such as:

- `results/2026/<run-id>/metadata/manifest.json`

Include:

- timestamp
- hostname
- user
- cwd
- selected suite(s)
- work directory
- results directory
- exact MRT filename(s)
- benchmark config file paths

#### 3.2 Environment capture

Capture command outputs into metadata files:

- `git rev-parse HEAD`
- `git status --short`
- `./bgperf2.py doctor`
- `./bgperf2.py images`
- `uname -a`
- `free -h`
- `df -h` for the work/results filesystems

#### 3.3 Optional config snapshotting

Copy the exact suite config files used into the metadata directory so the run is self-contained even if the checked-in files change later.

This should be required, not optional. The runner should always copy the exact suite config files it used into the metadata tree.

### Files Likely Touched

- `scripts/run_2026_suite.sh`
- possibly a helper such as `scripts/write_suite_metadata.sh`

### Validation

- confirm a run produces metadata files every time
- confirm the recorded git revision and config snapshot match the repo state
- confirm MRT filename is captured exactly

## Workstream 4: Long-Run Robustness and Resume Behavior

### Objective

Make long benchmark sweeps restartable without manual reconstruction.

### Deliverables

#### 4.1 Suite-level resume

The suite runner should be able to skip completed suites if their output directory already exists and is marked complete.

Suggested marker:

- `results/2026/<run-id>/<suite>/COMPLETE`

Resume behavior must be keyed by the explicit run ID described in Workstream 1. If the user does not supply the same run ID, resume is not expected to find prior state.

#### 4.2 Cell-level durability

Longer term, the better model is to make each suite cell durable enough that reruns can skip completed cells rather than rerun the whole suite.

There are two possible approaches:

##### Option A: per-suite CSV plus skip logic

Parse the output CSV and skip cells already present.

Pros:

- less file proliferation

Cons:

- more parsing logic
- more fragile if naming changes

##### Option B: per-cell output files

Write one result artifact per cell, then merge later.

Pros:

- clearer durability model

Cons:

- larger code change
- may require changes in `bgperf2.py`

Recommendation:

- implement suite-level resume now
- decide on cell-level durability after the first stable 2026 sweep

#### 4.3 Clear failure behavior

The runner should distinguish:

- preflight failure
- suite command failure
- interrupted run
- completed run

### Files Likely Touched

- `scripts/run_2026_suite.sh`
- possibly helper scripts for status markers

### Validation

- run one suite successfully, rerun, verify it skips
- interrupt after one suite, rerun, verify it resumes from the next suite

## Workstream 5: Benchmark-Model Improvements

### Objective

Improve what the benchmark can measure, not just how it is launched.

This workstream should start only after Workstreams 1 through 4 are in good shape.

### Deliverables

#### 5.1 Explicit BIRD thread variants in checked-in suites

The current YAML already supports `threads:`, but the checked-in suite set should standardize how BIRD 3 is represented:

- default-thread variant
- explicit `threads: 4` variant

This is partly already present and should be treated as required discipline, not optional interpretation.

#### 5.2 Withdrawal test mode

Add benchmark support for withdrawal-focused scenarios.

Minimum useful forms:

- load then withdraw all
- load then withdraw subset

This likely requires code changes in tester generation or orchestration logic, not just new YAML.

#### 5.3 Incremental delta-update mode

Add a way to benchmark:

- initial steady state
- then a second wave of updates

This is a benchmark-model change, not just a runner feature.

### Files Likely Touched

- likely `bgperf2.py`
- likely tester-related modules
- likely new benchmark configs
- docs updates

### Validation

- prove that the benchmark can distinguish initial load vs delta phase
- prove that completion detection still behaves correctly

## Suggested Execution Order

Implement in this order:

1. finalize checked-in suite configs
2. add suite runner
3. add MRT helper
4. add preflight helper
5. add metadata capture
6. add suite-level resume
7. validate the full 64 GB workflow
8. only then start withdrawal/delta benchmark-model work

## Acceptance Criteria

This plan is complete when all of the following are true:

- a new user can run the 2026 smoke and core suites with one documented command per suite
- the suite runner captures metadata automatically
- the runner refuses obviously broken inputs before long runs start
- the runner can resume at least at suite granularity
- the exact MRT file and exact image state are recorded with results
- the checked-in suite configs are sufficient to reproduce the baseline 64 GB comparison

## Risks and Tradeoffs

### Risk: too much shell logic, not enough benchmark logic

Mitigation:

- keep the initial helpers thin
- do not move benchmark semantics into shell scripts

### Risk: preflight checks become stale

Mitigation:

- keep them simple and factual
- prefer checking current files, mounts, and images over encoding guessed resource formulas

### Risk: resume logic becomes inconsistent with result naming

Mitigation:

- start with suite-level resume only
- avoid cell-level skipping until naming and output conventions are stable

### Risk: withdrawal/delta support becomes a large project

Mitigation:

- explicitly defer it until the execution tooling is stable

## Open Questions

These do not block Workstreams 1 through 4, but they should be answered before Workstream 5:

- Should withdrawal/delta tests be synthetic-only first, or also MRT-based?
- Should resume eventually live in shell tooling, or as a first-class `bgperf2.py` feature?
- Should result metadata be JSON only, or JSON plus a human-readable summary text file?
