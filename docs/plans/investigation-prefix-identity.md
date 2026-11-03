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
