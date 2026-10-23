# Future BGP testing workloads

Created 2026-10-23. Status: retained ideas; explicitly deferred. This is the
public engine's authoritative list of deferred workload directions. It neither
queues implementation nor authorizes experiments. Reopen a family only through
an explicitly scoped design with acceptance criteria.

The immediate priority is the
[developer performance testing plan](performance-testing-development-plan.md):
make existing tests reproducible, diagnosable and useful to daemon maintainers.
Its recipe/result/assertion interfaces should accommodate future families,
without pulling their implementation into that work. See the
[roadmap](../roadmap.md) for the overall sequence.

## Policy: a detailed engine design exists

The [policy engine design](policy-testing-engine-design.md) proposes semantic
ordered rules, equivalent daemon renderers, capability declarations,
attribute-capable generation, route-level observation and phased re-evaluation.
These are proposals, not a claim that current transit/ixp filters implement
that program.

Before reopening: reconcile the proposal against the engine at that time,
choose a small policy subset and target/version set, and establish an exact
route/attribute oracle. Equal total route counts alone do not establish policy
correctness. Start with small semantic conformance fixtures before defining
performance-scale corpora, initial-load scaling, policy-size/match-position
comparisons or re-evaluation over a populated RIB. Campaigns may choose their
own matrices while sharing these public semantics and capability contracts.
The proposed first policy implementation requires IPv4; IPv6 is a separate
expansion.

## IPv6: retained direction, not yet an implementation plan

IPv6 needs coordinated design across prefix/address generation, peering,
observers, MRT playback, daemon adapters and expected-route accounting. This
entry preserves the direction; it is not a staged implementation plan or a
promise of current adapter support.

Retain these design questions for that later plan:

- IPv6-only first, then explicit dual-stack behavior; never silently pool
  address families or compare unlike workloads.
- Addressing/peering, next-hop and capability requirements per role/version.
- Deterministic synthetic input first; IPv6 MRT acquisition/replay and exact
  consumed-input identities as a separate supported path.
- Observer support and expected state by address family, including partial
  failure and withheld measurements.
- Correctness fixtures and tiny adapter checks before performance-scale runs.
- Equivalent corpus and host/resource definitions for any IPv4/IPv6 comparison.

These are planning prompts, not settled semantics. Write the scoped IPv6 design
only when that work is explicitly selected.

## Other retained families

- Best-path changes and path exploration.
- Many paths per prefix and ECMP/multipath.
- AS-path, community, large-community, MED and local-preference changes.
- Route refresh, policy scale and policy re-evaluation.
- Graceful restart and stale-route handling.
- Add-Path and route-reflector topologies.
- RPKI origin-validation mixes.
- Slow-peer and backpressure behavior.

No separate implementation queues are created for these families now. Each
needs explicit stimuli, completion/failure rules, expected state, role/version
capabilities, raw evidence and a comparability contract before implementation.
The [architecture design](architecture-design.md) provides reusable background;
its example schema is directional, not a ready-to-run workload specification.

The general workload directions originated in the August 2026 engine proposal
`07c6ff1b4001976865057f7ed92ca4b4ccc334a1`. Engine workload design is maintained
here; experiments and publication programs built on it can live independently.
