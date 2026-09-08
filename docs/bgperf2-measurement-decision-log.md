# bgperf2 Measurement Implementation Decision Log

Why each change in
[`bgperf2-measurement-implementation-plan.md`](bgperf2-measurement-implementation-plan.md)
was made the way it was, what was measured to decide it, and what the Docker
verification showed. One section per phase, in the order the entries were
written.

This is the durable half of that plan. The plan says what is left to do and
what each phase must satisfy; this says what was already settled and on what
evidence, so a later change set argues with the measurement rather than
re-running it. Several entries exist specifically because the first version of
a change was wrong -- a bound on an interval nobody measured, a poll resolution
that understated itself, a guard that refused on one path while another
accepted silently. Those are the entries worth reading before touching the
thing they describe.

Entries are append-only. Correcting one means adding what was found and why the
earlier reading was wrong, not editing the earlier reading away: the record of
having been wrong is the part that stops it happening twice.

## Phase 2: Instrument the BIRD synthetic tester

Four things the wiring had to get right:

- **A BIRD tester runs one `bird` per peer, each on its own control socket.**
  `BIRDTester.get_startup_cmd()` launches `bird -c <guest_dir>/<router-id>.conf
  -s <guest_dir>/<router-id>.ctl` per neighbour, so a bare `birdc` inside a
  tester container reaches no daemon at all. `get_offerings()` names every
  socket and passes the results as one `TesterEventRecorder.observe()` call.
- **One `docker exec` per poll, not one per peer.** Every socket is read in a
  single `sh -c` loop whose sections are separated by `bird.SESSION_MARKER`,
  because an exec is ~50ms: at 50 peers a per-peer poll cannot keep up with a
  1s cadence and the controller becomes contention the run then reports as
  someone else's.
- **Every configured peer must appear in every poll**, with `offered=None` where
  the read failed. `observe()` rejects a poll whose session keys differ from the
  first one, because dropping a key would let `all(complete)` be satisfied by
  the peers that happen to remain.
- **`expected` comes from the scenario config**, `len(p['paths'])`, not from
  `tester_offering()['configured']`. The latter is the generator's own report of
  what it loaded and is a cross-check; using it as the yardstick would make a
  generator that loaded half its config look complete.

Three findings worth carrying forward:

- BIRD 3 inserts `RX limit` and `limit` columns into the route-change-stats
  table, so the column that is `accepted` on 2.19 is `RX limit` on 3.3.2. Read
  these tables by name; a positional read returns a plausible wrong number.
- Blocked-write evidence is version-dependent. BIRD 3 reports `TX pending: N
  bytes` and `Pending N attribute sets with total M prefixes to send`; 2.19 has
  neither. The synthetic tester runs the unversioned `bgperf/bird` image, which
  is 2.19, so backpressure is recorded as unavailable-with-a-reason rather than
  as zero.

- **BIRD 2.19's offered counter is queue-side, and saturates.** `Export
  updates accepted` counts a route when it is handed to the BGP protocol, not
  when it reaches the wire. In the 4-peer x 250k Docker verification the
  generator reported all 1,000,000 prefixes offered at 1.94s, while the monitor
  had seen 215,552 and the target itself held full tables from only 2 of the 4
  peers. So the *count* is exact and completion is positively observed, but the
  injection *duration* is not resolvable from this counter: repeated runs put
  between 0 and 153,744 of the million inside the measured interval purely
  according to where the first poll landed. Polling at 0.2s did not fix it, it
  made it worse — it reported a confident `21452 prefixes/s` that was the slope
  of the last 6,436 prefixes. `tester_metrics()` therefore publishes
  `offered_in_interval` beside `offered_rate_pps`, so a tail slope cannot be
  read as a send rate, and Phase 4 must not derive a tester-limited finding
  from a BIRD 2.19 rate. Wire-side evidence needs BIRD 3's `TX pending`, which
  means running the generator on `bgperf/bird:3.3.2`; the tester image is not
  selectable from the CLI today.

### Docker verification

Run on 2026-09-02 on an 8-core / 30 GB host (not the 64 GB campaign host), with
`-d /var/tmp/bgperf` and results outside the campaign tree: `bench -t bird -n 1
-p 50000` and `bench -t bird -n 4 -p 250000`. Both reported the exact expected
offered count (50,000 and 1,000,000) from the generator's own CLI, an observed
`tester_complete` for every session, `tester_startup_s` of 1.1s and 1.9s, and
backpressure recorded as unavailable-with-a-reason on 2.19. No tester errors or
timeouts; foreign CPU 4-7%.

Review raised one contention question worth recording: the poll runs `sh -c`
inside the tester, and `sh` is deliberately absent from
`contention.BGPERF_PROCESSES` (interpreters are excluded because
`/proc/<pid>/comm` for a script-driven neighbour workload *is* the interpreter),
so a first-seen shell would be charged as foreign CPU. Measured rather than
argued: 46 polls in a 10s window — 5x the production rate — put zero `sh` or
`birdc` processes in either `/proc` sample and contributed 0.0% to
`foreign_cpu_percent`. The shell forks `birdc` and waits, so its own CPU is
nil and it is too short-lived to be sampled. Left as it is; allowlisting `sh`
would reopen the hole that made the whole feature report a clean machine while
a neighbouring `python3 train.py` used eight cores.

### Defect found while instrumenting: BIRD 3 targets reported accepted = 0

Fixed on 2026-09-02, and `bird.tfsm` is deleted.

`bird.tfsm` read the `Import updates` row positionally
(`${received}\s+\S+\s+\S+\s+\S+\s+${accepted}`) — the same column shift
described above. So for any BIRD 3 target `neighbors_accepted` was always 0,
`neighbors_checked` never went all-True, and that route to
`note_neighbors_checkpoint()` in `bench()` was dead for half the BIRD matrix.
Runs still converged through `neighbors_received_full` (the `received` capture
read column 1 and was correct), which is why it stayed hidden: only the
per-second progress line looked wrong.

`BIRDTarget.get_neighbors_state()` now reads `bird.parse_protocols()`. Verified
on live output from both series, 3 peers x 200 prefixes:

| target | old template (accepted) | new parser (accepted) |
|---|---|---|
| bird 2.19 | 200, 200, 200 | 200, 200, 200 |
| bird 3.3.2 | 0, 0, 0 | 200, 200, 200 |

BIRD 2 is unchanged; BIRD 3 now reaches the neighbor checkpoint. This was a
prerequisite for meaningful BIRD 2 vs 3 comparison in Phase 5A.

## Phase 3: Instrument bgpdump2 MRT playback

### Progress on 2026-09-03: the injector log was empty, and now is not

`bgpdump2 --blaster` logs to stdout, which `start.sh` redirects into the
bind-mounted `bgpdump2.log`. Redirected stdout is block-buffered and nothing
ends the process but the container teardown, so **a converged two-injector run
left both logs at exactly 0 bytes** while the blaster was still running with its
walk finished. Every fact this phase needs was being written into a buffer no
one read. `start.sh` now runs the blaster under `stdbuf -oL -eL`; the same run
then produced complete logs for both injectors.

`bgpdump2.parse_blaster_log()` and `bgpdump2.tester_offering()` read that log,
covered against the two real captures in `tests/fixtures/bgpdump2_blaster*.log`
(2 injectors x 10,000 prefixes against a BIRD target). Earlier polls are modelled
by truncating those captures, including mid-line, since an incremental reader
meets exactly that.

Four things this settled:

- **Completion is the injector's own report, and it cannot be a count.** `-T`
  caps the table while the MRT file is read, so an injector holds whatever that
  MRT peer's table has; `offered >= expected` can stay false forever on an
  injector that has sent everything it holds. `measurements.TesterOffering`
  gained `send_complete` for a generator's own statement, and it decides
  completion in both directions — a generator that says it has not finished is
  not overruled by a count that reached `expected`. BIRD passes `None` and
  keeps the count-based rule. The signal is the `End-of-RIB` line rather than
  the `RIB walk complete` marker that precedes it: the marker is logged before
  the final `Sent ...` counters, so completing on it carries mid-walk counts,
  and in one capture it precedes the first `Sent` line entirely. That second
  case is refused twice over — `TesterEventRecorder` now holds
  `tester_complete` until an update has been observed, since a completion
  sorted ahead of `tester_first_update` makes `tester_metrics()` raise out of
  `finish_bench()` and kill a converged run.
- **Prefix counts are encode-side; the octet count is wire-side.** `prefixes
  sent` increments as prefixes are encoded into the 256KB session write buffer,
  `octets` only on a successful `write()`. A captured mid-walk line reads
  `Sent 2280 updates, 9981 prefixes sent, 0 prefixes withdrawn, 88 octets`. The
  BIRD 2.19 queue-side caveat applies to the prefix counts, with one wire-side
  number beside them.
- **`End-of-RIB, walk time` is the generator's own playback measurement**, and
  it resolves what the poll cadence cannot: one injector's entire 10,000-prefix
  walk took 1.03ms. It times one RIB, so it is published only for a single-RIB
  session; summing sequential walks would drop the gaps between them.
- The log's timestamps are local wall-clock with no year or zone, so they are
  parsed for nothing. Durations stay on the controller's monotonic clock.

Review of this change set also found a Phase 2 defect, fixed here:
`BIRDTester.get_offerings()` caught every exception from its `docker exec` and
read the failure as an empty capture, so `offering_stats()`'s
`tester_offering_error` path — and the artifact's `read_failures` evidence —
could never fire for the only generator that had one. A run whose polls all
failed produced the same artifact as a run whose generator never came up.

### Progress on 2026-09-03: every injector now reports into the event stream

`Bgpdump2Tester` declares `REPORTS_OFFERING`, so the generic `bench()` poll
covers it: each injector gets its own `TesterEventRecorder`, and its
`tester_session_ready`/`tester_first_update`/`tester_last_update`/
`tester_complete` are merged into the one ordered `<prefix>.events.json` under
its container name, with the derived intervals beside them. No injector speaks
for another -- there is one producer per container and no aggregate, so a
missing completion stays visible as that injector's missing completion.

Three things this change set had to get right:

- **No `docker exec` at all.** The blaster's log is bind-mounted, so
  `BlasterLogReader` reads it from the host. Ten injectors polled once a second
  through `exec` would put the controller's own cost into the run it is
  measuring, which is what the BIRD poll's single-exec loop exists to avoid.
- **The read is incremental**, keeping a byte offset and stopping at the last
  complete line, for the reason `frr._get_EOR_from_log()` does: bgpdump2 logs a
  `Sent ...` line per `write()` to the socket, and a write carries whatever the
  socket would take -- one capture shows an 88-octet write -- so the line count
  is a property of how the peer drained the session and nothing bounds it in
  advance. `BlasterLog` accumulates facts across polls rather than reparsing,
  because `End-of-RIB` belongs to a `RIB for peer-index` line that arrived
  polls earlier and chunk-at-a-time parsing would drop the walk time it
  carries.
- **An unreadable log raises rather than reading as an empty one.** The log is
  the injector's only account of itself, so failing to read it is 'the
  generator could not be asked' -- `offering_stats()` records that as
  `read_failures` in the artifact, which is the distinction a silent empty
  reading would erase.

The poll names the single session `get_startup_cmd()` actually drives, from the
same `injected_neighbor()`, and `expected` is the configured `count`, never the
RIB size the log reports.

#### Docker verification

Run on 2026-09-03 on the 8-core / 30 GB host, `-d /var/tmp/bgperf` with results
outside the campaign tree: `bench -t bird -g bgpdump2 -n 2 -p 10000 --mrt-file
mrt/rib.20210801.0000`. Both injectors appear in `<prefix>.events.json` with all
four tester events, the exact expected 10,000 offered prefixes, `configured`
matching, `tester_startup_s` 1.33s, and backpressure recorded as
unavailable-with-a-reason. No read failures, no tester errors or timeouts,
foreign CPU 4%.

It also showed the measurement's own limit plainly: the walk takes about a
millisecond, so both injectors had finished before the first poll looked.
`injection_s` is 0.0 with `offered_in_interval` 0 and no rate, and the run
prints `injection shorter than one poll` -- the same unresolvable-injection
shape as BIRD 2.19, refusing to publish an instant injection. The generator's
own `End-of-RIB, walk time` (0.000995s) is the number that would resolve it,
and it is parsed but not yet carried into the artifact.

#### Progress on 2026-09-03: the published poll resolution is now the achieved one

Found by review of the change set above, in Phase 2 code.
`Tester.offering_stats()` stamped a sample before the read but then waited a
full `interval` *after* it, so the cadence achieved was `read + interval` while
every event the recorder published carried `sample_interval_s = 1` as its stated
resolution. That field exists precisely so an `injection_s` of 0.0 reads as
*unresolved at this resolution* rather than as instant, so understating it by
the read time weakened the one number that qualifies the others.

Both halves are fixed:

- **The poll waits to a deadline measured from the sample**, not a fixed
  interval piled on top of the read. A read that overruns the interval keeps
  the full wait rather than polling back-to-back: chasing the deadline there
  would leave the controller inside a container continuously, which is the
  contention the run would then report as someone else's.
- **The resolution is derived from the sample timestamps rather than assumed.**
  `TesterEventRecorder` already tracked them, so no new plumbing was needed: an
  event is dated to the poll that saw it, and its timestamp is known only to
  within the gap since the previous look. Every event now carries
  `poll_resolution_s` beside the nominal `sample_interval_s`, and
  `tester_metrics()` publishes `startup_resolution_s` and
  `injection_resolution_s` from the polls that bound each of those intervals.
  `print_tester_metrics()` names the injection one: `injection shorter than the
  2.4s poll resolution`, not `shorter than one poll`.
- **One resolution cannot bound two intervals**, which review of this change
  set caught before it was committed. A first version published a single
  number, the worst across all three endpoints. But `tester_session_ready` is
  routinely found on the very first poll, and that poll's resolution is the
  whole interval since the clock started -- the origin is stamped before the
  testers are launched. On the ordinary BIRD shape (sessions up with `Export
  updates accepted` still 0, first update and completion two polls later) that
  published `injection shorter than the 30.0s poll resolution` for an injection
  bracketed by two polls 1.0s apart, overstating the uncertainty exactly as
  badly as the nominal cadence understated it.

Two properties are deliberate. **On the first poll the gap is measured from the
bench clock origin**, because everything the generator did before the instrument
arrived is invisible -- which is exactly the bgpdump2 case, where a 1ms walk
puts `tester_first_update` and `tester_complete` on the same first poll. And the
requested cadence is a **floor**: the loop stamps, reads, then waits, so it
cannot look twice inside one interval, and a stream that appears to is reported
at the cadence asked for rather than at a sharpness no real poll has.

No Docker run was needed: the change is to the controller's own timing, and both
halves are covered by unit tests -- the loop's achieved cadence in
`tests/test_controller_threads.py`, the derived resolution in
`tests/test_tester_measurements.py`.

#### Progress on 2026-09-03: the generator's own two numbers reach the artifact

An injection that finished before the first poll looked was, until this change
set, published only as the fact that nothing could be said about it. bgpdump2
had already measured it and said so in its log, and that measurement was parsed
and then dropped on the floor.

`TesterOffering` gained `reported_send_duration_s` and `octets_on_wire`,
`Bgpdump2Tester.get_offerings()` fills both from the log it already reads, and
`tester_metrics()` publishes them as `reported_injection_s` and
`octets_on_wire`, read from the poll that observed completion.

Four decisions in it:

- **`reported_injection_s` sits beside `injection_s`, never in place of it.**
  It is a different clock and the generator's own definition of sending —
  bgpdump2's walk time is encode time bounded by its 256KB write buffer, so on
  a table large enough to fill that buffer it tracks the wire and on a small
  one it does not. `print_tester_metrics()` names both bounds in one line:
  `injection shorter than the 1.0s poll resolution; the generator measured its
  own send at 0.001017s`.
- **No rate is derived from it.** Dividing an encode-side count by an
  encode-side interval yields a send rate the generator never achieved —
  10,000 prefixes over 1.017ms would publish 9.8M prefixes/s. This is the same
  trap `offered_in_interval` exists to keep the polled rate out of.
- **The octet count is read at completion**, which is the poll whose
  `offered_prefixes` it pairs with: both come off the same line of the
  generator's counters, one encode-side and one wire-side. The real captures
  show why the pair is worth having — a mid-walk line reads 9,981 prefixes
  encoded against 88 octets written.
- **Neither is published from only some of a container's sessions.** Octets are
  summed under the same all-or-nothing rule as the prefix counts, because a
  total covering only the sessions that answered reads as a small transfer
  rather than as a partial reading. Durations are not summed at all — sessions
  send at the same time — so the longest is taken, matching how this recorder
  aggregates everything else, and it stays a lower bound on the container's
  whole send span. Review of this change set caught that rule holding within
  one poll but not across polls: the duration is held on the recorder so the
  completion event can carry it, and a value that merely persisted from an
  earlier, fully legible look would be published against a poll that could not
  read it. It is now rebuilt every poll, cleared included, so one event never
  carries two polls' evidence.

##### Docker verification

Run on 2026-09-03 on the 8-core / 30 GB host, `-d /var/tmp/bgperf` with results
outside the campaign tree: `bench -t bird -g bgpdump2 -n 2 -p 10000 --mrt-file
mrt/rib.20210801.0000`. Converged in 3s. Both injectors carry
`reported_injection_s` (0.001017s and 0.011280s) and `octets_on_wire` (183,852
and 259,226) in `<prefix>.events.json`, on both the `tester_complete` event and
the derived `testers` section, with `injection_s` still an honest 0.0 at a
1.0001s achieved poll resolution. The two byte counts differ by 41% for
identical prefix counts, which is the point of a wire-side number: it is a
property of the paths played back, not of the table size. No read failures, no
tester errors or timeouts, foreign CPU 4%.

Left for the next change sets in this phase: an aggregate across injectors that
cannot let the fastest speak for the rest, and blocked-write evidence -- both
done below.


### Progress on 2026-09-03: the injector now says which build it is

`Bgpdump2` gained a version command, so the `tester version` column and the
`.versions.json` manifest record `2.0.14 (a019184)` instead of `UNKNOWN (no
version command for Bgpdump2Tester)`.

The version alone would not have been identity. bgpdump2 reports `Version:
2.0.14` and has for every master commit this project has built, so two images
compiled months apart are indistinguishable by it -- the gcov trap one layer up,
where a cached image keeps an older build and nothing in the results shows it.
The commit is what separates them.

Three decisions in it:

- **The commit is read from the running container, not baked into the recipe.**
  The image still carries the clone it compiled at `/root/bgpdump2`, so a
  version command can ask it. Adding a build-time label would have been the
  obvious move and the wrong one: `prepare` skips a tag that already exists, so
  a recipe change is absent from every image already built -- exactly the
  failure this is meant to close. Reading the clone identifies the images that
  exist today, including the one this host has been benching with.
- **A missing clone is reported, not omitted.** An image whose clone was pruned
  reports `2.0.14 (commit unknown)`; dropping the parenthesis would leave a
  string that looks pinned and is not.
- **No banner means no version.** The command is two commands in one shell, so a
  missing binary still produces the second half's output. The parser matches the
  banner and raises `VersionUnavailable` otherwise, rather than recording
  whatever came back -- the failure that put the word `exec` in the published
  baseline as a BIRD version.

`Bgpdump2.DAEMON_BINARY` is set in the same change set, so `verify` runs its
gcov check on the generator too. An instrumented blaster sends more slowly than
a clean one, and a run would publish that as the target's convergence time --
the same defect that made every FRR result incomparable, on the other side of
the wire.

#### Docker verification

`verify -t bgpdump2` on the 8-core / 30 GB host: `tester version: 2.0.14
(a019184)`, `tester instrumentation: clean`, exit 0. The image predates this
change set, which is the point -- its identity was recoverable without a
rebuild.

A real run confirmed it reaches the results, since `verify` probes a throwaway
container rather than a busy injector: `bench -t bird -g bgpdump2 -n 2 -p 10000
--mrt-file mrt/rib.20210801.0000`, `-d /var/tmp/bgperf` with results outside the
campaign tree. Converged in 3s; the CSV row's `tester version` and the
`.versions.json` testers entry both read `2.0.14 (a019184)` against
`bgperf/bgpdump2:latest`, in place of the `UNKNOWN` every earlier MRT run
recorded. No tester errors or timeouts, foreign CPU 4%.

Still open for the exabgp pair, which implements no version command at all and
is unpinned at both layers.

### Progress on 2026-09-03: one line for whether the fleet delivered the load

A full-internet run drives ten injector containers, and until this change set
the only account of them was ten per-generator sections. Reading "was the
workload offered?" off ten sections means noticing the one with a null
interval, which is the line a reader skims.

`measurements.tester_fleet_metrics()` summarises them into one
`tester_fleet` section beside the per-generator ones, and
`print_tester_fleet_metrics()` prints one line beside the per-generator lines.
Every aggregate is taken the way `TesterEventRecorder` already combines the
sessions inside one container: the fleet is ready when its **last** generator
is ready, its injection runs from the **earliest** first update to the
**slowest** completion, and completion is all-or-nothing.

Four rules in it:

- **One generator that never completed leaves the fleet unmeasured and named.**
  `incomplete_testers` carries it and `injection_s` stays None. An interval
  bounded by the nine that did finish would describe a workload that was never
  fully offered, and it would look entirely ordinary. The count is refused for
  the same reason: 90,000 of an expected 100,000 reads as a workload 10% short
  rather than as an injector nobody could ask.
- **Durations are not summed and rates are not added.** The injectors send at
  the same time, so summing their intervals totals time nobody spent sending.
  The rate divides the prefixes measured crossing the fleet span by that span,
  which makes it lower than any single generator's slope -- the conservative
  direction, and the only one an aggregate can take. `reported_injection_s` is
  the longest of the generators' own measurements, not their sum, and stays a
  lower bound on the fleet's whole send span.
- **A span nothing crossed is not a rate of zero.** This is the *normal* MRT
  shape, not an edge case: each injector's sub-millisecond walk is over before
  its own first poll, so a span bounded by two injectors completing at
  different polls contains none of the table. The ten-injector verification
  below measured exactly that -- `injection_s` 1.0s with `offered_in_interval`
  0 -- and dividing would have published `0 prefixes/s` for ten injectors that
  delivered all 100,000 prefixes. The rule is shared with the per-generator
  metrics, where the same shape occurs every time a self-reporting generator's
  count goes final one poll before it says `End-of-RIB`; that case previously
  printed `0 prefixes/s` too. `print_tester_metrics()` no longer borrows the
  sub-poll wording for it either: "shorter than the 1.0s poll resolution" is
  true only when first update and completion shared a poll, and here they did
  not.
- **It is a summary of the sections, never a replacement.** The fleet says
  whether the workload was delivered; the per-generator sections say which
  generator was slow. The line is printed only when a run has more than one
  generator, since with one it would restate the line above it less precisely.

#### Docker verification

Run on 2026-09-03 on the 8-core / 30 GB host, `-d /var/tmp/bgperf` with results
outside the campaign tree: `bench -t bird -g bgpdump2 -n 10 -p 10000
--mrt-file mrt/rib.20210801.0000`. Converged in 4s. All ten injectors reported
completion -- `testers_complete: 10`, `incomplete_testers: []` -- with the
exact expected 100,000 offered prefixes and 2,214,093 wire-side octets summed
across them, `tester_startup_s` 3.26s (the last injector's readiness, not the
first's), and a fleet injection of 1.0s that the run correctly refused to turn
into a rate. `tester version` reads `2.0.14 (a019184)`. No read failures, no
tester errors or timeouts, foreign CPU 5%.

The remaining Phase 3 item is blocked-write evidence, done below.

### Progress on 2026-09-03: the poll stops asking a generator that has finished

Raised by review of the provenance change set, and belonging to the Phase 2
poll loop rather than to bgpdump2: `Tester.offering_stats()` polled until the
monitor converged, however long ago the generator had finished. That costs
nothing for bgpdump2, whose poll is a host-side file read, but a BIRD poll is a
`docker exec` running one `birdc` per configured peer, so a 50-100 peer run kept
spawning that many short-lived processes a second for the whole run with nothing
left to learn from them. `birdc` is in `contention.BGPERF_PROCESSES`, which
makes this the one load `max foreign cpu %` deliberately cannot see -- the
instrument's own overhead invisible in the column whose whole meaning is "0
means the machine was yours".

The loop now ends itself, and the rule is
`measurements.offering_poll_can_stop()` -- pure, beside the recorder whose
behaviour it has to match.

Three things it had to get right:

- **The stop rule is not `all(o.complete)`.** It is the exact condition under
  which `TesterEventRecorder.observe()` records `tester_complete` on that same
  poll, which additionally requires every session's count to be legible and
  their sum nonzero: the recorder holds completion until it has seen a
  `tester_first_update`, and a generator can report its own completion on a poll
  whose counters are not yet readable -- bgpdump2 logs `RIB walk complete`
  before its final `Sent ...` counters. Stopping there would take away the later
  poll that would have supplied the update and leave a converged run with a
  generator that never completed. A unit helper asserts the two agree on every
  case rather than trusting the two code paths to stay in step.
- **The sample is queued before the loop looks at it**, so the poll that ends
  the loop is the poll that carries the completion evidence.
- **Nothing observable is lost after completion.** `offered` is cumulative and
  the recorder already refuses to move it past completion, and blocked-write
  evidence is a maximum over polls that cannot grow afterwards -- a session's
  queue stops filling once the last update has been handed to it, so the poll
  that observes completion reads the largest queue there will be.

The test fake had to change with it: it reported a finished generator on its
first poll, which after this change would have made every shutdown test in
`tests/test_controller_threads.py` pass without testing a shutdown.

#### Docker verification

Two runs on the 8-core / 30 GB host, `-d /var/tmp/bgperf` with results outside
the campaign tree. The count is taken from `docker events --filter
event=exec_create`, which is the thing being removed; sampling `/proc` for
`birdc` finds nothing either way, because the process is too short-lived to be
caught -- the same reason `contention.py` cannot see it.

`bench -t bird -g bird -n 4 -p 50000`: converged in 3s with all four tester
events, the exact 200,000 offered, and backpressure unavailable-with-a-reason on
2.19. The monitor and target were exec'd once a second from t+0 to t+10; the
last exec into the tester was at **t+3**, one poll after the generator reported
its whole table. Before this change it would have been exec'd for the remaining
seven.

`bench -t bird -g bgpdump2 -n 2 -p 10000 --mrt-file mrt/rib.20210801.0000`:
converged in 3s, both injectors carrying all four events, the exact 10,000 each,
`reported_injection_s` 0.000969s and 0.011226s, and `octets_on_wire` 183,852 and
259,226 -- unchanged from the run before this change set, which is the point for
a generator whose poll was never the expensive kind. No read failures, no tester
errors or timeouts, foreign CPU 3% in both runs.

#### Also found by review of this change set: a bound on an interval nobody measured

`tester_metrics()` published `injection_resolution_s` from whichever bounding
poll it could find, so a generator that offered updates and then stalled --
`injection_s` null, no `tester_complete` -- carried a 1.0s bound on the
injection it never measured. `startup_resolution_s` already got this right, so
the two fields disagreed about their own contract, and a consumer keying on the
resolution would read a resolved interval that does not exist. The printed line
was unaffected: it handles a null `injection_s` before it reaches the
resolution. `_bounding_resolution()` now returns None unless every endpoint is
present. From the poll-resolution change set, not yet released.

### Progress on 2026-09-03: blocked writes, and what asking for them costs

The last open Phase 3 item. bgpdump2's IO log class is the only blocked-write
evidence it has, and it is now readable -- but behind `--tester-trace-io`,
because turning it on damages the measurement that sits beside it.

Two of the class's lines are backpressure and one is not:

- `Partial write N bytes buffer to <peer>` -- `write()` took part of the
  session buffer and the socket refused the rest.
- `Write buffer full` -- an encode pass found fewer than one maximum BGP
  message free in the 256KB session buffer and could encode nothing. This is
  also the only place a `write()` that returned `EAGAIN` ever appears:
  bgpdump2 logs nothing at all for one, so a session whose socket had stopped
  taking anything writes no `Partial write` line and shows up only here.
- `Full write N bytes` -- the ordinary case. It is counted only because seeing
  any of the three proves the class is enabled.

That last point is the design of it. `blocked_writes` and `send_stalls` are
absent, not zero, until the log itself proves the class was on -- a count of 0
from a run that never asked would report a generator as never blocked on the
strength of lines it was never told to write, which is the same failure the
BIRD 2.19 backpressure case exists to avoid. The evidence becomes available at
the session's OPEN, which is the first write there is, so the distinction
resolves itself before there is anything to be blocked about.
`TesterOffering` gained both fields, and `TesterEventRecorder` keeps each as a
maximum over sessions as well as polls -- the most-blocked session, never a sum
across them, which is what lets the number stay an honest lower bound when one
session could not be read.

**Why it is not the default, measured rather than argued.** `-t io` also logs
one line per BGP message *received*, and the target re-advertises to each
tester what it learns from the others. Those lines arrive in the blaster's
event loop while it is still walking, so they lengthen the walk it is timing --
and that walk time is published as `reported_injection_s`, the only number that
says anything at all about an injection shorter than one poll. Three runs each
of `bench -t bird -g bgpdump2 -n 2 -p 10000`, on the injector whose walk
overlapped the echo:

| | walk time | its log |
|---|---|---|
| without `-t io` | 0.011217s, 0.011280s, 0.011252s | 947 bytes |
| with `-t io` | 0.017634s, 0.017556s, 0.017508s | 350 KB |

A reproducible 56% inflation with no overlap between the two sets, and 370x the
log volume -- on a run whose per-injector table is 10,000 prefixes. The
injector whose whole walk finished before the echo began was unaffected
(0.00095-0.00103s either way), which is the mechanism confirming itself. So a
run that wants to know whether the generator was blocked asks for it and reads
a perturbed walk time; a run that wants the walk time does not.

#### Docker verification

On the 8-core / 30 GB host, `-d /var/tmp/bgperf` with results outside the
campaign tree.

`bench -t bird -g bgpdump2 -n 1 -p 500000 --mrt-file mrt/rib.20210801.0000
--tester-trace-io`: converged in 6s with `backpressure` reading `available:
true, max_blocked_writes: 13, max_send_stalls: 3` in the injector's
`<prefix>.events.json` section and on its `tester_complete` event -- the first
run in this project to report positive blocked-write evidence from any
generator. Injection was still sub-poll (`reported_injection_s` 0.482256s), and
500,000 prefixes is where a single BIRD session first stops draining a 256KB
buffer as fast as bgpdump2 fills it.

The same run without the flag: `available: false` with its reason, and the
2-injector 10,000-prefix shape back to a 0.011306s walk on a 947-byte log.

`bench -t bird -g bgpdump2 -n 2 -p 500000 --mrt-file mrt/rib.20210801.0000
--tester-trace-io`, the two-injector version: the artifact's counts match the
logs exactly (22 partial writes and 82 stalls for one injector, 22 and 39 for
the other), and this run also settled the one invariant the counts touch.

It also exposed the flag's *second* cost, which review of this change set
caught in the write-up above. `BlasterLogReader.READ_MAX` caps a poll at 4 MB,
which was sized for the ~1 KB logs an untraced injector writes. Traced, the
injector that received the other's whole table wrote **22.5 MB before its own
`End-of-RIB`** -- so the reader needed about six polls to reach the line that
reports completion, and `tester_complete` was stamped that late: `injection_s`
5.0s against the generator's own `reported_injection_s` of 1.4996s. The counts
are unaffected, because they are still exact once the reader catches up; only
the polled interval is. The cap is left alone here -- changing the reader's
budget is a decision about the untraced path that everything else depends on,
and it needs its own verification -- but the field is now documented as not
comparable across the flag, which is the same conclusion the walk-time
inflation already reached by a different route: a traced run is for finding out
whether the generator was blocked, and `reported_injection_s` is what to read
for how long it sent.
`offering_poll_can_stop()` ends the poll at completion on the grounds that
nothing observable can arrive afterwards, which is argued for queue *depths*; a
cumulative count is a different shape, and bgpdump2 does keep flushing after
`RIB walk complete`. Checked rather than assumed: both injectors logged every
one of their writes before `End-of-RIB` and none after it, because the flush at
End-of-RIB empties the buffer. The docstring now says so instead of reasoning
only about depths.

The fixture `tests/fixtures/bgpdump2_blaster_io.log` is a real capture from a
**separate, earlier** repeat of that same single-injector 500,000-prefix shape
-- one injector precisely because a second one's log is 23 MB of the target's
echo. 150 lines carrying 28 full writes, 13 partial writes and 2 stalls: the
partial writes match the verification run above and the stalls do not (2 there,
3 here), which is what a backpressure count does from repeat to repeat and the
reason the two are recorded as two runs rather than one. The fixture is a
workload actually hitting backpressure rather than an invented one; its 41
write lines sum to exactly its final 7,891,005 `octets`, which is also the
independent check that no write line follows `End-of-RIB`.

## Phase 4: Derive bottleneck findings conservatively

### Progress on 2026-09-03: measure the tail, before classifying it

The exit criterion is to tell a controlled tester limitation apart from a
controlled post-injection convergence tail, and the run had no measurement of
that tail to classify. Phase 2 left `post_injection_tail_s` out deliberately:
it is the one interval that spans two producers, and the contract allows it to
be negative. That is now published per generator and for the fleet, beside a
resolution, and printed in one line at the end of a run.

Three things it had to get right.

**The sign is the finding, so nothing clamps it.** A negative tail means the
monitor reached the configured check-point while the generator was still
finishing. That is not a fault and not rare: the check-point sits below the
full table by design (99% for synthetic and bgpdump2 runs), and a generator
goes on flushing sessions the check-point did not need. It is the shape of a
run in which the target was never the thing being waited for. Clamping at zero
would give that run the same number as one that converged the instant its
generators finished -- the two conclusions Phase 4 exists to separate.
`signed_duration_s()` is therefore a separate helper: `duration_s()` still
refuses an inverted interval, because within one producer that is a wiring
fault rather than a measurement.

**It is measured from completion, never from `tester_last_update`.** The last
update is the last increase *observed*, not the end of the workload. A tail
derived from it would be available for exactly the runs where the generator is
under suspicion -- a stalled injector -- and it would look entirely ordinary.
A generator that never completed has no tail, and the fleet tail is
all-or-nothing with the rest of that section: it starts at the *slowest*
generator's completion, since one measured from the first would charge the
target with time it spent waiting for another injector.

**The monitor now publishes the resolution of its own polls**, because the
tail is the only interval bounded by two different instruments and it is only
as sharp as the wider of them. `Monitor.stats()` execs `gobgp neighbor -j` and
only then sleeps 1s, so its achieved cadence is `read + 1s` -- the same trap
the tester loop had, and the reason `MonitorEventRecorder` takes the requested
cadence as a floor and stamps the gap it achieved. `first_prefix_s`,
`convergence_s` and `assurance_s` are now qualified the same way, which they
were not before: a `first_prefix_s` of 0.0s on a fast run is a poll that could
not resolve it, not an instant first prefix. Assurance carries the resolution
of the sample its verdict ruled on rather than a gap to the moment the verdict
was stamped, since it is a decision about a sample and not a fresh look.

A tail whose magnitude is under that resolution is reported in words --
`shorter than the 1.0s poll resolution` -- rather than as a duration, in either
direction. No Docker run: this is a pure derivation over events two poll loops
already produce, covered by `tests/test_post_injection_tail.py` against
recorder-produced streams.

### Progress on 2026-09-03: the findings, and what they refuse to say

`findings.py` derives a `findings` section into every run's
`<prefix>.events.json` and prints its verdict as the last line of a run. It is
pure and Docker-free like `contention.py` and `convergence.py`, and its input
is the event artifact rather than the event stream, so it cannot reason about a
duration the artifact did not publish.

The verdict is `limiting_component`, and two of its four values are refusals
that are deliberately not the same refusal. `inconclusive` means the
measurement that would decide it was never made -- no generator that can be
asked, a generator that never completed, a monitor that never reached the
check-point. `unresolved` means the measurements exist and something forbids
attributing them. Collapsing the two would hide which one the operator can do
something about.

Four things this had to get right.

**The coverage rule is what keeps a queue-side counter from becoming a
verdict.** The dictionary already said not to derive a tester-limited finding
from a BIRD 2.19 rate, and the policy cannot ask which generator produced a
number. It asks the numbers instead: at least half the offered table has to
have crossed the measured interval, or the generator has to have timed its own
send. BIRD 2.19 puts between 0 and about 15% of its table inside that interval
depending only on where the first poll landed, so it fails both and the run is
`unresolved` with `injection_boundary_unresolved` -- including the large
positive tail such a run has, which would otherwise have been charged to the
target while the generator was still draining its sessions. An MRT injector
fails the first test and passes the second, so a 10,000-prefix run whose whole
walk is over before the first poll can still show a target tail.

**A confounder withholds the verdict, not the evidence.** A tester-limited run
on a saturated host publishes the `tester_limited` finding and reports
`unresolved`, naming host saturation as what decided it. Dropping the finding
would leave nothing to re-read when the run is repeated on a quiet machine,
and `min idle%` is host-wide and includes bgperf2's own load, so it says the
machine had nothing spare and not whose work that was -- the CPU attribution
boundary above, applied.

**Backpressure is an interaction, and only the counts of being blocked
qualify.** BIRD 3 reports `TX pending` bytes at every poll, and a session with
something queued at the instant it is looked at is what a working session
looks like; reading that as backpressure would withhold every BIRD 3 verdict
there is. Only `max_blocked_writes` and `max_send_stalls` -- cumulative counts
of writes the socket refused and encode passes that found no room -- are read,
and they name no component, because which end of a blocked write was at fault
is not in these numbers.

**An unsampled host minimum is not a measurement.** `min_free` starts at a
sentinel above every real value so the first sample can only lower it, so a run
whose memory sampler never fired would otherwise publish a machine with a
petabyte free. `host_evidence()` maps it back to `None`.

Tester log errors and timeouts are deliberately *not* inputs: `finish_bench()`
writes the artifact before scanning those logs, on purpose, and a finding is
worth less than the atomic write of the evidence it would be derived from.

No Docker run: this is a pure derivation over an artifact two poll loops and
the controller's samplers already produce, covered by `tests/test_findings.py`.

## Phase 5: Add repetitions and order control

### Progress on 2026-09-03: a matrix can be run more than once

A test may declare `repetitions: N`. `expand_batch_cells()` turns the matrix
into the ordered list of runs it asks for and `batch()` iterates that list,
replacing the four nested loops it used to walk. `batch_repetitions()` rejects
anything that is not a positive integer before the first container starts --
`repetitions: 0` would otherwise run nothing and `repetitions: "3"` would run
once, either of them discovered hours in or not at all.

Four decisions worth keeping:

- **A repetition repeats the whole matrix, not each cell.** Three back-to-back
  runs of one cell share a page cache, a thermal state, and whatever else the
  machine was doing a minute ago, so part of what they measure is that. Block
  order also means an interrupted batch holds one observation of everything
  rather than every observation of the first few cells.
- **A repetition is part of the run's name, not a column beside it.** Every
  artifact a run writes is named from one stem -- `<prefix>.events.json`,
  `<prefix>.versions.json`, six per-run PNGs -- and each is written with
  `os.replace` or a plain `open(..., 'w')`. A second pass under the same name
  replaces the first one's evidence with no error, which is the opposite of
  "preserve every raw observation", and leaves two CSV rows nothing can tell
  apart. `create_graph()` needs the distinction too: it keys the x axis off a
  dict of row names and appends one bar height per row, so rows sharing a name
  give it fewer ticks than heights -- a wrong graph or a crash depending on the
  matplotlib version, produced at the end of a batch that has already run for
  hours. The artifacts also carry `run.repetition` so a later summary need not
  parse a label to group passes.
- **That stem is now one function, and it was already losing evidence.**
  `bench_output_prefix()` must carry every dimension a batch iterates.
  `filter_test` was not among them: the three policy cells of
  `benchmarks/2026-filters.yaml` all wrote
  `bird_2.19.2_bgpdump2_1050000_10.*`, so two thirds of that suite's per-run
  artifacts were overwritten and no `run` dict recorded which policy the
  survivor came from. The periodic mid-run graphs were built from `args.target`
  alone and dropped label, version, filter and repetition together. Both use
  the stem now, and both new dimensions reach the `run` dict; each is appended
  only when set, so an unfiltered single-pass run keeps the name it has always
  had.
- **A cell id says what the cell is, never when it ran.** `ordinal` is the
  cell's position within one pass and `repetition` says which pass. Raising a
  test from two passes to three therefore does not move the ids of the two that
  already have results, and the ids will survive the permuted execution order
  the next change set introduces.
- **The id and the name must agree about a single-pass test.** Both say "no
  repetition": the cell carries `repetition: None` and the id omits the key.
  Suffixing the name only when `repetitions > 1` while the id always carried
  `repetition: 1` meant a completed single-pass batch whose config later gained
  `repetitions: 3` matched its stored pass-1 ids under `--resume` -- which
  `scripts/run_2026_suite.sh` passes by default -- reused those rows unchanged,
  and produced a CSV holding `bird` beside `bird #2` and `bird #3`. Adding
  repetitions changes what every row is, so it costs a re-run rather than a
  mixed table. Omitting the key also leaves a single-pass id with exactly its
  pre-repetition shape, so the progress schema version did not have to move and
  an in-flight batch from an older build still resumes rather than costing the
  operator every completed cell.

`check_batch_test()` came out of reviewing the above: `batch_repetitions()`
turns a bad repetition count into an up-front message, and the matrix axes next
to it had no such check -- a test with no `filter_test` reached expansion as a
bare `KeyError` naming neither the test nor the key, which all three tests in
`benchmarks/big-tests.yaml` did. They now declare `filter_test: [None]`, and an
axis is required rather than defaulted so a typo cannot quietly run the matrix
unfiltered.

Not addressed here, and still open in this phase: deterministic order from a
recorded seed, and the median / min / max / dispersion / coefficient-of-
variation summary. Both build on the enumerated cell list this change set
introduced. No Docker run was needed or made: the change is confined to batch
expansion, run naming and the progress file, all of which the unit suite
covers (`tests/test_batch_repetitions.py` plus `TestBenchOutputPrefix` in
`tests/test_measurement_artifacts.py`; 562 total, Docker-free).

### Progress on 2026-09-03: a matrix can be run in an order nothing chose

A test may declare `order: shuffle` and, optionally, `seed: <int>`. Matrix
order runs every cell of one target next to every other cell of that target, so
anything that drifts over the hours a batch takes -- an ambient thermal ramp, a
page cache filling, a neighbour's job that starts an hour in -- lands on the
axes in a pattern rather than as noise, and leaves as a difference between the
daemons. Permuting does not remove the drift; it stops it lining up with one
axis. The default is unchanged, so no existing benchmark config runs
differently.

Six decisions worth keeping:

- **The permutation is inside a pass, never across one.** A repetition is a
  block on purpose -- an interrupted batch then holds one observation of
  everything rather than every observation of the first few cells -- and
  dealing the three passes together would take that back. Each pass draws its
  own permutation, because the digest is keyed by a cell id that carries the
  repetition: one permutation reused for every pass applies the same position
  bias three times, and the repetitions cannot average out what they all share.
- **The order is a digest of the seed and the cell id, not a seeded PRNG
  draw.** The entire point of recording a seed is that the sequence can be
  reconstructed after the fact, and a `random.shuffle` result is a property of
  the interpreter that produced it as much as of the seed.
  `tests/test_batch_order.py` pins one seed's order outright, so changing the
  keying scheme costs a deliberate edit rather than silently invalidating every
  recorded seed.
- **The seed is written to the progress file before the first cell runs.** A
  seed recorded only once a cell completed would be missing from exactly the
  batches that died early -- the ones whose order someone will want to
  reconstruct -- and `--resume`, which `scripts/run_2026_suite.sh` passes by
  default, would draw a fresh permutation and finish in an order that is
  neither the recorded one nor a single one. Only a drawn seed is recovered
  that way: a seed the config states wins, because editing it by hand is an
  instruction to re-sequence rather than a resume to be corrected.
- **An omitted seed is drawn, not defaulted to a constant.** A constant shared
  by every batch is one permutation, applied identically everywhere: exactly
  the fixed pattern this exists to break. A `seed` under `order: matrix` is
  rejected rather than ignored, since a config naming a seed is asking to be
  permuted.
- **Execution order is not report order.** `create_graph()` keys the x axis off
  the row names it sees and appends one bar height per row, pairing the two
  positionally -- which holds only while each (peers, prefixes, filter) group
  arrives with its targets in the same order, as matrix order guarantees and a
  shuffle does not. `batch_report_rows()` therefore rebuilds the CSV and the
  graph input in matrix order from the completed-cell map, whatever order the
  cells ran in. Reporting in execution order would have put bars under the
  wrong labels, or raised a length mismatch, at the end of a batch that had
  already run for hours. The row order also no longer depends on whether a run
  was resumed.
- **Identity does not move with the order.** `ordinal` stays a cell's place in
  the matrix and the cell id says nothing about when it ran, which is what the
  previous change set built it for; resume matches its completed cells
  whichever way either pass was sequenced. `BATCH_PROGRESS_SCHEMA_VERSION` did
  not have to move either: `order` and `seed` are optional keys, so a progress
  file written before this change still loads and resumes.

Review of this change set found three defects, fixed here:

- **`check_batch_test()` was unreachable for the key it named first.**
  `batch()` read `test['targets']` to expand versions before validating
  anything, so a test with no `targets` -- or with `targets: bird` rather than
  a list -- still died as a bare `KeyError`, naming neither the test nor the
  key, which is the failure that check was added to remove. The new
  `batch_order()` sat ahead of it too, so a bad `order` in a test without a
  `name` reported `test 'None': ...`. Validation now runs first in the loop.
- **Two targets in one test could share a run name.** A run name is label, else
  target plus version; two entries differing only in `threads`, `mrt_file` or
  `image` -- the first of which is exactly the BIRD 2-vs-3 comparison Phase 5A
  calls for -- produce one name, and therefore one artifact stem, two
  indistinguishable CSV rows, and a `create_graph()` shape mismatch at the end
  of a batch that has already run for hours. `check_batch_run_names()` refuses
  them up front and says to add a `label`, the same remedy
  `expand_target_versions()` already applies along the version axis. Identical
  duplicate entries are refused for the same reason: a second observation of
  one cell is what `repetitions` is for, and it names its passes.
- **A superseded seed was dropped.** The progress document is rebuilt on every
  checkpoint, so editing the seed mid-batch and resuming left the file
  describing an order that its own completed rows did not run in. The old
  sequence moves to `previous_seeds`, and only when there are rows for it to
  describe.

A second review pass found two more, also fixed here:

- **The superseded-sequence guard never fired for a sequence with no seed.**
  Keying it on a recorded seed meant a matrix pass interrupted, then resumed
  under `order: shuffle`, rewrote the file as shuffle seed X with no
  `previous_seeds` -- the document then claiming rows that ran in matrix order
  had run under a permutation, which is exactly the state it exists to
  prevent. It compares the whole sequence now, and a file naming no order is
  read as matrix, since before this change there was no other order to have
  run in.
- **Nothing rejected a test key the batch does not read.** `seeds: 7` beside
  `order: shuffle` passed every check and drew a fresh permutation on each
  non-resume invocation while looking pinned; a misspelt `repetitions` runs one
  pass of a matrix someone asked three of. `check_batch_test()` now rejects any
  key outside the required and optional sets -- the same failure the value
  checks exist to prevent, reached one character earlier.

Still open in this phase after that change set: the median / min / max /
dispersion / coefficient-of-variation summary, and the named variance rule for
expanding three runs to five. No Docker run was needed or made -- the change is
confined to batch sequencing, the progress file and report assembly, covered by
the new `tests/test_batch_order.py` (29 tests) plus the extended
`test_benchmark_configs_expand`; 595 total, Docker-free.

### Progress on 2026-09-03: what the passes of a cell agree and disagree about

A batch now writes `<test>.summary.json` beside its CSV: one entry per matrix
cell, carrying that cell's passes and the distribution over them --
`mean`, `median`, `min`, `max`, `stdev` and `cv_percent` for each of the
thirteen measured columns. `summary.py` is the pure module that derives it,
free of Docker and of bgperf2 imports like `contention.py`, `convergence.py`
and `findings.py`, and `bgperf2.batch_summary_groups()` is the only thing that
knows about cells. The document is rewritten cell by cell, like the CSV, so a
batch that dies in its third pass still says what its first two measured.
`docs/measurement-dictionary.md` has the field list and every withholding
reason.

Eight decisions worth keeping:

- **The summary never replaces the rows.** Every pass keeps its CSV row, its
  `<prefix>.events.json` and its PNGs, and the summary publishes the
  observations each statistic was computed from beside it, together with which
  repetition produced which value. The plan's own words for this phase are
  "without hiding individual runs", and a statistic whose inputs are gone is
  not one a reader can disagree with -- the same reason a finding carries its
  evidence.
- **Nothing absent is published as a zero.** A withheld statistic is `null`
  with its reason in a `withheld` object beside it. `stdev` and `cv_percent`
  need two observations, because a coefficient of variation of 0 over one pass
  would say the measurement is perfectly repeatable on the strength of never
  having been repeated -- which is exactly the claim this phase exists to stop
  a single-observation cell from making. `cv_percent` also needs a positive
  mean: `tester errors` and `tester timeouts` are 0 in every good run, where
  the spread is real and zero and the ratio to the mean is a division nobody
  can do.
- **The dispersion is the sample standard deviation, n-1.** Three passes are a
  sample of what the machine does, not the population of it, and the
  population formula understates the spread -- to exactly 0 at n=1, which is
  the same lie in a different form.
- **`min` and `max` are observations, and are copied through unrounded.** A
  summary must not report an extreme no run produced. The derived statistics
  are rounded, to six places: a 0.4 MB spread in `max mem (GB)` reads as
  `0.000391` rather than as `0.0`, and `1.4142135623730951` stays out of a
  document meant to be read. `mean` is published although the plan did not ask
  for it, because `cv_percent` is otherwise a number a reader cannot check.
- **A failed pass is counted and named, never averaged in and never silently
  dropped.** Averaging it would put a crashed run's 3-second elapsed beside two
  good ones; dropping it silently would make two passes of three look like a
  complete, tight distribution. A non-numeric value withholds the whole column
  for the same reason, rather than skipping that pass: dropping an observation
  changes `n` without saying so, and `n` is what every dispersion here rests
  on. A pass that has *not run* is counted apart from one that failed, because
  one is a result and the other is unfinished work, and an operator does
  something different about each.
- **Passes that disagree about an image are not repeated observations of one
  thing.** `target image`, `tester version`, `monitor version` and the
  `required` count are checked for agreement across the observed passes; a
  disagreement lands in `inconsistent`, is published as the list of values
  rather than as one of them, and is printed as a warning even for a
  single-pass document. This is the gcov trap -- a freshly built version beside
  a cached one -- reached one layer up: three passes across a rebuild would
  otherwise publish a tight-looking distribution over two different binaries.
  The measurement is still published; the disagreement is what is said out loud
  about it.
- **Grouping is by `ordinal` and sorted, not left in the order it arrived.**
  `ordinal` is the one field neither a repetition nor a permuted execution order
  changes, so the passes of one cell come together whichever way the batch ran.
  Sorting both levels -- cells by ordinal, passes by repetition -- means the
  function returns matrix order even when handed a sequenced list, which is the
  same rule `batch_report_rows()` follows: execution order is a property of the
  run and not of the report, and a summary dealt in shuffle order would sit
  under a CSV and a set of bars that were not. Found by review of this change
  set, which had it inheriting the caller's order.
- **A summariser that raises costs the summary and not the rows.** It runs
  after the CSV is on disk and `publish_batch_summary()` catches, printing
  `summary unavailable: <exception>` -- the same rule
  `write_event_artifact()` applies to its findings, for the same reason: at the
  end of a batch that has already run for hours the rows are the evidence and
  this is an opinion about them.
- **The document is written before the first cell runs, not only after one
  finishes.** `batch()` unlinks the progress file of a discarded non-resumed
  batch but leaves its other output in place, so a summary written only on a
  completion would leave the previous run's -- three passes that no longer
  exist, described as though they did -- sitting beside a CSV that had been
  rewritten. Writing it up front also means the file names the cells a batch
  intends to run, all `not run`, from the outset.

Review of this change set found four defects, fixed here:

- **The unsampled `min_free` sentinel was summarised as an observation.**
  `output_stats['min_free']` starts at `UNSAMPLED_MIN_FREE` so the first
  sample can only lower it, and a run whose `free` poller never fired writes
  ~931,322 GB into the `min free mem (GB)` column. `host_evidence()` maps that
  sentinel back to `None` for the findings for exactly this reason and the
  summary had no equivalent, so the worse case was a mixed cell: the `free`
  thread raising in one pass of three -- which kills that thread while the run
  goes on -- would publish a mean of ~310,474 GB, a standard deviation of
  ~537,000 and a coefficient of variation of 173% on a 64 GB box, which reads
  as a finding about the daemon. The sentinel is now named by
  `unsampled_row_values()` in the row's own units, through the single
  `row_gb()` formatter so the two cannot drift, and one of them withholds the
  whole column for that cell rather than being dropped from it -- dropping it
  would change `n` without saying so. `min idle%` is deliberately left alone:
  its sentinel is 100, which is also a real value, and an idle host and an
  unsampled one are the same finding.
- **`max mem (GB)` was the same defect reached the other way round**, found by
  a second review of the fix above. `max_mem` starts at 0 so the first sample
  can only raise it, and the target's sampler is as easy to lose:
  `Container.stats()` has no `try` around its `dckr.stats` walk, and its `mem`
  comes from a `.get('usage', 0)` that can return 0 with the thread still
  alive. A 3-pass cell reading 1.0, 0.0, 1.0 published a coefficient of
  variation of 87% invented by a dead sampler -- immediately beside the
  `min free mem (GB)` the first fix correctly withheld, so the document would
  have reported the memory numbers disagreeing wildly while declining to
  publish the other memory number. A peak under 0.5 MB is not something a
  daemon holding a BGP table can produce, so `0.0` is distinguishable and is
  named too. `max cpu %` is left out beside `min idle%`: it rounds to 0 from
  any peak under 0.5%, so its zero is ambiguous.
- **A row that was not the header's width cost the whole test's document.**
  `summarize_batch()` checked that the header carried every name it reads, and
  then `summarize_cell()` indexed each row by position with no length check.
  `BATCH_PROGRESS_SCHEMA_VERSION` deliberately did not move when `max foreign
  cpu %` was appended, so `--resume` onto a progress file written by an older
  build is a supported path and such a row is one field short: it raised
  `IndexError`, `publish_batch_summary()` caught it, and the result was no
  summary file at all for that test plus a line naming neither the cell nor
  the pass. Such a pass is now `unreadable`, kept apart from `failed` because
  it says nothing about the daemon, and it costs only itself.
- **The pre-loop write discarded its own failure, defeating its own purpose.**
  It exists so a discarded batch's summary is replaced rather than left beside
  a rewritten CSV, and if `summarize_batch()` raised there -- the legacy-row
  case above, on the resume path -- nothing was written, the error string was
  thrown away, and the previous run's document stayed in `results/` with
  nothing said about it until the end-of-test call hours later. All three call
  sites print a failure line now, and a non-resumed batch unlinks the stale
  summary along with the progress file, so a failed write leaves no document
  rather than the wrong one.
- **The `isfinite` guard did not achieve what it was added for.** It withheld
  the statistics but still copied the offending value into `values`, and
  `json.dump` writes a nan or an inf as a bare word that jq and most
  non-Python parsers reject -- so the document stayed unreadable, which was
  the whole reason for the guard. A non-finite value is published as its own
  repr and the dump runs with `allow_nan=False`, which turns anything else of
  the kind into a named failure instead of an unparseable file.

Two smaller things came out of the same review. The row is read by **column
name** throughout, and `summarize_batch()` refuses a header that has lost one
of the columns it needs rather than guessing -- that row is positional for
`create_batch_graphs()` and has drifted by a column once already, so a summary
keyed on index 12 would be arithmetic nobody could check;
`tests/test_batch_summary.py` pins every name it reads against
`stats_header()`. And the printed line names a cell with
`batch_cell_description()` rather than the run name, because a run name is the
target and two cells of one target differ only in their axes: `bird: 3 of 3
passes observed` printed four times named none of them.

The exit criterion was demonstrated with a fake-runtime batch: two targets by
two peer counts, three repetitions, `order: shuffle` with a stated seed, an
interruption inside pass 2 and a `--resume`, one cell failing in pass 3. The
resumed batch re-ran only the interrupted cell, the CSV held all twelve rows,
and the summary reported four cells with their CVs and named the failed pass
under its own cell. No Docker run was needed or made: the change is confined to
report assembly over rows the batch has already written, covered by the new
`tests/test_batch_summary.py` (64 tests); 661 total, Docker-free.

### Progress on 2026-09-03: when three passes are not enough, and who decides

Phase 5's last work item -- "expand from three to five runs only under a named
variance rule" -- is implemented in `summary.py` as `apply_variance_rule()`.
The status line above deferred it to Phase 6 as "a campaign decision rather
than implementation". That was half right and the half it got wrong is the
expensive half: *which* rule is a campaign decision, but a rule that is not
named anywhere is not a decision at all. It is whoever reads the CSV, decides
they do not like a number, and reruns -- which selects for reruns of the
results somebody found surprising, and turns a benchmark into a search for the
expected answer. Naming it in code costs nothing and makes the campaign's
choice an edit to one constant rather than an act of judgement per cell.

The rule is comparative, not a threshold on a coefficient of variation:

> two cells are separated when their medians differ by more than the sum of
> their standard deviations, floored at the resolution of the metric

There is no CV that means the same thing twice here. A 2% spread is nothing on
a cell whose targets are 40% apart and fatal on one where they are 0.12% apart
-- which is what FRR 8.5, 9.1 and 10.0 actually were, finishing a 95s MRT run
within 0.11s of each other. A cell therefore earns more passes when its own
spread covers the difference it is being asked to resolve, and not otherwise.
Run against those three FRR numbers with a realistic 0.2s pass-to-pass spread,
the rule reports all three as unseparated and asks for five passes; run against
targets 40% apart it says nothing at all.

Five decisions worth keeping:

- **It is deliberately weaker than a significance test.** This is a scheduling
  rule with n=3, where a t-test would be arithmetic dressing up three numbers.
  It is conservative in the direction that costs machine time rather than the
  one that publishes a ranking the passes do not support.
- **It reads `elapsed (s)` only.** That is the end-to-end number every graph in
  `create_batch_graphs()` is keyed on and the one a version comparison is read
  from. A rule ranging over all thirteen metrics would recommend expansion for
  every batch ever run, since `min idle%` and `max cpu %` are noisy by nature
  and nobody ranks a daemon by them.
- **A cell is compared only within its own (peers, prefixes, filter) group,
  and against every rival in it.** `create_graph()` draws exactly those groups
  side by side, so the rule answers a question somebody is going to ask of the
  picture; a 10-peer cell is not the rival of a 50-peer one. The first version
  compared against the *nearest* rival by median, on the reasoning that
  separating a cell from its closest neighbour separates it from all of them --
  which review showed is true only if every rival has the same dispersion.
  With bird at 40 +/- 0.01, frr at 41 +/- 0.01 and gobgp at 45 +/- 10, bird
  cleared its nearest rival by a mile and was published `separated` while being
  nowhere near gobgp, in a picture that draws all three side by side. The
  verdict is decided by the **binding** rival instead: the smallest margin
  between the gap and the combined deviation, which is the closest call in the
  group and the one a reader would challenge first.
- **Five is a floor under the recommendation and a ceiling on the expansion,
  never a cap on what the test already asked for.** A cell still unseparated at
  five passes is not asking for a sixth -- it is saying those two targets are
  not distinguishable at this workload, which is a result, and expanding
  without a limit is how a batch that cannot decide something spends a weekend
  failing to. But a test declaring `repetitions: 7` told to "rerun with
  repetitions: 5" would *reduce* its passes and discard observations, so the
  recommendation is `max(5, declared)`. Reaching the ceiling in passes but not
  in observations is a third thing again: that shortfall is a failed pass to
  investigate, not a missing repetition, and rerunning at the same count only
  repeats it, so it is named rather than turned into advice.
- **The rule is silent about the results it supports, and says each thing
  once.** Every verdict but `separated` prints a line -- a cell the rule
  endorsed needs none, and review later showed that a *refusal* very much does;
  see the note below. The lines are de-duplicated by unordered pair, since the
  pair is usually mutual: a two-target group otherwise states one relation
  twice with identical numbers, and a matrix of 4 peers x 3 prefixes x 2
  filters x 3 targets would end a multi-hour batch with 72 lines carrying 36
  facts.

Withheld for a stated reason rather than answered, in the shape `findings.py`
publishes a verdict -- the policy and the numbers it was applied to sit beside
it, because a verdict nobody can argue with is a boolean with extra words:
a single-pass cell (no dispersion), a cell whose column was withheld by the
unsampled sentinel, a cell no other cell shares axes with, and a cell **no**
rival of which has a dispersion -- that last one still publishing the gap, so
the reader is told which pair could not be judged and by how much they differ.
That last case is deliberately not "the nearest rival has no dispersion":
review found that a single degraded cell -- two of its three passes failed, so
it has a median and no deviation -- could be picked as the neighbour of two
cells that were plainly unseparated and withhold the verdict for both, with
nothing printed to say the rule had been silenced. Rivals with a dispersion are
preferred, and the refusal fires only when none has one.

Four of those five decisions are as review left them rather than as they were
written: the binding rival, the recommendation floor, the shortfall and the
de-duplicated line all came out of `/code-review`, and each had a reproduction
attached. The first is the one that mattered -- it published `separated` for a
cell that was not.

Ten further review rounds, after the host was rebooted mid-change-set, found
twenty-seven more, every one of them a case where the summary published
something an operator would act on and the passes did not support. The tenth
round found no defect in the code, having fuzzed the rule over 50,000 randomly
shaped groups without an exception, and one sentence of documentation that
described `combined_stdev` as a sum when it is a floored sum -- which is where
this change set stops.

The first of them is the one that mattered, and it invalidated the rule
outright rather than a sentence about it:

- **The metric the rule decides on is quantised, and the rule did not know
  it.** `elapsed (s)` reaches the row as `stats['elapsed'].seconds` -- whole
  seconds -- and that is not a formatting choice that could be widened. It is
  counted off the monitor's poll loop at `MONITOR_POLL_INTERVAL_S`, one sample
  a second, with an integer number of assurance samples then subtracted. There
  is no finer number to publish. Passes of one cell therefore land in the same
  bucket routinely, `stdev` comes out at exactly 0.0, and a combined deviation
  of zero is cleared by *any* gap at all -- so the rule published `separated`
  on a difference of one rounding boundary, and published it in silence, since
  it prints nothing about the results it supports. Worse, the pairs it was
  written for are inside the quantum: FRR 8.5, 9.1 and 10.0 finished a 95s MRT
  run 0.11s apart, which at this resolution is the same measurement. As
  written the rule could not fire `expand` for exactly the comparison it
  exists to catch, and asserted separation instead. The combined deviation is
  now floored at `METRIC_RESOLUTION` -- the same rule as
  `MONITOR_POLL_INTERVAL_S` flooring the published `poll_resolution_s`, and
  the same reason: a span nothing crossed is not a measurement of zero. Two
  cells one second apart are `expand`, then `unseparated at the expansion
  limit`, which is the honest description of three FRR releases this
  instrument cannot tell apart. `summary.py` cannot import that constant --
  bgperf2 imports summary, and the Docker-free import property depends on it
  staying that way -- so `test_stats_contract.py` pins the two against each
  other. `total time` was considered and rejected as the decision metric: it
  is a float to two places, but it times the whole run including container
  startup, so it is finer and less relevant, and part of its dispersion is
  Docker's.

The rest are in what the rule *says* rather than what it computes, which is
where they would be: the arithmetic gets re-derived by anyone who doubts it,
and the sentence built from it does not.

- **`separated` could be published while a nearer rival went unjudged.** The
  preference for rivals that have a dispersion -- itself a fix from the first
  round -- excluded the others from the decision entirely, so one rival with a
  dispersion was enough to earn the verdict while a rival at an *identical*
  median sat in the same group unjudged. Reproduced with bird `[40, 40, 40]`,
  a `broken` cell whose single surviving pass read 40.0, and gobgp
  `[90, 90, 90]`: bird was published `separated` on the strength of gobgp,
  while `create_graph()` drew it beside a bar it was not distinguishable from
  at all. This is the nearest-rival defect one path over -- there it was the
  rival that decided the verdict, here the rival that was skipped. Every
  verdict now names its unjudgeable rivals in `rivals_unjudged`, and
  `separated` is withheld when one of them is nearer than the binding rival.
  Only `separated`: an unseparated verdict is already the conservative answer,
  and degrading those is exactly how one mostly-failed cell mutes its group,
  which is what the first round's fix was for.
- **The de-duplicated line was chosen by matrix position.** The two sides of a
  mutual pair need not carry the same verdict: at `repetitions: 5` a cell whose
  passes all succeeded is `unseparated at the expansion limit` while the rival
  that lost two of them is `expand` with a shortfall. Keeping whichever came
  first meant that when the fully-observed cell had the lower ordinal, the
  batch printed *more passes will not decide it* about a pair where one side
  had produced three of five observations -- and the one thing to act on, the
  failed passes, was in the JSON and never printed. Swapping the ordinals
  printed the shortfall, so which advice the operator got depended on where the
  cell sat in the matrix. The line is now the more actionable of the pair's two
  verdicts.
- **A shortfall was printed instead of the rerun count, not beside it.** With
  `repetitions: 3` and one failed pass, both cells of the pair are `expand` at
  five, but the only line printed said to investigate the failed pass -- and
  the pair de-duplication suppressed the rival's line, which was the one
  carrying the count. The operator's obvious next move is then to fix the pass,
  rerun at the three they already had, and arrive unseparated again. They are
  two different things to do about one cell and both are now said. The
  dictionary had documented a narrower condition than the code applies, which
  is how the substitution read as deliberate.
- **The refusal named only its nearest unjudgeable rival.** `rivals_unjudged`
  was populated on the verdicts that had a binding rival but not on the
  refusal that fires when *no* rival has a dispersion, so with two broken
  rivals the second appeared nowhere in the document -- contradicting what
  this note and the dictionary both say about naming every one of them.

- **A cell whose every pass failed said it had "no dispersion",** which is what
  one observation looks like. The refusal now quotes the metric's own
  `withheld` entry for `stdev`, which already tells the four cases apart in one
  place -- every pass failed, only one observation, the never-sampled sentinel,
  a non-numeric value. A second vocabulary answering the same question
  differently is how the distinction was lost, and the documented "four cases"
  had become three strings.
- **A cell whose rivals all failed was told it had no rivals.** A rival with no
  observation has no median, so it dropped out of the comparison and the
  survivor published `no other cell shares this cell's axes` -- false about the
  test, and the wrong half of the distinction this module keeps: nothing to
  compare against is a property of the matrix as written, rivals that produced
  nothing is a property of the run, and only the second is something to go and
  fix. That is now a fourth reason of its own.
- **A withheld separation was as silent as an endorsed one.** Only `expand` and
  `unseparated at the expansion limit` printed, so a cell demoted to
  `undecided` by a nearer unjudged rival produced no line at all, and silence
  meant both *the rule endorsed this ranking* and *the rule could not judge
  it*. Those are the two things a reader most needs told apart; it is also the
  complaint the first round's fix was written against, where the verdict was
  corrected and the printing was not. Refusals that name a rival now print.
  Making them print surfaced a latent crash on the way: the comparison
  sentence was built before the branch that returns early, so the refusal
  reached when no rival has a dispersion -- which has no combined deviation to
  report -- raised `KeyError` at the end of a batch that had already run for
  hours.
- **The de-duplication keyed on the wrong cell for a withheld separation.**
  That verdict reports a relation against the unjudgeable cell that blocked
  it, which is not the binding rival its `evidence` names. Keyed on the
  binding rival, two cells blocked by two *different* unjudged rivals
  collapsed onto one pair key, and since both rank equally, matrix position
  decided which of the two refusals was printed at all -- the same defect the
  ranking above was added to fix, reached one path over. The verdict now
  records `withheld_by` and the pair is keyed on it.
- **An equally close unjudgeable rival did not withhold separation.** The test
  was `<` where the stated intent is *distinguishable from the cells drawn
  beside it*: a rival at exactly the binding rival's distance contradicts that
  as completely as a closer one. An equal gap is also the likeliest shape here,
  since the decision metric is quantised -- which is the finding above, and the
  reason this one is not the edge case it looks like.
- **The evidence's `nearest_*` fields did not hold the nearest rival.** They
  hold whichever rival the branch chose, and the main branch deliberately
  chooses the smallest *margin*: in the group bird 40, frr 41, gobgp 45 that is
  gobgp, the cell furthest away, while the refusal branch really does use the
  nearest. One key name meaning two things is how a reader of
  `<test>.summary.json` -- the artifact this module exists to make auditable --
  concludes the rule compared a pair it did not. They are `rival_*` now, with
  `rival_chosen_by` saying which selection produced them.
- **A rival that had not run yet was reported as one that produced nothing.**
  The summary is written before the first cell and rewritten after every one,
  so for most of a batch a finished cell's rivals are unstarted -- and an
  interrupted batch leaves exactly that document behind, since the surviving
  file is the last checkpoint. Publishing *every other cell is without an
  observation* there sends the operator to investigate a batch that was merely
  in progress. It is the `failed` against `not run` distinction
  `summarize_cell()` already keeps at the pass level, collapsed one layer up,
  and it now has its own reason.
- **A rival with no observation at all was invisible to the verdict.** The
  unjudgeable rivals were drawn from the cells that have a median, so one that
  never ran -- or whose every pass failed -- was filtered out of the *naming*
  as well as out of the comparison, and appeared nowhere in the verdict:
  `rivals_considered: 1` could not be told from "one of two". It is the same
  defect class as the two above, reached through the rival with no median
  rather than the one with no dispersion, which is the third path into it. It
  also has to withhold `separated`, not merely be named: a rival with no
  observation is *less* known than one with a median and no dispersion, and
  withholding for the second while publishing beside the first would make the
  rule stricter about the case it knows more about.
- **`unseparated at the expansion limit` was decided from one cell's passes.**
  The claim it publishes -- "more passes will not decide it" -- is about the
  pair, so a fully observed cell published it beside a rival that had produced
  two of its five passes and whose dispersion cannot support it. The printed
  line was saved by the ranking, since the rival's `expand` outranks it, but
  the artifact carried the unsupported verdict, and the artifact is the point.
  Both cells must now have reached the ceiling.
- **A rival that failed was reported as one that had not run,** whenever any
  *other* rival in the group had an unrun pass -- an `any()` over the union,
  which throws away the distinction in the act of drawing it. The same shape
  one rival further down, where a single unrun pass described a rival whose
  other two had failed. The refusal now names each rival with its own state,
  counted rather than tested for: `frr_c (every pass failed); gobgp (of 3
  passes, 2 failed, 1 not run)`. The failed one is the only thing in such a
  group an operator can act on, and it was the one being hidden.
- **A pair short because of the *rival* was told to rerun at the count it had
  already run.** `passes_recommended` was always the ceiling, including where
  this cell was fully observed and only the binding rival was short -- advice
  that is a no-op, printed with nothing to say why. And the rival's own
  shortfall is filed under whichever pair *its* verdict binds to, which need
  not be this one, so the no-op could stand alone. That is the "fix the pass,
  rerun at the count you already had, come back unseparated again" failure the
  shortfall was added to prevent, reached through the rival instead of through
  the cell. Such a verdict now carries `rival_shortfall` and no recommendation.
- **A raise in the rule destroyed the whole summary document.**
  `apply_variance_rule()` ran unwrapped inside `summarize_batch()`, so anything
  it raised took the per-cell statistics with it -- `publish_batch_summary()`
  catches at the outer level and writes `summary unavailable`. That inverts the
  rule this repository states for exactly this shape of code, where
  `write_event_artifact()` wraps `derive_findings()` so the evidence still
  lands. The rule is a derived opinion about numbers that are already computed
  and correct, and it now costs only the verdicts: such a document carries
  `variance_failure`, no cell carries a partial verdict, and the failure is
  printed, since a batch whose rule raised otherwise looks exactly like one
  whose every cell was separated. Review's reproduction was a `filter_test`
  axis holding a list, which `check_batch_test()` does not reject and which
  makes the group key unhashable -- a document that would have been written
  before this change, lost at the end of a multi-hour batch.
- **The "rivals produced nothing" refusal was filtered out of the printing.**
  The printed lines were selected on carrying `evidence`, and that branch has
  none -- there is no rival median to take a gap from -- so a group whose rival
  failed every pass printed nothing at all. Silence is what an endorsed ranking
  looks like, which is the whole reason refusals print; the test is now for a
  verdict that identifies a rival rather than for `evidence` specifically.
- **That failure line then escaped the single-pass guard.** It was appended
  outside the `repetitions > 1` block that emits the heading, so a
  `repetitions: 1` batch whose rule raised printed one indented line with
  nothing naming the test or the summary path -- and every checked-in
  benchmark config is single-pass. It also broke the contract that a
  single-pass test prints nothing, for a case where nothing could have been
  printed anyway: every dispersion in such a test is withheld, so no cell of
  one can carry a printable verdict.
- **The call that *describes* the document sat outside the same guard.**
  `publish_batch_summary()` wraps the summariser for the stated reason -- the
  rows are already on disk -- and then called `describe_batch_summary()` after
  the `except`. A raise there aborts `batch()` after the CSV is written and
  before `create_batch_graphs()` and before every remaining test in the yaml,
  costing more rows than the summariser ever could. Review declined to file
  this one, having failed to construct an input that raises; it is fixed
  anyway, because the invariant is what protects the rows and not the current
  absence of a way through it. It reports its own line rather than `summary
  unavailable`, which would be false: the document is on disk and only the
  description of it failed.
- **`passes_observed` sat inside a document that also has `observed_passes`.**
  Near-anagrams, different types -- one a count, one a list of repetition
  numbers -- one nested inside the other's object. It is `observations` now,
  matching the cell field its value comes from.

`docs/measurement-dictionary.md` gains the `variance` field and a section
stating the rule, its four verdicts and the reasons it withholds one, since
that document is where `CLAUDE.md` says the summary's field list lives.

No Docker run was needed or made: the change is confined to the summary
document, which is assembled from rows the batch has already written.
Six of the twenty-seven were doc/code disagreements rather than behaviour, and
are worth naming as a class: each stated a *narrower or older* rule than the code
applied -- the shortfall condition, "only `expand` and `unseparated` print",
and the rule quoted without its resolution floor. A summary nobody can argue
with is the failure this module was written against, and a document that
describes a rule the code does not apply is that failure with extra steps.

Two things about the shape of that list are worth keeping.

Rounds after the rule's arithmetic was settled found almost nothing wrong with
the arithmetic and a great deal wrong with what the rule *said* about it -- the
field names, the printed lines, the refusal reasons, the documents describing
them. That is not incidental. The numbers get re-derived by anyone who doubts
them; the sentence built from them is taken on trust, and a summary nobody can
argue with is the exact failure this module was written against.

And two defects were each found several times, once per path into them,
which is the more useful observation of the two.

`separated` was published three times while a rival the rule could not judge
sat beside the cell in the same bars: through the rival that *decided* the
verdict (the nearest-rival version), through the rival skipped for having no
dispersion, and through the rival skipped for having no observation at all.
The `failed` against `not run` distinction was collapsed three times as well:
at the pass level it was always kept, but one layer up an `any()` over the
group let one unstarted rival relabel a failed one, and one layer down a single
unrun pass relabelled two failed ones. A third variant was a rival whose passes
all ran but whose metric column was withheld being told it had produced no pass
at all; it now quotes the metric's own `withheld` entry, which is what the
cell's own refusal had always done.

Each fix was correct and each left the next path open, because it was written
against the case rather than against the claim. Two claims are the invariants,
and they are what a later change should be checked against rather than the
list above:

- `separated` means *distinguishable from every cell drawn beside it*, so
  every rival that cannot be judged is a rival that cannot be cleared;
- a pass that failed and a pass that has not run are never described by one
  clause, at any level of aggregation -- one is a result to investigate and
  the other is unfinished work, and only the first is something an operator
  can act on.

`tests/test_batch_summary.py` gains 19 tests (`TestTheVarianceRule`) and 37
more (`TestWhatTheRuleWillNotClaim`) pinning the defects above -- including one
that asserts the printed advice does not change when the pair's ordinals are
swapped, and one that the endorsements did not start printing when the
refusals did -- plus one in `test_stats_contract.py` pinning the decision
metric's resolution against the monitor's poll interval and one in
`test_controller_threads.py` pinning that a raising describer costs the
description and not the batch; 728 total, Docker-free.

With this, Phase 5 is complete.

## Phase 5A: Add BIRD architecture workload controls

### Progress on 2026-09-08: policy can be changed on a table already held

`--policy-reload-blocks N` (batch: `policy_reload_blocks: N` on a test)
installs an import policy rejecting the last `N` of the fleet's prefix blocks
once the run has converged, applies it with the target's own reload command,
and measures the table settling at what the new policy leaves.

It closes the last workload gap of this phase. Churn made a converged table
*move*; this makes the policy over a converged table move, which is the thing
an operator does most often and the thing this tool has never measured. The
daemon has to re-read its configuration, re-evaluate its import policy against
routes it already holds, and withdraw the rejected ones from every export
session, with the sessions staying up throughout.

Seven decisions worth keeping:

- **The workload is stated in blocks, not peers.** A block is the group
  `--path-diversity` deals the fleet into -- one peer per block at the default
  -- and whole blocks are rejected. Rejecting *part* of a shared block leaves
  the prefix behind a surviving path: the target does real best-path work and
  the monitor's count does not move at all, so the reload could never be
  observed to complete. Rejecting whole blocks is what makes the completion
  count exact, and it is the same reason `split_churn_paths()` shares its
  block.
- **The blocks are the tail, so there is no seed.** Same determinism rule as
  churn's: a sampled selection would need one, and a seed is another dimension
  in the cell identity, the stem and the manifest -- what `--prefix-scope` and
  `--path-diversity` both refuse to become. The set is rebuildable from the
  peer count, the diversity and the block count alone, and it is published in
  the artifact as `rejected_peer_asns` so a reader need not rebuild it.
- **The peers are ordered by AS, not by mapping order.** A scenario is YAML and
  the order of a mapping is not part of what the file means, while `gen_conf()`
  assigns the address and the AS from the same incrementing index it keys the
  diversity block on. Ordering by AS reproduces the block assignment exactly;
  `Target.scenario_neighbors()` already sorts the same way.
- **What issuing the change cost is published beside what applying it cost,
  never as it.** Measured on `bgperf/bird:3.3.2`, `birdc configure` returns in
  about 20ms while the table drains over the following polls. One number would
  credit the daemon with an instant reload, so `command_s` and `reload_s` are
  separate fields, and the event is dated to the *sample* the reload was issued
  from rather than to the command's return -- the rule both poll loops already
  follow.
- **The CPU across the interval is the measurement, and an unsampled interval
  is not zero.** Re-evaluating a table is mostly CPU, and a reload that
  finishes inside one monitor poll would otherwise have no measurement at all
  beyond "it happened". The samples come from the target's existing stats
  thread and are kept in the artifact rather than in the row -- `max cpu %`
  still describes the delivery, on churn's rule. Where no sample fell inside,
  the field is `null` and the printed line says so: an interval too short to
  sample and an interval in which the target did nothing are different
  findings, and only the second is about the daemon.
- **A collapsed count is not an applied policy**, in either phase, and the
  message names which. `ConvergenceTracker.DROP_FRACTION` and
  `CHURN_COLLAPSE_FRACTION` on a third side of convergence: without it a
  post-reload sample of 0 satisfies `accepted <= expected` for every policy
  there is, and a target that had lost its sessions would be published as one
  that re-evaluated a table quickly. Rejecting *every* block is refused up
  front for the same reason -- an empty table cannot be told from an empty
  session.
- **What BIRD actually does was measured, not assumed.** On both 2.19.2 and
  3.3.2, two peers each: `birdc configure` holds the sessions up -- `Since`
  unchanged, both Established -- so these runs belong in the no-reset
  comparison the policy-testing plan's P4 asks for. But neither series
  re-evaluates purely locally: both answer a changed import filter by asking
  their peers for a route refresh, and each generator's `Export updates`
  doubled. So `reload_s` covers re-import as well as re-decision. That is what
  an operator changing policy on BIRD pays; it is recorded as `mechanism` and
  `session_preserving` rather than hidden, and it is not comparable with a
  daemon that re-filters from its own stored routes.

Refused, at every entry point, for: a target with no reload mechanism (only
BIRD has one), an MRT generator (the policy selects a block by the peer AS
bgperf2 assigned, and an injector replays the file's own AS paths), `-f`/a
scenario target, `--filter_test` (the target's import filter is already the
policy under test and the reload is written into the same place, so the run
would change two policies at once and attribute the result to one), a churn
workload, `-r/--repeat`, and a block count covering every block.
`check_batch_test()` checks every (target, filter, peer count) combination, not
the first.

**`--policy-reload-blocks` and a churn workload are refused together,
deliberately.** Both run against the converged table off the same monitor
samples, so running both means fixing an order, and the second would take the
first's outcome as its baseline -- with nothing in the row, the stem or the
manifest saying which ran first. Choosing that order is its own change set,
like `--prefix-scope total` under `--path-diversity`.

**`-r/--repeat` is refused too, and the first version of this change did not
refuse it.** Churn is refused there because repeat builds no tester objects and
nothing rewrites the generator config the churn protocol lives in; a reload is
target-side and the target is rebuilt anyway, so the reasoning that applies to
churn does not apply here and `-r` was left accepted. What actually breaks is
the completion count. It is `blocks x prefixes per peer`, and repeat reuses
whatever tester containers it finds while regenerating the scenario -- so `-p`
need not be what the generators are announcing. Verified by running it:
`-n 4 -p 1000 -r` behind a `-p 10000` run converged at 40,000, expected the
policy to leave 39,000, and the rejected peer took 10,000 with it. The collapse
guard named that correctly and the run was published incomplete, which is the
point -- it named it after a full run, and the rule is knowable from the
command line.

Stem gets `pr<N>`, both `run` blocks record it, `-f` records `null`. Not a CSV
column, for the reason `--path-diversity` is not. `config` deliberately does
not take the flag at all: a reload is a runtime action on the target and
changes no part of the scenario, so `config` has nothing to emit for it and
offering it there would print a scenario that reads as though it encoded a
workload it does not.

#### Docker verification

`bench -t bird --version 3.3.2 -n 4 -p 100 --policy-reload-blocks 1` on
2026-09-08: converged at 400 accepted prefixes, the reload rejected AS 1006,
the monitor settled at exactly 300, `command_s` 0.023s, target CPU 0.69% peak
over 2 samples, `session_preserving: true`. Repeated at `-p 50000`
(200,000 -> 150,000) and on `--version 2.19.2` at `-p 10000` with
`--policy-reload-blocks 2` (40,000 -> 20,000). Every refusal was exercised from
the command line and each fired before the first container.

The reload completed inside one poll at all three sizes, so `reload_s` equals
its own resolution and the printed line reports it as a bound rather than a
duration -- which is the honest reading, and the reason `command_s` and the CPU
samples are published beside it. A table large enough to make BIRD 3 take
several polls over this has not been run on this host; that is Phase 6 work on
the campaign host.

### Progress on 2026-09-08: a converged table can be made to move

`--churn-prefixes C` and `--churn-bursts B` (batch: `churn_prefixes` /
`churn_bursts` on a test) withdraw the last `C` prefixes of every peer's own
list once the run has converged and put them back, `B` times.

The gap it closes is the largest one left in this tool: **every run bgperf2 has
ever published measures a table arriving at a daemon that has never seen it.**
A router spends almost none of its life doing that. It spends it holding a
table while parts of it move -- a peer withdraws a block and re-announces it a
moment later, and the target has to remove those routes from a loaded table,
re-run best-path selection for every prefix that had a competing path, and
withdraw and re-advertise on every export session. Those are the same three
responsibilities BIRD 3's worker threads exist to parallelise, reached from the
only direction that exercises them together.

Six decisions worth keeping:

- **A burst is switched, not reconfigured.** The block goes into a `protocol
  static churn` of its own in each peer's generator config, and a burst is
  `birdc -s <sock> disable churn` followed later by `enable churn` -- one
  `docker exec` for the whole fleet, for the reason `get_offerings_cmd()` uses
  one: an exec is ~50ms, so a burst issued peer by peer at 50 peers would have
  the fleet withdraw in a staircase and the interval measured would be that
  staircase. The obvious alternative, rewriting the config and asking BIRD to
  `configure`, re-reads the whole file -- several hundred thousand static
  routes on a real run -- so what it timed would be BIRD parsing its own config
  rather than the target reacting to a withdrawal. Probed on both built series
  before the code was written: `bgperf/bird:2.19.2` and `:3.3.2` both answer
  exactly `churn: disabled` / `churn: enabled`, and `churn: already disabled`
  for a protocol already in that state -- which is deliberately *not* treated
  as success, since the sequence alternates and reaching a `disable` on an
  already-disabled protocol means the previous `enable` was lost.
- **The block is the tail of each peer's own list.** A sampled block would need
  a seed, and a seed is a fourth dimension in the cell identity, the artifact
  stem and the manifest -- exactly what the `--prefix-scope` and
  `--path-diversity` notes above refuse to become. The tail is reproducible
  from the per-peer count and the churn count alone. It also makes the block
  *shared* under `--path-diversity`, because a group's peers are handed the
  same list: they churn the same prefixes, so the target loses the prefix
  rather than falling back to a surviving path, which is the withdrawal a
  best-path selection actually has to react to. That is why the monitor-visible
  count is `groups * C` and not `n * C`, and why `churn_operation_counts()`
  publishes both -- reporting only the second understates a diversity-5 fleet's
  work by a factor of five, and reporting only the first describes a workload
  the instrument cannot confirm.
- **The two halves of a burst are timed separately.** A burst timed end to end
  cannot say whether a daemon was slow to drop routes or slow to re-select and
  re-export them, and the second is the half BIRD 3 parallelises. `burst_s` is
  published beside them and *is* their sum -- the withdrawal's end and the
  re-announcement's start are one event, so the three intervals share two
  endpoints. The first draft of this note claimed the opposite, reasoning about
  the actions rather than the timestamps; review caught it against the
  project's own test, which pins 2.0 + 3.0 == 5.0.
- **An interval of one poll is an upper bound rather than a duration.** Both
  halves are bounded below by one poll by construction -- the command is issued
  just after a sample and the soonest it can be seen is the next -- so the
  first Docker run's `withdraw_s` of 1.03s against a `withdraw_resolution_s` of
  1.03s says the block went away somewhere inside one look, and printing
  `1.0s` would publish the monitor's cadence as the daemon's reaction time on a
  run where a faster daemon prints the same number. This was written the wrong
  way round first and caught by reading the artifact of the verification run:
  the phrase only said `under the poll resolution` at exactly 0.0s, which is a
  value this measurement cannot produce.
- **A burst nobody performed is caught when it is issued.** `churn_failures()`
  checks each session's reply against the sessions asked about rather than
  against the sections that came back, on the rule `get_offerings()` already
  uses -- and it matters more here, because a missed withdrawal has no other
  symptom than the count not moving, which arrives `CHURN_STALL_SAMPLES` later
  as a stall that reads as a stuck target.
- **A collapsed count is not a withdrawal**, which review found and the first
  version had wrong. Completion is `accepted <= converged - groups * C`, and a
  post-convergence sample of 0 -- a monitor session that flapped, a target that
  restarted -- is below that floor for every block there is. It would have been
  read as the whole block going away: `churn_withdraw_complete` stamped, the
  re-announcement issued against a table that never lost the block, and the
  session re-learning the entire table published as `reannounce_s`, with
  nothing in the artifact marking either as suspect. `ConvergenceTracker`
  already guards the identical shape during delivery and the churn tracker had
  no equivalent. A count more than `CHURN_COLLAPSE_FRACTION` of the converged
  count below the floor now fails the sequence by name, in either phase and
  between bursts -- before the next burst opens, since a table that has lost
  routes nobody withdrew is not one to start a burst against.
- **The withdrawal target is exact and not tolerated.** Completion is
  `accepted <= converged - groups * C`. A target that never held part of the
  block -- the reason the monitor's check-point carries a 0.99 factor at all --
  can leave that count unreachable, and such a run stalls and is reported
  incomplete with the count it held and the count it wanted. That is a known
  cost, taken deliberately: a tolerance would have to be a number nobody
  measured, and it would let a burst that only half landed be published as
  complete, which is the failure this whole section is written against. All
  four verification runs held their full offered table.
- **The published row describes the delivery, and the churn is in the
  artifact.** `elapsed (s)` is settled before the first burst is issued, and
  the churn loop drains every other producer's queue messages without acting on
  them, so `max cpu %`, `max mem (GB)` and `min free mem (GB)` do not move with
  a burst's peak -- a churn run's row would otherwise mean something different
  from every other row in the same CSV while looking identical. `total time`
  *does* contain the churn, since it is wall clock, and the dictionary says so.

**A sequence that did not complete leaves the run converged and says so in
`MSG`.** Marking the row FAILED would corrupt `elapsed (s)`, which is computed
only on the CONVERGED path, and would discard a convergence measurement that is
real; but a batch of churn cells whose rows all read as ordinary would say
nothing at all about the second workload, which is the quiet-wrong-answer shape
this phase keeps producing. The message goes into `MSG` with the `failed` flag
left blank, and `summary.py` reads that column only for a row marked failed, so
no summary is affected.

**Refused, at all four entry points, for**: any generator but the synthetic
`bird` one (the handle is BIRD's own `birdc`, and an MRT injector plays a file
back once), `-f`/a scenario target, `-r/--repeat`, a block larger than the
per-peer count *after* `--prefix-scope total` has divided, a burst count with
no block to churn, and `--filter_test`. Two of those are worth their own note.

`-r/--repeat` is the `--receivers` shape one round earlier, found before it
shipped rather than after: `bench()` builds tester objects only `if not
args.repeat`, so under `-r` there is nothing to issue a burst through *and*
nothing rewrites the generator config the churn protocol lives in -- the run
would have named its artifacts `ch<C>x<B>`, recorded the workload in both
manifests, and withdrawn nothing. `check_batch_test()` refuses a target with
`repeat` set for the same reason, since a batch target can carry it.

`--filter_test` is a deferred definition rather than a limitation, like `total`
under `--path-diversity`. A burst completes when the monitor's count has fallen
by the whole distinct block; a policy that drops part of that block means the
target never held it, the count cannot fall that far, and a correctly filtered
run would be published as a stalled one. Defining churn under a filter means
deciding what fraction of a filtered block a burst is entitled to expect, which
is its own change set with its own tests.

**One rule cannot be checked before the run**, and that is the shape of the
handling. The converged count is not known until the table has been delivered,
so a run that accepted fewer prefixes than it offered can reach a block the
flag guards passed -- and a burst the monitor could never observe going away
would stall and be reported as a stuck target. `ChurnBurstTracker` refuses it
at construction, and `churn_phase()` turns that into the same
`sequence_complete: false` shape a stall produces rather than letting it raise:
by then the convergence measurement is the thing being preserved, and losing it
to a churn workload that could not start would be the wrong half to drop.

**Docker verification, which this phase requires.** Four runs on
`/var/tmp/bgperf`, no result rows published -- these are correctness checks on a
development host and the campaign's rows may not cross hosts:

- `bird`, 2 peers x 10 prefixes, `--churn-prefixes 4 --churn-bursts 2`: the
  monitor went 20 -> 12 -> 20 twice, both bursts complete, `ch4x2` in the stem
  and the `churn` section in the artifact.
- `bird`, 4 peers x 1,000 prefixes, `--path-diversity 2 --churn-prefixes 200`:
  the monitor held 2,000 distinct prefixes (2 groups x 1,000) and went 2,000 ->
  1,600 -> 2,000. The fleet withdrew 800 paths and 400 prefixes disappeared,
  which is the shared-block arithmetic confirmed against a daemon rather than
  against the test suite.
- `frr_c`, 2 peers x 100 prefixes, `--churn-prefixes 40 --churn-bursts 2`:
  200 -> 120 -> 200 twice. The mechanism is generator-side, and this is the
  check that it propagates through a target that is not BIRD.
- `bird`, 2 peers x 10 prefixes, no churn: the artifact has no `churn` key at
  all and the stem is unchanged, so every document produced by a command line
  predating this flag is untouched.

The change is otherwise pure and covered by the new `tests/test_churn.py`
(134 tests); 1,073 total, Docker-free.

Five things review found, and the two that matter are both the shape this
project keeps recording -- a rule applied to one path and not its neighbour:

- **A churn failure message could shift every column after it.** The message
  quotes birdc's own reply and the repr of an exec exception, and both of the
  replies a run can produce contain commas -- `syntax error, unexpected
  CF_SYM_UNDEFINED, expecting CF_SYM_KNOWN` is the one a wrong protocol name
  gets. Rows are `','.join()`ed with no quoting, so that message is two or
  three extra fields: `filters`, `max foreign cpu %` and all three provenance
  columns move for every reader of that row, and `summary.py` scores it
  `unreadable`. `Container.version_string()` has rewritten commas to `;` for
  exactly this reason since provenance landed; `row_message()` is that rule
  applied to the one other free-text column, and it covers every source of
  `fail_msg` rather than only the churn one.
- **The `-f` refusal read one of the two flags.** `resolve_churn()` runs only
  where a scenario is generated, so `bench -f scenario.yaml --churn-bursts 5`
  went through the guard that checks the block, did no bursts, and recorded
  `churn_bursts: null` in both manifests -- the operator's flag gone without a
  word, which is the thing `--receivers`, `--path-diversity` and
  `--prefix-scope` all have explicit `-f` refusals to prevent.
  `churn_flags_set()` is now what both the CLI and `check_batch_test()` ask,
  and the batch case mattered more than it looked: the combination loop below
  that refusal iterates the *generators*, which is empty when every target
  names a file, so nothing else would have checked such a test at all.
- **A failed run's artifact said it asked for no churn.** The `FAILED` branch
  passed no evidence, so a run that asked for four bursts and never converged
  wrote `run.churn_prefixes: 4` with no `churn` section -- exactly the
  ambiguity the section is published from evidence alone to remove.
- **The fix for that had no test at the call site.** The first version put
  `unrun_churn_evidence()` in `bench()`'s `FAILED` branch -- inside the monitor
  loop, which no Docker-free test can drive -- and the two tests written for it
  exercised the helper and `event_artifact()` in isolation. A second review
  deleted the argument and watched all 1,067 tests pass, which is the defect
  being reintroduced in silence. It is derived in `write_event_artifact()` now,
  the one place every run's document is built, so a path that forgets cannot
  exist and three tests fail if the fallback is removed.
- **And the note about `burst_s` was simply false.** It said the burst spans a
  poll neither half covers; the three intervals share two endpoints, so it is
  their sum, and the project's own test pins 2.0 + 3.0 == 5.0. Written by
  reasoning about the actions -- the re-announcement *is* issued at the sample
  that ends the withdrawal -- rather than about the timestamps.

Three smaller ones from the same second round: the unrun-sequence path printed
`churn: 0 of None burst(s) completed`, because `requested_bursts` is derived
from events and that path has none; `_collapsed()` reported `between bursts`
for a collapse that happened *before* the first burst, which is the flap the
rule most exists for; and it named no phase, though `_stall()`'s own docstring
argues a withdrawal and a re-announcement send the reader to different logs.
The batch path also refused `churn_bursts: 3` beside a `repeat` target with
"cannot be used with repeat" -- the nearest rule rather than the fault, so the
operator removes the repeat and meets the same missing block. The combination
loop runs above those two refusals now, which is the ordering
`resolve_path_diversity()` already uses for a typo'd scope.

**One gap the same round found is deliberately left open**, because it is
pre-existing and closing it properly is a decision rather than a line.
`row_message()` protects `MSG`; the `name` and `filters` columns are equally
free text and equally unquoted. A comma in a batch target's `label` shifts
every column after `name` and `summary.py` scores that pass `unreadable` --
and `label` also names every artifact the run writes, so rewriting it in the
CSV alone would make the row and the files disagree. The fix is a guard, not a
rewrite: `check_batch_run_names()` should refuse a comma in a label, and
`check_batch_test()` one in a `filter_test` entry, before the first container.
That belongs with whoever next touches those guards.

### Progress on 2026-09-07: the table can be exported more than once

`--receivers N` (batch: `receivers: N` on a test) adds N sessions the target
advertises its whole table to and which announce nothing back.

The gap it closes is that **a run has always had exactly one export session**.
The monitor is the only thing the target advertises to, so what a table costs to
*send* -- building a RIB-out, encoding updates, draining a socket -- and what it
costs to *receive* are a single number in every result this tool has produced.
Decoupled exports are the third responsibility BIRD 3's worker threads exist to
parallelise, and nothing here has been able to put load on it.

Five decisions worth keeping:

- **A receiver is not a route source, and that is structural rather than
  documented.** It is a top-level `receivers` key in the scenario and never an
  entry in `conf['testers']`, so `get_test_counts()` -- which reads the testers
  -- can never wait on one for a table it will never send, the monitor's
  check-point does not move with the receiver count, and neither does anything
  derived from it. Verified on Docker: 2 peers x 10 prefixes reports `required`
  19 and `received` 20 with 0 receivers and with 3. It also falls out that
  FRR's End-of-RIB reader is safe by construction: it marks `addr` only `if
  addr in neighbors`, and `neighbors` comes from the testers.
- **It is not a second monitor.** The monitor is the single instrument every
  published timing is read from, and a second one polled into the same queue
  would be an unlabelled second `recved` series in the same stats stream.
  `Receiver(Monitor)` inherits the gobgpd config writer, the startup script and
  the establishment wait -- two copies of that config would drift, and the
  receiver's would drift silently -- and **refuses `stats()`**, so it cannot be
  polled as an instrument by accident.
- **`Target.scenario_neighbors()` is the one place that knows a target has
  three kinds of session.** Eight target modules built `flatten(testers) +
  [monitor]` independently, and a receiver added to seven of them is a target
  quietly exporting to fewer sessions than the run says -- with nothing in the
  row, the artifact or the graph to show for it. The two callers that never
  sorted (`frr.py`, `gobgp.py`) pass `sort=False`, since ordering in a generated
  config is cosmetic and changing it would put an unrelated diff in front of
  anyone comparing a config against an older run's. A test asserts no module
  still builds that list by hand, because the seam is only a seam while every
  caller goes through it.
- **Receivers are established before any generator launches.** A session that
  came up mid-run would take a partial table and land the export work at a
  moment nothing recorded, which is the one thing this exists to measure. Their
  wait is deliberately *not* folded into `monitor_wait_time`: that column is the
  instrument coming up, and adding the fan-out to it would make a
  `--receivers 20` run read as a slow monitor in every published row.
- **Their addresses continue the peers' own index rather than occupying a
  region of their own.** Continuing means neither the address nor the AS number
  (`1000 + i`) can collide with a peer whatever the peer count; a separate
  region is safe only until somebody runs enough peers to reach it, and that
  collision surfaces as a daemon quietly refusing one session.

It is refused for **nothing** that `--path-diversity` and `--prefix-scope` are
refused for, and that asymmetry is the point: a receiver is a target-side
session, so it does not interact with the generator and an MRT run has the same
reason to want export fan-out as a synthetic one. The only refusals are a value
that is not a count, and `-f`/a scenario target -- where the file states the
sessions the target has, so the flag would add nothing to the config while
starting containers nobody peered with.

**Docker verification, which this phase requires.** Both target topologies were
run at 2 peers x 10 prefixes on `/var/tmp/bgperf`:

- `bird` (dynamic neighbours) with `--receivers 3`: all three receivers reached
  `Establ` with the target and held 20 of 20 prefixes, so the target really did
  fan one table out to four sessions while ingress stayed at 20.
- `frr_c` (explicit enumeration, the path through the new seam) with
  `--receivers 2`: the generated `frr.conf` carries five `remote-as` neighbours
  -- two testers, the monitor, two receivers -- in the unsorted order that
  caller has always produced.
- A following run with no receivers removed both containers, so a batch cannot
  inherit a previous cell's fan-out. The removal line said "tester container"
  for them and now names the role.

No result rows were published: these are correctness checks on a development
host, not measurements, and the campaign's rows may not cross hosts.

Four things review found, and two of them are the shape this phase keeps
producing -- a knob that reaches most of the run and not all of it:

- **`-r/--repeat` skipped creating the receivers while everything else acted
  on the number asked for.** `gen_conf()` writes the requested sessions into the
  target's config, `bench_output_prefix()` names the artifacts `rx<N>` and both
  `run` blocks record N, but `if not args.repeat:` created none of them -- so
  `bench -r --receivers 3` published a row and a manifest describing a
  three-way fan-out that did not exist, and skipped the establishment wait with
  it. The inverse left five containers up against a requested two, and a
  dynamic-neighbour target's `neighbor range 10.0.0.0/8` accepts every one, so
  the target exported to sessions provenance did not mention.

  The first fix refused a mismatch. Review found the premise underneath it was
  simply wrong: `--repeat` reuses the *tester* containers and has never reused
  the monitor -- `Container.run()` removes and recreates anything it finds by
  name, and the target is rebuilt under `-r` too, so every receiver session has
  to re-peer regardless. A receiver is a monitor in every respect but being
  read, so it now follows the monitor's lifecycle: built and established on
  every run. That dissolved the refusal, its message (whose "or ask for N"
  advice was unfollowable under `-f`, where `--receivers` is refused), its
  reliance on `dckr.containers(all=True)` (which counts *stopped* containers,
  so a died receiver satisfied the equality check), and the untested call site
  review flagged beside them. What remains is `surplus_receiver_names()`, for
  the one case recreating by name does not cover: a run asking for fewer than
  the last built, where `--repeat` skips `remove_old_containers()`.

  Verified on Docker: three receivers built and waited for; then `-r
  --receivers 1` removed receiver1 and receiver2, rebuilt and re-established
  receiver0; then `-r` with no fan-out removed the last one. Each run's `rx`
  name described the sessions that existed.
- **A Docker call sat ahead of the guards that read only the command line.**
  The refusal above was written there first, and the suite immediately began
  going green or red according to whether a verification run had left receiver
  containers up -- the same tree passed 934 on the branch and failed one on
  master minutes later. Review then found `target_image()` doing the same thing
  one line higher and years older: a mistyped `-p` was answered with
  `ImageNotBuilt` on a host with no daemon or no built image rather than with
  the typo, and every `bench()` guard test depended on which images happened to
  be built. Image resolution now sits after every pure guard and still above
  the teardown -- which is the invariant
  `test_image_resolves_before_containers_are_torn_down` was always about, so
  that test keeps its assertion and gains the workload fields the guards now
  read. A test monkeypatches both `get_ctn_names()` and `target_image()` to
  raise, so neither can drift back up.
- **The fan-out lands in a published column that feeds a confounder.** Each
  receiver is a full GoBGP holding its own copy of the table on the same host,
  and `min free mem (GB)` is host-wide, so `findings.py` can raise
  `low_free_memory` -- which withholds `limiting_component` entirely -- on
  memory the run consumed by design. `describe_export_fanout_cost()` names the
  mechanism before the run and deliberately estimates nothing, for the reason
  `LOG_SPACE_FLOOR_GB` is not an estimate: what a GoBGP holds per route depends
  on the paths, and a number invented here would be quoted back as measured.
  The measurement dictionary's `min free mem` entry says it too; only the
  `received` entry had been updated.
- **The one path that is handed a scenario rather than building one was
  unguarded.** `resolve_receivers()` covers `bench`, `config` and `batch`, but a
  `-f` file's own `receivers` key went straight into
  `enumerate(conf['receivers'])` and `scenario_neighbors()`'s `extend`, so an
  operator mirroring the CLI flag as `receivers: 3` got
  `TypeError: 'int' object is not iterable`. `scenario_receivers()` refuses it
  by name, and checks each entry carries the three fields every target's
  `gen_neighbor_config()` reads, so a malformed one is not a `KeyError` inside
  a config writer.
- **A comment ended up documenting the wrong block.** The note explaining why
  the diversity is resolved before the scope stayed put while the receivers
  call was inserted between it and the code it described -- and it then read as
  a claim about a scope interaction `resolve_receivers()` deliberately does not
  have.

The change is otherwise pure and covered by the new
`tests/test_export_fanout.py` (62 tests); 937 total, Docker-free.

### Progress on 2026-09-07: the target can be made to choose between paths

`--path-diversity D` (batch: `path_diversity: D` on a test) deals the peers
into groups of `D` and gives each group one shared block of prefixes, so the
fleet offers `n * p` paths for `(n / D) * p` distinct prefixes.

The gap it closes is that **the target has never had to select a best path**.
`gen_conf()` gives every neighbour its own `gen_paths(p)` off a single shared
iterator, so every route it learns is the only path it holds for that prefix.
That is not what a router does with a full table: the same prefix arrives from
several neighbours and the work is choosing between them, holding the losers,
and re-running the choice when one is withdrawn. A benchmark that never
presents a second path for a prefix measures reception and re-advertisement and
publishes it as convergence -- and best-path selection is one of the three
responsibilities BIRD 3's worker threads exist to parallelise, so it is
precisely the work a BIRD 2-vs-3 comparison has so far not asked for.

Four decisions worth keeping:

- **The monitor's check-point counts distinct prefixes, not offered paths.**
  It reads what the target *re-advertises*, which is one best path per prefix,
  so it is `groups * p` and not the `n * p` the fleet sends. The two differ by
  exactly the diversity, and the failure is asymmetric: too high is a run that
  can never converge and polls to `STUCK_SAMPLES`, too low is a run that
  reports CONVERGED on a fraction of the table with nothing in the row saying
  so. `path_diversity_groups()` is the one place that arithmetic lives, because
  the block a neighbour is given and the check-point are a hundred lines apart
  and have to agree. The per-neighbour `count` and `check-points` are
  deliberately unchanged at `p`: a peer under diversity still offers `p`, and
  the target still *accepts* all of them, since BGP holds the losing paths too.
- **The default renders exactly the scenario it always did.** `gen_paths()`
  gained an optional `block` argument and the caller omits it entirely at
  diversity 1, so every existing run's rendered scenario is byte-identical
  (verified) and only the Mako preamble, which nothing but Mako reads, differs.
  The same rule runs through the batch path: the cell id omits the key at the
  default, exactly as `repetition` does for a single-pass test, so an in-flight
  batch written by an older build still resumes and
  `BATCH_PROGRESS_SCHEMA_VERSION` did not have to move.
- **The block is keyed on the count of configured neighbours, not the loop
  index.** That loop skips the target's and monitor's addresses, so keying on
  `i` would put one group's peers either side of a block boundary and quietly
  change how many competing paths some prefixes get -- a workload nobody asked
  for, in a run whose manifest states the one they did.
- **It is refused rather than interpreted in four places**, and each is silent
  if it is not: an MRT generator (no paths are synthesised there at all, and the
  check-point comes straight from `-p`), a scenario target or `-f` run (the file
  states each neighbour's paths, so the grouping would do nothing), a diversity
  larger than the peer count, and an inexact division -- whose remainder group
  would announce a block with fewer competing paths than the rest, making `D
  paths per prefix` true of none of the table. Every one of those is checked at
  all four entry points (`bench`, `bench -f`, `config`, `batch`), which is the
  shape this change set got wrong fifteen times last round; `check_batch_test()`
  checks every peer count on the `neighbors` axis rather than the first, for the
  same reason the scope checks the whole grid.

**`--prefix-scope total` and `--path-diversity` are refused together, and that
is a deferred decision rather than a limitation.** Under diversity, "the whole
table" has two readings that differ by exactly `D` -- the paths the fleet
offers, and the distinct prefixes the target ends up holding -- and both are
defensible. The reading would not stay in the flag: it decides the
`prefixes per peer` column, the cell identity, and every artifact name, which is
the same "fourth dimension in all three" the scope note above refuses. Choosing
one is a separate change set with its own tests over `check_batch_test()` and
`expand_batch_cells()`, and refusing costs a message before the first container
while guessing costs a matrix.

**The diversity is in the artifact stem and in the manifest, and it is not a CSV
column.** Nothing else in `bench_output_prefix()` carries it -- a disjoint run
and a run whose peers compete have the same peer count and the same per-peer
prefix count -- so two tests in one batch config differing only in
`path_diversity` would otherwise write every per-run artifact over each other,
the failure `filter_test` had. It is a test-level key rather than a matrix axis
for now, so it does not need a column; making it an axis is the same
three-place change the scope note describes. `run.path_diversity` records it,
and records `null` for a `-f` run: the file states each neighbour's paths, so a
1 there would be an assertion about a workload bgperf2 did not build.

Two things review found, both the same shape as ones this phase has already
recorded:

- **The events artifact carried the dimension in its filename and not in its
  body.** `write_provenance()` records `run.path_diversity` and
  `write_event_artifact()` did not, so `<prefix>.events.json` -- the durable
  per-run evidence, and the document `findings.py` reasons over -- stated
  `peers: 10, prefixes_per_peer: 1000` for a run whose target held 2,000
  distinct prefixes against a `required` of 1,980, with nothing in the document
  able to correct the reader. The stem's `pd5` was the only carrier. That is
  exactly the rule already written down for `repetition`: an artifact carries
  the dimension so a summary does not have to parse a label to recover it, and
  the two `run` blocks are far enough apart that adding it to one and not the
  other is the natural slip.
- **A refusal named the nearest rule it tripped rather than the fault.** The
  scope cross-check read `prefix_scope not in (None, 'per-peer')`, which fires
  on a *typo* as readily as on `total`: `prefix_scope: totl` beside a
  `path_diversity` was reported as the combination being undefined, naming the
  misspelling as though it were a real scope. The operator removes the
  diversity, and only then gets the `unknown prefix scope 'totl'` that was the
  actual fault. It tests against `PREFIX_SCOPES` now, so an unrecognised scope
  falls through to the function whose job is to diagnose it.

No Docker run was needed or made: the change is confined to scenario generation
and matrix expansion, both pure and covered by the new
`tests/test_path_diversity.py` (61 tests); 875 total, Docker-free. What Docker
would add here is the one thing the pure layer cannot check -- that a daemon
handed three paths for a prefix re-advertises one, so the monitor's
`groups * p` check-point is reachable -- and that belongs with the phase's
"small Docker checks for each topology" rather than with this change set.

### Progress on 2026-09-03: peers can move without the table moving with them

`--prefix-scope total` (batch: `prefix_scope: total` on a test) reads
`--prefix-num` as the whole table and splits it evenly across the peers,
instead of giving that many prefixes to each of them.

The gap it closes is that **session count and table size are one axis today**.
`gen_conf()` hands every neighbour its own `gen_paths(p)` off a single shared
iterator, so the peers get disjoint prefixes and the table is `n * p`. Every
synthetic matrix in `benchmarks/` therefore sweeps both at once:
`2026-core-synth.yaml`'s `neighbors: [10, 50]` against `prefixes: [50_000,
100_000]` holds 500k, 1M, 2.5M and 5M routes, and no reader of that CSV can
separate "50 sessions were slower" from "five times the routes were slower".
`benchmarks/2026-peer-scaling.yaml` is the same three targets at 10, 25 and 50
sessions with 1,000,000 routes throughout.

Three decisions worth keeping:

- **It is normalised to a per-peer count before anything reads it**, in
  `bench()` beside the image resolution and in `expand_batch_cells()` for a
  batch -- never carried forward as a scope. `-n 50 -p 100000 --prefix-scope
  total` and `-n 50 -p 2000` are the same workload, so they must produce the
  same scenario (verified byte-identical through `./bgperf2.py config`), the
  same cell identity, the same row and the same bar. Everything downstream is
  keyed on the per-peer number -- the CSV column is literally `prefixes per
  peer`, `bench_output_prefix()` names every artifact from `prefix_num`, and
  `create_graph()` groups its bars by it -- so a scope that survived into those
  would have to become a fourth dimension in all three, for a distinction that
  describes how the run was *asked for* rather than what it did.
- **An inexact division is refused rather than rounded or spread**, and refused
  for every combination of the two axes before the first container starts. A
  remainder means the peers do not all offer the same table, so `prefixes per
  peer` is a number true of none of them, each neighbour's `check-points`
  differs, and the monitor's own stops being `n * p`. A matrix is where such a
  split is easy to write without noticing -- 1,050,000 divides by 10 and 25 but
  not by 9 -- and finding out at cell three costs hours, so `check_batch_test()`
  checks the whole grid and the message names peer and prefix counts that would
  work rather than leaving the operator doing arithmetic on a full-table RIB.
- **It is refused for the MRT testers, on both paths.** `gen_conf()` sets the
  monitor check-point straight from `-p` for `gobgp` and `bgpdump2`, so `-p` is
  already the whole table there. The first version refused it only on the CLI:
  `check_batch_test()` and `expand_batch_cells()` never passed the tester, and
  `batch()` sets `prefix_scope: per-peer` on the synthesized args, so
  `bench()`'s own guard never saw it either. A batch would have divided a
  1,050,000-prefix MRT table by its peer count and reported CONVERGED at
  103,950 -- a tenth of the table -- with nothing in the row or the artifacts
  saying so, while `CLAUDE.md` and this note both claimed the combination was
  refused. The batch path is the one that matters: a CLI mistake costs one run,
  a batch mistake costs a matrix, and nobody is watching it. One MRT target
  poisons the whole test rather than only its own cells, because `prefixes` is
  a single axis shared by every target and a test mixing an MRT generator with
  a synthetic one under `total` cannot be right for both.
- **The axes are checked for being numbers before they are divided.** A quoted
  entry reached the arithmetic as a bare `TypeError` -- the traceback naming
  neither the test nor the key that `check_batch_test()` exists to eliminate,
  reintroduced by putting arithmetic in front of the type check.
- **A suggestion the operator cannot act on is worse than none.** The refusal's
  "or N peers" fell through to 1 at one end and walked to `prefix_num` at the
  other, so a prime-ish table was answered with *or 1 or 4999999 peers* after a
  fifth of a second of scanning. It reads as the tool having thought about it.
  The scan is bounded by `MAX_SUGGESTED_PEERS` now, and the clause is omitted
  when nothing usable exists -- the prefix counts either side are always exact
  by construction, so the message is never empty.

`benchmarks/2026-peer-scaling.yaml` is deliberately **not** registered in
`scripts/run_2026_suite.sh`. The driver's `suite_config()` knows four suites
and `all` runs those four; adding a fifth extends what
`continue the 2026 benchmark campaign` runs, and what that campaign benches is
the campaign owner's decision rather than a Phase 5A implementation detail --
the run ID, the results root and the suite sequence are all fixed by that
contract. Whoever adds it should add it there rather than running it by hand,
since a `bgperf2.py batch` outside the driver gets none of its `COMPLETE`
markers, config snapshotting or metadata, and its rows are then not comparable
with the rest of the run ID.

Its numbers are chosen so the suite can answer its own question, which took
review to notice. The first version was 100,000 routes over up to 50 sessions
in a single pass: the baseline's smallest cell (10 peers x 20,000) finished in
4-5s, `elapsed (s)` is whole seconds off a 1s monitor poll, so the entire
10-to-50-peer difference would have sat inside one or two polls and the axis
would have been unreadable at the resolution of the instrument. And a
single-pass test has no dispersion, so `apply_variance_rule()` withholds every
verdict and prints nothing -- a suite whose output cannot say whether its
differences are real is the reading error that rule exists to prevent. It is
1,000,000 routes over three passes now, and the split stays exact at 10, 25 and
50 peers as it does for any multiple of 50.

**The suite trades one confound for a smaller one, and says so.** With
`tester_type: bird` the generator runs one `bird` per neighbour, so the 50-peer
cell runs 50 generator daemons against the 10-peer cell's 10, on the same box.
The peer axis therefore still moves two things -- the target's session count
and the generator fleet -- and no published column can separate them: `bird`
and `birdc` are in `contention.BGPERF_PROCESSES`, so `max foreign cpu %` cannot
report that load by construction, and `min idle%` is host-wide and cannot
attribute it. This is the same blind spot `CLAUDE.md` records for the
offering-poll `birdc` execs. It is a much smaller confound than the one removed
-- generator processes rather than 50x the routes -- and the `tester_fleet`
section says whether the load was delivered, which is the closest thing to
evidence about it. The suite header states it, and whoever registers the suite
should read `tester_fleet` alongside the timings rather than the timings alone.

One pre-existing defect was fixed on the way, because it blocked verifying the
change without Docker: **`./bgperf2.py config` could not be run at all.**
`gen_conf()` reads `tester_type`, `mrt_file` and `license_file`, and only the
`bench` subparser declared them, so a documented subcommand raised
`AttributeError` on every invocation. It is what proves the two forms produce
the same scenario.

No Docker run was needed or made: the change is confined to scenario generation
and matrix expansion, both of which are pure and covered by the new
`tests/test_prefix_scope.py` (84 tests); 814 total, Docker-free.

Two things review found that outlive this change. **A run with no peers or no
prefixes was never refused**: zero and negative pass a type check, and
`resolve_prefix_scope()` catches them only under `total`, so under the default
scope `gen_conf()` built a scenario with no testers and a monitor check-point
of `int(0 * 0.99)` -- satisfied at zero routes, so the run wrote a row that
reads as converged. Refused on the batch path first and then, a round later,
on the CLI as well: adding a single normalisation point in `bench()` is not the
same as adding a check there, and `bench -n 0` went through it untouched. And
**a test-level key written under a target was silently ignored**; see below.

Two corrections to earlier rounds of this same change set are worth recording,
because both were the fix being wrong rather than the original code:

- **The resolution pin was against the wrong constant.** `elapsed (s)` is
  quantised by *two* things and the coarser wins -- the `timedelta.seconds`
  truncation, always 1s, and the monitor poll interval, 1s today and a real
  knob. Pinning `METRIC_RESOLUTION` to the interval alone would have gone red
  if somebody polled twice a second, and the obvious fix then is to set the
  resolution to 0.5, which understates the truncation: two cells one whole
  second apart clear a 0.5 floor and are published `separated` on a rounding
  boundary, silently. The floor's own test would have reintroduced the defect
  the floor exists to prevent. It is `max(1.0, MONITOR_POLL_INTERVAL_S)` now.
- **`MAX_SUGGESTED_PEERS` was applied as an absolute ceiling** where its
  comment said "how far above the asked-for count", so anybody asking for more
  than 512 peers got no upward suggestion at all -- 513 peers was never offered
  625, which divides 1,000,000 exactly. Code and comment disagreeing is the
  class of defect this repository treats as a defect; it is a distance now. A
  round later it turned out to reach the degenerate advice from the other end
  as well -- a peer count equal to the table size divides it exactly and offers
  each session one route -- so both ends stop at one prefix per peer.
- **A rival's missing metric was described by its passes.** A cell can have
  observations and still no median, because a non-numeric value withholds the
  column, and deciding the reason on "were any passes not observed" described
  such a cell as `1 failed` -- printed two lines under its own `2 of 3 passes
  observed`, so the document contradicted itself and pointed at the failed pass
  rather than at the unreadable value. Where any pass was observed, the
  metric's own reason leads and the pass counts are an addition to it. This is
  the fourth variant of the failed-against-not-run collapse, and the first
  where the missing thing was neither.

Three more rounds later, three gaps of one shape -- a rule applied at one entry
point and not another. This change set produced that shape fifteen times in all, which is the thing
worth remembering rather than any of the individual defects. Eight of the
fifteen were in guards or defaults added by an earlier round of this same
review -- a guard is code and gets the rule as wrong as the code it guards, one
of them replaced a loud failure with a quiet wrong answer, and three more got a
rule wrong that the guard immediately beside them already had right:

- **`config()` had the scope resolution and not the positive-count guard**, and
  it is the path that most needs it. `bench -f` deliberately skips the guard on
  the reasoning that a scenario file states its own neighbours; a scenario
  stating *none* -- `check-points: [0]` and no testers, satisfied at zero
  routes -- goes straight through, and the tool that would have produced that
  file is this one.
- **A batch target that omitted `tester_type` passed every up-front check and
  then killed the batch mid-run.** `batch()` gave every unset field `None`, and
  `gen_conf()` routes anything that is not `exa` or `bird` down the MRT branch,
  where a missing `mrt_file` is a bare `exit(1)` -- the multi-hour failure
  `check_batch_test()` exists to prevent, reached through the same key it now
  reads to detect an MRT generator. `BATCH_FIELD_DEFAULTS` gives it the CLI's
  own default so the two paths agree about what an unstated generator is.

  A side effect worth knowing: this makes `benchmarks/big-tests.yaml` runnable
  for the first time. Its nine targets all omit `tester_type`, so every cell of
  it previously died at that `exit(1)` -- the same file `CLAUDE.md` already
  records as having reached expansion with a missing `filter_test` axis.
  Synthetic generation is what those tests want (1,000 prefixes across up to
  5,000 neighbours), so the default is the right answer for that file rather
  than a guess that happens to run.

  That claim was written a round too early: the default closed the
  *omitted-`tester_type`* shape and this note said the class was closed, while
  two more shapes of it were still open. **An MRT target with no `mrt_file`**
  reaches the same `exit(1)` -- the guard now refuses both halves, since the
  MRT set is computed two lines away. And **`tester_type:` with nothing after
  it** parses as a present key holding `None`, so a key-presence test skipped
  the default for precisely the slip it was added to catch;
  `batch_target_field()` keys on the value instead. It *reads* the default
  rather than writing it into the target, because the target dict is part of
  the cell identity and the cell id is what `--resume` matches on -- filling a
  default into it renames every completed cell of every in-flight batch, which
  the first attempt did and three existing tests caught.

  And that guard was *still* keyed on the wrong predicate. `gen_conf()` routes
  on `tester_type not in ('exa', 'bird')`, not on the MRT list, so anything
  unrecognised is treated as an MRT injector -- and a batch target bypasses
  argparse's `choices` entirely, so `tester_type: brid` passed the guard and
  died at the same `exit(1)`. The generator is validated against
  `TESTER_TYPES` now, which is also the CLI's `choices`, so the two cannot
  drift. The same guard additionally refused `file:` targets, whose generator
  never reaches config generation at all, and raised a bare `TypeError` on a
  target with neither name nor label -- the traceback this function exists to
  eliminate, produced by the checks added to eliminate it. A target must have
  a `name`.
- **`filter_type` was missing from `BATCH_FIELD_DEFAULTS`**, one field over
  from the one that prompted it. `batch()` handed `bench()` `None`,
  `gen_conf()` writes `'filter': {args.filter_type: assignment}`, and every
  target's config writer looks for the literal key `'in'` -- so a batch target
  with policy counts and no `filter_type` produced `filter: {null: [p2]}`, ran
  unfiltered, and reported as a filtered run. Latent rather than active, since
  no committed config sets those counts. It also changes the shape of every
  generated GoBGP-family config -- `import-policy-list: []` and
  `default-import-policy: accept-route` where there was previously no
  `apply-policy` block -- which is GoBGP's own default and so behaviourally
  identical, but worth knowing before diffing a generated config against an
  older run's.
- **And that default made a wrong workload quiet.** A target naming
  `mrt_injector` or `mrt_file` and no `tester_type` used to fail loudly:
  `None` took `gen_conf()`'s MRT branch and `bench()` stopped at `invalid
  mrt_injector: None`. With the default it became a *synthetic BIRD run* --
  `mrt_file` never read, the monitor check-point `n * p` instead of `p` -- that
  converges and writes a row and artifacts with nothing saying the table was
  never played back. A default that replaces a crash with a plausible wrong
  answer is worse than the crash, so the intent those two keys state is now
  checked against the generator that will actually run. This is the strongest
  argument in the list for why a default on this path needs its own guard: the
  fix for a loud failure created a silent one.

  That guard was wrong twice over on its first outing, both times in ways its
  own sibling ten lines away already handled. **`mrt_injector` was read as a
  statement of intent when `gen_conf()` never reads it at all** -- the injector
  is derived from `tester_type` -- so `tester_type: gobgp` beside
  `mrt_injector: bgpdump2` passed every check and played back through gobgp,
  against a 0.93 check-point factor instead of 0.99, writing a row that reads
  as a bgpdump2 run. A key the run ignores is now refused when it disagrees
  with the one it obeys. And **the guard did not exempt `file:` targets**,
  though the `mrt_file` rule beside it does and for a stated reason: such a
  target never reaches `gen_conf()`, so its generator is inert and the advice
  the guard prints would not change what runs. An `mrt_file` left on a scenario
  target as documentation failed the batch before the first container.

  Then the *default* needed the same exemption the guards had. A scenario
  target's generator is inert, but `tester_type` is not inert on the `-f`
  path: `write_provenance()` records it as `run.tester_type`,
  `collect_provenance()` labels the tester role with it, and
  `bench_output_prefix()` puts it in the stem. So defaulting it wrote
  `"tester_type": "bird"` into the versions manifest of a run that played back
  an MRT file, and named that run's artifacts `bird_bird_...`. Provenance
  never guesses -- absent is the honest value -- and a scenario target now
  takes no defaults at all, which also required exempting it from the
  generator-validity check, since its tester is then `None`. That exemption has
  to be uniform across all four checks or one contradicts the rest.

- **And the CLI never refused MRT intent with a synthetic generator at all.**
  The batch guard above was added for that failure; `bench` and `config`
  accepted it. `-t frr_c -n 10 -p 1050000 --mrt-file rib.mrt` with `-g
  bgpdump2` forgotten offers 10.5M *synthetic* routes against a check-point of
  `n * p * 0.99` instead of `p * 0.99`, converges, and publishes a row and
  artifacts that read like the MRT run it is not. The rule is one function
  (`mrt_keys_without_an_mrt_generator()`) applied at all four entry points now,
  rather than three statements of it that were only ever going to be two.
- **And then only one direction of it.** The mirror -- an MRT generator with no
  `--mrt-file` -- was refused on the batch path and not on the CLI, and it
  fails differently: loud, but late. `gen_conf()` ends at a bare `exit(1)`, and
  by then `bench()` has run `remove_target_containers()`,
  `remove_old_containers()` and `rmtree()` over the config directory, so the
  previous run's containers and logs are gone -- the ones this repository keeps
  deliberately so a failure can be investigated, and the reason the other
  guards sit above the teardown. `check_generator_matches_workload()` refuses
  both directions now, and a test asserts nothing was torn down first.

  A known gap deliberately left: `exabgp` as an MRT injector
  (`ExaBGPMrtTester`) is reachable only from `bench()`'s scenario-reading
  branch, not from `-g` or from a batch target. That predates this change and
  closing it means deciding whether the generator is supported, which is not a
  peer-scaling question.
- **The `-f` refusal was unreachable from the batch path**, because `batch()`
  pins `prefix_scope: per-peer` on the synthesized args once the division has
  happened. A scenario target under `total` would have divided `prefixes`,
  recorded the divided count in the cell id, the `prefixes per peer` column and
  every artifact name, and then run whatever the file describes. Refused in
  `check_batch_test()`, where the batch can still see the scope.

On that second one: **a test-level key written under a target is silently
ignored**, which is worth keeping beyond this change. There is no allowlist of
target keys -- `batch()` reads a fixed field list and ignores the rest -- and
every knob an operator sets *is* a target key (`threads`, `tester_type`,
`mrt_file`, `image`, `version`), so putting a test key one level too deep is
the natural slip and each one fails silently and expensively: `prefix_scope:
total` under a target runs that target at `neighbors x prefixes`, which is
5,000,000 routes instead of 100,000 at 50 peers, and it converges and writes
rows and bars that read as a peer sweep. `BATCH_TEST_ONLY_KEYS` refuses the
seven of them at target level, which is the reverse of the unknown-key check
and needs no enumeration of what a target may legitimately carry.
