# CLAUDE.md

This file provides guidance to coding agents working in this repository. `AGENTS.md` is a **symlink
to this file**, so Codex and anything else that looks for that name reads exactly this — there is no
second, shorter copy to keep aligned.

It used to be a separate hand-written summary, and that failed the way a second copy of anything
fails: silently. By the time it was noticed it carried five absolute paths to a machine this
repository is not checked out on (including the `git -C <path>` rule, so an agent obeying it ran git
against a directory that does not exist), two duplicated Beads blocks from a `bd setup` that appends
rather than replaces, and no mention at all of the last seven change sets — every workload control,
repetitions, order control and `summary.py`. None of that looked wrong from inside the file. A
document that is confidently out of date is worse than no document, because it is followed.

So: **do not recreate a condensed agent file.** That rule is about a second *copy* — a summary
living beside the thing it summarises, free to drift in silence. It is not a rule against this file
having parts, and since 2026-09-12 it has three:

- **this file**, always loaded: the rules, the shape of the system, and an index naming every
  invariant there is;
- **`docs/invariants/*.md`**, which hold the argument for each of those invariants and the
  measurement that settled it. They were *moved* there, not duplicated; nothing was left behind but
  the index line, and a `PreToolUse` hook names the right document whenever the source it governs is
  about to be edited, so following it is not the model's to skip. **That last part holds for Claude
  Code only** — Codex reads this file through the `AGENTS.md` symlink but loads neither
  `.claude/skills/` nor the hook, so for it the index below and the skill files are ordinary
  documents it has to choose to open.
- **`.claude/skills/*`**, one per operator contract, loaded in full when its trigger phrase is said.

What made the old `AGENTS.md` dangerous was that it could go on looking right while saying something
different from the source. An index line cannot, because it names a document and a rule rather than
restating one, and `tests/test_docs_index.py` fails if a document is missing, unindexed, or no
longer governs anything. If this file is still too long for some harness, shorten *this* one — do
not fork it.


## rules

commit-message:
  max-length: 144
  format: conventional
  no-body: false

code-review:
  before-commit: required

**Run `/code-review` on the staged/working diff before every `git commit`**, and act on what it
finds before committing — fix it, or say plainly why you are committing anyway. Skip only for
commits that change no code at all (docs-only, or moving files without editing them).

This is not ceremony. There is no CI on this repo and the test suite deliberately cannot touch
Docker, so it covers the pure layers only — a real `bench` is the sole end-to-end check and nobody
runs one per commit. Review is the only thing standing between a bad edit and master.

git:
  never-cd: required

**Never `cd` into a directory to run git — use `git -C <dir> ...`.** It works from any cwd, leaves
the shell's working directory alone, and matches the permission rules already allowed here, so it
does not trigger a fresh approval prompt for every command. This applies to *any* repo, including
scratch clones outside the project. A `PreToolUse` hook in `.claude/settings.json` denies
`cd ... && git ...`, so the shortcut will simply fail rather than prompt.

## What this is

bgperf2 benchmarks BGP daemons by running them in Docker containers, blasting routes at them from
generator containers, and measuring how long they take to converge plus their CPU/memory cost. Forked
from osrg/bgperf with significant changes.

## Setup and commands

```bash
source venv/bin/activate          # or prefix commands with venv/bin/python
pip install -r pip-requirements.txt

./bgperf2.py doctor               # verify docker version + which bgperf/* images exist
./bgperf2.py images               # which daemon versions are built, and from which git ref
./bgperf2.py verify               # start each built image, check it reports its own version
./bgperf2.py verify -t frr_c      # just one daemon
./bgperf2.py prepare              # build all daemon images (slow; compiles from source)
./bgperf2.py prepare -t frr_c --versions 10.4,10.5   # just these, for one daemon
./bgperf2.py update <image> --version 10.7           # add one version image
./bgperf2.py dockerfile frr_c --version 8.0          # print a recipe without building it
./bgperf2.py bench -t bird -n 10 -p 1000    # one run: 10 peers x 1000 prefixes
./bgperf2.py bench -t frr_c --version 10.1  # a specific release
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
(stats row/header contract, convergence rules, host-contention detection, CLI-output parsers,
module imports). Importing
`bgperf2` works without a reachable daemon, which is what makes that possible; keep it that way.
There is no coverage of the container orchestration itself, so a real `bench` is still the only
end-to-end check. Use `-n1 -p1` for the fastest one.

`pytest.ini` narrows pytest's collection globs to `test_*` / `Test[A-Z]*`. Several production
names start with "test" — `measurements.TesterEventRecorder`, `measurements.TesterOffering`,
`measurements.tester_metrics`, `bird.tester_offering` — and the defaults (`test*`, `Test*`) try to
collect them as soon as a test module imports them. Keep new test functions on the `test_` prefix:
a pattern with no glob character is a *prefix* match in pytest, so widening this back out to
`test` would re-admit every `tester_*` name.

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
to a host directory bind-mounted into the container (`<--dir>/<bench-name>/<role>/`, so
`/var/tmp/bgperf2/<role>/` by default). Startup is
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
attribute), `write_config`, `get_startup_cmd`, `get_version_cmd`, and `get_neighbors_state`, and set
`IMAGE_REPO`. Then register it in two dicts at the top of `bgperf2.py` — `TARGET_CLASSES` (which
feeds the `-t` choices, `bench()`'s dispatch, and `remove_target_containers()`) and
`BUILDABLE_IMAGES`/`PREPARE_IMAGES` if it builds from source.

`build_image` should take `(force, tag, checkout, nocache, version)` and default `tag` to
`cls.image_tag()`, so `build_version()` can drive it.

### Versions

Multi-version testing lives in `Container` (`base.py`). Each daemon declares `IMAGE_REPO`,
optionally `VERSIONS` (what `prepare` builds), `DEFAULT_REF`, and overrides `resolve_ref()` to map a
user-facing version onto that project's ref naming — FRR `10.1` → `stable/10.1`, BIRD `2.19.2` →
`v2.19.2`. Images are `<IMAGE_REPO>:<sanitized version>`, or `:latest` when no version is given.

`img_exists()` is tag-aware. It used to compare only the repository half of `RepoTags[0]`, which is
why the old FRR builds faked version tags with path-like names (`bgperf/frr_c/stable_8`) — those
still work if passed explicitly as `image:`, but nothing builds them any more.

Different versions can need different *build instructions*, not just a different checkout, so the
inline Dockerfiles are format strings over `BUILD_VARS` (`{ubuntu_version}`, `{extra_setup}`,
`{configure_extra}`, `{ref}`), and `VERSION_BUILD_VARS` overrides those per version prefix. A
literal brace in one of those recipes has to be doubled. When a version needs a wholly different
recipe, `dockerfiles/<name>/<version>.dockerfile` replaces the inline one and receives `BGPERF_REF`
/ `BGPERF_VERSION` as docker build args.

`./bgperf2.py images` lists versions and their refs; `./bgperf2.py dockerfile <name> --version X`
renders a recipe without building it (`Container.render_dockerfile`, which short-circuits
`build_dockerfile` via `_RenderOnly`). `doctor` reports built vs not-built versions per daemon.

A bare `prepare` builds only the unversioned images; version lists are opt-in behind `-t`, since
`FRRoutingCompiled.VERSIONS` alone is four full compiles. It prints its plan and skips what exists.


### The invariants index

The documents under `docs/invariants/` hold the rules for the measurement and orchestration
layers. They were **moved** out of this file, not summarised away: the argument and the measurement
that settled each one are in the document, and a `PreToolUse` hook
(`.claude/hooks/invariants-guard.sh`) names the relevant file whenever one of the sources it
governs is about to be edited, so the pointer is not the model's to skip. Each line below exists so
you know a rule is there; none of them is the rule.

Each document states the sources it governs on its own `**Read this before editing:**` line, and
**that line is the mapping** — the guard reads it rather than carrying a copy, so a document that
starts governing another module says so in one place. The first version of the guard did carry its
own table, and review found it had already drifted from three documents and matched four modules
nowhere at all; `tests/test_docs_index.py` now runs the guard against every module every document
claims.

**`docs/invariants/workload-controls.md`** — `bgperf2.py` argument guards, `check_batch_test()`,
`bench_output_prefix()`; `base.py`'s `gen_conf()`/`gen_paths()`/`scenario_neighbors()`; `churn.py`;
`policy.py`; `bird.py`.

- Session count and table size are one axis. `--prefix-scope total`, `--path-diversity D`,
  `--receivers N`, `--churn-prefixes C`/`--churn-bursts B`, `--policy-reload-blocks N` and
  `--threads N` are the controls that separate them, and each is refused for a named list of things.
- **A rule that refuses something must be applied at every entry point, and there are four**:
  `bench`, `bench -f`, `config`, and `batch`, which synthesizes args and bypasses argparse *and*
  `bench`'s own guards. The peer-scaling change got this wrong seven times in review.
- A batch *test* key written under a *target* is refused; a batch target's defaults are **read**
  through `batch_target_field()` and never written into the target dict, because that dict is the
  cell identity. A default needs its own guard.
- Every dimension a batch iterates must reach `bench_output_prefix()`, or two cells overwrite each
  other's artifacts.
- No call that asks the world may run before the guards that read only the command line.

**`docs/invariants/batch-passes.md`** — `bgperf2.py`'s `expand_batch_cells()`/`batch_report_rows()`/
`create_batch_graphs()`, `summary.py`, `graphs.py`, `scripts/timing_variance_review.py`,
`scripts/check_repetition_configs.py`, `scripts/build_timing_report.py`.

- A repetition repeats the whole matrix, not each cell, and is part of a run's *name*, never a
  column beside it.
- A cell's cross-pass identity is its axes and its target, **never its ordinal** — a block that
  repeats part of an earlier matrix moves the survivors' ordinals while they stay the same cells.
  A pass that covers only part of a series says so, and the declaration is enforced both ways.
- A cell id says what the cell is, never when it ran; execution order is not report order.
- Nothing absent is published as a zero: a withheld statistic is `null` with its reason beside it,
  and an unsampled extreme is not an observation.
- **A pass that failed and a pass that has not run are never described by one clause**, at any level
  of aggregation. Collapsed three times.
- `summary.py` reads the stats row by column name and must not import `bgperf2`.
- The report computes no statistic; every claim cites figures resolved against the review before it
  is written, matched exactly, and `testers (s)` is neither published nor cited.

**`docs/invariants/target-state.md`** — `frr.py`, `bird.py`, `gobgp.py`, `base.py`'s
`sample_target_state()`, `measurements.py`'s `target_table_section()`/`delivery_metrics()`,
`scripts/check_timing_evidence.py`.

- **Never read a BIRD stats table positionally.** BIRD 3 inserts columns, which made every BIRD 3
  target report `accepted` 0 for every neighbour, silently.
- FRR's End-of-RIB log read must stay incremental and key its restart reset on **inode**: a 1 GB
  `bgpd.log` cost 4.14s per 1s poll and the run never finished.
- One CLI read per poll serves the neighbour counters and the table witness both — two reads are
  two execs and, worse, two instants.
- A daemon with no gauge reports `None`, never 0. FRR withholds `best_paths` deliberately.
- `monitor_required_reached` is the monitor's count against the check-point; a second rule for it
  was built, verified and backed out. `delivery_metrics()` is the sound version and carries ten
  named refusals; `check_events()` accepts it in place of that event only for an MRT generator,
  only for that one event, and only when it resolved.

**`docs/invariants/tester-offering.md`** — `measurements.py`'s `TesterOffering`,
`TesterEventRecorder`, `tester_metrics()`, `tester_fleet_metrics()`; `Tester.offering_stats()`;
`tester.py`; `mrt_tester.py`; `bird.py`; `bgpdump2.py`; `exabgp.py`.

- **Both poll loops stamp the sample before the read**, and the published resolution is the gap the
  loop achieved, not the one it asked for.
- `post_injection_tail_s` is signed and nothing clamps it.
- A span nothing crossed is not a rate of zero.
- One `docker exec` per poll, not one per peer; every configured peer appears in every poll, with
  `offered=None` where the read failed.
- A BIRD 2.19 offered count is queue-side; bgpdump2's prefix counts are encode-side and its octet
  count wire-side. Any generator logging to a redirected stdout needs `stdbuf -oL`.
  `--tester-trace-io` inflates the walk time it measures by 56%.
- Both tester-health scans go through `scan_log_lines()` and **stop at the last complete line**;
  the generator is still writing, and a truncated `Invalid route` reads as a protocol error.

**`docs/invariants/export-timing.md`** — `monitor.py`'s `Receiver`, `measurements.py`'s
`ExportEventRecorder`, and `bgperf2.py`'s `controller_export_stats()`/`finish_bench()`.

- A receiver is not a route source and not a second monitor; `Receiver.stats()` is refused.
- One serialised round for the whole fan-out, never a thread per receiver, and **every** round waits
  at least as long as it took.
- This is the one sampler that does not go through the run's queue.
- Export timing and a post-convergence workload are not measured in the same run; a run asking for
  both keeps the fan-out and withholds the timing by name.
- What still cannot be separated is table selection, and that is said out loud rather than folded
  into an interval that quietly contains it.

**`docs/invariants/findings.md`** — `findings.py`, the only thing allowed to name a limiting
component, and `bgperf2.py`'s `write_event_artifact()`, which catches for it.

- `inconclusive` (the deciding measurement was never made) and `unresolved` (it was made and
  something forbids attributing it) are different refusals and must not be collapsed.
- Half the offered table must cross the measured interval before that interval may be read as the
  generator's send — or the generator must have timed its own send.
- A confounder withholds the verdict, not the evidence.

**`docs/invariants/host-and-environment.md`** — `contention.py`, the controller threads, and the
`-d` warnings.

- **Measure CPU as a delta between two `/proc` samples, never `ps -eo pcpu`**, which fails in both
  directions.
- **Never allowlist interpreters**; exclude bgperf2's own tree by pid, exclude kernel threads, and
  charge a first-seen process rather than skipping it. Each of those three made the feature report
  a clean machine while it was busy.
- Every daemon a target can run must be in `BGPERF_PROCESSES`, or that target's own load is
  published as contention.
- The names travel with the number, and only ever together.
- The controller threads are governed by the `controller_stop` Event and must actually stop — they
  once did not, and bgperf was manufacturing the contention it reports.
- The bench directory must not be in RAM, and must not be on the root filesystem.

**`docs/invariants/provenance-and-verify.md`** — `Container.version_string()`,
`collect_provenance()`, `verify`, and every module carrying a version command (`rustybgp.py` and
`openbgp.py` included — both had the bug this document is about).

- `version_string()` is the only thing to call for a version; it never guesses, and its parsers
  match a banner rather than taking a fixed word.
- A version command belongs on the **daemon base class**, not the `*Target` subclass, or the monitor
  and testers cannot answer.
- `verify` probes through `TARGET_CLASSES` **and** `TESTER_CLASSES`, never the daemon base class,
  and a green result over zero checks must exit non-zero.
- The three provenance columns stay last in the stats row.

**`docs/invariants/convergence.md`** — `convergence.py`'s `ConvergenceTracker`, and the `bench()`
loop that feeds it.

- Five rules hold it up and each was broken once: stability is tracked on **every** sample;
  regression is measured against the **high-water mark**, not the previous sample; a count more
  than `DROP_FRACTION` below its peak is never reported CONVERGED however steady it looks; and the
  target's own table witness excuses a monitor decline the target does not share — but a monitor
  count of zero never attests, and a run the witness alone is keeping alive still ends.
- The target's per-neighbour counters **shorten** the assurance window; they are not what makes
  convergence possible. Either checkpoint opens the gate, neither does not, and a run decided on one
  witness says so.


## Targets and images

Open-source daemons are built from source into `bgperf/<name>` images by `prepare`/`update`.

FRR is only ever `frr_c` — compiled from a git checkout, with `prepare` building master plus the
releases in `FRRoutingCompiled.VERSIONS`.

**If your `bgperf/frr_c:*` images predate 2026-08-08, rebuild them: `prepare -f -t frr_c`.** They
were compiled with `--enable-gcov`, which links gcov coverage instrumentation into `bgpd` itself, so
those images benchmark an instrumented binary against everyone else's optimized one. Measured on FRR
10.7.0, same source, 4 peers × 25k prefixes: **103% CPU instrumented vs 45% clean**, and ~12% more
memory. Convergence time was unchanged at that size — the run is not CPU-bound there — so the
distortion sits in the CPU and memory columns, which is exactly where it is hardest to notice.
`prepare` skips any tag that already exists, so nothing invalidates these automatically; a batch
mixing a freshly built version with a cached one silently compares the two kinds of binary.

**If your `bgperf/exabgp*` or `bgperf/bgpdump2` images predate 2026-09-02, rebuild them:
`prepare -f -t exabgp -t exabgp_mrtparse -t bgpdump2`.** Their recipes changed — the exabgp pair moved
off archived Debian buster onto bookworm, and bgpdump2 gained the `autoreconf` its link needs — and
`prepare` skips a tag that already exists, so a cached image keeps the old base image with nothing
looking wrong. ExaBGP still implements no version command, so for the exabgp pair the `tester
version` column records `UNKNOWN` either way and the manifest cannot tell the two builds apart —
same trap as the gcov one above.

**bgpdump2 does report itself**, and reports the commit it was compiled from: `2.0.14 (a019184)`.
The version half alone would not be identity — upstream has said `Version: 2.0.14` for every master
commit this project has built, so two images made months apart are indistinguishable by it, which
is the gcov trap one layer up. The commit is read at probe time from the clone the image still
carries at `/root/bgpdump2` (`Bgpdump2.VERSION_CLONE`), deliberately rather than baked into the
recipe at build time: `prepare` skips an existing tag, so anything added to the Dockerfile is
missing from every image already built, whereas reading the clone identifies the images you have
now. An image whose clone was pruned reports `2.0.14 (commit unknown)` — said out loud, because
`2.0.14` on its own looks pinned and is not. `Bgpdump2.DAEMON_BINARY` is set too, so `verify` runs
the gcov check on the generator: an instrumented blaster sends more slowly than a clean one, and
the run would publish that as the target's convergence time.

That rebuild left the exabgp pair **unpinned at both layers**, which is a known open issue rather
than a settled decision. `FROM python:3-bookworm` floats to whatever Python major is current
(buster was frozen at 3.9 once it was archived), and `pip_spec('')` installs plain `exabgp`, so two
`prepare -t exabgp` runs months apart produce testers on a different interpreter *and* a different
ExaBGP release. With no version command, provenance records `UNKNOWN` for both and nothing can tell
them apart — the gcov trap again, one layer up. Pinning `python:3.11-bookworm` and a concrete
`exabgp==` would close it, at the cost of rebuilding those images.

**Both traps above are the same shape — `prepare` skips a tag that already exists, so a recipe
change is invisible until someone remembers to force a rebuild — and `prepare`/`doctor`/`images` now
catch it going forward** rather than needing a date memorised by hand; see
`docs/invariants/provenance-and-verify.md`'s "Recipe drift" section for the mechanism and its
reasoning. One consequence worth stating here: every image built before that mechanism shipped —
including every image the two paragraphs above describe — reports as unverifiable rather than as
current, so an untouched pre-existing image is *not* a clean bill of health from it; only a rebuild,
or the date/measurement checks above, settle those.

The old `frr` target (a wrapper over the prebuilt `frrouting/frr:v7.5.1` image) was removed. **`frr.py` still exists and must stay**: its
`FRRoutingTarget` holds all the FRR config generation, `get_neighbors_state`, and End-of-RIB parsing,
which `FRRoutingCompiledTarget` inherits. Only the image build and CLI target went away.

OpenBGPD is the one open-source target that is **repackaged rather than compiled**: the image is
`FROM openbgpd/openbgpd:<tag>`, so a "version" is an upstream Docker tag (7.3 through 9.2 exist) and
the inherited passthrough `resolve_ref()` is already correct. Two consequences that do not apply to
the compiled daemons:

- The upstream image starts the daemon itself — its entrypoint is `multirun bgpd bgplgd haproxy` on
  the image's own `/etc/bgpd.conf`. bgperf's `start.sh` then died with `cannot bind to
  0.0.0.0:179: Address in use`, the target never peered, and the run hung in "Waiting N seconds for
  monitor" forever. The recipe sets `ENTRYPOINT []` so the container idles like every other image
  and `exec_startup_cmd()` is what starts bgpd, on the config under test.
- `PULL_BASE = True`, because here the base image *is* the daemon. Docker does not re-pull a `FROM`
  it already has, so a locally cached `openbgpd/openbgpd:latest` kept `bgperf/openbgp:latest` at 8.8
  long after 9.2 shipped — a run recording a version nobody asked for, with nothing looking wrong.
  It is off for everyone else, where the base image is only a toolchain.

  Read it through `Container.pulls_base(tag)`, never the flag directly. It applies to the
  **unversioned tag only**: `FROM openbgpd/openbgpd:9.2` is immutable so a pull can find nothing
  new, and `pull` is *fatal* when the registry is unreachable even though the image is already
  local — which would turn an offline `prepare -t openbgp` into a failure it never used to be.
  `prepare` also rebuilds such a tag unconditionally, since "already built" says nothing about
  whether it is current, and passes `force` to match — `build_dockerfile()` skips an existing tag
  otherwise, so it would be planned and then quietly not built.

Note that `batch()` assigns `args.target` straight from the yaml, so it bypasses argparse's `choices`
validation — `tests/test_static.py` checks the benchmark configs instead.

Commercial NOSes (Junos cRPD, Arista cEOS, SR Linux) are never built. Download them out of band and
tag them as `crpd:latest` / `ceos:latest` — or as `crpd:<version>` to select them with `--version`
like any other daemon. These write root-owned files into the bench directory (`/var/tmp/bgperf2` by
default), which bgperf2 then cannot clean up; `sudo rm -rf /var/tmp/bgperf2` when that happens. Their licenses prohibit publishing results.


## Conventions

### Operator contracts

Four contracts are each triggered by an exact user phrase — which is precisely what a skill
description is — so each one is a skill under `.claude/skills/` and is loaded **in full** on
invocation. Nothing about them has been condensed and the plan documents they drive are unchanged:

| the user says | skill | drives |
|---|---|---|
| `continue the 2026 benchmark campaign` | `2026-benchmark-campaign` | run ID `2026-baseline`, `results/2026`, `/data/bgperf-work` |
| `continue the bgperf2 measurement implementation plan` | `measurement-implementation` | `docs/bgperf2-measurement-implementation-plan.md` and its decision log |
| `continue the 64 GB timing validation campaign` | `timing-validation-campaign` | `docs/2026-64gb-timing-validation-plan.md`, `scripts/run_timing_validation_block.sh` |
| `continue the unattended execution plan` | `unattended-execution` | `docs/unattended-execution-plan.md` |

All four have one shape: inspect durable state first, never run two things concurrently, complete
exactly one reviewable unit, then stop and tell the user to use the same prompt again.

**The campaign host is a class, not a machine**, and that is cross-cutting enough to state here: 16
vCPU / 61.44 GiB AMD EPYC 9R14 (`m7a.4xlarge`), an EC2 spot instance reclaimed without warning, of
which only `/data` survives a reclaim — which is why the work directory is `/data/bgperf-work` and
not `/var/tmp`. Rows measured on it may never be read against
`benchmarks/baseline/baseline-benchmark.csv`, which was produced on a different CPU. The
timing-validation skill carries the full rule.

### Code conventions

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


<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:6cd5cc61 -->
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
   git push
   git status
   ```
5. **Hand off** - Summarize changes, validation, issue status, and any blocked sync/commit/push step

**Critical rules:**
- Explicit user or orchestrator instructions override this Beads block.
- Do not commit or push without clear authority from the active profile or the current user request.
- If a required sync or push is blocked, stop and report the exact command and error.
<!-- END BEADS INTEGRATION -->

### Beads is task tracking, and nothing else

The managed block above was written by `bd init` (beads v1.2.2) and is rewritten by `bd`
whenever it drifts, so nothing in it is worth editing. **This section governs the block and
everything else beads says**, including the `bd prime` text the `SessionStart` hook injects
into every session — which restates the same instructions far more forcefully ("🚨 SESSION
CLOSE PROTOCOL 🚨", "**Prohibited**: Do NOT use TodoWrite, TaskCreate, or markdown files for
task tracking") and arrives ahead of anything a session reads. That injection is not an
exception to the rules below; it is the main thing they are about. Beads is scoped to issue
tracking, and where it reaches past that, this file wins — which the block itself says. Three
of its instructions meet rules stated elsewhere here, and `bd init` changed three things about
this repository that no one asked it to. The resolutions:

- **`bd remember` does not replace the plan documents.** The block offers it for persistent
  knowledge. The reasoning in `docs/*.md` and in this file is the most valuable content in
  this repository, and the first trap in the unattended execution plan is exactly this: once
  an item body starts accumulating reasoning there are two sources of truth and neither is
  complete. An item links to a document anchor; it does not summarize it.
- **Commit discipline is unchanged** — `/code-review` before every code commit, and
  unattended work commits to its own branch, never master. The block describes a
  "team-maintainer" profile that closes beads and pushes at session close; that profile is
  opt-in and this repository does not opt in. Note `bd config show` reports
  `beads.role = maintainer`, inferred from the git remote — that is beads' write-routing role,
  **not** the team-maintainer profile, and it is not an opt-in to anything.
- **The ban on "markdown files for task tracking" does not reach the plan documents.** All
  four operator contracts here are driven by `docs/*.md`, and every one of them requires the
  worker to record progress in a plan document -- or, for the measurement plan, in its decision
  log -- as part of being done. A driver that took the
  injection literally would stop writing the record its own contract is defined by. Items in
  beads link to a document anchor; the document stays the durable account. The bans on
  `TodoWrite` and `MEMORY.md` are narrower still: a per-turn todo list is execution state
  within one turn, and the harness's own memory directory lives outside this repo and is not
  beads' to govern.
- **`bd` decides nothing about git.** `bd init` committed its own setup to the current branch
  without review, and it repointed `core.hooksPath` at `.beads/hooks`, so `.git/hooks/` is
  now inert and five hooks there run `bd`. Nothing lived in `.git/hooks/` when that happened,
  so nothing broke — but a repo git hook added later has to go in `.beads/hooks/` to run at
  all. Two hazards come with that: those hooks are **tracked files**, so checking out a branch
  changes what runs on your next commit, and `master` has no `.beads/`, so checking it out
  leaves `core.hooksPath` naming a directory that does not exist and every hook silently stops.
  Also, any `bd` failure there — a held Dolt lock, a stopped server — fails the whole
  `git commit`, the driver's included; that is loud rather than silent, so it is left alone.
  The review hook now matches `bd init|setup|migrate|dolt|hooks` as well as `git commit`,
  because a `bd` command that touches git is otherwise a commit no one reviewed. It also
  matches `git -C <dir> commit`, which it never did before — see the plan's step 2.
- **`bd init` pointed `sync.remote` at `origin` — the shared public upstream — and it has been
  unset.** `bd dolt push` writes issue state to `refs/dolt/data` on that remote, which is both
  outside the review discipline and outside this repository's branch rule. One worker on one
  host needs no cross-machine sync; `.beads/config.yaml` records why.
- **`.claude/settings.json` is now tool-managed, and `bd setup` is not idempotent against it.**
  `bd` rewrites it whole on drift — reordering keys and re-escaping `&`, `<` and `>` — so a real
  hook edit arrives inside a whole-file diff; read it for the hook bodies, not the line count.
  Worse, `bd setup claude` does not revert an edited hook, it **appends a second unguarded copy
  beside it**, so both run while the edited one still looks right. Re-review that file after any
  `bd setup`, and do not run one casually. It now also registers
  `.claude/hooks/invariants-guard.sh`, which is what points an editor at the invariant document
  governing the file they are changing; `tests/test_docs_index.py` fails if that registration is
  ever dropped, because a guard that silently stops firing is the failure this whole split is
  arranged against.
