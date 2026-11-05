# FRR combined-controller functional validation

Selected by the operator after controlled localization at `76990e2`: push the
committed branch and validate the public comparison command and combined FRR
bisection build/run/cache path. The initial push completed at `76990e2` with
normal hooks enabled (3,141 tests passed, one skipped). Six concurrent engine
source/test edits remain outside the clean pinned runtime checkout and are
preserved. This is a fresh case; completed or stopped cases were not resumed.

## Scope and fixed inputs

Runtime engine: `76990e2bf487ad8acbee87c5fc68457ebae62abd`. Local evidence:
`/tmp/bgperf2-frr-controllers-20261105/`. New independent local engine/source
copies and new source plans bind one peer/two prefixes to the existing controlled
packaging-adapted FRR 10.3.1 history:

- good endpoint `b7ffb580af3066b05f73fb07f6b6fc56db199d9f`;
- neutral midpoint `4bc2f0429e904cc6c5b504bc56deffad2884fd65`;
- deliberate bad endpoint `ea5d46e6d07a0a427df80092ac0914a87ed79438`.

The last revision substitutes `100.0.0.1/32` with `198.18.0.1/32`, preserving
count. Candidate means explicit rollback, not an upstream defect/fix claim.
Earlier packaging adaptation materialized 79 tracked aliases; pristine FRR
source remains unsupported by this regular-file source contract. Source
attribution, patches and earlier evidence remain retained.

The fixed `frr-local/v1` controls are optimized declaration, requested `-O2 -g`,
`--disable-doc`, two make jobs and no network/pulls/package installation.
Builder/runtime base is existing mixed image
`sha256:2ab2018dfe70088f318ee9b9c976bd2fd610580460e1715fe14548042dcc133d`;
BIRD generator is
`sha256:db0a8e144635b1d4b9f81f24ee78f11383c5b0cbd79f10353edcb8452e9af423`;
sink observer is
`sha256:58491f5d3ad4d4872c13d53243f482f3cf7245997991b924990358795212ab38`.
Mixed-base residual modules/libraries/build tree, compiler/configure/daemon
warnings and nonhermetic/nonreproducible limits remain explicit.

## Execution and acceptance — completed 2026-11-05 UTC

Exactly three public native source-build invocations and nine distinct fresh
original workers completed, with zero retries, acquisitions or probe containers.
Source-range verification and four modeled admission/accounting/trajectory checks
passed before runtime. The final frozen packet SHA256 is
`6434f76eec85671d28bba2ebc64568ded0807dc1f50faddac117f3a4569cb17f`.
The earlier preparation packet/config version is retained as preparation history;
no runtime used it.

| Public execution path | Fresh workers | Observed outcome |
| --- | ---: | --- |
| Five separate bisection `step --execute` calls | 5 | good0, bad2, good1, fresh good1, fresh bad2; adjacent boundary confirmed |
| One `recipes.py compare` command, two alternating pairs | 4 | bad baseline, good candidate, good candidate, bad baseline; all originals completed |

Bisection began with an empty cache. Its first three steps invoked the native
builder for indices 0, 2 and 1; Docker compilation was cached in all three.
These are three new public build invocations, not three fresh compilations.
The final two steps hit the native build cache without changing cache files,
while producing distinct fresh worker IDs. No cache entry was preseeded, no
execution backend injected, and no externally collected result imported.
Every target retains the exact new recipe/source/build-plan bindings.

The freshly confirmed adjacent boundary is
`4bc2f0429e904cc6c5b504bc56deffad2884fd65` →
`ea5d46e6d07a0a427df80092ac0914a87ed79438`.
There are no pending reservations, skipped or ambiguous trials. All five trials
use the public combined single-step controller. The full-search `run --execute`
loop remains outside this case.

Static image audits recomputed config and all layer hashes from retained sealed
exports of the exact returned physical images, including fresh installed
bgpd/vtysh/libfrr paths after the mixed runtime base. Those exports are audit
inputs, not reused worker observations. All originals reported FRRouting 10.3.1
and the selected immutable role images.

Across nine six-assertion evaluations, 50 assertions passed and four intentionally
failed only `observer.prefixes`. Every bad original had exactly the declared
one-prefix substitution and count two; all other witnesses passed. Every good
original passed all six. No unexpected failure, timeout or worker retry occurred.
Native worker durations were 11.73–14.38 seconds, within the 120-second limit.
Actual combined-step outer durations were 13.89–47.34 seconds; comparison took
74.63 seconds, within their declared limits. All selected command exits were zero.

All originals have empty cleanup_errors. All 27 owned container IDs and nine
attempt network scopes were absent, with foreign public identities and semantic
mount/network/label sets unchanged. Monitor/socket 0700/0666 metadata was checked
using lstat only. Background activity and warnings remain retained; timing,
CPU and memory are descriptive observations without a performance conclusion.

Native comparison and bisection verification passed. Physical reconstruction
matched 179 comparison files and 230 bisection files. Separate byte-identical
relocations also passed both native verifiers and full file/coverage checks.
`final-readback.json` records the completed finite graph and 112 operation
receipts. A separate offline reconstruction from original packages, native
journals/classification and cache bytes verified all nine identities, all 54
assertion rows and 387 original/package artifact bindings. This is a separate
local verifier, not an external independent reviewer or execution authentication.

The finite runtime budget is consumed and a permanent case stop forbids further
builds/workers. Local full-case preservation/readback covers source Git,
environment, build inputs/archives/logs, original work/packages, cache journals,
reports, receipts and native endpoint metadata. Preservation records at the case
root are authoritative for final seal/readback status. Earlier source/evidence
remains unchanged. Checksums are neither authenticated execution provenance nor
an independent/off-device backup; no evidence was transferred remotely.

## Protocol and limits

The operator selected immediate functional-only execution and continued the
explicit root-backed `/tmp` development-storage convention. Native idle guard,
input/image/dependency checks, advisory activity/storage snapshots and 16 GiB
available-memory/20 GiB free-disk floors preceded each combined step and the
combined comparison. Admission was under 300 seconds old at command launch.
These are command-level checks; they do not claim fresh external admission
between an internal build/worker or between comparison originals. Native recipe
prechecks, host coordination and cleanup remained enabled.

Per build: native 1,200-second timeout. Per worker: native 120-second timeout.
Combined build/worker step outer limit: 2,100 seconds; cache-hit step: 240 seconds;
four-worker comparison: 960 seconds. Outer cancellation has 15-second TERM grace
and bounded KILL/reap; native worker groups retain native cancellation/cleanup.
No timeout occurred; Docker daemon-side build termination remains unqualified.
No development/build/analysis overlapped a selected active worker. No quiet-CPU
wait, hourly scheduling or performance qualification was introduced.

Comparison owns its four serial originals and records their status. The six-row
case acceptance checks occur after the combined command returns; this is not a
new between-original assertion gate. Two alternating pairs exercise the selected
functional ordering/repetition controller, not statistical repetition adequacy.

This case qualifies the selected FRR combined single-step build/run/cache path
and alternating comparison controller. It does not qualify the all-steps search
loop, continuous daemon health, crash predicates, cancellation/recovery failure
paths, broader source versions, pristine/hermetic/reproducible builds, statistical
sensitivity or performance policy. Upstream investigation stays paused,
performance policy disabled and calibration deferred.
