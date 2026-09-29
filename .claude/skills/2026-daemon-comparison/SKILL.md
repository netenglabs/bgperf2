---
name: 2026-daemon-comparison
description: Complete exactly one item of the 2026 daemon comparison plan, after checking that the plan and its beads agree, then stop. Use when the user says "continue the 2026 daemon comparison", or asks where that plan stands or whether its beads match it.
---

# 2026 daemon comparison operator contract

When the user says `continue the 2026 daemon comparison`, follow
`docs/2026-daemon-comparison-plan.md`, epic `bgperf2-0y5`.

1. **Check alignment first, before reading anything else:**
   `venv/bin/python scripts/check_plan_beads.py docs/2026-daemon-comparison-plan.md`.
   If it reports findings, reconcile them before any other work. The plan is the source: if a
   bead disagrees, fix the bead. If the plan is the stale side (work finished and never
   recorded), fix the plan, citing the commit. Re-run until it exits 0. A reconciliation that
   needed a real correction counts as this session's unit; say so and stop.
2. **Find the first phase whose status is not `done` or `not needed`**, and within it the first
   numbered item not struck through. Complete exactly that item and verify it against the phase's
   exit criterion.
3. **Record it in the same step, both sides:**
   - the item in the plan (strike it through and add the commit), and the phase's `Progress:`
     line;
   - the phase's `**Status:**` line, and the bead to match: `bd update <id> --status
     in_progress` when a phase starts, `bd close <id> --reason="<sha>, plan §N"` when it is done.

   Run the checker again; it must exit 0.
4. **Stop**, and tell the user to say `continue the 2026 daemon comparison` again.

Rules this contract adds to `CLAUDE.md`'s:

- **A decision marked "(operator)" in the plan is never guessed.** Lay out the options the plan
  records and stop. Today that is Phase 2.1: whether to change the monitor.
- **Phase 3 runs benchmarks that take the whole host for hours.** Confirm with the user before
  starting one, and never run two at once.
- **Phase 4 needs hardware nobody here can provision.** At the Phase 3 gate, report which row of
  the gate table the evidence landed in, and stop. Do not start Phase 4 work speculatively.
- **Beads never carry reasoning.** A finding goes into the plan (or the decision log), and the
  bead gets at most a pointer. The checker flags a description long enough to be prose.
- `/code-review` before every code commit, as `CLAUDE.md` requires.
