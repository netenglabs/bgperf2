# Milestone C controlled repeatability validation

Prepared and executed 2026-10-27. **Approved case permanently stopped after
worker 1 for outside CPU activity.** One optimized build and one worker completed;
31 workers remain never run. The approved procedure below is retained as the
frozen protocol; the [execution record](#approved-execution-stopped-at-first-review--2026-10-27)
supersedes its preparation handoff. All runtime authorization is consumed.
The operator selected a **10% slower observer delivery window** as the practical
calibration target. This means the separately defined
[10%-to-90% observer count-crossing window](../observer-timing.md), not legacy
elapsed time or isolated target processing. It is not a regression cutoff.
Performance policy remains `disabled`, qualification `not_assessed`.

This is the next case after the completed
[noise/resolution discovery](milestone-c-calibration-proposal.md#hourly-resolution-discovery-completed--2026-10-26-1400-pdt-job).
That document preserves discovery history; this one owns the new procedure.
Milestone D's confirmed count-fault boundary is complete and supplies no new
runtime authorization. All earlier runtime authorizations are consumed.

## What the completed pilot establishes

The read-only audit verified the original eight-attempt A/A report (322 files)
and reconstructed all eight observer supplements from their original packages
and assertions. These are **four natural pairs**, not eight independent pairs.
All source hashes remained unchanged. Offline apparent A2/A1 window differences
are −25.13%, +40.17%, +71.14% and +1.24%. Actual crossing uncertainty is much
smaller: the maximum supplement bracket width is 1.651% of its lower bound.
These bounds describe timestamp crossings, not statistical confidence intervals.

Both roles used the same supplied image, but instrumentation was unknown,
pinning absent and outside CPU work recorded throughout. The ordinary report
correctly withholds controlled differences. These exploratory ratios diagnose
repeatability under those confounded conditions; they establish no version
ranking, controlled performance effect or powered sample size. Do not override
that report or pool this pilot with changed build/placement/host conditions.

Audit, CSV, figure, unchanged-input hashes and verification commands remain
outside Git at `/tmp/bgperf2-c-calibration-next-20261026`. Original evidence
remains at `/tmp/bgperf2-c-resolution-hourly-20261026/jobs/20261026T2100Z`
and its adjacent preparation. Original work and D evidence are unchanged.

## Fixed scope and inputs

One optimized source build, then **two separately gated blocks of eight A/A
pairs: at most 32 serial workers**. Both target labels A1/A2 must use the same
actual built immutable image and identical source/build provenance. No A/B
ranking or performance bisection is included. Sixteen pairs are a bounded
repeatability study, **not** a validated sample requirement for detecting 10%.

| Input | Frozen choice |
| --- | --- |
| Engine | Clean `milestone-a-newcomer` in `/tmp/bgperf2-milestone-a`; freeze final documentation commit in packet |
| Recipe | [comparison-repeatability-control.yaml](../../examples/recipes/comparison-repeatability-control.yaml), cell `8d043e8dc2f9f660` |
| Workload | BIRD target and generators, sink observer; two peers × 1,000,000 prefixes, 2,000,000 total; no filters, churn or receivers |
| Source | Trusted packaging-patched BIRD revision `ff132d4180f8f56882f0e977cd979992e9eb3b64`; clean local clone from retained D history |
| Source snapshot | `526022eb0dea09be71b98c60f0582e0ba30a06388baf3692e132b2cd5176d249` |
| Build | `bird-local/v1`, `instrumentation optimized`, compiler/linker `-O2 -g`, no additional configure flags; network none, no pull/install |
| Builder/runtime/generators | Existing `sha256:db0a8e144635b1d4b9f81f24ee78f11383c5b0cbd79f10353edcb8452e9af423` |
| Observer | Existing `sha256:311317014fc98e2cadf46941b4b23dab9dd724281dd50167a0f9187d8ac08f19` |
| Diagnostics | `none`; exactly session, injection, observer-count and experiment-completion worker-budget assertions |
| Build budget | Exactly one public build invocation, at most 1,200 seconds |
| Worker budgets | At most 32 unique original attempts, 120 seconds each; 3,840 worker seconds |
| Combined budget sum | 5,040 seconds (84 minutes); admission, reviews, collection and cleanup are additional, not a wall-clock promise |

Build flags are requested configuration, not proof of emitted optimization.
Independently review build.log and actual compiler/linker commands and image
identity before binding comparisons. Record any Docker cache reuse truthfully.
Binary SHA and reconstructibility remain unestablished under the current build
contract. Existing supplied images must not be relabeled as optimized targets.
The generated comparison plans remain pending until the real build returns its
image ID; no hypothetical digest is an executable target.

The opt-in recipe pinning implementation is `69ac253`, following the pure-helper
extraction `eca7c2d`; independent code review accepted both. Feature validation:
337 focused checks and the full 2,454-test commit gate passed. Absent-pin recipe
identities remain unchanged. Live effective placement is still unvalidated.

## Host and storage admission

Candidate is **jpietsch-server**, otherwise idle; `9950` remains excluded.
No host is qualified by this proposal. The old light-work/concurrency and
functional root-disk exceptions do not carry forward. Seek a new explicit
root-backed persistent storage exception **limited to this repeatability case**:

- Work: `/home/jpietsch/bgperf-work/2026-10-c-repeatability-control-01`.
- Results: `/home/jpietsch/bgperf-results/2026/2026-10-c-repeatability-control-01`.

These are proposed new destinations, not directories created during preparation.
Home, Docker and packet backing mounts must be inspected again. `/dev/sda5`
is the observed root-backed ext4 volume; this is not independent backup or
full performance-host qualification. Preserve all original source/work/evidence.
No remote transfer, push, provisioning, download or unrelated cleanup is included.

Before the build and every worker, run the active-measurement guard, inspect
measurement locks and all-UID activity, and require six five-second host-wide
CPU intervals spanning 30 seconds. Each interval must have at most one logical
CPU equivalent busy in aggregate, with no competing build, benchmark or heavy
job. Check aggregate `/proc/stat` as well as processes: root-owned work must not
be invisible to admission. Wait for heavy jobs to finish without interrupting
them. A read/probe failure refuses execution. This selected operational idle
rule is not a performance threshold or a promise of zero interference.

Require at least **48 GiB MemAvailable and 64 GiB free disk** before build and
each worker; stop successors below **16 GiB** during a worker. These are
protective reservations, not demand estimates inferred from smaller runs.
Recheck topology, CPU model/governors, kernel, Docker identity and image IDs;
record lab/research/engine revisions separately. Changed facts need review.

The selected layout is
`target=0,16,monitor=1-2,17-18,testers=3-14,19-30` on the observed 32-logical-CPU
host with SMT siblings i and i+16. Target, observer and generators occupy
distinct physical cores. Revalidate all package/core/sibling identities before
use; an online-ID check alone cannot prove this. CPUs 15/31 are unassigned to
containers; controller and kernel work remain unrestricted. Verify requested
and effective cpusets for **every** live role after worker 1 before worker 2.
Stop if that evidence is absent or differs. Pinning does not establish isolation
or prove which component limits delivery. The existing lifecycle resolves live
container PIDs/cgroups before the bench clock and retains per-container requested
and effective cpusets in the raw `role_cpu` section even with diagnostics none.
Review that retained capture after worker 1, bound through its verified package
and owned container names to the original attempt/scenario/provenance; require
the three expected containers: target, monitor and one tester container hosting
both peer processes. Missing/extra members or unknown/different placement stop
successors. Apply the same retained-evidence gate after every worker. This is not a request to
inspect containers after the step has already cleaned them up.

## Frozen order and execution gates

Use public [staged comparison commands](../comparison-execution.md), never an
unbounded `compare` loop or scheduler. Before data, fix these shuffle seeds:

| Block | Seed | Per-pair A1/A2 order |
| --- | --- | --- |
| 1 | 20261027 | AB, AB, BA, BA, BA, AB, AB, AB |
| 2 | 20261028 | BA, BA, BA, BA, BA, AB, AB, BA |

A means A1/baseline, B means A2/candidate; each pair contains both. These orders
are predetermined, not exactly balanced and not selected after outcomes. They
do not select a statistical test. Preserve block and position effects.

Preparation packet includes `prepare_control.py`, `selected-effect.json`,
`study-design.json`, `pressure.json`, topology snapshot and offline command logs.
After the final clean commit, regenerate into a fresh `final-inputs` directory.
It exports the recipe/four assertions and optimized source-build plan without
Docker/build/worker activity. Early failed preparation logs remain preserved.

Only after new execution approval:

1. Revalidate clean pinned engine/environment, packet hashes, host/storage and
   exact existing images. No installation, acquisition or source repair.
2. Run `recipes.py target-build final-inputs/build-plan.json` with a new owned
   output directory and `--timeout 1200`. Independently review actual source,
   commands/log, observed bases, image and cleanup. Failure stops this case;
   daemon-side build work may outlive a timed-out client and must be checked.
3. Run packet `bind_built_target.py INPUTS BUILD_OUTPUT NEW_PLAN_DIRECTORY`.
   This offline helper requires successful optimized local-source provenance,
   exact source/recipe/flags/bases/log binding and unchanged engine, copies only
   distinct A1/A2 labels, and freezes both public plans with the actual image ID.
   Review generated identities, order, assertions and budgets before worker 1.
4. `comparison-start` block 1 with new block-specific work/result roots,
   `--observer-window --pressure-policy PACKET/pressure.json`. Issue exactly
   one `comparison-step` at a time. Independently review first checkpoint before
   recording `first_review` acceptance. Inspect every subsequent worker's
   completed synchronous assessments and host records before issuing its successor.
5. Require the normal observer screen: conservative lower ≥1 second, crossing
   width ≤5% of lower, ≥10 increasing interior records. Do not change sampling,
   scale the workload, pad elapsed time or reinterpret a failure. Assess the
   actual crossing bounds against the 10% planning target descriptively;
   a passed resolution screen is not demonstrated detection ability.
6. Independently accept block 1's final portable report, cleanup and host
   observations. Start block 2 only after fresh host admission and its accepted
   `--prior-review .../block-1/reviews/final.json`. The same recipe and baseline
   target are mandatory. Repeat first/final reviews and per-worker gates.
7. Retain all failed/interrupted/completed and never-run entries, original
   packages, assertions, supplements, reports, command arrays, reviews, source
   and resource inventories. Verify reconstruction and hash/type coverage.
   Independently review final accounting and owned cleanup before documentation.

The selected pressure policy samples every second (maximum gap 2.5 seconds),
with busy ≥75% AND CPU PSI some avg10 ≥20% for two consecutive intervals, or
MemAvailable below 16 GiB, stopping the owned controller. Missing coverage or
monitor failure also stops. This is a severe-pressure protection, **not** the
idle gate. Its overhead remains uncalibrated and must be held fixed/recorded.
After each worker, recorded foreign CPU above 100% of one logical CPU blocks
successors even if the severe-pressure screen passed. Any nonzero foreign CPU
may still withhold ordinary controlled deltas; preserve that decision. Inspect
all-UID and aggregate host records rather than relying on one metric.

Any unexpected assertion, timeout, verification, resolution, placement,
monitoring, capacity or cleanup failure stops the case permanently. Wait for
owned collection/cleanup, retain evidence and leave unused budget never run.
No warm-ups, retries, extensions, alternate workload or adaptive exclusions.
Do not kill unrelated work. No code changes, development or analysis run on
an active measurement host; required synchronous worker assessment remains
part of the explicitly reviewed runtime workflow.

## What remains before calibration is complete

Report all 16 natural pair ratios and crossing bounds, variation within each
block, order effects and differences between blocks. Use the exact interval
ratio bounds documented in the retained audit. No formal confidence interval,
false-positive/power claim or threshold is selected here. Pairing and repeated
measurements require an explicit analysis consistent with their dependence;
see [NIST paired observations](https://www.itl.nist.gov/div898/handbook/prc/section3/prc311.htm)
and [repeatability conditions](https://www.itl.nist.gov/div898/handbook/mpc/section4/mpc441.htm).

After this case, separately choose the estimator, acceptable false-positive
rate/power, missing/outlier/ordering rules and a justified sample budget for the
selected 10% effect. Require suitable known-effect positive controls and
independent held-out validation before implementing/enabling a named regression
policy. These decisions may reveal that different instrumentation, workload,
placement or hardware is needed. Do not automatically extend this study.

Independent review accepted the fixed design, source/build binding helper,
seed sequences, retained live-placement evidence gate and audit figure. Final
inputs must be regenerated and verified at the clean documentation commit.
Preparation at `2b15281` ran **zero builds and zero workers**. The subsequent
explicitly approved execution is recorded below. This protocol does not authorize
a new case, a retry or use of its unrun budget.

## Approved execution stopped at first review — 2026-10-27

The operator approved the exact one-build/32-worker case and renewed intentional
root-backed persistent storage exception on otherwise-idle `jpietsch-server`.
Later clarification said there was no reserved quiet window and ordinary work
was running; it neither relaxed admission nor authorized concurrent heavy work.
Engine remained clean at `2b15281a97a55f643e0def790505578fd4d72fde` throughout
the build and worker. No scheduler or automatic benchmark loop was installed.

Read-only admission waited through ongoing and newly started foreign work.
Build admission 177 finally passed six five-second intervals spanning 30 seconds,
with 0.255–0.757 logical CPU equivalents busy and at least 56.8297 GiB available
memory. Fresh all-UID process/resource review and the locked 34-package environment
check passed. CPU model, all physical/core/sibling identities, governors, kernel,
Docker identity, immutable images, packet hashes and selected persistent ext4
storage on `/dev/sda5` were checked. Protective reservations remained operational
limits, not demand estimates or host qualification. An initial sandbox socket
refusal and a separately scoped process snapshot remain honestly recorded; only
host-side checks qualified execution. Heavy jobs were never interrupted.

**Build:** exactly one public `target-build` invocation completed in 21.263
seconds under its 1,200-second limit, producing immutable image
`sha256:8cc3a97c01b7dd3aa188fb040067aeb70244fd4382183fb5763cb09d5db12f88`.
Independent review matched all 481 regular source archive files to the selected
clean `ff132d4` checkout, the full frozen plan and source/patch/Dockerfile/log/base
identities. Three setup layers used Docker cache; configure, compilation and
linking actually ran. Logged CFLAGS were `-O2 -g -pthread -fno-strict-aliasing
-fno-strict-overflow`, and LDFLAGS `-O2 -g -pthread`. This is optimized code with
debug symbols; binary SHA remains null and reconstructibility false. Both A/A
plans then bound the actual image with A1/A2 labels only, retaining all provenance.
Independent plan and build/cleanup reviews accepted those bindings.

**First worker:** fresh admission 002 passed six intervals of 0.161–0.332 busy
CPU equivalents with at least 57.1281 GiB available memory. An earlier accepted
worker admission expired during final process review and was refreshed without
launching a worker. The first public `comparison-step` completed in 66.293
seconds; its original worker budget records 60.865264169 of 120 seconds used.
Original attempt `bgperf_recipe_a8b79b7d4cf947fc8cc9bca648e256c9` passed all four
assertions: two sessions, two injection witnesses, exact 2,000,000 observer
prefixes and completed experiment; no tester errors/timeouts. Its package
verifies 39 artifacts, checkpoint 42 files, and observer supplement reconstructs.

Live per-container evidence confirms the exact requested/effective CPU layouts
for target, monitor and the one tester container hosting two peer processes,
with the correct attempt-owned names and no read errors. Thus portable pinning
has live functional evidence for this worker. The observer window spans
1.594992592 seconds, with conservative crossing bounds
[1.570661986, 1.604230381] seconds, width 0.033568395 seconds and 147 increasing
interior records. Its resolution screen passes; these bounds are not statistical
confidence intervals or a performance conclusion.

**Independent continuation gate: REJECT.** Outside CPU peaked at
**173.97100570003434% of one logical CPU**, above the frozen 100% successor cap
(CSV rounds to 174%). The peak names six Python processes at 105.70%, one Deno
process at 43.39% and three Codex processes at 9.55%; these are leading contributors,
not the entire total. The passing prelaunch idle window does not qualify later
foreign work. The separate severe-pressure screen correctly passes its different
rule: 65 observations, maximum host busy 21.1122%, CPU PSI zero, minimum available
memory 53.9451 GiB and maximum observation gap 1.02193 seconds. It cannot override
the stricter outside-CPU successor gate.

Worker execution stopped permanently before any successor or documentation edit.
The external permanent-stop marker blocks the coordinator, and the public
`comparison-review --decision rejected` receipt stops block 1; its exit 5 records
rejected continuation, not a failed worker experiment. Block 2's prior gate was
never reached. Accounting is **one completed build, one completed worker, zero
failed worker experiments, 15 block-1 plus 16 block-2 workers never run**. No pair
completed; no variance, repeatability, power, 10%-effect detection or version
ranking is established. Performance stays `not_assessed`, policy `disabled`.
There is no retry, resume, extension, exclusion or additional build/worker.

**Cleanup and preservation:** all 71 pre-existing container identities/states,
six networks and 495 volumes match before/after; Docker identity and all 45
image inventory lines are unchanged during the worker. The build added only its
approved image/tag. Runtime `cleanup_errors` is empty; all 36 original work files
match packaged hashes. Original work, evidence, failures and unrelated resources
remain intact. No broad cleanup, download, provisioning, 9950 access, remote
transfer or push occurred.

Original work is at
`/home/jpietsch/bgperf-work/2026-10-c-repeatability-control-01`; results at
`/home/jpietsch/bgperf-results/2026/2026-10-c-repeatability-control-01`.
The latter retains `preparation`, `plans` and `block-1`; it will retain the final
`runtime-evidence` copy after the last writers finish. Original coordinator evidence remains at
`/tmp/bgperf2-c-repeatability-runtime-20261027`; original preparation and prior
C/D evidence are unchanged. All 561 preparation file hashes verify in both local
copies. Final preservation inventories and archive coverage/checksums are pending
the last writers and will distinguish regular files from retained socket types. This is
local preservation on the same root-backed device, not independent backup.
Independent reviews, accounting and the reviewed local documentation commit are
retained with runtime evidence. No new runtime is implied; a further study needs
a concrete reviewed case and fresh execution approval.
