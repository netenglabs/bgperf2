# Milestone C calibration pilot proposal

Prepared 2026-10-23. Status: renewed 2026-10-25 pilot completed eight A/A attempts; independent timing-resolution gate blocks A/B. Milestone C's implementation and
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
