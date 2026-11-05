# Received-prefix correctness in functional investigations

Selected 2026-11-03 after the successful single-run real-BIRD 100-prefix
validation. The operator requested capture for both baseline and candidate,
separate count/identity results, preserved partial/unavailable evidence and
offline validation, followed by preparation of a small direct functional pair.
The upstream source-bug investigation remains paused.

## Implemented scope

- `investigate --observer-prefixes` validates the existing capture bounds before
  host checks or directory creation, records opt-in selection in the controller
  plan and forwards it to each serial attempt. Defaults do not acquire a new
  runner argument, plan field or report view.
- The optional `correctness` report view evaluates all six existing assertions
  separately for each verified result package. Count equality and exact prefix
  identity have separate rows and outcomes. Recipe reproduction assessment and
  controller exit meanings remain unchanged and explicitly distinguished.
- Missing packages retain their original reason and an inconclusive entry with
  no invented assertions. Missing, malformed or unavailable capture remains
  unmeasured through the existing evaluator. Original experiment statuses,
  controller stops, package identities, image bindings and cleanup remain intact.
- Report-only evaluation starts no capture. Verification reconstructs the view
  from bundled packages with strict selection/type checks; rewrite/re-hash of
  a summary or prose cannot create a valid false assertion pass. Rebuild and
  storage-backed relocation retain the selected view and original attempt IDs.

The view records evaluation intent, not authenticated user intent or proof of
capture. Omitting the optional view remains possible when creating an unselected
report. It must never be represented as an identity pass. Older reports keep
their default schema/prose; older engines refuse a new optional correctness field.

## Validation and delivery

Focused offline fixtures cover correct sets; equal-count substituted prefix;
old, missing and unavailable capture; missing sides and controller stops;
nonboolean selection; pre-probe bounds refusal; altered/rehashed summaries and
prose; strict nested boolean/integer semantics; stored/relocated/rebuilt reports;
both CLI selections; symmetric forwarding and unchanged default kwargs. A
rendering regression requires one contiguous table containing six rows per side.
Fixtures are explicitly simulated observations, not an upstream routing defect.

Independent source review, actual focused/native gate results and local commit
are retained under `/tmp/bgperf2-investigation-prefix-20261103/`. The public
[investigation guide](../investigations.md#optional-received-prefix-correctness)
owns exact CLI usage and result interpretation.

## Bounded real functional pair preparation

Prepare one same-image A/A control using the already available BIRD 2.19.2
target/generator and sink 0.2.0 IDs from the earlier successful case. Both sides
must be distinct original attempts with the same recipe and observer, six
passing assertions, exactly 100 expected IPv4 prefixes and verified packages,
report/prose, permissions and owned cleanup. Labels distinguish sides but do
not claim a binary change or fixed bug. No source build or version probe is
needed. The exact case commands, immutable source/image identities, destinations,
capacity/storage decision, budget, expected outcomes and recovery belong in a
fresh reviewed execution packet after the implementation commit.

Proposed ceiling: two serial workers, each 120 seconds, with one 600-second
outer controller deadline and bounded termination/cleanup. This is a small
functional protocol: record ordinary concurrent activity instead of hourly
CPU-idleness waiting, retain native active-measurement isolation and declared
16 GiB available-memory/20 GiB free-disk floors. The outer deadline may stop
before both positions execute; timeout/unknown launch is terminal and requires
inspection, not a repeat or use of leftover positions. A fresh explicit approval
is required before real workers run. No automatic retry follows partial work.

No build/probe, image/package acquisition, infrastructure, evidence deletion,
push/publication or remote transfer is included. Capture remains one final
snapshot and has uncalibrated overhead. Repeated comparison/bisection capture,
broader workload/UID qualification and timing-policy activation are separate;
performance policy stays disabled and formal 10% calibration deferred.

## Approved direct pair completed — 2026-11-03 UTC

Implementation commit `cb7b1d1` passed 2,803 tests with one optional skip and
independent code review. The separately reviewed case then received explicit
approval for two serial workers and its functional-only root-storage exception.
The immediate functional protocol ran directly, with no scheduler, builds,
version probes, acquisition or retry. A private clean source checkout retained
that implementation revision independently of subsequent documentation changes.

Both distinct original attempts completed: baseline
`bgperf_recipe_17cf2791a07d47fa97f3ed9675a1c0f6` in 11.332393 seconds and
candidate `bgperf_recipe_334759fbf957481bad64ed3cd2c40fd4` in 12.033889 seconds,
within their respective 120-second worker budgets. The outer controller exited
normally with status `recorded` in 30.133623 seconds, below its 600-second
deadline. The report has no controller stop and records
`same_observed_reproduction` separately from correctness.

Each side passed all six assertions: sessions, injection, exact count,
completion, observed role health and exact prefix identity. Both snapshots
contained all 100 expected prefixes with zero missing or unexpected. Public
verification accepted 45 artifacts per original package and 96 files per
investigation report. Independent per-side assertion exports agreed. The
separate rebuilt report verified with the same correctness view and original
attempt identities. Original monitor directories were collector-owned mode
0700; retained socket endpoints were mode 0666. Both runtimes reported no
cleanup errors; native inventories are retained for owned-resource reconciliation.

Case inputs, mandatory controller-completion acceptance addendum, approval,
actual command exits, original work/packages, rebuilt report and review evidence
remain under `/tmp/bgperf2-investigation-prefix-20261103/`. The frozen packet
and preparation records remain unchanged. Shared-store references still require
the retained local artifact store; local checksums do not constitute a backup.

This qualifies the selected two-side capture/report/rebuild path for the existing
BIRD 2.19.2 target/generator image and sink 0.2.0 observer, one peer and 100 IPv4
host routes. Both labels used the same image. Ordinary foreign CPU was recorded
(reported maxima 309% and 311%); worker durations are budget observations, not a
performance comparison. The case establishes no changed-binary or upstream-fix
verdict, continuous correctness, new workload/UID qualification or calibrated
capture overhead. The upstream investigation stays paused; repeated comparison
and bisection capture remain deferred, performance policy disabled and formal
10% calibration deferred. The two-worker allowance is consumed.
