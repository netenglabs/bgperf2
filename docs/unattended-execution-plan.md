# Unattended Execution Plan

Status: proposed on 2026-09-03; steps 0 through 5 taken the same day.
The continuation prompt at the end of this document is now an operator contract,
carried by the `unattended-execution` skill (`.claude/skills/unattended-execution/SKILL.md`)
and named in `CLAUDE.md`'s contract table. It settles two things this document
deliberately left open -- the driver's scope and where its commits go; see the
contract. Step 6 is next:
`bd` 1.2.2 is installed and initialized, the three epics exist, the measurement
plan's phases are seeded, and the 64 GB campaign's twelve blocks are seeded
behind its release gate, so `bd ready --exclude-type=epic` offers the four
untaken Phase 5A change sets and nothing else. Nothing here changes how the
three existing contracts run, or any measurement semantics.

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
- a Docker-free unit suite of 814 tests that runs in under ten seconds.

What is missing:

- a single ready-queue across plans — ordering between the three contracts is
  enforced by the operator remembering it;
- a place to record work discovered mid-change-set that is not the tail of a
  1000-line markdown document;
- any mechanism for parking a decision, so a decision currently stops the
  session rather than one item;
- a driver;
- beads itself — `bd` was not installed on this host when this was written; step 2
  installed 1.2.2.

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
   workload, `/data/bgperf-work`;
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

#### Progress on 2026-09-08: the campaign host is settled, and one stop rule loses its reason

The note above says the driver stops at Phase 6 because calibration taken on
the development host "would describe a machine the campaign never runs on."
That is no longer true, and the sentence is left standing above because this
record is append-only -- the reading that was current on 2026-09-03 is part of
how the decision was reached.

What changed, in two steps. The development host was resized on 2026-09-03 from
8 vCPU / 30.65 GiB to **16 vCPU / 61.44 GiB, AMD EPYC 9R14 (`m7a.4xlarge`)**,
which removed the memory objection: the heaviest baseline row peaked at 25.3 GB
target RSS with 14.25 GB free of 60.74, and that now fits. Then on 2026-09-08
Justin chose this machine as the campaign host, as the closest available match
to the host that produced `benchmarks/baseline/baseline-benchmark.csv`.

So the development host and the campaign host are one machine, and the
two-hosts-are-two-experiments objection no longer applies to anything run here.
The match is on memory and **not on CPU**, which costs exactly one thing:
campaign rows may never be read against the old baseline CSV. The campaign was
already designed that way -- it is not a continuation of `2026-baseline` and
re-runs its comparisons under a new run identity -- so nothing is given up, but
nothing downstream refuses the comparison either.

**The Phase 6 stop stays, on its remaining reason.** A calibration is a
multi-hour benchmark that takes the whole host exclusively, and starting one is
the operator's call. That reason was always underneath the host argument; it
was simply never the binding one. It is stated in the `unattended-execution`
skill, in the form the worker actually reads.

The lesson is the one this repository keeps relearning and is worth naming
here, because a driver is the thing least able to notice it: **a rule outlives
the fact it was derived from.** "Stops at Phase 6" was correct on both readings
and would have gone on being obeyed for a reason that had evaporated, in a
document written to be followed without supervision.

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

#### Progress on 2026-09-03: installed, and what it wrote without asking

Exit criterion met: `bd ready` runs (reporting no open issues), and neither
`.claude/settings.json` nor `CLAUDE.md` lost anything. `bd` 1.2.2 is installed
at `~/.local/bin/bd` and the workspace is initialized with prefix `bgperf2`.

Four things this step found that the plan did not anticipate, all of which
matter to whoever writes step 6.

- **Upstream moved.** `steveyegge/beads` now redirects to `gastownhall/beads`,
  and the GitHub API does *not* follow that redirect without `-L` -- it returns
  301 with an empty body, which reads as "no such release" rather than as a
  move. There is no Go, npm or cargo toolchain on this host, so the install was
  the `linux_amd64` release tarball, checksum verified against the release
  `checksums.txt` before unpacking.
- **`bd init` commits to git by itself.** It touched 18 files -- creating `.beads/`,
  `.agents/skills/beads/` and `.codex/`, and editing `.gitignore`, `AGENTS.md`,
  `CLAUDE.md` and `.claude/settings.json` -- and committed all of it to the
  current branch in one commit, unreviewed. The review hook did not fire and
  could not have: it matches `git commit` in the *Bash command text*, and the
  command was `bd init`. That is the review discipline being bypassed by a tool
  the plan adopted to support it. It landed on `unattended/measurement` rather
  than master only because that is the branch that happened to be checked out.
  The commit is left in place as the record of exactly what the tool wrote, and
  reviewed here after the fact.
- **`core.hooksPath` is repointed at `.beads/hooks`.** Five hooks there
  (`pre-commit`, `pre-push`, `post-merge`, `post-checkout`,
  `prepare-commit-msg`) now shell out to `bd`, and `.git/hooks/` is inert.
  Nothing lived in `.git/hooks/` but samples, so nothing broke -- but a repo
  git hook added later has to go in `.beads/hooks/` to run at all. The path is
  absolute and lives in `.git/config`, so it is per-clone and not inherited,
  and a worktree shares it -- an agent given `isolation: worktree` resolves
  hooks into the main checkout's `.beads/hooks`, not its own. Two consequences
  worth more than they first look: those hooks are **tracked files**, so
  checking out a branch changes what runs on the next commit -- branch content
  becomes locally executing code; and `master` has no `.beads/`, so checking it
  out leaves `hooksPath` naming a directory that does not exist and every hook
  silently stops running.
- **`AGENTS.md` was not clobbered.** The plan named it as the file at real
  risk. On 1.2.2 `init` appends a marked block to `AGENTS.md` and `CLAUDE.md`
  and re-serializes `.claude/settings.json`, preserving both existing
  `PreToolUse` hooks -- reordered and with `&`/`<`/`>` written as `\u0026`,
  `\u003c`, `\u003e`, which decode identically, so the hooks are unchanged in
  meaning. It also dropped the file's trailing newline, restored here. The one
  addition is a `SessionStart` hook running `bd prime --hook-json`, which is
  the integration working as intended and is kept.

`bd setup claude` was not run separately: `init` had already installed the
Claude integration, the skill and the Codex hooks. The block it appended to
`CLAUDE.md` carries a content hash in its marker and is rewritten on drift, so
editing inside it is pointless; where its instructions reach past task tracking
they are answered in a section beneath it, which is the mechanism the block
itself sanctions. Two of those conflicts are worth naming here because they are
this plan's own constraints: it offers `bd remember` as the place for
persistent knowledge, which is the "two sources of truth" trap in
[Traps](#traps) if taken literally, and it describes a session-close profile
that commits and pushes, which is not enabled and does not displace
`/code-review`.

**CLI surface, confirmed against the installed binary** rather than upstream
docs, as the step asked. All four spellings in this document are correct:
`bd dep add <child> <parent>` (first argument depends on the second;
`--blocked-by` and `--depends-on` are aliases for the positional), `bd gate
create --blocks <id>`, `bd update <id> --claim`, and `bd list --label` (`-l`,
AND across repeats; `--label-any` for OR). One correction: a gate is closed
with **`bd gate resolve <id>`**, not `bd close` -- `type: human` is already the
default, and `--reason` is where the question goes.

**What review changed, over and above the record above.** `/code-review` on
this step's diff returned eight findings, and the two that mattered were both
about state leaving the machine:

- **`sync.remote` had been auto-derived from `origin`** -- the shared public
  `netenglabs/bgperf2` -- so a `bd dolt push`, which `.beads/README.md` and the
  block appended to `AGENTS.md` both advertise, would have written this
  repository's issue state to `refs/dolt/data` on a public remote, unreviewed
  and past the branch rule. It is unset, with the reason recorded in
  `.beads/config.yaml`. One worker on one host needs no cross-machine sync.
- **`.beads/interactions.jsonl` was committed as a tracked runtime append
  log**, matched by nothing in `.beads/.gitignore`, so every `bd` session would
  have dirtied the tree and its contents eventually reached that same public
  remote. Untracked and ignored.

Three smaller ones were taken: the `SessionStart` hook now guards on
`command -v bd` and carries a timeout, since `.claude/settings.json` is
committed and `bd` is not a documented dependency of this repository, so a
clone without it would fail a hook every session; the repo-wide `*.db` that
`init` added to `.gitignore` is gone, being both unanchored -- it would have
silently untracked any future fixture anywhere in the tree -- and already
covered, anchored, inside `.beads/.gitignore`; and the two instructions the
`CLAUDE.md` addendum had left unanswered, the block's bans on `TodoWrite` and
on `MEMORY.md`, are answered there now.

**The review-bypass is closed, and closing it exposed an older one.** Recording
that `bd init` committed past the `/code-review` hook is not the same as fixing
it, and the next `bd` command that touched git would have been another
unreviewed commit. The hook now matches `bd init|setup|migrate|dolt|hooks` as
well as `git commit`. Testing that change is what turned up the real defect:
the pattern was `git +(-[^ ]+ +)*commit`, which does not match
**`git -C <dir> commit`** -- the form the sibling hook *forces* every git
invocation in this repository to take. The guard the repository describes as
"the only thing standing between a bad edit and master" has therefore never
fired for its own mandated commit form. It is now `git [^;&|]*commit`, verified
firing on `git commit`, `git -C <dir> commit` and `git --no-pager -C <dir>
commit --amend`, and silent on `status`, `log`, `diff`, `show` and on `bd
ready`. Over-matching is the right side to err on here: the hook only adds
advisory context, so a false positive costs a sentence and a false negative
cost eighteen files.

**A second review round, and what it caught in the first round's own fixes.**
Seven more findings, four of them in code the first round had just added --
the same proportion the [step 1 note](#progress-on-2026-09-03-two-change-sets-and-what-the-driver-actually-costs)
recorded, and the reason the loop has to be review-until-clean.

- **Unsetting `sync.remote` was not the same as disabling push.** The key is
  absent from the effective config, but `bd init` derives it from
  `remote.origin.url` and would rewrite it on any later `init` or `setup`, so
  the protection lasted exactly until the next setup command. The binary has a
  rig-level `no-push`, and it is now `true` in `.beads/config.yaml`; absence is
  not a setting. (The review proposed `dolt.local-only`, which does not exist
  in 1.2.2 -- the string in the binary is `skipping push: rig is local-only
  (no-push: true)`. A finding can be right about the hole and wrong about the
  plug.)
- **The widened review hook still had an easy miss**: it anchored on
  `(^|[;&|] *)`, so an *indented* `git commit` -- the normal shape inside an
  `if`, a loop or any multi-line block -- did not match, nor did an
  env-prefixed `BD_X=1 bd init`. It now allows any run of non-separator
  characters after the anchor, and is verified firing on all of those and on
  `git -C <dir> commit`, and silent on `status`, `log`, `diff`, `show`,
  `pytest` and `bd ready`.
- **The `SessionStart` guard was fixed only on the Claude side.** `bd init`
  also wrote four unguarded Codex hooks (`UserPromptSubmit`, `SessionStart`,
  `PreCompact`, `PostCompact`) and enabled hooks in `.codex/config.toml`. All
  four now carry the same `command -v bd` guard and timeout.
- **The corrective section existed only in `CLAUDE.md`.** `bd init` appended
  its block to `AGENTS.md` too, and a Codex or other non-Claude agent reads
  that file alone -- so it saw the unqualified `bd dolt push` session-close
  recipe and the `TodoWrite`/`MEMORY.md` bans with none of the answers.
  `AGENTS.md` now points at the `CLAUDE.md` section rather than repeating it,
  since two copies of a resolution is the same trap as two sources of truth.
- **The `interactions.jsonl` ignore rule was put in a file `bd` rewrites.**
  Moved to the repo-root `.gitignore`, which no tool manages, and verified as
  the fallback with `.beads/.gitignore` moved aside. An ignore rule inside a
  tool-managed file is one the tool can take away.

One finding was recorded rather than fixed: the five `.beads/hooks` scripts
abort the whole `git commit` on any `bd` exit other than 0, 3 or a timeout, so
a held Dolt lock or a stopped server blocks committing entirely. Patching
tool-managed files that `bd` rewrites would trade a loud failure for a silent
one, so the hazard is written down instead.

**Also found, by neither review: `bd` ships telemetry on by default**, posting
to `https://gastownhall-eventsapi.com/mp/collect` per the user-global
`~/.config/bd/config.yaml`. `metrics.disabled` is now `true`. Worth knowing
before step 6 puts this tool in an unattended loop.

**A third round, and the one result worth the whole exercise.** Round two had
asked whether `bd setup` would quietly revert the hook guards it had just
added, and guessing was not good enough, so it was tested: back up
`.claude/settings.json`, run `bd setup claude`, diff, restore. It does not
revert them. **It appends a second, unguarded `SessionStart` hook beside the
guarded one**, so both run and the bare `bd prime --hook-json` is back --
while the guarded entry sits above it still looking correct. A revert would at
least show up as a changed line. Duplication reinstates the defect and leaves
the fix visibly in place, which is the harder failure to see. The duplicate is
removed; the lesson is that `bd setup` is not idempotent against an edited
hook, so its output is reviewed every time it is run, and it is never run
casually.

Four more from that round, all of them consequences of rules this step had
already written down and then not applied widely enough:

- **The root ignore rules covered `.dolt/`, which does not exist here, and not
  the issue store, which does.** `.beads/embeddeddolt/` (the live Dolt
  database) and `.beads/backup/` (exported issue JSONL) were ignored only by
  `.beads/.gitignore` -- the file this step had just declared untrustworthy for
  exactly that reason. A regenerated template that drops one entry, one
  `git add -A`, and the issue store is on a public remote. They are anchored at
  root now, and verified with `.beads/.gitignore` moved aside.
- **The duplicate `interactions.jsonl` rule is gone from `.beads/.gitignore`**,
  so the root rule is the one actually matching rather than an untested
  fallback sitting behind a tool-managed line.
- **The review hook missed `bd bootstrap`, `bd worktree` and `bd backup`.**
  `bootstrap` re-wires origin for push, which would silently undo the
  `sync.remote` unset. All three are matched now.
- **`.beads/config.yaml` had lost its trailing newline** to `bd config set`,
  so the next appender would have produced `no-push: truebackup:` on one line
  and dropped the only remaining guard against a re-derived remote.

And a correction to this note's own telemetry claim: `metrics.disabled` cannot
be set per-repository. `bd` 1.2.2 reads `metrics.*` only from the user-global
`~/.config/bd/config.yaml` -- a `metrics` block in `.beads/config.yaml` is
accepted and silently ignored, which was verified rather than assumed. **The
opt-out is host-local and does not travel with the repository**, so the 64 GB
campaign host needs `bd config set metrics.disabled true` of its own. The
config file records that where someone would look for the setting, instead of
carrying a block that looks like protection and is not.

**A fourth round, and the finding that reaches step 6 directly.** The
corrective section had been written against the *static* block `bd init`
appends. But the `SessionStart` hook this step kept and hardened injects
`bd prime` into every session, ahead of anything it reads, and that text says
the same things far more forcefully -- verbatim: "**Prohibited**: Do NOT use
TodoWrite, TaskCreate, or **markdown files for task tracking**" and "Do NOT use
MEMORY.md files". All four operator contracts in this repository are driven by
plan documents under `docs/`, and every one of them makes recording progress in
the document part of being done. An unattended driver that took the injection
literally would stop writing the record its own contract is defined by -- and
would look like it was working. The section now governs the injection by name,
in `CLAUDE.md` and in `AGENTS.md`, and answers the markdown ban specifically
rather than only the `TodoWrite` and `MEMORY.md` ones.

Four smaller ones, three of them in round three's own fixes:

- **The root ignore net covered the store directories and not `.beads/.env` or
  `.beads/ephemeral.sqlite3*`** -- by bd's own comment the `.env` is the Dolt
  connection config, the one file there that plausibly holds a credential, and
  the sqlite file holds issue content. Closed for the directories, left open
  for the two files where it would cost most. Both anchored now and verified
  the same way.
- **The `bd` alternation fired on read-only inspection** -- `bd dolt status`,
  `bd hooks list`, `bd backup list`, even `bd dolt --help` -- while telling the
  reader those commands commit to git, which is false. A guard that cries wolf
  on inspection is one a worker learns to skim, and this one has to survive an
  unattended loop. It now names the mutating subcommands, verified firing on
  all nine and silent on the five read-only forms.
- **`bd doctor --fix` and `bd vc commit` were missing from it.** `doctor --fix`
  regenerates `.beads/.gitignore` and the git hooks -- it is the concrete
  mechanism behind "a regenerated template that drops one entry", which is the
  premise the whole ignore change rests on.
- **The `timeout: 20` added to the four Codex hooks is removed.** `bd` does not
  emit that key and codex's project hooks schema is experimental and could not
  be validated here; an unknown field that fails the parse would disable all
  four hooks silently, which is worse than the missing-`bd` failure the guard
  was added to prevent. The `command -v bd` guard is the substantive fix and
  stays. Unverifiable additive risk is not worth carrying next to a verified
  one.

Also clarified: `bd config show` reports `beads.role = maintainer`, inferred
from the git remote. That is beads' write-routing role and **not** the
team-maintainer profile the block describes, which this repository does not opt
into -- two different things a reader can easily collapse.

**A fifth round, which reviewed `master..HEAD` and came back with three low
findings.** Two were about this change set and are fixed:

- **The commit-advice regex over-matched.** `git [^;&|]*commit` matched the
  word anywhere in a git command, so `git log --grep=commit` and `git show
  HEAD -- docs/commit.md` both fired. That is the same cry-wolf problem round
  four fixed on the `bd` half, and the earlier "over-match is the right side to
  err on" reasoning does not survive it -- a guard that fires on `git log` is
  one an unattended worker learns to skim, which costs exactly the signal the
  round-two fix bought. It now requires `commit` to be its own argument,
  `git( [^ ;&|]+)* commit( |$)`, which keeps every `git -C <dir> commit` form.
  Getting there needed one more fix: the trailing `\b` closing the whole
  alternation could not hold after the space that ends `commit `, so every
  `git commit -m x` silently stopped matching. The boundary now closes the
  `bd` branch alone. Verified across 14 forms that must fire and 12 that must
  not, listed in the commit.
- **`.gitignore` narrowing `*.db` to `/.beads/*.db` removed a catch-all.** This
  was argued both ways across rounds -- round three asked for the narrowing
  because an unanchored rule silently untracks a future fixture, rounds five
  and six both asked for the catch-all back -- and the narrowing was the weaker
  side. `git add <file>` on an ignored path *errors* and names the ignore rule,
  so the untracked-fixture case is loud in the spelling anyone uses
  deliberately; only `git add -A` skips it quietly. Against that, a stray
  database committed by `git add -A` is the likelier accident and the more
  expensive one. `*.db` is restored beside the anchored beads rules, which stay
  for the separate reason that they must not depend on a file `bd` rewrites.

The third is **not** this change set's: an invalid `prefix_scope` on a test
that also has a `file:` target reports "prefix_scope has nothing to divide"
instead of naming the unknown scope, because the scenario-target branch is
checked before the value is validated. That is in `bgperf2.py` from the
peer-scaling work committed last session, it is a diagnostic-ordering bug
rather than a wrong answer, and folding a `bgperf2.py` fix into a beads
adoption commit would make both harder to review. It belongs to the
measurement plan's contract, and it is written down here so it survives until
step 4 can seed it as an item -- which is precisely the "place to record work
discovered mid-change-set" that [Current State](#current-state) lists as
missing.

An eighth round found nothing in this change set and one more of the same kind,
recorded here for the same reason: `resolve_prefix_scope()` normalisation
assigns `args.prefix_num` without also setting `args.prefix_scope` to
`per-peer`, so it is not idempotent on its own namespace -- calling `bench()`
twice on one `Namespace` under `--prefix-scope total` would divide twice and
run a tenth of the table while reporting CONVERGED against the smaller
check-point. It is unreachable today, because the CLI calls `bench()` once and
`batch()` builds a fresh `Namespace` per cell and pins the scope itself; the
point is that the guard lives at the call site rather than in the operation.
Also `bgperf2.py`, also the measurement plan's.

**A sixth round found two more, both in round five's own fixes**, and one of
them is the reason the previous bullet reads the way it does. The other:
requiring `commit` to be its own argument had been written with single spaces,
`git( [^ ;&|]+)* commit`, so `git  commit -m x` -- two spaces, which the shell
accepts and a person types -- silently stopped matching. It allows runs of
spaces now. The remaining false positive, `git log --grep commit ` with the
pattern space-separated, is accepted: distinguishing it needs argument parsing,
and it costs one spurious reminder.

**A seventh round, one finding, again in the previous round's fix.** Requiring
`commit` to be followed by a space or end-of-line missed `git commit;` and
`git commit&&git push` -- a bare `commit` immediately followed by a separator.
That is an ordinary way to write a commit and it would have proceeded with no
reminder at all. The boundary is back to `commit\b`, which was what the
original pattern used; the reason it had been dropped was that the `\b` closed
the *whole* alternation, where it could not hold after the space ending
`commit `. Scoped to the git branch alone it is correct, and the round-two
`git -C` fix and the round-four narrowing both survive it. Verified on 14 forms
that must fire -- now including `git commit;`, `git commit&&git push` and
`cd /d; git commit` -- and 9 that must not.

Three passes of this hook in a row each broke something the pass before had
fixed, in a regex of about eighty characters that nothing in the test suite
covers. That is worth noting for step 6: this guard is the only thing enforcing
review, it lives in a file `bd` rewrites, and it is verified today by running
it against a list of commands by hand. If the headless driver is going to
depend on it, that list belongs in a test.

Step 3 is next.

### Step 3: seed the epics

Three epics, three labels, no items yet.

**Exit criterion:** `bd list --label plan:measurement` returns the epic.

#### Progress on 2026-09-03: three epics, and three things the queue does not say out loud

Exit criterion met: `bd list --label plan:measurement` returns
`bgperf2-8gg`. The other two are `bgperf2-iee` (`plan:timing-64gb`) and
`bgperf2-c4u` (`plan:campaign`). No items yet, as the step says.

Each epic carries a title, an acceptance criterion, the path to its plan
document and the operator contract prompt that drives it, and says in its own
body that it holds no reasoning -- which is the
[two-sources-of-truth trap](#traps) written where a worker reading the item
will actually hit it, rather than only here.

**A childless epic is ready work, and all three were offered immediately.**
`bd ready` returned every epic the moment it was created; its documented
exclusions are "in_progress, blocked, deferred, and hooked", and having open
children is not among them. That matters to the two steps after this one,
because both state their exit criteria against `bd ready` and neither would
have held: step 4 wants *exactly* Phase 4 and would have got Phase 4 plus the
epic, and step 5 wants no campaign work at all while the release gate is open
and would have got the campaign epic. The query a driver must use is
`bd ready --exclude-type=epic` -- `epic` is the example in bd's own help text
for that flag -- and with it the queue is correctly empty today. Left
unnoticed, this is the failure mode the plan warns about twice over: a worker
would have claimed an epic, found no change set inside it, and either invented
one or reported the queue exhausted.

**The empty-queue message is not evidence about blockers.** With epics
excluded, `bd ready` prints "No ready work found (all issues have blocking
dependencies)" -- while nothing in the store has a dependency of any kind. And
it **exits 0** either way, which is the more consequential half: the stage-2
loop distinguishes an empty queue from a failure by exit code, and it cannot
read that distinction off `bd`. `bd ready --json` returning `[]` is the test;
translating that into the loop's own empty-queue code stays the worker's job,
exactly as [Stage 2](#stage-2-headless-loop) specifies.

**This step's entire output is untracked.** The epics live in
`.beads/embeddeddolt`, which is ignored on purpose -- `bd`'s own
`.beads/.gitignore` is the rule that matches, with the root rule step 2 added
behind it as the fallback that does not depend on a file `bd` rewrites -- and
`.beads/issues.jsonl`, the passive export `CLAUDE.md` names, does not exist.
`git status` is clean after creating three epics. So the ready queue is durable
across *sessions*, which is what [Stage 2](#stage-2-headless-loop) needs, and
not across the host, while every plan document it supplements is in git. That
is a real asymmetry rather than an oversight to fix in passing: tracking the
export would carry issue state to `origin` on any push of the branch, which is
a second route to the public remote step 2 closed for `bd dolt push`. It is
written down here so step 6 decides it rather than discovers it.

**The `2026-baseline` epic exists and has no seeding step, by design.** The
[work model](#epics-and-labels) asks for one epic per plan and this is the
third, but the migration sequence seeds only the measurement plan (step 4) and
the 64 GB campaign (step 5). That is consistent with
[`2026-bgp-performance-test-plan.md`](./2026-bgp-performance-test-plan.md),
whose Status section records that campaign as having produced its result and
retains its remaining phases as historical design context that are not
scheduled while the local 64 GB server is the only host. The epic says so in
its acceptance criterion. It is left open rather than closed as complete,
because "not scheduled" is a statement about the hardware available and
reopening it is a human's call; closing it would file that decision as done.

Step 4 is next.

### Step 4: seed the measurement plan

Phases 0 through 3 closed as complete. Phase 4, Phase 5, Phase 5A, Phase 6 and
the release gate created as a dependency chain, each carrying its exit criterion
from the plan document.

**Exit criterion:** `bd ready --label plan:measurement` returns exactly Phase 4.

#### Progress on 2026-09-03: the phases are seeded, and a parent that waits on its children deadlocks its children

Done, with one deviation from this step's own wording and one bd behaviour that
had to be found by running it.

**The exit criterion was met in intent and could not be met literally.** It asks
that `bd ready --label plan:measurement` return exactly Phase 4. It was written
while Phase 4 was the first incomplete phase; Phases 4 and 5 both landed on
2026-09-03, between that sentence and this one. What the criterion is for is
that the queue offer exactly the first incomplete unit of the measurement plan
and nothing behind or ahead of it, and it does: `bd ready --exclude-type=epic`
returns the four untaken Phase 5A change sets. Phases 0 through 5 are seeded
closed (`bgperf2-8gg.1` through `.6`), each with the date its status line in
[`bgperf2-measurement-implementation-plan.md`](./bgperf2-measurement-implementation-plan.md)
records. The step's own text -- "Phases 0 through 3 closed as complete" -- is
left standing above rather than rewritten, because a migration step that is
quietly edited to match what happened stops being a record of what was planned.

**Phase 5A got its five children now, and that is not seeding in advance.** The
[granularity rule](#granularity) says a phase gets child items when it turns out
to need several reviewable change sets, not before. Phase 5A has turned out: its
own status line says the peer-scaling workload landed and "the remaining five
work items below are untaken", and its Work list enumerates them. Seeding them
was also the only way to keep the queue honest. A single Phase 5A item is one
item that takes five change sets, and this harness's contract is one change set
per continuation -- so the driver would have claimed it, done one, been unable to
close it, and found `bd ready` empty next session with four change sets left,
because `bd ready` excludes `in_progress`. That is the
[empty-queue trap](#traps) reached without anyone doing anything wrong.

**`--waits-for-gate=all-children` does not gate a plain task.** It was the first
attempt at hiding the phase item while its children are open -- `bd ready`
documents excluding "hooked" issues, and `bd create` offers the flag on any
type. Created with it and left `open`, Phase 5A was offered as ready alongside
its four children. The flag appears to be molecule machinery; nothing in
`bd show` reports it either way.

**A parent that depends on its own children makes the whole subtree
unclaimable.** The second attempt was the obvious one: `bd dep add` Phase 5A on
each of its five children, so it is blocked until they close and ready
immediately after. `bd ready --exclude-type=epic` then returned **nothing at
all** -- not the parent, which was the point, but not the four children either,
which were ready a moment earlier and had acquired no dependency of their own
(`bd show` on one lists an empty dependency set and only the two things it
blocks). `bd blocked` reported each child as "Blocked by 1 open dependencies:
[bgperf2-8gg.7]", inverting the edge that was actually stored. So bd's
ready-work semantics propagate a blocked parent down to its children, and the
tracker reports a plan with five open change sets in it as having no ready work,
with nothing in the data looking wrong. Both edges are removed.

**The fix is step 3's rule at a second level: Phase 5A is typed `epic`.** The
driver's query is already `bd ready --exclude-type=epic`, for exactly this --
[step 3](#progress-on-2026-09-03-three-epics-and-three-things-the-queue-does-not-say-out-loud)
found that a container is offered as ready work whether or not it has children.
Typing the phase container the same way as the plan container costs no new rule
and no new flag, and the queue is correct. That the
[work model](#epics-and-labels) says one epic per plan is about labels and
selection; it does not stop bd's own epic/task/subtask hierarchy being used for
a phase that split.

**Phase 6 is blocked by the last Phase 5A child, not by the Phase 5A epic.**
This is the same trap once more and it is worth stating separately, because the
first wiring had it: an epic the driver never claims cannot be the thing that
unblocks the next phase. Phase 6 depending on `bgperf2-8gg.7` would have left
the queue empty the moment the last child closed, waiting on an item nothing
offers and no one is watching. It depends on `bgperf2-8gg.7.5` instead, so
closing the last child unblocks Phase 6 structurally. The epic is bookkeeping:
it is closed when its acceptance criterion holds, and if it is forgotten it
shows as an open epic in `bd list` and blocks nothing.

**`bgperf2-8gg.7.5` depends on the other four, and that ordering is a judgement
this note is the record of.** The plan document's Work list states no order
among the five. Four of them add a workload -- path diversity, export fan-out,
churn bursts, policy reload -- and the fifth asks that ingress, table-selection,
export and monitor timing stay independent "so parallel work is not collapsed
into one end-to-end number". There is no parallel work to keep uncollapsed until
the four exist, so it is wired last. The four are deliberately left unordered and
all four are offered at once; a single worker picking any of them is fine, and
inventing a sequence the document does not state would be worse.

**Phase 6 carries the driver's stop, and the release gate carries no checklist.**
`bgperf2-8gg.8` says in its own body that the unattended driver stops there --
the operator contract in `CLAUDE.md` puts Phase 6's calibration runs on the
campaign host, not this one -- so a worker that reaches it stops and says so
rather than starting a benchmark on the wrong machine. The plan document states
no one-line exit criterion for Phase 6, so that item's acceptance is its Work
list; the nine-condition release gate is `bgperf2-8gg.9` and its acceptance
*points at* the checklist rather than restating it, which is the
[two-sources-of-truth trap](#traps) in the one place it would have been most
tempting to copy nine lines.

**This step's output is untracked too.** `git status` is clean after seeding
fifteen items, for the reason step 2 and step 3 record: the store is
`.beads/embeddeddolt`, which is ignored, and `.beads/issues.jsonl` does not
exist. The durable record of the seeding is this note.

Step 5 is next, and its exit criterion -- `bd ready` returns no campaign work
while the release gate is open -- now has something to hang on: Block 0 of the
64 GB campaign depends on `bgperf2-8gg.9`.

### Step 5: seed the 64 GB campaign

Blocks 0 through 11 as a chain, with Block 0 blocked by the release-gate item
from step 4.

**Exit criterion:** `bd ready` returns no campaign work while the release gate
is open.

#### Progress on 2026-09-03: twelve blocks behind the gate, and an edge bd will not store

Done. `bd ready --exclude-type=epic` returns the four untaken Phase 5A change
sets and nothing else; `bd blocked` lists all twelve campaign blocks, and
they carry `plan:timing-64gb` by inheritance.

**The exit criterion holds under the driver's query, and cannot hold under the
bare one.** It asks that `bd ready` return no campaign work while the release
gate is open. Plain `bd ready` still offers all three epics -- that is
[step 3's finding](#progress-on-2026-09-03-three-epics-and-three-things-the-queue-does-not-say-out-loud),
not a new one, and the reason the driver's query is
`bd ready --exclude-type=epic`. No block is offered by either query.

**`bd` refuses to let an epic depend on a task**, so the
[work model's](#ordering-is-a-dependency-not-a-label) "the campaign epic is
blocked by the release-gate item" is not expressible as written:
`bd dep add bgperf2-iee bgperf2-8gg.9` fails with `epics can only block other
epics, not tasks`. The available substitute -- blocking the campaign epic on
the *measurement* epic -- was rejected twice over. It is
[step 4's deadlock](#progress-on-2026-09-03-the-phases-are-seeded-and-a-parent-that-waits-on-its-children-deadlocks-its-children)
a third time: a blocked parent propagates down to its children, so the whole
campaign would wait on someone closing a bookkeeping epic the driver never
claims. And it moves the gate from the plan document's checklist to a worker's
judgement that the measurement epic is finished, which is exactly what
[splitting the gate out of Phase 6](#granularity) was for. The structural
guarantee lives on `bgperf2-iee.1` instead, which depends on `bgperf2-8gg.9`
directly and is an item the driver does claim. The propagation itself was not
re-tested here; nothing seeded in this step relies on it either way.

**Block N is `bgperf2-iee.<N+1>`.** bd numbers children from 1 and the plan
numbers blocks from 0, so the ids are offset by one for all twelve. Every title
starts `64GB Block N:` so the item's own text is unambiguous; the offset is
recorded here because a worker matching id suffixes against block numbers would
be one block off the whole way down.

**Blocks 2-4 and 5-7 are six items, not two.** The plan document gives each
trio one section, but states its exit criterion *per block* -- "14 reviewed
rows or explicit durable exclusions" -- and its review boundary is a block, so
each repetition is its own item and names which of the three it is. Nothing is
typed `epic` here: no block has turned out to need several reviewable change
sets, and the [granularity rule](#granularity) says that happens when it turns
out, not in advance.

**Block 8 needs Phase 5A's four workloads and carries no edge saying so.** The
BIRD architecture screen runs path diversity, export fan-out, churn and policy
reload, which are `bgperf2-8gg.7.1` through `.7.4`. It is already blocked by
all four transitively -- the chain runs through Block 0 to the release gate,
which is downstream of every Phase 5A item -- and a direct edge would restate
an ordering the tracker already enforces.

**This step's output is untracked too**, for the reason steps 2 through 4
record: `git status` is clean after creating twelve items and twelve
dependencies, and this note is the durable record.

Step 6 is next.

### Step 6: headless driver

Stage 2, on a branch, with the notification path for gates verified first.

**Exit criterion:** an unattended run completes at least one item, opens a gate
on a decision rather than guessing, and continues to the next ready item.

#### Progress on 2026-09-15: the driver is built, and the criterion is NOT met

**Not done.** Every clause of the exit criterion is about a worker session
actually running, and no worker session could start: `claude -p` exited 1 with
*"You've hit your monthly spend limit … your weekly limit resets Sep 18, 2am
(UTC)"*. The driver did the right thing with that — stopped, left the tree, and
did **not** sleep — but that is the failure path, not the criterion. Recorded as
a gate (`bgperf2-cqi`) rather than as a step that nearly passed, because the
next session reads this note and a "nearly" is indistinguishable from a yes
once it is three weeks old.

What exists and is verified:

- **`scripts/notify_gate.sh`**, and the step's "notification path verified
  first" is verified as a *path*: delivered 0, unconfigured 78 (`EX_CONFIG`,
  distinct so the driver can tell "set this up" from "your channel is broken"),
  a channel that fails 1. **It has no fallback**, deliberately. The tempting
  one is a local log file, and a local log file *is* a gate nobody sees, so it
  would satisfy the code and defeat the rule. With nothing configured the
  driver refuses to start.
- **`scripts/unattended_driver.sh`**, whose refusals are the substance: it will
  not run off `unattended/measurement` (checked again inside the loop, since a
  worker can check out a branch mid-run), will not start without a channel that
  *just delivered a test message*, and filters benchmark-labelled items out of
  the queue before a session is spent rather than asking the worker to behave.
- **`scripts/unattended_worker_prompt.md`**, which is the whole of the
  discipline for a session nobody reads: review until a round comes back clean,
  full suite, never push, never master, never start a benchmark, and gate
  rather than guess.
- **`tests/test_unattended_driver.py`** — pure, no `claude` and no Docker.
  Deliberately not a count: a number here is the one falsifiable claim in this
  bullet, and the first version of it was stale on the commit that introduced
  it.

Four things this turned up that the plan had wrong or had not said.

- **`bd gate create --blocks <id>` does not exist.** Step 2 warned that this
  document's CLI spellings came from upstream docs rather than a local install,
  and this is one of them: `bd gate` is for formula steps and has no `create`.
  What works is the `human` label plus an ordinary dependency — `bd create
  --labels=human` then `bd dep add <item> <gate>` — which blocks the item and
  surfaces it in `bd human list`. Verified by opening a gate against a real
  item and watching it leave the ready queue.
- **A gate is ready work unless you exclude it.** An open gate is unblocked,
  unclaimed and P1, so it sorts to the *front* of `bd ready` — measured: it
  came back at position 1, ahead of every real item. A worker handed its own
  gate answers its own question and closes it, which is worse than guessing
  outright, because the tracker is then left recording that a human decided.
  `human` is in the driver's skip list for that reason.
- **The driver computes the queue; the worker does not report it.** The stage 2
  sketch above has the worker exit 3 for an empty queue. That puts the model's
  exit code and the tracker in a position to disagree — a worker that says 3
  with items ready stalls the loop, one that exits 0 having done nothing spins
  it, and both are the failure the two-exit-code rule is about. Reading `bd
  ready` in the driver before spending a session makes "nothing is ready" a
  fact the loop establishes. What is left for the model to get wrong is only
  the work. **The sketch is left as written above**, because it is the
  reasoning that produced this, and a corrected sketch would hide the
  correction.
- **The notification destination is a human decision and is now gated**
  (`bgperf2-5p6`). This host has `curl` and `tmux` and no mail, no
  `notify-send`, no configured webhook, so there is nothing to verify delivery
  *to*. The mechanism was verified against a file sink under supervision, which
  is legitimate while someone is watching and is exactly what the driver
  forbids for an unattended run.

**`/code-review` found twelve things, and the first was this file's own rule
broken in this file.** The header says a loop that treats every non-zero exit
as an empty queue "sleeps through a crash" — and `next_item()` wrapped `bd` in
`|| true` with stderr discarded, so a held Dolt lock, a stopped server, an
orphaned `venv/bin/python` or a `bd` run from a directory with no `.beads`
produced no output, read as an empty queue, and slept half an hour a round
forever. Moving the question from the worker to the tracker had moved the
failure with it. Every `bd` call now separates "answered, and the answer is
nothing" from "did not answer", and only the first sleeps. Verified by
execution against a stub that exits 7: exit 1, and the words "nothing ready"
never printed.

The rest, each a way an unattended run looks like it is working:

- **A bare `gates_before="$(open_gate_count)"` killed the driver silently.**
  Under `set -e` a failing `bd` exited the script with bd's own status and no
  message — and at the second call site that fires *after* the worker, so a
  session that opened a gate exited before the notification.
- **`bd` auto-discovers `.beads/` from the working directory, which the driver
  never set.** Started from a systemd unit with no `WorkingDirectory` every
  tracker call fails — straight into the bug above. Every call is `bd -C
  "$REPO_ROOT"` now.
- **Nothing claimed the item.** `bd ready` excludes `in_progress`, so a worker
  that exits 0 without closing its item left it open and unblocked and the next
  round handed back the identical id, unattended, forever. The header claimed
  this design removed that spin; it had only moved it. `bd ready --claim` is
  atomic and is what makes the queue advance.
- **Gate detection by count missed a new gate whenever an old one closed in the
  same window** — and the operator answering an earlier gate *while a worker
  runs* is the expected steady state here, so open-one close-one nets to zero
  and the new gate is never sent. Ids are compared now, not counts.
- **A failed notification only warned, and the loop ran on.** The warning goes
  to a terminal nobody is reading, which is the premise of the whole script. It
  stops, for the same reason the startup check is fatal.
- **`tmux display-message -p` was a documented channel that passes `--check`
  while delivering nothing**: it never reads stdin and prints to stdout, which
  the notifier sends to `/dev/null`. `--check` cannot detect that, which is
  worth knowing about any channel added later.
- The documented exit codes said `0` for an empty queue where the code says
  `3`; `--max`/`--sleep` died as `unbound variable` on an operator typo, which
  this file documents as "a real failure"; `--max N` counted sleeps as items,
  so a night idle exited 0 looking like N completed; and the worker ran
  unbounded, so a stalled session hung the loop looking like a long item.
- Two of the tests were vacuous: the empty-queue one accepted `0 or 3` against
  the *real* tracker, so it passed whether or not the path was ever taken, and
  the "says where it came from" one had an `or '@' in delivered` disjunct that
  is true of every message. The driver takes `BGPERF_BD_BIN` now so the tests
  can point it at a stub and actually exercise exit 3 and the tracker-failed
  path.

**A second review round found eight more, and the worst was in the fix the
first round asked for.** Claiming the item — added to stop the queue handing
back an id a worker had already failed on — is never released, and `bd ready`
excludes `in_progress` by *stored status*. So the worker prompt's gate path
("leave the item open and stop") was not achievable: the driver had already
flipped it. An item whose worker gates it, fails, or times out leaves the queue
**permanently** — not when its gate is answered, not when a human restarts the
loop — while the driver reports "nothing ready" over real work sitting
invisible. That is the pattern this plan's step 1 note already records: about a
third of review findings are in code an earlier round of the same review added.

The release needed both halves. Releasing alone reintroduces the spin the claim
was added to prevent, so a worker that exits 0 having neither closed nor gated
its item now stops the loop by name instead of being handed the same id
forever.

The rest:

- **The claim happens inside `bd`, before its output can be parsed**, and
  stderr was merged into the JSON buffer — so any notice `bd` writes made
  `json.loads` raise *after* an item had been claimed, consuming one item per
  start under a systemd `Restart=`. stderr goes to its own file now.
- **`human` was a default, and a default is a thing an operator replaces.**
  Setting `BGPERF_UNATTENDED_SKIP_LABELS` to the two benchmark labels — the
  plausible edit, since those are the two `--help` names — dropped it and put an
  open gate back at position 1. It is unioned in now and cannot be overridden.
- **Four tests passed only on this branch** and would go red the moment it
  merges, in a repo with no CI to notice; the one branch-aware refusal
  `skip`ped whenever you were on the branch, which is always. The expected
  branch is overridable, so each test pins what it is actually testing.
- `timeout` without `-k` waits forever for a child that ignores SIGTERM, which
  is the hang the bound exists to prevent; `--max 0` passed the guard and read
  as *unlimited*, and `--sleep 0` turned the idle branch into a tight query
  loop; the two environment numbers bypassed the guard entirely.
- **`pipefail` turned a channel that reads part of the message into a false
  "NOT told"** — and in the driver that is a `die`, so a working channel
  stopped the loop. Worse, whether `printf` fills the pipe buffer first is a
  race, so a channel could pass `--check` at startup and fail on the first real
  gate. The channel's own status is read now, and getting there took two wrong
  turns worth recording: `set -e` aborts before `PIPESTATUS` can be read, and
  `|| true` resets `PIPESTATUS` to `true`'s so `set -u` kills it instead.
- The header promised a channel re-check the code did not do; it is per
  iteration now, as claimed.

**A third round found seven more, and the first was the second round's fix
applied to only one of the two functions that needed it.** `first_ready()` was
rewritten to keep `bd`'s stderr out of the JSON buffer; `open_gate_ids()` — four
lines away, same shape — was left on `2>&1`, so one notice line on a *healthy*
tracker killed the driver with "refusing to continue without being able to read
the gates". At the post-worker call site that fires after a session has opened a
gate, so the run dies before the notification: the gate nobody sees, reached
through the code that exists to prevent it.

- **The per-iteration channel re-check, added in round two, was worse than the
  gap it filled.** It does not probe the channel, it *sends* through it —
  measured at 6 pages in five seconds with a short sleep, ~48 a day at the
  default, on the same channel the gate alert uses. That trains the operator to
  filter it, manufacturing the gate nobody sees rather than preventing it. The
  check is at startup only; a channel that breaks mid-run is caught by the gate
  send itself, which is a `die`, so at most one gate goes unseen and the loop
  stops there. Now one message per invocation, verified.
- **`item_still_in_progress()` collapsed "the tracker did not answer" into "the
  item is not in progress"**, so a failed `bd show` skipped the release and
  stranded the item forever — verbatim the failure its own docstring describes,
  by the same read-failure-as-an-answer conflation this file's header forbids
  everywhere else. Three outcomes now, and it releases on "cannot tell" too,
  because releasing an already-open item is harmless and not releasing a
  claimed one is not.
- **The spin guard asked whether *a* gate appeared, not whether *this item* was
  blocked.** A worker that creates a gate and fails the `bd dep add` gates
  nothing; the count still rose, the item was released unblocked, and the next
  round handed back the identical id with the gate notification making it look
  normal. It asks the question the loop will actually ask next.
- The worker prompt hardcoded the branch while the driver's is overridable, so
  a run elsewhere told the worker it was somewhere it was not — and its own
  "if you find yourself on another branch, stop" then fires against a correct
  run. `{{BRANCH}}` is substituted like `{{ITEM}}`.
- One test proved nothing: its stub failed both `bd` subcommands, so it passed
  on the *other* function's error message and would still pass with the check
  it was written for deleted.

**A fourth round found eight more, one of which was not mine.** A 26 MB
`results.tgz` — a backup of the gitignored `results/`, made on this host at
04:40 — had been swept into the index by a `git add -A`. Committed, that is 26
MB in history permanently, since a later `git rm` does not shrink the pack. It
is unstaged, the file is untouched, and `.gitignore` now covers
`results*.tgz`/`.tar.gz`/`.tar.zst` so the obvious way to back up a gitignored
directory cannot be committed by accident.

The seven in the driver, and two are the same conflation a third time:

- **A failed `release_item()` was a warning**, and it is the one failure path
  in the file whose consequence is permanent: the item stays `in_progress`,
  `bd ready` excludes it by stored status forever, `item_is_ready_again` then
  says false so nothing else stops the loop, and the driver reports "nothing
  ready" over work that has silently left the queue. It `die`s now, and prints
  the command to release it by hand.
- **`item_is_ready_again()` folded "the tracker did not answer" into "not ready
  again"** — the same read-failure-as-an-answer the header forbids, now caught
  in a third function. Folded that way, a failed read means the spin guard does
  not fire and `--once` exits **0**, reported as a completed item, for one
  released unblocked and unchanged.
- **Nothing checked the working tree between items.** The whole design here is
  that a rule a model can forget is enforced by the driver — gates are diffed
  by id for exactly that reason — while "commit your work" was left to the
  prompt. A worker that closes its item but leaves a hunk behind hands it to
  the next worker, who reviews and commits it under a different item with
  nothing recording that.
- **`bd list` defaults to 50**, so the gate set was a *window*, and new-gate
  detection survived only on bd's undocumented newest-first ordering. Past 50
  open gates under any other sort, a new one falls outside it and no
  notification is sent: the gate nobody sees, through the function written to
  prevent it. `--limit 0`.
- **A gate whose notification failed was unrecoverable**: on the next start the
  id diff already holds it, so under a systemd `Restart=` the driver comes
  back, works the remaining items, and that gate is never mentioned again. The
  ids are recorded to `.unattended-undelivered-gates` before dying and re-sent
  before the next loop.
- **`--dry-run` paged the operator**, on the alert channel, once per attempt —
  the same behaviour the per-iteration re-check was backed out for. A dry run
  raises no gates and now needs no channel. Verified: dry run 0 messages, real
  run 1.
- The notifier discarded the channel's stderr, so a bad topic or a TLS error
  reported `exit 6` and the command string, and the driver then refused to
  start with "fix it before running unattended" and nothing to fix it from.

**A fifth round found seven more, and the first was the release again — a
fourth round finding the same class.** `release_item` sat *after* the gate
block, so the two `die`s in between — the gate read failing, and the gate
*send* failing, which the header explicitly plans for — left the item claimed.
`bd ready` excludes `in_progress` by stored status, so when the operator
answered that very gate the item never came back. It is released immediately
after the worker returns now, before anything that can exit: the claim only
ever means "a worker is on this right now", so it ends when the worker does.

- **The worker was started with the driver's inherited cwd.** Every `bd` and
  `git` call here is `-C` because a systemd unit with no `WorkingDirectory`
  leaves cwd at `/` — and a worker started there resolves the project
  `CLAUDE.md`, the `.claude/` hooks (review-before-commit, the invariants
  guard) and its own `pytest tests/` against the wrong directory. The entire
  discipline the prompt consists of would silently not be in force, and nothing
  would report it.
- **The prompt hardcoded `/data/bgperf2`** while the driver derives `REPO_ROOT`
  from `BASH_SOURCE` — the identical defect to the hardcoded branch fixed one
  round earlier, so a run from a second checkout told the worker to commit in a
  different repository from the one the guards watch.
- **`comm` compares under `LC_COLLATE` and the ids are sorted in Python
  codepoint order.** Disagreeing, comm errors, and `|| true` turned that into
  "no new gates" — the gate nobody sees, for the third distinct reason. Fixed
  collation, and the status is checked.
- **The operator's channel command had no bound**, so the documented `curl`
  example against a black-holed host hangs the startup check with no output
  and, worse, hangs the post-worker gate send while a worker's changes sit
  uncommitted. The driver bounds its worker with `timeout -k` for exactly this
  reason.
- **`.unattended-undelivered-gates` was written to the repo root**, where the
  driver's own dirty-tree guard would blame the next worker for it and a
  `git add -A` could commit it — the accident the `results*.tgz` rules were
  added for, one round earlier. Both markers were *meant* to move under
  `.git/`; the sixth round found that only the read site had, so see below.
- **A deterministically failing item was released and immediately re-offered.**
  Under the systemd `Restart=` this file assumes twice, the restart claims the
  same item, it fails identically, and the loop runs hot with no notification
  and no record. Not hypothetical: it is the spend-limit failure recorded as
  `bgperf2-cqi`. Failures are counted, and the second one stops the loop and
  pages the operator.

**A sixth round found nine more, three of them high, and the first was a claim
in this document that was false.** "Both markers live under `.git/` now" — the
fix had been applied to the *read* site only. `resend_undelivered` read
`<git-dir>/unattended-undelivered-gates`; the write site still said
`$REPO_ROOT/.unattended-undelivered-gates`. Different directory, different
name. So the marker was never found on restart — the gate was owed forever and
the id diff could never re-report it — *and* it sat untracked in the worktree,
where the driver's own dirty-tree guard blamed every later item for it. Both
halves verified by running the driver against a channel that fails only on the
gate message.

- **`rev-parse --git-dir` returns a *relative* path** (`.git`), and this driver
  deliberately never cd's — so under the systemd unit its own header assumes,
  both markers resolved to `/.git/…`, where the append fails and the guard that
  reads them sees no file and returns clean. `--absolute-git-dir`.
- **The poisoned-item refusal died with the item still claimed**, so the item
  the operator was being asked to deal with was the one they could no longer
  see — and the notification told them to clear the record without mentioning
  releasing it.
- **The dirty-tree guard had no baseline.** It compared against absolute
  emptiness, so any pre-existing untracked file stopped the driver on the
  *next* item naming the wrong culprit — demonstrated with a stub worker that
  touched nothing, blamed for this branch's own staged changes. It diffs
  against the tree as it was before the worker now, and a tree that is already
  dirty is refused at startup, which is the only place it can be attributed
  honestly.
- **Only one of seven post-worker exits recorded the failure.** `note_failed_item`
  sat at the bottom, past six `die`s, so a worker that failed *and* tripped any
  of them wrote no record and the restart came straight back onto the same
  item — the loop the record exists to break.
- **The gate notification body was every open gate, truncated to 20 lines**,
  rather than the new ids the driver had just computed and discarded. Past
  twenty open gates — the steady state this design expects — the subject said
  "3 gate(s) opened" and the body showed none of them.
- The failure count was lifetime rather than consecutive and was never cleared
  on success; `BGPERF_NOTIFY_TIMEOUT` was the one numeric environment variable
  left unvalidated, so a `60s` typo was reported as a broken channel.
- **One test pinned two of these bugs in place.** It asserted the marker
  *definitions* only, so it locked in the relative-path form and never touched
  the write site at all — 46 tests passed over both. The tests that drive the
  loop past startup build their own clean checkout rather than depending on
  this one being clean. (The round-trip test this paragraph originally claimed
  was written did not exist; see the seventh round below.)

**A seventh round found eight more, three high — and one was this document
being wrong about its own tests for the second round running.** "It now writes
a marker and asserts the round trip" was false: the round trip had been checked
by hand in a shell, and the tests only grepped the script's source. The test now
exists, drives the driver through a failed gate send, and asserts the marker
lands under `.git`, holds the new id, leaves the worktree clean, and is re-sent
and cleared on the next start.

- **Releasing on "cannot tell" reopened work that was finished.** `bd update
  --status open` on a *closed* issue reopens it, so a transient `bd show`
  failure after a worker had committed and closed its item put that item back
  in the queue — and the spin guard then died saying the worker had left it
  unchanged, which was false. The release needs an observed `in_progress`; the
  stranded-claim case it was covering is handled by asking the tracker what is
  claimed instead of guessing.
- **A claim could outlive the driver two ways.** `bd ready --claim` mutates
  state *inside* bd and the parse after it can still fail, with no way to name
  the item; and there was no signal trap at all, on a loop whose own header
  assumes a systemd `Restart=` and whose host is a spot instance reclaimed
  without warning. There is a `TERM`/`INT` trap now, and a reconciliation that
  releases anything left `in_progress`.
- **`--dry-run` could write to the tracker and page the operator.** The
  poisoned-item refusal ran before the dry-run exit, and it both notifies and
  calls `release_item` — against a `--help` promising "claim nothing, start no
  worker". The test that was supposed to cover this passed vacuously, because
  its stub returned an empty queue so no item ever reached the refusal.
- The poisoned-item notification was the one send in the file allowed to fail
  silently (`|| true`), so an operator whose channel had broken was never told
  the loop had stopped; a malformed `BGPERF_NOTIFY_TIMEOUT` exited 78, which
  the driver renders as "no notification channel", telling the operator to
  configure one that was already working; and the environment numbers were
  validated *before* the arguments that override them, so `--sleep 1800` was
  refused for the value it was replacing and `--help` exited 1.

**An eighth round found six more, and the first means the loop could never
have completed an item at all.** `claude -p --permission-mode acceptEdits`
auto-approves Edit and Write only; a Bash call outside the project allowlist
still needs a permission decision, and in `-p` there is nobody to give one, so
it is denied. `.claude/settings.json` allows `pytest` and three read-only
`bgperf2.py` subcommands — **no `git`, no `bd`** — so every clause of the
prompt's definition of done (commit to the branch, close the item, open a gate
with `bd dep add`) was unreachable. The worker would edit, fail to commit, exit
0, and the tree check would then blame it and leave the tree dirty for every
subsequent start.

It had never been exercised: the one recorded run died on the spend limit
before reaching a worker session at all, which is exactly why this step's
criterion is a *run* and not a reading. The tools are named explicitly now, in
the driver, and that list is the security boundary — `git push` and `docker`
are absent deliberately and denied explicitly as well, because an omission is
undone by anyone widening the allow list later and a denial is not.

- **The signal trap reopened closed work.** `CURRENT_ITEM` stays set through
  the gate read, the gate send, the `comm` and the tree check — all *after* a
  successful worker has closed its item — so an unconditional release on
  `TERM` reopened a closed, committed item on precisely the signal the header
  calls most likely, the spot reclaim. It follows the same observed-
  `in_progress` rule the release site states and this did not.
- **Nothing reconciled stranded claims at startup.** A driver killed rather
  than signalled — a reclaim past its two-minute warning, an OOM kill, a stop
  that hit `TimeoutStopSec` behind a foreground worker — never runs the trap,
  and nothing else ever released that item.
- **The reconciliation released every `in_progress` item in the tracker**, not
  this driver's. An item a human had claimed interactively would be reopened
  and then handed to an unattended worker, two sessions on one piece of work.
  Scoped by assignee — though the ninth round found that scoping was itself
  wrong, so see below.
- **A worker that exits 0 without advancing its item was not recorded as a
  failure**, so the restart claimed the same item, ran a full session, and died
  again — indefinitely, with nothing in the record and no page. Only crashes
  were counted, and a model that declines the work is the likelier way there.
- **The poisoned-item refusal paged on every restart.** It notifies, releases
  and dies without recording that it announced, so under `Restart=always` that
  is a page every tenth of a second — worse than the ~48 a day the
  per-iteration check was backed out for, on the same channel.

**A ninth round found four more, and the first was the eighth round's fix
being a permanent no-op.** `bd` records an assignee as the *actor* — git
`user.name` — and the scoping filter used `user.email`, so
`release_stranded_items` matched nothing, always. Every path depending on it
silently did nothing: the startup recovery, the failed-claim reconcile, and the
"leaving it as it is and reconciling" branch. Measured against the real
tracker: `--assignee jpietsch@gmail.com` returns 0 rows, `--assignee "Justin
Pietsch"` returns 21.

And the obvious repair would not have been enough. The human's name does not
distinguish this driver's claims from that same person's interactive ones, so a
startup reconciliation would reopen an item they had in flight and hand it to
an unattended worker. The driver claims under `BEADS_ACTOR=bgperf2-unattended`
now — a distinct identity nothing else uses — and filters on that. Verified end
to end: a claim under that actor is found and released; the same query under a
git identity finds nothing.

- **`Bash(venv/bin/python -c *)` in the worker's allowlist defeated the two
  denials the list calls its boundary.** A prefix-matched `-c` auto-approves
  arbitrary code, so a worker could reach `git push` or `docker` through a
  one-liner and the deny rules would never see it — the tool input is the
  python, not what it runs. Nothing in the prompt asked for it.
- **`item_still_in_progress` returns the *pipeline's* status**, so an orphaned
  `venv/bin/python` — a failure this file's header names, and one CLAUDE.md
  says a distro upgrade causes — gives 127, which matched neither branch at the
  call site: no release, no reconcile, nothing printed, claim stranded. Only 1
  means "definitely not" now; everything else is the third outcome.
- **A stale `.announced` entry silenced the next real page.** Both die messages
  tell the operator to clear `$FAILED_ITEMS` and never mention the marker
  beside it, so an item that failed again after a clear was released and the
  loop died having told nobody.

**A tenth round found five more, and the first was the ninth round's fix being
dead code.** `[[ "$count" -lt 2 ]] && return 0` sat *above* the clear it was
meant to perform, so the clear was unreachable for every value that could reach
it — and the test written for it grepped the source for the call and its
position rather than running the function, so 76 tests passed over the
regression it was supposed to close. It now runs the function against a
temporary marker directory, and the mutation (putting the clear back below the
return) fails it.

- **The startup notification check pages once per process start**, and under
  the `Restart=always, RestartSec=100ms` this file assumes, every `die` becomes
  roughly ten pages a second carrying nothing about the failure — worse than
  both floods the header reasons about, and it sits *above* the announce-once
  suppression added in round eight, so it defeats it. The check is now
  rate-limited to once an hour, recorded under `.git`; a channel that breaks
  inside that window is still caught by the gate send, which is a `die`.
- **A worker that fails after editing wedges the driver permanently and
  silently.** The tree is left dirty, the startup guard then refuses *before*
  the loop is entered, so `refuse_a_repeatedly_failing_item` — which lives
  inside the loop — never runs, no second failure accumulates, and no
  failure-specific page is sent. That is the likeliest shape of a worker
  failure: a session that edits, then errors or hits the timeout. It pages once
  now, and clears the marker when the tree is clean again.
- **Nothing stopped two drivers running against one checkout.** The actor
  scoping added in round nine fixed the human-vs-driver case and created the
  driver-vs-driver one: a second driver's startup reconciliation reopens the
  first's in-flight item, claims it, and two sessions edit and commit the same
  item in the same worktree. An `flock` under `.git`, released on any death
  including SIGKILL.
- One test was vacuous in the way this suite is written against: its assertion
  did not depend on the loop variable, so it passed for any set of commands the
  prompt might name, including ones the allowlist does not cover.

**An eleventh round found six more, and the sharpest was round eight's defect
in a second form.** Bash permission rules are *prefix* matches, not globs —
every rule in this repository's own `.claude/settings.json` is a trailing `*`
and nothing else — so the `Bash(git -C * commit *)` entries added in round
eight matched nothing, and the worker, which `CLAUDE.md` and the prompt both
push toward `git -C`, could not commit at all. The same "no item can ever be
completed" as round eight, through the fix for round eight.

`Bash(git -C *)` is deliberately not the repair: it would match, and would also
permit `git -C <dir> push`, which no prefix rule can then deny. The `-C` form
is left out entirely, so it needs a decision nobody can give and is denied; the
worker uses plain `git`, which works because `run_worker` starts it in
`$REPO_ROOT` and which satisfies CLAUDE.md's rule — that rule prohibits `cd`,
not git in a directory one is already in.

- **The `.announced` clear still did not run when the record had been `rm`'d**,
  because the `-f` guard returned first — and "clear `$FAILED_ITEMS`", which
  both `die` messages say, reads as `rm`. Fourth round on this one marker. The
  test passed because its fixture wrote an *empty* file rather than omitting
  it.
- **The rate limit skipped the configuration check, not just the delivery
  probe**, so a hand-run `--once` from a shell with no `BGPERF_NOTIFY_CMD`
  export started, claimed an item and spent a whole worker session with no
  channel at all.
- **One `die` asserted a release that had almost certainly not happened.** The
  only way to reach it is `bd` being unhealthy, which is exactly when the
  reconcile's own read fails and returned silently — so the operator was told
  the claim was clean while it sat `in_progress`. It is now the two clauses
  `docs/invariants/batch-passes.md` requires, not one.
- The wedged-tree page was marked sent before it was sent and its failure
  swallowed — the only silent drop in a file where every other send dies or
  records a debt; and `BGPERF_NOTIFY_CHECK_INTERVAL` was the fourth unvalidated
  number, where `abc` silently switched the rate limit *off*.

Moving `CHECK_INTERVAL` into place then broke every invocation with an
unbound-variable death, and the tests caught it within a minute. That is worth
one line of its own: the tests that *run* the driver found in seconds what
eleven rounds of reading had to be told.

**Eleven rounds, 80 findings, on about 450 lines.** Three rounds running now have
found the *previous* round's fix to be wrong rather than incomplete: a
permission mode that made the definition of done unreachable, a scoping filter
that matched nothing, and a clear that could not execute. Each was caught only
because that round verified by measurement instead of by reading — and in two
of the three, a test had already been written that passed over the defect
because it grepped the source rather than running it.

That is the finding this step produced, and it is worth more than the driver:
**a test that reads the code cannot tell a fix from the appearance of one**, and
an unattended loop is exactly where the difference stops being visible. Anyone
adopting stage 2 should read the round-by-round record above as the cost
estimate, not the driver as a finished thing. Two rounds running found a
sentence in this document claiming a fix that had not landed where it said.
That is the same failure the file's own opening paragraphs are about, and the
reason it is recorded rather than quietly corrected: the durable account is
only worth having if being wrong in it is expensive. Step 1's note says review is
the expensive part and roughly a third of findings are in code an earlier round
added; here it is closer to half. Three separate rounds each found the *same*
conflation — a failed tracker read treated as an answer — in a different
function, and four rounds running found the claim outliving the worker by a
different route each time. The sixth round found a *documented* fix that had
only half landed, which is the same failure one level up: a note in this file
saying a thing was fixed is not the thing being fixed. That is worth carrying into stage 2 as a fact about the work rather
than about this change set: the rule a reviewer can state in one line is not
the same as the rule being applied everywhere it holds.

**Committed unreviewed-to-convergence, deliberately, and this is the reason.**
`CLAUDE.md` allows a commit over outstanding review "or say plainly why you are
committing anyway". Eleven rounds have each found something, three of them
finding the *previous* round's fix wrong; meanwhile the driver's central path —
a worker session completing an item — has never executed once, and cannot until
the spend limit resets. Round eight's defect was structural and only a run
would have surfaced it; round eleven's was the same defect again. Further
rounds refine code whose main behaviour is unverified, and each round's fix is
itself unverified. The first real run is worth more than the twelfth reading,
and the work is safer committed to a branch than sitting in a working tree.

**Read this driver as unverified.** It is on `unattended/measurement`, it is not
merged, and step 6 is not done.

**To finish this step:** answer `bgperf2-5p6`, then `export BGPERF_NOTIFY_CMD=…`
and run `scripts/unattended_driver.sh --once` once `bgperf2-cqi` is resolved.
The criterion is then read off that run.

### Step 7: survive a reclaimed host

The campaign host is intended to move to EC2 spot instances, which can be
reclaimed and terminated at any moment. This step makes a reclamation cost at
most the cell in flight: re-invoking the identical command resumes where it
stopped. Tracked as `bgperf2-82b`.

**Most of this already exists and must not be rebuilt.** `batch()` checkpoints
per cell to `<test>.progress.json`, `--resume` skips cells with durable
results, cell identity is stable across passes and across a changed execution
order, and `scripts/run_2026_suite.sh` already passes `--resume` and gates
suites on `COMPLETE` markers. **A cell is already the checkpoint unit**, which
is the granularity this needs. What is missing is everything between "the
process exited" and "the machine went away mid-write":

- **`atomic_write()` does not fsync the directory.** It fsyncs the temp file
  and then `os.replace()`s it, which orders the rename but does not make it
  durable: a hard termination can leave the directory entry pointing at the old
  file. That is one call, and it covers the four records that go through it --
  the progress file, the batch CSV, the batch summary, and the event artifacts.
- **`write_provenance()` does not go through it at all**, and this is the worse
  hole of the two. It writes `<prefix>.versions.json` with a plain
  `open(path, 'w')` and a `json.dump` (`bgperf2.py:2943`), as do the per-run
  PNGs. A kill landing inside that dump leaves a **truncated** file rather than
  the old-or-new an atomic writer guarantees, and provenance is the one record
  this repository says must never guess. An earlier draft of this step claimed
  every durable record went through `atomic_write()` and that the directory
  fsync was therefore "the only place the fix is needed" -- false, and false in
  the direction that would have let the exit criterion below pass over a
  half-written manifest. Corrected rather than deleted, because the appealing
  wrong answer here is to fix the writer you already know about.
- **Nothing handles SIGTERM.** A spot reclaim is SIGTERM, then SIGKILL about
  two minutes later. Nothing stops the controller threads, tears down
  containers, or declines to begin a cell it cannot finish. A batch that
  stopped at the nearest cell boundary would lose nothing at all.
- **The interruption notice is not polled.** The instance metadata endpoint
  publishes `/latest/meta-data/spot/instance-action` about two minutes ahead.
  Polling it turns "killed mid-cell" into "stopped between cells", which is
  the difference between losing a cell and losing nothing. It is also the only
  part of this that is EC2-specific, so it belongs behind a check that a
  non-EC2 host passes silently.
- **A hard kill leaves `atomic_write()`'s temp file behind.** Its cleanup is in
  a `finally`, which a `SIGKILL` never reaches, so a `<name>.tmp` survives
  beside the real document and nothing removes it on the next run. Harmless
  today -- nothing reads those files, and the next write truncates -- but it is
  the visible trace of an interrupted checkpoint, and the exit criterion below
  should account for it rather than let a resumed batch look clean while
  carrying one.
- **A hard kill mid-cell has never been tested.** `Container.run()` removes and
  recreates by name and `surplus_receiver_names()` covers the receivers a
  smaller run leaves behind, so the leftovers are *probably* handled -- but
  "probably" is what this whole document exists to remove, and the test is
  cheap: SIGKILL a batch mid-cell, re-invoke, and check for duplicate rows and
  orphaned containers.

**One part of it is not a code change and is Justin's**: results and the repo
live on the `/data` EBS volume, and a checkpoint on a volume that is deleted
with the instance is not a checkpoint. Whether that volume survives
termination, and detaches and reattaches to the replacement, has to be decided
and recorded before any of the above is worth having. Campaign artifacts
already depend on it -- `results/` is gitignored, so every row and every
evidence directory this campaign produces lives only there.

**That decision is a gate, not a note.** It is recorded on `bgperf2-82b` as an
acceptance criterion rather than left in this paragraph, because the
[Human Decisions](#human-decisions) rule in this document says a decision must
block the item and be surfaced out of band, and warns that a gate nobody sees
is worse than stopping. Without it a worker passes every test below, closes the
item green, and has built checkpointing onto a volume that dies with the host --
the exact failure the step exists to prevent, reached through the step itself.

**Exit criterion:** a batch killed with `SIGKILL` mid-cell, then re-invoked with
the identical command, resumes at the next incomplete cell with no duplicate
rows and no orphaned containers; a `SIGTERM` stops it at a cell boundary; the
progress file **and the versions manifest of a completed cell** survive a
simulated hard power-off; no stray `*.tmp` is left beside a durable document;
and the volume question above is answered and recorded.

**Done 2026-09-13, and measured rather than reasoned about.** `reclaim.py`
holds the pure part (the stop signal, the IMDS notice, the watcher);
`bgperf2.py` holds the transport, the SIGTERM handler, and the two places that
act on a stop. Every clause above was exercised against a real two-cell batch
on this host, not argued from the code:

| clause | how it was verified |
|---|---|
| SIGKILL mid-cell, then resume | killed during cell two; `--resume` skipped cell one, ran cell two, CSV carries two rows and no duplicate |
| no orphaned containers | three `bgperf_*` containers survived the kill; `bench()`'s existing entry sweep reclaimed them on the next run |
| SIGTERM stops at a cell boundary | exit **143**, the in-flight cell abandoned with no row recorded, only the completed cell in the progress file |
| the manifest survives | `versions.json` of the completed cell parsed clean after the kill |
| no stray `*.tmp` | two planted temp files swept and **named** on the next run |
| the volume question | answered by observation on 2026-09-10 and recorded on `bgperf2-82b` |

Three things are worth carrying forward, because they are not what the bullets
above predicted.

**A cell is abandoned, never finished.** Neither window -- the notice's ~120s
nor SIGTERM's ~120s -- finishes an MRT cell that runs for tens of minutes, so
nothing here tries. `abandon_run()` stops the samplers and *raises*, so
`completed[cell_id] = bench(a)` never executes and the cell cannot be recorded
as done. Stopping the samplers is the part that must not be skipped: they are
daemon threads polling `docker exec` once a second, and leaving them running is
how bgperf once manufactured the contention it reports.

**The `.block.lock` in the runner was never stale**, and the campaign record
saying it had to be cleared by hand is wrong in a way worth correcting. An
`flock` is released when its holder dies -- SIGKILL included -- and does not
survive a reboot, so a reclaim leaves an inert 0-byte file that the next block
locks normally. Measured. What *does* hold it is an orphan: every child
inherits fd 9, so a bgperf2 run that outlived its bench (`bgperf2-mzy`) keeps
the lock after the script that took it is gone. The runner now names the
holding pids and its command line, and says explicitly not to remove the file
-- removing it while a live holder is locked on it is how two blocks end up
running at once.

**The IMDS path was verified against the real endpoint on this host**, not
only against the injected transport: IMDSv2 token 200, `instance-action` 404,
parsed as "nothing scheduled". 404 is the answer for the whole life of an
instance nobody is reclaiming, which is why it is not an error and is never
logged.

**`/code-review` then found four things, two of which would have cost a
campaign block**, and they are recorded here rather than only in the diff
because each is a case the implementation had already reasoned about and got
backwards.

- **Only 404 means "nothing scheduled".** `parse_instance_action()` mapped
  *every* non-200 to `None`, so on an instance with IMDSv2 enforced -- where a
  token request that does not answer 200 leaves the action read
  unauthenticated, and IMDS answers **401** -- the watcher read a reclaimable
  host as quiet, counted no failures, never gave up and never fired. That is
  precisely the failure the module's own docstring says it exists to prevent,
  arrived at through the one status nobody thought about. Every status but 200
  and 404 now raises `MetadataUnavailable` and is counted as a failed read.
- **A stop at a cell boundary has to unwind the batch, not one loop.** The
  boundary check `break`ed, which leaves only the *cell* loop: `batch()` then
  finished that test, walked on to the next test in the config, and returned 0
  -- the exit status the 143 exists to distinguish from a host taken away, and
  the one `run_batch()` reads as success before stamping `RAN` over a truncated
  matrix. Sharper still, each remaining test re-enters a preamble that unlinks
  its progress and summary documents when the batch is not resuming, so a stop
  would have **discarded the previous results of tests it never ran**. It
  raises `StopRequested` now, and `tests/test_checkpoint_durability.py`'s
  `TestAStopUnwindsTheWholeBatch` fails if it goes back to a `break`.
- **The lock-holder report named the process asking.** The runner has already
  run `exec 9>"$LOCK_FILE"` by the time it calls `fuser`, so it listed its own
  pid and the command substitution's subshells beside any real holder -- under
  advice to kill anything there that is not a block you started. It now drops
  `$$`, `$BASHPID` and any pid with no `/proc` entry, and `fuser`'s exit 1
  gets a `|| true`, without which `set -euo pipefail` aborted before the
  message could print at all.
- **`abandon_run()` assumed a local target.** `bench()` binds `target` only in
  the non-remote branch, so a stop on a remote run raised `NameError` *before*
  `controller_stop.set()` -- skipping the sampler shutdown, which is the one
  thing abandoning a run may not skip. `target` is now bound to `None` ahead of
  the branch and the call guards on it.

Two smaller ones came with them. `install_stop_handlers()` and
`start_interruption_watch()` ran only from `batch()`, so a direct `bench` run
-- which `scripts/calibration_case.sh` drives -- installed no handler and the
boundary check was unreachable there; both calls are idempotent and now run
from `bench()` as well. And the watcher gave up after three *consecutive*
failed reads, which at a 5s interval is fifteen seconds: an IMDS blip on a real
EC2 host would have disabled reclaim detection for the rest of a batch,
silently. Giving up is now scoped to a host that has never answered at all,
which is the case the rule was written for.

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
