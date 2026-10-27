# bgperf2 roadmap

Updated 2026-10-26. This is the public index of engine development plans.
Everything needed to understand, use and contribute to bgperf2 belongs in this
repository. Other projects can build campaigns and services on its documented
CLI and versioned artifacts; none is required to use the engine.

## Current direction

Make bgperf2 a performance tester that daemon developers can use to reproduce
problems, test their own fixes and investigate regressions. Reuse existing
batch/scenario inputs, repetitions, ordering, measurement artifacts, provenance,
the hashed Python bootstrap and quality gates. Add contracts and testable
boundaries incrementally while keeping current CLI and output compatibility.

| Document | Status | Purpose |
| --- | --- | --- |
| [Developer performance testing plan](plans/performance-testing-development-plan.md) | A/B functional validation; C noise/resolution discovery complete; staged comparisons and deterministic D implemented with controlled validation; performance calibration deferred | Delivery sequence and acceptance for recipes, local builds, diagnostics, comparisons, assertions and bisection; later minimization |
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
evidence. Calibrated regression policy remains disabled pending the separately
selected [pilot and effect-size decisions](plans/milestone-c-calibration-proposal.md).
The revised two-million-prefix noise/resolution pilot completed all eight A/A
and eight A/B attempts with independent gates and
[observer timing supplements](observer-timing.md). This establishes resolution
for that selected discovery run and makes no performance conclusion. The
[staged execution guide](comparison-execution.md) adds synchronous assessments,
explicit review gates and optional operator-selected pressure monitoring.
[Milestone D deterministic bisection](bisection.md) now supplies bounded local
revision search, build caching, explicit recovery, skipped/ambiguous outcomes,
fresh boundary confirmations and verified portable reports. Controlled histories
validate the workflow. A [bounded live-bisection case](plans/milestone-d-runtime-validation.md)
is prepared for fresh authorization; live qualification remains pending.
Broader source-build qualification and performance predicates remain deferred.

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
