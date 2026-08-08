# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.


## rules

commit-message:
  max-length: 144
  format: conventional
  no-body: false

## What this is

bgperf2 benchmarks BGP daemons by running them in Docker containers, blasting routes at them from
generator containers, and measuring how long they take to converge plus their CPU/memory cost. Forked
from osrg/bgperf with significant changes.

## Setup and commands

```bash
source venv/bin/activate          # or prefix commands with venv/bin/python
pip install -r pip-requirements.txt

./bgperf2.py doctor               # verify docker version + which bgperf/* images exist
./bgperf2.py prepare              # build all daemon images (slow; compiles from source)
./bgperf2.py update <image>       # force-rebuild one image, e.g. update bird -c <git-ref>
./bgperf2.py bench -t bird -n 10 -p 1000    # one run: 10 peers x 1000 prefixes
./bgperf2.py batch -c bench.yaml  # matrix of runs -> CSV + PNG graphs
./bgperf2.py config -o out.yml    # emit scenario.yaml without running
```

Requires Docker (user must be in the `docker` group), and `sysstat` for `mpstat` — `bench` shells out
to `mpstat` and `free`, and will crash without them.

```bash
venv/bin/pip install -r test-requirements.txt
venv/bin/python -m pytest tests/ -q        # ~0.5s, no Docker needed
venv/bin/python -m pytest tests/test_convergence.py -q
```

The test suite deliberately needs **no Docker daemon and no privileges** — it covers the pure layers
(stats row/header contract, convergence rules, CLI-output parsers, module imports). Importing
`bgperf2` works without a reachable daemon, which is what makes that possible; keep it that way.
There is no coverage of the container orchestration itself, so a real `bench` is still the only
end-to-end check. Use `-n1 -p1` for the fastest one.

The venv is tied to a specific interpreter — a distro Python upgrade orphans it. Recreate with
`rm -rf venv && python3 -m venv venv && venv/bin/pip install -r pip-requirements.txt`.

## Architecture

### The three roles

Every `bench` run creates containers on a dedicated Docker bridge network (`<bench-name>-br`):

- **target** — the daemon under test. One per run.
- **monitor** — always a GoBGP instance peered with the target. It is the *measurement instrument*:
  `bench` polls `gobgp neighbor -j` once a second and reads `afi_safis[0].state.accepted` to see how
  many routes the target has re-advertised. This is what "recved" means in the output.
- **testers** — one or more route generators peered with the target. BIRD (default) or ExaBGP for
  synthetic prefixes; GoBGP, ExaBGP-mrtparse, or bgpdump2 for MRT file playback.

Routes flow tester → target → monitor. Timing is measured at the monitor, so it captures full
propagation, not just reception.

### Config generation flow

`gen_conf()` builds a `scenario.yaml` describing AS numbers, addresses, router IDs, per-neighbor
prefix lists, and monitor `check-points`. It is **Mako-templated** — `gen_mako_macro()` injects a
`gen_paths(n)` helper so the file stays small for large prefix counts. `bench` renders it with Mako,
then parses it as YAML. `-f` passes a hand-written scenario instead.

Each container class then translates that scenario into its own native config format and writes it
to a host directory bind-mounted into the container (`/tmp/<bench-name>/<role>/`). Startup is
uniform: `exec_startup_cmd()` writes a `start.sh` into that directory and execs it inside the
container. To debug a target that won't come up, run its `start.sh` by hand and read the output:

```bash
docker exec bgperf_bird_target /root/config/start.sh
```

### Class hierarchy

`base.py` defines `Container` → `Target` and `Tester`. Each daemon module contributes a *base* class
(holding `GUEST_DIR`, the `dockerfile` string, and a `build_image` classmethod with a default
`bgperf/<name>` tag) plus a *target* class that mixes it with `Target`:

```
class BIRDTarget(BIRD, Target)          # bird.py
class FRRoutingCompiledTarget(FRRoutingCompiled, FRRoutingTarget)
class RustyBGPTarget(RustyBGP, GoBGPTarget)   # reuses GoBGP's config writer
```

MRO order matters — the daemon base comes first so its `GUEST_DIR`/`dockerfile` win. Testers use the
same trick (`class Bgpdump2Tester(Tester, Bgpdump2, MRTTester)`).

**To add a daemon target**, implement: `build_image` (the Dockerfile lives inline as a class
attribute), `write_config`, `get_startup_cmd`, `get_version_cmd`, and `get_neighbors_state`. Then
register it in three places in `bgperf2.py` — the `-t` choices list, the `if/elif` chain in `bench()`,
and `remove_target_containers()` — plus `prepare()`/`update()` if it builds from source.

### get_neighbors_state — the per-daemon wart

`bench` needs to know how many prefixes each neighbor has sent, and every daemon reports this
differently. There is no common API, so each target parses its own CLI:

- FRR: `vtysh -c 'sh ip bgp summary json'`, JSON
- BIRD: `birdc 'show protocols all'` parsed with a **TextFSM template** (`bird.tfsm`)
- Junos/EOS/SR Linux: vendor JSON via their own CLIs

FRR is a special case worth knowing about: it has no received-prefix counter, so
`FRRoutingTarget.get_neighbor_received_routes()` overrides the base method and greps `bgpd.log` for
`End-of-RIB` messages instead.

### Termination detection

Lives in `convergence.py` as `ConvergenceTracker`, deliberately separated from `bench()`'s container
plumbing so the rules are testable without Docker (`tests/test_convergence.py`).

The naive check ("stop when received == expected") only works for synthetic prefix generation. With
MRT playback the total unique prefix count is unknown (peers' tables overlap), and with filtering
enabled the accepted count is deliberately lower than what was sent. So the tracker instead waits for
the count to go *stable*: `ASSURANCE_SAMPLES` (20) without change, or 5 if the configured checkpoint
was already hit. Those trailing samples are subtracted from the reported elapsed time afterward.

It also detects failure: a count that stops moving for `STUCK_SAMPLES` (600), a drop of >1% sustained
over 10 samples, or nothing arriving at all within 15s. `bench()` feeds it one sample per monitor
poll via `update()` and acts on the returned status; `note_neighbors_checkpoint()` is called from the
target branch when every neighbor has finished sending.

## Targets and images

Open-source daemons are built from source into `bgperf/<name>` images by `prepare`/`update`.
`frr_c` is FRR compiled from a git checkout (`prepare` builds `stable/8.0` and `stable/9.0` variants
under separate tags); the `frr` target is a thin wrapper over the prebuilt upstream
`frrouting/frr:v7.5.1` image. Note that `batch()` assigns `args.target` straight from the yaml, so it
bypasses argparse's `choices` validation — `tests/test_static.py` checks the benchmark configs
instead.

Commercial NOSes (Junos cRPD, Arista cEOS, SR Linux) are never built. Download them out of band and
tag them exactly as `crpd:latest` / `ceos:latest` — bgperf2 looks up those literal tags and fails
confusingly otherwise. These write root-owned files into `/tmp/bgperf2`, which bgperf2 then cannot
clean up; `sudo rm -rf /tmp/bgperf2` when that happens. Their licenses prohibit publishing results.

## Conventions

- Container names are fixed strings (`bgperf_<name>_target`, `bgperf_monitor`) declared as
  `CONTAINER_NAME` class attributes; testers use a `CONTAINER_NAME_PREFIX` plus an index.
- Policy/filter fragments live in `filters/*.conf` and are read verbatim at config-write time.
  `nos_templates/*.j2` are Jinja2 templates for the commercial NOSes (rendered via
  `Target.get_template`). Note the two template engines coexist: Mako for scenarios, Jinja2 for NOS
  configs.
- Stats flow through a single `queue.Queue` fed by daemon threads (one per container plus two for
  host-level CPU/memory). Consumers dispatch on the `who` key.
- `batch()` runs `bench()` in-process by synthesizing an `argparse.Namespace` per cell of the matrix,
  so any new `bench` argument must also be added to the field lists in `batch()` or it will be
  missing at runtime.
- Graph column indices in `create_batch_graphs()` are positional into the stats row built by
  `create_output_stats()`, and `stats_header()` names those columns by position too. All three must
  agree; `tests/test_stats_contract.py` enforces it. They drifted once already, silently shifting
  every batch CSV by one column.
- Resource files are resolved from `REPO_ROOT` (defined in `base.py`), not the working directory, so
  bgperf2 can run from anywhere. Generated output goes to `--results-dir` (default `results/`).
