# Proposed FRR source-build functional validation

This is a preparation proposal, **not an execution-ready or approved case**.
The [implementation plan](frr-source-workflow.md) and
[source guide](../frr-source-workflow.md) own engine delivery and contracts.
The earlier supplied-image pair remains complete; its two workers will not rerun.

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
