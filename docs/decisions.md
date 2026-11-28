# Engine decisions and qualification status

This page holds the current state of the A–D performance-testing milestones,
the decisions that still constrain engine work and what has and has not been
qualified on real daemons. The [roadmap](roadmap.md) owns current direction and
the index of active plans. Contracts live in the guides linked below.

## Milestone status

| Milestone | Delivered interface | Status |
| --- | --- | --- |
| A. Newcomer reproduction | [Recipe contract and `recipes.py run`](recipes.md) | Functionally validated for synthetic BIRD/BIRD/sink |
| B. Test a local fix | [Target selection, source builds, diagnostics, investigations](investigations.md) | Supplied-image pair and packaging-adapted BIRD source build validated |
| C. Baseline/candidate comparison | [Descriptive comparisons](comparisons.md), [staged execution](comparison-execution.md), [observer timing](observer-timing.md) | Descriptive workflow delivered; calibrated detection deferred |
| D. Regression localization | [Deterministic bisection](bisection.md) | One bounded live count-fault boundary confirmed |
| Phase 7. Minimization | [Bounded minimizer](minimization.md) | Peer/prefix-count reduction delivered; one controlled live FRR case |

The engine owns recipe validation, image preparation, execution, build identity,
observations, diagnostics and generic comparison interfaces. Consumers own host
qualification, campaign orchestration, storage, research interpretation and
publication, and use only documented CLI commands and versioned artifacts.
A threshold policy supplied by a caller is named and recorded, never embedded
silently in the engine.

## Decisions in force

- **Feature expansion is paused (2026-11-06).** The goal is easy performance
  comparison for a general audience evaluating daemons, versions and workloads;
  maintainer and source-investigation workflows are advanced options. No new
  feature milestone is selected until use of the existing comparison workflow
  exposes a concrete need.
- **Descriptive comparisons are the delivered performance workflow; formal
  reliable-10% calibration is deferred (2026-10-31).** Why: on the shared
  development host, same-image variation was as large as the target effect
  (16 A/A pairs ranged −11.39% to +20.94%, paired-log SD 0.0859), and repeated
  cases stopped on outside CPU or memory before completing. Only a large
  optimized/debug contrast (about +72% to +78%) separated from local A/A
  envelopes; a tunable small control never measured a nonzero dose. Deferral
  is not a release blocker and establishes no minimum detectable effect.
- **Performance policy stays `disabled` and qualification `not_assessed`** in
  every report. Performance bisection and performance minimization remain
  unsupported until a calibration supplies effect size, repetition and error
  requirements. Deterministic correctness/crash bisection is unaffected.
- **A future calibration is one bounded, separately approved campaign** on a
  host with predictable capacity. Before execution it freezes the workload,
  operating conditions, modest-effect control and its characterization,
  detector, error goals, justified sample budget, resource/time budget and
  success/stop criteria. Characterization and held-out confirmation stay
  separate. Exhausting the budget or inconclusive evidence ends the campaign
  with calibration still deferred; there are no automatic extensions.
- **The 10% planning target means a 10% longer observer 10%-to-90% delivery
  window** ([definition](observer-timing.md)), not legacy `elapsed (s)` or
  isolated target processing. It is not a single-pair regression cutoff.
- **Small correctness checks use the [immediate functional protocol](functional-validation.md)
  (2026-11-03).** Why: hourly CPU-idleness admission cost hours of waiting for
  12-second correctness questions whose timing is not interpreted.
- **Real-runtime qualification is separate from modeled checks.** Fake-runtime
  and simulated walkthroughs establish interface behavior, not live adapter,
  host or performance qualification. Each live case is bounded, consumed on
  completion and never resumed or retried from unused positions.

## Qualified on real daemons

Each entry is a bounded functional qualification on the development host,
with recorded background activity; none is a performance or hardware result.

- Synthetic one-peer/100-prefix BIRD/BIRD/sink `run`, package return and
  verification; a 0.01-second worker deadline returns `inconclusive` (exit 5)
  with a verified partial package.
- Supplied-image BIRD 2.19.2/3.3.2 investigation pair with basic diagnostics.
- Packaging-adapted BIRD 2.19.2 `bird-local/v1` build, functional pair and
  SIGTERM interruption while only setup containers were running (exit 143).
- Observer-window resolution on the two-peer/2,000,000-prefix pilot workload.
- Assertion bisection across a deliberately introduced BIRD route-drop fault:
  three builds, five workers, fresh confirmations of the adjacent boundary.
- Adjacent upstream BIRD release transition (pre-2.19.2 to 2.19.2) through
  source-range preparation and handoff, with alias-only packaging.
- Received-prefix identity capture with sink 0.2.0 on real BIRD.
- Packaging-adapted FRR 10.3.1 `frr-local/v1` build and functional pair.
- FRR controlled prefix fault: public-run comparison/investigation reports,
  native minimization to one peer/two prefixes, external-trial bisection, five
  combined `step --execute` trials (three build invocations, two cache hits)
  and one alternating `compare` command with four originals.
- Generated import policy (`batch` `policy_rules`/`policy_match`/`policy_hit`,
  2026-11-27) on BIRD 2.17.1 and FRR 10.7.0: 10 peers × 10,000 prefixes,
  baseline and 1,000 rules, `prefix`, `as-path` and `community` matches, `first`
  and `last` hits at `/24`, and `as-path`/`last` at `/32`. All 18 cells
  delivered exactly the expected count, and the policy-loaded check passed
  before every policy cell. Descriptively, FRR `as-path`/`last` converged in
  about 276 s at both lengths, against about 4 s for every other FRR cell
  except `community`/`last` (11 s) and 7 s for BIRD's matching cell. That is
  one run per cell, not a performance result. The policy-loaded refusal and the
  count guard's withholding were not exercised live.

## Not qualified

- Unmodified BIRD or FRR release sources: both contain tracked symlinks that the
  regular-file source contract refuses.
- Real `prepare --pull` registry acquisition.
- Timeout or interruption cleanup while the target is running; crash diagnosis
  and live `target_crash` bisection.
- The full-search `recipe_bisection.py run --execute` loop and live
  interrupted-search recovery.
- Per-daemon RSS, continuous daemon health, binary hashes and reproducible or
  hermetic builds.
- Any performance difference, regression threshold or detection sensitivity.

## Where the run records went

The milestone plan and its runtime validation records were removed from
`docs/plans/` on 2026-11-20. They remain in Git history
(`git log --diff-filter=D -- docs/plans/`).
