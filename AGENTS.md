# AGENTS.md

This file provides guidance to Codex and other coding agents when working with code in this repository.

## What This Repo Is

`bgperf2` benchmarks BGP daemons by running them in Docker containers, injecting routes from generator
containers, and measuring convergence time plus CPU and memory cost. It is a heavily modified fork of
`osrg/bgperf`.

The repository already has Claude-oriented guidance in [`CLAUDE.md`](/home/jpietsch/code/bgperf2/CLAUDE.md).
This file is the Codex-facing equivalent. Keep the two aligned rather than creating competing workflows.

## Working Rules

- Run a review on staged or working diffs before any `git commit`, and fix findings or state plainly why you
  are committing anyway. There is no CI here, and the unit tests deliberately do not cover Docker orchestration,
  so review is a required quality gate.
- Prefer `git -C /home/jpietsch/code/bgperf2 ...` if you need to run git outside the repo root. Do not rely on
  `cd ... && git ...` patterns in automation.
- Do not break the property that importing `bgperf2` and running the unit tests needs no Docker daemon and no
  elevated privileges.
- Treat real `bench` runs as expensive integration checks. Use unit tests for pure logic; use the smallest
  realistic benchmark only when a change actually touches runtime orchestration or daemon interaction.

## Setup

```bash
python3 -m venv venv
venv/bin/pip install -r pip-requirements.txt
venv/bin/pip install -r test-requirements.txt
```

Useful commands:

```bash
./bgperf2.py doctor
./bgperf2.py images
./bgperf2.py verify
./bgperf2.py verify -t frr_c
./bgperf2.py prepare
./bgperf2.py prepare -t frr_c --versions 10.4,10.5
./bgperf2.py update <image> --version 10.7
./bgperf2.py dockerfile frr_c --version 8.0
./bgperf2.py bench -t bird -n 10 -p 1000
./bgperf2.py bench -t frr_c --version 10.1
./bgperf2.py batch -c bench.yaml
./bgperf2.py config -o out.yml
venv/bin/python -m pytest tests/ -q
venv/bin/python -m pytest tests/test_convergence.py -q
```

Requirements outside Python:

- Docker, with the user in the `docker` group
- `sysstat`, because `bench` shells out to `mpstat`
- A disk-backed working directory for heavy runs; `-d /var/tmp` is safer than a tmpfs-backed `/tmp`

## Architecture Notes

### Roles in a benchmark

Every `bench` run creates:

- `target`: the daemon under test
- `monitor`: a GoBGP instance that measures accepted routes from the target
- `testers`: one or more route generators

Traffic flow is tester -> target -> monitor. The monitor is the measurement point.

### Config flow

`gen_conf()` builds `scenario.yaml` with Mako templating. Each container class translates that into its own native
config and writes host-side files under the benchmark directory. Startup is normalized through `start.sh`.

### Class model

`base.py` defines the shared `Container`, `Target`, and `Tester` abstractions. Daemon modules typically provide:

- a base class with `GUEST_DIR`, `dockerfile`, and `build_image`
- a target class mixing that base with `Target`

MRO matters. The daemon base class must come first so its class attributes win.

When adding a daemon target, implement:

- `build_image`
- `write_config`
- `get_startup_cmd`
- `get_version_cmd`
- `get_neighbors_state`

Then register it in the dicts near the top of `bgperf2.py`, including build-related registries if it is buildable.

### Versions

Version-aware behavior lives in `Container` in `base.py`. Daemons may define `IMAGE_REPO`, `VERSIONS`,
`DEFAULT_REF`, and `resolve_ref()`. Images are version-tag aware, and build recipes may vary by version through
`BUILD_VARS`, `VERSION_BUILD_VARS`, or `dockerfiles/<name>/<version>.dockerfile`.

Batch configs can expand `versions: [...]` into one run per version. Preserve the custom YAML loading behavior
that avoids turning values like `10.10` into `10.1`.

A test may also declare `repetitions: N`, which repeats the whole matrix N times rather than each cell N times.
Every pass gets its own run name (`bird 2.19.2 #2`), because every artifact a run writes is named from
`bench_output_prefix()` -- a shared name means the second pass replaces the first one's evidence. That stem must
carry every dimension a batch iterates, `filter_test` included. Cell ids carry the cell's position within one
pass and which pass it is, never its position in the execution order, and a single-pass test says "no
repetition" in both the name and the id so the two cannot disagree under `--resume`.

### Neighbor-state parsing

Each daemon reports neighbor state differently. `bench` depends on target-specific parsing in
`get_neighbors_state()`. FRR is a special case: it infers received routes from `End-of-RIB` log lines, so log
parsing must stay incremental and memory-conscious.

## Testing Expectations

- Prefer unit tests for pure logic in modules such as `contention.py` and `convergence.py`.
- If you change daemon orchestration, config generation, monitor/tester startup, or Docker image handling, say
  clearly whether you did or did not run a real benchmark or verification command.
- Use the smallest practical end-to-end run when needed, for example `./bgperf2.py bench -n1 -p1 ...`.

## Benchmark Integrity Constraints

- Host contention matters. If you add a new target daemon, update `BGPERF_PROCESSES` so the benchmark does not
  classify its own load as foreign CPU contention.
- The legacy `testers (s)` field is `elapsed (s)` minus time to the first monitor-visible prefix. It does not
  record tester completion, so its proximity to elapsed time cannot establish that a run was injection-bound.
- Tester completion is recorded separately, in each run's `.events.json` `testers` section, by polling the
  generator's own counters. A BIRD 2.19 offered count is queue-side: the count and the completion fact are
  sound, the injection duration and rate are not. Read `offered_rate_pps` only beside `offered_in_interval`,
  and do not derive a tester-limited verdict from a BIRD 2.19 rate.
- `post_injection_tail_s` is the interval from the last generator finishing to the monitor reaching the
  required count — the second half of an injection-bound verdict, and signed on purpose. A negative value
  means the monitor reached the check-point while a generator was still finishing, which is ordinary and must
  not be clamped to zero. Both ends come from 1s poll loops, so a magnitude at or under
  `post_injection_tail_resolution_s` says the two events shared a look, not that the tail was short.
- Where a generator measures its own send, that measurement is published as `reported_injection_s` beside the
  polled `injection_s`, not folded into it — a different clock and the generator's own definition of sending.
  For a bgpdump2 walk that finishes in a millisecond it is the only account of the interval there is. Its
  wire-side companion is `octets_on_wire`; `offered_prefixes` is counted at the encoder.
- A run's verdict about what limited it lives in the `findings` section of its `.events.json`, derived by
  `findings.py`. It refuses to attribute far more often than it attributes, and the two refusals differ:
  `inconclusive` means the deciding measurement was never made, `unresolved` means it was made and a
  confounder (busy or shared host, low free memory, blocked writes, a queue-side completion) forbids
  attributing it. A withheld verdict still publishes the evidence it withheld. Do not add a finding that
  names a component from a single extremum or from two similar durations.
- The project is effectively IPv4-only today. Changes that appear to add IPv6 support need updates in prefix
  generation, peering, monitor accounting, and MRT playback behavior.

## 2026 Benchmark Campaign Operator Contract

When the user says `continue the 2026 benchmark campaign`, use these fixed defaults unless durable run metadata
already records different values:

- run ID: `2026-baseline`
- results root: `results/2026`
- work directory: `/var/tmp/bgperf`

Then:

1. Inspect `COMPLETE` markers, progress JSON, CSV rows, logs, and any active benchmark process.
2. Never run benchmark suites concurrently.
3. If a suite is active, monitor it. If it was interrupted, resume it with the same run ID.
4. Otherwise run exactly one suite with `scripts/run_2026_suite.sh next --run-id 2026-baseline --workdir /var/tmp/bgperf`.
5. Review the completed suite for failed rows, tester errors/timeouts, foreign CPU contention, low free memory, and
   timing evidence before accepting it. The legacy `testers (s)` field is elapsed minus time to the first
   monitor-visible prefix; do not use its proximity to elapsed time as an injection-bound verdict.
6. Stop after that suite is complete and reviewed. Tell the user to use the exact same prompt next time.

Do prerequisite work needed by the selected suite, such as building a missing image or preparing the pinned MRT,
but do not advance into a second suite in the same continuation.

## Measurement Implementation Operator Contract

When the user says `continue the bgperf2 measurement implementation plan`, follow
[`docs/bgperf2-measurement-implementation-plan.md`](/home/jpietsch/code/bgperf2/docs/bgperf2-measurement-implementation-plan.md):

1. Inspect the working tree, recent commits, tests, plan exit criteria, and any durable phase notes.
2. Resume unfinished work before selecting new work.
3. Implement exactly one smallest reviewable change set from the first incomplete phase.
4. Run proportionate tests and any Docker verification explicitly required by that phase.
5. Review the complete diff and fix findings before accepting the change set.
6. Stop after that change set and tell the user to use the exact same prompt next time.

Do not start the follow-up benchmark campaign until the implementation plan's release gate passes.

## 64 GB Timing Validation Campaign Operator Contract

When the user says `continue the 64 GB timing validation campaign`, follow
[`docs/2026-64gb-timing-validation-plan.md`](/home/jpietsch/code/bgperf2/docs/2026-64gb-timing-validation-plan.md)
with these fixed defaults:

- run ID: `2026-timing-validation`
- results root: `results/2026`
- work directory: `/var/tmp/bgperf`
- hardware ceiling: the local 64 GB host; never schedule a larger-memory workload

Then:

1. Verify the measurement implementation release gate. If it is incomplete, run no benchmark and direct the user
   to `continue the bgperf2 measurement implementation plan`.
2. Inspect manifests, `COMPLETE` markers, progress data, rows, logs, and active benchmark processes.
3. Never run benchmark suites or cells concurrently.
4. Monitor or resume an active block with the same run ID, schema, seed, and repetition identity; otherwise run
   exactly one next block.
5. Review correctness, tester timing evidence, provenance, contention, memory, and timing decomposition.
6. Stop at the reviewed block boundary and tell the user to use the exact same prompt next time.

## Repo Hygiene

- Large generated results belong in `results/`, which is already gitignored.
- Avoid committing machine-local agent files such as `.claude/settings.local.json` unless the user explicitly asks.
- Keep documentation changes synchronized when operational guidance changes, especially between this file and
  [`CLAUDE.md`](/home/jpietsch/code/bgperf2/CLAUDE.md).

<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:970c3bf2 -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/SYNC_CONCEPTS.md for details and anti-patterns.

## Agent Context Profiles

The managed Beads block is task-tracking guidance, not permission to override repository, user, or orchestrator instructions.

- **Conservative (default)**: Use `bd` for task tracking. Do not run git commits, git pushes, or Dolt remote sync unless explicitly asked. At handoff, report changed files, validation, and suggested next commands.
- **Minimal**: Keep tool instruction files as pointers to `bd prime`; use the same conservative git policy unless active instructions say otherwise.
- **Team-maintainer**: Only when the repository explicitly opts in, agents may close beads, run quality gates, commit, and push as part of session close. A current "do not commit" or "do not push" instruction still wins.

## Session Completion

This protocol applies when ending a Beads implementation workflow. It is subordinate to explicit user, repository, and orchestrator instructions.

1. **File issues for remaining work** - Create beads for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **Handle git/sync by active profile**:
   ```bash
   # Conservative/minimal/default: report status and proposed commands; wait for approval.
   git status

   # Team-maintainer opt-in only, unless current instructions forbid it:
   git pull --rebase
   bd dolt push
   git push
   git status
   ```
5. **Hand off** - Summarize changes, validation, issue status, and any blocked sync/commit/push step

**Critical rules:**
- Explicit user or orchestrator instructions override this Beads block.
- Do not commit or push without clear authority from the active profile or the current user request.
- If a required sync or push is blocked, stop and report the exact command and error.
<!-- END BEADS INTEGRATION -->

<!-- BEGIN BEADS CODEX SETUP: generated by bd setup codex -->
## Beads Issue Tracker

Use Beads (`bd`) for durable task tracking in repositories that include it. Use the `beads` skill at `.agents/skills/beads/SKILL.md` (project install) or `~/.agents/skills/beads/SKILL.md` (global install) for Beads workflow guidance, then use the `bd` CLI for issue operations.

### Quick Reference

```bash
bd ready                # Find available work
bd show <id>            # View issue details
bd update <id> --claim  # Claim work
bd close <id>           # Complete work
bd prime                # Refresh Beads context
```

### Rules

- Use `bd` for all task tracking; do not create markdown TODO lists.
- Run `bd prime` when Beads context is missing or stale. Codex 0.129.0+ can load Beads context automatically through native hooks; use `/hooks` to inspect or toggle them.
- Keep persistent project memory in Beads via `bd remember`; do not create ad hoc memory files.

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/SYNC_CONCEPTS.md for details and anti-patterns.
<!-- END BEADS CODEX SETUP -->

## The beads blocks above are task tracking, and nothing else

They were written by `bd init` and are rewritten by `bd` on drift, so nothing in them is worth
editing. The same goes for the `bd prime` text injected at session start, which says the same
things much more forcefully. Where any of it reaches past issue tracking — offering
`bd remember` as the home for persistent knowledge, banning `TodoWrite`, `MEMORY.md` and
"markdown files for task tracking", or describing a session close that runs `bd dolt push` and
`git push` — it is answered under **"Beads is task tracking, and nothing else"** at the end of
[`CLAUDE.md`](CLAUDE.md), which is authoritative for this repository and applies to every
agent, not just Claude. Read it before acting on any of them. The markdown ban is the one that
matters most here: this repository's operator contracts are driven by the plan documents under
`docs/`, and recording progress in them is part of being done.

In particular: this repository pushes nothing automatically. `sync.remote` is unset and
`no-push` is true, because `bd init` had aimed sync at the shared public upstream.
