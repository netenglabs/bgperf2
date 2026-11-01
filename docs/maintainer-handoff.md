# Prepare the concrete commands for a selected maintainer problem

Use a [prepared local revision range](source-range.md), one explicit baseline
build plan from that range, and one explicit candidate build plan. The candidate
can be another range revision or a separately planned local clean/dirty change.
The handoff does not infer that it fixes the problem. Both selected targets keep
the exact same recipe, generator, observer and reproduction question.

This command creates a new, checksummed local bundle with canonical inputs,
the exact existing bisection plan, dependency-ordered public command arguments
and a readable runbook. It verifies local source snapshots but runs no source
code, image inspection, download, build, worker or host-capacity probe. It never
accepts `--execute` and never changes a maintainer checkout.

```sh
venv/bin/python recipe_handoff.py prepare \
  --source-range /absolute/prepared-range/source-range.json \
  --baseline-build-plan /absolute/prepared-range/build-plans/BASELINE.json \
  --candidate-build-plan /absolute/artifacts/local-fix-build-plan.json \
  --build-root /absolute/new/builds \
  --work-root /absolute/new/work \
  --results-root /absolute/new/results \
  --session /absolute/new/bisection-session \
  --output /absolute/new/handoff
venv/bin/python recipe_handoff.py verify /absolute/new/handoff/handoff.json
```

Replace `BASELINE.json` with the exact plan selected from the range. A separate
candidate plan comes from the existing
[`target-source-plan` workflow](investigations.md#plan-a-trusted-local-source-build).
All artifact roots must be absolute, fresh, distinct and nonnested, outside the
engine, original maintainer checkout, prepared range, selected source trees and
input evidence. The original checkout stays protected even when both selected
plans refer only to prepared worktrees. No destination
apart from the handoff bundle is created during preparation.

Open `/absolute/new/handoff/RUNBOOK.md`. `commands.json` retains the same public
argument arrays, dependencies, limits and explicit decision points. It is
metadata, not a script or scheduler. Commands refer to the actual future
`builds/baseline/target.json` and `builds/candidate/target.json` returned by source
builds; no image identity or successful build is invented. The declared image
inventory includes both selected toolchain/runtime pairs and the fixed generator
and observer. The recipe's original target image is not an additional requirement
after a target override is selected.

The runbook connects these existing operations:

- Build each explicitly selected trusted source plan into its own fresh output.
- Check the actual baseline target, reproduce the problem, verify its original
  package and evaluate named observable assertions separately.
- Run a separate fresh baseline/candidate investigation and verify or rebuild
  its complete/partial report without losing controller stops or missing reasons.
- Optionally create and execute a descriptive comparison after actual target
  artifacts exist.
- Initialize the unchanged prepared bisection plan, inspect/preview requests,
  explicitly select a bounded step, and verify a retained report.
- Inspect a pending reservation and recover its exact original package, or
  explicitly record an abandonment reason. Recovery guidance never invents a
  trial result path or repeats its build/worker.

A reproduction of a target crash can return **exit 4** with experiment status
`experiment_failed` and reproduction outcome `reproduced`. This is different
from harness failure, interruption, or a general fix claim. Named assertions can
independently fail or remain inconclusive. Read each result and stop condition;
a dependency edge does not authorize the next action. The supported assertion
and crash bisection predicates retain their existing recipe meanings.

Comparison is omitted unless repetitions are explicitly selected:

```sh
# Add to prepare only when these extra descriptive workers are selected:
--compare-repetitions 4 --compare-order alternating
# Or select deterministic shuffle order with its explicit seed:
--compare-repetitions 4 --compare-order shuffle --compare-seed 23
```

A seed is accepted only for shuffle order. The worker/build timeouts and search
trial budget remain exactly those in the prepared bisection plan. The bundle
records ceilings for two initial source builds, one reproduction, one separate
functional pair, any selected comparison workers and the existing bounded
bisection. Candidate instrumentation, compiler flags, source or build-environment
differences remain visible; they are not silently normalized into a controlled
performance comparison. Policy stays disabled and qualification not assessed.

Verification rechecks the original input bytes, prepared range, selected source
snapshots, complete copied inputs, command derivation, budgets and runbook. It
refuses unsafe paths, overlaps, relocation, changed inputs and unlisted bundle
content. This is a location-bound preparation: retain its original input plans
and source worktrees at their selected paths. Existing portable result and
investigation/bisection report contracts remain separate.

When both selected plans use prepared worktrees, the original exported checkout
is provenance only and need not remain present for verification. Its recorded
path remains protected from handoff and future-output writes. A separately
selected dirty-fix checkout is still an active source input and must continue
matching its frozen build plan.

Local image availability, OS tools, engine cleanliness, host suitability and
execution authorization remain **unassessed**. Future public commands perform
their own existing prerequisite and non-overwrite checks; the handoff neither
waives them nor installs missing prerequisites. A valid handoff is not readiness
qualification or retry permission. Hashes detect changed evidence but do not
authenticate its author or prove execution.
