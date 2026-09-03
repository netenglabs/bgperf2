# Unattended Execution Plan

Status: proposed on 2026-09-03; steps 0 and 1 taken the same day.
The continuation prompt at the end of this document is now an operator contract
in `CLAUDE.md`, which settles two things this document deliberately left open --
the driver's scope and where its commits go; see the contract. Step 2 is next,
and steps 2 onward are untaken: beads is not installed and no epics or items
exist. Nothing here changes how the three existing contracts run, or any
measurement semantics.

## Purpose

This plan describes how to run the existing bgperf2 plans across multiple
sessions without a human acting as the scheduler between every change set.

The work in this repository is already decomposed. Three operator contracts in
[`CLAUDE.md`](../CLAUDE.md) — the 2026 benchmark campaign, the measurement
implementation plan, and the 64 GB timing validation campaign — each define a
fixed continuation prompt, a durable state check, and a stop condition. They
work. What they do not do is start themselves.

The objective is:

> Let one worker take the next ready item from any plan, complete it under the
> existing review discipline, park anything that needs a human decision without
> stopping, and continue — until the work runs out or a decision blocks it.

## The Two Problems

These are separate, and conflating them is why the situation looks harder than
it is.

**Decomposition and durable state.** What is next, what is blocked, what is
done, across three plans. This is largely solved already: the plan documents
carry phase structure and appended `Progress on <date>` sections, benchmark
suites leave `COMPLETE` markers, and git history records every reviewed change
set.

**The driver.** Something has to invoke the agent again when a change set
finishes. When this was written that was unsolved, and it was the human typing
the continuation prompt. It is no longer: this harness self-paces a `/loop`
between change sets, which is stage 1 below with no new tooling at all, and its
`schedule` command drives a fresh-context worker on a cron, which is stage 2
without the shell loop. What beads still adds is the ready queue those drivers
read from -- see stage 2, which is where a fresh session's inability to find
"the first incomplete phase" in 1,383 lines of prose starts to bite.

**Beads addresses only the first problem.** It is a tracker, not a scheduler.
Adopting it without a driver changes nothing about how unattended the work is.
Fixing the driver without adopting beads produces most of the benefit
immediately. The order in this plan follows from that.

## Current State

What exists:

- three operator contracts with stable continuation prompts;
- plan documents as the durable record of intent, evidence, and progress;
- `COMPLETE` markers and progress JSON under the results root;
- a `PreToolUse` hook that requires `/code-review` before a code commit;
- a Docker-free unit suite of 491 tests that runs in under three seconds.

What is missing:

- a single ready-queue across plans — ordering between the three contracts is
  enforced by the operator remembering it;
- a place to record work discovered mid-change-set that is not the tail of a
  1000-line markdown document;
- any mechanism for parking a decision, so a decision currently stops the
  session rather than one item;
- a driver;
- beads itself — `bd` is not installed on this host.

## What Beads Adds

Four primitives matter here.

| Primitive | Solves |
|---|---|
| `bd ready` | What can be worked on now, across every plan at once |
| labels, `--label` | Separating and reporting work by plan |
| dependencies | Ordering plans against each other |
| gates (`--blocks`, type `human`) | Parking a decision without stopping the worker |

Two secondary ones are worth using: `bd update <id> --claim` is an atomic
claim, so adding a second worker later needs no redesign, and `bd remember` /
`bd prime` carry insight across sessions without a session having to re-read
every plan document.

The gate is the piece with no equivalent today. It is an explicit asynchronous
wait condition that only a human closes, and it is what turns a decision from a
session-ending event into a blocked item.

## Fixed Constraints

- **Plan documents remain the source of intent and evidence.** Beads holds work
  items — a title, an exit criterion, and a link to the document anchor. It does
  not hold the prose. The reasoning in the plan documents and in `CLAUDE.md` is
  the most valuable content in this repository and must not be shredded into
  issue bodies.
- **Never run benchmark suites or cells concurrently.** The ceiling on workers
  is the machine, not the tracker: `contention.py` exists because a benchmark
  sharing its host reports numbers that look fine and are not comparable.
- **Unattended work does not commit to master.** Each plan gets a branch.
- **An unattended worker never guesses a decision.** It opens a gate and moves
  on.
- **Review discipline is unchanged.** `/code-review` before every code commit,
  as `CLAUDE.md` requires, is part of the definition of done for every item.
- **The Docker-free import and unit-test property is unchanged.**

## Work Model

### Epics and labels

One epic per plan, one label per plan:

| Epic | Label |
|---|---|
| bgperf2 measurement implementation | `plan:measurement` |
| 2026 64 GB timing validation campaign | `plan:timing-64gb` |
| 2026 benchmark campaign (`2026-baseline`) | `plan:campaign` |

Labels are for selection and reporting — "show me what is left in the
measurement plan." They are not for ordering.

### Ordering is a dependency, not a label

The measurement plan gates the 64 GB campaign: the campaign plan already states
that it must not begin until the release gate passes, and `CLAUDE.md` repeats
it. That ordering is currently enforced by the operator remembering it.

Encode it instead: the campaign epic is blocked by the release-gate item. Then
`bd ready` structurally cannot offer campaign work early, and an unattended
worker cannot start the wrong plan even if nothing else in the measurement plan
is ready.

The same applies within a plan. The measurement phases are sequential, so they
form a dependency chain; the 64 GB blocks are sequential for the same reason.

### Granularity

One item per phase or block, not per line of the plan document. The measurement
plan has Phase 4, Phase 5, Phase 5A and Phase 6 remaining — four items, not four
hundred. The 64 GB plan has Blocks 0 through 11.

The release gate is a fifth item, and deliberately not a sixth phase: it is a
subsection of Phase 6, which the plan document titles "Calibration and release
gate". It is split out because it is what the campaign epic depends on. Hanging
that dependency on Phase 6 instead would let the campaign start as soon as the
phase was closed — a worker's judgement — rather than when the gate was opened,
which is the plan document's own checklist.

A phase that turns out to need several reviewable change sets gets child items
at that point, not in advance. The existing contract already says one smallest
reviewable change set per continuation; the child items are how that gets
recorded when a phase splits.

### Definition of done

Unchanged from the current contracts, with one addition at the end:

1. focused unit tests;
2. the full unit suite when shared timing, batch, convergence, result or
   lifecycle code changed;
3. required Docker verification for phases that call for it, smallest realistic
   workload, `/var/tmp/bgperf`;
4. `/code-review` on the working diff, findings acted on;
5. progress recorded in the plan document as today;
6. commit;
7. close the item.

## Human Decisions

When a plan reaches a point that requires a decision, the worker must not
choose. The sequence is:

1. open a gate blocking the affected item, recording the question, the options,
   the evidence, and a recommendation;
2. notify the user out of band, so the gate is visible without reading the
   tracker;
3. return to `bd ready` and take the next unblocked item;
4. if nothing is ready, sleep and re-check rather than exiting — a 20 to 30
   minute wakeup costs nothing and resumes the moment the gate is closed.

The point of this is step 3. Today a decision stops the session. Under this
model it stops one item, and only stops the worker when it has blocked
everything else too.

**A gate nobody sees is worse than stopping.** Stopping is at least visible in
the terminal. A gate that is opened, never surfaced, and silently blocks the
only ready item leaves a worker that looks busy and is idle. The notification
in step 2 is not optional.

## The Driver

Two stages, in order.

### Stage 1: self-paced loop, supervised

```
/loop continue the bgperf2 measurement implementation plan
```

One session, and its iteration is *review until clean*, not one review per
change set -- see the step 1 progress note, where two small change sets took
twenty-five rounds and a third of the findings were in code the earlier rounds
had added. The agent works a change set, then schedules its own next wakeup
instead of stopping. The existing continuation prompt drops in unchanged, so
this stage requires no beads and no other work in this plan. It is the whole
benefit of removing the human from the loop, available immediately, and it
should be run supervised for several change sets before anything else here is
adopted.

Its limit is context: a single session accumulates, and the harness summarizes.
That is fine for a handful of change sets and not for an overnight run.

### Stage 2: headless loop

```bash
while :; do
  claude -p "take exactly one ready item from beads and complete it;
             exit 3 if nothing is ready" && continue
  case $? in
    3) sleep 1800 ;;   # nothing ready: a gate is open, wait for a human
    *) break ;;        # a real failure: stop, leave the tree for inspection
  esac
done
```

**An empty queue is not a failure, and must not be mistaken for one in either
direction.** A loop that breaks only on a non-zero exit spins as fast as the
model can decline, because a worker that correctly finds nothing to do
*succeeds*; one that treats every non-zero exit as an empty queue sleeps
through a crash. The two need distinct exit codes, and the worker's prompt has
to specify the empty-queue one — this is the same requirement as step 3 of
[Human Decisions](#human-decisions), which is where an empty queue normally
comes from: every remaining item is behind a gate.

Fresh context per iteration, so session length stops being a limit. This only
works when the state lives entirely outside the session — which is what the
work model above provides, and what the plan documents alone do not, because a
fresh session cannot cheaply determine "the first incomplete phase" by reading
1000 lines of prose three times over.

Graduate to stage 2 when stage 1 has completed several change sets without
producing a diff that review had to reject.

## Migration Sequence

Each step is small and independently useful. Stop at any point and the
preceding steps still stand.

### Step 0: register this contract

Add `continue the unattended execution plan` to the operator contracts in
`CLAUDE.md`, beside the three that are already there, pointing at this document.

Until that is done the prompt at the end of this document is not a contract —
it is a sentence in an untracked file that a fresh session has no reason to
read, so the first continuation would be interpreted from scratch. Every other
contract in this repository is reachable because `CLAUDE.md` names it; this one
is not yet.

**Exit criterion:** a session given that prompt and nothing else finds this
document and reports which migration step is next.

#### Progress on 2026-09-03: the contract exists, and it names what it will not do

`CLAUDE.md` now carries `continue the unattended execution plan` beside the
other three contracts, so a fresh session has a route to this document. Two
decisions were made there rather than here, because they bind the driver and
this plan is only the mechanism:

- **Scope is the measurement plan, stopping at Phase 6.** Phase 6 is the first
  phase needing real calibration runs, and the host that will run the campaign
  is a 64 GB machine with a **different CPU** from the 8-core / 30 GB
  development host. So the stop is not a convenience -- calibration taken here
  would describe a machine the campaign never runs on, and nothing downstream
  refuses to compare rows from two hosts. This is the gate from
  [Human Decisions](#human-decisions) in the only form available before beads:
  a sentence in the contract rather than an item a worker is blocked by.
- **Commits go to `unattended/measurement`, never master.**

Exit criterion met: the prompt is registered and points here. Step 1 (driver,
supervised) is next, and is a stage-1 `/loop` against the measurement plan --
whose remaining work is the three-to-five variance rule in Phase 5, then all of
Phase 5A.

### Step 1: driver, supervised

Run stage 1 against the measurement plan for at least two change sets under
observation.

**Exit criterion:** two consecutive change sets completed and committed without
the operator typing the continuation prompt, and without a review finding that
required reverting.

#### Progress on 2026-09-03: two change sets, and what the driver actually costs

Exit criterion met. Two consecutive measurement-plan change sets were completed
and committed from one continuation, with the operator typing nothing between
them:

- `9eba403` -- Phase 5's named variance rule (`summary.py`), which completes
  Phase 5.
- `79dc690` -- Phase 5A's first work item, peer scaling at a constant table
  size.

The host was rebooted mid-change-set before this session began. The first thing
the contract asks for -- inspect durable state, resume unfinished work -- is
what recovered it: the working tree held a complete, uncommitted change set,
and nothing was lost. That is the failure mode a driver has to survive, and it
survived it by accident rather than by design, which is worth saying plainly.

**No review finding required reverting**, which is the other half of the
criterion. One came close: the first attempt at reading a batch default filled
it into the target dict, which is part of the cell identity, and three existing
tests went red because it would have renamed every completed cell of every
in-flight batch. That is the test suite doing the job the criterion describes.

Two things this exposed about the discipline, both of which belong to whoever
runs stage 2:

- **Review is the expensive part, not the work.** The two change sets took
  twenty-five `/code-review` rounds between them and thirty-odd findings, and
  the rounds ran five to fourteen minutes each. Neither change set was large.
  A driver that assumes one review round per change set will commit unreviewed
  work; the loop has to be *review until clean*, and the clean round is the
  commit signal.
- **Roughly a third of the findings were in code added by an earlier round of
  the same review.** A guard is code and gets the rule as wrong as the code it
  guards, and a default can replace a loud failure with a quiet wrong answer.
  Re-reviewing after each fix is not ceremony here; it is where a third of the
  defects were found.

Both are recorded in `CLAUDE.md` and in the measurement plan's own notes rather
than only here, since they outlive this step.

### Step 2: install and inspect beads

Install per the upstream README and run `bd init`, then `bd setup claude`.

**Review what `setup` writes before accepting it.** It installs hooks and an
`AGENTS.md`. This repository already has all three: two `PreToolUse` hooks (one
carrying the review requirement, one denying git invocations reached by `cd`), a
`CLAUDE.md` whose contents are hard-won, and an `AGENTS.md` addressed to Codex
and other agents. `AGENTS.md` is the one at real risk — it is the file `setup`
writes by name, and unlike a replaced hook a clobber there leaves nothing
visibly broken. Diff all three; the setup output is a starting point to merge,
not a file to accept.

Confirm the CLI surface against the installed binary at this point. The command
and flag spellings used in this document — `bd dep add <child> <parent>`,
`bd gate create --blocks <id>`, `bd update <id> --claim`, `bd list --label` —
were taken from upstream documentation, not from a local install.

**Exit criterion:** `bd ready` runs, and nothing in `.claude/settings.json` or
`CLAUDE.md` was silently replaced.

### Step 3: seed the epics

Three epics, three labels, no items yet.

**Exit criterion:** `bd list --label plan:measurement` returns the epic.

### Step 4: seed the measurement plan

Phases 0 through 3 closed as complete. Phase 4, Phase 5, Phase 5A, Phase 6 and
the release gate created as a dependency chain, each carrying its exit criterion
from the plan document.

**Exit criterion:** `bd ready --label plan:measurement` returns exactly Phase 4.

### Step 5: seed the 64 GB campaign

Blocks 0 through 11 as a chain, with Block 0 blocked by the release-gate item
from step 4.

**Exit criterion:** `bd ready` returns no campaign work while the release gate
is open.

### Step 6: headless driver

Stage 2, on a branch, with the notification path for gates verified first.

**Exit criterion:** an unattended run completes at least one item, opens a gate
on a decision rather than guessing, and continues to the next ready item.

## Traps

Each of these makes the arrangement look like it is working while it is not.

- **Two sources of truth.** If an item body starts accumulating reasoning, the
  plan document stops being authoritative and neither is complete. Items link to
  the document; they do not summarize it.
- **A tracker that outruns the machine.** `bd ready` will happily offer two
  Docker items at once. Concurrency here is bounded by the host, and a second
  worker running a benchmark alongside the first produces rows that are not
  comparable with anything — the failure `contention.py` was written to catch,
  and one that looks like a real version difference.
- **Unattended commits to master.** There is no CI on this repository. The
  review hook is the only guard, and it is advisory context, not a block.
- **A closed item that was never verified.** The definition of done includes the
  exit criterion from the plan document, not the worker's judgment that the
  change looks finished.
- **Gates opened into silence.** Covered above; repeated here because it and the
  empty-queue spin are the two failure modes in this plan that report no problem
  at all — one leaves a worker that looks busy and is idle, the other a worker
  that looks idle and is burning tokens.

## Continuation Prompt Contract

Use this prompt in a new session, once step 0 has registered it in `CLAUDE.md`:

> continue the unattended execution plan

The operator contract for that prompt is:

1. read this plan, and inspect which steps are complete;
2. complete exactly one step from the migration sequence;
3. verify its exit criterion;
4. record progress in this document;
5. stop, and tell the user to use the same prompt again.

This plan is infrastructure for the other three contracts. It does not itself
run a benchmark, and adopting it does not change any measurement semantics.

## Bottom Line

The driver is the bottleneck, not the decomposition. Stage 1 removes the human
from the loop with no new tooling and should be tried first. Beads earns its
place after that, for three things the plan documents cannot do from a fresh
session: answer what is ready across plans in one query, enforce plan ordering
structurally, and park a decision without stopping the worker.
