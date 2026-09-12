---
name: measurement-implementation
description: Complete exactly one reviewable change set of the bgperf2 measurement implementation plan, then stop. Use when the user says "continue the bgperf2 measurement implementation plan", or asks to advance that plan or its decision log.
---

# Measurement implementation operator contract

When the user says `continue the bgperf2 measurement implementation plan`, follow
`docs/bgperf2-measurement-implementation-plan.md`. Inspect durable
state, resume unfinished work, and complete exactly one smallest reviewable change set from the first incomplete
phase. Run proportionate tests and any phase-required Docker verification, review the full diff, then stop and tell
the user to use the same prompt again. Do not start follow-up benchmarking before the release gate passes.

**That plan comes in two halves and both are part of being done.** The plan document is forward-looking --
phases, work lists, tests, exit criteria, and one `Status:` line each -- and stays short enough to read whole
before starting.
`docs/bgperf2-measurement-decision-log.md` holds why each change was
made the way it was, what was measured to decide it, and what its Docker verification showed, one section per
phase. Read the phase's log section before changing what that phase settled, and append to it when a change set
lands; the `Status:` line moves in the plan. Several log entries exist because a first attempt was wrong -- a
bound on an interval nobody measured, a poll resolution that understated itself, a guard that refused on one
path while another accepted silently -- so it is append-only: correcting an entry means adding what was found,
never editing the earlier reading away. The record of having been wrong is the part that stops it happening
twice, which is the same reason `verify` exists.

---

This contract used to live in `CLAUDE.md`. It moved here because it is triggered by an
exact user phrase, which is what a skill description is; the body is loaded in full on
invocation, so nothing about it has been condensed.
