---
name: unattended-execution
description: Complete exactly one migration step of the bgperf2 unattended execution plan, then stop. Use when the user says "continue the unattended execution plan", or asks about the unattended driver, its branch, or its migration steps.
---

# Unattended execution operator contract

When the user says `continue the unattended execution plan`, follow
`docs/unattended-execution-plan.md`. Inspect which migration
steps are complete, complete exactly one step, verify its exit criterion, record progress in that
document, then stop and tell the user to use the same prompt again. That plan is infrastructure for
the other three contracts: it runs no benchmark and changes no measurement semantics.

Two things the plan leaves to whoever adopts it, settled here:

- **The driver's scope is the measurement plan, and it stops at Phase 6 — for a reason that has
  changed.** It used to stop because calibration taken on the development host would describe a
  machine the campaign never runs on. That reason is gone: as of 2026-09-08 this *is* the campaign
  host (see the `timing-validation-campaign` skill), and the resize took it past the memory
  objection too. The
  stop stays for the reason underneath it: a Phase 6 calibration is a multi-hour benchmark that
  takes the whole host exclusively, and starting one is the operator's call, not something a worker
  does to see how it goes. A worker that finds Phase 6 next still stops and says so. Do not restate
  the old wording — an 8-core / 30 GB host is not what this runs on any more, and a contract that
  describes a machine that no longer exists is followed anyway.
- **Unattended work does not reach master.** It commits to `unattended/measurement`, and
  `/code-review` before every commit stays part of the definition of done — it is the only thing
  between a bad edit and the branch, and it does not become optional because nobody is watching.

---

This contract used to live in `CLAUDE.md`. It moved here because it is triggered by an
exact user phrase, which is what a skill description is; the body is loaded in full on
invocation, so nothing about it has been condensed.
