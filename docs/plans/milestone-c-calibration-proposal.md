# Milestone C calibration pilot proposal

Prepared 2026-10-23. Status: proposal only. Milestone C's implementation and
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
