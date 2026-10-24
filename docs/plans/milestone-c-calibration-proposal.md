# Milestone C calibration pilot proposal

Prepared 2026-10-23. Status: authorized pilot stopped at the idle-host prerequisite; no attempts run. Milestone C's implementation and
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
