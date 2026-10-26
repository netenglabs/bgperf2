# Milestone C calibration pilot proposal

Prepared 2026-10-23. Status: prior A/A pilot blocked A/B; revised experiment authorized once for 2026-10-25 13:00 PDT, refused at host admission with zero attempts. Milestone C's implementation and
controlled reports authorize no real performance trial or policy activation.
The [comparison guide](../comparisons.md) owns command and accounting semantics.

## Decision needed before a real pilot

Select an otherwise idle, qualified existing host and suitable persistent work
storage, plus the effect size that matters for each intended measurement. The
previous development-host concurrency and small-run root-disk exceptions covered
functional validation only and are consumed. `9950` remains excluded. No host
is provisioned or qualified by this proposal.

Recommended first scope is a noise/resolution pilot, retaining a disabled
regression policy. Use the existing supplied BIRD/sink images below after exact
read-only availability checks, without downloads, builds or repairs. Supplied
binary instrumentation stays `unknown`; this pilot cannot silently certify an
optimized build. A later calibrated policy needs reviewed build/instrumentation
and host controls as well as appropriate effect sizes and sample requirements.

| Role | Immutable local image ID |
| --- | --- |
| Baseline and both generators | `sha256:db0a8e144635b1d4b9f81f24ee78f11383c5b0cbd79f10353edcb8452e9af423` |
| Candidate | `sha256:7f60bf1483ccf766c768f0a3d894b52176748a4d76f9d18cc9af8730520b9142` |
| Both observers | `sha256:311317014fc98e2cadf46941b4b23dab9dd724281dd50167a0f9187d8ac08f19` |

The proposed [pilot input](../../examples/recipes/comparison-pilot.yaml) selects
two peers, 100,000 prefixes per peer, total 200,000 prefixes. Its single cell is
`b715828f2e681c25`; export selection was checked offline. This is a proposed
existing synthetic workload, not a measured resource estimate or promised timing
resolution. If it is too short for the legacy whole-second monitor clock,
record that limitation and stop; do not scale or extend automatically.

## Proposed bounded procedure

After separate explicit authorization, use a clean checkout pinned to the final
implementation commit, its existing locked environment and new owner-only local
artifact/work/result roots. Record revisions, exact image inspections, host/kernel,
CPU affinity, mounts/capacity and before/after resource inventories. Require the
normal active-measurement guard and verify no ordinary concurrent work. Missing
prerequisites stop the procedure without acquisition or repair. Storage floors
and available memory must be reviewed for this workload; earlier smoke floors
are not extrapolated as estimates.

Export one recipe from `examples/recipes/comparison-pilot.yaml`, test
`comparison-pilot`, cell `b715828f2e681c25`, using the exact baseline, generator
and observer IDs above and the clean engine revision. State the question as
noise/resolution discovery, not improvement or bug-fix proof. Export the explicit
four worker-budget assertions shown in the comparison guide, excluding optional
final health snapshots for the `none` diagnostic mode. Keep their bound
specification unchanged across both comparisons.

Create baseline and candidate target declarations with `--instrumentation
unknown`. Also create a second baseline-image declaration with a distinct
descriptive label for the A/A control. Freeze two plans with the public
`comparison-plan` command:

| Series | Selected targets | Order | Repetitions per role | Worker budget per attempt |
| --- | --- | --- | --- | --- |
| A/A noise control | Baseline versus the same baseline image | `alternating` | 4 | 120 seconds |
| A/B supplied versions | Baseline versus candidate | `alternating` | 4 | 120 seconds |

The proposed total is 16 serial attempts, with at most 1,920 seconds (32 minutes)
of worker budgets. Probe, collection, cleanup and packaging overhead remains
additional and is recorded separately. Four rounds are a bounded discovery
budget, not validated statistical power or an accepted repetition requirement.
Use distinct new roots for each series. Execute the A/A plan first and verify
its portable report before starting the A/B plan. The runner stops on the first
unexpected setup/harness/noncompleted/inconclusive outcome. After the A/A
sequence, independently inspect its report: failed correctness assertions,
failed verification, resource-cleanup problems or inadequate measurement
resolution block the A/B series. The current runner does not automatically
stop a completed sequence on assertion or resolution findings; those are an
explicit between-series review gate. Apply the same report review after A/B.
Do not retry, extend budgets, scale workloads or repair automatically.

Independently inspect individual counts, failures versus never-run work,
sequence/host/image identities, signed descriptive differences, missing memory,
CPU sampling and clock resolution. Source/instrumentation unknowns remain
confounders even if the machine is idle. Distributions remain inspectable;
controlled deltas will be withheld. Make no regression, version-ranking, leak or
hardware-qualification claim from the pilot.

Preserve all original work, ledger, packages, commands, versions and
checksum/coverage manifests locally. Independently review owned cleanup and
unchanged unrelated resources, then record findings and limitations with local
documentation commits. No evidence removal, remote transfer, push, paid
infrastructure, source build or `9950` access is included.

## Policy remains a separate decision

Use the pilot only to assess whether these instruments and workload can resolve
the operator's selected practical effect sizes and what additional controlled
evidence is needed. Do not derive a universal percentage threshold or activate
a regression policy from four rounds. Instrumentation/build provenance,
repetition requirements, ordering, outlier/missing-data treatment and resolution
must be explicitly reviewed before a named policy can be implemented and
validated. Milestone D's deterministic crash/correctness work can be developed
without enabling performance bisection or running this pilot.

## Authorized pilot prerequisite refusal — 2026-10-24 UTC

Operator authorization on 2026-10-23 selected `jpietsch-server` only after an
idle-host check, the three pinned images above, and an explicit root-backed
persistent disk exception for this bounded noise/resolution pilot. Scope was
four alternating A/A rounds, then four alternating A/B rounds only after the
independent A/A review gate: at most 16 serial attempts, 120 worker seconds each,
`diagnostics none`, and the four worker-budget assertions from the comparison
guide. No retries, extensions, repairs, downloads, builds, provisioning, remote
transfers, `9950` access or push were authorized. Regression policy stays disabled.

The clean existing `milestone-a-newcomer` branch was inspected at engine
`3dc9ba08699f0be69cbe01d2ded1be85dc8dbf85`; lab context was
`48bcb97bee71cd11b4e6c793831a2a82a7ac1de2`. All three exact local image
inspections succeeded. Host-wide inspection (outside the process sandbox)
showed unrelated development/test work, including `source_census.py --offline`
and `gate_slot.py ... pixi run test-commit`. Three one-second CPU samples averaged
43.63% idle, with 31.16% and 32.75% idle in the latter two samples. The host
therefore failed the otherwise-idle prerequisite and was **not authorized**.
No waiting for load to clear, retry or automatic repair followed.

`/tmp` and Docker storage were persistent ext4 on root device `/dev/sda5`, with
282,502,262,784 bytes available; available memory was 58,300,817,408 bytes of
65,210,888,192 bytes. The explicit root-backed exception was recorded but unused.
These are capacity observations, not workload-specific suitability acceptance;
that acceptance stopped at the failed idle prerequisite. Earlier smoke floors
were not extrapolated.

Owner-only local evidence is retained at
`/tmp/bgperf2-c-pilot-20261024-refused`: exact inspection commands and exit codes,
host/kernel/CPU facts, process and CPU samples, memory/mount/capacity records,
Docker inventories, image inspections, the decision record and checksum coverage.
No raw evidence was added to this source repository or transferred remotely.

**Accounting:** zero attempts started; all eight A/A and eight A/B attempts are
never-run work, not failed measurements. No recipe/target/assertion exports or
comparison execution roots were created. The A/A report gate was never reached,
so A/B remains blocked. There are no distributions or performance conclusions;
performance is not assessed and regression policy remains disabled.

**Cleanup:** no pilot runtime resources were created and none were removed.
No command in this procedure modified unrelated processes, containers, networks
or volumes. Post-refusal Docker inventory commands inside the sandbox returned
socket permission denied (exit 1 each); their outputs are preserved without
retry. Before/after inventory equality is therefore unverified. This limits the
cleanup review to the absence of pilot runtime creation or removal commands.
All captured evidence remains local; there is no evidence deletion or backup claim.
Independent subagent review accepted the refusal and revised cleanup limitations
with no blocking findings; retained in `independent-review.txt` alongside the
evidence. It verified the initial artifact hashes, confirmed 71 unique existing
container identities in the before inventory with no bgperf-named containers,
and confirmed that the A/B gate remains blocked. Final checksum verification
covers every retained evidence file, including the review and failed inventory
outputs. Documentation validation: `git diff --check` passed; no engine code
changed. This record is committed on the existing branch; its commit is found
with `git log -- docs/plans/milestone-c-calibration-proposal.md`.


## Renewed scheduled pilot — 2026-10-25 PDT

The renewed one-time authorization selected `jpietsch-server` at or after
03:00 America/Los_Angeles, retaining the explicit root-backed persistent disk
exception. It permitted ordinary services, light agent sessions and brief status
checks, and removed the 04:00 wall-clock cutoff. No retries, repairs, extra
attempts, scaling, remote evidence transfer or push were authorized.

Execution used the exact clean existing `milestone-a-newcomer` checkout at
`c3d94d3c844807b08e78b7b0f33cdc54cdbab5f2`, its existing locked 34-package
Python environment, lab `c4c499b40e6cf29a2d6d38de811a35b52b3a58b5` and research
`ad8e0402fef6ab8ddafc9220363a57f9cc8f63dc`. All exact image IDs in the table
above were inspected locally without acquisition. Host kernel was
`7.0.0-38-generic`, with CPU affinity 0–31. Host-wide process identities,
measurement locks, relevant state and Docker inventories were inspected.
The 30-second CPU sample averaged 99.60% idle (five-second samples
99.20–99.76%), with 0.01% average iowait and no sustained competing heavy work.
Agent presence and nonzero CPU were not refusal criteria. The existing weekly
cron was unchanged; its configured checkout was absent during inspection.

Owner-only work/results/artifact roots are under
`/tmp/bgperf2-c-pilot-20261025-run`. They are persistent ext4 on `/dev/sda5`,
with 274,150,715,392 free bytes and 60,590,465,024 bytes MemAvailable before
execution. Conservative operational reservations allowed up to 32 GiB pilot
memory while retaining a 16 GiB host margin and required 64 GiB disk free.
These are reservation/stop thresholds, not measured resource estimates or
extrapolations from tiny smoke floors. Host-wide process CPU/activity and
resource observations continued every five seconds; no substantial competing
work or resource threshold stop was observed. The report retains its separate
nonzero foreign-CPU confounder; no calibrated contention threshold is inferred.

The public CLI exported `comparison-pilot`, cell `b715828f2e681c25`, with two
peers × 100,000 prefixes. Both frozen plans select four alternating rounds,
120 worker seconds per attempt, `diagnostics none`, and the identical explicit
session-establishment, injection-completion, exact observer-count and
experiment-completion assertions. Final health snapshots were excluded. A/A
uses distinct `baseline` and `baseline-control` labels with the same baseline
image; the frozen A/B plan selects the candidate image. All three target
instrumentation declarations remain `unknown`.

**Accounting:** all eight A/A attempts completed in the exact AB, BA, AB, BA
sequence, with four observations per label. Every assertion passed: two
sessions, two injection completion witnesses, exact 200,000 observer prefixes
and completed experiment, within each 120-second worker budget. No A/A attempt
failed or remains unrun. `comparison-verify` exited 0 and verified 322 portable
report files. Exit 0 alone was not the acceptance decision.

**Independent gate: BLOCK.** Every legacy monitor elapsed observation is exactly
4 seconds. Its at-least-one-second resolution is one quarter of that span;
zero observed bucket standard deviation does not establish zero noise. The
independent reviewer found this workload too short for the legacy clock under
the authorized resolution gate. A/B was therefore never started: all eight
A/B attempts are **never-run work**, not failed measurements. There were eight
attempts total, with no retries, resume, budget extension or workload scaling.
The authorization is consumed; this record schedules no follow-up.

The report retains observations and distributions, including sampled target
CPU and legacy delivery-memory values. Optional cgroup lifetime peak, final
memory and diagnostic sampled peak are missing under `diagnostics none`;
process RSS and total CPU work remain unmeasured. CPU peaks are sampled values,
not unsampled maxima or total work. Unknown instrumentation withholds every
controlled descriptive delta; signed arithmetic differences cannot support a
version ranking. No practical effect size was supplied. Performance remains
`not_assessed`, regression policy `disabled`; there is no calibration, leak,
improvement/regression or hardware-qualification conclusion.

**Cleanup and preservation:** each attempt records no cleanup errors; post-A/A
container identities/states, network inventory and volume inventory match the
pre-series inventories exactly. Independent review checks these records and
owned-resource evidence. Original work, packages, ledger, stdout/stderr,
commands, revisions, checksums and complete file/type coverage remain local at
the run root. Runtime sockets are preserved in original work and explicitly
listed as nonregular, unhashed entries; portable packages record their socket
omissions. No broad cleanup or evidence deletion ran. The initial Docker
inventory also retained verbose historical build command strings; later
inventories omitted command arguments. The previous refusal directory
`/tmp/bgperf2-c-pilot-20261024-refused` was left unchanged, and all 24 entries
in its checksum manifest still verify.

Evidence entry points: `decision.json`, `admission.txt`, `aa-command.json`,
`aa-exit.json`, `aa-verify.stdout`, `contention-aa.jsonl`,
`results/aa/attempts.json`, `results/aa/report/comparison.json`,
`results/aa/report/REPORT.md`, `independent-review.txt`, `coverage.json` and
`SHA256SUMS` beneath the run root. The scheduled final output is
`/tmp/bgperf2-c-pilot-20261025-schedule/final.txt`. The documentation change is
reviewed independently and committed locally; locate its commit with
`git log -- docs/plans/milestone-c-calibration-proposal.md`.

## Revised experiment prepared offline — 2026-10-25

The operator requested preparation of a revised experiment after the resolution
failure. This section defines that experiment; it starts no worker and schedules
no follow-up. The earlier runtime authorization is consumed. A new quiet-window
execution needs explicit authorization, including any renewed root-backed disk
exception. Existing evidence, reports and the original pilot input are unchanged.

### Resolve delivery, rather than extending bookkeeping

The prior raw samples reach the full table within one controller poll. The
four-second CSV value includes other lifecycle timing and is not four seconds
of useful delivery. It cannot be multiplied by a route-count ratio to predict
a new duration. Extra sleeps, assurance time or repetitions would not improve
that interval's resolution.

The pinned sink already records finer monotonic count timestamps. The new
[offline observer supplement](../observer-timing.md) defines a separately named
**10%-to-90% observer count-crossing window**, with actual adjacent-record
timestamp brackets. It preserves all legacy measurements and report schemas;
it changes no sampling cadence, engine convergence rule or container image.
The supplement verifies the original package and four assertions, records
source/analysis hashes, and can be independently reconstructed with `--verify`.

Offline inspection of the eight existing A/A packages places their recorded
10%-to-90% endpoint differences around 0.111–0.150 seconds, with actual bracket
widths around 0.018–0.020 seconds. All eight fail the new discovery screen. This
does not overturn the prior gate or establish a version difference. Raw evidence
and original reports remain immutable; new supplements are a separate analysis
version. The preparation bundle records exact per-attempt bounds and inputs.

The screen requires a conservative delivery-window lower bound of at least
one second, bracket width no larger than 5% of that lower bound, and at least
ten increasing interior count records. These are sampling design requirements,
not a practical effect size, repetition-power calculation or regression policy.
Use actual observed gaps; nominal 10 ms coalescing is not an error guarantee.
Do not use longer setup/runtime or a larger rounded CSV value as a substitute.

### Fixed workload and unchanged budget

Use [comparison-resolution-pilot.yaml](../../examples/recipes/comparison-resolution-pilot.yaml),
test `comparison-resolution-pilot`, cell **`e340b76986938b1c`**: two peers,
1,000,000 prefixes per peer, **2,000,000 prefixes total**. This is ten times the
original route count, retaining the same topology and default daemon controls.
The first attempt will test suitability; no duration or resource scaling law
is claimed. Larger Python/Mako/YAML configuration generation and parsing also
consume the worker's 120 seconds. A timeout is a stop, not permission to extend
the deadline. If this fixed workload remains unresolved, stop and review it;
there is no workload ladder or automatic escalation to a larger table.

Retain exactly the image IDs in this document's table, supplied targets with
`instrumentation unknown`, `diagnostics none`, and identical four-capability
assertions bound to the new recipe. Freeze two four-round alternating plans:
eight A/A attempts, then eight A/B attempts only after the independent gate.
Maximum **16 serial attempts**, each **120 worker seconds**, at most **1,920
worker seconds**. The first A/A attempt is the screen and counts as attempt 1
of 16; there are no additional screening/warm-up attempts. Configuration and
the final clean engine revision must be committed before export/execution.

### Pause before spending the remaining attempts

The current `compare` command cannot pause at the resolution/assertion gate
between completed attempts. **Do not launch either whole sequence with
`compare` for this revised procedure.** Drive each frozen sequence entry with
the existing public `recipes.py run` command, through its normal host lock,
bounded worker, collection and owned cleanup. This is explicit orchestration
of existing public commands, not a resume or engine implementation change.
The preparation bundle provides exact argument arrays for every entry.

Before any worker, inspect both target prerequisites, exact local images,
host-wide activity, normal active-measurement guards and resource suitability.
Record revisions, kernel, affinity, mounts, capacity and before inventories.
Quiet means no competing heavy work or sustained resource pressure; ordinary
services, light agent sessions and brief status checks are permitted. Nonzero
utilization or agent presence alone is not a refusal. There is no arbitrary
04:00 cutoff; observe actual competing work, including scheduled jobs.

Use fresh owner-only persistent work/results roots. Prior memory/storage
observations do not qualify this larger workload. As conservative operational
reservations, require at least 48 GiB MemAvailable and 64 GiB disk free before
each series, and retain a 16 GiB host-memory margin during execution; record
these as reservations, not measured demand estimates. Recheck actual backing
mounts and image availability. Missing prerequisites, pressure or uncertain
host visibility stop without acquisition, repair, waiting or retries.

Initialize a new eight-entry ledger for each series, copied from its frozen
plan's exact `id`, `index`, `pair` and `role` values. Start every entry with
`result: null`, `status: not_run` and an explicit reason. After one invocation,
verify its original package, recipe/target/timeout bindings and unique original
attempt ID. Record its actual outcome and absolute result path atomically;
never map a package to two entries. An unexpected nonzero exit, failed or
inconclusive assertion, invalid package, cleanup issue or unavailable/blocked
timing screen stops all later entries. Preserve any failed original package
even if it cannot be included in a portable report.

After **the first A/A attempt**, run the four assertions and observer supplement,
then build a new partial report with `comparison-report` and verify it. It
contains one completed attempt and seven explicitly never-run entries;
incomplete-pair confounders are expected at this checkpoint. An independent
reviewer must accept correctness, timing brackets, screen and cleanup before
attempt 2 is allowed. If the first screen fails, stop after one attempt. Do
not start another worker while the review or analysis is running.

Apply the same per-attempt checks and pause between all subsequent entries.
Use a new report directory for each checkpoint so verified bundles are never
overwritten. The public `comparison-report` reconstruction binds all eight
entries to the original four-round plan; splitting execution does not reset
pair numbering or change the overall AB, BA, AB, BA order.

After all eight A/A attempts, independent review must accept every package,
all 32 assertions, every observer-window screen, host/image/order identities
and owned cleanup before any A/B attempt. No aggregate statistic may hide an
unresolved individual attempt. A/B uses the same frozen workload/assertions
and per-attempt checks; a faster candidate whose window is unresolved also
stops the sequence without a ranking claim. Failed attempts and never-run
work remain distinct, including all eight A/B entries if the A/A gate blocks.

### Review, preservation and remaining decisions

Keep the whole-second comparison report alongside its separate observer
supplements. The former continues to state its resolution limit; the latter
does not silently upgrade legacy CPU/memory sampling or full-convergence
timing. Unknown source/build instrumentation still withholds controlled deltas.
No practical effect size has been supplied. Regression policy remains disabled
and performance not assessed, even when the sampling screen passes.

Retain original work, packages, logs, versions, commands, ledgers, all reports
and supplements with full path/type/checksum coverage. Independently verify
owned cleanup and unchanged unrelated resources before documenting completion.
No evidence deletion or off-device backup claim is included. No downloads,
builds, provisioning, `9950` access, automatic repair, retries, extra attempts,
worker-budget extensions or future remote transfers are part of this procedure.

Offline preparation and review records are under
`/tmp/bgperf2-c-resolution-preparation-20261025`. After the preparation commits,
export the recipe/targets/assertions and both plans with the exact final clean
HEAD, outside the source checkout. The bundle's runbook, command manifest and
hashes identify those inputs; none is execution evidence or host qualification.
Code and plan reviews, tests and local commits are recorded there. No new
quiet window has been scheduled by this preparation.

Implementation reference: `589360033f95a93ba0919504626fe6dde30313df`
adds the offline supplement. Independent code review accepted it after fixing
manifest-snapshot and output-directory replacement races; 24 focused tests
and the normal 2,349-test commit gate passed. Independent plan review confirmed
the new cell, historical bounds, per-entry pause semantics and 16-attempt
accounting. Final clean export and bundle review are recorded with the exact
preparation revision in the local bundle rather than using a self-referential
commit pin in this document.


## Revised scheduled invocation refused at admission — 2026-10-25 13:00 PDT

The user explicitly authorized the prepared revised experiment once on
`jpietsch-server` at 20:00 UTC, renewing the intentional root-backed persistent
storage exception for this invocation only. That exception waived no memory or
storage suitability checks. The scheduled invocation began after the scheduled
time; no worker started. Measurement execution is permanently stopped for this
invocation, with no retry, catch-up, reschedule or follow-up authorized.

The clean `milestone-a-newcomer` checkout was pinned to
`3e8c6176d3c92fd3ed236c26640bb8376dd1d3c2` during admission. Frozen preparation
coverage and SHA256SUMS verified exactly: 46 path/type entries, 43 checksum
entries including the coverage document, with the documented self-exclusions.
Preparation records remain preparation evidence, not runtime observations.
The future runtime root `/tmp/bgperf2-c-resolution-pilot-01` remained absent.

A single approximately 30-second **host-wide**, automatically approved read-only
admission sample recorded Python PID `4104145`, parent `4104139`, consuming
99.93%, 99.93%, 99.93%, 100.01% and 100.00% of one CPU across five consecutive
approximately five-second intervals. It had exited by the sixth interval.
This sustained competing CPU work blocks admission under the current
instruction; ordinary services, sleeping/light agents, the status publisher and
nonzero CPU alone were not refusal reasons. No second admission sample or wait
for quiet was performed. Its full command and workload type could not be
recovered after exit, so no claim identifies it as a particular benchmark,
build or test. Separately, a host-visible unrelated plan-run process and held
queue locks were recorded read-only; none was modified or stopped.

The selected `/tmp` ancestor was persistent ext4 on `/dev/sda5`, the root
filesystem. Observed available memory was about 56 GiB or more and available
disk about 252 GiB, exceeding the 48 GiB/64 GiB reservations at observation.
These observations are neither demand estimates nor hardware qualification.
Kernel, CPU facts, affinity (0–31), mounts, pressure/process deltas and initial
container/network/volume/lock/schedule inventories are preserved locally.
Exact image inspections and all three public target prerequisite checks were
not reached following the admission refusal. They are not claimed passed.
No runtime series roots, worker packages, assertions, observer supplements or
portable runtime reports exist for this invocation. All eight A/A and eight
A/B entries are explicitly never run; **zero of sixteen attempts were spent**.
There are no failed worker attempts. The first-attempt and A/A acceptance gates
were never reached. No approval rejection occurred during admission.

Evidence and the renewed exception/decision are under
`/tmp/bgperf2-c-resolution-20261025-1300-schedule/admission/`, including
`host-samples.json`, `decision.json`, `competing-identities.json`, both
`*-never-run.json` accounting records and before inventories. Final independent
review, path/type/hash coverage, documentation commit receipt and final outcome
are retained in the schedule directory. The frozen preparation bundle and prior
pilot/refusal evidence were not edited; no historical runtime result was used
as admission evidence. Cleanup verification is limited to the fact that this
invocation created no Docker resources or worker work, plus the recorded final
inventory comparison; unrelated resources remain owned by their existing jobs.

Performance remains `not_assessed` and regression policy `disabled`. There are
no new timing/CPU/memory performance measurements, version rankings, controlled
deltas, leak conclusions or hardware qualification. Documentation changed only
after measurement execution was permanently stopped. Local commit identity and
independent review disposition are recorded in the schedule evidence, avoiding
a self-referential commit identifier here. No push, evidence transfer, external
notification, infrastructure provisioning or new schedule was performed.


## Revised 16:00 invocation stopped at frozen-input verification — 2026-10-25 PDT

The user newly authorized one bounded attempt at the revised experiment on
`jpietsch-server` at 16:00 PDT (23:00 UTC), explicitly allowing one unrelated
busy core when remaining resources were ample. The intentional root-backed
persistent-disk exception was renewed for this invocation alone; memory and
storage suitability requirements remained in force. Initial verification took
place after the scheduled time. No worker started, and execution is permanently
stopped without retry, catch-up, follow-up or rescheduling.

The engine branch `milestone-a-newcomer` was clean at the newly authorized pin
`a4a0c7944463b7bc6081b7a10b2c4c534a238bae`. Verification of
`/tmp/bgperf2-c-resolution-20261025-1600-preparation/SHA256SUMS` failed for
`final-bundle-review.txt`: the expected SHA-256 was
`1b485382a85ea40791116d1a9eba6f89c1356cf9a8b318d9a0a9b6b9fc510945`,
while the observed SHA-256 was
`b89eb7450385441ca20213609b4b22e80486200945a12b3d7abcaae36adf8bd4`.
The coverage document likewise records 2,671 bytes versus 2,597 observed.
The other 31 checksum entries matched. Exact path/type coverage matched the
35 declared entries with the two documented self-exclusions; there were no
extra or missing files. No cause or time of the discrepancy is established.
The bundle was left unchanged; `prepare.py` was not rerun and no checksum or
review record was repaired. This integrity failure is the stop reason, not
CPU activity, the old revision pin, or root-backed storage.

Accounting is **zero of sixteen workers started**: all eight A/A and eight A/B
entries were never run, with no failed worker attempts. The future runtime root
`/tmp/bgperf2-c-resolution-pilot-20261025-1600` remained absent. No runtime
ledgers, packages, assertions, observer supplements or comparison checkpoints
were created. Host admission, mount/capacity checks, exact image inspections
and the three target prerequisite checks were not reached and are not claimed
passed. No automatic approval rejection occurred.

The independent read-only refusal review passed, confirming the mismatch,
coverage, clean exact pin and absent runtime root. No worker or owned Docker
resource was created, so no owned cleanup was needed. Unchanged unrelated
resources cannot be established by before/after inventories because admission
was not reached; no unrelated resources were altered or cleaned by this job.
Evidence is retained locally under
`/tmp/bgperf2-c-resolution-20261025-1600-schedule/verification-refusal/`,
including the observed preparation inventory, hash and coverage checks,
operation record, independent review and documentation commit receipt.
The schedule's `final.txt` records the outcome. Earlier pilot/refusal evidence
was not used as runtime evidence or modified; no verification claim is made
about historical bundles not referenced as inputs here.

Documentation changed only after measurement execution stopped permanently.
Independent documentation review and the local conventional commit are recorded
in the new refusal evidence. Performance remains `not_assessed`, regression
policy `disabled`; no new performance observations or qualification claims are
available. No push, remote evidence transfer, external notification, paid
provisioning or subsequent schedule was performed.


## Primary 03:00 invocation stopped at public prerequisite — 2026-10-26 PDT

The user authorized a primary invocation at 03:00 PDT (10:00 UTC) on
`jpietsch-server` and exactly one conditional fresh fallback at 04:00 PDT.
The intentional root-backed persistent-storage exception is explicitly renewed
for these two bounded invocations only; memory/storage suitability checks remain
mandatory. This record covers primary03 alone. The existing scheduler controls
the conditional fallback; this invocation adds no timer or retry and does not
alter the isolated fallback checkout.

The primary began checks after 10:00 UTC. `milestone-a-newcomer` was clean at
`ef404a242339004cf8d8e0e3a26f6b5f1790573f`. The new frozen bundle at
`/tmp/bgperf2-c-resolution-20261026-schedule/03-preparation` passed all 31
SHA256SUMS entries and exact path/type/size/hash coverage with its documented
self-exclusions. No frozen input was changed, repaired or resealed; `prepare.py`
was not rerun. Preparation material is not runtime evidence.

Read-only inspection found all three exact local image IDs requested by the
operator: baseline/generator `db0a8e144635b1d4b9f81f24ee78f11383c5b0cbd79f10353edcb8452e9af423`,
candidate `7f60bf1483ccf766c768f0a3d894b52176748a4d76f9d18cc9af8730520b9142`,
and observer `311317014fc98e2cadf46941b4b23dab9dd724281dd50167a0f9187d8ac08f19`.
The selected `/tmp` ancestor is persistent non-RAM ext4 on `/dev/sda5[/tmp]`,
backed by the root filesystem. Observed MemAvailable was 61,897,994,240 bytes
and disk available 276,173,164,544 bytes, above the conservative 48 GiB/64 GiB
reservations. These are snapshots, not workload demand estimates or hardware
qualification. CPU identity, kernel and affinity 0–31 are recorded locally.

The first manifest public `recipes.py check` for baseline returned exit 2.
Its `bootstrap` check was refused because the existing locked-environment
active-measurement guard could not run
`docker --host unix:///var/run/docker.sock ps --format '{{.Names}}'`
(exit 1). The public check recorded the exact clean engine revision and valid
new disk-backed destinations, but could not establish its mandatory environment
and active-measurement guard. The underlying Docker stderr was not exposed by
that prerequisite report; no more specific cause or automatic approval-review
rejection is asserted. Direct image inspection succeeding does not satisfy the
failed public guard. No retry, alternate endpoint, environment repair or bypass
was attempted. The baseline-control and candidate public prerequisite checks
were not reached after this stop and are not claimed passed.

Execution is permanently stopped for primary03: **zero of sixteen workers
started**, zero failed worker attempts, eight A/A and eight A/B entries never
run. All unused entries retain their exact frozen id/index/pair/role and current
authorization/stop reasons in the job's separate accounting files. The future
runtime root `/tmp/bgperf2-c-resolution-pilot-20261026-0300` remains absent;
no series roots, original packages, assertions, timing supplements or runtime
comparison reports were created. The first-A/A/full-A/A gates were not reached.
Host-wide 30-second admission sampling and before/after Docker inventories were
not completed. No CPU-based refusal was made: one unrelated busy core remains
permitted when resources are ample, including in the conditional fallback.

Evidence is retained under `/tmp/bgperf2-c-resolution-20261026-schedule/03`:
`commands/prerequisite-baseline.json`, stdout/stderr, `stop-decision.json`,
`observations.json`, `aa-never-run.json`, `ab-never-run.json`, independent review
text/receipts, inventory/checksums, `outcome.json` and `final.txt`. The command
record preserves arguments, exit and timestamps without dumping host process
arguments or secrets. No worker or owned Docker resource was created, so no
owned resource removal was needed. Unchanged unrelated resources cannot be
established by full inventories because the required guard failed; no unrelated
resource was stopped or cleaned. Earlier pilot/refusal evidence remains
unchanged; it supplied no runtime evidence for this invocation.

Documentation was edited only after execution stopped permanently. Independent
result/cleanup and documentation reviews and the local conventional commit
identity are retained in the job directory, avoiding a self-referential commit
hash here. Performance remains `not_assessed`, regression policy `disabled`.
No performance, version ranking, controlled delta, leak or hardware qualification
conclusion follows. No download, build, 9950 access, push, remote evidence
transfer, external notification, paid provisioning or new schedule occurred.

## Hourly 18:00 UTC invocation stopped for evidenced load — 2026-10-26

The operator authorized hourly bounded discovery until fully verified success,
with automatic diagnosis/repair of non-load failures in a separate supervisor
pass. This supersedes earlier one-shot/no-repair restrictions. Each fresh job
retains at most sixteen serial 120-second workers, diagnostics none, four
assertions, first-A/A and full-A/A independent gates, and unchanged observer
resolution requirements. No new timer was installed by this invocation.

Job `/tmp/bgperf2-c-resolution-hourly-20261026/jobs/20261026T1800Z`
froze the current clean `milestone-a-newcomer` revision
`a1b57a761e9dc70c82b2796b07f6a6ab892313e7`. Its adjacent
`20261026T1800Z-preparation` was generated offline from the reviewed helper,
independently reviewed read-only, and sealed only after preparation writers and
the reviewer had finished. It retains exact recipe/target/assertion declarations,
four-round alternating A/A and A/B plans, sixteen future command arrays and
path/type/size/hash coverage. Original reviewer text is preserved in the job.
Older sealed bundles were not changed or reused as execution evidence.

All **three** public target prerequisite checks passed through approved host
execution, avoiding the diagnosed sandbox Docker-socket denial. The exact
baseline/generator, candidate and observer image IDs were inspected locally;
no pull, install or build occurred. Instrumentation stays unknown. Host storage
was ext4 `/dev/sda5`, intentionally root-backed under the renewed exception,
with 272,469,716,992 bytes available, above the 64 GiB reservation.

Admission stopped for actual sustained host load, independently reviewable in
`host-activity-samples.json` and `host-activity-summary.json`: seven host samples
span 30 seconds, with six interval CPU-busy values **82.06–92.21% across 32
logical CPUs**. MemAvailable was **36.61–39.57 GiB**, below the mandatory
48 GiB pre-series reservation. These are operational reservations, not workload
estimates. This was not isolated one-core activity or an agent/unknown-argv
refusal. No actual BGP measurement/held measurement lock was identified; the
hourly supervisor's coordination lock is not a measurement conflict. No
unrelated work was stopped and no model/code repair was made for load.

Execution stopped permanently before worker 1: **zero attempts started, zero
failed worker attempts, zero A/A or A/B completions, all sixteen entries never
run**. New runtime ledgers preserve each frozen id/index/pair/role with null
result and the explicit stop reason. No result packages, timing supplements or
runtime comparison checkpoints exist; no assertion or timing gate is claimed
passed. First-A/A, full-A/A and A/B receipts honestly record not reached.
Owned cleanup requires no removal because no worker/resource was created;
before/after local Docker inventories and independent review are retained.

The job retains outcome/stop records, all three host prerequisite commands and
stdout/stderr, original activity/resource/lock inventories, independent review
text and receipts, and evidence coverage including non-regular file types.
Independent cleanup/outcome and documentation reviews and the local conventional
commit identity are recorded with the job; the outcome carries that commit hash.
Documentation changed only after permanent worker stop. Performance remains
`not_assessed`, regression policy `disabled`; no performance or hardware
qualification conclusion follows. No retry within this job, push, remote
transfer, external notification, paid provisioning or 9950 access occurred.
The existing supervisor owns the next hourly attempt and its success decision.


## Hourly 19:00 UTC invocation stopped for coordinator setup — 2026-10-26

Job `/tmp/bgperf2-c-resolution-hourly-20261026/jobs/20261026T1900Z`
froze clean `milestone-a-newcomer` revision
`1f2bbdc38754e1b89777fd141cfee8bcff280408`. Its fresh adjacent preparation
was generated offline from the reviewed helper, independently reviewed read-only,
and sealed after all preparation writers/reviewers finished. Exact image IDs,
unknown instrumentation, two peers times one million prefixes, four assertions,
four alternating rounds per series, 120-second budgets and diagnostics none
were retained. All three public prerequisite checks passed on the approved host
path; no sandbox Docker refusal was repeated.

The renewed intentional root-backed persistent ext4 exception was recorded.
Free disk was 274,278,866,944 bytes; seven host samples spanning 30 seconds
showed 54.47–55.70 GiB MemAvailable. Host CPU busy was 28.54–30.00% across
32 logical CPUs, with no sustained CPU/I/O/memory pressure. Ordinary foreign
activity and unrelated locks did not alone block this discovery attempt.
The during-worker sample retained seven resource observations spanning 30
seconds; it does not attest continuous coverage of the full worker interval.

The first A/A worker completed successfully in 64.0128768030554 seconds.
Original attempt `bgperf_recipe_9d5f0593656f436bb1509a4dd6bbee8d`, its
verified package and all four passed assertions are preserved. The coordinator
omitted creation of `runtime/supplements`, causing the first timing command
to exit 2 with ENOENT before evaluating sampling. This non-load **setup**
failure permanently stopped worker execution after one attempt. No worker was
retried and no second worker started. The supervisor owns a separate repair
pass and the next hourly attempt; this job claims no complete success.

After permanent worker stop, offline diagnosis created the missing output
parent and evaluated the same original package at its manifest supplement path.
Generation and reconstruction both passed: conservative lower 1.789916889 s,
actual bracket width 0.019958769 s, 145 increasing interior count records.
These observations satisfy the screen but do not reverse the original setup
stop or authorize the remaining workers. Both original refusal logs and the
separate post-stop command logs remain. The new partial report at
`runtime/reports/aa-after-01/comparison.json` verified successfully and binds
the original attempt to its frozen entry. The runtime ledgers retain one
completed A/A worker, seven A/A never-run entries and eight A/B never-run
entries, with zero failed worker experiments. First-A/A continuation and both
full-series gates remain blocked by the permanent stop.

Original work, logs, packages, supplements, host inventories and path/type/hash
coverage, including socket types, remain local. Independent stop/cleanup and
documentation findings and parent-written receipts are retained with the job;
its outcome records the reviewed local documentation commit. No source edits
occurred while a worker was active. Performance remains `not_assessed` and
regression policy `disabled`. No performance ranking, hardware qualification,
remote evidence transfer, push, build, download, paid provisioning, 9950 access,
external notification or new timer occurred.

## Hourly 20:00 UTC invocation stopped after A/A for load — 2026-10-26

Job `/tmp/bgperf2-c-resolution-hourly-20261026/jobs/20261026T2000Z`
froze current clean `milestone-a-newcomer` revision
`9373bb682dbb20e8d6e0547917ac1050891571c7`. The reviewed lab adapter
created fresh adjacent preparation and private runtime/supplements before worker
admission. Its 16 offline commands passed; independent read-only preparation
review finished before sealing. The exact supplied images, unknown
instrumentation, two peers times one million prefixes, four assertions, four
alternating rounds per series, diagnostics none and 120-second worker budgets
were unchanged. All three public prerequisite checks and all worker commands
ran on the approved host path. No sandbox socket refusal was repeated.

Initial host admission retained seven samples spanning 30 seconds, with
79.78–80.84% idle CPU, negligible I/O wait, no sustained pressure and at least
56.32 GiB MemAvailable. Persistent ext4 `/dev/sda5` had 273,486,962,688 bytes
free. The renewed intentional root-backed disk exception and 48 GiB memory,
64 GiB free disk and 16 GiB running memory reservations were recorded as
operational reservations, not demand estimates.

Eight serial A/A workers completed, with eight unique original attempt IDs,
32 passed assertions and eight passed observer screens. Lower bounds range
1.640276902–2.539973499 seconds; actual bracket widths range
0.019593734–0.031265228 seconds, all below 5% of their respective lower
bounds; increasing interior counts range 131–212. Each original package and
new checkpoint report verified. The first independent gate accepted attempt 1
before attempt 2. The original final A/A report at
`runtime/reports/aa-after-08/comparison.json` verifies 322 files. These passed
instrument/correctness checks do not establish an acceptable host gate.

**Independent full A/A gate: blocked for actual sustained CPU pressure.**
`aa-r004-baseline-host-samples.json` records 18 consecutive five-second
intervals over approximately 90 seconds: idle 0.98–8.62%, mostly around
1–2% for the first 80 seconds, with CPU PSI some avg10 34.54–58.13%.
Cumulative CPU stall grew approximately 42 seconds over the last 85 seconds;
load exceeded 55 on 32 logical CPUs. The preceding worker's final interval
already had 5.81% idle and PSI 19.39%. This is material host-wide pressure,
not one busy core, agent presence, unknown instrumentation or foreign CPU
alone. No active BGP measurement or held measurement lock was identified.
Fresh pre-A/B admission later showed recovered capacity, but cannot qualify
the pressured A/A sequence.

The coordinator preserved five-second resource samples but inspected memory and
cleanup without adequately examining CPU pressure between workers 7 and 8.
That omission allowed worker 8 under pressure; preliminary per-attempt accepted
receipts remain preserved and are superseded by the blocked independent full
gate. A separate premature receipt read before checkpoint verification finished
is recorded in `coordinator-ordering-note.txt`; awaiting completion resolved
that read, with no worker retry or package/assertion/timing failure. Neither
limitation is hidden by the successful correctness or timing results.

Worker execution is permanently stopped before A/B: **eight attempts started,
eight A/A completions, zero A/B completions, zero failed worker experiments,
eight A/B entries never run**. Outcome class is load, with measurement_conflict
false, material_interference true and isolated_one_busy_core_only false;
its preserved samples_path points to the actual worker-8 host sample file.
No retry, load repair or interference with unrelated work occurred. The existing
supervisor owns the next hourly attempt; no new timer or success marker was
created by this invocation.

All workers report no owned cleanup errors. Original work, packages, commands,
stdout/stderr, ledgers, checkpoint reports, supplements, independent reviewer
text and honest receipts remain local, with path/type/size/hash coverage that
records sockets without reading them. Container identities/states, networks and
volumes remain unchanged in retained inventories; final independent cleanup and
documentation reviews are recorded in the job. Documentation changed only after
permanent worker stop, and outcome.json records its reviewed local conventional
commit. Performance remains `not_assessed`, regression policy `disabled`.
There is no performance ranking, hardware qualification, remote evidence
transfer, external notification, push, download, build, paid provisioning or
9950 access.

## Hourly resolution discovery completed — 2026-10-26 14:00 PDT job

The user authorized hourly bounded discovery until one fully verified success,
with automatic diagnosis/repair of non-load failures between hourly jobs. This
superseded earlier one-shot/no-repair limits while retaining all correctness,
timing, worker-budget and independent-review gates. The existing supervisor
owns scheduling and reconstructs completion; this invocation created no timer
and did not edit its success marker. Performance remains `not_assessed` and
regression policy `disabled`; this discovery result selects no effect size,
regression threshold, version ranking or hardware qualification.

Job `/tmp/bgperf2-c-resolution-hourly-20261026/jobs/20261026T2100Z` used the clean
existing `milestone-a-newcomer` checkout pinned throughout every worker to
`57e51b3c2ad09fdb0fcb091e15ae9b8f0f0db298`, its committed two-peer, one-million
prefixes-per-peer config and existing locked environment. The reviewed lab
adapter created fresh adjacent `20261026T2100Z-preparation` offline at that
current HEAD and exclusively created private `runtime/supplements` before
admission. Preparation exited zero and was sealed only after its independent
read-only review finished. All three public target prerequisite checks ran
host-side through normal automatic approval and passed. All supplied immutable
baseline/generator, candidate and observer image IDs in this proposal were
confirmed locally; instrumentation remains unknown. No sandbox Docker refusal
was substituted for a host check.

Before worker 1 the coordinator repaired its CPU-pressure permission logic.
The retained `pressure_monitor.py`, `control.py` and `accept.py` use host CPU
counter deltas and CPU PSI every five seconds. Two consecutive intervals with
host busy at least 75% AND CPU PSI some avg10 at least 20% permanently stop the
invocation and gracefully interrupt only its owned public recipe controller.
A memory-margin breach also stops; monitoring errors terminate/wait for that
controller's collection/cleanup, record the error and block successors.
Observation gaps over 7.5 seconds reject acceptance. Every retained CPU/PSI and
memory observation is reviewed after each attempt and rechecked before its
successor; adequate memory alone cannot establish no material interference.
Independent review initially found the exception-handling gap; it accepted the
fix before any worker started.

Replay preserved the prior 13:00 job unchanged. Its r004 baseline's sustained
roughly 98% busy and 50%+ PSI rejects the old sequence despite ample memory.
The preceding candidate ends at 94.15% busy and PSI 19.39%, below the fixed
screen; it is not relabeled as meeting that threshold. A synthetic single-busy-
core control on 32 logical CPUs passes at 3.125% aggregate busy and zero PSI.
The initial replay incorrectly expected both old files individually to reject;
its assertion and corrected expectation are retained without changing the gate.
This is a coordinator repair, not a host-load repair or a revision of old
preliminary receipts.

Fresh host admission covered about 30 seconds with 28.23–29.62% aggregate busy,
CPU PSI declining from 1.99% to 0.09%, no I/O/memory PSI pressure and at least
55.61 GiB MemAvailable. Fresh pre-A/B admission recorded 21.85–25.19% busy,
zero CPU PSI and at least 55.86 GiB available. No active BGP measurement or held
measurement lock was found; the supervisor coordination lock is orchestration
state. The one running unrelated container and ordinary foreign work were
retained. The explicitly renewed root-backed persistent ext4 `/dev/sda5`
exception was checked with fresh findmnt/df observations: disk availability
was 260,914,405,376 bytes before A/A and 248,299,888,640 before A/B. Both series
met the 48 GiB available-memory and 64 GiB disk reservations; those floors and
the 16 GiB running margin are reservations, not measured demand estimates.

Exactly **16 serial attempts completed**: eight A/A then eight A/B, each with
120 worker seconds and diagnostics `none`. No retry, warm-up or whole-compare
loop ran. The first A/A attempt was screen 1 of 16; its independent gate passed
before worker 2. Independent full-A/A acceptance followed eight completed
attempts and preceded fresh A/B admission. Each attempt verified its original
package, four assertions, recipe/target/budget binding, unique original attempt
ID, owned cleanup, observer supplement and supplement reconstruction, and a new
partial comparison checkpoint before its successor. All 32 A/A and 32 A/B
assertions pass. Original final reports remain at
`runtime/reports/aa-after-08/comparison.json` and
`runtime/reports/ab-after-08/comparison.json`; all 16 timing supplements remain
at their frozen manifest paths.

All actual observer screens pass independently of verification exit status:
A/A conservative lower bounds are 1.540092155–2.950087929 seconds, actual bracket
widths 0.6888–1.6509% of their respective lower bounds, and increasing interior
counts 137–232. A/B lower bounds are 1.660004570–3.278005236 seconds, widths
1.4511–1.6005%, and interior counts 65–145. These observer 10%-to-90% windows
neither upgrade the legacy clock nor establish which component limits delivery.
Unknown instrumentation and withheld controlled deltas remain limitations.

All 129 A/A and 122 A/B retained worker observations were reviewed. No pair of
intervals meets the severe CPU/PSI stop screen, and no memory-margin breach
occurred. Highest A/A CPU PSI was 17.74%; A/B CPU PSI was zero throughout.
Minimum available memory during workers was 47.8648 GiB A/A and 53.5947 GiB
A/B, above the running 16 GiB margin. Intermittent CPU peaks alone did not
establish material pressure under the user-authorized practical standard.

The coordinator initially read worker 7's acceptance inputs before asynchronous
checkpoint verification finished; ENOENT prevented acceptance. It waited for
post-processing exit zero and accepted the finished evidence before worker 8.
The traceback and ordering note are retained; no worker retry or premature
successor followed. Every package reports no owned cleanup errors, and all
post-attempt container identity/state, network and volume inventories match the
initial inventory. Original work, failures, logs, command arrays, ledgers,
reports, supplements and reviewer text remain local with exact path/type/hash
coverage, retaining socket entries without opening them.

All worker execution permanently stopped before documentation edits and normal
local commit hooks. Final independent A/B, cleanup and documentation review
receipts and the full reviewed local documentation commit are retained in the
job; `outcome.json` records completion and exact accounting. Failed worker
attempts: zero; never-run entries: zero. No evidence deletion, remote transfer,
external notification, push, download, build, paid provisioning or 9950 access
occurred. This result authorizes no additional worker invocation.
