# Milestone B runtime validation proposal

Prepared 2026-10-23. Status: proposed only. Milestone B implementation, tests and
controlled investigation reports grant no runtime authorization. The current
operator instruction excludes real downloads, builds, benchmarks, provisioning,
9950 access and pushing.

## Recommended first authorization: supplied-image functional pair

Authorize exactly one serial BIRD/BIRD/sink investigation on `jpietsch-server`,
with two maximum 120-second worker budgets and the new basic diagnostics enabled.
Permit ordinary concurrent work only for this functional check, with the same
explicit small-run root-backed disk exception as milestone A. This validates
selected-target substitution, completion, diagnostic availability and packaging;
it supplies no performance comparison or real bug-fix claim.

The earlier local inventory recorded these images. Reinspect exact identities
before execution; a missing or changed image stops the procedure without pulling,
building, importing or retagging anything:

| Role | Immutable local image ID |
| --- | --- |
| Baseline target, generator for both attempts | `sha256:db0a8e144635b1d4b9f81f24ee78f11383c5b0cbd79f10353edcb8452e9af423` (BIRD 2.19.2 as observed in A) |
| Candidate target | `sha256:7f60bf1483ccf766c768f0a3d894b52176748a4d76f9d18cc9af8730520b9142` (previously inventoried BIRD 3.3.2, reverify actual version) |
| Observer for both attempts | `sha256:311317014fc98e2cadf46941b4b23dab9dd724281dd50167a0f9187d8ac08f19` (sink built and observed in A) |

Use one clean checkout at the final committed B implementation and its existing
locked Python environment. Record source revision, host/kernel and capacity
observations. Require the normal active-measurement guard, no other benchmark,
at least 10 GiB free disk and 2 GiB available memory as smoke admission floors,
not workload estimates. Verify `/var/tmp` mount/write suitability. Do not install
or repair missing prerequisites automatically. Keep all earlier A evidence.

After authorization, create an owner-only new `/var/tmp/bgperf-recipe-b-validation`
for recipe, target selections, command logs, exact image inspections and
before/after resource inventories. From the selected clean engine checkout:

```sh
venv/bin/python recipes.py export \
  --batch examples/recipes/synthetic-ipv4.yaml --test synthetic-ipv4 \
  --cell f94a3878b2dad49e --engine-revision "$(git -C . rev-parse HEAD)" \
  --target-image sha256:db0a8e144635b1d4b9f81f24ee78f11383c5b0cbd79f10353edcb8452e9af423 \
  --generator-image sha256:db0a8e144635b1d4b9f81f24ee78f11383c5b0cbd79f10353edcb8452e9af423 \
  --observer-image sha256:311317014fc98e2cadf46941b4b23dab9dd724281dd50167a0f9187d8ac08f19 \
  --question 'Functional milestone B adapter/diagnostic check: do both supplied BIRD targets complete?' \
  --output /var/tmp/bgperf-recipe-b-validation/recipe.json
venv/bin/python recipes.py target-image /var/tmp/bgperf-recipe-b-validation/recipe.json \
  --image sha256:db0a8e144635b1d4b9f81f24ee78f11383c5b0cbd79f10353edcb8452e9af423 \
  --label released-baseline --instrumentation unknown \
  --output /var/tmp/bgperf-recipe-b-validation/baseline-target.json
venv/bin/python recipes.py target-image /var/tmp/bgperf-recipe-b-validation/recipe.json \
  --image sha256:7f60bf1483ccf766c768f0a3d894b52176748a4d76f9d18cc9af8730520b9142 \
  --label supplied-candidate --instrumentation unknown \
  --output /var/tmp/bgperf-recipe-b-validation/candidate-target.json
venv/bin/python recipes.py investigate /var/tmp/bgperf-recipe-b-validation/recipe.json \
  --baseline-target /var/tmp/bgperf-recipe-b-validation/baseline-target.json \
  --candidate-target /var/tmp/bgperf-recipe-b-validation/candidate-target.json \
  --workdir /var/tmp/bgperf-recipe-b-work-001 \
  --results-dir /var/tmp/bgperf-recipe-b-results-001 \
  --timeout 120 --diagnostics basic
venv/bin/python recipes.py investigation-verify \
  /var/tmp/bgperf-recipe-b-results-001/report/investigation.json
```

This selects one peer and 100 prefixes. Both completions are expected; the
report's functional assessment should be `same_observed_reproduction`, with
performance `not_assessed`. Source/flags remain unknown for supplied images.
Do not present a released-version substitution as a real fix investigation.

Stop on the first unexpected setup/harness/inconclusive outcome or failed
verification. No automatic retries, forced terminations, timeout extension or
other workloads are authorized. Probe/collection/cleanup budgets are additional
to the two worker budgets; final diagnostics have a 20-second collection budget
per attempt (plus bounded client termination), and cleanup/packaging overhead
is recorded separately.

Review both verified packages, stage records, exact target-only identity change,
fixed generator/observer, observed versions, optional BIRD presence, logs and
memory accounting. Missing cgroup/peak/RSS observations remain unknown. Confirm
owned resources/samplers stop and unrelated identities remain unchanged. Preserve
all original work, build/target declarations, command logs and checksum/coverage
manifests locally. Record actual results in the engine plan with a local commit.
No evidence removal, upload, 9950 access, provisioning or push is included.

## Separate source-fix/build qualification decision

The controlled fixture proves the source-plan/build/target/report paths with
fakes, not real BIRD compilation or a real bug. A real source-fix investigation
requires the operator to name a concrete trusted BIRD source checkout, requested
full commit and reviewed local changes, plus already-provisioned immutable
builder and runtime base images. No such selection is inferred from a sibling
checkout or made by downloading source.

Once selected, the exact read-only planning action is:

```sh
venv/bin/python recipes.py target-source-plan /absolute/recipe.json \
  --source /absolute/operator-selected/bird --revision FULL_40_HEX_COMMIT \
  --toolchain-image sha256:APPROVED_LOCAL_TOOLCHAIN_64_HEX_ID \
  --runtime-image sha256:APPROVED_LOCAL_RUNTIME_64_HEX_ID \
  --instrumentation debug --cflags='-O0 -g' --include-dirty \
  --output /absolute/new/candidate-build-plan.json
```

The source tree must meet the full-checkout/no-filter/no-lazy-fetch restrictions
in the [investigation guide](../investigations.md). Review the actual snapshot,
patch/untracked hashes, configure/link flags and plan before authorizing exactly
one `target-build PLAN --output-dir NEW_DIR --timeout 1200`. It uses
`--network=none` and `--pull=false` through the required local legacy builder,
with BuildKit disabled and no remote Buildx fallback. All build tools, headers and runtime/sanitizer
libraries must already exist. A missing prerequisite is a refusal, not permission
for package installation, image acquisition or a broader build. Timeout stops
owned clients but cannot guarantee Docker daemon/cache cancellation.

After successful identity verification, a separate two-attempt functional
investigation can reuse the same frozen recipe and instruments, selecting the
new local target. The concrete bug and expected outcome must be stated first;
a reproduced baseline and nonreproduced candidate are observations, not a
universal fix guarantee. Core dumps, privileged journals, forced daemon faults,
active-container timeout trials and real memory-regression qualification are not
included in either authorization proposed here. Prepare their exact procedure,
budget, owned resources and evidence expectations separately if selected.

## Decision at the milestone B handoff

Review the returned controlled reports and public commands first. Recommended
first real check is the supplied-image pair above, requiring no downloads or
builds. Alternatively, select the real BIRD bug/source pair and reviewed local
base images so the source plan can be made concrete before any build approval.
No stage is currently authorized to execute.
