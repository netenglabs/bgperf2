# bgperf2 developer performance testing plan

Created 2026-10-23; updated 2026-10-27. Status: milestones A and supplied-image B
functionally validated, including B's approved packaging-source functional and
setup-container interruption checks; C noise/resolution discovery completed; staged comparison
safeguards and deterministic milestone D implemented, including one bounded live
count-fault bisection with fresh confirmations. Pristine-source/source-bug-fix,
broader live bisection/diagnostics and performance calibration remain deferred. See the
[comparison guide](../comparisons.md) and [bisection guide](../bisection.md).
The [bounded milestone D validation record](milestone-d-runtime-validation.md)
confirms the deliberate local count-fault boundary with three public builds and
five serial workers. It retains earlier admission stops, the first-trial load
monitor limitation, observed contention, cached compilation and independent
reviews. All runtime authorizations are consumed; no performance policy is enabled.
The operator selected a 10% observer-window slowdown planning target. The approved
[controlled repeatability case](milestone-c-repeatability-validation.md) completed
one optimized build and its first worker, then permanently stopped for outside
CPU above its selected cap. No pair completed; statistical detection is unvalidated.
Direction: make bgperf2 a reusable performance tester, with portable public
contracts that other tools can build on.
The operator authorized phase 0, phase 1a–b prerequisites/preparation and complete
milestone A implementation on 2026-10-23. This work starts
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

## Feedback-driven execution

Execution policy updated 2026-10-23: work in complete user-facing milestones.
The technical phases below remain the scope, dependency and acceptance map;
individual commands, helper extractions and commits are internal work units.
They are not routine handoff points to the operator.

When asked to continue or do the next step, advance the current execution
milestone through all remaining authorized implementation, independent review,
tests, documentation and progress recording. Keep changes reviewable in separate
commits and continue after each commit. There is no fixed commit or substep limit.
Use parallel implementation and review where the work is independent. Routine
implementation choices and fixable test failures do not need operator feedback.

The operator reiterated this policy at the milestone C continuation: complete
larger steps, use subagents with appropriate models/effort for independent work,
and ask for advancement only when a necessary decision or authorization remains.
Internal commits and ordinary review fixes are not operator handoff points.

Pause when the operator can make a concrete decision: review a usable workflow
or report, choose a new daemon/reproduction case, resolve a material compatibility
or measurement-definition tradeoff, or authorize a specified runtime validation.
Prepare the implementation, examples, test evidence and proposed validation
commands before that handoff. Identify the exact decision, recommended choice,
alternatives and remaining work; do not hand back an unfinished internal slice
merely because its tests pass. A blocking runtime check must not stop independent
implementation and fake-runtime validation that can still be completed safely.

Existing execution restrictions still apply. Real downloads, source builds,
benchmarks, host access, provisioning and publication require their applicable
authorization; this execution policy grants none. Keep implementation ready for
feedback distinct from runtime qualification. A milestone whose hardware or
adapter acceptance checks are deferred is not fully accepted.

| Execution milestone | Complete before the feedback handoff | Operator feedback or decision |
| --- | --- | --- |
| A. Usable newcomer reproduction workflow — functionally validated; ready for feedback | Finish phase 1: run one supported recipe through the existing runtime with exact role identities, isolated attempts, result/artifact production and verification, actionable failures, public instructions and a maintained fresh-checkout smoke entry point. Include the timeout, interruption, owned-resource cleanup and partial-result handling needed for this workflow, plus the existing completion/reproduction outcomes. Exercise the complete workflow with fake runtimes and review it end to end. | Review the actual CLI walkthrough and returned result package. Present an exact, bounded real-image/qualified-host smoke proposal for authorization. Select the next daemon or concrete bug when that choice affects the following milestone. |
| B. Test and diagnose a local fix — supplied-image functional pair validated | Complete phases 2–3 and the existing-workload assertions needed from phase 5: supplied-image/local-source target overrides, recorded build differences, useful crash/memory diagnostics and preserved partial evidence. Deliver one coherent baseline/fix investigation using controlled fixtures and the selected adapter. Keep generator, observer and workload identities fixed. | Review the reproduction/fix report and diagnostic usefulness. Decide any remaining source-build trust, instrumentation or adapter choices that affect real validation. |
| C. Trustworthy baseline/candidate comparison — implementation reviewed; calibration deferred | Complete phases 4–5: repeated/interleaved comparisons, explicit existing-workload correctness assertions, separate memory/CPU/timing results, missing/failed attempts and confounders, machine-readable output and a useful human report. Include controlled differences, noise and inconclusive examples. | Review comparison outputs and a concrete calibration proposal. Select acceptable effect sizes, measurement budget and any regression policy before calibrated performance verdicts are enabled. |
| D. Automated regression localization — bounded live count-fault case validated | Complete phase 6 for supported deterministic predicates: bounded revision search, identity-based build caching, resume, skipped/ambiguous revisions and confirmation evidence. Keep performance bisection conditional on milestone C's calibration. | Review the resulting revision boundary and evidence; decide whether to prioritize broader daemon support, calibrated performance bisection or the separately deferred minimization work. |

Milestone A includes only the lifecycle robustness and assertions necessary for
a reliable first reproduction workflow. Full diagnostic capture and generalized
assertion interfaces remain in B/C. Phase 7 minimization, policy, IPv6 and other
new workload families remain deferred until explicitly selected.

## Technical delivery sequence

Each phase supplies acceptance criteria within the execution milestones above.
Split code into small commits,
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

Status: complete for the supported synthetic BIRD/BIRD/sink functional workflow
and the explicitly authorized concurrent-work validation scope. Offline
prerequisites, selected preparation, isolated execution, packaging/verification
and the maintained simulated fresh-checkout smoke are implemented. The real
functional attempt and early-timeout check passed; see the
[validation record and limits](milestone-a-runtime-validation.md). Real
`prepare --pull` acquisition, performance/hardware qualification and broader
adapter/diagnostic checks remain unassessed.
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

Status: implemented locally for BIRD with controlled fixtures. The supplied-image
and explicit local-source paths, identity records and investigation CLI are
reviewed and tested. The supplied-image pair and approved BIRD 2.19.2 plus
packaging-patch real build/functional pair passed. Pristine-source support,
actual source-bug-fix and broader adapter qualification remain deferred in the
[milestone B record](milestone-b-runtime-validation.md). Depends on phase 1.

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

Status: implemented locally for the supported BIRD recipe workflow. Scoped
stages, optional diagnostics, host/build identities, memory accounting and
partial evidence have fake-runtime coverage. Basic diagnostics passed in the
supplied-image and packaging-source functional pairs. The approved SIGTERM check
also passed with live setup generator/observer containers, before target startup;
broader target-interruption/crash/memory diagnostic qualification
remains deferred. See the [public guide](../investigations.md) and
[validation record](milestone-b-runtime-validation.md). Depends on phases 0–1.

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

Status: implemented and independently reviewed for the supported synthetic
recipe. Repeated serial plans, descriptive reports and controlled fixtures are
documented in the [comparison guide](../comparisons.md). Real noise/resolution
discovery completed; the controlled repeatability case stopped after its first
worker. Completed repeatability and calibrated regression policy remain
pending/disabled. Depends on phases 0–3.

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

Status: implemented for supported synthetic session, injection, exact observer
count, experiment completion and final container-health witnesses; independently reviewed.
Bound assertion specifications and outcomes preserve unsupported or missing
observations. Route/attribute, new action and broader workload oracles remain
deferred. See the [comparison guide](../comparisons.md).

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

Status: implemented for the existing observable assertions and captured-target
crash predicates; controlled Docker-free validation plus the
[bounded live count-fault search](milestone-d-runtime-validation.md#approved-waited-execution-completed--2026-10-26).
Broader live source-build/crash/recovery qualification and performance predicates
remain deferred. See the
[bisection contract and walkthrough](../bisection.md).

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

Current handoff: the bounded D live case confirmed its deliberately introduced
revision boundary and both fresh confirmations; review its
[evidence and limits](milestone-d-runtime-validation.md#approved-waited-execution-completed--2026-10-26).
The B supplied-image and packaging-source cases remain accepted in their
[validation record](milestone-b-runtime-validation.md). C calibration remains
pending: its [discovery history](milestone-c-calibration-proposal.md) is complete;
the [controlled repeatability record](milestone-c-repeatability-validation.md)
records the selected 10% target, first-worker stop and remaining statistical/policy
decisions. Broader daemon/source/crash validation
and minimization are separate selections. No further host trial or performance
policy activation is implied by these completed functional cases.

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

### Execution milestone decision — 2026-10-23

The operator requested larger execution batches organized around points where
their feedback is needed. The feedback-driven execution policy above replaces
the earlier command-by-command handoffs. Completed phase 0/1a/1b records and
commit references remain unchanged. The next continuation targets the complete
remaining newcomer workflow and a reviewable runtime-validation proposal.
This is a planning change; no runtime execution or new workload is authorized.


### Milestone A implementation and feedback handoff — 2026-10-23

- `049fbbf` completes the authorized newcomer implementation: `recipes.py run`,
  exact BIRD/BIRD/sink role pins, isolated work/results and runtime names, a
  bounded worker around the existing engine lifecycle, label/ID-owned resource
  cleanup, result generation and `result-verify`. Legacy measurement definitions,
  convergence, bench and batch behavior remain unchanged.
- The controller holds a cooperating-user host lock across prerequisites and
  execution; timeouts, Ctrl-C/SIGTERM, stopped roles, missing rows, cleanup and
  collection failures have explicit status handling. Partial evidence is retained.
  A target's abnormal container exit is a container-level crash witness, not
  diagnosis of a daemon crash inside a still-running container. That unsupported
  case remains bounded by timeout and inconclusive without evidence.
- Packages contain a canonical recipe, summary, available raw work artifacts,
  checksums and explicit missing kinds. Unsafe artifacts and traversal failures
  are recorded; lost reproduction evidence becomes inconclusive. Verification
  rejects changed, missing, unlisted, symlink and nonregular artifacts. Streaming
  copying/hashing avoids loading whole logs into memory.
- `scripts/recipe_smoke.py --output ABSOLUTE_NEW_DIRECTORY` exercises all nine
  public CLI operations with allowlisted simulated probes and a fake execution
  backend. An additional test drives the worker bridge through the actual
  existing lifecycle with queued fake adapters/observations. These are distinct
  checks; neither is real runtime or hardware acceptance.
- The maintained smoke also passed from a fresh detached checkout of `049fbbf`
  using the existing locked Python environment. All nine CLI operations completed,
  the independently invoked result verifier passed, and the checkout remained
  clean. Its retained summary explicitly identifies simulated completion and
  leaves comparison unassessed.
- Independent subagent reviews covered runtime isolation, image pinning, existing
  lifecycle integration, failure/stop/cleanup behavior, package completeness,
  safe verification and the public walkthrough. Findings about partial
  collection, lost evidence, FIFO manifests and coverage were fixed and tested.
  The final focused recipe/documentation suite passed 297 tests. The feature
  commit's normal locked-environment/idle guard and full Docker-free test gate
  passed all 2,097 tests.
- Existing locked Python 3.14 packages were copied into the local worktree; no
  dependencies were installed. Read-only local image inspection informed the
  [bounded runtime proposal](milestone-a-runtime-validation.md). It found an
  existing BIRD image and no sink image, so sink supply/build authorization is
  explicitly separated from experiment execution.
- No real image download, source build, benchmark, provisioning, 9950 access,
  push, publication or remote evidence transfer occurred. Hardware acceptance
  remains unmet; milestone A is ready for workflow/package feedback, not fully
  accepted as a qualified performance experiment.

Feedback decision: review the [CLI walkthrough](../recipes.md#run-and-return-one-attempt)
and a locally generated simulated package, then choose whether to authorize the
[runtime proposal](milestone-a-runtime-validation.md). Recommended scope is one
functional 1-peer/100-prefix attempt with a 120-second worker budget and an
optional separate timeout-path attempt, after the missing sink image and host
suitability are explicitly resolved. Keep BIRD as the first adapter; no new
daemon or bug selection is necessary to finish A's runtime acceptance. Milestone
B remains unstarted pending feedback and an explicitly selected investigation.


### Authorized functional validation and socket collection fix — 2026-10-23

The operator authorized sink-only acquisition/build and functional checks on
`jpietsch-server` alongside ordinary work. The active-benchmark exclusion remained;
resource guards passed, and the root-backed disk exception was explicit. This
superseded the proposal's idle-host requirement only for functional validation.

At `7b2d502`, the sink build and one real experiment completed: the exact pinned
BIRD target/generator delivered 100 prefixes against the existing 99-prefix
completion checkpoint, with no tester errors/timeouts, using the newly built
immutable sink. Owned runtime cleanup passed and unrelated container/network
identities were preserved. End-to-end packaging failed on the tester Unix
control socket, returning `harness_failed` with a verifiable partial package.
The driver stopped; no automatic retry or real timeout trial followed.

`3165af2` records socket endpoints as checksummed omissions without reading them;
`8e9ed9b` also proves ordinary control-named files remain evidence. Independent
review and 32 package tests passed; the normal full locked Docker-free gate
passed 2,101 tests. Offline replay of the corrected packager on the preserved
work produced a new verified package, matching all 23 original regular files and
preserving both original work and the original failed package unchanged. It
retains distinct execution and packaging revisions and is not a fresh run.

The [runtime validation record](milestone-a-runtime-validation.md) owns exact
engine/image identities, evidence paths, checksum/coverage verification,
limitations and the bounded new authorization proposal. Fresh end-to-end
execution with the socket fix and the real timeout trial remain unaccepted.
CPU/memory/timing observations under concurrent load are unsuitable for
performance interpretation. No 9950 access, provisioning, push, publication,
remote evidence transfer or evidence removal occurred. The sink build cache
and nonrunning intermediate containers remain; no broad cleanup was performed.

Next handoff: review the corrected package and authorize, if desired, exactly
one new functional attempt plus the conditional timeout trial, reusing existing
images with no further downloads or builds. The original stop-on-failure rule
prevents treating the prior authorization as permission for a benchmark retry.


### Fresh end-to-end and early-timeout validation passed — 2026-10-23

The operator separately authorized one fresh functional attempt with a 120-second
worker budget and, only after success, one 0.01-second early-timeout attempt.
Both ran exactly once at clean `73fed28`, reusing the existing pinned images with
no downloads/builds. Ordinary concurrent work and root-backed disk storage
remained explicitly accepted for functional use; no performance comparison or
hardware qualification is claimed.

The functional attempt completed, delivered all 100 prefixes under the existing
completion contract, recorded zero tester errors/timeouts and returned a verified
26-artifact package without offline repair. All 23 source regular files matched;
the control socket was retained in work and explicitly recorded as omitted from
portable evidence. The timeout attempt returned the expected `inconclusive` /
exit 5 and verified 6-artifact partial package; all 4 source files matched and
missing observations had explicit reasons. It stopped before generated
configuration or observed container activity, so live-container timeout cleanup
remains unqualified. Fake-runtime coverage of that path remains separate.

Independent evidence review passed exact image/engine provenance, raw completion,
status separation, socket handling and full copy coverage. All 71 baseline
container identities/states/mount sets and all network IDs were unchanged; no
worker/mpstat processes remained. New preservation checks verified 120 regular
files, and all 143 entries in the previous sealed evidence still matched. Exact
attempt IDs, paths, hashes and limitations are authoritative in the
[runtime validation record](milestone-a-runtime-validation.md).

Milestone A's implementation and authorized functional validation are complete
and ready for workflow/package feedback. No further runtime attempts, qualified
performance trials, registry acquisition, 9950 access, infrastructure changes,
push or transfer are implied. Milestone B remains unstarted until a specific
released-target/local-fix investigation is selected. No new approval is needed
merely to inspect the delivered artifacts or provide feedback.


### Milestone B implementation and controlled investigation handoff — 2026-10-23

The operator authorized the whole milestone B implementation on the existing
`milestone-a-newcomer` branch, using BIRD and controlled baseline/fix fixtures.
The instruction explicitly excluded real downloads, builds, benchmarks,
provisioning, 9950 access and pushing. Previous A runtime approvals were not
reused. Work continued through reviewed implementation, tests, docs and local
commits without treating internal substeps as operator handoffs.

- `0c59ec6` adds strict external target/build identity contracts and the explicit
  trusted-local-source BIRD builder. Base recipes remain unchanged; target-only
  substitution preserves generator, observer and workload identities. Source
  commit/HEAD, dirty patch/untracked/snapshot hashes, requested and observed base
  images, compiler/linker flags and instrumentation are recorded. Supplied-image
  source/build facts and binary reconstruction remain explicitly unknown.
- The source planner executes no source/build code, mutates no maintainer tree
  and refuses Git filters, incomplete/promisor/sparse/hidden-index views and
  unsupported source entries. Snapshot size is bounded; Git/archive memory and
  actual build resources are not workload estimates or hard host limits. The
  fixed build recipe requires existing local bases, uses network-none/pull-false,
  asserts installed BIRD/birdc, preserves failed work and selects a new tag.
- `a02be06` adds scoped optional BIRD diagnostics, monotonic control stages,
  pre-cleanup states/logs/cgroup memory and preserved event/sample material before
  final graph/provenance failures. Stages do not redefine convergence clocks;
  optional probes have uncalibrated overhead. Retained legacy graph samples are
  explicitly distinguished from an all-poll journal. Unsupported/unreadable data
  stays unknown, and collector failures retain any supported reproduction witness.
- `c86ada0` connects the public CLI, serial investigation, report-only rebuild,
  self-contained JSON/Markdown reports, verification and maintained smoke.
  It also records host identity before the worker and forces the source builder
  onto the selected local legacy daemon, disabling BuildKit/Buildx routing.
  Host changes or incomplete observed role identities withhold controlled
  attribution. No statistical performance comparison or universal fix rule is
  introduced.
- Reports verify bundled package bytes and the exact frozen recipe, preserve
  failed versus never-run attempts, record target/build/instrumentation changes,
  show crash witnesses/log references and carry explicit memory definitions.
  Both JSON assessment and rendered prose are reconstructed during verification;
  modified conclusions, unsafe/unlisted artifacts and differing fixed controls
  are refused. Malformed optional diagnostics retain their raw artifact plus an
  inspection reason rather than erasing the report.
- Independent implementation and final reviews covered all three boundaries.
  Findings fixed before handoff included Git filters/lazy-fetch and cumulative
  snapshot size, build routing/install identity, bounded client reaping,
  stage-failure cleanup, diagnostic path ownership, crash evidence conservatism,
  edited report prose and malformed optional evidence. The final independent
  focused review passed 109 tests. The implementation feature's normal locked
  environment/idle guard and full Docker-free gate passed all 2,213 tests.
- The first source-contract commit gate exposed a scratch Git fixture inheriting
  hook Git variables. It changed local Git metadata and created an inert fixture
  commit; the failed gate did not land an implementation commit. The accidental
  state was preserved at local recovery ref
  `recovery/milestone-b-hook-fixture` and `/tmp/bgperf2-b-git-recovery`, then the
  intended branch, index and effective repository settings were restored without
  editing worktree source files. The fixture helper now strips every `GIT_*`
  variable; 39 source tests also passed independently under simulated inherited
  directory/index/object/config context, with caller HEAD/index/config/work
  byte-checked unchanged. All subsequent normal gates passed.
- The maintained `scripts/investigation_smoke.py` passed from a fresh detached
  checkout of `c86ada0` using the existing locked environment, with no dependency
  installation. Its inert source and fake Git/build/runtime paths exercise
  target-image validation, dirty-source planning/build identity, direct override,
  serial investigation, report-only rebuilding and independent verification.
  No real BIRD bug or fix is claimed. The checkout stayed clean.

Retained feedback artifacts are under `/tmp/bgperf2-milestone-b-feedback`:

| Controlled case | Report | Independently verified report files | Meaning |
| --- | --- | --- | --- |
| `resolved` | `resolved/results/report/REPORT.md` | 34 | Modeled child-daemon crash in baseline, candidate completes; same frozen recipe/instruments, distinct target/build identity |
| `collector-failure` | `collector-failure/results/report/REPORT.md` | 16 | Baseline harness failure preserves available diagnostics; candidate is explicitly `not_run`, assessment inconclusive |
| `missing-memory` | `missing-memory/results/report/REPORT.md` | 34 | Same modeled functional outcomes; memory remains null with reasons, never zero or a leak verdict |

The simulation question and host facts are conspicuously labeled. Each case has
an `investigation.json`, checksum manifest and verified result packages; the
source/build fixture and direct-override result are retained alongside them.
The separate stdout summary is
`/tmp/bgperf2-milestone-b-feedback-summary.json`. These are controlled examples,
not real measurement evidence or adapter/build qualification.

The [public guide](../investigations.md) owns commands and schema/accounting
meanings; the [runtime proposal](milestone-b-runtime-validation.md) owns the
explicit future validation decision. Recommended first real scope is a bounded
supplied-image functional pair using previously observed images, after exact
read-only availability checks, with no downloads/builds or performance verdict.
A real source-fix build requires a selected trusted checkout/commit/patch and
reviewed preprovisioned local bases before an explicit build approval. Forced
faults, privileged crash capture and live-container timeout qualification are
not silently included.

Milestone B implementation and its controlled report workflow are ready for
operator feedback. Real source-build/diagnostic acceptance remains unmet. No
real download, build, benchmark, provisioning, 9950 access, push, publication,
notification or evidence transfer ran. Both existing A preservation manifests
were rechecked: all 143 and 120 entries remained unchanged.
Milestone C comparison/calibration and all new workload families remain unstarted.

### Milestone C implementation and controlled comparison handoff — 2026-10-23

The operator requested larger complete steps, autonomous progress until a necessary
decision and parallel subagents with appropriate models/effort. This selected
milestone C implementation on the existing `milestone-a-newcomer` branch. The
earlier B runtime authorization was consumed by its recorded pair (`99ad7e0`);
it was not reused. No real benchmark, download, build, provisioning, remote
transfer, `9950` access or push occurred during C implementation.

`e4fbbf1` adds strict recipe-bound observable assertion specifications and
outcomes, plus controller-recorded worker-budget evidence. The recipe/result
v1 envelopes stay unchanged. Assertions name session readiness, injection
completion, exact observer count, existing experiment completion and final
pre-cleanup container health separately. Unsupported predicates are refused;
missing or inconsistent clocks/budgets remain unmeasured. Health does not claim
continuous process health, and exact counts do not claim route/attribute truth.

`b7bab14` adds offline frozen plans, explicit serial
execution, per-attempt ledgers, report-only rebuilding and portable JSON/Markdown
verification. Each round contains both targets, with alternating AB/BA or
stable seeded digest ordering; the seed-43 sequence is pinned by a test. Every
attempt uses new paths through the existing guarded bounded runner. The first
noncompleted experiment/setup/harness/stop/inconclusive outcome stops execution,
without retries or automatic continuation. Failed attempts and work never run
remain distinct. A completed runtime sequence may still have failed or
unmeasured assertions; the report exposes this rather than changing legacy
completion semantics.

Reports preserve separate CPU, timing and memory quantities, individual values,
sample counts, missing/failed/not-run counts, variation and withheld reasons.
Legacy sampled delivery memory in actual GiB is separate from lifetime cgroup
peaks/ending observations. Rounded zero memory is below resolution, not an
observed zero. Diagnostic-none runs do not fabricate optional final health or
cgroup observations: callers may select the explicit four-assertion subset, or
retain the full set and see unmeasured health. Basic diagnostics preserve their
uncalibrated overhead. Performance qualification is always `not_assessed`, with
regression policy `disabled`; descriptive differences do not imply improvement.

Independent review fixed frozen timeout mismatches, duplicate original attempt
identities that could invent repetitions, malformed/oversized memory metadata,
impossible event spans and overflow-safe timeout validation. Verification
reconstructs assertions, statistics, confounders and prose from bundled verified
bytes and refuses unlisted/unsafe/modified files. The independent final focused
suite passed 205 tests, with another 11 tests for the last timeout/CLI changes.
The normal commit quality gate passed all 2,323 Docker-free tests.

The maintained public `scripts/comparison_smoke.py` walkthrough retains five
clearly simulated cases under `/tmp/bgperf2-milestone-c-controlled-feedback`,
with summary `/tmp/bgperf2-milestone-c-controlled-feedback-summary.json`:

| Controlled case | Simulated attempts executed | Files verified in each primary/rebuilt report | Purpose |
| --- | --- | --- | --- |
| `known-difference` | 6 | 92 | Known descriptive CPU/timing/legacy sampled-memory differences; optional cgroup/health absent under `none` |
| `noise` | 6 | 92 | Equal role distributions with nonzero within-role variation |
| `confounded` | 6 | 92 | Instrumentation/basic-probe confounders withhold differences while retaining observations |
| `stopped` | 2 | 32 | Harness failure retained, four later attempts explicitly never run |
| `missing-measurements` | 6 | 91 | Missing final metrics retain null values and reasons |

All ten primary/report-only reports verify using the final implementation; 26
simulated packages remain with their original work. These are controlled
examples, not BIRD measurements or host qualification. The public guide is
[comparisons.md](../comparisons.md). The
[calibration pilot proposal](milestone-c-calibration-proposal.md) specifies a
200,000-prefix workload, two proposed four-round series, worker budgets,
between-series correctness/resolution review and the necessary host/storage/
effect-size decisions. It authorizes no execution or policy activation.

Milestone C's implementation and controlled feedback workflow are ready for
review. Real host-trial/calibration acceptance remains unmet, and no calibrated
performance rule is enabled. Milestone D deterministic bisection remains
unstarted; performance bisection still depends on a separately calibrated C.

The standalone walkthrough also passed from fresh detached checkout `b7bab14`
at `/tmp/bgperf2-milestone-c-fresh`, reusing the existing locked environment
without installation. All five cases passed; retained fresh outputs are under
`/tmp/bgperf2-milestone-c-fresh-feedback`, with summary
`/tmp/bgperf2-milestone-c-fresh-summary.json`. The temporary environment symlink
was removed after verification and the checkout remained clean. The earlier
milestone A/B preservation manifests were rechecked unchanged: 143, 120 and
302 regular-file entries still match their sealed bytes. No original evidence
was deleted or transferred.

### Pilot closeout, supported safeguards and deterministic D — 2026-10-26

The operator selected these three next steps after completion of the hourly
noise/resolution experiment. The accepted run used engine `57e51b3` and was
recorded in `1cfe6c5`: exactly eight A/A then eight A/B attempts, 120 worker
seconds each, diagnostics none, 64 passing named assertions, 16 accepted
observer timing screens and independent first-attempt, A/A, A/B and cleanup
reviews. The [calibration record](milestone-c-calibration-proposal.md) retains
the successful run and every earlier refusal/stopped invocation. This is
noise/resolution discovery, not performance calibration or a version ranking.
Lab operations own schedule retirement and the verified local preservation
receipt; raw evidence is not placed in engine Git or transferred remotely.

The [staged comparison interface](../comparison-execution.md) moves private
coordinator lessons into an optional supported public workflow. It initializes
supplement directories before execution, serializes collection/assessment,
verifies package/assertion/budget/cleanup evidence before successors, requires
explicit hash-bound first/final reviews, and supports a prior accepted series
as a prerequisite. Optional pressure monitoring uses an explicit operator
policy rather than requiring zero utilization. Monitoring errors and material
pressure stop owned execution and block successors. Setup refusals proven to
precede any attempt remain not-run. Legacy compare and report contracts stay
unchanged; no automatic repairs or retry scheduler was introduced.

[Deterministic bisection](../bisection.md) implements phase 6 for the existing
four observable correctness assertions and a captured nonzero target-daemon
exit. Hash-checked commit objects prove a consecutive first-parent chain;
fixed source/build controls bind every trial. Build caches use complete plan
identity, measurements retain unique original IDs, and both boundary sides
require fresh confirmation. Skipped and ambiguous candidates remain holes in
an explicitly unresolved range. Fixed trial budgets never extend. Interrupted
reservations require explicit recovery; incomplete copies and existing failure
records are retained without re-executing a worker. Portable reports reconstruct
predicates, search requests, bounds, confirmations and human prose from evidence.

Independent review tightened crash timing to explicit controller worker start/
end anchors, retained missing/old clocks as ambiguous, made partial-copy and
failure-before-journal recovery safe, and refused symlinked session paths. An
additional check refuses a completed crash trial with unexplained target
absence. The controller adds optional monotonic anchors to existing worker
budget evidence without changing benchmark clocks or legacy assertion meaning.

The maintained `scripts/bisection_smoke.py` exercises public planning, execution,
report rebuilding and verification with five strictly simulated histories:
assertion boundary, captured-crash boundary, skipped revision, ambiguous
pause/resume and unstable confirmation. Subprocess and network operations are
guarded throughout. Separate tests read an inert local Git chain without
changing its checkout. That fixture strips the entire inherited Git environment;
a trap-variable regression prevents a commit hook from redirecting it into the
engine checkout. During validation its original missing isolation created an
unintended local fixture commit; branch/index were restored with a checked
compare-and-swap, all implementation edits retained, and an audit patch kept
outside Git. No accidental fixture files remain in the branch.

These are controlled implementation checks, not a real source build or live
regression localization. Selecting a trusted daemon revision range, locally
available builder/runtime images and qualified host remains a separate live
validation decision. New daemon builds, downloads, benchmarks, infrastructure,
remote evidence transfers and performance policy activation were not performed.

Delivery commits are `42420a4` (staged comparisons) and `78a03b5` (deterministic
bisection, controller budget anchors, maintained walkthrough and updated
contracts). Both passed independent code review before normal local commits.
The final engine quality gate passed **2,410 Docker-free tests** in 88.61 seconds;
the locked environment inventory also matched all 34 packages. Independent final
focused review passed 68 related tests, including 11 walkthrough tests.

The final standalone walkthrough passed at
`/tmp/bgperf2-milestone-d-final-feedback`, with summary
`/tmp/bgperf2-milestone-d-final-feedback-summary.json`. It retained 33 simulated
workers and 25 fake builds across five histories: assertion and crash boundaries
confirmed; skipped, ambiguous and unstable cases remained unresolved. All 11
primary, rebuilt and paused portable reports verified. Modeled workers use
private output-owned host locks, leaving real host/session guards intact.
These fixtures supply no daemon measurement or performance conclusion.

### Codex/Docker prerequisite diagnosis — 2026-10-26

An assistant-proposed follow-up addressed the Codex execution blocker. The
operator subsequently clarified that this did not replace the A–D milestone
objective. Read-only public
checks at clean engine `78dd9a2` reproduced the distinction: the sandbox check
refused at bootstrap, while the same recipe/check passed through approved host
execution, including all three pinned image inspections. Neither created work
or result directories. This confirms the approved execution path; it does not
authorize a measurement or establish CPU idleness.

The remaining engine bug was lost diagnostic output: the quality gate captured
Docker stderr but rendered only its exit code through bootstrap. It now retains
the last 2,000 diagnostic characters and explains execution-context access and
approved host execution. A missing daemon is not mislabeled as a permission
failure. The guard still refuses on every Docker inspection failure, makes one
probe with no retry or automatic repair, and remains mandatory.

The focused quality-gate/prerequisite suite passed 39 tests. Direct read-only
verification of the corrected guard returned exit 1 with the actual socket
permission-denied message in the sandbox and exit 0 through approved host
execution. Reports and original stderr remain under
`/tmp/bgperf2-codex-docker-verification-20261026`. The environment guide records
the remedy. No BIRD regression was selected, and no build, benchmark, download,
new schedule or remote transfer ran as part of this fix.

### Focused execution and cleanup bug review — 2026-10-26

An assistant-proposed review, accepted as a follow-up, repaired existing
execution, error-handling and cleanup behavior. Baseline `46f13ba` supplied four confirmed defects,
reproduced with fake workers and Docker responses before fixes:

- An inspect, ownership or removal failure abandoned the remaining resources
  of that kind. Cleanup now records each failure and checks every remaining
  owned container/network once, retaining foreign or uncertain resources.
- A normal process wait returning after the observed wall-clock budget could
  still report completed. An exceeded observed budget is now inconclusive,
  including when the child returned successfully; collection and cleanup
  remain outside the worker budget.
- A background health-monitor exception could kill monitoring while the
  worker reported completed. Monitoring failures now reach the terminal
  harness-failure outcome rather than being lost in a daemon thread.
- One malformed container inspection could discard diagnostic state/memory
  already collected for other containers. The collector now preserves those
  observations and records a partial collection with the failure.

The initial controller regression tests failed in all four selected cases
(three cleanup failure kinds plus late completion); container and network
coverage and related sequencing checks passed after repair. Red/green test
outputs and review evidence remain under
`/tmp/bgperf2-execution-bug-review-20261026`. Review scope stops at these four
defects. No benchmark, daemon build, download, schedule, infrastructure or
remote evidence transfer is part of this work. Normal Docker-free tests and
independent review precede the local commit; live Docker/hardware qualification
remains separate.

The related Docker-free suite passed 114 tests. Independent final review passed
70 controller/worker/diagnostic tests and accepted all four fixes. The monitor
regression forces the capture-to-handoff race with real threads; captured errors
survive concurrent completion. Stopping prevents later artifact/terminal writes,
and a healthy in-flight SDK probe adds no join delay or new failure threshold.

### Milestone B real-source validation resumed — 2026-10-26

The operator selected continuation of milestone B's real-source validation.
The Codex/Docker interruption and subsequent repairs did not replace the plan.
Use the bounded [source-build validation procedure](milestone-b-runtime-validation.md#source-build-and-interruption-validation--2026-10-26)
on the existing branch, with current reviewed engine code `26e5c5c` plus this
committed procedure. First qualify the real clean-source build and basic
diagnostic/interrupt/cleanup paths. No upstream bug or fix is selected by this
functional check; an actual bug-specific source-fix assessment and milestone D
live revision search remain distinct acceptance work.

The pristine release source plan subsequently refused two checked-in BSD
symlinks under the documented source guard. No build or worker started. A
separate reviewed local packaging commit `ff132d4` materializes only those
aliases; its execution is a changed source case awaiting the operator decision
in the [milestone B record](milestone-b-runtime-validation.md#source-plan-refusal-and-prepared-compatibility-case).
The original source and the engine guard remain unchanged. This preparation
does not advance B's runtime acceptance or replace the A–D milestone objective.

The operator subsequently approved that changed source case. At clean engine
`3cf1a0a`, exactly one real build, two completed functional workers and one
expected setup interruption passed independent review. Both completed workers
passed all four bounded assertions; every package/report verified and actual
container/network/volume inventories remained unchanged. The
[full record and limits](milestone-b-runtime-validation.md#approved-packaging-source-validation-completed--2026-10-26)
retains the user decision, source/image identities, raw evidence and review
receipts. Source-builder symlink restrictions remain unchanged. Optional
generator memory read timeouts stay missing, and interruption reached setup
containers only; these results imply no routing bug fix, performance conclusion
or broader fault-path qualification. The bounded authorization is consumed;
the original A–D milestone objective remains in effect.

### Milestone D bounded live count-fault validation — 2026-10-26

The prepared case at `6d66b2f` and admission stop at `43965e6` were followed by
the operator's renewed approval and explicit instruction to wait for heavy jobs.
At runtime engine `43965e6`, three public builds and five distinct serial workers
confirmed the deliberately introduced `f6f9adbd` → `4bddf6ab` count-fault boundary,
including fresh workers on both sides. Each step and the two independently
rebuilt 219-file portable reports passed review. The
[authoritative execution record](milestone-d-runtime-validation.md#approved-waited-execution-completed--2026-10-26)
preserves source/build identities, cached-compilation and contention caveats,
diagnostic nulls, cleanup and local retention coverage. This is a bounded live
functional qualification, not an upstream bug or performance result. Its runtime
budget is consumed; C calibration and performance policy remain pending/disabled.

### Milestone C controlled repeatability prepared — 2026-10-27

The operator selected 10% slower observer 10%-to-90% delivery as the practical
planning target. A read-only audit verified 322 A/A report files and reconstructed
all eight original supplements: four natural pairs, with apparent same-image
differences −25.13%, +40.17%, +71.14% and +1.24%. Unknown instrumentation,
uncontrolled placement and recorded outside CPU work prevent a controlled
performance conclusion or sample-size calculation. Original report withholding
and source evidence are unchanged.

Pure CPU layout helpers were extracted in `eca7c2d`; opt-in portable recipe
pinning followed in `69ac253`, preserving absent-pin identities and forwarding
canonical placement through the existing worker lifecycle. Independent code
review accepted both; the feature passed 337 focused tests and its normal
2,454-test commit gate. Live placement qualification remains pending.

The [controlled repeatability validation](milestone-c-repeatability-validation.md)
owns the next exact case: one optimized packaging-source build, then two
separately gated blocks of eight A/A pairs, 32 serial workers maximum. Its new
idle-host/storage authorization is pending. No builds/workers started during
preparation. Sixteen pairs are not a powered sample-size claim, and the selected
10% target is not a regression cutoff. Estimator, error rates/power, adequate
sample budget, known-effect controls and held-out validation remain separate
decisions before performance policy or performance bisection can be enabled.

### Milestone C controlled repeatability stopped at first review — 2026-10-27

The operator approved the prepared case at `2b15281`: one optimized source build
and up to 32 serial A/A workers, with fresh idle admission and the renewed
root-backed storage exception. The build completed with actual `-O2 -g`
compilation/linking, immutable image/source/build bindings and independently
accepted cleanup. Three setup layers used cache; compilation ran.

The first worker completed and passed all four assertions, source/package/report
verification and observer resolution. Its live requested/effective target,
monitor and tester CPU layouts matched the recipe. Outside CPU then blocked
continuation: the retained peak was 173.9710% of one core, above the frozen 100%
cap. Independent first review rejected continuation; the public session and
coordinator are permanently stopped. Accounting is one completed build, one
completed worker, zero failed worker experiments and 31 never run. No pair
completed, so there is no repeatability, variance, power or performance finding.

The [execution record](milestone-c-repeatability-validation.md#approved-execution-stopped-at-first-review--2026-10-27)
owns actual bounds, host/pressure evidence, cleanup, source revisions and local
preservation paths. All original evidence is retained, unrelated resources are
unchanged, and policy stays disabled. This case's authorization is consumed;
a further run needs a concrete reviewed case and fresh execution approval.

### Milestone C fresh zero-build case 02 prepared — 2026-10-27

After the operator noted lighter load, a read-only 30-second check passed the
existing CPU/memory/disk limits without authorizing execution. The
[case-02 proposal](milestone-c-repeatability-validation.md#case-02-prepared-with-existing-optimized-image--2026-10-27)
reuses the actual optimized image from case 01: zero builds and at most 32 serial
workers under unchanged admission, pressure, outside-CPU and review/stop gates.
Derived target declarations preserve the full immutable image/build provenance;
only labels and the binding to an equivalent recipe at the final documentation
revision change. Original build/runtime engine `2b15281`, stop record `8446aef`
and sealed-preservation completion `edd5ce7` remain separately recorded.
The original case stays permanently stopped. New destinations and separate
ledgers are selected; no new worker or host/storage exception is authorized yet.
