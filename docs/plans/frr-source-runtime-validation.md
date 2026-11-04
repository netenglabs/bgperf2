# Proposed FRR source-build functional validation

Case02 is prepared and independently reviewed, **awaiting separate explicit
execution approval**. No build or worker has started. The original proposal and
read-only findings below remain preparation history; the case02 record is current.
The [implementation plan](frr-source-workflow.md) and
[source guide](../frr-source-workflow.md) own engine delivery and contracts.
The earlier supplied-image pair remains complete; its two workers will not rerun.

## Prepared case02 — 2026-11-04 UTC

Evidence root: `/tmp/bgperf2-frr-source-validation-20261104/`.
The reviewable entry point is `READY-final.md`; exact public argv and conditional
review dependencies are `preparation/case02/commands.json`. The final approval
input manifest is `preparation/approval-inputs02.json`, SHA256
`3faba7eb2f6d0603df42ffde2c08a8271b89f5a9ea6800cd6e7b59c212bb69d9`.
Its closed inputs remain marked `not_authorized`; later approval must be recorded
separately without editing the frozen packet. Local checksums do not authenticate
execution or provide independent backup.

The independent engine/environment copy is pinned at
`ab7d65b2926bb3da9815d45bcb142b4e548fdb46`. Available local FRR 10.3.1 source
`35e662efa7cc9ef3e97a253368950cc1a58f3bc1` was explicitly adapted into
`b7ffb580af3066b05f73fb07f6b6fc56db199d9f`, parented to that upstream object.
The preparation tool materialized 79 topotest aliases only; all 7,804 original
regular files retain exact bytes and Git modes. Independent readback reconstructed
the adaptation and checked 7,989 derived regular files, original checkout/index
preservation, upstream attribution and 7,382 private engine/environment files.
No original checkout, source guard or measurement definition was changed.
This is packaging-adapted source, not pristine-source qualification.

Both selected builder and runtime base are the existing immutable FRR image
listed below. Static local archive inspection authenticated its configuration
and layer hashes and found the existing compiler/autotools, frr/frrvty accounts,
no `/etc/frr.old`, and libyang 2.1.128 matching the selected source's declared
minimum. No container, compiler or source code was executed. The base retains
an existing FRR installation and possible residual modules/libraries; it is
explicitly a mixed base. Build review must inspect fresh installed binaries and
library paths, and both workers must report FRR 10.3.1. No pristine-runtime or
clean-distribution claim follows from metadata or an eventual passing pair.

The concrete scope is one `frr-local/v1` build, requested `-O2 -g`, optimized
declaration and `--disable-doc`, at most 1,200 build-client seconds. Its outer
1,800-second bound includes snapshot/prerequisite overhead, with 15-second
termination grace. After actual independent build acceptance, execute at most
two distinct serial 120-second workers using that one returned target image,
one peer/100 prefixes each, with 240-second outer bounds and 15-second graces.
This means two independent worker observations, not independent source builds.
Zero retries, acquisitions, extra probe containers or scheduler jobs.

Require fresh native guard, exact image/input checks and 16 GiB available memory/
20 GiB free-disk floors before the build and each worker. Readiness observed
50,125,889,536 available memory bytes and 342,326,005,760 free disk bytes;
these are snapshots, not reservations or capacity qualification. Paths are on
root-backed ext4; **a fresh explicit functional-only root-storage exception is
required**. The previous pair's exception does not carry forward.

Actual independent build acceptance precedes the baseline. Baseline acceptance
must establish six passed assertions, exact 100-prefix set, FRR 10.3.1 banner,
valid original/package/budget/exit and owned cleanup before fresh candidate
prerequisites and the second worker. Final acceptance requires all twelve
assertions, distinct originals, verified report/check/status/reconstruction,
report equality, actual exits and semantic foreign-resource reconciliation.
Any failed/missing/uncertain evidence or rejected review stops successors.
Retain partial state; build cancellation cannot prove daemon-side cache work
ended and never authorizes another build or worker.

Tooling review resolved the alias-normalization and image-whiteout findings.
Focused final review resolved the later disposition, one-build pair wording and
host dependency/receipt binding findings, with no blocking defects. Its retained
nonblocking provenance note is explicit: initial unprefixed environment-freeze
receipts came from an earlier unretained helper version. They are historical
records rather than proof of a retained producer. `environment_final.py` then
ran a fresh guard, pinned-head check and two native locked-dependency checks
with exact receipts, its own recorded source hash and unchanged private inputs.
The final verifier also binds/rechecks the named host stdlib, interpreter,
probe-mapped shared libraries and tool bytes; this is not a hermetic-host claim.
All earlier drafts/refusals and case01 remain separate and unselected.

Preparation ran no source build, worker, acquisition or scheduler. The completed
supplied-image pair, raw evidence and frozen delivery remain untouched. No
upstream investigation, remote evidence transfer, push or publication occurred.
Performance policy remains disabled and calibration deferred. Live source-build,
minimization and bisection qualification remain unassessed until separately
approved execution and its actual reviews complete.

## Proposed first live question and natural bounds

Can one explicitly selected compatible local FRR source snapshot be built into
the existing adapter layout and pass the six named functional witnesses in two
independent original observations with verified source-bound targets and reports?
This establishes source/build compatibility, not an upstream bug, fix or timing
effect. A same-source pair is an honest first build integration check; source
fault localization remains a separate later case.

Proposed ceiling: one explicit build command, maximum 1,200 seconds, followed by
two serial original workers, one peer and 100 prefixes each, at most 120 seconds
per worker. Zero retries, acquisitions, version-probe containers or scheduler
jobs. Reuse the one returned target artifact on both sides of the functional
investigation; separate original attempts remain mandatory. Build/client outer
cancellation bounds, daemon-side cache reconciliation and worker outer grace
must be frozen in the final packet before approval.

Select immediate functional validation, advisory activity observations and owned
resource isolation. Keep performance policy disabled and calibration deferred.
After the build, independently verify source/image/log bindings before any
worker. The first original must pass sessions, injection, count, completion,
bounded role health and exact final prefix set, package verification and an
actual independent review before the second starts. Final acceptance requires
both originals, successful report reconstruction/verification, original outer
exit receipts and independent owned-cleanup/foreign-inventory review. Any failed
assertion, refusal, timeout, unknown launch/cleanup, missing receipt, identity
change or rejected review stops successors; preserve partial work without retry.

## Read-only prerequisite findings — 2026-11-04

The existing local FRR checkout `/home/jpietsch/code/frr` was clean on
`stable/8.0` at `3bc7a60a2577a650ebbadab8ed5f0342fba173ea`, with 4,838 tracked
entries. It contains tracked topotest symlinks and therefore **does not satisfy
the current regular-file source contract**. No source files were changed,
materialized, extracted or deleted. A separately selected compatible source or
reviewed explicit packaging adaptation is required before freezing this case.
The source is not the unknown source behind the completed FRR 10.7 image.

The existing image from the completed pair,
`sha256:2ab2018dfe70088f318ee9b9c976bd2fd610580460e1715fe14548042dcc133d`,
is only a possible dependency-bearing builder/runtime input. Its metadata does
not qualify compiler/dependency versions, installed accounts, bootstrap success,
the selected source's libyang compatibility or a source build. No probe container
was started. Toolchain/runtime IDs are **not selected or qualified** for this
case. The final packet must disclose exact compatible immutable bases and
preserve their observed IDs without acquisition or automatic fallback.

The existing generator and prefix-capable sink pins from the completed pair are
candidates only:

- BIRD: `sha256:db0a8e144635b1d4b9f81f24ee78f11383c5b0cbd79f10353edcb8452e9af423`.
- Sink: `sha256:58491f5d3ad4d4872c13d53243f482f3cf7245997991b924990358795212ab38`.

Reinspect final selected images read-only after source/base selection. Their
historical availability is not a reservation. Choose fresh disk-backed build,
work and results roots, frozen engine revision, bounded source plan, exact public
argv and preservation destinations. Record resource floors and storage policy;
the prior root-storage exception does not carry forward. Freeze the final
source trust, build/worker budgets and review/stop graph for separate execution
approval. Do not ask to execute this incomplete proposal.

Live source build, changed-image comparison, minimization and correctness
bisection remain unqualified. No upstream investigation is resumed. No build,
worker, acquisition, evidence transfer, push or publication has occurred here.
