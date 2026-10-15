# Policy testing engine design

Historical design proposal extracted from the policy testing plan at
07c6ff1b4001976865057f7ed92ca4b4ccc334a1. These interfaces are proposed, not
implemented capabilities. Existing transit/ixp filters remain supported.
The full experimental program and its methodology now belong to
[research](https://github.com/jopietsch/second-looks-labs-research/blob/main/bgp/2026/docs/policy-testing-plan.md)
(private, optional context).

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
tests check native configuration, while P0 checks behavior.

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
  are prerequisites; P1 through P4 are not runnable with the current CLI.
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
