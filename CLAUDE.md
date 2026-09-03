# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.


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
  with the table and therefore lands in `min free mem` on a default `-d /tmp`.
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

### The bench directory is in RAM by default

`-d/--dir` defaults to `/tmp`, which is tmpfs on most systemd distros, and every role's config and
logs are bind-mounted under it. A 50-peer 100k-prefix BIRD run wrote **31GB** of tester logs there
— half this machine's RAM — pulling the recorded `min free mem` from 56GB to **28.5GB** on a run
whose target daemon used **0.56GB**. A published, graphed column was measuring tester logging.
`warn_if_log_dir_is_in_ram()` says so at the start of a run; `is_memory_backed()` in
`contention.py` is the pure part.

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
like any other daemon. These write root-owned files into `/tmp/bgperf2`, which bgperf2 then cannot
clean up; `sudo rm -rf /tmp/bgperf2` when that happens. Their licenses prohibit publishing results.

## Conventions

### 2026 benchmark campaign operator contract

When the user says `continue the 2026 benchmark campaign`, use these fixed defaults unless durable run metadata
already records different values:

- run ID: `2026-baseline`
- results root: `results/2026`
- work directory: `/var/tmp/bgperf`

Inspect `COMPLETE` markers, progress JSON, CSV rows, logs, and active benchmark processes first. Never run suites
concurrently. Monitor an active suite or resume an interrupted one; otherwise run exactly one suite with
`scripts/run_2026_suite.sh next --run-id 2026-baseline --workdir /var/tmp/bgperf`. Review it for failed rows,
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

### 64 GB timing validation campaign operator contract

When the user says `continue the 64 GB timing validation campaign`, follow
[`docs/2026-64gb-timing-validation-plan.md`](docs/2026-64gb-timing-validation-plan.md) with run ID
`2026-timing-validation`, results root `results/2026`, and work directory `/var/tmp/bgperf`. Verify the measurement
release gate first. Never run cells or blocks concurrently. Monitor or resume an active block; otherwise run exactly
one next block, review timing evidence, correctness, provenance, contention, and memory, then stop at the reviewed
block boundary. The local 64 GB host is a hard ceiling; do not schedule a larger-memory workload.

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
