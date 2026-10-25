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
