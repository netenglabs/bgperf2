# Exact-prefix maintainer workflow across comparison and localization

Selected 2026-11-03 after the operator requested a larger complete goal than
individual inspection/CI helpers. Starting checkpoint: `1c3edeb` on the explicit
development checkout. The upstream BIRD investigation remains paused.

## User outcome

A maintainer can reproduce a count-preserving prefix-set mismatch, evaluate a
candidate using named assertions and CI, repeat the fixed comparison, and search
a consecutive source chain for the deterministic correctness boundary. One
maintained public-CLI walkthrough connects these steps, interruption recovery
and portable report verification using explicitly simulated evidence. It must
not imply a real BIRD bug, introduce a fault into BIRD, or reopen upstream test
selection. Existing real-BIRD cases qualify only their recorded bounded paths.

## Delivery units

1. Extend comparison planning/execution with explicit bounded prefix capture,
   symmetric forwarding, assertion selection and retained report evidence.
   Existing unselected plan bytes/runner kwargs and report semantics remain.
   Add the same forwarding to staged comparison sessions. Mark capture as an
   uncalibrated timing confounder; performance policy stays disabled.
2. Add an explicit `prefix_assertions` deterministic bisection predicate: the
   existing four worker-budget assertions plus final prefix identity, excluding
   optional role-health from the search predicate. Validate capture bounds at
   planning before probes/changes. Missing/unavailable evidence stays ambiguous;
   a decisive supported assertion failure is bad. Keep source-range preparation,
   handoff commands, build caching, reservation recovery and fresh confirmation
   evidence consistent with the selected predicate. Old predicates unchanged.
3. Deliver one public-CLI exact-prefix walkthrough covering reproduction,
   count-pass/identity-failure, candidate CI, repeated comparison, deterministic
   search and fresh confirmations, interrupted-work recovery and relocated
   reports. Retain the existing crash walkthrough. Simulated backends must
   refuse unmodeled runtime/subprocess/network actions. No actual build/worker
   runs during the walkthrough or unit gates.
4. Review the integrated workflow independently, fix findings, run meaningful
   focused checks and required repository gates, document and commit internal
   checkpoints. Prepare a single bounded existing-image comparison validation
   packet only after clean committed implementation, for one execution approval.
   Do not execute it automatically. Real prefix-bisection qualification remains
   separate until a concrete authorized source history/build budget is selected.

## Acceptance and limits

Check strict flags/types/capture caps before side effects, unchanged defaults,
equal-count changed sets, unmeasured/partial/stopped work, original identity and
source/build bindings, recovered reservations without retries, rehashed tamper
refusal, stored-artifact relocation/rebuild and complete human/machine reports.
Keep assertion correctness, reproduction, operation status and performance
separate. A final snapshot establishes neither attributes nor continuous truth.
Capture overhead is uncalibrated; formal 10% calibration remains deferred.

Use local conventional commits as internal checkpoints and Markdown progress.
Preserve existing evidence and frozen packets. No new real workers/builds,
image/package acquisitions, provisioning, evidence deletion, push, publication
or remote transfer are authorized. Task evidence and review live under
`/tmp/bgperf2-prefix-workflow-20261103/`.

## Integrated implementation and offline qualification

The three delivery components are implemented together. New focused checks:
34 comparison cases, 11 localization/source-range/handoff cases and 11 connected
walkthrough cases passed. Existing documentation and comparison/bisection/crash
walkthrough checks passed 107 tests. Independent review inspected the complete
change and separately exercised component and integrated walkthrough checks.

The connected public walkthrough prepares four actual inert local commits,
executes the generated prefix-aware handoff with modeled backends, preserves
count 100 while one prefix is substituted, and demonstrates candidate CI exit 0,
both-side exit 4 and missing-candidate exit 5. Its two comparison rounds retain
four distinct originals. The six-trial search confirms the modeled revision 1/2
boundary with fresh observations after recovering a collected original without
retry. Across stages, 13 modeled original attempts and six modeled builds remain
distinct and explicitly simulated. Original and prepared source trees, private
Git bank, handoff and candidate plan are retained unchanged; offline rebuilt and
relocated evidence verifies without modeled execution.

Required native gate output, local commit, final source hashes and retained
public command transcripts accompany the external task evidence. Real validation
of normal/staged repeated capture and prefix localization is not established by
these fixtures. The next approval packet selects only a normal existing-image
same-image comparison: two rounds/four serial workers, zero builds/probes, with
declared functional storage/capacity decisions and no scheduler. Preparation
does not run it. Real prefix-localization/build qualification remains deferred;
no source history or build budget is silently selected by this milestone.

The first native full gate retained a legacy comparison-smoke failure: its
modeled runner collided with the real user recipe host lock, then its missing
result caused follow-on verification errors. The fixture now uses the shared
per-output modeled-lock helper already used by bisection/maintainer smokes;
production locking is unchanged. A regression refuses any real host-lock open
while the public comparison smoke runs successfully. The original failed gate
and final retry are preserved separately in task evidence.

## Approved normal comparison validation — 2026-11-04 UTC

After the complete implementation/review at `f20c943` and a 2,922-pass native
gate (one optional skip), the operator approved the frozen four-worker A/A
case and its functional-only root-storage exception. Fresh native admission
passed before the single direct comparison invocation. There was no scheduler,
build, probe container, image/package acquisition or retry.

| Sequence position | Worker seconds | Named assertions | Exact prefix set |
| --- | ---: | --- | --- |
| r001-baseline | 11.785825 | Six passed | 100 expected; missing 0, unexpected 0 |
| r001-candidate | 12.387204 | Six passed | 100 expected; missing 0, unexpected 0 |
| r002-candidate | 13.110714 | Six passed | 100 expected; missing 0, unexpected 0 |
| r002-baseline | 12.505563 | Six passed | 100 expected; missing 0, unexpected 0 |

All four distinct original attempts completed within their 120-second worker
budgets. The outer controller exited normally with status `recorded` and exit 0
in 64.201782 seconds, below the 900-second deadline. All 33 recorded commands
exited 0. Independent per-attempt assertion exports agreed with the report.
Public verification accepted 45 artifacts per original and 190 files in each
original/rebuilt comparison bundle. The verified rebuilt report is identical,
including original attempt identities, correctness and frozen plan.

The read-only original-work permission receipt shows collector-owned mode-0700
monitor directories and socket endpoints of the expected type/mode 0666. All
runtime records explicitly report empty cleanup errors; native post-run
container/network/volume inventories contain none of the four owned scopes or
12 captured owned container IDs. Foreign inventory activity is recorded, not
claimed globally unchanged. Source, raw capture, load, approval, command exits,
packages, permissions, cleanup and review evidence remain under
`/tmp/bgperf2-prefix-workflow-20261103/`, separate from the unchanged preparation
packet and earlier milestones. Retain the referenced local store; local hashes
and copies are not an independent backup.

This qualifies normal comparison capture for the selected BIRD 2.19.2 target
and generator, sink 0.2.0 observer, one peer and 100 synthetic IPv4 host routes.
Both target labels used the same immutable image. Unknown instrumentation,
basic diagnostics, prefix capture and recorded foreign CPU remain confounders;
descriptive deltas stay withheld. The run is not a changed-binary comparison,
upstream bug/fix, continuous-correctness, hardware or performance qualification.
Live staged comparison and source-build/prefix-localization qualification remain
separate. The four-worker allowance is consumed with no automatic successor.
Upstream investigation remains paused; performance policy stays disabled and
formal 10% calibration deferred.

## Operator continuation — 2026-11-04 UTC

After the normal four-worker case succeeded, the operator requested continued
work on the larger goal rather than treating its completed worker allowance as
a failed or finished overall qualification effort. There is no token/time-budget
failure. Implementation and the selected normal path are delivered; the live
staged and localization paths remain separate acceptance gaps.

Prepare the remaining validation as one review batch: a minimal staged A/A pair
using existing images and explicit first/final independent review gates, plus
a concrete localization case if the preserved controlled-test source/build
proofs support it. Source inspection is restricted to those named preserved
test records; the upstream bug investigation stays paused. Do not create a new
source fault, silently relabel cached image targets, or claim a prefix mismatch
from a count-only witness. A same-good endpoint control, if selected, can qualify
capture and refusal but cannot confirm a regression boundary.

Complete substantive preparation and any required supported-workflow fixes,
checks, review, documentation and local checkpoints before presenting the
execution decision. Cases must explain their natural worker/build counts,
fresh confirmations, review pauses, exact source/image bindings and terminal
recovery rules. Prior successful-case positions are not automatic permission
for new runs, and reaching a case ceiling is not a failure of the larger goal.
No new real build/worker, acquisition, scheduler or policy activation follows
from this continuation. Preparation evidence lives under
`/tmp/bgperf2-prefix-qualification-20261104/`.

The remaining batch has a concrete natural scope: two staged workers (one per
role, exercising first/final review), then three public local-source build
invocations and five fresh localization workers. The preserved controlled
history contains a good revision, an inert-comment good revision and its
documented deliberate single-prefix suppression. Fresh plans preserve all three
source identities and first-parent proofs. Updating the framework/observer
changes the recipe binding, so old target/cache declarations cannot be edited
or imported as new targets; the existing Docker compilation layers may be reused
by actual public builds without claiming fresh compilation.

Localization must first witness the selected good/bad endpoints, classify the
midpoint, and obtain fresh good/bad confirmations. The controlled bad result is
expected to fail count and prefix identity while completing the experiment;
that is an expected test witness, not an upstream bug or an arbitrary failure.
Its prefix observation must be collected afresh and cannot be inferred from an
old count. It does not establish a count-preserving wrong-prefix live boundary.
Unexpected, unavailable or ambiguous evidence remains an incomplete case.

The build/localization phase is conditional on an actual accepted staged final
review. Each later localization step requires inspection of its exact request,
verified original evidence, owned cleanup and independent review of the prior
trial; no automatic run-over-skipped-results or approval loop is selected.
Confirmation cache identities must already verify, preventing an unnoticed
fourth build. Per-command timeouts bound actual execution; there is no arbitrary
overall goal/token deadline and review pauses do not fabricate a failed goal.

Qualification cases use an independent clean committed engine at `28e6a54`,
with its existing locked environment and private Git/object/source hashes.
Pending parent documentation is explicitly excluded. The staged controller's
existing child argv has no `-E/-B`, so these cases freeze an explicit minimal
`env -i` profile, including known store/converter and bytecode-disable settings,
instead of inheriting Python/Git/Docker overrides. Engine defaults do not change.
Observer-window, pressure/prior-series combinations, forced build-timeout or
interruption experiments and performance calibration are outside this batch;
they do not silently become new closure requirements for the selected goal.
