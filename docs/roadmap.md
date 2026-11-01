# bgperf2 roadmap

Updated 2026-11-01 UTC. This is the public index of engine development plans.
Everything needed to understand, use and contribute to bgperf2 belongs in this
repository. Other projects can build campaigns and services on its documented
CLI and versioned artifacts; none is required to use the engine.

## Current direction

Make bgperf2 a performance tester that daemon developers can use to reproduce
problems, test their own fixes and investigate regressions. Reuse existing
batch/scenario inputs, repetitions, ordering, measurement artifacts, provenance,
the hashed Python bootstrap and quality gates. Add contracts and testable
boundaries incrementally while keeping current CLI and output compatibility.

The operator selected descriptive comparisons as the delivered performance
workflow and deferred formal reliable-10%-slowdown calibration. It is not a
release blocker. Performance policy remains disabled and performance bisection
deferred; deterministic correctness bisection remains available. Further work
should address concrete maintainer reproduction/fix/usability needs. A future
calibration effort requires one bounded, separately approved campaign with
predeclared success/stop criteria on a host with predictable capacity. See the
[authoritative decision](plans/performance-testing-development-plan.md#operator-decision-descriptive-comparisons-first--2026-10-31).

The [maintained maintainer walkthrough](maintainer-workflow.md) connects one
simulated crash recipe and source history through reproduction, a local rollback,
interrupted-work recovery and a confirmed correctness boundary. Its public CLI
evidence verifies after relocation. It runs offline with explicitly simulated
source/build/runtime boundaries; it supplies no additional live qualification.

[Maintainer checkout preparation](maintainer-checkout.md) now prepares an explicit
local first-parent range into independent checkouts and plans, verifies selected
object identities, and freezes a baseline/fix handoff with actual future artifact
paths. Its maintained inert-Git example exercises real local preparation while
leaving all build/worker/image/host readiness unassessed. Existing source and
workload boundaries remain; no command in the handoff executes automatically.

The [real BIRD maintainer validation](plans/real-bird-maintainer-validation.md#fresh-hourly-case-functional-validation--2026-11-01-utc)
now covers an adjacent upstream release transition with explicit alias-only
packaging, two successful build commands and three completed functional workers.
The manual admission refusal remains separate. A fresh approved hourly case
passed all twelve assertions, source/package/report checks and recorded cleanup;
candidate compilation reused cache. A lab citation-scope defect blocked original
controller closeout after its final reviewer accepted the evidence. Independent
offline acceptance and measured local preservation support a separate resolution,
retaining that blocked record without rerunning work. Recorded foreign CPU
prevents a quiet-throughout/performance claim. This is bounded functional
compatibility for the adapted source, with no upstream bug/fix, pristine-source
or bisection-boundary qualification.

| Document | Status | Purpose |
| --- | --- | --- |
| [Developer performance testing plan](plans/performance-testing-development-plan.md) | A/B functionally validated; C descriptive workflow delivered, calibrated detection deferred; bounded deterministic D live validation passed | Delivery sequence and acceptance for recipes, local builds, diagnostics, comparisons, assertions and bisection; later minimization |
| [Architecture design](plans/architecture-design.md) | Supporting proposal; reconciled with shipped foundations | Recipe/result records, lifecycle boundaries, observations and compatibility strategy |
| [Future testing workloads](plans/future-testing-workloads.md) | Deferred | Preserve policy, IPv6 and other workload ideas without scheduling their implementation |
| [Policy engine design](plans/policy-testing-engine-design.md) | Deferred | Semantic policy model, conformance, adapter/generator/observer requirements and implementation risks |

Phase 0 ships a Docker-free [recipe/result contract](recipes.md) and public
fixtures. Phase 1a adds offline planning and explicit read-only prerequisite
reports. Phase 1b adds selected-image preparation with explicit digest pulls;
real `prepare --pull` acquisition validation remains deferred. Milestone A
implements isolated recipe execution, verified return packages, failure/stop/cleanup
handling and a maintained simulated fresh-checkout smoke. Its supported synthetic
BIRD/BIRD/sink functional attempt and early-timeout check passed on the development
host under expressly permitted concurrent work. See the
[validation record and limits](plans/milestone-a-runtime-validation.md); this
establishes neither performance/hardware qualification nor live-container timeout
cleanup qualification. Follow the
plan's [feedback-driven execution policy](plans/performance-testing-development-plan.md#feedback-driven-execution):
continue through internal commits until a usable milestone or a concrete operator
decision is ready for review.
Milestone B now adds strict target/build identities, a trusted local-source BIRD
build path, optional bounded diagnostics, partial evidence and verified
baseline/fix reports. The [investigation guide](investigations.md) and maintained
controlled smoke supply a complete feedback workflow; pristine-source and broader
diagnostic qualification remain deferred. Its explicitly authorized supplied-image
BIRD 2.19.2/3.3.2 functional pair passed with basic diagnostics, verified packages
and independently reviewed cleanup. Its approved BIRD 2.19.2 plus packaging-patch
source build/functional pair and live setup-container SIGTERM cleanup also
passed. Pristine-source support and broader target/crash/memory qualification
remain limited; see the
[validation record and limits](plans/milestone-b-runtime-validation.md).
Baseline/candidate comparison now has a separate descriptive milestone C
workflow: [named assertions, repeated serial plans and verified reports](comparisons.md)
retain memory/CPU/timing observations, variation, failures and confounders.
Controlled examples demonstrate known differences, noise and inconclusive
evidence. Calibrated regression policy remains disabled. The operator selected
a 10% slower observer-window planning target. Earlier bounded
[controlled repeatability case](plans/milestone-c-repeatability-validation.md)
attempts stopped for outside CPU or admission/preparation limits; their evidence
remains separate. The subsequently authorized
[queued study and analysis](plans/milestone-c-repeatability-validation.md#queued-repeatability-study-and-analysis-completed--2026-10-29)
completed all 32 workers and 16 same-image pairs with four independent public
review gates and verified preservation. Offline analysis found pair changes
from −11.39% to +20.94%, block/order differences and nonzero background CPU;
original controlled deltas remain withheld. The 10% planning target is not a
single-pair cutoff or a demonstrated detection capability. A balanced validation
design, known-effect positive control, justified statistical rule/sample budget
and fresh held-out confirmation remain before calibration or performance policy
can be enabled. The subsequent [debug-control eligibility case](plans/milestone-c-control-eligibility.md#execution-and-descriptive-outcome--2026-10-30-utc)
completed one cached build and 23 workers before outside CPU permanently stopped
successors. Its three complete optimized/debug pairs had longer observed windows;
the incomplete, confounded screen does not qualify a known 10% control. Nine
workers remain never run. Calibration and performance policy remain pending/
disabled. The completed queued job will not rerun.
The subsequent [background-load diagnostic and analysis](plans/milestone-c-control-eligibility-queued.md#diagnostic04-completed-and-analyzed--2026-10-30)
completed sixteen unique workers/eight balanced optimized/debug pairs with zero
builds, four public reviews and independently verified preservation. Observed
debug windows were longer in every pair (geometric change +72.23%); background
load and instrumentation confounders remain, and this is not a known 10% control
or calibration result. The approved [interleaved noise/control case](plans/milestone-c-control-separation.md#approved-execution-and-partial-outcome--2026-10-30-utc)
stopped at its memory-capacity requirement after twelve completed workers/six
pairs, with twenty workers never run and zero builds. Only one macroblock has
both conditions; one of its two AD brackets exceeds the local AA envelope,
and the full screen remains unassessed. Evidence and partial analysis remain
separate from earlier cases. This case is closed; policy remains disabled.
The approved [hourly case02](plans/milestone-c-control-separation-02-hourly.md)
completed 32 workers/sixteen pairs and sixteen accepted public reviews with
zero builds. All eight AD brackets exceeded their local AA envelopes;
geometric AD change was +78.40%, while AA ranged −14.96% to +10.23%.
The large contrast separates in this sample, but 10% calibration remains
pending and policy disabled. Next preparation requires a quantified small
control, error goals and a justified confirmation budget; no new run is authorized.
The approved [adjustable route-work discovery case](plans/milestone-c-route-work-discovery.md)
completed all four optimized builds, then stopped before its first worker when
available memory fell to 38.40 GiB below the selected 48 GiB launch floor. All 64
worker positions remain never run; no dose effect or nomination is measured.
The four cached images are retained for a separately reviewed fresh zero-build
case. This case is closed; policy remains disabled and calibration pending.
The subsequently approved fresh zero-build route-work case 02 completed two
zero-dose workers before its third worker was interrupted by the selected
sustained CPU/PSI pressure screen. The remaining 61 positions never ran. No
nonzero dose was measured; the incomplete screen cannot nominate a control.
Background CPU was recorded from the first worker; performance policy remains
disabled and calibration pending. See the same route-work record for this
separate partial execution.
Its evidence is now locally preserved with independent full readback. Offline
arithmetic reconstructed a −10.63% change in its sole complete same-image pair;
this describes confounded variation and supplies no nonzero-dose or calibrated
detection result.
The revised two-million-prefix noise/resolution pilot completed all eight A/A
and eight A/B attempts with independent gates and
[observer timing supplements](observer-timing.md). This establishes resolution
for that selected discovery run and makes no performance conclusion. The
[staged execution guide](comparison-execution.md) adds synchronous assessments,
explicit review gates and optional operator-selected pressure monitoring.
[Milestone D deterministic bisection](bisection.md) now supplies bounded local
revision search, build caching, explicit recovery, skipped/ambiguous outcomes,
fresh boundary confirmations and verified portable reports. Controlled histories
validate the workflow. The [bounded live-bisection case](plans/milestone-d-runtime-validation.md#approved-waited-execution-completed--2026-10-26)
confirmed a deliberately introduced local count-fault boundary with three public
builds and five distinct workers, including fresh confirmations. Its record retains
the earlier admission stops, first-trial contention limitation and cached-build
qualification. This establishes no upstream bug or performance result. Broader
source-build/crash-bisection qualification and performance predicates remain deferred.
The offline `recipe_bisection.py status` view now verifies and summarizes search
progress, trial budget, failed checks, evidence paths, pending recovery and
supported boundary conclusions without starting a build or worker.

The architecture proposal is supporting material, not a second execution order.
New policy semantics, IPv6 and protocol/topology expansion remain deferred until
separately selected. A roadmap entry neither implements a feature nor authorizes
an experiment or publication.

## Existing behavior and contribution checks

Use the [README](../README.md) for supported commands and examples,
[measurement definitions](measurement-dictionary.md) for current output semantics,
and [environment guide](python-environment.md) for bootstrap, local hooks and CI.
The [agent/contributor guidance](../CLAUDE.md) indexes the invariant documents
that govern source changes. Proposed behavior in a plan must not be mistaken
for a supported command, result field or capability.

Every change needs appropriate tests and review. Keep normal unit tests free
of live Docker operations, and explicitly select adapter/hardware validation.
Performance comparisons need recorded identities and an otherwise idle,
qualified host; hosted unit-test success does not qualify a measurement host.
No benchmark schedule, infrastructure provisioning or automatic upstream issue
posting is part of this roadmap.

## Maintaining plans

Keep detailed plans in `docs/plans/` and update this index when status changes.
Each plan has one authoritative copy, explicit scope, acceptance criteria and
commit/validation records as work lands. Move completed engine plans to
`docs/plans/completed/` when appropriate and keep their history accessible.
Separate historical evidence and proposals from current documented contracts.

Engine implementation decisions stay with the engine. Deployment-specific
host operations, campaign scheduling, research programs and private evidence
belong to their consuming projects and do not gate public contributions.
