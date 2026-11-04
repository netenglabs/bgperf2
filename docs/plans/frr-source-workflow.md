# FRR source-to-fix and correctness localization

Selected by the operator after the supplied-image FRR pair at
`03a4e77830f33a33a68931a41dabfd0318e510c6`, branch `milestone-a-newcomer`.
The earlier pair is complete and will not be rerun. Its authoritative record
remains [the supplied-image plan](frr-maintainer-workflow.md).

## Outcome and scope

An FRR maintainer can select trusted local source, freeze a build with immutable
builder/runtime inputs, reproduce a correctness failure, investigate a candidate,
reduce peers/prefixes and locate a deterministic first-bad source boundary.
Use the existing `frr_c` adapter, BIRD generators and sink observer. Keep BIRD
defaults and identities compatible. Source identity and requested build controls
are evidence, not proof of hermetic or bit-reproducible compilation.

Deliver a fixed `frr-local/v1` recipe with adapter-compatible installed paths,
strict adapter/build bindings, offline source-range preparation and maintainer
handoffs, and assertion/prefix-assertion bisection. Keep FRR crash predicates and
thread controls refused. Preserve bounded budgets, missing/ambiguous outcomes,
unique original observations, interrupted-result recovery, fresh confirmations,
owned cleanup and independently reconstructed portable reports.

Minimization keeps its existing image-only contract. Explicitly export a recipe
with the built failing image for reduction, then replan source builds for the
confirmed reduced recipe; never relabel a target bound to a different recipe.

## Acceptance

1. Meaningful tests cover local inert FRR Git source, dirty snapshots, malformed
   plans/targets, fixed Dockerfile paths, build failures and immutable identities.
2. Source-range preparation and handoff work offline for FRR with no source code,
   image acquisition, real compiler or worker execution.
3. One maintained public CLI walkthrough connects reproduction, candidate CI,
   minimization and deterministic localization of a deliberately modeled fault.
   It demonstrates interrupted-result recovery without repeating an original,
   fresh confirmations, report rebuild/relocation and changed-evidence refusal.
4. Required code review, focused checks and native repository gates pass before
   local delivery commits. Record commit and evidence references here.
5. Prepare a separate live-validation proposal with explicit prerequisites,
   source/image bindings, finite budgets and stop conditions. Missing local
   prerequisites remain gaps. No execution is authorized by this plan.

## Limits and progress

No real builds/workers, acquisition, upstream investigation, source fault search,
paid provisioning, evidence deletion/remote transfer, push or publication.
Performance policy stays disabled, calibration deferred and the unrelated
upstream investigation paused. Earlier evidence and frozen checkouts stay intact.
Development requires a passing active-measurement guard; it passed before this
implementation began. Evidence root: `/tmp/bgperf2-frr-source-workflow-20261104/`.

## Implementation checkpoint

The `frr-local/v1` contract, strict adapter bindings, offline range/handoff support
and correctness bisection are implemented. The maintained
`frr_source_smoke.py` connects a count-preserving modeled prefix fault to a
candidate rollback, image-only minimization and fresh source-bound localization.
Standalone `modeled02/REPORT.md` passed: 16 distinct simulated originals, seven
modeled builds, confirmed one-peer/two-route reduction, recovery of the unchanged
third trial without more work, fresh boundary confirmations and eight relocated
verification receipts. The initial `modeled01/` harness fixture error remains
retained; no real worker was involved.

Source-focused checks passed 22 tests; layout corrections passed 13 tests;
source/handoff integration passed ten tests. Earlier fixture-signature and fixed
file-count failures were corrected without changing production recovery or
resource-limit semantics. The final focused selection passed all 332 tests (`focused-final.xml`).
Independent review accepted with one nonblocking configuration-base follow-up.
The recipe now uses `/etc`, matching the existing compiled adapter recipe and
current FRR installation guidance; the guide states source-version default-path
limits. Focused review verification accepted the correction with `R1` resolved and no
remaining findings. The native commit gate passed; see the delivery record below.

Read-only local-source readiness is `source-readiness.json`. The available FRR
8.0 checkout has tracked topotest symlinks; its original bytes remain unchanged
and it does not satisfy the existing regular-file contract. The separate
[bounded live proposal](frr-source-runtime-validation.md) records that gap and
unselected builder/runtime inputs. It is not execution-ready and requests no
approval or new worker. Pristine FRR source support is not claimed.


## Delivered implementation — 2026-11-04 UTC

Implementation commit: `701ae2c48cfa92daad9220848132fdcca0fc2994`.
Independent broad review and focused correction verification are preserved under
`review-broad/` and `review-focused/` in the evidence root. The accepted frozen
implementation diff SHA256 is `8c47925cef8f0e203ebac6209ddaedb4dabaf3f2565cc3c3f6fbd65b69f1d372`.
The required review-state check matched source/index/Git state before the commit.
The normal native commit hook verified the 34-package locked environment and
passed **3,141 tests, one skipped**, in 337.29 seconds. No hook was bypassed.
`implementation-commit.stdout`, `.stderr` and `.exit` retain the actual local
commit and gate result; its exit is zero.

Final standalone modeled evidence is `modeled-final/REPORT.md`: sixteen distinct
simulated originals, seven modeled builds, a fresh confirmed one-peer/two-route
reduction, unchanged-original recovery, fresh source-boundary confirmations,
eight relocated verification receipts and changed-report refusal. All sources,
images, builds and observations there are simulated. Earlier modeled outputs and
failed fixture checks remain separate and retained. The final source-layout
selection passed eleven tests; the broader focused selection passed 332.

Source/build contracts, source-range preparation, maintainer handoffs, modeled
integrated acceptance and reviewed engine implementation are complete. The
[public source guide](../frr-source-workflow.md) is the maintained entry point.
Live source-build/changed-image/minimization/bisection qualification remains
separate. The [runtime validation record](frr-source-runtime-validation.md)
records the later approved case: one successful source build and independent
static acceptance, followed by a frozen-input prerequisite stop before any
worker. Functional source/changed-image/minimization/bisection qualification
remains unassessed; that stopped case will not resume.

Earlier supplied-image originals and their preservation remain untouched. No
real build, worker, acquisition, upstream investigation, scheduler job, evidence
transfer, push or publication occurred. Policy stays disabled and calibration
deferred. Local checksums and readback do not provide authenticated execution
provenance or independent backup.
