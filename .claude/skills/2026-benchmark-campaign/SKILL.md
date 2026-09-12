---
name: 2026-benchmark-campaign
description: Run or resume one suite of the 2026 BGP performance benchmark campaign (run ID 2026-baseline, results under results/2026, work directory /data/bgperf-work). Use when the user says "continue the 2026 benchmark campaign", or asks to run, monitor, resume or review a 2026-baseline suite.
---

# 2026 benchmark campaign operator contract

When the user says `continue the 2026 benchmark campaign`, use these fixed defaults unless durable run metadata
already records different values:

- run ID: `2026-baseline`
- results root: `results/2026`
- work directory: `/data/bgperf-work` (why it is not `/var/tmp`: the `timing-validation-campaign`
  skill, which settled it for this host — `/var/tmp` is on the 29 GB root here)

Inspect `COMPLETE` markers, progress JSON, CSV rows, logs, and active benchmark processes first. Never run suites
concurrently. Monitor an active suite or resume an interrupted one; otherwise run exactly one suite with
`scripts/run_2026_suite.sh next --run-id 2026-baseline --workdir /data/bgperf-work`. Review it for failed rows,
tester errors/timeouts, foreign CPU contention, low free memory, and timing evidence. The legacy `testers (s)`
field is elapsed minus time to the first monitor-visible prefix, so its proximity to elapsed must not be used as
an injection-bound verdict. Stop after that one
suite is complete and reviewed, and tell the user to use the same prompt next time. Prerequisite image or MRT work
is allowed, but do not advance into a second suite in the same continuation.

---

This contract used to live in `CLAUDE.md`. It moved here because it is triggered by an
exact user phrase, which is what a skill description is; the body is loaded in full on
invocation, so nothing about it has been condensed.
