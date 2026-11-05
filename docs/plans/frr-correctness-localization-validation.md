# Controlled FRR correctness localization

Selected by the operator after the source-built functional pair at `961be89`.
The operator requested documentation integration and a controlled local FRR
regression exercising changed-revision comparison, minimization and bisection.
The earlier supplied-image/source-built cases remain complete; the earlier
stopped case remains stopped. No completed original is rerun.

## Scope and acceptance

Use the existing FRR source/recipe contracts and a clean private engine at
`961be899d1202e787658f5934e6ec0bc0c9616ee`. Integrate earlier documentation into
`milestone-a-newcomer` without staging or changing the six concurrent code/test
edits. That fast-forward is complete, with before/after byte receipts retained.

The controlled source history starts at the explicitly packaging-adapted FRR
10.3.1 revision `b7ffb580af3066b05f73fb07f6b6fc56db199d9f`. A comment-only neutral
commit `4bc2f0429e904cc6c5b504bc56deffad2884fd65` is followed by deliberate local
fault `ea5d46e6d07a0a427df80092ac0914a87ed79438`: an IPv4-unicast NLRI
`100.0.0.1/32` becomes `198.18.0.1/32`, preserving route count. The candidate
explicitly rolls back to the pre-fault revision. This is test input, not an
upstream FRR defect or general fix claim. Retain source attribution, patches,
regular-file packaging adaptation and unchanged original checkout/evidence.

The bounded case contains five public builds and twelve fresh originals:

- Two source-bound workers on the same two-peer/four-prefix recipe establish
  the bad/rollback contrast. All six witnesses are evaluated; only exact prefix
  identity may fail on bad source. Public comparison/investigation reports and
  candidate CI consume those independently collected public `run` originals.
- Five native minimization steps select `observer.prefixes`, reduce to one
  peer/two prefixes and freshly confirm that result. Passing one-prefix evidence
  remains retained. This is a bounded greedy result, not a global minimum.
- Replan source targets for the reduced recipe, refusing the old recipe binding.
  Three new source-build invocations cover the same three consecutive revisions.
  Five fresh external bisection originals establish good/bad endpoints, test the
  neutral midpoint, and confirm both sides of the adjacent boundary.

Use the documented bisection `step` preview, fresh public `run` and `record --result`
interface. This separates builds from each worker's fresh admission. It qualifies
that source-bound external-trial path, without claiming combined `step --execute`
or FRR build-cache-controller qualification. The manually collected pair similarly
does not qualify the `compare` multiworker controller or repetition adequacy.

Every source build uses fixed `frr-local/v1`, optimized declaration, requested
`-O2 -g`, `--disable-doc`, two make jobs, no network/pull/install. Existing builder
and runtime are mixed FRR image `sha256:2ab2018dfe70088f318ee9b9c976bd2fd610580460e1715fe14548042dcc133d`.
BIRD generator and sink retain the accepted source-built pair's exact identities.
Cached Docker compilation is allowed but must be reported as cached; it supplies
no old worker observation. Static image/config/layer/fresh-installation inspection
runs no probe container. Preserve all build logs, source archives and warnings.

## Execution protocol

The user's current instruction authorizes this finite functional case and the
same explicitly declared root-backed `/tmp` storage convention. The plan itself
does not grant execution authority. Per build: 1,200-second client limit and
1,800-second outer limit. Per worker: 120-second inner and 240-second outer limit,
with 15-second TERM grace and at most 15-second post-KILL reap. No retries,
acquisitions, probe containers, scheduler, broad cleanup or budget extension.

Fresh guard, exact input/image/dependency checks, 16 GiB memory/20 GiB disk
floors, mount and advisory activity snapshots precede each build/worker.
Admission must be within 300 seconds of launch. Workers are serial; development,
builds and analysis never overlap a selected active worker. No quiet-CPU wait
or timing/performance qualification is part of this immediate functional protocol.

Independent preparation, build, changed-pair, reduction/reduced-build and final
reviews gate the stages. After every original, verify actual process exit,
exact worker budget, package/work hashes, all six witnesses, expected prefix
set, immutable role images and FRR 10.3.1 banner. Require empty cleanup_errors,
owned container/network absence and stable foreign public identities/semantic
mount/network/label sets. Inspect native monitor/socket modes with lstat only.
Unexpected failure, missing evidence, ambiguity, uncertain launch/cleanup or
rejected runtime review stops successors; preserve partials without repair/retry.

Verify and reconstruct all comparison, investigation, minimization and bisection
reports; keep original attempt identities and freshly confirmed witnesses.
Whole-case local preservation includes source Git, archives/logs, inputs,
receipts, original work/packages, journals, reports and reviews. Checksums are
not authenticated execution or independent backup. No evidence deletion,
remote backup, push, publication or paid infrastructure is authorized.

## Preparation checkpoint — 2026-11-05 UTC

Evidence root: `/tmp/bgperf2-frr-localization-20261105/`.
`integration/OUTCOME.json` records completed documentation fast-forward with all
six concurrent files and staged/unstaged diff bytes preserved. `preparation/range/`
contains verified local object proofs, three owned checkouts and source plans.
Five modeled control checks passed, including exact five-trial minimization and
bisection trajectories; no worker or build ran in those tests. `READY.md` and
the sealed packet contain exact conditional stage operations and review gates.
Independent preparation, original-build, changed-pair and reduction/reduced-build
reviews accepted before their required successors. The runtime checkpoint below
records the completed originals. Supplemental complete-case closeout accepted
after the missing offline relocation checks were supplied; the original final
rejection and permanent runtime stop remain retained.

Packaging adaptation, mixed-base residual modules/libraries/build tree,
configure/build/daemon warnings, bounded container-health snapshots and
post-measurement prefix identity remain explicit limits. Continuous bgpd
liveness, crash witnesses, pristine/hermetic/reproducible builds and general
regression conclusions remain unqualified. The unrelated upstream investigation
stays paused, performance policy disabled and calibration deferred.

## Runtime checkpoint — 2026-11-05 UTC

All five source-build invocations and twelve fresh original workers completed
with zero actual process exits and no timeout, retry or unexpected failure.
Bad original and neutral reduced builds showed actual compilation; original
rollback and reduced indices0/2 used cached compilation. Each build's source,
recipe, log, Dockerfile, physical image and exported layers/fresh installed
bgpd/vtysh/libfrr bindings verified. Cached builds are not fresh-compilation proof.

| Phase | Fresh originals | Actual outcome |
| --- | ---: | --- |
| changed-revision pair | 2 | bad source preserves count 8 with exactly one substituted prefix; explicit rollback passes all six witnesses |
| native minimization | 5 | 2x4 fault, 1x4 fault, 1x1 pass, 1x2 fault, fresh 1x2 confirmation fault; `confirmed_smaller` |
| external-trial bisection | 5 | good0, bad2, good1, fresh good1, fresh bad2; adjacent boundary `confirmed` |

The freshly confirmed boundary is
`4bc2f0429e904cc6c5b504bc56deffad2884fd65` →
`ea5d46e6d07a0a427df80092ac0914a87ed79438`.
All source revisions were observed on the same one-peer/two-prefix recipe.
No pending trial, skipped/ambiguous outcome or budget extension remains.
Every faulty original is missing only `100.0.0.1/32` and adds only
`198.18.0.1/32`, preserving count. Across twelve six-witness evaluations,
65 assertions passed and seven intentionally failed prefix identity; the
other witnesses passed in every original. Candidate CI returned zero;
all-side CI exit4 and old-target/reduced-recipe refusal exit2 were expected.

Worker inner durations were 11.18–13.59 seconds and outer durations
13.19–17.55 seconds, within 120/240 bounds. Original work, native events,
packages, identities, versions, budget records and warnings remain preserved.
All twelve have explicit empty cleanup_errors. All 36 exact owned container IDs
and 12 attempt network scopes are absent; foreign public identities and semantic
mount/network/label sets remain 75 containers, 6 networks, 495 volumes. Native
monitor/socket 0700/0666 metadata was inspected with lstat only.

All native report verifications passed. Fresh physical reconstruction matches
95 comparison files, 95 investigation files, 248 minimization files and 230
bisection files, including original bindings and fresh confirmations.
`final-readback.json` verifies 303 exact operation receipts, packet/source/engine
closure, budgets, stage review ordering and expected outcomes.

The actual final review independently verified the runtime facts and rejected
complete acceptance because relocated-report verification was missing. Its
judgment and permanent runtime stop remain preserved. Four byte-identical local
copies were then verified with the native offline report interfaces: all 668
files match their originals before/after verification. No build, worker,
charge, runtime receipt, original rejection or stop was changed or retried.
The four extra offline receipts bring the total to 307; the original 303-operation
readback remains unchanged. Actual supplemental complete-case closeout accepted
in `reviews/final-supplement.json`, independently recomputing all six bindings,
all 668 relocated file hashes/coverage and the four actual verification receipts.
It accepts closure only; the original rejection and permanent runtime stop remain
byte-identical, no original was retried/reclassified and no bad row was excluded.
Runtime successors remain forbidden.

Runtime preservation passed: all 2,897 regular runtime files (317,639,253 bytes)
and 27 native sockets are sealed with immediate byte/coverage/metadata readback.
The full-case seal and separate verifier additionally cover source Git,
environment, audits, reviews, documentation/native-gate and integration records.
Preservation remains local, without authenticated execution or off-device backup.

The public comparison and investigation reports bundle manually collected
public-run originals, and bisection uses documented external fresh trials and
recording. The combined compare controller, FRR combined bisection build/run
controller and build-cache execution path remain outside this qualification.
No timing or performance conclusion follows from the small functional case.
