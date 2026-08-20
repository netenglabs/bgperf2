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
- `testers (s)` versus `elapsed (s)` matters when interpreting results. If they are close, the run is
  injection-bound rather than target-bound.
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
   injection-bound results before accepting it.
6. Stop after that suite is complete and reviewed. Tell the user to use the exact same prompt next time.

Do prerequisite work needed by the selected suite, such as building a missing image or preparing the pinned MRT,
but do not advance into a second suite in the same continuation.

## Repo Hygiene

- Large generated results belong in `results/`, which is already gitignored.
- Avoid committing machine-local agent files such as `.claude/settings.local.json` unless the user explicitly asks.
- Keep documentation changes synchronized when operational guidance changes, especially between this file and
  [`CLAUDE.md`](/home/jpietsch/code/bgperf2/CLAUDE.md).
