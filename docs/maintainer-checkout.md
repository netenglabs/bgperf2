# Prepare your own maintainer checkout

Use this path when you already have a selected local BIRD-style source checkout,
a recipe and the revisions you want to investigate. It replaces manual creation
of a clean checkout and build plan for every bisection revision with one isolated
preparation, then freezes the concrete public commands for your baseline and fix.

Preparation uses local Git and filesystem reads/writes only. Source configure
code, builds, Docker probes and workers remain separate operations. Image
availability, host suitability and execution authorization remain unassessed.
Performance policy stays disabled and calibration deferred.

For a concrete real-source example awaiting execution approval, see the
[neutral BIRD release-transition case](plans/real-bird-maintainer-validation.md).
It explicitly adapts the two BSD aliases into a separately identified packaging
history and then uses this unchanged preparation/handoff workflow. It alleges
no upstream bug and does not enable general symlink support.

## Select the question and source history

Freeze a recipe using the [recipe guide](recipes.md) and select full source
commit IDs for an inclusive, consecutive first-parent good→bad range. Keep the
same workload, generator, observer and question throughout. Use the existing
`assertions` predicate with an `experiment_completed` question, or `target_crash`
with the corresponding crash question. A selected endpoint still needs actual
good/bad witnesses during execution; its label is not evidence.

```sh
venv/bin/python recipe_source_range.py prepare \
  --recipe /absolute/artifacts/recipe.json \
  --source /absolute/maintainer/source \
  --good FULL_GOOD_SOURCE_COMMIT --bad FULL_BAD_SOURCE_COMMIT \
  --toolchain-image sha256:TOOLCHAIN_64_HEX_IMAGE_ID \
  --runtime-image sha256:RUNTIME_64_HEX_IMAGE_ID \
  --predicate assertions --max-trials 32 \
  --worker-timeout 120 --build-timeout 1200 \
  --output /absolute/new/prepared-range
venv/bin/python recipe_source_range.py verify \
  /absolute/new/prepared-range/source-range.json
```

Replace the conspicuous commit/image placeholders. The original source can
retain local dirty/untracked changes; historical source plans use isolated clean
checkouts. Preparation retains its local repository, per-revision plans, range
proofs, command records and human report. Partial preparation is retained on
failure. See [source-range preparation](source-range.md) for its source,
resource and object-integrity contract.

## Select the baseline and local fix

Choose the exact baseline build-plan filename from the prepared range. The
candidate may be another prepared revision or a separately selected local fix.
For an uncommitted fix, the existing source planner records explicit dirty
inclusion, patch and untracked-file identities without changing that checkout:

```sh
venv/bin/python recipes.py target-source-plan /absolute/artifacts/recipe.json \
  --source /absolute/maintainer/fix-source --revision FULL_CANDIDATE_SOURCE_COMMIT \
  --toolchain-image sha256:TOOLCHAIN_64_HEX_IMAGE_ID \
  --runtime-image sha256:RUNTIME_64_HEX_IMAGE_ID \
  --include-dirty --output /absolute/artifacts/candidate-build-plan.json
```

The candidate revision must equal that checkout's HEAD. Omit `--include-dirty`
for a clean candidate. Review source trust and build controls through the
[investigation guide](investigations.md); planning alone executes no source code.

## Freeze the handoff

```sh
venv/bin/python recipe_handoff.py prepare \
  --source-range /absolute/new/prepared-range/source-range.json \
  --baseline-build-plan /absolute/new/prepared-range/build-plans/NNN-FULL_BASELINE_COMMIT.json \
  --candidate-build-plan /absolute/artifacts/candidate-build-plan.json \
  --build-root /absolute/new/builds --work-root /absolute/new/work \
  --results-root /absolute/new/results --session /absolute/new/search \
  --output /absolute/new/handoff
venv/bin/python recipe_handoff.py verify /absolute/new/handoff/handoff.json
```

Open `handoff/RUNBOOK.md`. The [handoff contract](maintainer-handoff.md) binds
canonical inputs, exact existing search budgets, explicit destination roles,
build differences and dependency-ordered argument arrays. Future targets refer
to returned `target.json` paths, with their image IDs still unknown. Only the
handoff directory is created; build/work/results/session roots remain fresh.
The command graph is inspectable metadata rather than an executable scheduler.

The runbook joins reproduction, assertions, a separate fresh fix investigation,
optional descriptive comparisons and deterministic bisection/recovery. Existing
public commands perform their actual checks when individually selected.
An expected reproduced crash can have exit 4; report verification success is
different from a successful fix or confirmed boundary. Read the scoped outcomes
and actual stop evidence at each stage. The handoff grants no runtime authority.

## Try the preparation path without daemon execution

```sh
venv/bin/python scripts/checkout_workflow_smoke.py \
  --output /absolute/new/checkout-preparation-demo
# Or exercise the same preparation contract for a crash question:
venv/bin/python scripts/checkout_workflow_smoke.py \
  --predicate target_crash --output /absolute/new/crash-preparation-demo
```

Open the generated `REPORT.md`. This maintained example creates an inert local
Git history and a pre-existing dirty fix, then calls the real preparation and
handoff CLIs. It verifies unchanged original HEAD/refs/index/configuration and
dirty/untracked bytes, retained range proofs and absent runtime destinations.
Unmodeled process/network operations are refused; only selected local Git runs.
No BIRD source, compiler, image download, build or worker is involved.

The [connected execution walkthrough](maintainer-workflow.md) separately uses
fully simulated source/build/runtime fixtures to demonstrate returned evidence,
controller stops, exact-original recovery and confirmed boundaries. These two
examples exercise preparation and execution contracts without claiming a real
daemon bug/fix or live qualification.

Prepared source roots, Git worktree administration and handoff paths are
location-bound. Retain that layout for later use; portable result reports have
their separate relocation support. Existing strict regular-file source rules
still apply: pristine BIRD symlink aliases/submodules are not silently rewritten.
Actual daemon builds and workload runs require their own selected case and
applicable host/source/execution decisions.
