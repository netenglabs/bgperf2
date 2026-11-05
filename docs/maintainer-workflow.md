# Follow one problem from reproduction to a regression boundary

For exact prefix identity, the [connected prefix workflow](#exact-prefix-regression-workflow)
below starts with real inert Git preparation and exercises the generated handoff
through candidate CI, repeated comparison and localization. The original crash
walkthrough remains available independently.

Run this maintained offline walkthrough to learn how a recipe, local target
change, diagnostic witnesses and deterministic revision search fit together.
It exercises the public recipe and bisection CLIs with one shared
`target_crash` recipe and one nine-revision simulated history. The same bad tip
appears in reproduction, the local-change investigation and the search.

For your own selected source and revisions, start with
[maintainer checkout preparation](maintainer-checkout.md). It uses real local
Git to prepare clean historical checkouts and a verified handoff; the walkthrough
below demonstrates the later execution/evidence stages with simulated runtimes.

Use the existing [locked Python environment](python-environment.md) on a
development host where no measurement is active. Choose an absolute output
directory that does not exist and is outside the engine checkout:

```sh
venv/bin/python scripts/maintainer_smoke.py --output /absolute/new/maintainer-demo
```

Open `/absolute/new/maintainer-demo/REPORT.md`. This is the human entry point;
its links lead to the retained evidence and explain each stage. The walkthrough
uses maintained simulated source/build/runtime fixtures. It refuses unmodeled
subprocess and socket operations across setup, execution, recovery and reporting.
No real source checkout, compiler, Docker daemon, image download or worker runs.
Read-only destination/capacity checks still observe the local filesystem.
Output remains on local disk, and existing output is never overwritten.

| Stage | What to inspect | What it teaches |
| --- | --- | --- |
| Frozen recipe | `recipe.json`, `plan.json` | Workload, generator, observer and reproduction question stay fixed while only the target changes. |
| Reproduction | `return/reproduction/SUMMARY.txt` and its diagnostic artifacts | An abnormal exit can produce `experiment_failed` while the crash question is `reproduced`; experiment status and reproduction outcome have separate meanings. |
| Local rollback | `return/investigation/REPORT.md` | Fresh baseline/candidate attempts test a local target change, record exact source/build differences and preserve scoped functional outcomes. |
| Stopped investigation | `return/investigation-stopped/REPORT.md` | A separate fresh baseline package survives a controller stop, its candidate remains `not_run`, and offline rebuilding preserves missing-attempt reasons and the inconclusive outcome. |
| Interrupted controller | `interruption/status.json`, `return/pending/REPORT.md` | A completed original trial package may exist before its journal record. A pending reservation blocks another trial and requires explicit recovery. |
| Recovery | `interruption/recovery.json`, `interruption/status-after.json` | `recover --result` records that original package without repeating its build or worker; the pre-recovery state and refusal remain inspectable. |
| Deterministic bisection | `return/bisection/REPORT.md` | The first-bad search uses a single-transition assumption and fresh boundary confirmations, while cached builds retain their own identity. |
| Portable evidence | `verification.json`, `commands.json`, `return/` | The result packages and reports verify after copying to a new local directory; report-only rebuilds start no build or worker. |

The modeled revisions 0–3 complete; revisions 4–8 have an evidenced abnormal
target exit. The local candidate is explicitly a rollback from tip 8 to
pre-regression revision 3. This demonstrates a concrete local change with the
same source identities used by bisection. All stages make distinct original
attempts. The investigation's candidate outcome does not stand in for a search
trial or a fresh confirmation.

The resolved and stopped investigations both use public `investigation-rebuild`
to reconstruct a verified report offline. The stopped case has its own distinct
baseline attempt, a separate controller-stop artifact, and no candidate attempt.
The verified original baseline observation retains its experiment and
reproduction outcomes; the controller stop makes the pair assessment inconclusive.

The simulated interruption occurs after trial 3 has produced a verified package
and before its journal append. The script retains the original work/results,
the pending reservation snapshot, verified pending report, CLI error and
recovery receipt. It first demonstrates refusal to execute another trial, then
explicitly recovers the exact original. No retry or fabricated interrupted
worker is introduced. `session/` retains the complete search state after recovery.

The generated `commands.json` records the exact public entry point, arguments,
exit code, stdout and stderr for every command, including both intentional
refusals. Each record also exists separately under `commands/`, so a later
walkthrough failure preserves completed steps. Original stage packages and
report-only rebuilds remain alongside the copied `return/` evidence.

The return directory can be inspected independently using public offline
verification commands:

```sh
venv/bin/python recipes.py result-verify \
  /absolute/new/maintainer-demo/return/reproduction/result.json
venv/bin/python recipes.py investigation-verify \
  /absolute/new/maintainer-demo/return/investigation/investigation.json
venv/bin/python recipes.py investigation-rebuild \
  /absolute/new/maintainer-demo/return/investigation-stopped/investigation.json \
  --output-dir /absolute/new/stopped-investigation-rebuilt
venv/bin/python recipe_bisection.py verify \
  /absolute/new/maintainer-demo/return/pending/bisection.json
venv/bin/python recipe_bisection.py verify \
  /absolute/new/maintainer-demo/return/bisection/bisection.json
```

These simulated observations establish no actual BIRD bug, fix, reproducible
binary, hardware qualification or performance conclusion. Numeric values in
reused diagnostic fixtures are explicitly simulated. Performance policy stays
disabled, and calibration remains deferred. Checksums detect changed evidence
but do not authenticate its publisher or prove execution.

For a real maintainer-selected problem, follow the [recipe guide](recipes.md),
[trusted local-source and investigation guide](investigations.md), and
[deterministic bisection guide](bisection.md). Those guides own the supported
contracts, prerequisites, execution boundaries and limitations. The smaller
[recipe](../scripts/recipe_smoke.py), [investigation](../scripts/investigation_smoke.py)
and [bisection](../scripts/bisection_smoke.py) smokes retain their separate focused
cases; this walkthrough connects public commands around one modeled problem.

## Exact-prefix regression workflow

```sh
venv/bin/python scripts/prefix_workflow_smoke.py --output /absolute/new/prefix-workflow
```

Open `/absolute/new/prefix-workflow/REPORT.md`. Setup uses the maintained
checkout-preparation workflow with four real local Git commits containing inert
source comments and a retained dirty candidate. Only allowlisted local Git
commands execute during preparation. Build/image/daemon behavior and numeric
observations are explicitly **SIMULATED**. Subsequent stages forbid all real
subprocess and network operations while exercising the public CLIs and actual
handoff command arguments. No BIRD source or deliberately introduced BIRD fault
is compiled or executed; no actual upstream bug or fix is claimed.
`checkout/REPORT.md` remains the historical preparation snapshot; its then-future
destinations subsequently contain this walkthrough's modeled execution evidence.
The frozen setup account and handoff packet are preserved unchanged.

| Stage | Retained entry point | Meaning |
| --- | --- | --- |
| Preparation | `checkout/REPORT.md`, `source-before.json`, `source-after.json`, `prepared-before.json`, `prepared-after.json` | Actual frozen source proofs, private Git bank, isolated historical checkouts, candidate plan and generated handoff remain unchanged through later stages. |
| Reproduction and candidate | `return/investigation/REPORT.md` | All modeled attempts complete with count 100. Baseline substitutes one prefix, candidate has the exact set. Completion/reproduction is separate from prefix truth. |
| CI | `commands.json` | Default both-side check exits 4, candidate check exits 0, missing selected candidate exits 5. Full integrity verification covers both sides. |
| Repetition | `return/comparison/REPORT.md` | Two rounds/four distinct original attempts retain separate count and identity assertions. Capture remains an uncalibrated confounder, so no controlled timing delta follows. |
| Interruption | `return/pending/REPORT.md`, `interruption/` | A collected original exists before journal append. A pending reservation refuses another trial; explicit recovery records that same original without rerunning work. |
| Localization | `return/bisection/REPORT.md` | The combined `prefix_assertions` predicate finds the modeled revision 1/2 boundary and requires fresh good/bad confirmations. Build caching never reuses a worker observation. |
| Portability | `return/`, `verification.json` | Copied reports verify independently, and offline reconstruction starts no modeled build or worker. Prepared checkouts, original work and build caches remain at their original location-bound paths. |

The fixed question is `experiment_completed`, so the prefix mismatch does not
change recipe reproduction into a routing-correctness verdict. The optional
capture receipts and named assertions supply that separate evidence. The
combined localization predicate can also classify another decisive supported
assertion failure; a count failure alone must not be called an observed prefix
identity mismatch. Missing evidence stays unmeasured or ambiguous.

Use the [prefix contract](observer-prefixes.md), [comparison guide](comparisons.md),
[CI check](investigations.md) and [bisection guide](bisection.md) for supported
commands and limits. This walkthrough adds no execution authority, source trust,
binary reproducibility, live path qualification, continuous route correctness
or performance verdict. Keep the original evidence; a portable report tree and
local checksums are not a complete independent backup. Performance policy stays
disabled and formal 10% calibration deferred.
