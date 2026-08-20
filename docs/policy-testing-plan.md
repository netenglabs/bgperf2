# BGP Policy Performance and Correctness Test Plan

## Purpose

This document turns the policy-testing direction in the architecture roadmap
into an implementable test program. It builds on the existing `transit` and
`ixp` filter tests without treating those tests as a sufficient cross-daemon
policy benchmark.

The program is intended to answer four separate questions:

1. Do equivalent policies produce equivalent route decisions?
2. What is the cost of evaluating policy during initial table load?
3. How does that cost scale with policy size and match position?
4. What is the cost and correctness of changing policy on a populated RIB?

It does not attempt to assign one universal "policy performance" score. Import
filtering, attribute mutation, export processing, and policy re-evaluation are
different operations and must remain separately visible.

## Relationship to Existing Tests

The current tests remain useful as historical and version-comparison workloads:

- no filter, `transit`, and `ixp`;
- 10 peers replaying a pinned full-table MRT;
- 50 peers advertising 100,000 synthetic prefixes each;
- daemon-specific translations of filters derived from the NLNOG filter guide.

They have already demonstrated the main hazards: filters change the expected
monitor count, pre-policy counters are not consistently available, synthetic
routes can accidentally match reserved-prefix filters, and superficially
similar configurations can differ across daemons.

The new corpus must not silently replace those workloads or retroactively make
their results comparable. It introduces named, versioned policy semantics and
inputs designed together so that expected decisions are known before a daemon
runs.

## Required Result Contract

Every policy run must report three kinds of result.

### Correctness

- sessions established at the start and end of the measured phase;
- updates offered by each tester;
- expected and observed accepted routes at the target, where observable;
- expected and observed exported routes at the monitor;
- expected attribute values for sampled or exhaustively checked routes;
- unexpected accepted, rejected, exported, or missing routes;
- daemon crash, session reset, timeout, or received-count regression.

The monitor's total route count is not a sufficient oracle. Counts can agree
while the wrong routes or attributes are present. The policy corpus must provide
an expected route manifest, and the observer must be able to compare route keys
and relevant attributes with that manifest.

### Performance

- phase wall-clock time from a defined stimulus event to the correctness oracle;
- target CPU time and sampled CPU utilization during that phase;
- target peak and ending resident memory;
- tester completion time and offered update rate;
- observer processing time or backlog indicator;
- for dynamic tests, time to first correct change and time to complete state.

Cold-start policy time includes parsing configuration, session establishment,
and route processing unless the lifecycle can measure those stages separately.
It must not be described as pure filter evaluation time.

### Qualification

- tester error or timeout;
- target or observer failure;
- foreign CPU contention;
- low free memory or swapping;
- generator- or observer-limited execution;
- missing route-level oracle data;
- unsupported or weakened policy translation;
- missing immutable image or input identity.

A run with a correctness mismatch is `failed`. A run without enough evidence to
evaluate correctness or identify the limiting component is `inconclusive`, not
slow or successful. Performance comparisons use only correctly completed runs
accepted under the same named qualification policy.

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

## Deterministic Route Corpus

Policy scaling tests use generated routes with a checked-in manifest generator,
seed, and schema version. The generated corpus must avoid special-use address
space unless matching it is the purpose of the test. IPv4 is the only required
address family for this plan.

Each route has a stable ID and records:

- NLRI;
- source peer;
- AS path;
- standard and large communities;
- MED;
- the expected decision and output attributes for every policy profile.

The controlled corpus advertises each NLRI from exactly one tester. This avoids
best-path selection and path hiding changing the policy oracle. Multipath and
overlapping-NLRI policy tests require a later corpus with an explicit path-level
oracle. Route identity is the normalized IPv4 prefix; AS paths are normalized as
ordered ASN sequences and communities as unordered sets before comparison.

Use mutually exclusive route classes so each rule's contribution is auditable:

| Class | Share | Intended match |
| --- | ---: | --- |
| control | 40% | no explicit rule; reaches default action |
| prefix | 15% | prefix-set rule |
| AS number | 15% | AS-path membership rule |
| path length | 10% | long-path rule |
| community | 10% | standard-community rule |
| large community | 10% | large-community rule |

For combined policies, precedence fixtures deliberately match two rules. These
fixtures are separate from the mutually exclusive performance population and
verify first-match, continuation, and attribute-mutation behavior.

The generator must validate before execution that the realized class counts and
expected accepted/exported counts exactly match the manifest. The same manifest
is used for every target. Daemon-native route display is diagnostic evidence;
it is not the source of the expected answer.

Real MRT data remains a realism check, not the primary correctness corpus. MRT
runs must use a pinned file and a precomputed classification manifest. If route
attributes cannot be replayed consistently by the selected tester, the affected
policy family must be omitted rather than approximated silently.

## Workload Families

### P0: Translation Conformance

Purpose: prove that adapters implement the semantic model before measuring it.

- 2 peers and 200 routes;
- at least two positive, two negative, and two boundary cases per rule;
- precedence and default-action cases;
- exact route and attribute comparison;
- no performance conclusion.

Every semantic match/action/flow-control operation used by a policy profile must
pass P0 for a target/version before that profile's performance rows are eligible.
Generated native configurations are retained as artifacts.

### P1: Single-Dimension Cold Start

Purpose: isolate the scaling cost of one match type.

Fixed workload:

- 10 peers;
- 100,000 total distinct NLRIs, evenly distributed across peers;
- 50% accepted and 50% rejected;
- unlimited input only after calibration shows the tester is not the bottleneck;
- set cardinalities of 10, 100, 1,000, and 10,000 entries where supported.

Run separate profiles for prefix entries, AS-path membership, standard
communities, and large communities. Path-length comparison is a constant-size
profile and is not presented as an entry-count scaling test.

An entry is one exact member of the relevant prefix, ASN, or community set. Test
routes reuse matching members according to a deterministic balanced
distribution, so a 10-entry set can still classify 50,000 routes. Prefix members
are non-overlapping ranges of equal width; the semantic match remains membership
in the set rather than one native rule per covered prefix.

Set-cardinality tests do not claim to measure rule order: native daemons may use
tries, hashes, compiled regexes, or other structures. Add a separate ordered
rule-chain subtest, where supported, with 10, 100, and 1,000 semantically
distinct terminating rules. For each chain length, generate two variants:

- `early`: matched entries are in the first decile of an ordered linear policy;
- `late`: matched entries are in the last decile.

Only call these variants early and late when the adapter preserves the specified
rule order and P0 proves first-match behavior. Otherwise mark the rule-chain
subtest unsupported; the daemon may still participate in set-cardinality tests.

Controls are no policy and an accept-all policy. The no-policy comparison shows
total feature overhead; accept-all helps distinguish attaching policy from
evaluating a populated rule set.

### P2: Mixed Import Policy

Purpose: represent a moderate operational import policy without claiming that
one universal network policy exists.

The versioned `mixed-import-v1` profile contains, in order:

1. reject explicit forbidden prefixes;
2. reject AS paths containing forbidden ASNs;
3. reject paths longer than the configured limit;
4. reject routes carrying a discard community;
5. tag a selected customer class with a standard community;
6. set local preference for a selected peer class;
7. accept the remainder.

Run with 10 peers and 100,000 total routes, then 50 peers and the same total
route count. Holding total routes constant isolates peer-count effects. A later
capacity experiment may increase total routes, but must be reported separately.

### P3: Import and Export Composition

Purpose: measure two policy stages and verify exported attributes.

Use the P2 import policy, then apply `mixed-export-v1` toward the monitor:

- reject routes tagged no-export-to-monitor by the import stage;
- add an origin-identifying community;
- set MED by source class;
- accept the remainder.

The expected manifest describes both the target's post-import RIB and the
monitor's post-export view. This workload requires observation of route identity
and attributes at both points. If target RIB inspection cannot be implemented
reliably for a daemon, the run may test end-to-end output but is marked as
partial-oracle and is not used to localize an error to import or export.

### P4: Policy Replacement and Re-evaluation

Purpose: measure policy changes after a stable table is installed.

Sequence:

1. establish sessions and install the corpus under `dynamic-a-v1`;
2. verify the initial manifest and observe 10 seconds with no route delta after
   the last correct observation;
3. record the monotonic timestamp immediately before issuing the policy-change
   command and the timestamp when that command returns;
4. replace it with `dynamic-b-v1` using the daemon's supported transactional or
   reload mechanism;
5. trigger route refresh or soft re-evaluation if the daemon requires it;
6. verify the final route and attribute manifest without resetting sessions;
7. restore `dynamic-a-v1` and verify reversibility.

The A-to-B transition changes known, disjoint populations: 10% accepted to
rejected, 10% rejected to accepted, and 10% retained with changed attributes.
Report these populations separately.

Configuration parse/apply time, route re-evaluation time, and export convergence
time are separate clocks when observable. Command return does not necessarily
mean that the daemon has applied the policy. The primary portable metric is from
the pre-command timestamp to the first correct monitor state. That state is
accepted as complete only if the following 10-second quiet period has no route
delta; the quiet period is not included in the metric. Also report command
duration. The observer's polling or event timestamp resolution must accompany
the result. Runs that reset BGP sessions do not belong in the no-reset
comparison; they form a separately labelled reload strategy.

### P5: Pinned-MRT Realism Check

Purpose: determine whether conclusions from the controlled corpus survive a
real attribute and prefix distribution.

- 10 peers replaying the campaign's pinned MRT file;
- no policy, existing `transit`, existing `ixp`, and `mixed-import-v1` only when
  its required attributes survive playback;
- precomputed per-peer offered paths and expected exported route identities;
- no policy-size sweep.

This workload preserves continuity with the first filter tests. It does not
replace P1 through P4 because the natural hit rates are uncontrolled.

## Execution Matrix and Repetition

Do not run the Cartesian product initially. Promote cells through these gates:

1. P0 on one current stable version of each supported daemon.
2. P1 set-cardinality tests at 10 and 1,000 entries, three repetitions, to
   validate instrumentation. Run rule-chain tests as a distinct matrix.
3. P2 and P3, three repetitions.
4. P4, five A-to-B-to-A cycles or five fresh runs if repeated in-process cycles
   show state carry-over.
5. Expand P1 to 100 and 10,000 entries and to older/default versions only after
   the calibration review.
6. Run P5 last because MRT playback is expensive and less diagnostically clean.

For three initially eligible daemons, the P1 calibration gate is 90 measured
runs: 24 populated-policy runs per daemon (four match families, two
cardinalities, and three repetitions), plus six shared-control runs per daemon
(two controls and three repetitions). This assumes the controls use the same
corpus and need not be repeated per match family. Any extra corpus or profile
variant requires a separately stated matrix and a recomputed run count. This
budget is a planning check, not permission to run benchmarks concurrently.

Interleave target order within a workload and record cold versus warm execution.
Use medians and a dispersion measure; retain every individual run. Do not claim
a regression threshold until the calibration set establishes variance and the
minimum effect worth detecting.

The initial target set is BIRD, FRR, and OpenBGPD versions that pass P0. RustyBGP
joins individual profiles only when its route accounting and required policy
features pass the same contracts. Unsupported cells are recorded as
`unsupported` with a reason, not omitted or failed.

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

## Analysis Rules

- Compare only runs with the same corpus, semantic policy version, policy size,
  hit distribution, action mix, lifecycle strategy, hardware profile, and
  qualification policy.
- Report absolute results before ratios. A filtered run doing less downstream
  work can finish sooner while spending more CPU per offered route.
- Normalize CPU by offered updates only as a secondary measure; retain total CPU
  and wall time because policy actions and exports change work performed.
- Do not rank daemons across cells with unsupported or weakened semantics.
- Separate import-only, import-plus-export, and re-evaluation conclusions.
- Treat native implementation differences as explanatory evidence, not grounds
  for changing the semantic workload after seeing results.
- Publish correctness mismatches and inconclusive runs, but exclude them from
  performance rankings.

## Acceptance Criteria

The second-generation policy program is ready for comparative publication when:

- the policy schema and corpus generator are versioned and documented;
- at least two daemon families pass P0 for a common profile;
- expected route identities and attributes are checked automatically;
- tester and observer ceilings are calibrated for the selected cells;
- repeated runs establish variance;
- every published row includes native config, input identity, image identity,
  raw evidence, findings, and a named qualification verdict;
- the report states unsupported features and translation limitations; and
- another operator can reproduce the accepted cells from saved definitions.

## Explicit Non-Goals

The first implementation does not include IPv6, RPKI validation, extended
communities, regex-language equivalence, route-reflector or route-server
topologies, Add-Path, graceful restart, or multi-host execution. These are
separate workloads with additional correctness and capability requirements.
RPKI in particular requires a controlled validation-state source and must not be
represented as an ordinary static prefix or AS-path list.

The plan also does not estimate policy-only nanoseconds per rule. Containerized
end-to-end measurements can support operational comparisons, scaling curves,
and regressions, but they cannot isolate an internal evaluator without daemon
instrumentation.
