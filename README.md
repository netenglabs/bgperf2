bgperf2
=======

bgperf2 measures how fast BGP daemons converge and what it costs them. It runs
the daemon under test in a container, has generator containers announce routes
to it, and times how long the routes take to come back out through a monitor
session, while sampling CPU and memory. It started as a fork of
[osrg/bgperf](https://github.com/osrg/bgperf) and has since been largely
rewritten.

* [Install](#install)
* [Your first run](#first-run)
* [What a run writes](#outputs)
* [Batches](#batch)
* [Getting results you can trust](#trust)
* [Targets and versions](#targets)
* [Debugging](#debugging)
* [Roadmap and development plans](docs/roadmap.md)
* [Portable recipe and result contracts](docs/recipes.md) (export, validate, plan, check and selected image preparation; no execution)
* [How bgperf2 works](docs/how_bgperf_works.md) ·
  [Benchmarking a remote target](docs/benchmark_remote_target.md) ·
  [MRT injection](docs/mrt.md) ·
  [Measurement definitions](docs/measurement-dictionary.md)

## What it does

Each run has three roles, each in its own container on a dedicated Docker
network:

- **target** — the daemon under test: BIRD (`bird`), FRRouting built from
  source (`frr_c`), OpenBGPD (`openbgp`), RustyBGP (`rustybgp`, routes and
  neighbors only; it lacks some of the policy bgperf2 uses), Flock (`flock`),
  and the commercial Arista cEOS (`eos`), Juniper cRPD (`junos`) and Nokia
  SR Linux (`srlinux`).
- **testers** — route generators. BIRD (default) or ExaBGP synthesise prefixes,
  which makes it cheap to drive hundreds of peers; bgpdump2 plays back an MRT
  file, which is how you load a full Internet table.
- **monitor** — the measuring instrument, peered with the target, counting what
  the target re-advertises. The default is the purpose-built sink
  (`bgperf/sink`); `--monitor gobgp` selects GoBGP, kept as a reference to
  re-check a sink result against. GoBGP is not a target.

`bench` runs one such experiment; `batch` runs a matrix of them from a YAML file
and compares them in a CSV, a summary and graphs.

## Prerequisites

* Linux with Docker; your user must be in the `docker` group.
* `sysstat` and `procps` (`bench` shells out to `mpstat` and `free`).
* Python 3.14 with venv/ensurepip support. `requirements.lock` pins the full
  runtime and test environment; `pip-requirements.txt` and `test-requirements.txt`
  are the human-edited sources.

## <a name="install"></a>Install

```bash
git clone https://github.com/netenglabs/bgperf2.git
cd bgperf2
python3.14 scripts/bootstrap.py
venv/bin/python bgperf2.py prepare -t bird -t sink   # the default target, tester and monitor
venv/bin/python bgperf2.py doctor
venv/bin/python bgperf2.py verify -t bird
```

Activating the venv (`source venv/bin/activate`) lets you run `./bgperf2.py`
directly, as the rest of this document does. On a fresh Ubuntu VM, `new_vm.sh`
installs the system packages and creates the venv. A bare `prepare` builds one
image for every buildable daemon, which takes hours; build what you need with
`-t`.

### Commands

| Command | What it does |
|---|---|
| `doctor` | Checks Docker and lists which images and versions are built |
| `prepare [-t NAME ...]` | Builds daemon images; skips existing ones unless `-f` |
| `update NAME --version V` | Builds one more version image |
| `images` | Lists versions, which are built, and the git ref each came from |
| `verify [-t NAME]` | Starts each built image and checks it reports its own version |
| `dockerfile NAME --version V` | Prints the Dockerfile a version would build, without building |
| `bench` | Runs one benchmark |
| `batch -c FILE` | Runs a matrix of benchmarks from a YAML file |
| `config -o FILE` | Writes the scenario a `bench` would use, without running it |

Global options go before the command: `-d/--dir` is the work directory for
configs and logs (default `/var/tmp`; see
[where the work directory lives](#workdir)) and `-b/--bench-name` names the run's
subdirectory and Docker network (default `bgperf2`). Every command has `--help`.

The separate `venv/bin/python recipes.py` entry point offers `export`, `validate`,
`inspect`, `plan` and `result-validate` without probing the host or Docker.
`check` explicitly takes a read-only prerequisite snapshot using the local Docker
CLI; it never acquires images or starts containers. It supports a small synthetic
IPv4 recipe contract. `prepare RECIPE` reports a local image acquisition plan;
only `prepare RECIPE --pull` can acquire missing selected repository digests.
Recipe execution remains future work. See the [recipe guide and public fixture](docs/recipes.md).

## <a name="first-run"></a>Your first run

```bash
./bgperf2.py bench -n 10 -p 1000
```

This benchmarks BIRD (`-t bird` is the default) with 10 BIRD tester peers each
announcing 1,000 prefixes (the defaults are 100 and 100). While it runs it
prints a progress line every second; at the end it prints a summary and one CSV
row, preceded by its header, for pasting into a spreadsheet. The columns are
defined in the [measurement dictionary](docs/measurement-dictionary.md); the
ones most people want are `elapsed (s)` (convergence as seen by the monitor),
`max cpu %`, `max mem (GB)` and `max foreign cpu %` (anything else competing
for the machine; `0` is what you want).

Common options:

* `-t NAME` and `--version V` — the target and its version image.
* `-n` / `-p` — peers, and prefixes per peer.
* `-g bgpdump2 --mrt-file /absolute/path` — play back an MRT file instead of
  synthetic prefixes; see [Getting an MRT table](#mrt). (Batch configs may use
  relative paths.)
* `-a`, `-e`, `-c`, `-x` — the number of as-path, prefix-list, community-list
  and ext-community-list filters on the target (default 0).
* `--filter_test transit|ixp` — apply a realistic import policy.
* `--pin target=0-7,monitor=8-9,testers=10-15` — give each role its own cores
  (add `receivers=...` with `--receivers`). Every role the run has must be named
  and the sets must not overlap. Pinning keeps the generators and the monitor
  from competing with the daemon you are measuring.
* `--monitor gobgp` — the reference monitor instead of the sink.
* `-o FILE` — also append the CSV row to `FILE`.

Try `-n1 -p1` first if anything looks wrong; see [Debugging](#debugging).

## <a name="outputs"></a>What a run writes

Everything generated goes under `results/` (gitignored), or `--results-dir`.
Every file of a run is named from one stem built from what the run was —
target, version, tester, prefixes, peers, and any filter, workload control,
pinning, monitor and repetition — for example
`bird_2.19.2_bgpdump2_1050000_10_mon-sink`.

| File | Contents |
|---|---|
| `<stem>.events.json` | The full record of one run: timing events, what each generator offered and when, the target's own table, export, churn and policy-reload results, host contention, and `findings` naming what the run was waiting for or why that cannot be said |
| `<stem>.versions.json` | Provenance: the bgperf2 revision, every image and daemon version, the run's parameters and the host |
| `<stem>_cpu.png`, `_mem_used.png`, `_free_mem.png`, `_machine_idle.png`, `_mon_received.png`, `_neighbors.png` | Time series of the run |

A batch also writes, per test:

| File | Contents |
|---|---|
| `<test>.csv` | One row per run, in matrix order |
| `<test>.summary.json` | Median, min, max, spread and pass states across repetitions, and whether cells are separated |
| `<test>.cells/<key>.json` | Each cell's row, the record the CSV and summary are built from |
| `bgperf_<test>_<metric>.png` | Bars comparing the targets: elapsed, total time, route reception, CPU, memory and more |

`bench` exits 1 when its run is marked failed (as for a setup error), 143 when
stopped by SIGTERM, and 0 when the run converged. A batch records a failed cell as a result and carries on.

The CSV is the legacy, compact view. The `events.json` and `summary.json`
documents carry what the CSV cannot, and the
[measurement dictionary](docs/measurement-dictionary.md) defines every field.

## <a name="batch"></a>Batches

A batch runs every combination of the axes in a YAML file and compares the
targets. `benchmarks/example.yaml` is the smallest one; keep your own configs in
`benchmarks/local/`, which is gitignored.

```bash
./bgperf2.py batch -c benchmarks/example.yaml
```

```YAML
tests:
  - name: mrt-table              # names the CSV, summary and graphs
    neighbors: [10, 20]          # axes: every combination is a cell
    prefixes: [1_050_000]
    filter_test: [None]          # None, transit or ixp
    repetitions: 3               # optional: run the whole matrix 3 times
    order: shuffle               # optional: matrix (default) or shuffle
    seed: 20261021               # with shuffle: fixes the order
    monitor: sink                # optional: sink (default) or gobgp
    pin: target=0-7,monitor=8-9,testers=10-27
    targets:
      - name: bird
        version: 2.19.2
        tester_type: bgpdump2
        mrt_file: mrt/rib.20260808.0000
      - name: frr_c
        versions: [9.1, 10.7]    # one target entry per version
        tester_type: bgpdump2
        mrt_file: mrt/rib.20260808.0000
```

**Test keys** (beside `name`, `neighbors`, `prefixes`, `filter_test` and
`targets`, which are required): `repetitions`, `order`, `seed`, `monitor`,
`pin`, and the workload controls `prefix_scope`, `path_diversity`, `receivers`,
`churn_prefixes`, `churn_bursts` and `policy_reload_blocks` described under
[workload controls](#workload). Any other key is refused, so a typo cannot
silently run the wrong matrix.

**Target keys**: `name`, `version` or `versions`, `label` (the row and bar
name; two targets in one test may not share one), `tester_type` (`bird`,
`exa` or `bgpdump2`; default `bird`), `mrt_file`, `mrt_injector`, `threads`,
`image`, `filter_type`, the filter counts `as_path_list_num`,
`prefix_list_num`, `community_list_num` and `ext_community_list_num`, and the
addressing overrides `local_address_prefix`, `target_local_address`,
`monitor_local_address`, `target_router_id` and `monitor_router_id`, and
`license_file`, `repeat`, `tester_trace_io`, `docker_network_name` and `file`
(a scenario file). A test key written under a target is refused rather than
ignored.

Paths in a config may be relative or use `~`. Every axis combination is checked,
and every image must exist, before the first container starts.

### Repetitions

One run of a cell tells you nothing about how much that number moves between runs. Add
`repetitions` to a test to run the whole matrix more than once:

```YAML
tests:
  - name: variance
    repetitions: 3
    neighbors: [10]
    prefixes: [100_000]
    filter_test: [None]
    targets:
      - {name: bird, version: 2.19.2, label: bird 2.19.2, tester_type: bird}
```

The matrix is repeated as a block — every cell once, then every cell again — rather than each cell
three times in a row, so consecutive runs of the same cell do not share a warm page cache and the
same thermal state, and an interrupted batch has one observation of everything rather than every
observation of the first few cells.

Each pass gets its own run name (`bird 2.19.2 #1`, `#2`, `#3`), so its CSV row, its graph bar and
its `.events.json` / `.versions.json` are its own; a shared name would have the second pass
overwrite the first one's files. A test without `repetitions` runs once, with no `#` suffix.

### Order and seed

`order: shuffle` runs each pass of the matrix in a permuted order, so slow drift
over a long batch (a warming machine, a filling cache, a neighbour's job) does
not line up with one target. The permutation is derived from `seed`; state one
to make the order reproducible. Without one a seed is drawn and recorded in
every cell's result. The CSV, summary and graphs are always in matrix order.

### Stopping and resuming

SIGTERM stops a batch at the next check: the cell in flight is abandoned rather
than recorded, and the process exits 143. `--resume` then skips every cell that
already has a result and runs the rest in the planned order, continuing a drawn
seed. It refuses results for cells the config no longer lists and results that
ran under a different order or seed: if you edit an axis, target, monitor,
`repetitions` or `seed`, measure into a new `--results-dir`. A plain `batch`
starts fresh and removes the previous cell results for its tests.

### Running a batch in pieces

```bash
./bgperf2.py batch -c my.yaml --list-cells             # every cell, in run order, with its key (JSON; no Docker)
./bgperf2.py batch -c my.yaml --cells 3f2a... 9c01...  # run just these cells, then rebuild the report
./bgperf2.py batch -c my.yaml --cells 3f2a... --no-report
./bgperf2.py batch -c my.yaml --report                 # rebuild CSV, summary and graphs from recorded cells
```

The report names any cell without a result and leaves the graphs until every
cell has one. `--cells` refuses a cell that already has a result; delete its
`<test>.cells/<key>.json` to measure it again. `--list-cells` and `--cells`
need `seed:` on a shuffled test.

## <a name="trust"></a>Getting results you can trust

### The machine has to be yours

A benchmark sharing its host produces numbers that look fine and mean nothing,
so every run records what else was running. This is not a theoretical worry:
FRR 8.5, 9.1 and 10.0 finished a 95-second MRT run **within 0.11s of each
other**. A competing job of a few cores is more than enough to invent a version
ranking that never existed.

Two guards:

- `bench` prints a warning before it starts if processes outside the benchmark
  are already using more than one core's worth of CPU, and names them.
- Every row carries a **`max foreign cpu %`** column: the worst competition seen
  during the run, as a percentage of one core (so `400` means four cores). `0`
  means the machine was yours.

`min idle%` cannot do this job alone, which is why the column exists: it also
moves when *bgperf's own* daemons work, so it cannot separate "the target worked
hard" from "something else was running."

**CPU is measured as a delta between two samples of `/proc`, not with
`ps -eo pcpu`.** This matters more than it sounds. `ps` reports a *lifetime
average* — CPU time divided by how long the process has been alive — which is
wrong in both directions here. A job that finished hammering the machine an hour
ago still reports a high number and would condemn a perfectly good run. Worse,
the case the check exists for is invisible to it: a long-lived process that
starts burning four cores for the 95 seconds of a run barely moves its average.
Measured on a real box, a process alive 16,821s having used 1,475s of CPU reads
8.7%, and four cores for 95s would take it only to about 11%.

bgperf's own processes are recognised two ways: its daemons by name, and the
harness itself by walking the process tree from its own PID. Interpreter names
are deliberately *not* allowlisted — `/proc/<pid>/comm` for a script-driven job
is just `python3`, so allowlisting it would hide a neighbouring `python3
train.py` completely.

If a row shows foreign CPU, re-run it before comparing it against anything.
The logic lives in `contention.py`, kept free of Docker so it is unit-tested.
Every daemon that a target can run is listed in `BGPERF_PROCESSES`; **if you add
a target, add its process names there** or that target reports its own load as
contention and all of its rows look incomparable. The cEOS and SR Linux entries
are the main agents, not the complete set.

### <a name="workdir"></a>Where the work directory lives

`-d/--dir` defaults to `/var/tmp`, and it holds every tester and target log,
bind-mounted. It defaulted to `/tmp` for years, which systemd mounts as tmpfs on
many distros — so those logs were written into **RAM**. That is not a small
effect. A 50-peer × 100k-prefix BIRD run wrote **31 GB** of tester logs, half
the machine's memory, and dragged the recorded `min free mem` from 56 GB down to
**28.5 GB** on a run whose target daemon used **0.56 GB**. The column was
measuring log volume, not the daemon; on a smaller box it is an out-of-memory
failure instead of a misleading number.

`bench` still warns if the directory it is given turns out to be memory-backed,
because `/var/tmp` is a symlink to `/tmp` on some images and `-d` can name a
tmpfs path outright.

It also warns when that filesystem has less than 10 GB free. `/var/tmp` is on
the **root** filesystem on most hosts, and a run that fills it takes Docker and
journald with it — hours into a batch, losing the artifacts of the cells that
already finished. Point `-d` at the larger filesystem when there is one:

```bash
./bgperf2.py bench -d /data/bgperf-work -t bird ...
```

The BIRD tester's logging was also `log ... all`, which includes `trace` and
recorded every route event at about 7 KB per prefix. It now logs only the
classes `find_errors()` needs, cutting roughly 6× off the volume. What remains
is almost entirely `<RMT> Invalid route ... withdrawn` — the target reflecting
routes back to testers that reject them, which is normal and which
`find_errors()` already discards.

### Reading the timing fields

The complete field-by-field contract is in the
[legacy CSV measurement dictionary](docs/measurement-dictionary.md).

`elapsed (s)` is the monitor-observed convergence boundary after trailing
assurance samples are removed; it is not necessarily a literal full-table time.
`prefix received (s)` is the time until its first monitor-visible prefix. The
historical `testers (s)` field is calculated as `elapsed - prefix received`;
despite its name, it is not the generators' runtime and does not say when they
finished sending routes.

Consequently, a `testers (s)` value close to `elapsed (s)` cannot establish
that a run was injection-bound. That conclusion requires an explicit tester
completion event and comparison of injection time with the post-injection
convergence tail, both of which are in `<prefix>.events.json` rather than the
CSV. `post_injection_tail_s` is the second of those: the interval from the
last generator finishing to the monitor reaching the required count, printed
at the end of a run and published per generator and for the fleet.

It is **signed**, and a negative value is an ordinary result rather than a
fault — the monitor reaches the check-point (99% of the configured table)
while the generators are still finishing, which is what a run looks like when
the target was never the thing being waited for. Both ends come from 1s poll
loops, so a tail whose magnitude is at or under
`post_injection_tail_resolution_s` says the two events landed within one look
of each other, in either direction, and says nothing about which side was
slower.

`post_injection_tail_s` is not the only measurement outside the CSV. A run
also publishes what each generator offered and when (`testers`,
`tester_fleet`), what the target itself held (`target_table`), what the export
fan-out received (`export`), what a churn sequence or a policy reload cost
(`churn`, `policy_reload`), and a `findings` section naming what the run was
waiting for — or, more often, saying which measurement forbids naming it. All
of them are in `<prefix>.events.json`, and each run records the bgperf2
revision and schema versions that produced them.

The [measurement dictionary](docs/measurement-dictionary.md) defines current
measurements and their limits.

### IPv4 only

Everything here is IPv4, in four separate places: synthetic prefixes are
generated as IPv4 `/32`s (`gen_paths`), the MRT injectors replay only IPv4, the monitor and gobgp read `afi_safis[0]` — the first address
family — so v6 routes would not be counted even if they arrived, and peering
uses an IPv4 `--local-address-prefix`. Supporting IPv6 means all four: prefix
generation, a v6 peering plane, dropping `--no-ipv6`, and summing across
families instead of indexing `[0]`.

## <a name="targets"></a>Targets and versions

### Several versions of one daemon

Each buildable daemon gets one image per version, tagged `bgperf/<name>:<version>`. Build them
with `prepare` (which builds the daemon's default list) or `update` (for anything else):

```bash
./bgperf2.py prepare -t frr_c                              # master + 8.5, 9.1, 10.0, 10.7
./bgperf2.py prepare -t frr_c --versions 10.4,10.5         # just these two, plus master
./bgperf2.py update frr_c --version 10.7                   # add one later
./bgperf2.py images                                        # what is built, and from which ref
```

Then bench one directly, or list several in a batch config:

```bash
./bgperf2.py bench -t frr_c --version 10.1 -n 10 -p 100000
```

```YAML
      -
        name: frr_c
        versions: [8.5, 9.1, 10.0, 10.7]
        tester_type: bird
```

That runs once per version and labels each row `frr_c 10.1` and so on, so the CSV and the graphs
tell them apart. Add your own `label:` to override. A target with no `versions:` uses the
unversioned image, which tracks the daemon's default branch.

Versions are named the way the project names its releases, and each daemon module translates:
FRR `10.1` is the branch `stable/10.1`, FRR `10.1.1` is the tag `frr-10.1.1`, BIRD `2.19.2` and
GoBGP `3.37.0` are the tags `v2.19.2` and `v3.37.0`. Anything unrecognized is passed through as a
raw git ref, so `--version master` or a commit sha also work. `./bgperf2.py images` prints the
mapping.

A bare `prepare` builds one image per daemon, tracking its default branch. Version images are
opt-in behind `-t`, because a daemon's whole version list is hours of compiling. Either way it
skips what already exists, so re-running after adding a version is cheap; `-f` forces a rebuild.
`doctor` lists which versions are built and which are not.

Every version image must exist before a run starts — `bench` and `batch` both check up front and
tell you the exact `update` command rather than failing an hour into a batch.

The commercial NOSes work the same way once you tag what you downloaded (`docker tag <image>
crpd:24.2`, then `-t junos --version 24.2`).

#### BIRD 3 and threads

BIRD 3 is the multi-threaded rewrite; BIRD 2 does everything in one thread. But **BIRD 3 starts a
single worker unless the config asks for more**, so a 2.x-vs-3.x comparison without `--threads`
measures BIRD 3 pretending to be BIRD 2. Measured on 3.3.2: 2 OS threads by default, 5 with
`threads 4`. BIRD 2.19.2 parses the keyword and ignores it, staying at 1 — so a batch config can
set it for both.

```bash
./bgperf2.py bench -t bird --version 3.3.2 --threads 4 -n 10 -p 100000
```

```YAML
      - name: bird
        version: 2.19.2
        label: bird 2 (single-threaded)
      - name: bird
        version: 3.3.2
        threads: 4
        label: bird 3 (4 threads)
```

`--threads` is ignored by daemons with no such setting.

#### When an old version will not build

Build instructions drift: the base distro moves on, dependencies get renamed, configure flags come
and go. Two levels of override, cheapest first.

For a different *value* — base image, extra packages, configure flags — add a rule to the daemon
class's `VERSION_BUILD_VARS`, keyed by version prefix:

```python
class FRRoutingCompiled(Container):
    VERSION_BUILD_VARS = (
        ('8.', {'ubuntu_version': '20.04', 'extra_setup': 'apt-get install -y libyang-dev'}),
    )
```

For a genuinely different recipe, drop a whole Dockerfile in
`dockerfiles/<name>/<version>.dockerfile` (see `dockerfiles/README.md`). The longest matching
version prefix wins, so `10.dockerfile` covers the whole 10.x series.

Either way, check the result without paying for a build:

```bash
./bgperf2.py dockerfile frr_c --version 8.0
```

<a name="workload"></a>
### Workload controls beyond peers and prefixes

`-n` and `-p` scale one axis: each peer gets its own disjoint prefix block, so
session count and table size move together and the target holds `n * p`
routes, each learned over exactly one path. Five flags separate the things
that hides. Each is also a batch key -- a *test* key, beside `neighbors` and
`prefixes`, not a target key -- and each is refused rather than approximated
where it cannot be honoured.

| flag | batch key | what it adds |
|---|---|---|
| `--prefix-scope total` | `prefix_scope: total` | reads `-p` as the whole table and splits it across the peers, so peer count can rise without the table rising with it |
| `--path-diversity D` | `path_diversity: D` | deals the peers into groups of `D` sharing one prefix block, so the target has competing paths to choose between |
| `--receivers N` | `receivers: N` | `N` extra sessions the target exports its whole table to and which announce nothing back |
| `--churn-prefixes C --churn-bursts B` | `churn_prefixes` / `churn_bursts` | after convergence, withdraws and re-announces the last `C` prefixes of every peer, `B` times |
| `--policy-reload-blocks N` | `policy_reload_blocks: N` | after convergence, installs an import policy rejecting `N` prefix blocks and applies it with the daemon's own reload command |

```bash
# 50 sessions holding the same 100,000 routes, not 5,000,000
./bgperf2.py bench -t bird -n 50 -p 100000 --prefix-scope total

# 10 peers in pairs, so 500,000 paths compete for 250,000 prefixes
./bgperf2.py bench -t bird -n 10 -p 50000 --path-diversity 2

# one table, twelve export sessions
./bgperf2.py bench -t bird -n 10 -p 100000 --receivers 11

# move a converged table: withdraw 1,000 prefixes per peer and put them back, 3 times
./bgperf2.py bench -t bird -n 10 -p 100000 --churn-prefixes 1000 --churn-bursts 3

# change the policy over a converged table
./bgperf2.py bench -t bird -n 10 -p 100000 --policy-reload-blocks 2
```

What each refuses, and why, is worth knowing before a batch fails at cell
three: `--prefix-scope total` needs the peer count to divide the table exactly
and is refused for the MRT generators (whose check-point is already the whole
table); `--path-diversity` needs the diversity to divide the peer count
exactly and is refused for MRT playback and beside `--prefix-scope total`;
churn works only with the synthetic BIRD generator (the burst is `birdc`
switching a static protocol) and is refused under `-r/--repeat` and
`--filter_test`; the policy reload needs a target with a reload mechanism
(only BIRD today), and is refused for MRT playback, under `-r`, under
`--filter_test`, and beside churn. Every one of them is also refused for a `-f` scenario file,
which states its own paths. A batch is checked against **every** combination
on its axes before the first container starts, not just the first.

**None of these appear in the CSV.** `elapsed (s)` keeps meaning the monitor's
convergence in every row. What a workload was is in the artifact filename
(`pd2`, `rx11`, `ch1000x3`, `pr2`) and in the `run` block of both
`<prefix>.events.json` and `<prefix>.versions.json`; what it cost is in that
artifact's own section — `export`, `churn`, `policy_reload`. The
[measurement dictionary](docs/measurement-dictionary.md) lists the fields.

### Asking whether the generator was blocked

`--tester-trace-io` turns on the generator's own blocked-write reporting. Only bgpdump2 has any:
it logs `Partial write` when the socket took part of a buffer and refused the rest, and `Write
buffer full` when an encode pass found no room in its 256KB session buffer — which is also the
only place a `write()` that returned `EAGAIN` ever appears, since bgpdump2 logs nothing for one.
The counts reach `<prefix>.events.json` as `max_blocked_writes` and `max_send_stalls` under each
generator's `backpressure`; without the flag that section says `available: false` with a reason,
because reporting 0 would claim the generator was never blocked on the strength of lines it was
never told to write.

**It costs the measurement beside it, so leave it off for timing runs.** bgpdump2's IO log class
also logs every BGP message the injector *receives*, and the target re-advertises to each tester
what it learns from the others. Those lines land in the blaster's event loop while it is still
walking, so they lengthen the walk it is timing — and that walk time is published as
`reported_injection_s`, the only number that resolves an injection shorter than one poll. Measured
over three runs each, 2 injectors x 10,000 prefixes: the injector whose walk overlapped the echo
reported 0.01122 / 0.01128 / 0.01125s without the flag and 0.01763 / 0.01756 / 0.01751s with it,
and its log grew from 947 bytes to 350 KB. That growth scales with the table, so on a large run
keep `-d` off tmpfs — a bench directory in RAM is already measured by the `min free mem` column.

It also costs the *polled* injection interval. The log reader consumes at most 4 MB per poll, sized
for the ~1 KB an untraced injector writes, so a traced injector can write its `End-of-RIB` several
polls before the controller reads it and `tester_complete` is stamped late. Measured on a traced
2 x 500,000-prefix run: one injector wrote 22.5 MB before its `End-of-RIB`, and `injection_s` read
5.0s against the generator's own 1.4996s. **`injection_s` is not comparable across this flag** —
read `reported_injection_s` for a traced run, and do not put traced and untraced runs in the same
comparison.

### <a name="mrt"></a>Getting an MRT table

MRT playback needs the bgpdump2 image: `./bgperf2.py prepare -t bgpdump2`.
Select and record an MRT file explicitly. For example, this dated dump can be
downloaded into the ignored `mrt/` directory:

```bash
mkdir -p mrt
curl -o mrt/rib.bz2 \
  https://archive.routeviews.org/route-views2/bgpdata/2026.08/RIBS/rib.20260808.0000.bz2
bunzip2 mrt/rib.bz2 && mv mrt/rib mrt/rib.20260808.0000
```

RouteViews posts a RIB dump every two hours under `<year>.<month>/RIBS/`. They
are about 80 MB compressed and 1.3 GB expanded. To see what a table actually
holds before benchmarking against it — `bench` exits if no peer has as many
prefixes as you asked for:

```bash
docker run --rm --entrypoint= -v $PWD/mrt/rib.20260808.0000:/root/mrt_file \
    bgperf/bgpdump2 /usr/local/sbin/bgpdump2 -c /root/mrt_file
```

That prints a per-peer prefix count. The 2026-08-08 table has 28 peers, 17 of
them carrying a full ~1.05M-prefix table, which is what makes
`prefixes: [1_050_000]` across 10 peers possible.

### Commercial stacks

bgperf2 was originally created to test open source bgp software, so for most containers it compiles the software
and creates a container. For commercial NOSes this doesn't make sense. For those you will need to download
the container images manually and then use bgperf2.

For most of these images, bgperf2 mounts a local directory (usually in /var/tmp/bgperf2) to the container. These
commercial stacks then write back data as root, and set the privileges so that a regular user cannot delete these
files and directories.

bgperf2 tries to delete /var/tmp/bgperf2 before it runs, but it can't with data from these stacks, so you
might need to remove them yourself. The other option is to run bgperf2 as root \<shrugs\>, that's not a good idea.

```
sudo rm -rf /var/tmp/bgperf2
```

I have setup multi-threaded support by default in both of these. If you want to do uni-threaded performance
testing you will have to edit config files, which is documented below.

**Warning** The license for these stacks prohibits publishing results. Don't publish results.

#### Arista cEOS

[cEOS overview](https://www.arista.com/en/products/software-controlled-container-networking)

To download, after getting an account: https://www.arista.com/en/support/software-download. Make sure you get the cEOS64
image. I didn't the first time, and the results are frustratingly slow. After downloading:

``` bash
$ docker import ../NOS/cEOS64-lab-4.27.0F.tar.xz ceos:latest
```

Be sure to use this command for importing: if you don't tag the image as ceos:latest then bgperf2
won't be able to find the image.

N.B. EOS takes longer to startup than other BGP software I've tested with bgperf2, so don't be alarmed.
However, if it's taken more than 60 seconds to establish a neighbor, something is wrong and start 
looking at logs.

EOS has less clear directions on how to setup multithreading and the consequences. I can't find an authoritative doc to point to.

However, if you want to remove multi-threading support, remove this line from nos_templates/eos.j2

```bash
service routing protocols model multi-agent
```

There is no way to adjust the number of threads being used. For cEOS it appears to be hardcoded
no matter the hardware that you have.

#### Juniper cRPD

[Junos cRPD deployment guide](https://www.juniper.net/documentation/us/en/software/crpd/crpd-deployment/index.html)


Download the image to your local machine and then run:

``` bash
$ docker load -i ../NOS/junos-routing-crpd-docker-21.3R1-S1.1.tgz
$ docker tag crpd:21.3R1-S1.1 crpd:latest
```

Be sure you tag the image or bgperf2 cannot find the image and everything will fail.

bgperf2 mounts the log directory as /var/tmp/bgperf2/junos/logs, however there are a lot there and most of it
is not relevant. To see if your config worked correctly on startup:

``` bash
$ docker logs bgperf_junos_target
 ```

[Deploying BGP RIB Sharding and Update Threading](https://www.juniper.net/documentation/en_US/day-one-books/DO_BGPSharding.pdf) -- while informative it's weird to me that it's 2021 and getting multi-threaded performance requires a 40 page document. How am I not supposed to think that networking is two decades behind everybody else in software? (This isn't just a Juniper problem by any means)

For multithreading, as mentioned above bgperf2 sets this up by default in nos_templates/junos.j2

``` bash
processes {
        routing {
            bgp {
                rib-sharding {
                    number-of-shards {{ data.cores }};
                }
                update-threading {
                    number-of-threads {{ data.cores }};
                }
            }
        }       
    }
```

data.cores is set in junos.py and by default it's half the number of available cores on the test machine, 
with a max of 31, since that is the Junos max. If you want to try setting the threads to something different
you can hard code those values. If you want to see without multi-threading, delete that whole section.

#### Nokia SR Linux

Pulled rather than built: `docker pull ghcr.io/nokia/srlinux:<version>`, then
`-t srlinux --version <version>`. The same licence caution applies.

## <a name="debugging"></a>Debugging

Start with one peer and one route: `./bgperf2.py bench -n1 -p1`. If it stalls
waiting for a neighbor, the generated config for the target is usually wrong.

Each run writes its configs, startup scripts and logs under
`<--dir>/<--bench-name>/` — `/var/tmp/bgperf2/` by default — one subdirectory
per role, bind-mounted into the containers. The containers are named
`bgperf_<daemon>_target` (for example `bgperf_bird_target`,
`bgperf_frrouting_target`), `bgperf_monitor`, `bgperf_bird_tester_<n>` or
`bgperf_bgpdump2_tester_<n>` for the generators, and `bgperf_receiver<n>`. The sink monitor writes
every session event to `monitor/sink.log`, which is the first thing to read;
under `--monitor gobgp` query the monitor with `docker exec bgperf_monitor gobgp
neighbor`.

The target's startup script is copied in as `/root/config/start.sh`. Running it
by hand after a run shows the output bgperf2 does not capture:

```bash
docker exec bgperf_bird_target /root/config/start.sh
docker exec bgperf_bird_target ps auxww        # e.g. find and kill an old daemon first
```

bgperf2 removes its own containers at the start of each run. To clear them by
hand without touching anything else on the host:

```bash
docker rm -f $(docker ps -aq --filter name=bgperf_)
```

The commercial images write their bind-mounted files as root; if bgperf2 cannot
clean up, `sudo rm -rf /var/tmp/bgperf2`.

## Tests

The test suite needs no Docker and no privileges:

```bash
python3.14 scripts/bootstrap.py --check
venv/bin/python -m pytest tests/ -q
```

It covers the measurement, parsing and batch layers; a real `bench` is the only
end-to-end check.

## Development

The [public roadmap](docs/roadmap.md) indexes current priorities, detailed plans
and deferred workload ideas. Engine plans and implementation decisions live in
this repository. Proposed capabilities are labelled separately from supported
commands; no other project or private repository is needed to use or contribute
to bgperf2. Read [contributor/agent guidance](CLAUDE.md) before changes.

## History

bgperf2 was forked from osrg/bgperf when none of its containers built any more,
and was ported to Python 3 and current daemon releases. FRR is now compiled
from source as `frr_c`, choosing the version; the old prebuilt `frr` target
(pinned to 7.5.1), Quagga, and GoBGP as a target and MRT injector have been
removed. Policy beyond the configurations exercised here, and remote targets,
are less tested.

The [Python environment guide](docs/python-environment.md) documents the full
hashed lock, verification and dependency updates.
