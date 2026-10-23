# bgperf2 developer performance testing plan

Created 2026-10-23. Status: phase 0 complete; phase 1 in progress.
Direction: make bgperf2 a reusable performance tester, with portable public
contracts that other tools can build on.
The operator authorized phase 0 and phase 1a–b prerequisite/preparation implementation on
2026-10-23. This work starts
no daemon builds, benchmarks, provisioning or publication, and changes no host
qualification gate.

## Outcome and ownership

A daemon maintainer who has never used bgperf2 can take a reproduction recipe,
set up its documented prerequisites, run just the required experiment, test a
local fix and return an inspectable result. The same recipe and result contracts
support version comparisons, diagnostics and eventually regression bisection.

The public engine owns recipe validation, dependency resolution, selected image
preparation, execution, build identity, observations, diagnostic collection and
generic comparison interfaces. A public checkout must contain everything needed
to understand, contribute to and use those features. Examples use redistributable
synthetic inputs.

Consumers own deployment-specific host qualification, campaign orchestration,
storage, research interpretation and publication. They consume documented CLI
commands and versioned artifacts; new integrations must not depend on engine
internals or a particular checkout layout. Threshold policies supplied by a
caller must be named and recorded rather than silently embedded in the engine.

## Scope and starting point

Build on the existing batch/scenario inputs, repetitions and ordering, explicit
image overrides, provenance, measurement artifacts, hashed Python bootstrap,
local hooks and hosted CI. The run lifecycle was mechanically extracted at
engine `5ff976f`; its broad runtime compatibility boundary is not yet the staged
failure-handling interface proposed by the architecture roadmap.

Planning baseline: engine `a4b271529478b02076b5c7f8518c63eea0f2c9f4`. This
identifies source inspection, not a measured baseline or an instruction to
execute that revision. See the [roadmap](../roadmap.md) for current priorities.

New policy semantics, IPv6, new protocol capabilities and new topology families
are deferred in the [future workload index](future-testing-workloads.md).
This plan improves testing of workloads the engine already supports. Assertion
and phase interfaces must leave room for future workloads without implementing
them now. No GUI, scheduling service, distributed execution framework or language
rewrite is required for this work.

## Delivery sequence

Each phase is a separate reviewable milestone. Split code into small commits,
keep mechanical refactors separate from behavior changes, and record actual
commit references and validation here when implementation is authorized.
Later phases describe intended operations. The shipped phase 0 interface is
documented in the [recipe contract](../recipes.md).

### 0. Specify the recipe and result boundary

Status: complete locally, 2026-10-23. See the validation record below.

- Specify a small versioned recipe envelope around existing workload inputs.
  Export one fully resolved batch cell first; require explicit selection rather
  than accidentally handing a maintainer the whole matrix. Preserve the source
  definition, selection, normalized values and legacy run identity separately.
- Record engine revision, target/generator/observer identities, input hashes and
  seeds, resource requirements, completion conditions and the question being
  reproduced. A recipe must not conflate failure reproduction with performance
  comparability on different hardware.
- Define a named, versioned result manifest referencing existing event,
  provenance, sample, configuration and log artifacts. Extend existing formats
  incrementally; retain CSV and current batch/scenario compatibility.
- Give downstream callers stable exit/status semantics for setup refusal,
  harness failure, experiment failure, interruption and inconclusive evidence.
  Recipe-specific reproduction outcome is separate: a daemon crash can reproduce
  the reported bug while remaining a failed experiment.
- Treat recipes as declarative data. Reject unsupported fields and capabilities
  before destructive runtime operations. Do not allow arbitrary shell/Python
  hooks in a downloaded recipe. Review explicit local build instructions as a
  separate trust boundary.

Accept: a checked-in small IPv4 synthetic example can be exported, validated
and inspected without Docker or private repositories. Invalid, unsupported or
incompletely pinned inputs receive specific errors. Contract fixtures cover
round trips and compatibility; no benchmark or result definition changes merely
to introduce the envelope.

### 1. Deliver the newcomer reproduction workflow

Status: in progress. Phase 1a's offline plan/read-only prerequisite report and
phase 1b's selected-image preparation are complete locally. Recipe execution
and result production remain pending; real acquisition has not been validated.
Depends on phase 0; first useful public release milestone.

- Provide export, inspect/plan, prepare and run operations over the same recipe.
  One documented entry point guides a newcomer through the workflow after
  prerequisites are satisfied; preserve read-only inspection without execution.
- Check Linux/Python/Docker access, host idleness, CPU/memory/storage needs,
  work-directory suitability, required capabilities and existing artifacts.
  Unknown resource estimates stay unknown. Explain any manual OS prerequisites;
  do not silently run sudo, upgrade the host or provision infrastructure.
- Reuse the existing hashed Python bootstrap. Prepare only the selected target,
  generator and observer images, including required receivers. Never fall back
  to building every supported daemon or silently substitute a floating version.
- Resolve immutable image identities and source/build provenance. A requested
  source commit alone does not prove a reproducible binary when build inputs
  are unlocked; report those limits instead of claiming exact reconstruction.
- Describe downloads and expected sizes before acquisition. Fetch external
  inputs only on an explicit preparation/run path, verify recorded hashes and
  respect redistribution limits. Missing or changed inputs are refusals.
- Keep work/results isolated per attempt and produce a small result summary
  plus a manifest that a maintainer can return. Never overwrite earlier evidence.

Accept: a reviewer starting from a fresh public engine checkout follows only the
recipe instructions and reproduces a small existing workload with the selected
roles. A fake-runtime test proves that unrelated images, private repositories,
notifications and infrastructure services are untouched. Hardware smoke requires
a separately authorized qualified host; a failed prerequisite must leave an
actionable diagnostic, not a partially successful benchmark.

### 2. Make testing local fixes routine

Status: planned. Depends on phase 1.

- Support a target override using a supplied image or an explicitly selected
  source checkout/commit and supported build recipe. Existing image overrides
  are the starting point, not a second independent execution path.
- Record requested and actual source identity, dirty-tree patch identity,
  toolchain/build inputs, compiler flags, image identity and instrumentation.
  Do not modify the maintainer's source checkout or retag an existing result's
  image in place.
- Hold generator, observer and workload identities constant when substituting
  the target. Explain which changes invalidate a comparison.
- Make debug/sanitizer/profiling builds visibly distinct from ordinary builds;
  never present instrumented and optimized timings as an ordinary comparison.

Accept: the same recipe exercises a released target and a locally modified
target, with distinct complete build identities and unchanged workload inputs.
Both supplied-image and supported source-build paths have fake-runtime tests;
real build/adapter qualification is explicitly selected and recorded.

### 3. Make failures and memory behavior diagnosable

Status: planned. Depends on phases 0–1; can proceed alongside phase 2.

- Add bounded lifecycle stages and explicit failure paths for setup, session
  establishment, observation, generator failure, target failure and collection.
  Preserve current timing definitions; new timeouts/cleanup behavior require
  their own changes and acceptance checks.
- Persist useful partial results even if final provenance, graphing or a log
  collector fails. Stop this attempt's samplers and isolate cleanup to its owned
  resources. Preserve failed work for investigation under the caller's retention
  policy; do not add automatic evidence expiry.
- Package generated configurations, raw samples/events, logs, process exits,
  build/host identities and supported crash artifacts with a checksum manifest.
  State missing data and truncation. Do not fetch privileged journals or cores
  silently, leak credentials or redistribute restricted inputs/binaries.
- Define peak and ending memory with explicit accounting boundaries and units.
  Distinguish daemon process, container and logging/cache costs where supported;
  missing measurements stay missing. Growth across repeated existing actions
  requires defined observation points, not a new ambiguous "leak" verdict.
- Offer optional diagnostic capture through adapter capabilities. Record its
  overhead/instrumentation and keep such runs out of ordinary timing comparisons.

Accept: fake-runtime tests cover completion, timeout, stop, dead observers,
generator/target failures and collection/cleanup failures. Every path leaves a
readable status and available evidence. A maintainer can inspect a memory or
crash reproduction without reconstructing the experiment from console output.

### 4. Compare a baseline and a candidate

Status: planned. Depends on phases 0–3.

- Run repeated interleaved comparisons of two target builds on the same
  qualified host, reusing existing ordering/repetition machinery.
- Compare correctness, memory, CPU and timing as separate named measurements.
  Report individual attempts, sample counts, variation, missing/failed attempts
  and relevant host/build/workload differences.
- Keep bug reproduction and performance qualification distinct. An otherwise
  unsuitable timing run can still demonstrate a crash; it cannot supply a clean
  speed comparison. Never treat a missing/failed run as zero or silently drop it.
- Return a generic machine-readable comparison and a concise human report.
  Enable a named regression policy only after calibration supports its effect
  size and repetition requirements. Report inconclusive evidence honestly;
  do not start with a universal percentage threshold.

Accept: controlled fixtures with known differences and confounders yield an
auditable comparison. Separately authorized host trials demonstrate that order,
variance and missing results are represented correctly. Another repository can
consume the comparison without importing plotting or engine implementation code.

### 5. Expose correctness assertions for existing workloads

Status: planned. Build basic recipe outcomes in phase 0; extend after phases 1–3.

- Name observable session, count, health and existing action-completion
  assertions, with capabilities and deadlines. Preserve their evidence alongside
  the result rather than hiding it behind a single success flag.
- Distinguish route-count agreement from route/attribute correctness. If the
  present observer cannot prove an assertion, refuse it or report it unmeasured.
- Generalize sequencing only as required by currently supported actions. New
  policy or recovery experiments, IPv6 and new route-level oracles remain in
  the deferred workload track even if they will later use this interface.

Accept: at least one supported existing workload has an explicit expected
outcome that survives recipe export and rerun. Unsupported assertions cannot
silently become count checks or fixed sleeps. Existing completion/measurement
semantics remain documented and separately tested.

### 6. Bisect reproducible daemon regressions

Status: planned, later. Depends on phases 2–5 and a trustworthy predicate.

- Search an explicitly bounded daemon revision range with the same recipe and
  build contract. Start with deterministic crash/correctness outcomes.
- Cache builds by complete identity, preserve every trial and support resuming
  an interrupted search. Unbuildable, unsupported or inconclusive revisions are
  not classified as good; expose ambiguous boundaries.
- Add performance predicates only after phase 4 supplies calibrated repeated
  comparisons. Report a candidate boundary and its evidence, then confirm both
  sides rather than treating one noisy run as the first bad commit.

Accept: a synthetic revision history with bad, skipped and ambiguous revisions
produces the correct supported boundary or an explicit unresolved range. No
daemon repository is modified and no upstream issue/comment is posted.

### 7. Minimize a reproducer

Status: deferred within this plan until recipes and predicates prove useful.

Reduce selected peers, routes, attributes or input subsets while checking the
same reproduction predicate. Every candidate has its own recipe/input identity.
Preserve the original and report the dimensions searched, budget and unresolved
cases; "smaller reproducer found" is not proof of a global minimum. External
MRT reduction and attribute semantics need explicit support and redistribution
review before inclusion. Performance minimization requires its own stable
predicate, not simply fewer resources.

Accept: controlled fixtures retain a known failure while shrinking an allowed
dimension, without silently changing unrelated workload semantics.

## Validation, decisions and resumption

All implementation needs applicable engine guidance, review and the normal
quality gates. Prefer contract/fake-runtime tests for orchestration. Real adapter
checks, source builds, profiling and hardware measurements require explicit
scope on an idle qualified host. A host awaiting qualification cannot be used
for performance acceptance. Never run development or analysis alongside a
measurement.

No performance acceptance numbers, repetition counts, benchmark schedules or
host purchases are authorized by this document. Public recipe examples must
contain no private evidence paths or credentials. Artifact export must preserve
original evidence and explicitly select what can be shared.

Next development unit, when requested: phase 1c's isolated, one-cell recipe
execution and result production through the existing runtime. Preserve selected
role identities, workload/cell identity and measurement definitions; use fake
runtime tests for execution and failure paths before real host qualification.
Add a maintained, explicitly invoked fresh-checkout smoke entry point once that
workflow exists, keeping real execution separate from the ordinary test gate.
Real downloads, builds and benchmarks still need explicit runtime scope.
Use the
[architecture design](architecture-design.md) for background,
without treating its historical proposed interfaces as current behavior.

Progress record: 2026-10-23, this plan records the operator's priorities. No
engine behavior, measurement definitions or experiments changed. This document
was moved into the public engine on 2026-10-23; that relocation starts no phase. Future entries
must name the phase, implementation commits, review, actual validation and any
deferred checks; phases are not complete merely because their code is committed.

### Phase 0 implementation — 2026-10-23

- `8be6228` mechanically extracts the pure batch cell contract, preserving
  legacy identities and defaults. Independent review compared moved functions
  against their source; the normal commit gate passed 1,866 tests.
- `3878764` adds the Docker-free `recipes.py` export, validate, inspect and
  result-validate commands, versioned recipe/result contracts and public fixtures.
  The first supported subset is one explicitly selected synthetic IPv4 cell
  using BIRD as target and generator and the sink observer. Unsupported fields
  are refused, including in unselected source tests.
- Independent code review covered identity preservation, strict validation,
  canonical hashing, runtime isolation and outcome semantics. Focused contract
  and documentation checks passed 186 tests. Public recipe validation,
  inspection and result validation also passed locally without Docker access.
  The feature commit passed the normal full-suite gate.
- Source text and hash, raw target, resolved workload and legacy identity remain
  separate. Role image pins and the full engine revision are declared immutable
  identities, with no claim that referenced images or revisions exist locally.
  Resource estimates remain explicitly unknown. Reproduction outcomes are
  separate from experiment status and performance qualification.
- Deferred checks: real image resolution, selected image preparation, prerequisite
  qualification, fresh-checkout runtime smoke, result production and artifact
  checksum verification belong to phase 1 or later. No real benchmark, daemon
  build, provisioning, measurement-host access or push occurred. Fixtures declare
  synthetic image identities and do not represent an executed experiment.

### Phase 1a implementation — 2026-10-23

- `6c79203` adds `recipes.py plan` and `check`, documented in the
  [recipe guide](../recipes.md). Offline planning performs no host/runtime
  probes. Explicit checks return a versioned prerequisite snapshot with named
  pass, refusal and unknown observations; they do not qualify execution or
  performance comparison.
- The local check verifies Linux/Python, tools, the clean requested engine
  revision and the existing hashed environment through `bootstrap.py --check`.
  This reuses the active-measurement guard and keeps one Python bootstrap path.
  Docker probes are bounded, local-only and limited to the three selected
  immutable role images. New work/results destinations must be isolated,
  disk-backed and outside the checkout; inspection creates neither directory.
- Independent review covered probe isolation, timeout process-group cleanup,
  immutable image matching, source validation, Git environment isolation,
  destination preservation and report limitations. The 25 focused prerequisite
  tests passed, and the normal full commit gate passed 1,996 tests. The guide
  and invariant mapping passed the documentation checks in that suite.
- Local read-only validation used a temporary in-memory copy of the public
  synthetic recipe bound to `6c79203`'s full revision. Checkout, tools, bootstrap,
  capacity and destination observations passed; each synthetic role image was
  correctly refused as missing. No acquisition occurred and neither prospective
  work nor results directory was created. This validates refusal behavior,
  not an executed workload or a qualified measurement host.
- Deferred: selected image acquisition/preparation, verified build provenance,
  resource estimates, foreign CPU qualification, runtime capabilities, hardware
  qualification, fresh-checkout execution smoke, result production and artifact
  verification. Phase 1's full acceptance remains unmet. No benchmarks, daemon
  builds, provisioning, measurement-host access or pushes occurred.

### Phase 1b implementation — 2026-10-23

- `35cd64e` mechanically extracts shared runtime prerequisites and strict image
  inspection from the existing check path. Independent review found no behavior
  changes; the normal full commit gate passed 1,996 tests.
- `0f6082f` adds `recipes.py prepare`, documented in the
  [recipe guide](../recipes.md). Its default is a local acquisition plan.
  Explicit `--pull` discloses the plan before acquiring only selected missing
  repository digests. Shared references retain every role and are acquired once;
  existing exact images are reused. A missing bare image ID blocks acquisition
  rather than inventing a repository or invoking a build.
- All selected references are classified before mutation. Permission failures,
  timeouts, malformed responses and identity mismatches block all pulls. The
  existing measurement guard runs again before each pull, and the same immutable
  pin is verified afterward. A later failure retains earlier cache progress and
  stops pending acquisitions. The guard remains a snapshot, not a held host lock.
- Pulls use a bounded client process group; timeout, Ctrl-C and foreground
  SIGTERM clean up owned clients. Docker daemon/cache work may continue, and
  interruption does not guarantee a final JSON report. Source/build/binary
  provenance, download sizes and incremental cache requirements stay unknown.
- Independent code review covered the shared extraction, acquisition ordering,
  exact identity verification, disclosure, partial cache outcomes and cancellation.
  The focused contract/documentation suite passed 235 tests; the normal full
  feature commit gate passed 2,029 tests. Fake-runtime tests exercise acquisition
  and failure paths without real Docker mutations.
- Local validation used the maintained export/prepare CLI commands with a
  temporary synthetic recipe pinned to `0f6082f`'s full revision. The read-only
  preparation plan reported the three selected repository digests as missing
  with pull actions, while acquisition and cache changes remained `none`.
  Checkout, tools and the existing bootstrap/measurement guard passed. No registry
  download, build, benchmark, provisioning, measurement-host access or push ran.
- Repeated ad hoc prerequisite/image checks now live in maintained modules and
  CLI commands. The observed Docker missing-image response (exit 1, `[]` stdout
  and an exact error naming the image) is retained as a regression case. The
  temporary checkout/commit orchestration remains development-only; a reusable
  end-to-end smoke command is deferred to the execution workflow above.
- Deferred: real registry acquisition and adapter validation, trusted build and
  binary provenance, resource estimates, complete host/runtime qualification,
  isolated recipe execution, result/artifact production and the fresh-checkout
  smoke. Phase 1's full acceptance remains unmet.
