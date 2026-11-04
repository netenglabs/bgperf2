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
