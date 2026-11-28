# Policy testing engine design

Status: phase 1 delivered; later phases not selected
Strand: 6 Test capabilities (IPv6, BGP policy, new workloads)
Updated: 2026-11-27
Next: When a later phase is selected, write its scoped design with acceptance criteria.
Blocked on: operator selection of a later phase
Done when: Semantic policy rules render equivalently for selected daemons and a route-level oracle verifies them on a controlled corpus.

Status: long-range proposal. Policy work was selected on 2026-11-21, and only
phase 1 was scoped for implementation. It was delivered on 2026-11-27 (below).
Everything else here reopens only through its own scoped design and validation decision; the current priority is the
delivered A–D workflow summarized in [engine decisions](../decisions.md).
See [future workloads](future-testing-workloads.md) for the deferred families.

## Phase 1, delivered: import-policy cost on initial table load

Phase 1 measures what a generated import policy costs BIRD and FRR while they
load a table, through `bench --policy-rules/--policy-match/--policy-hit` and
the matching `batch` axes. It measures performance, not correctness: an exact
accepted count is its only guard, against unequal work. The contracts are in
[workload controls](../invariants/workload-controls.md), and the live
qualification is in [engine decisions](../decisions.md). The phase plan was
deleted when it completed, and Git history keeps it.

Phase 1 excluded these, and each needs its own scoped phase:

- policy correctness: no per-route oracle and no attribute verification;
- attribute-modifying actions (MED, local preference, community edits),
  continue semantics, export policy, and mixed match types in one policy;
- a policy change on a populated table (`--policy-reload-blocks` covers BIRD
  alone);
- MRT corpora, IPv6, mixed prefix lengths in one run, and lengths other than
  24 and 32.

Candidate next phases, none authorized:

- attribute-modifying actions, cost only, once a daemon-side witness confirms
  that the action was applied;
- policy reload and re-evaluation across BIRD and FRR, unified with
  `--policy-reload-blocks`;
- large communities (once both renderers and the generator support them),
  regex AS-path matches, and mixed match types;
- further renderers (OpenBGPD, RustyBGP, rustbgpd, Holo, …) within each
  adapter's scope;
- why FRR 10.7 takes about 70 times longer with `as-path`/`last` at 1,000
  rules (276 s against about 4 s), which phase 1 recorded but did not explain.

Adapted from the policy engine proposal at
`07c6ff1b4001976865057f7ed92ca4b4ccc334a1`, preserved in engine
`5a082b9eefcbd3b1ce0fc97f9d7fc4e36e2e95a8`. The semantics and proposed engine
interfaces below are self-contained. Campaign-specific corpora, parameter
matrices and publication programs are separate consumers of those interfaces.
Existing transit/ixp filters and the BIRD reload workload do not establish
implementation of this broader policy program.

## Semantic Policy Model

Policy definitions are implementation-independent ordered rules. Each rule has:

- a stable rule identifier;
- zero or more match conditions;
- an action;
- an explicit continue-or-terminate behavior;
- an expected set of matching route IDs in each corpus.

The first schema needs only these matches:

- exact prefix and prefix range;
- AS-path contains ASN;
- AS-path length comparison;
- standard community membership;
- large-community membership.

The first actions are:

- accept;
- reject;
- set local preference;
- set MED;
- add or remove a standard community;
- add or remove a large community.

Regex syntax must not be used as the cross-daemon semantic definition. If an
adapter implements `AS-path contains ASN` with a regex, adapter contract tests
must prove boundary behavior for the beginning, middle, and end of a path and
must reject substring matches such as ASN `123` matching `1234`.

Each adapter must render this model into native configuration or declare the
specific match/action unsupported. A translation that changes ordering,
termination, default action, address family, or attribute scope is not
equivalent and cannot participate in the corresponding comparison.


## Implementation Work

### 1. Policy and corpus schema

Add versioned data structures for semantic rules, route records, expected route
manifests, and capability requirements. Reject invalid or unsupported plans
before starting containers.

### 2. Adapter renderers and contract tests

Move benchmark policy definitions out of opaque, hand-maintained snippets for
new workloads. Each daemon adapter renders the same semantic input. Fixture
tests check native configuration; small behavioral conformance tests must also
prove route decisions, attributes, ordering and default actions before any
policy performance comparison is accepted.

### 3. Attribute-capable generator

Extend or select a tester that can deterministically attach AS paths,
communities, large communities, and MED, control update rate, replace or
withdraw selected routes, and report offered-update completion. Calibrate its
maximum rate independently.

### 4. Route-level observer and oracle

Collect monitor routes and relevant attributes in a structured form. Compare
them with the expected manifest using set differences, not only totals. Use
bounded sampling only after exhaustive validation shows that full collection is
the bottleneck; sampled runs cannot prove full correctness.

### 5. Phased lifecycle

Implement explicit establish, advertise, verify, change-policy, re-evaluate,
verify, and restore phases. Persist timestamps and evidence for every phase.
Completion policy consumes observations; it must not infer success from a fixed
sleep.

### 6. Capability declarations

Record per target/version whether it supports each match, action, reload method,
route refresh behavior, structured target-RIB inspection, and session-preserving
re-evaluation. Capabilities are verified facts with evidence, not assumptions
based only on daemon family.

### 7. MRT oracle builder

Parse the pinned RIB into normalized paths, apply the semantic policy with a
reference evaluator, and model the target's deterministic best-path selection
only for attributes represented by the input and common target contract. Validate
the builder against small hand-worked fixtures. If equal paths or daemon-specific
tie breakers can change the exported NLRI set, classify the affected MRT cell as
count-and-subset validation or omit it from cross-daemon correctness comparison.


## Implementation Risks and Required Decisions

- The present `filter_test` option selects only opaque `transit` or `ixp`
  snippets. The new schema, renderers, generator, observer, and phased lifecycle
  are prerequisites; the broader policy workload families described here are
  not runnable with the current CLI.
- Local preference is normally meaningful inside the target and is not exported
  as a BGP attribute. A profile that mutates it needs target-RIB inspection or a
  controlled competing-path test; monitor-only observation cannot verify it.
- A monitor sees only paths the target selects and exports. The controlled
  unique-NLRI corpus avoids this ambiguity; MRT does not, so its oracle is a
  distinct implementation problem.
- Large-community support, policy continuation semantics, and session-preserving
  re-evaluation must be verified per version. A convenient native approximation
  is not an equivalent implementation.
- Exhaustive route dumps can perturb the target or observer. Correctness may be
  verified after the timed quiet point, but the timed completion signal still
  needs a low-overhead route-delta or digest mechanism whose collision and
  freshness properties are documented.
- Applying policy by file reload, management CLI, and transactional API are
  operationally different. Compare like mechanisms where possible and always
  report the mechanism as a workload dimension.
