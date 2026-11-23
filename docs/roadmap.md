# bgperf2 roadmap

Updated 2026-11-21 UTC. This is the public index of open engine plans and
delivered capabilities. Everything needed to understand, use and contribute to
bgperf2 belongs in this repository. Other projects can build campaigns and
services on its documented CLI and versioned artifacts; none is required to use
the engine.

## Current direction

Make it easy for anyone evaluating BGP implementations to try performance
comparisons across daemons, versions and workloads. The primary entry point is
the README's [benchmark and batch comparison path](../README.md#performance-comparison).
Source investigation, correctness localization and daemon-specific maintainer
guides are advanced options within that broader purpose.

No new feature milestone is selected (2026-11-06). Feature expansion is paused
until a concrete use of the existing comparison workflow identifies the next
usability gap. Descriptive comparisons remain available, performance policy
stays disabled and calibration stays deferred. The milestone status and the
decisions in force are in [engine decisions](decisions.md).

## Open plans

| Plan | Status | Next | Blocked on |
| --- | --- | --- | --- |
| [Maghemite receive readiness](plans/maghemite-receive-readiness.md) | paused | Decide whether to design receive-side loading beyond the 4,096-prefix synthetic ceiling, or close the plan into the recipe guide. | Operator selection of a larger receive-side workload |
| [Exact-prefix maintainer workflow](plans/prefix-maintainer-workflow.md) | paused | Decide whether the completed FRR correctness-localization case satisfies the remaining localization step, then close or rescope. | Operator decision; the upstream BIRD investigation it excludes is paused |
| [Upstream BIRD correctness screening](plans/upstream-bird-correctness-screening.md) | paused | If resumed, resolve the issue 436 evidence limit or select another documented BIRD fix with a supported trigger and witness. | Operator decision to resume |
| [Future testing workloads](plans/future-testing-workloads.md) | paused | When selected, write a scoped design for one family (IPv6 or policy phase 1). | Operator selection of a workload family |
| [Policy phase 1](plans/policy-phase1.md) | in progress | Attach per-block attributes on the BIRD generator and measure their send cost (step 3). | none |
| [Policy testing engine design](plans/policy-testing-engine-design.md) | selected (phase 1 scoped) | Carry out phase 1; later phases stay unauthorized until scoped. | Phase 1 |
| [Engine architecture design](plans/architecture-design.md) | reference | Consult when the next engine seam (typed records, staging or runtime interfaces) is selected. | none |

A plan describes proposed or in-progress work. It never documents a supported
command, result field or capability; the guides below do.

## Delivered capabilities

- [How bgperf works](how_bgperf_works.md): roles, lifecycle and the `bench`/`batch` model.
- [Measurement dictionary](measurement-dictionary.md): legacy CSV column meanings.
- [Native batches](native-batches.md): one durable native batch with interruption recovery.
- [Native throughput](native-throughput.md): native throughput controls.
- [Native MRT performance](native-mrt-performance.md): fixed-input MRT `bench` and `batch`.
- [MRT injection](mrt.md): bgpdump2 replay, input inventory and peer selection.
- [Input-bound MRT recipes](mrt-recipes.md): exact-prefix MRT recipes, profiles, injector and observer corrections.
- [Portable recipes](recipes.md): recipe/result contracts, image preparation and per-adapter scope.
- [Functional validation](functional-validation.md): a small bounded functional check.
- [Observer prefixes](observer-prefixes.md): received IPv4 prefix identity.
- [Observer timing](observer-timing.md): observer delivery timing supplement.
- [Comparisons](comparisons.md): descriptive two-selection comparisons.
- [Comparison execution](comparison-execution.md): staged comparison execution.
- [Investigations](investigations.md): test and diagnose a target change.
- [Bisection](bisection.md): localize a deterministic regression.
- [Source ranges](source-range.md): prepare a local revision range for bisection.
- [Minimization](minimization.md): bounded reproducer minimization.
- [First run](first-run.md): the simulated maintainer first run.
- [Maintainer workflow](maintainer-workflow.md): one problem from reproduction to a regression boundary.
- [Maintainer checkout](maintainer-checkout.md): prepare your own maintainer checkout.
- [Maintainer handoff](maintainer-handoff.md): concrete commands for a selected maintainer problem.
- [FRR maintainer workflow](frr-maintainer-workflow.md): supplied-image FRR scope.
- [FRR source workflow](frr-source-workflow.md): FRR local builds and correctness localization.
- [Artifact storage](artifact-storage.md): shared local artifact storage.
- [Local delivery checks](local-delivery-checks.md): local review and validation receipts.
- [Remote targets](benchmark_remote_target.md): benchmark a remote target.
- [Python environment](python-environment.md): locked bootstrap, hooks and CI.
- [Engine decisions](decisions.md): milestone status and the decisions in force.

The [agent/contributor guidance](../CLAUDE.md) indexes the invariant documents
that govern source changes.

## Contribution checks

Every change needs appropriate tests and review. Keep normal unit tests free
of live Docker operations, and explicitly select adapter/hardware validation.
Performance comparisons need recorded identities and an otherwise idle,
qualified host; hosted unit-test success does not qualify a measurement host.
No benchmark schedule, infrastructure provisioning or automatic upstream issue
posting is part of this roadmap.

## Maintaining plans

- `docs/plans/` holds open plans only. Each starts with a status header:
  `Status`, `Strand`, `Updated`, `Next`, `Blocked on` and `Done when`. Update
  the header and the table above when status changes.
- When a plan is complete, distill its durable contracts, limits and outcomes
  into the guide next to the code, then delete the plan. Do not archive it.
- The deleting commit's message records the plan's final commit SHA, so the
  full text stays reachable through Git history.
- Run records and other measurement evidence belong to the consuming project's
  evidence store, not this repository.

Engine implementation decisions stay with the engine. Deployment-specific
host operations, campaign scheduling, research programs and private evidence
belong to their consuming projects and do not gate public contributions.
