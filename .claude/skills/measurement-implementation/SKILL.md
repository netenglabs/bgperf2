---
name: measurement-implementation
description: Complete up to three reviewable change sets of the bgperf2 measurement implementation plan, each reviewed and committed on its own, stopping early at any operator decision, phase boundary or hardware requirement. Use when the user says "continue the bgperf2 measurement implementation plan", or asks to advance that plan or its decision log.
---

# Measurement implementation operator contract

When the user says `continue the bgperf2 measurement implementation plan`, follow
`docs/bgperf2-measurement-implementation-plan.md`. Inspect durable
state, resume unfinished work, and complete the smallest reviewable change sets from the first incomplete
phase, in order. Each one gets its own proportionate tests, any phase-required Docker verification, a review of its
full diff with the findings acted on, its own plan and decision-log record, and its own commit, before the next one
starts. Do not start follow-up benchmarking before the release gate passes.

**Continue through at most three change sets, then stop** and tell the user to use the same prompt again. Stop
earlier at the first of:
any operator decision, a phase boundary, a step that needs other hardware (the campaign host), a
step that changes published output (CSV columns, findings verdicts, defaults), or a change set
whose review is still finding real defects after two rounds.
Name which one stopped the run.

The cap is three because review quality falls as one session's context grows, and because change sets build on
each other: a defect that survives one review gets built on by the next, and three stacked commits are much harder
to unwind than one. Set by the operator on 2026-10-01, after a session that ran two change sets in a row. Their
reviews found six real defects, and each was fixed before its own commit. Before that, the contract was one change
set per prompt.

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
