---
name: 2026-daemon-comparison
description: Complete the next item of the 2026 daemon comparison plan, or several independent ones in parallel through subagents, after checking that the plan and its beads agree, then stop. Use when the user says "continue the 2026 daemon comparison", or asks where that plan stands or whether its beads match it.
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
   numbered item not struck through. Then look for other items, in that phase or in any open
   bead the plan names (`bgperf2-nit`, `bgperf2-9su`, `bgperf2-0l7`, ...), that pass every
   test under **Running items in parallel** below. Complete the first item, plus any items
   that qualify, and verify each against its phase's exit criterion. If none qualify, this is
   one item, exactly as before.
3. **Record each item in the same step, both sides:**
   - the item in the plan (strike it through and add the commit), and the phase's `Progress:`
     line;
   - the phase's `**Status:**` line, and the bead to match: `bd update <id> --status
     in_progress` when a phase starts, `bd close <id> --reason="<sha>, plan §N"` when it is done.

   Each item gets its own commit and its own record; parallel items are never squashed into one.
   Run the checker again; it must exit 0.
4. **Stop**, and tell the user to say `continue the 2026 daemon comparison` again.

Rules this contract adds to `CLAUDE.md`'s:

- **A decision marked "(operator)" in the plan is never guessed**, and never delegated. Lay out
  the options the plan records and stop.
- **Phases 3 and 4 run benchmarks that take the whole host for hours.** Confirm with the user
  before starting one, and never run two at once.
- **Phase 4's items 2 and 3 need an `m7a.8xlarge` that only the operator provisions** (plan §6,
  decided 2026-10-02). Item 1 is code and runs on whatever host this is. Before item 2, confirm the
  host with `lscpu` against §6; on any other host, say so and stop.
- **Beads never carry reasoning.** A finding goes into the plan (or the decision log), and the
  bead gets at most a pointer. The checker flags a description long enough to be prose.
- `/code-review` before every code commit, as `CLAUDE.md` requires.

## Delegation

The main session is the operator's counterpart: it reads the plan, chooses the work, judges
the evidence, writes the record and commits. Subagents do the legwork. Pick the cheapest model
that can do a job without needing judgement it isn't given:

| job | agent | model |
|---|---|---|
| Sweep artifacts or logs into a table (a field across every `events.json`, a count across a RIB) | `Explore`, or `general-purpose` when it must run a script | `haiku` |
| Run the checker, the test suite or `bd` queries, and report pass/fail with the output | `general-purpose` | `haiku` |
| Read upstream daemon source to answer a stated question (does RustyBGP honour NO_EXPORT? what does FRR's tie-break do?), citing file and line | `Explore` | `sonnet` |
| Write a bounded code change against a spec the main session wrote, with its tests | `general-purpose`, `isolation: "worktree"` when another agent is editing too | `sonnet` |
| Adversarially check a finding before it is recorded ("try to break this explanation") | `general-purpose` | `opus` |

What stays in the main session, whatever it costs in context:

- **Interpreting evidence and writing findings.** Every rule in `docs/invariants/` exists
  because a plausible reading published a wrong number. A subagent returns data, with its
  method and where it read it; the main session decides what the data means. Anything a
  subagent reports that will be recorded is re-checked here first. The cheapest check is one
  count reproduced independently, the way 1.1's 95,945 against 119,784 ruled out a plausible
  but wrong cause.
- **Writes to the plan, the decision log and beads.** One writer, so two agents cannot record
  conflicting states and the checker always describes one truth.
- **Commits, and `/code-review` before them.**
- **Operator decisions.** No model makes them.

## Unattended runs on spot

Since 2026-10-05 the remaining steps also run without a session (plan §9, "Operator decisions,
2026-10-05, on running the rest unattended on spot"). `scripts/spot_boot.sh` runs the configs in
`/data/bgperf-work/unattended/comparison-queue` and starts a headless session to record each one, on branch
`unattended/comparison`. Its log is `/data/bgperf-work/logs/spot-boot-*.log`. In an interactive
session, check first whether it is running, because it holds the host:
`pgrep -af 'scripts/spot_boot.sh'`. Also check what is left in the queue and what
`unattended/comparison` holds that master does not. Never start a batch beside it. The queue is
the operator's list: add to it only what an approval in the plan names.

## Running items in parallel

Independent items may run at once, each in its own subagent. An item qualifies only if:

1. **Nothing it needs is unfinished.** No bead dependency on unfinished work, no earlier plan
   item it reads from, and no operator decision pending.
2. **It does not touch the host's shared resources while anything else might.** Docker image
   builds, container runs and `prepare` all qualify as touching them. A Phase 1/2 item that
   builds images runs alone, or alongside read-only work only. **Nothing runs while a benchmark
   is running**, not even a read-only agent: Phase 3 rows are measured on this host, and the
   agents' CPU is contention that lands in those rows. This
   is the one rule here that protects the published numbers rather than the record.
3. **It edits no file another parallel item edits.** Code changes run in separate worktrees
   and are reviewed and merged one at a time.

Cap a session at **three** concurrent subagents unless the user asks for more. Past that, the
main session cannot check everything they return, and unchecked results are what this plan
exists not to publish.
