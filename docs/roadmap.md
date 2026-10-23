# bgperf2 roadmap

Updated 2026-10-23. This is the public index of engine development plans.
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
| [Developer performance testing plan](plans/performance-testing-development-plan.md) | Phase 0 complete; phase 1 planned | Delivery sequence and acceptance for recipes, local builds, diagnostics, comparisons, assertions and bisection; later minimization |
| [Architecture design](plans/architecture-design.md) | Supporting proposal; reconciled with shipped foundations | Recipe/result records, lifecycle boundaries, observations and compatibility strategy |
| [Future testing workloads](plans/future-testing-workloads.md) | Deferred | Preserve policy, IPv6 and other workload ideas without scheduling their implementation |
| [Policy engine design](plans/policy-testing-engine-design.md) | Deferred | Semantic policy model, conformance, adapter/generator/observer requirements and implementation risks |

Phase 0 ships a Docker-free [recipe/result contract](recipes.md) and public
fixtures. The next unit is phase 1: the newcomer preparation and run workflow,
beginning with prerequisite checks. Recipe execution is not implemented yet.
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
