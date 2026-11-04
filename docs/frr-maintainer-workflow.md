# Supplied-image FRR maintainer workflow

The portable maintainer workflow supports the existing `frr_c` adapter with
synthetic IPv4 BIRD generators and the sink observer. This means images compatible
with bgperf2's compiled FRR adapter: its executable paths, generated configuration,
startup commands and version/neighbor queries. It does not promise compatibility
with all FRR images or arbitrary registry images. BIRD remains the default target.

Implemented and reviewed at `f81404b`; the native repository gate passed 3,071
tests with one skipped. The [delivery plan](plans/frr-maintainer-workflow.md)
records modeled acceptance and the separately approved
[successful real-image functional pair](plans/frr-maintainer-workflow.md#approved-same-image-functional-pair-completed--2026-11-04-utc).
Both originals passed all six assertions, exact-prefix checks, independent review
and owned cleanup; original and reconstructed reports verified. This qualifies
that selected same-image functional path. Broader live comparison/minimization,
performance and source/build qualification remain separate.

Supply immutable image IDs (`sha256:…`) or repository digests for all three roles.
An image pin identifies selected bytes; it does not establish FRR source revision,
build flags, provenance, correctness or host qualification. `target-image` retains
unknown source provenance for an externally supplied image. Substituting a second
image changes the target identity; it does not establish a source fix. The target
adapter must remain `frr_c` on both sides. Generators and observer remain fixed.

## Maintained modeled example

From a configured checkout, choose a new absolute directory outside the checkout:

```sh
venv/bin/python scripts/frr_workflow_smoke.py --output /tmp/my-new-frr-workflow
```

Open its `REPORT.md`. The public CLI exports a recipe, validates/plans/checks it,
selects two supplied FRR image identities, and packages one reproduction and a
functional investigation. Six selected assertions cover sessions, injection,
observer count, bounded completion, observed role health and exact prefix identity.
The modeled baseline completes while correctness fails; the candidate passes.
A missing candidate remains inconclusive. The repeated comparison retains four
distinct original attempts. A separate staged case models passing observations
for both supplied images: prepare starts no worker, each explicit step assesses
one original, and first/final review gates refuse premature continuation. Written
review attestations are explicitly modeled, without claiming independent human
review. Bounded minimization selects `observer.count`, reduces
the count failure to two routes and uses a fresh confirmation attempt.

The walkthrough retains 14 distinct modeled originals: one reproduction, two
investigation, four repeated comparison, two staged comparison and five
minimization attempts. The passing staged case demonstrates controller gates;
it does not change the separate controlled mismatch case. Its final reviewed
report is reconstructed and verifies after relocation with the other reports.
The staged session retains its copied review text, assessments and hash-bound
receipts. Those receipts bind absolute local session paths; their portability
is not claimed by relocating the comparison report.

Every image, numeric observation and worker outcome is **SIMULATED**. Global
subprocess and socket guards forbid real workers, builds, acquisition and network.
Local command parsing, planning, packaging, accounting and verification execute
normally. The example establishes no FRR fault, fix, source change, actual adapter
qualification or performance result. The retained command receipts include portable
verification, offline report reconstruction, relocation and changed-report refusal.

## Explicit commands with supplied images

Create a supported batch definition with target `name: frr_c`, generator `bird`
(the default) and `monitor: sink`. Select its exact legacy cell key, then export:

```sh
venv/bin/python recipes.py export --batch workload.yaml --test selected-test \
  --cell CELL_KEY --engine-revision ENGINE_COMMIT \
  --target-image FRR_IMAGE_ID --generator-image BIRD_IMAGE_ID \
  --observer-image SINK_IMAGE_ID --question 'Selected FRR behavior' --output recipe.json
venv/bin/python recipes.py plan recipe.json
venv/bin/python recipes.py target-image recipe.json --image SECOND_FRR_IMAGE_ID \
  --label 'Supplied candidate; source unknown' --output candidate.json
venv/bin/python recipes.py check recipe.json --target candidate.json \
  --workdir /data/frr-check-work --results-dir /data/frr-check-results
```

`plan` is offline. `check` makes read-only local prerequisite probes, including
selected local image availability, and starts no worker. Neither command authorizes
acquisition or compilation. Missing images remain an explicit prerequisite gap.
Review the paths, workload, runtime deadline, available images and owned-resource
cleanup before explicitly requesting runtime execution on an idle suitable host:

```sh
venv/bin/python recipes.py run recipe.json --target candidate.json \
  --workdir /data/frr-run-work --results-dir /data/frr-run-results \
  --timeout 120 --diagnostics basic --observer-prefixes
venv/bin/python recipes.py result-verify /data/frr-run-results/result.json
```

This `run` is a real worker gate; the modeled walkthrough never authorizes it.
Prefix capture requires a supporting supplied sink image and adds a bounded
post-measurement observation. Use [investigations](investigations.md),
[comparisons](comparisons.md), [staged comparison execution](comparison-execution.md)
and [minimization](minimization.md) for the remaining explicit commands and budgets.
The emitted `commands.json` in the modeled example records complete runnable CLI
shapes for these stages, including assertion selection, investigation CI checks,
rebuilding and verification. Use fresh owned destinations for real execution.

Basic FRR diagnostics retain scoped container state, target memory and failures;
they do not manufacture daemon-exit evidence from FRR's daemonizing startup.
FRR `target_crash` and target thread controls remain unsupported. The separate
[FRR source workflow](frr-source-workflow.md) adds trusted-local-source builds,
correctness bisection, source-range preparation and source handoffs. The completed
supplied-image pair does not qualify those source interfaces. No automatic image build or acquisition occurs.

Experiment completion and correctness are separate. Inspection/verification exit
success means valid evidence, not a passing daemon. Investigation correctness
checks exit 4 for a selected failure and 5 for inconclusive evidence; candidate-only
checking does not silently accept a missing candidate. Health is a bounded snapshot,
not a proof of continuous liveness. Portable report checksums detect changed
evidence without authenticating that execution occurred. Performance policy remains
disabled, performance qualification unassessed and formal 10% calibration deferred.
