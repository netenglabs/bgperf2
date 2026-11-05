# Compare two target selections

The separately approved [four-worker prefix case](plans/prefix-maintainer-workflow.md#approved-normal-comparison-validation--2026-11-04-utc)
passed all 24 assertions with exact 100-prefix snapshots and verified original
and rebuilt reports. It qualifies that same-image normal functional path, not
live staged capture, a changed binary or performance detection.

Use one immutable synthetic IPv4 recipe with a BIRD or supplied-image `frr_c`
target, BIRD generators and sink observer, and two same-adapter
[target selections](investigations.md). A comparison repeats the whole pair,
preserves every attempt and returns a portable JSON and Markdown report.
It does not enable calibrated performance verdicts. Read the
[measurement dictionary](measurement-dictionary.md) for the existing clocks and
accounting boundaries; no measurement definition changes here.

The [FRR guide](frr-maintainer-workflow.md) documents its supplied-image scope
and modeled comparison evidence. Cross-daemon image overrides are refused;
actual FRR runtime qualification remains separate from modeled checks. The
[controlled FRR case](plans/frr-correctness-localization-validation.md) collects
two fresh public-run originals for an introduced prefix fault and explicit
rollback, then verifies comparison/investigation reports and reconstruction.
It does not qualify the combined `compare` execution controller or repetition
adequacy; all timing observations remain descriptive and uncalibrated.

This descriptive workflow is delivered for the supported recipe. Formal reliable
10% regression detection is deferred and is not a release blocker; automated
performance verdicts remain disabled. See the
[development decision](plans/performance-testing-development-plan.md#operator-decision-descriptive-comparisons-first--2026-10-31)
for the conditions of any later calibration campaign. Recorded differences,
including large ones, do not establish a general detection guarantee.

For preparation, synchronous assessment, explicit first-attempt and final
reviews, optional operational pressure screening and a prior-series review
gate, use [staged comparison execution](comparison-execution.md). The existing
`compare` command below retains its original semantics.

## Exercise the complete workflow without Docker

Use the existing locked Python environment in a public checkout:

```sh
venv/bin/python scripts/comparison_smoke.py --output /absolute/new/comparison-demo
```

This walkthrough simulates selected targets, prerequisite checks and worker
evidence. Its controlled differences, noise, confounders and missing/stopped
cases demonstrate report behavior. They establish no BIRD performance,
hardware qualification or real regression. The script refuses unmodeled
subprocess and network operations; it downloads and builds nothing.

## Freeze the expectations and sequence

After exporting a recipe and selecting both immutable targets, choose the
repetition budget explicitly. The `2` below demonstrates two rounds (four
attempts); it is not a statistical sample-size recommendation.

```sh
venv/bin/python recipes.py assertions-export /absolute/artifacts/recipe.json \
  --capability session_establishment --capability injection_completion \
  --capability observer_route_count --capability experiment_completion \
  --output /absolute/artifacts/assertions.json
venv/bin/python recipes.py comparison-plan /absolute/artifacts/recipe.json \
  --baseline-target /absolute/artifacts/baseline-target.json \
  --candidate-target /absolute/artifacts/candidate-target.json \
  --assertions /absolute/artifacts/assertions.json \
  --repetitions 2 --order alternating --diagnostics none --timeout 300 \
  --output /absolute/artifacts/comparison-plan.json
```

These commands validate and write new files without runtime probes. Keep their
output outside the source checkout so execution can require a clean pinned
revision. The plan embeds the unchanged recipe, both target declarations,
assertions, diagnostics, worker timeout and complete ordered sequence.
Assertions default to the exported set when `--assertions` is omitted.
Strict schemas refuse unknown fields and unsupported assertions.

The example selects four worker-budget assertions explicitly. Final container
health snapshots and cgroup memory require `--diagnostics basic`; `none` leaves
them unmeasured. Omitting `--capability` exports all five assertions, so the
default full set with `diagnostics none` yields inconclusive health. Select the
full set with `basic` when investigating those observations, retaining its
uncalibrated overhead confounder. Unsupported capabilities cannot be requested.

For exact received-prefix checks on every repeated attempt, select capture in
the frozen plan:

```sh
venv/bin/python recipes.py comparison-plan /absolute/artifacts/recipe.json \
  --baseline-target /absolute/artifacts/baseline-target.json \
  --candidate-target /absolute/artifacts/candidate-target.json \
  --observer-prefixes --repetitions 2 --order alternating \
  --diagnostics basic --timeout 120 \
  --output /absolute/artifacts/prefix-comparison-plan.json
```

`--observer-prefixes` selects the existing bounded final snapshot on both sides
of every round. It requires a supporting immutable sink image and at most
100,000 expected prefixes. The optional plan field is strictly `true`; omitting
it preserves old plan shapes, defaults and runner arguments. The selected
default assertion set contains all six assertions, including prefix identity.
An explicit `--assertions` document remains the requested specification: capture
does not silently add predicates or turn a count-only specification into an
identity check. The plan and captured artifacts retain that distinction.
Invalid selection or capture bounds refuse before runtime probes or output
creation. Old engines refuse plans containing the new optional selection.

Each selected report includes a separate count/identity table for every planned
attempt, with exact observed, missing and unexpected prefix counts when measured.
Missing or unavailable capture stays unmeasured, and stopped/not-run positions
retain their original meanings. Selected capture always records an uncalibrated
overhead confounder, even with an explicit specification that omits identity;
it withholds controlled descriptive deltas without discarding observations.
One final snapshot establishes neither route attributes nor continuous truth.
No capture-overhead calibration or performance policy is enabled.

`alternating` produces AB, BA, AB, BA across rounds. `shuffle --seed INTEGER`
orders the two roles independently in each round using deterministic SHA-256
keys, following the existing batch ordering approach. Every round contains
both roles; repetition identities do not depend on position. The recorded seed
reconstructs the sequence without interpreter-specific random draws. Seeds apply
only to shuffle; there is no implicit random seed. The implementation bounds
repetitions to 1–100, independent of statistical adequacy.

## Execute only an authorized comparison

Select an otherwise idle, qualified Linux host with suitable persistent storage,
the existing locked environment and all exact images already available. Neither
the plan nor the functional A/B smoke qualifies a host. The development-host
concurrency/root-storage exceptions used in earlier validation do not authorize
performance measurements.

```sh
venv/bin/python recipes.py compare /absolute/artifacts/comparison-plan.json \
  --workdir /absolute/disk/work/comparison-001 \
  --results-dir /absolute/disk/results/comparison-001
venv/bin/python recipes.py comparison-verify \
  /absolute/disk/results/comparison-001/report/comparison.json
```

Both targets must pass existing prerequisite checks before execution or creation
of the comparison roots. The explicit `compare` operation executes serially
through the existing guarded recipe runner, with new per-attempt work/results
paths, scoped owned cleanup and the planned worker budget. Each attempt is
verified against the exact recipe and selected target before continuing.
Final collection, cleanup and packaging remain separate from worker budgets.
No pull, build, retry, resume, automatic extra repetitions or evidence removal
is part of this command. Cooperating recipe attempts take the existing host
lock per attempt; the sequence does not reserve the machine between attempts or
exclude arbitrary Docker users.

The runner stops at the first noncompleted experiment, setup/harness failure,
interrupt or inconclusive attempt. Earlier evidence and failed work remain in
place; later attempts are explicitly `not_run`. A checksummed but invalid or
unverifiable package remains in the original results directory and is withheld
from the portable report. The local `attempts.json` ledger records that reporting
failure. A hard kill, storage failure or machine loss may prevent final packaging;
the incrementally written ledger is not a transactional resume mechanism.

Exit 0 means the planned sequence was recorded, not that correctness assertions
passed or that performance improved. Stops propagate the attempt exit (2–5,
130 or 143). Contract or report verification refusals exit 2. Inspect the report
and every attempt's independent status and assertion outcomes.

## Named correctness assertions

The separate `bgperf2/assertions/v1alpha1` specification binds expectations to
the canonical recipe digest. It survives export, comparison execution and
portable packaging without changing the recipe/result v1 envelopes. Evaluate
it against any compatible verified package:

```sh
venv/bin/python recipes.py assertions-check /absolute/artifacts/assertions.json \
  --result /absolute/results/attempt/result.json
```

| Assertion | Meaning and boundary |
| --- | --- |
| `sessions.ready` | Configured generator session total witnessed ready in lifecycle events |
| `injection.complete` | Configured generator session total witnessed complete in lifecycle events |
| `observer.count` | Exact observer count at convergence confirmation equals the selected total prefix count |
| `experiment.complete` | Existing engine runtime records completion; separate from exact count agreement |
| `roles.healthy` | Expected roles have running, non-OOM, error-free owned container snapshots at final pre-cleanup collection |

The first four positive assertions require a satisfied finite worker budget in
`work/execution-budget.json`. Its controller monotonic elapsed interval excludes
final diagnostics and cleanup. Health uses a later pre-cleanup snapshot and does
not assert continuous or per-daemon health. Older/missing budget evidence remains
unmeasured. Every answer carries expected and observed values, witness paths and
hashes, deadline scope and reasons. Overall outcomes are `passed`, `failed` or
`inconclusive`; the CLI exits 0, 4 or 5 respectively.

Exact observer count is deliberately separate from the existing convergence
threshold: an engine-completed attempt may fail exact count agreement. It proves
no route identities or attributes. Unsupported attribute, policy, recovery,
IPv6 and action predicates are refused instead of reduced to counts or sleeps.

An explicitly selected [received-prefix identity assertion](observer-prefixes.md)
inspects a complete final snapshot from a supporting capture-selected run or
comparison plan. It is separate from the five unselected defaults and from the
convergence-time count. Merely selecting that assertion does not enable capture;
the comparison plan must independently select `--observer-prefixes`. Packages
without complete capture leave the assertion unmeasured. Attribute predicates
remain unsupported.

For compatibility, an older unselected plan can still evaluate an explicitly
requested identity assertion against independently captured packages. Its old
confounder rules are not retroactively reclassified. An absent capture confounder
is not proof that capture did not occur or that its overhead was calibrated;
use the explicit plan selection for newly prepared capture comparisons.

## Inspect and rebuild the report

Open `report/REPORT.md` and `report/comparison.json`. The portable
`bgperf2/comparison/v1alpha1` bundle includes its frozen plan and verified copies
of available packages under `attempts/<id>/`. It retains attempt statuses,
reproduction outcomes, named assertions and source/build/host/image identities.

Memory, CPU and timing are separate named observations with units and accounting
definitions. Reports show individual values, counts, missing observations, failed
attempts, work never run, mean/median/range, sample standard deviation and
coefficient of variation where defined. Missing/failed data is never zero and
is never silently dropped. Performance distributions include only completed
attempts and retain their confounders and correctness outcomes.

Kernel container memory peaks include setup and file-backed/cache costs;
ending memory is the final pre-cleanup observation. Sampled peaks are not
unsampled extremes. Process RSS remains unsupported. Legacy peak target CPU is
not total CPU work, monitor elapsed has at least one-second resolution, and total
runtime includes setup. No leak diagnosis follows from these quantities.

`memory.target_delivery_sampled_peak_gib` separately retains the legacy
`max mem (GB)` column in its actual GiB units, sampled over delivery and rounded
to three decimals. Its rounded zero is withheld as below resolution, rather than
claimed as zero memory. This metric remains available without optional final
diagnostics; it is never substituted for a kernel cgroup lifetime peak.

Changed or incomplete host/image identities, unknown or instrumented targets,
basic/unrecorded diagnostics, recorded contention, failed/unmeasured assertions
and incomplete pairs withhold descriptive deltas while retaining observations.
An available median difference is explicitly unqualified. Performance remains
`not_assessed` and regression policy `disabled` in every report. A separately
reviewed calibration must select effect sizes, repetition budget, noise handling
and policy before any calibrated verdict can be enabled.

Rebuild from the retained frozen plan and ledger without runtime access, choosing
a new output directory:

```sh
venv/bin/python recipes.py comparison-report /absolute/results/comparison-plan.json \
  --attempts /absolute/results/attempts.json --output-dir /absolute/new/report
venv/bin/python recipes.py comparison-verify /absolute/new/report/comparison.json
```

Verification checks the complete file inventory and hashes, every bundled result,
recipe/target bindings, reconstructed statistics/assertions/confounders and human
prose. It refuses unsafe, unlisted, missing or modified artifacts. Checksums
establish local integrity, not publisher authenticity or proof of execution.
Keep original work and local evidence. No upload, publication or expiry runs.

For a separate, offline view of the existing sink's finer count timestamps, see
the [observer delivery timing supplement](observer-timing.md). It retains
observed crossing bounds and an explicit discovery screen, while leaving this
comparison report and all legacy timing definitions unchanged.

The [FRR combined-controller case](plans/frr-controller-runtime-validation.md)
separately exercised the public comparison command with two alternating pairs
and four fresh bad/good/good/bad originals, exact prefix witnesses, owned cleanup
and rebuilt/relocated reports. This validates the selected functional controller
path, not statistical repetition adequacy or performance sensitivity.
