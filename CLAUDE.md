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

So: do not recreate a condensed agent file. If this one is too long for some harness, shorten *this*
one.


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

### Peer scaling

`gen_conf()` gives each neighbour its own `gen_paths(p)` off one shared iterator, so peers get
*disjoint* prefixes and the table is `n * p`. **Session count and table size are therefore one
axis**, and every synthetic matrix in `benchmarks/` sweeps both at once: `2026-core-synth.yaml`'s
`neighbors: [10, 50]` x `prefixes: [50_000, 100_000]` holds 500k, 1M, 2.5M and 5M routes, so
nothing downstream can separate "50 sessions were slower" from "five times the routes were slower".

`--prefix-scope total` (batch: `prefix_scope: total` on a test) reads `-p` as the whole table and
splits it across the peers instead. `benchmarks/2026-peer-scaling.yaml` is the shape it exists for.

- **It is normalised to a per-peer count before anything reads it** -- in `bench()` beside the
  image resolution, and in `expand_batch_cells()` for a batch. `-n 50 -p 100000 --prefix-scope
  total` and `-n 50 -p 2000` are the *same workload* and must produce the same scenario (verified
  byte-identical), the same cell identity, the same row and the same bar. Everything downstream is
  keyed on the per-peer number: the CSV column is literally `prefixes per peer`,
  `bench_output_prefix()` names artifacts from `prefix_num`, and `create_graph()` groups by it. A
  scope surviving into those would be a fourth dimension in all three. The batch sets
  `a.prefix_scope = 'per-peer'` on the synthesized args for that reason -- passing the test's scope
  through as well would divide twice.
- **The division must be exact, and an inexact one is refused before the first container.** A
  remainder means the peers do not all offer the same table, so `prefixes per peer` is true of none
  of them, each neighbour's `check-points` differs, and the monitor's stops being `n * p`.
  `check_batch_test()` checks every (neighbors, prefixes) combination, not just the first: 1,050,000
  divides by 10 and 25 but not by 9, and finding that out at cell three is hours lost. The message
  names peer counts and prefix counts that would work.
- **It is refused for the MRT testers, on the batch path as well as the CLI.** `gen_conf()` sets
  the monitor check-point straight from `-p` for `gobgp` and `bgpdump2`, so it is already the whole
  table. Refusing it only on the CLI let a batch divide a 1.05M-prefix MRT table by its peer count
  and report CONVERGED at a tenth of it, silently -- `check_batch_test()` therefore reads the
  tester from the test's targets, and one MRT target refuses the whole test, since `prefixes` is a
  single axis shared by every target.

**A rule that refuses something must be applied at every entry point, and there are four:**
`bench`, `bench -f`, `config`, and `batch` (which synthesizes args and so bypasses argparse *and*
`bench`'s own guards for anything it pins). The peer-scaling change got this wrong seven times in
review, each time refusing on one path while another accepted it silently -- three of them in
guards added by an earlier round of the same review, because a guard is code and gets the rule as
wrong as the code it guards. Note `gen_conf()` routes on `tester_type not in ('exa', 'bird')`, so
anything unrecognised is an MRT injector: a batch target's `tester_type` is validated against
`TESTER_TYPES` (the CLI's own `choices`) because a batch target bypasses argparse. A default for a batch
target belongs in `BATCH_FIELD_DEFAULTS` and must be **read** through `batch_target_field()`, never
written into the target dict: that dict is part of the cell identity, so filling a default into it
renames every completed cell of every in-flight batch. **A default needs its own guard**, because it
can replace a loud failure with a quiet wrong answer -- defaulting `tester_type` to `bird` turned a
target that named `mrt_file` and no generator from an immediate `invalid mrt_injector: None` into a
synthetic run that never read the MRT file, converged, and published a row. **A `file:` target
takes no defaults at all** (`batch_target_defaults()`): its generator is inert, but `tester_type`
still reaches `write_provenance()` and `bench_output_prefix()`, so a default there writes
`"tester_type": "bird"` into the manifest of a run that played back MRT. Provenance never guesses. `batch` is the path that
matters: a CLI mistake costs one run, a batch mistake costs a matrix, and nobody is watching it.

A test key written under a *target* is refused (`BATCH_TEST_ONLY_KEYS`). There is no allowlist of
target keys -- `batch()` reads a fixed field list and ignores the rest -- and every knob an operator
sets is a target key, so a test key one level too deep is the natural slip and fails silently:
`prefix_scope: total` under a target runs that target at `neighbors x prefixes`, converges, and
writes rows that read as a peer sweep.

`--path-diversity D` (batch: `path_diversity: D`, a *test* key) is the other half of
that separation: it deals the peers into groups of `D` and gives each group one shared prefix
block, so the fleet offers `n * p` paths for `(n / D) * p` distinct prefixes and the target
actually has to select a best path. Without it every route the target learns is the only path it
holds for that prefix, so a run measures reception and re-advertisement and publishes it as
convergence -- and best-path selection is one of the three things BIRD 3's worker threads exist to
parallelise.

- **The monitor's check-point counts distinct prefixes, not offered paths** (`groups * p`), since
  the monitor reads what the target *re-advertises* and that is one best path per prefix.
  `path_diversity_groups()` is the only place that arithmetic lives, because the block a neighbour
  is given in `gen_conf()` and the check-point are far apart and must agree: too high never
  converges, too low reports CONVERGED on a fraction of the table. Per-neighbour `count` stays `p`
  -- a peer still offers `p` and the target still accepts all of them, since BGP holds the losers.
- **The default renders the scenario it always did.** `gen_paths()` takes an optional `block` and
  the caller omits it at diversity 1 (verified byte-identical); the cell id omits the key at the
  default too, so an in-flight batch from an older build still resumes.
- **The block is keyed on the count of configured neighbours, not the loop index**, which skips the
  target's and monitor's addresses.
- **Refused, at all four entry points, for**: an MRT generator (no paths are synthesised there),
  `-f`/a scenario target (the file states its own paths), a diversity above the peer count, and an
  inexact division -- the remainder group would announce a block with fewer competing paths than
  the rest. `check_batch_test()` checks every peer count on the axis, not the first.
- **`--prefix-scope total` and `--path-diversity` are refused together**, deliberately: "the whole
  table" then has two readings differing by exactly `D` (paths offered vs. distinct prefixes held),
  and the reading would decide the `prefixes per peer` column, the cell identity and every artifact
  name. Choosing one is its own change set.
- **It is in the artifact stem (`pd<D>`) and in `run.path_diversity`, not in the CSV.** Nothing
  else in `bench_output_prefix()` carries it -- a disjoint run and a competing one have the same
  peer and per-peer prefix counts -- so two tests differing only in it would overwrite each other's
  artifacts, which is the `filter_test` failure. A `-f` run records `null`: provenance never
  guesses about a workload bgperf2 did not build. **Both `run` blocks carry it** --
  `write_provenance()` and `write_event_artifact()` -- because the events artifact is what
  `findings.py` reads, and stating `peers` and `prefixes_per_peer` alone describes a table five
  times the one the target held, uncorrectably. Same rule as `repetition`.
- **A refusal names the fault, not the nearest rule it trips.** The scope cross-check tests against
  `PREFIX_SCOPES`, so a typo'd `prefix_scope: totl` beside a diversity gets `unknown prefix scope`
  from the function that owns that diagnosis, rather than being blamed on the combination -- which
  sends the operator to remove the diversity and meet the same typo again.

`--receivers N` (batch: `receivers: N`, a *test* key) is export fan-out: N sessions the
target advertises its whole table to and which announce nothing back. Without it a run has exactly
one export session -- the monitor -- so what a table costs to *send* and what it costs to *receive*
have been one number in every result this tool has produced, and decoupled exports are the third
thing BIRD 3's worker threads exist to parallelise.

- **A receiver is not a route source.** It is a top-level `receivers` key in the scenario, never an
  entry in `conf['testers']`: `get_test_counts()` reads the testers, so a receiver is never waited
  on for a table it will never send, and the monitor's check-point and the whole ingress side do
  not move with the receiver count. Verified: 2 peers x 10 prefixes gives `required` 19 and
  `received` 20 with 0 receivers and with 3.
- **It is not a second monitor.** The monitor is the single instrument every published timing is
  read from; a second one polled into the same queue would be an unlabelled second `recved` series.
  `Receiver(Monitor)` inherits the gobgpd config, the startup script and the establishment wait, and
  **refuses `stats()`** so that cannot happen by accident. It *is* read --
  `accepted_prefixes()`, see the export timing section below -- but into a recorder and an
  artifact section of its own, never into the queue the row is built from.
- **`Target.scenario_neighbors()` (base.py) is the one place that knows a target has three kinds of
  session.** Eight target modules built `flatten(testers) + [monitor]` independently, and a receiver
  added to seven of them is a target quietly exporting to fewer sessions than the run claims.
  `sort=False` for `frr.py` and `gobgp.py`, which never sorted -- ordering in a generated config is
  cosmetic and changing it puts an unrelated diff in front of anyone comparing against an older run.
  `tests/test_export_fanout.py` asserts no module still builds that list by hand.
- **Receivers are established before any generator launches**, since a session that came up mid-run
  would take a partial table and put the export work at a moment nothing recorded. Their wait is
  *not* folded into `monitor (s)`: that column is the instrument coming up, and a `--receivers 20`
  run would otherwise read as a slow monitor in every row.
- **They are removed like testers** (`bgperf_receiver<i>`), because `batch()` reuses the process per
  cell and a leftover fails the next cell on a duplicate name.
- **Their addresses continue the peers' own index**, so neither the address nor the AS number
  (`1000 + i`) can collide whatever the peer count -- a separate region would be safe only until
  someone ran enough peers to reach it.
- Unlike `--path-diversity` and `--prefix-scope`, it is refused for **nothing** except a bad count
  and `-f`/a scenario target: a receiver is a target-side session, so an MRT run has the same reason
  to want fan-out as a synthetic one. Stem gets `rx<N>`, both `run` blocks record it, `-f` records
  `null`.
- **A receiver follows the monitor's lifecycle, not the testers'.** `--repeat` reuses the *tester*
  containers and has never reused the monitor: `Container.run()` removes and recreates anything it
  finds by name, and the target is rebuilt under `-r` too, so every receiver session has to re-peer
  regardless. Receivers are therefore built and established on **every** run. Skipping them under
  `-r` -- the first version -- meant the count the target was configured for, the count in the
  artifact name and the count in both manifests were three claims about sessions that did not
  exist, and the establishment wait that keeps the export work from landing mid-run went with them.
  `surplus_receiver_names()` covers the one case recreating by name does not: a run asking for fewer
  than the last built leaves the rest up, `--repeat` skips `remove_old_containers()`, and a
  dynamic-neighbour target's `neighbor range 10.0.0.0/8` accepts every one of them.
- **No call that asks the world may run before the guards that read only the command line.**
  `bench()`'s argument guards are covered by a suite that deliberately needs no Docker daemon, so a
  Docker call ahead of them makes that suite depend on machine state -- it went green or red
  according to whether a verification run had left receiver containers up. `target_image()` was
  doing the same thing and older: a mistyped `-p` was answered by `ImageNotBuilt` on a host with no
  daemon or no built image rather than by the typo. Image resolution now sits after every pure guard
  and still above the teardown, which is the invariant
  `test_image_resolves_before_containers_are_torn_down` was always about.
- **The fan-out is in `min free mem (GB)`, and that column feeds a confounder.** Each receiver holds
  its own copy of the table on the same host, and a low value becomes `findings.py`'s
  `low_free_memory`, which withholds `limiting_component` -- so a run can be told its intervals
  include page pressure caused by memory it consumed on purpose. `describe_export_fanout_cost()`
  says so before the run and deliberately **does not estimate the size**, for the reason
  `LOG_SPACE_FLOOR_GB` is not an estimate: what a GoBGP holds per route depends on the paths, and an
  invented number gets quoted back as though it had been measured.
- **A `-f` scenario's own `receivers` key is validated where the file is parsed**
  (`scenario_receivers()`). `resolve_receivers()` guards every path that *builds* a scenario; this
  guards the one path that is handed one, so `receivers: 3` written into a scenario file is refused
  by name instead of reaching `enumerate()` as a bare `TypeError`.

`--churn-prefixes C` and `--churn-bursts B` (batch: `churn_prefixes` / `churn_bursts`, *test* keys)
are the fourth workload control: once the run has converged, the last `C` prefixes of every peer's
own list are withdrawn and re-announced, `B` times. Every run this tool has published measures a
table arriving at a daemon that has never seen it, and a router spends almost none of its life
doing that -- it spends it holding a table while parts of it move, which is removing routes from a
loaded table, re-running best-path selection for every prefix that had a competing path, and
withdrawing and re-advertising on every export session.

- **A burst is switched, not reconfigured.** The block goes into a `protocol static churn` of its
  own in each peer's generator config and a burst is `birdc -s <sock> disable churn` / `enable
  churn`, one `docker exec` for the whole fleet. A `configure` would re-read the whole file --
  several hundred thousand static routes on a real run -- so the interval measured would be BIRD
  parsing its own config rather than the target reacting to a withdrawal. Verified on
  `bgperf/bird:2.19.2` and `:3.3.2`: both answer exactly `churn: disabled` / `churn: enabled`, and
  `churn: already disabled` for a protocol in that state, which is **not** success -- the sequence
  alternates, so reaching a `disable` on an already-disabled protocol means the previous `enable`
  was lost.
- **The block is the tail of each peer's own list.** A sampled block would need a seed, and a seed
  is a fourth dimension in the cell identity, the stem and the manifest -- what `--prefix-scope`
  and `--path-diversity` both refuse to become. Taking the tail also keeps the block *shared* under
  `--path-diversity`: peers in a group are handed the same list, so they churn the same prefixes
  and the target loses the prefix rather than falling back to a surviving path. That is why the
  monitor-visible count is `groups * C` and not `n * C`; `churn_operation_counts()` publishes both,
  because reporting only the second understates a diversity-5 fleet's work fivefold.
- **The two halves of a burst are timed separately.** Dropping routes and re-selecting/re-exporting
  them are different mechanisms and the second is one of the three BIRD 3 parallelises, so one
  end-to-end number would hide what the workload exists to expose. `burst_s` *is* their sum -- the
  withdrawal's end and the re-announcement's start are one event -- and is published so a reader
  need not add two rounded numbers, never as a third measurement.
- **An interval of one poll is an upper bound, not a duration.** Both halves are bounded below by
  one poll by construction -- the command is issued just after a sample and the soonest it can be
  seen is the next. The printed line says `within the 1.0s poll resolution` for that case, on the
  same rule `print_tester_metrics()` applies to a sub-poll injection, reached from the other side.
- **A burst nobody performed is caught when it is issued.** `churn_failures()` checks every
  session's reply against the sessions asked about (not against the sections that came back), so a
  lost withdrawal is named immediately instead of arriving `CHURN_STALL_SAMPLES` later as a stall
  that reads as a stuck target.
- **A collapsed count is not a withdrawal.** Completion is `accepted <= converged - groups * C`,
  and a post-convergence sample of 0 -- a session that flapped, a target that restarted -- satisfies
  that for every block there is. Read as a withdrawal it would stamp the burst complete, issue the
  re-announcement against a table that never lost the block, and publish the session re-learning the
  whole table as `reannounce_s`. A count more than `CHURN_COLLAPSE_FRACTION` of the converged count
  below the floor fails the sequence by name instead, in either phase and between bursts --
  `ConvergenceTracker`'s `DROP_FRACTION` rule on the other side of convergence. The message names
  the phase, and distinguishes a collapse before the first burst from one between bursts, for the
  reason the stall message names its phase: the three send the reader to different logs.
- **A run that asked for churn and issued none still says so**, and that fallback lives in
  `write_event_artifact()` rather than at the `FAILED` branch that needs it. That branch is inside
  `bench()`'s monitor loop, which no Docker-free test can drive, so a fix written there passed the
  whole suite when review deleted it again. Anything that builds a run's document gets the
  fallback; a caller that supplies real evidence always wins.
- **`MSG` is rewritten through `row_message()`** -- commas to `;`, whitespace folded -- because a
  churn failure quotes birdc's own reply and `syntax error, unexpected CF_SYM_UNDEFINED, expecting
  CF_SYM_KNOWN` is two extra CSV fields, shifting `filters`, `max foreign cpu %` and all three
  provenance columns. Same rule as `Container.version_string()`. **`name` and `filters` are still
  unguarded**, which is pre-existing: a comma in a batch `label` shifts the row the same way, and
  the fix there is a guard in `check_batch_run_names()` rather than a rewrite, since a label also
  names every artifact the run writes.
- **The withdrawal target is exact, and a target that never held part of the block stalls rather
  than being tolerated.** Completion is `accepted <= converged - groups * C`, so a target holding
  fewer prefixes than the fleet offered -- the reason the monitor check-point carries a 0.99 factor
  in the first place -- can leave that count unreachable if any of the missing prefixes fall in the
  tail. The stall message names the count it held and the count it wanted, which is diagnosable; a
  tolerance would have to be a number nobody measured, and it would let a burst that only half
  landed be published as complete.
- **The published row describes the delivery, not the churn.** `elapsed (s)` is settled before the
  first burst, and the churn loop drains every other producer's queue messages without acting on
  them, so `max cpu %`, `max mem (GB)` and `min free mem (GB)` do not move with a burst's peak.
  `total time` *does* include churn, since it is wall clock. What a burst cost is in
  `<prefix>.events.json`'s `churn` section, per burst.
- **A sequence that did not complete leaves the run converged and says so in `MSG`.** The
  convergence measurement is real and marking the row FAILED would corrupt `elapsed (s)`, which is
  computed on the CONVERGED path; but a batch of churn cells whose rows all read as ordinary would
  say nothing about the second workload. `summary.py` reads `MSG` only for a row marked failed, so
  no summary changes.
- **Refused, at all four entry points, for**: any generator but synthetic `bird` (the handle is
  BIRD's own `birdc`), `-f`/a scenario target, `-r/--repeat` (which builds no tester objects at
  all, so nothing would issue the burst and nothing rewrites the generator config the churn
  protocol lives in -- the `--receivers` shape one round earlier), a block larger than the per-peer
  count *after* `--prefix-scope total` has divided, a burst count with no block, and
  `--filter_test` (a policy that drops part of the block makes the burst's completion count
  unreachable, so a correctly filtered run would be published as a stalled one -- a deferred
  definition, like `total` under `--path-diversity`). `check_batch_test()` checks every
  (generator, filter, peers, prefixes) combination, not the first.
- **One rule cannot be checked before the run**: the converged count is not known until the table
  is delivered, so a run that accepted fewer prefixes than it offered can reach a block the flag
  guards passed. `ChurnBurstTracker` refuses it there and the sequence is reported incomplete
  rather than raising -- by then the convergence measurement is the thing being preserved.
- Stem gets `ch<C>x<B>`, both `run` blocks record both numbers, `-f` records `null`. Not a CSV
  column, for the reason `--path-diversity` is not.

`--policy-reload-blocks N` (batch: `policy_reload_blocks: N`, a *test* key) is the fifth workload
control and the last of Phase 5A's: once the run has converged, an import policy rejecting the last
`N` of the fleet's prefix blocks is installed on the target and applied with that daemon's own
reload command. Churn makes a converged table move; this makes the *policy over* a converged table
move, which is the thing an operator does most often and the thing nothing here has measured. The
daemon re-reads its config, re-evaluates its import policy against routes it already holds, and
withdraws the rejected ones from every export session, with the sessions staying up.

- **The workload is stated in blocks, not peers, and whole blocks are rejected.** A block is the
  group `--path-diversity` deals the fleet into -- one peer per block at the default. Rejecting
  *part* of a shared block leaves the prefix behind a surviving path, so the target does real
  best-path work and the monitor's count does not move at all: the reload could never be observed
  to complete. Same reason `split_churn_paths()` shares its block, reached from the other side.
- **The blocks are the tail, so there is no seed** -- churn's determinism rule. The set is
  rebuildable from the peer count, the diversity and the block count alone, and is published as
  `rejected_peer_asns` so nobody has to. The peers are ordered by **AS**, not by mapping order: a
  scenario is YAML and a mapping's order is not part of what the file means, while `gen_conf()`
  assigns the address and the AS from the same index it keys the diversity block on.
- **The expected count is exact and measured down from what the run converged on**, not from what
  the fleet offered -- the check-point's 0.99 factor exists because a target does not always hold
  everything offered to it. A target missing prefixes that fall *inside* a rejected block stalls,
  naming both counts, on `ChurnBurstTracker`'s rule: a tolerance would have to be a number nobody
  measured, and it would let a half-applied policy be published as an applied one.
- **`command_s` is published beside `reload_s`, never as it.** Measured on 3.3.2, `birdc configure`
  returns in ~20ms while the table drains over the following polls, so one number would credit the
  daemon with an instant reload. The started event is dated to the *sample* the reload was issued
  from rather than to the command's return -- the rule both poll loops already follow.
- **The CPU across the interval is the measurement, and an unsampled interval is `null`.**
  Re-evaluating a table is mostly CPU, and a reload finishing inside one poll would otherwise have
  no measurement beyond "it happened". Samples come from the target's existing stats thread and stay
  in the artifact -- `max cpu %` still describes the delivery, on churn's rule. `0.0` would publish
  an interval too short to sample as a daemon that did no work; those are different findings.
- **A collapsed count is not an applied policy**, in either phase, and the message names which.
  `DROP_FRACTION` and `CHURN_COLLAPSE_FRACTION` on a third side of convergence. Rejecting *every*
  block is refused up front for the same reason: an empty table cannot be told from an empty session.
- **What BIRD does was measured, not assumed** (2.19.2 and 3.3.2, two peers each). `birdc configure`
  holds the sessions up -- `Since` unchanged, both Established -- so these runs belong in the
  no-reset comparison `docs/policy-testing-plan.md`'s P4 asks for. But neither series re-evaluates
  purely locally: both answer a changed import filter by asking their peers for a route refresh, and
  each generator's `Export updates` doubled. `reload_s` therefore covers re-import as well as
  re-decision. Recorded as `mechanism` and `session_preserving` rather than hidden, and not
  comparable with a daemon that re-filters from its own stored routes.
- **Refused for**: a target with no reload mechanism (only BIRD has one -- read through
  `Target.SUPPORTS_POLICY_RELOAD`, never a list of names), an MRT generator (the policy selects a
  block by the peer AS bgperf2 assigned, and an injector replays the file's own paths), `-f`/a
  scenario target, `--filter_test` (the target's import filter is already the policy under test and
  the reload is written into the same place, so the run would change two policies at once), a churn
  workload, and a block count covering every block. `check_batch_test()` checks every
  (target, filter, peers) combination, not the first.
- **Refused alongside churn, deliberately**: both run against the converged table off the same
  monitor samples, so running both means fixing an order, and the second would take the first's
  outcome as its baseline with nothing in the row, the stem or the manifest saying which ran first.
  A deferred definition, like `total` under `--path-diversity`.
- **Refused under `-r/--repeat` too**, for a different reason than churn's. Churn needs the
  *generator* config rewritten; a reload is target-side and the target is rebuilt anyway, so the
  first version accepted `-r`. What breaks is the completion count: it is `blocks x prefixes per
  peer`, and repeat reuses whatever tester containers it finds while regenerating the scenario, so
  `-p` need not be what the generators are announcing. Measured -- `-n 4 -p 1000 -r` behind a
  `-p 10000` run converged at 40,000, expected the policy to leave 39,000, and the rejected peer
  took 10,000 with it. The collapse guard named it correctly, which is the point: it named it after
  a full run, and this is knowable from the command line.
- **There are three entry points here, not four.** `config` deliberately does not take the flag: a
  reload is a runtime action on the target and changes no part of the scenario, so `config` has
  nothing to emit for it and offering it there would print a scenario that reads as though it
  encoded a workload it does not.
- Stem gets `pr<N>`, both `run` blocks record it, `-f` records `null`. Not a CSV column, for the
  reason `--path-diversity` is not. The evidence key is `reload_complete`, not `complete`:
  `policy_reload_metrics()` derives a `complete` off the event stream, and
  `_policy_reload_section()` refuses a caller that lands on a derived name.

`--threads N` sets worker threads on the target (`conf['target']['threads']`). Only BIRD reads it
so far: **BIRD 3 runs one worker unless the config says otherwise**, so benching 3.x against 2.x
without it measures nothing (verified: 3.3.2 gives 2 OS threads by default, 5 with `threads 4`;
2.19.2 accepts the keyword and stays at 1).

`bench()` and `batch()` resolve and verify images before starting any container, so a version that
was never built costs a second rather than an hour.

Batch configs take `versions: [...]` on a target, expanded by `expand_target_versions()` into one
run per version with an auto label. Batch yaml is parsed with `BatchLoader`, which drops YAML's
float resolver — plain `yaml.safe_load` reads `10.10` as `10.1` and would silently bench the wrong
release.

### Repetitions

One observation per cell says nothing about run-to-run variance. A test may declare
`repetitions: N`; `expand_batch_cells()` turns the matrix into the ordered list of runs, and
`batch_repetitions()` rejects anything that is not a positive int **before the first container
starts** — a `repetitions: 0` that ran nothing would otherwise be found hours in. `check_batch_test()`
does the same for the matrix axes, which had no such check: a test with no `filter_test` reached
expansion as a bare `KeyError` naming neither the test nor the key, which is what
`benchmarks/big-tests.yaml` did. An axis is required rather than defaulted, so a typo cannot quietly
run the matrix unfiltered.

- **A repetition repeats the whole matrix, not each cell.** Three back-to-back runs of one cell
  share a page cache, a thermal state, and whatever else the machine was doing a minute ago, so
  part of what they measure is that. Block order also means an interrupted batch holds one
  observation of everything rather than every observation of the first few cells.
- **A repetition is part of the run's *name*, not a column beside it.** Everything a run writes is
  named from `bench_output_prefix()` — `<prefix>.events.json`, `<prefix>.versions.json`, the six
  per-run PNGs — and those are written with `os.replace`/`open(...,'w')`, so a second pass under
  the same name silently replaces the first one's evidence and the CSV grows two rows nothing can
  tell apart. `create_graph()` needs it too: it keys the x axis off a dict of row names and appends
  one bar height per row, so rows sharing a name give it fewer ticks than heights — a wrong graph
  or a crash, depending on the matplotlib version, at the end of a batch that has already run for
  hours. The artifacts also carry `run.repetition` so a summary does not have to parse a label to
  group passes.
- **`bench_output_prefix()` is the one place that names a run's files**, for the same reason, and
  it must carry every dimension a batch iterates. `filter_test` was missing: the three policy cells
  of `benchmarks/2026-filters.yaml` all wrote `bird_2.19.2_bgpdump2_1050000_10.*`, so two thirds of
  that suite's per-run evidence was overwritten and no `run` dict recorded which policy the
  survivor came from. The periodic mid-run graphs were worse — built from `args.target` alone, they
  dropped label, version, filter and repetition. Both now use the same stem, and each dimension is
  appended only when set, so an unfiltered single-pass run keeps the name it has always had.
- **A cell id says what the cell is, never when it ran.** `ordinal` is its position within one pass
  and `repetition` says which pass, so raising a test from two passes to three does not move the
  ids of the two that already have results, and resume keeps matching once execution order can be
  permuted.
- **The id and the name must agree about a single-pass test.** Both say "no repetition" — the cell
  carries `repetition: None` and the id omits the key entirely. Suffixing only when `repetitions >
  1` while the id always said `repetition: 1` meant a completed single-pass batch whose config
  later gained `repetitions: 3` matched its stored pass-1 ids under `--resume`, reused those rows,
  and produced a CSV holding `bird` beside `bird #2` and `bird #3`. Omitting the key also means a
  single-pass id has exactly its pre-repetition shape, so `BATCH_PROGRESS_SCHEMA_VERSION` did not
  have to move and an in-flight batch from an older build still resumes instead of costing the
  operator every completed cell.

### Order

A test may also declare `order: shuffle` (default `matrix`) and, optionally, `seed: <int>`. A test
key outside `BATCH_TEST_KEYS` + `BATCH_TEST_OPTIONAL_KEYS` is rejected: `seeds: 7` under
`order: shuffle` would otherwise draw a fresh permutation every invocation while looking pinned,
and a misspelt `repetitions` runs one pass of a matrix someone asked three of. Matrix
order runs every cell of one target next to every other cell of that target, so anything that
drifts over a batch — a thermal ramp, a filling page cache, a neighbour's job that starts an hour
in — lands on the axes as a pattern and comes back out as a difference between the daemons.
Shuffling does not remove that drift; it stops it lining up with one axis.

- **The permutation is inside a pass, never across one.** A repetition stays a block for the
  reason above, so dealing the passes together would take that back. Each pass draws its own
  permutation — one permutation reused for all three applies the same position bias three times
  and the repetitions cannot average it out.
- **The order is a digest of the seed and the cell id, not `random.shuffle`.** The point of
  recording a seed is that the sequence can be rebuilt later, and a Mersenne Twister draw is a
  property of the interpreter as much as of the seed. `tests/test_batch_order.py` pins one seed's
  order so changing the keying scheme has to be deliberate.
- **The seed is recorded in the progress file before the first cell runs**, and `--resume` uses
  the recorded one. A seed written only on a cell's completion would be missing from exactly the
  batches that died early, and a resumed batch drawing a fresh permutation has run two orders,
  neither of which is the one it recorded. Only a *drawn* seed is recovered that way — a seed the
  config states is left alone, since editing it by hand is an instruction to re-sequence. An
  omitted seed is drawn rather than defaulted to a constant: one shared default is itself a
  permutation nobody chose. A `seed` under `order: matrix` is rejected rather than ignored.
- **Execution order is not report order.** `batch_report_rows()` emits the CSV and the graphs in
  matrix order whatever order the cells ran in, because `create_graph()` keys the x axis off the
  row names it sees and appends one bar height per row, pairing the two positionally — that only
  holds while each (peers, prefixes, filter) group arrives with its targets in the same order. A
  shuffled batch reporting in execution order would produce bars under the wrong labels, or a
  length mismatch, at the end of a batch that has already run for hours.
- Identity is untouched by the order: `ordinal` stays a cell's place in the matrix, so `--resume`
  matches its completed cells whichever way either pass ran.
- **A superseded sequence stays in the file.** The progress document is rewritten whole on every
  checkpoint, so a sequence dropped when the config is edited mid-batch leaves the record
  describing an order that some of its own completed rows did not run in. It moves to
  `previous_seeds` instead, and only when rows exist to describe. That covers a matrix pass
  resumed as a shuffle, not just a changed seed — a file naming no order at all was written before
  ordering existed, and is read as matrix, because that was the only order there was.

### Summarising the passes — `summary.py`

A batch writes `<test>.summary.json` beside its CSV: one entry per matrix cell, with the
distribution of that cell's passes. Pure and Docker-free like `contention.py`, `convergence.py`,
`churn.py` and `findings.py`, and it reads the stats row **by column name** — that row is positional for
`create_batch_graphs()` and has drifted by a column once already, so a summary keyed on index 12
would be arithmetic nobody could check. `docs/measurement-dictionary.md` has the field list.

- **The summary never replaces the rows.** Every pass keeps its CSV row and its own artifacts; the
  summary carries the observations it computed each statistic from, and which pass produced each
  one. A number whose inputs are gone is not auditable.
- **Nothing absent is published as a zero.** A withheld statistic is `null` with its reason beside
  it. `stdev`/`cv_percent` need two observations — a CV of 0 over one pass says the measurement is
  perfectly repeatable on the strength of never having been repeated — and `cv_percent` needs a
  positive mean, which `tester errors` never has in a good run. `stdev` is the **sample** (n-1)
  deviation: the population formula understates the spread of one, to exactly 0 at n=1.
- **`min` and `max` are observations and are not rounded**; the derived statistics are, to six
  places, so a 0.4 MB spread in `max mem (GB)` does not read as `0.0`.
- **A failed pass is counted and named, never averaged in and never silently dropped.** Dropping it
  would change `n` without saying so, which is the one thing a dispersion cannot survive; a pass
  that has not run is counted apart from one that failed, because one is a result and the other is
  unfinished work.
- **An unsampled extreme is not an observation, here as well as in `findings.py`.** `min_free`
  starts above every real value and `max_mem` at 0, so an untouched sentinel reaches the row as
  ~931,322 GB or as 0.0 GB; `unsampled_row_values()` names both in the row's own units (via the
  single `row_gb()` formatter, so the two cannot drift) and the whole column is withheld for that
  cell. One pass of three losing its sampler would otherwise publish a ~310,474 GB mean and a 173%
  CV on a 64 GB box, or an 87% CV on the target's peak — and `Container.stats()` has no `try` around
  its walk, with a `mem` that comes from a `.get('usage', 0)`. `min idle%` and `max cpu %` are
  deliberately excluded: 100 and a peak rounding to 0 are both values a real run can report.
- **A stored row that is not the header's width costs its own pass, not the document.** `--resume`
  onto a progress file written before a column was appended is a supported path — the schema version
  deliberately did not move for `max foreign cpu %` — and one short row indexed against the current
  header raises, which the wrapper turns into *no summary at all* for that test. Such a pass is
  `unreadable`, kept apart from `failed`. A right-width, wrong-layout row cannot be caught here at
  all, which is why `stats_header()` is the contract.
- **Passes that disagree about an image are not observations of one thing.** `target image`,
  `tester version`, `monitor version` and `required` are checked for agreement across the passes
  and any disagreement lands in `inconsistent` and in a printed warning — the gcov trap (a freshly
  built version beside a cached one) reached one layer up.
- **Grouping and reporting are in matrix order**, sorted by `ordinal` rather than left in the order
  they arrived, for the same reason `batch_report_rows()` is: execution order is a property of the
  run, not of the report, and a summary dealt in shuffle order would sit under a CSV and a set of
  bars that were not.
- **A summariser that raises costs the summary, not the rows.** It runs after the CSV is on disk and
  `publish_batch_summary()` catches — same rule as `write_event_artifact()` and its findings.
- **It is written before the first cell, then after each one**, and a non-resumed batch unlinks its
  predecessor's summary along with its progress file — otherwise a write that then fails leaves the
  previous run's document beside a rewritten CSV. Every call site prints a failure line, including
  the two that do not ask for the description: it is the only report that the document beside the
  CSV is not the one describing it.
- **The document must stay readable by a strict parser.** `json.dump` runs with `allow_nan=False`
  and a non-finite observation is published as its own repr — a bare `NaN` is rejected by jq and by
  most non-Python parsers.
- **Whether a cell has earned more passes is a named rule, not a reader's judgement.**
  `apply_variance_rule()` says two cells are separated when their medians differ by more than the
  sum of their standard deviations, **floored at the metric's resolution**, applied to `elapsed (s)`
  alone. That floor is not a detail: `elapsed (s)` is whole seconds counted off the monitor's 1s
  poll loop, so passes of one cell agree exactly all the time, `stdev` is 0.0, and an unfloored
  rule clears any gap at all — publishing `separated` on one rounding boundary, in silence, for
  exactly the sub-second comparisons it exists to catch. `METRIC_RESOLUTION` is pinned against
  `MONITOR_POLL_INTERVAL_S` by `test_stats_contract.py`, since `summary.py` must not import
  `bgperf2`. Unnamed, the decision to rerun
  belongs to whoever read the CSV and disliked it, which reruns the surprising results and turns a
  benchmark into a search for the expected answer. It is comparative rather than a CV threshold
  because no CV means the same thing twice: 2% is nothing between targets 40% apart and fatal
  between ones 0.12% apart, which is what FRR 8.5, 9.1 and 10.0 were over a 95s MRT run. Three
  details are load-bearing. It is decided against **every** rival sharing the cell's (peers,
  prefixes, filter) axes and reported against the *binding* one — the smallest margin — since
  separating a cell from its nearest neighbour separates it from the rest only if every rival has
  the same dispersion, and `create_graph()` draws the whole group side by side. Rivals that have a
  dispersion are preferred, so one mostly-failed cell cannot sit between two unseparated ones and
  silently mute both — but preferred is not ignored. `separated` means *distinguishable from every
  cell drawn beside it*, so every rival that cannot be judged is a rival that cannot be cleared:
  each verdict names its unjudgeable rivals, and `separated` alone is withheld when one of them is
  at least as near as the binding rival, or has no observation at all. That one claim was got wrong
  three times, once per path into it — the rival that decided the verdict, the rival skipped for
  having no dispersion, the rival skipped for having no median — because each fix was written
  against the case instead of against the claim. The companion invariant, collapsed three times the
  same way: **a pass that failed and a pass that has not run are never described by one clause, at
  any level of aggregation** — one is a result to investigate, the other unfinished work, and only
  the first is something an operator can act on. And `EXPANSION_PASSES` (5) is a floor
  under the recommendation, never a cap: telling a `repetitions: 7` test to rerun at five would
  discard observations, and a cell with fewer observations than passes is told about its shortfall
  *beside* that count, never instead of it — fixing the failed pass and rerunning at the count you
  already had comes back unseparated again. Where a pair's two cells disagree, the printed line is the more
  actionable verdict, never the lower ordinal: a shortfall to investigate must not lose to "more
  passes will not decide it" on matrix position alone.
- The printed block is `elapsed (s)` and `total time` only, and nothing at all for a single-pass
  test; the cell is named by `batch_cell_description()`, since the run name alone is the target and
  two cells of one target differ only in their axes.

**Two targets in one test may not share a run name.** A run name is label, else target plus
version — nothing else — so entries differing only in `threads`, `mrt_file` or `image` are one
name, and that is the stem `bench_output_prefix()` builds every artifact from, the `name` column
of the CSV, and the x label `create_graph()` pairs bar heights against. `check_batch_run_names()`
refuses them before the first container and says to add a `label`; `expand_target_versions()`
already does the same thing along the version axis by labelling each version. This is also why
two identical target entries are refused rather than treated as two observations — that is what
`repetitions` is for, and it names its passes.

Note the container work directory (`<--dir>/<bench-name>`) is wiped at the start of every cell, so
raw daemon and tester logs only ever survive for the run in progress — that is true across cells
already, and repetitions do not change it. The published artifacts are the durable record.

### get_neighbors_state — the per-daemon wart

`bench` needs to know how many prefixes each neighbor has sent, and every daemon reports this
differently. There is no common API, so each target parses its own CLI:

- FRR: `vtysh -c 'sh ip bgp summary json'`, JSON
- BIRD: `birdc 'show protocols all'`, parsed by `bird.parse_protocols()` — which reads the
  route-change-stats table by **column name**. It replaced a positional TextFSM template
  (`bird.tfsm`, now deleted, along with the `textfsm` dependency): BIRD 3 inserts `RX limit`
  and `limit` into that table, so the field that is `accepted` on 2.19 is `RX limit` on 3.3.2.
  Every BIRD 3 target therefore reported `accepted` 0 for every neighbor, `neighbors_checked`
  never went all-True, and that route to `note_neighbors_checkpoint()` was dead — quietly, since
  runs still converged through `neighbors_received_full`. Never read a BIRD stats table
  positionally.
- Junos/EOS/SR Linux: vendor JSON via their own CLIs

FRR is a special case worth knowing about: it has no received-prefix counter, so
`FRRoutingTarget.get_neighbor_received_routes()` overrides the base method and greps `bgpd.log` for
`End-of-RIB` messages instead.

**That log read must stay incremental.** `write_config()` sets `log stdout debug` purely so
End-of-RIB is visible, which means `bgpd.log` grows with the route count — a 10-peer 1.05M-prefix
MRT run puts it past **1 GB**. `_get_EOR_from_log()` used to `readlines()` the whole file and
rematch every line once per second, costing 4+ seconds of CPU against a 1-second poll interval: the
loop fell permanently behind, stopped printing progress, and the run never finished even though the
target had converged minutes earlier. Measured on a real 1.04 GB log, same neighbors found either
way: **4.14s per poll before, 0.0000s after the first.** It now tracks a byte offset and reads only
what was appended, and:

- it stops at the last complete line, so a half-written one is not consumed and lost;
- the restart reset keys on **inode**, not size — a replaced log that had already grown past the
  saved offset would otherwise be resumed from the wrong place, and since FRR reaches its
  checkpoint only via End-of-RIB, missing those lines means the run never converges;
- the per-poll read is capped, and matching happens on bytes with the decode deferred to lines that
  hit, because this process's own RSS feeds the recorded `min_free` column.

### Asking the generator what it sent — tester offering polls

`bench()` polls every tester whose class sets `REPORTS_OFFERING` (`BIRDTester`
and `Bgpdump2Tester`) at the monitor's own 1s cadence, so the two sides of a run
are read at the same resolution. `Tester.offering_stats()` is the sampler;
`get_offerings()` returns one `measurements.TesterOffering` per configured peer,
and `measurements.TesterEventRecorder` turns those polls into
`tester_session_ready`/`tester_first_update`/`tester_last_update`/
`tester_complete`. They are merged into the same ordered `<prefix>.events.json`
stream as the monitor's events, with the derived intervals under `testers`. The
legacy `testers (s)` CSV column is untouched: it is elapsed minus
time-to-first-prefix, a property of the target and monitor, and the two must not
be read as versions of the same measurement.

`measurements.tester_fleet_metrics()` summarises every generator in the run into
one `tester_fleet` section beside those per-generator ones, aggregated the way
`TesterEventRecorder` combines the sessions inside one container: ready when the
**last** generator is ready, injection from the **earliest** first update to the
**slowest** completion, and completion all-or-nothing. One injector of ten that
never completed leaves `injection_s` null and its name in `incomplete_testers`
— an interval bounded by the nine that finished would describe a workload that
was never fully offered, and it would look entirely ordinary. Counts are summed
under the same rule; durations are not summed at all, because the generators
send at the same time. It is a summary of the sections, never a replacement:
the fleet says whether the load was delivered, the sections say which generator
was slow.

**`post_injection_tail_s` is signed, and nothing clamps it.** It runs from a
generator's completion (the **slowest** one, for the fleet) to
`monitor_required_reached`, and it is the only published interval that spans
two producers — which is why `measurements.signed_duration_s()` exists beside
`duration_s()`, which still refuses an inverted interval because within one
producer that is a wiring fault. A negative tail means the monitor reached the
check-point while the generator was still finishing, which is ordinary: the
check-point is 99% of the table, and a generator goes on flushing sessions it
did not need. Clamping at zero would give that run the same number as one that
converged the instant its generators finished — the two conclusions this
measurement exists to separate. It is never measured from `tester_last_update`
instead: that is the last increase *observed*, not the end of the workload, so
it would supply a plausible tail for exactly the stalled-injector runs that
have none. The printed line reports a magnitude at or under
`post_injection_tail_resolution_s` in words rather than as a duration.

**The monitor stamps its own poll resolution too**, for the same reason the
generators do and because the tail is bounded by one poll from each loop.
`Monitor.stats()` execs `gobgp neighbor -j` and only then sleeps 1s, so its
achieved cadence is `read + 1s`; `MonitorEventRecorder` takes
`MONITOR_POLL_INTERVAL_S` as a floor and publishes the gap it achieved — the
constant is *passed into* that loop rather than asserted about it, so the
published floor cannot drift away from the sleep the loop takes. **Both poll
loops stamp the sample before the read**, never after: the monitor's read is a
`docker exec` too, and dating its sample to when the read finished while the
generator dates its own to before would bias `post_injection_tail_s` positive
by a read from each instrument — on the one interval whose *sign* is the
finding. That
qualifies `first_prefix_s`, `convergence_s` and `assurance_s` as well, which
were previously published bare — a `first_prefix_s` of 0.0s is a poll that
could not resolve it, not an instant first prefix. `convergence_confirmed`
carries the resolution of the sample its verdict ruled on, not a gap to the
moment it was stamped: assurance is a decision about a sample, not a fresh
look.

**A span nothing crossed is not a rate of zero**, at either level. Each MRT
injector's sub-millisecond walk is over before its own first poll, so a fleet
span bounded by two injectors completing at different polls contains none of
the table: the real ten-injector run measured `injection_s` 1.0s with
`offered_in_interval` 0, and dividing would have published `0 prefixes/s` for
ten injectors that delivered all 100,000 prefixes. The same shape occurs
per-generator every time a self-reporting generator's count goes final one poll
before it says `End-of-RIB`. The rate is withheld in both cases — and the
printed line does not borrow the sub-poll wording for it, since "shorter than
the 1.0s poll resolution" is true only when first update and completion shared
a poll.

Five things this depends on:

- **The published resolution is the gap the loop achieved, not the one it asked
  for.** A poll stamps a sample, reads the generator, and only then waits, so
  sleeping a fixed interval after the read makes the real cadence
  `read + interval`. It waits to a deadline measured from the sample instead —
  except when the read itself overruns the interval, where it keeps the full
  wait rather than polling back-to-back and putting the controller inside a
  container continuously. Either way the recorder derives each event's
  `poll_resolution_s` from the sample timestamps (from the bench clock origin
  on the first poll, since everything before the instrument arrived is
  invisible), floored at the requested cadence, which the loop cannot beat.
  That number is what makes an `injection_s` of 0.0 read as *unresolved at this
  resolution* rather than as an instant injection, so understating it by the
  cost of the read overstates what the run knows. **Each interval is qualified
  by the polls that bound it** — `startup_resolution_s` and
  `injection_resolution_s`, never one shared number: sessions are usually up on
  the first poll, whose resolution is the whole interval since the origin, and
  folding that into the injection bound would call a 1s-resolved injection
  30s-unresolved.
- **One `docker exec` per poll, not one per peer.** A BIRD tester runs a
  separate `bird` per neighbour on its own control socket, so a bare `birdc`
  reaches no daemon at all and each socket must be named. They are read in a
  single `sh -c` loop, split on `bird.SESSION_MARKER`, because an exec is ~50ms:
  per-peer execs at 50 peers overrun the poll interval and the controller
  becomes contention the run then reports as someone else's.
- **Every configured peer appears in every poll**, with `offered=None` where the
  read failed. `observe()` rejects a poll whose session keys differ from the
  first one — dropping a key would let the peers that remain satisfy "the whole
  table was offered".
- **`expected` is the configured table size** (`len(p['paths'])`), never
  `tester_offering()['configured']`. That is the generator's own report of what
  it loaded, a cross-check; using it as the yardstick would make a generator
  that loaded half its config look complete.
- **The poll thread stops, twice over.** It waits on `controller_stop` like the
  other samplers, and `finish_bench()` sets `stop_monitoring` on the testers
  too, so a batch does not accumulate one exec loop per cell into containers
  that are gone. It also ends itself the moment the generator has reported the
  whole table offered, since polling on until the monitor converges spends a
  `birdc` per peer per second on a generator with nothing left to say — and
  `birdc` is in `contention.BGPERF_PROCESSES`, so that is the one load `max
  foreign cpu %` cannot report. The rule is
  `measurements.offering_poll_can_stop()`, and it is deliberately not
  `all(o.complete)`: it is the exact condition under which `observe()` records
  `tester_complete` on that same poll, which also needs every session's count
  legible and nonzero. A generator can report completion on a poll whose
  counters are not yet readable — bgpdump2 logs `RIB walk complete` before its
  final `Sent ...` counters — and stopping there would take away the poll that
  would have supplied the update, leaving a converged run with a generator that
  never completed. Nothing is lost by stopping: `offered` cannot move past
  completion, and a session's queue stops filling once the last update is handed
  to it, so the completion poll reads the largest queue there will be.

**A BIRD 2.19 offered count is queue-side.** `Export updates accepted` counts a
route when it is handed to the BGP protocol, not when it hits the wire, so it
saturates before the instrument first looks: in the 4-peer x 250k verification
the generator reported all 1,000,000 prefixes offered at 1.94s while the monitor
had seen 215,552 and the target held full tables from 2 of 4 peers. The count
and the completion fact are sound; the *duration* is not. Repeated runs put
between 0 and 153,744 of the million inside the measured interval depending
purely on where the first poll landed, and polling at 0.2s made it worse — a
confident-looking 21452 prefixes/s that was the slope of the last 6,436
prefixes. `tester_metrics()` publishes `offered_in_interval` beside
`offered_rate_pps` for that reason; never read the rate without it, and do not
call a BIRD 2.19 run tester-limited from it. Wire-side evidence needs BIRD 3's
`TX pending`, i.e. running the generator on `bgperf/bird:3.3.2`, which the CLI
cannot select today.

### Asking the other end what it got — export timing

`bench()` polls every receiver at the monitor's own cadence and publishes an
`export` section in `<prefix>.events.json`. Without it, **a `--receivers 20` run
and a `--receivers 0` run differ in exactly one published number** — `elapsed
(s)` — with whatever the fan-out cost the target inside it, indistinguishable
from a slow daemon. Ingress is measured at the generators and convergence at the
monitor; export was measured nowhere, which is the end-to-end collapse Phase 5A's
last work item is about.

`Receiver.accepted_prefixes()` is the read and it is deliberately not `stats()`,
which stays refused: `stats()` feeds the queue every published timing comes from,
and a receiver in it would be an unlabelled second `recved` series. This one
answers `controller_export_stats()`, which keeps it in `ExportEventRecorder` and
in a section of its own. `EventPhase.EXPORT` exists for the same reason one level
down — a reader grouping the stream by phase must not find several first-prefix
intervals under `convergence` with nothing saying which one the row describes.

- **The check-point is the run's own** (`conf['monitor']['check-points'][0]`),
  the same yardstick the monitor is judged by. Deriving one from what the monitor
  has seen so far would couple the two instruments, and the whole point of
  reading a receiver is that its answer does not depend on the monitor's. A
  policy that makes that count unreachable leaves the receivers incomplete
  exactly as it leaves `convergence_s` null.
- **One loop for the whole fan-out, not a thread per receiver.** A round reads
  each receiver in turn, so the controller is inside one container at a time.
  The alternative keeps the nominal cadence by putting N concurrent `docker
  exec`s on the host — and the run that wants this measurement is the one whose
  host is already loaded, so the instrument would become part of what it
  reports. A serialised round costs resolution instead, and the resolution is
  published: a 6-receiver 1M-prefix run measured a 3.8s round.
- **Every receiver in a round shares the round's timestamp, and the cost of that
  is bounded rather than hidden.** A round takes real time, so a receiver read
  late in it is dated to the round's start and can appear to reach a state up to
  one round-gap before one read early in it — which is what the 6-receiver run
  showed. That gap *is* each event's `poll_resolution_s`, and `export_spread_s`
  is compared against the wider of the two bounding it, so a fan-out served
  simultaneously can be off by at most one gap and can never be published as a
  *resolved* spread. Verified: spread 3.849s against resolution 3.849s, printed
  as "within the poll resolution of each other".
- **The fan-out is served when its *slowest* receiver has the table**, and one
  receiver that never got there leaves every fleet interval null with its name
  in `incomplete_receivers` — `tester_fleet_metrics()`'s all-or-nothing rule,
  reached from the export side. The export *start* is gated separately: a
  fan-out where every session was seen taking prefixes and one never finished
  has a real start, and that is exactly the run where a reader wants it.
- **Every configured receiver appears in every round**, with `None` where the
  read failed — the generator poll's rule, and here it is what stops the
  receivers that happen to answer from satisfying "the whole fan-out has the
  table". A failed read does not erase what that receiver was already seen
  holding; the last count read from each is published as `accepted_prefixes`,
  which is the only thing that says how far a receiver that never finished got.
- **`monitor_delta_s` is signed**, for the reason `post_injection_tail_s` is: the
  monitor is one export session among several and nothing orders them, so a
  receiver reaching the table first is ordinary. It is deliberately measured
  against the monitor rather than against the generators — a generator-relative
  export tail is `post_injection_tail_s + monitor_delta_s`, and publishing it
  here would repeat `tester_fleet_metrics()`'s completion rule in a second place
  where the two could drift apart.
- **The poll ends itself once every receiver holds the table**, since a round
  cannot be batched: continuing to convergence spends an exec per receiver per
  second on sessions with nothing left to say. That load is invisible to
  `max foreign cpu %` — not because it is bgperf2's own process tree (the read
  runs *inside* the receiver container, where `own_process_tree()` does not
  reach), but because `gobgp` is in `contention.BGPERF_PROCESSES`, the by-name
  allowlist, exactly as `birdc` is. A poll whose CLI were *not* in that
  frozenset would be charged to that column as somebody else's load. It is
  also why **every** round waits at least as long as it took
  (`EXPORT_POLL_MAX_DUTY`), not only one that overran the cadence: four
  receivers at a 200ms read give a 0.8s round inside a 1s cadence, 80% of the
  window spent inside containers without ever tripping an overrun. The
  instrument runs inside the window it measures, nothing bounds the receiver
  count, and it may never spend more than half its time inside containers. The
  cost is resolution — the 6-receiver run's 3.8s rounds now publish a 7.1s gap
  — and every interval publishes the resolution that bounds it. Nothing is
  lost: both events are recorded on or before the round that satisfies the
  rule, in that round rather than queued for someone else to record.
- **The poll takes one closing round when the window shuts.** The gap between
  rounds is wider than the window that follows the check-point: at six
  receivers it is a round plus its floor, against the five monitor polls
  between the check-point and convergence. Ending on the stop event without a
  last look would publish a fan-out served in that gap as one that was never
  served — the same false conclusion review found for the churn case, reached
  from the other side. The closing read is stamped when it is taken and carries
  the gap since the previous round as its resolution, which is the honest
  statement of when it could have happened. `finish_bench()` waits for it after
  the clock has stopped, for `EXPORT_POLL_TEARDOWN_WAIT_S` plus an allowance
  per receiver, since a flat wait long enough for six expires on fifty.
- **Export timing and a post-convergence workload are not measured in the same
  run**, and that is the settled answer rather than a gap. The poll's window
  closes at convergence, which is exactly where churn and the reload begin, so
  every way of making them coexist costs something published: letting the poll
  run on puts N `docker exec`s inside a burst's 1.0s-resolution withdrawal and
  the reload's CPU interval; waiting for it puts that wait inside `total time`
  — a graphed column, moving with the *instrument's* fan-out — and leaves the
  workload's recorder dating its first sample across the wait, so a withdrawal
  resolved to a second is published as "within the 25.0s poll resolution".
  Eight rounds of review found that seam from five different sides. A run that
  asks for both keeps the fan-out — the receivers exist, hold the table and
  cost the target its export work — and withholds the *timing* by name, on the
  rule `--prefix-scope total` under `--path-diversity` and churn beside a
  reload already follow. Choosing an order and paying for it is its own change
  set.
- **The window is the delivery of the table**, closing at convergence — the
  same window `elapsed (s)`, `max cpu %` and `max mem (GB)` describe. It closes
  there because the run does: nothing waits for the fan-out afterwards, and a
  wait that grew with the receiver count would land inside `total time`. A
  receiver not served by then is reported incomplete with the count it last
  held, and the printed line names the window, because "2 of 3" alone reads as
  a broken session. **`monitor_delta_s`'s positive side is bounded by that
  window** — convergence is 5 polls past the check-point, so a fan-out slower
  than that is reported incomplete rather than as a large lag, and what
  separates that from a stalled session is each receiver's `accepted_prefixes`.
  Giving the positive side a bound would mean a post-convergence phase that
  waits for the fan-out: a separate decision, like `total` under
  `--path-diversity`. The stop event is per run and never cleared, unlike
  `controller_stop`, so a round still in flight at the end of a batch cell
  cannot find that event clear again at the start of the next one.
- **This is the one sampler that does not go through the run's queue**, and the
  reason is that nothing would reliably take its messages out again: `bench()`'s
  monitor loop stops the instant convergence is declared, and `run_churn_bursts()`
  and `run_policy_reload()` read that queue afterwards and skip anything that is
  not a monitor sample. A round completing near the end of a run — and a round
  takes seconds at the fan-out sizes this measures — would be queued and never
  observed, publishing a receiver that had been served as one that never was,
  with the previous round's stale count beside it. The poll thread is its
  recorder's only writer instead, and `finish_bench()` waits
  `EXPORT_POLL_TEARDOWN_WAIT_S` for a round still in flight before reading it —
  **after** `bench_stop`, on the rule the tester log scan follows, so a wait
  that grows with the receiver count cannot reach `total time`.
- **Nothing about the CSV moves.** `elapsed (s)` is the monitor's convergence and
  must keep meaning that in every row; what the fan-out cost is printed beside
  the row and published in the artifact, on churn's and the reload's rule. A run
  with no receivers keeps exactly the document it has always produced. A run
  that *had* receivers and could not measure them — the check-point is 99% of
  the table, so `-p 1` gives 0, and a threshold of 0 would stamp every receiver
  complete on the first round — publishes an `unmeasured_reason` instead:
  absent is what an older build wrote, so silence could not be told from a
  build that never took the measurement.

**What still cannot be separated is table selection.** With this in place a run
decomposes into ingress (measured at the generators), the target's own work, and
export (measured at the receivers) — but best-path selection happens inside the
target and the only external observable is when a session sees the result. No
daemon-agnostic instrument can split it out of the target-side interval, so it is
stated here rather than implied by an interval that quietly contains it.

### What a bgpdump2 injector says about itself

`bgpdump2 --blaster` reports its own work to stdout, and `start.sh` redirects
that to `<host_dir>/bgpdump2.log`, which is bind-mounted — so the controller can
read it from the host, no `docker exec` per poll.

**It has to run under `stdbuf -oL`.** bgpdump2 logs with `fprintf(stdout)`, and
stdout to a file is block-buffered; nothing ever ends the process except the
container being torn down, so the buffer was never flushed. Measured: a
converged 2-injector run left both `bgpdump2.log` files at **exactly 0 bytes**
with the blaster still running and its work done. The generator had been
reporting all along and none of it was observable. A run whose log outgrows one
buffer is not saved by that either — it is simply always up to a buffer behind,
which is exactly the tail a poll wants to read. Any generator that logs to a
redirected stdout has this trap.

`parse_blaster_log()` and `tester_offering()` in `bgpdump2.py` read that log:

- **Prefix counts are encode-side, the octet count is wire-side.** `prefixes
  sent` and `updates sent` increment as prefixes are encoded into the 256KB
  session write buffer; `octets` only on a successful `write()` to the socket.
  One real mid-walk line reads `Sent 2280 updates, 9981 prefixes sent, 0
  prefixes withdrawn, 88 octets`. Same caveat as BIRD 2.19's counter, with one
  wire-side number beside it. It reaches the artifact as `octets_on_wire`, read
  at the poll that saw completion so it pairs with the `offered_prefixes` off
  the same line of counters. Two injectors sending the same 10,000 prefixes
  from different MRT peers wrote 183,852 and 259,226 octets — the byte count is
  a property of the paths played back, not of the prefix count.
- **`End-of-RIB, walk time` is bgpdump2's own measurement of its walk**, and it
  resolves what a 1s poll cannot: one injector's whole 10,000-prefix walk took
  1.03ms. It is encode time bounded by the write buffer, so on a table large
  enough to fill that buffer it tracks the wire and on a small one it does not.
  It times *one* RIB — a session given several `-p` indexes logs one per RIB,
  and summing them would drop the gaps between walks, so the summary publishes
  it only for a single-RIB session (which is what bgperf configures). It is
  published as `reported_injection_s`, **beside** the polled `injection_s` and
  never folded into it: different clock, and the generator's own definition of
  sending. No rate is derived from it either — dividing an encode-side count by
  an encode-side interval gives a send rate the generator never achieved.
- **Completion is the injector's own report, not a count.** `-T` caps the table
  while the MRT file is read, so an injector ends up holding whatever that MRT
  peer's table has; `offered >= expected` can stay false forever on an injector
  that has demonstrably sent everything it holds. That is what
  `TesterOffering.send_complete` is for, and it decides completion in both
  directions — a generator saying it has *not* finished is not overruled by a
  count that reached `expected`. `configured` vs `expected` stays the separate
  cross-check for a workload that did not load.
- **The completion signal is the `End-of-RIB` line, not `RIB walk complete`.**
  bgpdump2 logs the marker, then the final `Sent ...` counters, then End-of-RIB
  — one code path, microseconds apart, but a poll lands between them often
  enough. Reporting on the marker freezes the counters at their mid-walk value
  (9,981 of 10,000 in one capture), and in the other capture the marker precedes
  the first `Sent` line entirely, so completion would carry no count at all.
  `TesterEventRecorder` refuses that second case anyway: it holds
  `tester_complete` until an update has been observed, because a completion
  sorted before `tester_first_update` makes `tester_metrics()` raise out of
  `finish_bench()` and kills a run that had already converged.
- **The log's timestamps are never parsed.** They are local wall-clock with no
  year and no zone (`%b %d %H:%M:%S.%06lu`); durations here come from the
  controller's monotonic clock.
- **Blocked-write evidence is opt-in, because it costs the measurement beside
  it.** `--tester-trace-io` starts the blaster with `-t io`, whose write lines
  are the only backpressure bgpdump2 has: `Partial write` (the socket took part
  of the buffer and refused the rest) and `Write buffer full` (an encode pass
  found no room in the 256KB session buffer, which is also the only place a
  `write()` returning `EAGAIN` appears — bgpdump2 logs nothing for one). They
  reach the artifact as `max_blocked_writes` and `max_send_stalls`. But the
  same class logs one line per BGP message *received*, and the target
  re-advertises to each tester what it learns from the others, so those lines
  arrive in the blaster's event loop while it is still walking and lengthen the
  walk it is timing. Measured, three runs each on 2 injectors x 10,000
  prefixes: the injector whose walk overlapped the echo reported 0.01122 /
  0.01128 / 0.01125s without the flag and 0.01763 / 0.01756 / 0.01751s with it
  — a 56% inflation of `reported_injection_s`, the one number that resolves a
  sub-poll injection — and its log grew from 947 bytes to 350KB, which scales
  with the table, and lands in `min free mem` whenever `-d` names a memory-backed path.
  A run that wants to know whether the generator was blocked asks for it and reads a
  perturbed walk time; a run that wants the walk time does not. **`injection_s`
  is perturbed too, by a second mechanism**: `BlasterLogReader.READ_MAX` caps a
  poll at 4 MB, sized for the ~1 KB an untraced injector writes, so a traced
  injector can log `End-of-RIB` several polls before the reader gets to it and
  `tester_complete` is stamped late. Measured on a traced 2 x 500,000-prefix
  run: 22.5 MB written before `End-of-RIB` on one injector, `injection_s` 5.0s
  against its own reported 1.4996s. The counts stay exact — the reader catches
  up — so only the interval is affected. Never compare `injection_s` across the
  flag. **A count of
  zero is only published when the log proves the class was on**; otherwise the
  counters are absent, because 0 would say the generator was never blocked on
  the strength of lines it was never asked to write.

`Bgpdump2Tester` sets `REPORTS_OFFERING`, so `bench()` polls each injector at
the monitor's own cadence and every one of them contributes its own
`tester_session_ready`/`tester_first_update`/`tester_last_update`/
`tester_complete` to `<prefix>.events.json`, under its container name. There is
no aggregate across injectors and deliberately no `docker exec`: the log is
bind-mounted, so `BlasterLogReader` reads it straight from the host, keeping a
byte offset, stopping at the last complete line, and keying its restart reset on
**inode** as well as size — the same rules as the FRR reader, and for the same
reason: a replaced log that had already grown past the saved offset is not
smaller, so a size check alone would resume in the middle of a new session and
go on reporting the old one's completion. A
`Sent ...` line is logged per `write()` — one real capture shows an 88-octet
write — so the line count follows how the peer drained the session, not the
table size, and nothing bounds it in advance.

**A 10,000-prefix walk is over before the first poll.** Verified on a 2-injector
run: both injectors reported the exact 10,000, `tester_complete` observed, and
`injection_s` 0.0 with `offered_in_interval` 0 and no rate — the same
unresolvable-injection shape as BIRD 2.19, said out loud rather than published
as an instant injection. What says anything at all about that interval is the
generator's own two numbers, carried into the artifact from the poll that saw
completion: `reported_injection_s` (0.001017s and 0.011280s for the two
injectors of a later verification) and the wire-side `octets_on_wire`. The
printed line names both bounds rather than choosing between them — `injection
shorter than the 1.0s poll resolution; the generator measured its own send at
0.001017s`.

### What the run was waiting for — `findings.py`

The intervals above exist to answer one question, and `findings.py` is the only
thing allowed to answer it. It derives a `findings` section into every
`<prefix>.events.json` and prints its verdict as the last line of a run. Pure
and Docker-free like `contention.py`, `convergence.py` and `churn.py`, and it reads the
*artifact* rather than the event stream, so it cannot reason about a duration
the artifact did not publish.

`limiting_component` is `tester`, `target_or_monitor`, `unresolved`, or
`inconclusive`, and the last two are not the same refusal: `inconclusive` means
the deciding measurement was never made (no generator that can be asked, a
generator that never completed, a monitor that never reached the check-point),
`unresolved` means it was made and something forbids attributing it. Collapsing
them hides which one the operator can do something about. Each finding carries
the rule it applied (`policy`) and the durations it applied it to (`evidence`),
because a verdict that cannot be argued with is a validity boolean with extra
words.

Six rules hold the thing up:

- **Half the offered table must cross the measured interval before that
  interval may be read as the generator's send** — or the generator must have
  timed its own send. This is what keeps a queue-side counter from becoming a
  verdict *without the policy having to know which generator produced it*. BIRD
  2.19 puts between 0 and ~15% of its table inside that interval depending only
  on where the first poll landed, so it fails both tests and the run is
  `unresolved` with `injection_boundary_unresolved` — including its large
  positive tail, which would otherwise be charged to the target while the
  generator was still draining its sessions. An MRT injector fails the first
  test and passes the second, so a 10,000-prefix walk that is over before the
  first poll can still show a target tail.
- **A confounder withholds the verdict, not the evidence.** A tester-limited
  run on a saturated host still publishes the `tester_limited` finding and
  reports `unresolved`, naming host saturation as what decided it. `min idle%`
  is host-wide and includes bgperf2's own load, so it says the machine had
  nothing spare and not whose work that was — per-role, time-aligned CPU is
  what would say more, and it does not exist.
- **Backpressure names no component, and only the counts of *being blocked*
  qualify.** BIRD 3 reports `TX pending` bytes at every poll and a session with
  something queued is what a working session looks like, so reading queue depth
  as backpressure would withhold every BIRD 3 verdict there is. Only
  `max_blocked_writes` and `max_send_stalls` are read, and which end of a
  blocked write was at fault is not in those numbers.
- **An unsampled minimum is not a measurement.** `min_free` starts at a
  sentinel above every real value so the first sample can only lower it; a run
  whose memory sampler never fired would otherwise publish a machine with a
  petabyte free. `host_evidence()` maps it back to `None`.
- **Tester log errors and timeouts are deliberately not inputs.**
  `finish_bench()` writes the artifact *before* scanning those logs, on purpose,
  and a finding is worth less than the atomic write of the evidence it would be
  derived from.
- **A policy that raises costs the verdict, not the evidence.**
  `write_event_artifact()` catches: by the time the findings run, that document
  is the only record a converged run happened, and the failure is published in
  the shape of a verdict (`inconclusive`, naming the exception) rather than as
  an absent section that would read as a run with nothing to say.

`docs/measurement-dictionary.md` lists every finding and when it fires.

### Host contention — `contention.py`

A benchmark sharing its machine reports numbers that look fine and are not comparable with
anything. The margins here are small enough that this decides results: FRR 8.5, 9.1 and 10.0
finished a 95s MRT run within **0.11s** of each other, so a competing job of a few cores invents a
version ranking out of nothing.

`contention.py` attributes busy CPU to processes outside `BGPERF_PROCESSES`. It is kept free of
Docker and privileges so the test suite covers it, like `convergence.py`. Two consumers:

- `warn_if_machine_is_busy()` names the offenders before the run starts. It is called **after**
  `remove_target_containers()`, not at the top of `bench()`: `batch()` reuses the process for every
  cell, so checking earlier sees the previous cell's own target daemon and blames it.
- `controller_foreign_cpu()` samples every 5s into the same queue as the other controller threads;
  `bench()` keeps the max and writes it as the **`max foreign cpu %`** column. The interval is a
  parameter so the tests can pass a short one — the first sample only arrives one interval in,
  because the measurement is a delta.

`min idle%` cannot replace this: bgperf's *own* daemons move it, so it cannot separate "the target
worked hard" from "something else was running."

**Measure CPU as a delta between two `/proc` samples, never `ps -eo pcpu`.** This was got wrong
first time round and the mistake is easy to repeat, because `ps` looks exactly like what you want.
It reports cputime divided by process *lifetime*, so it fails in both directions: a job that
finished an hour ago still reads high and condemns a clean run, and — the case the whole module
exists for — a long-lived process that starts burning four cores for a 95s run barely moves its
average. On a real box: alive 16821s, 1475s of CPU, reads 8.7%; four cores for 95s takes it to
about 11%, well under the one-core threshold. A lifetime average also barely moves within a run, so
sampling repeatedly and keeping the max adds nothing over sampling once.

Every daemon a target can run must be in `BGPERF_PROCESSES`, including the commercial NOSes
(`rpd`, `Bgp`, `sr_bgp_mgr`, …) and `flockd`. A missing name means that target's own load is
reported as contention and every one of its rows looks incomparable — the failure is silent and
looks like a real finding. cEOS and SR Linux run dozens of agents each and those lists are the
main ones, not complete.

Three more traps, each of which made the feature report a *clean* machine while it was busy — the
worst possible failure for something whose output is "0 means the machine was yours":

- **Never allowlist interpreters.** `python`, `python3`, `sh` and `bash` were in the list at first,
  and `/proc/<pid>/comm` for a script-driven workload is the interpreter — so a neighbouring
  `python3 train.py` on eight cores was filtered out entirely. bgperf2's own Python is excluded by
  PID via `own_process_tree()`, which walks descendants of `os.getpid()`.
- **Kernel threads are excluded** (`PF_KTHREAD`). The ones that appear during a run — `ksoftirqd`,
  `kworker` — are doing *the benchmark's own* veth and bridge softirq work.
- **A process with no baseline is charged, capped at the interval.** Skipping first-seen processes
  scored a fully saturated machine at 0, because a parallel build is thousands of sub-second `cc1`
  processes that never appear in two consecutive samples.

The column goes **before** the three provenance columns, not after: `test_provenance.py` requires
provenance to stay last, and every graph index in `create_batch_graphs()` points at a column before
either group, so both invariants hold.

**The controller threads must actually stop.** They are governed by the `controller_stop`
`threading.Event`: `bench()` clears it before starting the samplers, `finish_bench()` sets it. This
was previously a module-level bool that `finish_bench()` assigned *without* `global`, so the
assignment created a local and was a no-op — and since `batch()` calls `bench()` in-process once per
cell, a 40-run batch ended with 40 `mpstat` loops, 40 `free` loops and 40 `ps` loops still polling.
bgperf was manufacturing the contention it now reports, and it grew run over run, so later cells of
a long batch were quietly noisier than earlier ones. Two things follow: clearing the event at the
start of each run is required or every cell after the first gets a sampler that exits immediately
and a contention column stuck at 0, and the samplers wait on the event instead of `time.sleep()` so
they stop at once rather than lingering a poll interval. `tests/test_controller_threads.py` covers
both directions.

### The bench directory must not be in RAM

`-d/--dir` holds every role's config and logs, bind-mounted under it, and defaults to `/var/tmp` —
**not** `/tmp`, which is tmpfs on most systemd distros. A 50-peer 100k-prefix BIRD run wrote
**31GB** of tester logs there — half this machine's RAM — pulling the recorded `min free mem` from
56GB to **28.5GB** on a run whose target daemon used **0.56GB**. A published, graphed column was
measuring tester logging. The default stayed `/tmp` long after that was found, while every operator
contract and every doc told the operator to pass `-d /var/tmp/bgperf` — so the only runs that hit it
were the ones nobody had thought about, which is the wrong way round.
`warn_if_log_dir_is_in_ram()` still runs at the start of every run, because `/var/tmp` is tmpfs on
some systems and `-d` can still name one; `is_memory_backed()` in `contention.py` is the pure part.

Moving off tmpfs traded that for a smaller failure, and `warn_if_log_dir_is_short_on_space()` covers
it: `/var/tmp` is on the **root** filesystem on most hosts, so a run that fills it takes Docker and
journald with it, hours into a batch, and what is lost is the finished cells' artifacts rather than
the current run. The floor is `LOG_SPACE_FLOOR_GB` (10) and is deliberately **not** an estimate of
the run in front of it: a 50-peer 100k-prefix BIRD run writes ~5GB of tester logs while a full-table
MRT run puts `bgpd.log` past 1GB, so those two ends differ by 30x and an estimate would have to know
what each generator logs. `free_space_bytes()` in `contention.py` is the pure part, and two details
in it decide whether the number means anything: it reads `f_bavail`, not `f_bfree` — the difference
is the reserve only root may use, and bgperf2 does not run as root — and it measures the nearest
**existing** ancestor, because `bench()` asks before it creates the directory, on purpose. A warning
about log volume is worth nothing once the logs are written.

Two things made it that large, and only one is fixed:

- The BIRD tester config used `log ... all`, which includes `trace` — every route event, ~7KB per
  prefix. It now names the classes `find_errors()` actually needs, about 6x less.
- What remains is `<RMT> Invalid route ... withdrawn`: the target re-advertises everything it
  learns back to the testers, which reject it. That is normal operation — `find_errors()` already
  excludes those lines — but they are class `remote`, which `find_errors()` needs, so they cannot be filtered
  out without blinding it. Stopping the target from exporting to testers would remove the noise but
  would also change the workload (no RIB-out to N peers), so it is left alone.

### Recording versions — provenance

A result nobody can trace back to a build is not reproducible, so every run records the version
**and** image of all three roles, not just the target: the testers generate the load and the monitor
is the instrument the timings are read from.

- `Container.version_string()` is the only thing that should ever be called for this. It returns
  what the daemon reported, or a string starting `UNKNOWN` explaining why not — it never guesses.
  Commas are rewritten to `;` because rows are `','.join()`ed with no quoting.
- Each daemon's `get_version_cmd`/`exec_version_cmd` belong on the **daemon base class**
  (`BIRD`, `GoBGP`, `RustyBGP`), not the `*Target` subclass. `Monitor(GoBGP)` and
  `BIRDTester(Tester, BIRD)` inherit from the base, so a version command defined on the target was
  invisible to them and asking raised `NotImplementedError`. That is why only targets used to be
  recorded.
- Parse defensively. These parsers used to take a fixed word (`ret.split(' ')[2]`), which on an
  error message produced a plausible-looking value — `benchmarks/baseline/baseline-benchmark.csv`
  has two rows whose BIRD version is the word `exec`. Match the expected banner and raise
  `VersionUnavailable` otherwise.
- `collect_provenance()` asks one tester per distinct image and records a count, so a 100-peer run
  does not exec into 100 containers.
- Output goes two places: three columns appended to the **end** of the stats row (`target image`,
  `tester version`, `monitor version`) and a full `<prefix>.versions.json` manifest beside the
  graphs. Appending at the end is required — `create_batch_graphs()` indexes the row positionally.

Caveat worth knowing: a git ref pins source, not dependencies. RustyBGP gitignores its `Cargo.lock`,
so its builds resolve dependencies fresh and old refs rot — `340f521` (the 2024-12 commit the 2025
baseline benched) no longer compiles on any toolchain, which is why it is not offered as a version.

### verify — the check the test suite cannot do

`./bgperf2.py verify` starts a throwaway container per built image and asks the daemon about
itself. It exists because the unit tests deliberately cannot touch Docker, so nothing else covers
the seam where a parser meets a real container — and that is exactly where the bugs have been.
Both of these pass every unit test and are caught by `verify` in about a second per image:

- rustybgp read its version with **GoBGP's** parser (`RustyBGPTarget`'s MRO is
  `RustyBGP → GoBGPTarget → GoBGP`), recording `UNKNOWN` on every run.
- openbgpd looked for `bgpctl` under `/usr/local/sbin`, which does not exist in the image.

It also checks the daemon binary for gcov instrumentation, the defect that made every FRR result
incomparable for years. Notes for anyone extending it:

- Probe through the classes that really run the image — `TARGET_CLASSES` **and** `TESTER_CLASSES`,
  never the daemon base class. The rustybgp bug was invisible when the base was asked directly,
  because GoBGP is not in that MRO. `TESTER_CLASSES` exists for this: `bench` builds
  `ExaBGPTester(Tester, ExaBGP)`, not `ExaBGP`, and bird/gobgp run as both roles with different MROs.
- The throwaway container is created with `entrypoint=[]`. `command` is *appended* to an
  `ENTRYPOINT`, not run instead of it, so `bgperf/bgpdump2` and `bgperf/exabgp_mrtparse`
  (`ENTRYPOINT ["/bin/bash"]`) would run `bash sleep 600`, exit 126, and every later `exec` would
  fail with "not running" — while `dckr.start()` still returned success.
- The tag-vs-reported-version check runs only when the label could plausibly appear in a banner
  (`expect_version_in_banner`). `resolve_ref()` passes unrecognized values through as raw refs, so
  `update gobgp --version master` is supported and reports `3.38.0` — demanding the word "master"
  would fail a good image. Matching is anchored on a numeric boundary, because a bare substring
  makes `3.1` match `3.13`.
- An explicitly requested version that is missing, or a run that checked nothing at all, exits
  non-zero. A green result over zero checks is the one outcome a caller must not be able to trust.
- `VERSION_NEEDS_DAEMON` (FRR) means the version command talks to a running daemon over a socket,
  so a bare container cannot answer it — it is reported as unprobeable, not as broken.
- A daemon with no version command at all is a declared gap, not a failure; failing on it would
  make `verify` permanently red and therefore worthless.
- The gcov pattern is `GCOV_PATTERN`, and `.gcda` only counts where a **non-letter** follows.
  A bare `\.gcda` matches Go's `runtime.gcdata` and flags every gobgp image. Both halves were
  validated against a purpose-built instrumented/clean pair — a detector that never fires is worse
  than none.
- `verify` creates containers, so it is not in the permission allowlist alongside the read-only
  subcommands.

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

Three rules here are load-bearing and were each broken at some point. Any change to `update()`
should be checked against all of them:

1. **Stability is tracked on every sample, including ones below the peak.** It used to sit behind
   the regression branch, so a count that came to rest under an earlier peak by *less than*
   `DROP_FRACTION` advanced neither the stability counter nor the stuck counter: the run could
   neither converge nor fail, and polled forever with the target idle. Every one of the four FRR
   MRT runs settles 0.07–0.43% below its peak, so this hung the entire FRR test, not an edge case.
2. **Regression is measured against the high-water mark, not the previous sample** — otherwise a
   count resting below its peak compares equal to the sample before it and a real slide is missed.
3. **A count sitting more than `DROP_FRACTION` below its peak must not be reported CONVERGED**,
   however steady it looks. Every real run reaches the neighbor checkpoint, which shortens the
   assurance window to 5 samples — fewer than the 10 the regression streak needs — so without that
   gate a run that lost half its routes and held there was reported CONVERGED at sample 6, with the
   loss visible only as a low `received` column. None of the original drop tests set the
   checkpoint, so this was uncovered; `test_a_big_drop_still_fails_once_the_checkpoint_is_set`
   pins it now.

Both halves of the regression rule apply to the same samples: the streak counts only samples that
are themselves past `DROP_FRACTION`. If sub-threshold wobble armed the streak instead, one later
sample past the threshold would fail the run instantly.

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

### 2026 benchmark campaign operator contract

When the user says `continue the 2026 benchmark campaign`, use these fixed defaults unless durable run metadata
already records different values:

- run ID: `2026-baseline`
- results root: `results/2026`
- work directory: `/data/bgperf-work`

Inspect `COMPLETE` markers, progress JSON, CSV rows, logs, and active benchmark processes first. Never run suites
concurrently. Monitor an active suite or resume an interrupted one; otherwise run exactly one suite with
`scripts/run_2026_suite.sh next --run-id 2026-baseline --workdir /data/bgperf-work`. Review it for failed rows,
tester errors/timeouts, foreign CPU contention, low free memory, and timing evidence. The legacy `testers (s)`
field is elapsed minus time to the first monitor-visible prefix, so its proximity to elapsed must not be used as
an injection-bound verdict. Stop after that one
suite is complete and reviewed, and tell the user to use the same prompt next time. Prerequisite image or MRT work
is allowed, but do not advance into a second suite in the same continuation.

### Measurement implementation operator contract

When the user says `continue the bgperf2 measurement implementation plan`, follow
[`docs/bgperf2-measurement-implementation-plan.md`](docs/bgperf2-measurement-implementation-plan.md). Inspect durable
state, resume unfinished work, and complete exactly one smallest reviewable change set from the first incomplete
phase. Run proportionate tests and any phase-required Docker verification, review the full diff, then stop and tell
the user to use the same prompt again. Do not start follow-up benchmarking before the release gate passes.

**That plan comes in two halves and both are part of being done.** The plan document is forward-looking --
phases, work lists, tests, exit criteria, and one `Status:` line each -- and stays short enough to read whole
before starting.
[`docs/bgperf2-measurement-decision-log.md`](docs/bgperf2-measurement-decision-log.md) holds why each change was
made the way it was, what was measured to decide it, and what its Docker verification showed, one section per
phase. Read the phase's log section before changing what that phase settled, and append to it when a change set
lands; the `Status:` line moves in the plan. Several log entries exist because a first attempt was wrong -- a
bound on an interval nobody measured, a poll resolution that understated itself, a guard that refused on one
path while another accepted silently -- so it is append-only: correcting an entry means adding what was found,
never editing the earlier reading away. The record of having been wrong is the part that stops it happening
twice, which is the same reason `verify` exists.

### 64 GB timing validation campaign operator contract

When the user says `continue the 64 GB timing validation campaign`, follow
[`docs/2026-64gb-timing-validation-plan.md`](docs/2026-64gb-timing-validation-plan.md) with run ID
`2026-timing-validation`, results root `results/2026`, and work directory `/data/bgperf-work`. Verify the measurement
release gate first. Never run cells or blocks concurrently. Monitor or resume an active block; otherwise run exactly
one next block, review timing evidence, correctness, provenance, contention, and memory, then stop at the reviewed
block boundary. The local 64 GB host is a hard ceiling; do not schedule a larger-memory workload.

**The campaign host is settled: the machine this repository is checked out on** -- 16 vCPU, 61.44
GiB, AMD EPYC 9R14 (`m7a.4xlarge`), resized into that shape on 2026-09-03. Justin chose it on
2026-09-08 as the closest available match to the host that produced
`benchmarks/baseline/baseline-benchmark.csv`, which is a match on memory (61.44 GiB against 60.74)
and **not** on CPU. Run Phase 6 calibration and every campaign block on this machine; that is what both plans
require -- one host for the whole experiment. The cost is paid in exactly one place:
**campaign rows may never be read against `benchmarks/baseline/baseline-benchmark.csv`**. That is
already the campaign's own design (it is not a continuation of `2026-baseline`, it re-runs the
comparisons under a new run identity), so nothing has to be given up for it -- but nothing refuses
it either, and `create_batch_graphs()` will put two hosts' bars side by side without comment.

**The work directory in both contracts above moved to `/data/bgperf-work` for this host**, and
that is the whole of the change -- there is no advisory version of it, because a work directory
named in prose beside a contract that pins a different one is read as decoration. `/var/tmp` here
is on the **29 GB root**, with ~26 GB free, shared with journald and the OS; `/data` has ~150 GB.
Docker itself is safe either way -- `/etc/docker/daemon.json` sets `data-root` to `/data/docker` on
this host, so images and container logs are not on the root. `2026-core-mrt.yaml` runs 14 target
configurations at 1.05M prefixes, five of them `frr_c` whose `bgpd.log` alone passes 1 GB, and
`warn_if_log_dir_is_short_on_space()` only fires below `LOG_SPACE_FLOOR_GB` (10) -- so a batch can
fill the root hours in and take Docker and journald down with it, losing the *finished* cells'
artifacts rather than the current run. The `2026-baseline` contract's "unless durable run metadata
already records different values" clause still wins for that campaign, so anything in flight keeps
the directory it recorded. **The timing-validation campaign has no such clause** -- its work
directory is part of Fixed Campaign Identity -- but it has not started, so there is nothing to
contradict; if a block is ever found mid-flight against `/var/tmp/bgperf`, the recorded manifest
wins and the discrepancy is a finding to report, not a path to silently switch.

### Unattended execution operator contract

When the user says `continue the unattended execution plan`, follow
[`docs/unattended-execution-plan.md`](docs/unattended-execution-plan.md). Inspect which migration
steps are complete, complete exactly one step, verify its exit criterion, record progress in that
document, then stop and tell the user to use the same prompt again. That plan is infrastructure for
the other three contracts: it runs no benchmark and changes no measurement semantics.

Two things the plan leaves to whoever adopts it, settled here:

- **The driver's scope is the measurement plan, and it stops at Phase 6 — for a reason that has
  changed.** It used to stop because calibration taken on the development host would describe a
  machine the campaign never runs on. That reason is gone: as of 2026-09-08 this *is* the campaign
  host (see the campaign contract above), and the resize took it past the memory objection too. The
  stop stays for the reason underneath it: a Phase 6 calibration is a multi-hour benchmark that
  takes the whole host exclusively, and starting one is the operator's call, not something a worker
  does to see how it goes. A worker that finds Phase 6 next still stops and says so. Do not restate
  the old wording — an 8-core / 30 GB host is not what this runs on any more, and a contract that
  describes a machine that no longer exists is followed anyway.
- **Unattended work does not reach master.** It commits to `unattended/measurement`, and
  `/code-review` before every commit stays part of the definition of done — it is the only thing
  between a bad edit and the branch, and it does not become optional because nobody is watching.

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
  `bd setup`, and do not run one casually.
