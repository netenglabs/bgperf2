# CI correctness checks for functional investigations

Selected 2026-11-03 after delivery of the read-only investigation status command
at `f83172d`. A maintainer needs a process exit suitable for CI without parsing
the full assertion view or mistaking integrity success for correctness.

## Contract

`recipes.py investigation-check /absolute/report/investigation.json` verifies
the report through the existing status snapshot, then emits
`bgperf2/investigation-check/v1alpha1` JSON with the status fields, outcome,
exit_code, checked_attempts and reasons. The default checks both sides;
`--side candidate` or `--side baseline` checks one side while retaining all
observations. A candidate check can pass alongside an observed baseline failure.
It starts no subprocess, worker or probe, creates no
results, and changes no report. Status and verification retain their existing
outputs and exit meanings.

| Exit | Outcome | Meaning |
| --- | --- | --- |
| 0 | passed | Correctness selected, checked original packages present and completed, every assertion in checked attempts passed, no report-bound controller stop. |
| 4 | failed | At least one assertion in a checked attempt failed, including when other checked evidence is incomplete or a controller stop exists. |
| 5 | inconclusive | No checked assertion failed, but selection, checked completion or checked evidence is incomplete/unmeasured, or a controller stop exists. |
| 2 | No check JSON | Invalid input or report integrity refusal; stderr explains the refusal. |

An observed failure takes precedence over incompleteness without concealing
either: retain all per-side assertion outcomes and report controller state.
Report integrity verification still covers both sides; selecting one cannot
hide altered evidence on the other. A report-bound stop anywhere prevents a
passing check, even for an otherwise complete selected side.
Count and identity remain separate. Reproduction assessment is preserved, not
used as a substitute for correctness. Legacy reports cannot silently pass.
Absence of a report-bound stop does not prove the original outer CLI exit;
full execution acceptance still needs that record and the case's other evidence.
This is not a universal bug-fix or performance verdict.

## Delivery

Use sealed simulated reports to check success, equal-count prefix mismatch,
unavailable/legacy capture, unselected correctness, partial/missing attempts,
controller stops, failure precedence, integrity refusal and CLI exit behavior.
Verify read-only behavior and unchanged status/verify compatibility. Independently
review the final change, run required repository gates and commit locally.
Retain commands and progress in `/tmp/bgperf2-investigation-check-20261103/`.
Exercise the public CLI against the retained real-BIRD original/rebuilt reports;
verify existing evidence before and after. No new execution budget is needed or
granted. Upstream investigation stays paused, performance policy disabled and
formal 10% calibration deferred.

## Completed read-only qualification — 2026-11-03 UTC

All 37 new check tests passed, including candidate success alongside baseline
failure, side-specific missing evidence and global controller-stop handling.
Existing status, prefix, investigation and documentation checks passed 158
tests. The final public CLI returned passed/exit 0 for both retained
real-BIRD original and rebuilt reports in all three side selections, with
identical original/rebuilt JSON per selection, two distinct
completed originals and six assertions passed per side, including 100 exact
prefixes. All 840 original evidence files and 48 prior delivery files were
verified before and after those six commands. No new worker, build or probe
ran. Exact source hashes, final review, native commit gate and local checkpoint
are retained with the external task evidence above. Integrity/status contracts
and original execution evidence remain unchanged.
