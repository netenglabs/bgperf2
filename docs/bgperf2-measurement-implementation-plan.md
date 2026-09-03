# bgperf2 Measurement Integrity Implementation Plan

## Purpose

This is the implementation plan for repairing `bgperf2` timing semantics and
adding the minimum campaign machinery needed for statistically useful version
comparisons. It is the focused implementation companion to
[`architecture-and-benchmark-roadmap.md`](./architecture-and-benchmark-roadmap.md).

The immediate problem is concrete: the CSV column named `testers (s)` is
currently calculated as `elapsed (s) - prefix received (s)`. It measures the
interval from the first monitor-visible prefix until convergence, not how long
the tester took to send the workload. It therefore cannot identify a tester
bottleneck.

The implementation objective is:

> Record tester, target/monitor, and assurance intervals from explicit events,
> preserve the legacy CSV without silently changing its meaning, and qualify
> bottlenecks only from measurements that can distinguish them.

## Relationship to the Follow-Up Campaign

The follow-up campaign is specified in
[`2026-64gb-timing-validation-plan.md`](./2026-64gb-timing-validation-plan.md).
That campaign must not begin until the release gate in this document passes.

The completed `2026-baseline` results remain historical end-to-end evidence.
Do not rewrite their CSV rows or reinterpret their `testers (s)` values as
tester completion times.

## Current State

The completed `2026-baseline` campaign established the implementation starting
point:

- all four planned suites completed;
- five known-bad observations have successful targeted reruns;
- the baseline contains useful end-to-end elapsed, CPU, memory, correctness,
  and provenance evidence;
- BIRD synthetic testing uses one BIRD tester container;
- full-internet MRT testing uses ten bgpdump2 injectors;
- bgpdump2 tester provenance currently lacks a reported version;
- the legacy `testers (s)` column does not record tester completion;
- the main comparison cells have one observation each and do not establish
  run-to-run variance.

This plan should repair those concrete gaps without reopening the completed
baseline campaign or broadening workload scope.

## Fixed Constraints

- Preserve the Docker-free import and unit-test property.
- Preserve existing CLI commands and continue emitting the legacy CSV during
  migration.
- Do not require more than the local 64 GB host.
- Run real Docker benchmarks only where the phase explicitly requires them.
- Never run benchmark suites concurrently.
- Preserve raw events and observations; derived metrics must be recomputable.
- Use monotonic clocks for durations. Wall-clock timestamps may accompany
  events for correlation but must not drive elapsed calculations.
- Treat tester limitation, target limitation, and observer limitation as
  findings supported by evidence, not conclusions inferred from two similar
  durations.

## Operational Ground Rules

Before each implementation change set:

```bash
git status --short
venv/bin/python -m pytest tests/ -q
```

Use focused tests while developing. Run the full unit suite before accepting a
change that touches shared timing, batch, convergence, result, or lifecycle
code. Run Docker verification only in the phases that call for it, using the
smallest realistic workload and `/var/tmp/bgperf`.

The implementation workflow is intentionally incremental:

- one reviewable change set per continuation;
- resume unfinished work before starting new work;
- no benchmark concurrency;
- no phase is complete until its tests and exit criterion pass;
- no follow-up campaign block runs from this plan;
- review the complete working diff before committing.

## One-Prompt Implementation Workflow

Use the stable operator prompt:

> continue the bgperf2 measurement implementation plan

Each invocation inspects durable state and completes no more than one smallest
reviewable change set from the first incomplete phase. It stops after tests and
review, then tells the user to use the same prompt again. This is the
implementation equivalent of the one-suite-at-a-time workflow used for
`2026-baseline`.

## Intended Measurement Contract

Every run should eventually expose these events when applicable:

| Event | Producer | Meaning |
|---|---|---|
| `bench_clock_started` | controller | Common monotonic origin for measured run phases |
| `tester_session_ready` | tester/controller | Tester is able to send updates |
| `tester_first_update` | tester | First workload update offered |
| `tester_last_update` | tester | Last workload update offered or queued successfully |
| `tester_complete` | tester | Generator has completed its defined send/flush contract |
| `monitor_first_prefix` | monitor | First nonzero accepted count observed |
| `monitor_required_reached` | convergence tracker | Required route threshold first reached |
| `monitor_last_change` | convergence tracker | Last accepted-count change before assurance |
| `convergence_confirmed` | convergence tracker | Assurance policy declares completion |

The initial derived intervals are:

- `tester_startup_s`: benchmark origin to tester readiness;
- `injection_s`: first tester update to tester completion;
- `first_prefix_s`: benchmark origin to first monitor-visible prefix;
- `post_injection_tail_s`: tester completion to required monitor state, allowed
  to be negative only when explicitly representing overlap and documented;
- `convergence_s`: benchmark origin to required monitor state;
- `assurance_s`: required state to confirmed completion;
- `total_time_s`: existing whole-run wall-clock duration, kept separate from
  the monotonic phase metrics;
- offered updates/prefixes and average offered rate;
- blocked-write/backpressure evidence where the tester can expose it.

MRT and synthetic testers may initially provide different levels of detail.
Unsupported events must be recorded as unavailable, not synthesized from
monitor timestamps.

## CPU Attribution Boundary

The legacy resource fields do not identify which benchmark role exhausted
CPU. `max cpu %` is the maximum sampled CPU use of the target container, while
`min idle%` is the minimum sampled idle percentage for the whole host. Tester,
monitor, controller, and kernel CPU are not reported separately, and the two
published extrema are not time-aligned evidence that can be subtracted.

Reliable component attribution requires time-aligned CPU measurements for the
target, tester, and monitor, together with host-wide CPU and explicit treatment
of controller and kernel overhead. Until that instrumentation exists, a run
with near-zero host idle may receive a `host CPU saturated` finding, but its
limiting component must remain `unresolved`. In particular, target-container
CPU near one logical core is consistent with single-core pressure, but a
maximum alone does not show whether that pressure was sustained or prove that
the tester caused the remaining host load.

## Result Compatibility Decision

Do not silently redefine the existing `testers (s)` CSV column. During the
migration:

1. Keep the column and document its historical formula as
   `post-first-prefix (legacy)`.
2. Add new named fields to the canonical structured result.
3. If CSV must expose new fields, append them at the end so positional graph
   code and old consumers do not shift.
4. Update graphs and reports to use named structured fields when available.
5. Add an explicit schema/tool version so old results remain interpretable.

## Implementation Sequence

### Phase 0: Correct the published contract

Status: complete on 2026-08-20. The legacy CSV dictionary, public/operator
documentation, implementation comment, and regression contract now agree.

#### Work

- Add a measurement dictionary covering every existing stats column.
- Correct `README.md`, `CLAUDE.md`, and operator-facing documentation so
  `testers (s)` is not described as generator duration.
- Update the 2026 report generator and review logic to stop assigning an
  injection-bound verdict from the legacy column.
- Add a regression test for the legacy formula so its actual historical
  meaning cannot drift again unnoticed.

#### Likely files

- `README.md`
- `CLAUDE.md`
- `AGENTS.md`
- `bgperf2.py`
- `tests/test_stats_contract.py`
- a measurement dictionary under `docs/`

#### Exit criterion

Documentation, code comments, tests, and report language agree on the meaning
of every existing timing column.

### Phase 1: Introduce typed lifecycle events

Status: complete on 2026-08-20. Monitor queue observations now carry monotonic
timestamps, the controller boundary converts them to typed events and named
durations, and an ordered event artifact is written atomically for converged
and tracked-failure runs.

#### Work

- Add a small typed event record using the standard library, preferably a
  dataclass plus an enum or stable string constants.
- Give every event a monotonic timestamp, producer, phase, and optional
  counters/details.
- Convert existing monitor and convergence timestamps at the queue boundary
  without migrating every daemon adapter at once.
- Keep compatibility conversion near the current `bench()` boundary.
- Persist an ordered event artifact even when a run fails.

#### Likely files

- a new pure module such as `measurements.py` or `events.py`
- `bgperf2.py`
- `convergence.py`
- focused unit tests under `tests/`

#### Tests

- Event ordering and monotonic-duration calculations.
- Missing/duplicate event behavior.
- Failure before first prefix and failure during assurance.
- Import and unit tests without Docker access.

#### Exit criterion

Existing monitor/convergence metrics are derived from named events in unit
tests, and a failed fake run still produces an event artifact.

### Phase 2: Instrument the BIRD synthetic tester

Status: complete on 2026-09-02. `bird.py` parses `birdc show protocols all` by
column name, `tester_offering()` summarises what a generator says it put on the
wire, and `measurements.TesterEventRecorder` turns polled sessions into
`tester_session_ready`/`tester_first_update`/`tester_last_update`/
`tester_complete` with `tester_metrics()` deriving `tester_startup_s`,
`injection_s`, `offered_prefixes`, `offered_in_interval` and
`offered_rate_pps`. `bench()` polls each generator that declares
`REPORTS_OFFERING` at the monitor's own 1s cadence, merges its events into the
one ordered `<prefix>.events.json` stream, and publishes the derived intervals
under a per-generator `testers` section beside `backpressure` and any
`observation_error`. Both parser and recorder are covered against real 2.19 and
3.3.2 captures.

`post_injection_tail_s` is deliberately still absent — it spans tester and
monitor events and needs a signed interval helper, since the contract allows it
to be negative when injection and convergence overlap.

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

#### Docker verification

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

#### Defect found while instrumenting: BIRD 3 targets reported accepted = 0

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

#### Work

- Define when the BIRD tester is ready, when it offers its first update, and
  when the configured table has been completely offered.
- Record expected and observed update/prefix counts.
- Record a completion signal through a file, control socket, log marker, or
  another explicit mechanism with a testable contract.
- Record blocked-write/backpressure evidence if BIRD exposes a reliable signal;
  otherwise record that it is unavailable.
- Do not treat container start or BGP establishment alone as injection
  completion.

#### Tests

- Parser tests using captured completion evidence.
- Timeout/missing-marker behavior.
- A tiny Docker verification with one tester and one target.

#### Exit criterion

A small synthetic run reports an independently observed injection interval and
the expected offered route count.

### Phase 3: Instrument bgpdump2 MRT playback

Status: complete on 2026-09-03. Every injector reports its own readiness, first
update, last update and completion into the run's event stream; the fleet is
summarised without letting the fastest injector speak for the rest; bgpdump2
reports its build identity; and blocked-write evidence is available behind
`--tester-trace-io`, off by default because asking for it perturbs the
generator's own walk time.

#### Progress on 2026-09-03: the injector log was empty, and now is not

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

#### Progress on 2026-09-03: every injector now reports into the event stream

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

##### Docker verification

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

##### Progress on 2026-09-03: the published poll resolution is now the achieved one

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

##### Progress on 2026-09-03: the generator's own two numbers reach the artifact

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

###### Docker verification

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


#### Progress on 2026-09-03: the injector now says which build it is

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

##### Docker verification

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

#### Progress on 2026-09-03: one line for whether the fleet delivered the load

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

##### Docker verification

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

#### Progress on 2026-09-03: the poll stops asking a generator that has finished

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

##### Docker verification

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

##### Also found by review of this change set: a bound on an interval nobody measured

`tester_metrics()` published `injection_resolution_s` from whichever bounding
poll it could find, so a generator that offered updates and then stalled --
`injection_s` null, no `tester_complete` -- carried a 1.0s bound on the
injection it never measured. `startup_resolution_s` already got this right, so
the two fields disagreed about their own contract, and a consumer keying on the
resolution would read a resolved interval that does not exist. The printed line
was unaffected: it handles a null `injection_s` before it reaches the
resolution. `_bounding_resolution()` now returns None unless every endpoint is
present. From the poll-resolution change set, not yet released.

#### Progress on 2026-09-03: blocked writes, and what asking for them costs

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

##### Docker verification

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

#### Work

- Make every injector report first-update and completion evidence.
- Aggregate ten peer injectors without allowing the fastest injector to hide a
  slow or failed peer.
- Record per-injector and aggregate start, finish, count, and rate.
- Add a bgpdump2 version command, build identity, or immutable image digest so
  `UNKNOWN` is no longer the only tester provenance.
- Keep MRT scanning/setup time separate from update playback.

#### Tests

- Pure aggregation tests for staggered completion, missing peers, and timeout.
- Captured-log parser tests.
- One minimal pinned-MRT Docker verification.

#### Exit criterion

A ten-peer MRT run reports all ten injector completions, aggregate injection
duration/rate, and reproducible bgpdump2 identity.

### Phase 4: Derive bottleneck findings conservatively

#### Work

- Add structured findings rather than a permanent validity boolean.
- Define candidate findings for tester limitation, target/monitor tail,
  observer uncertainty, foreign CPU contention, low memory, tester failure,
  and missing timing evidence.
- Require explicit completion and rate evidence for tester-limited findings.
- Treat TCP backpressure as an end-to-end interaction unless it can be assigned
  reliably to a component.
- Apply the CPU attribution boundary above: host saturation without time-aligned
  per-role CPU evidence leaves the limiting component unresolved.
- Keep the raw durations and the named qualification policy beside every
  verdict.

#### Tests

- Deliberately rate-limited tester is classified as tester-limited.
- Deliberately delayed target/monitor tail is not classified as tester-limited.
- Near-zero host idle without per-role CPU evidence is classified as host CPU
  saturation with the limiting component unresolved.
- Missing tester completion produces `inconclusive`, not a guessed result.

#### Exit criterion

The qualification policy distinguishes controlled tester limitation from a
controlled post-injection convergence tail.

### Phase 5: Add repetitions and order control

#### Work

- Add explicit repetitions to batch configuration or a validation runner.
- Assign stable repetition IDs and preserve resume behavior.
- Support deterministic randomized order from a recorded seed, or a documented
  rotating/block order if randomization would complicate resume excessively.
- Preserve every raw observation.
- Produce median, min/max, dispersion, and coefficient of variation without
  hiding individual runs.
- Expand from three to five runs only under a named variance rule.

#### Tests

- Batch expansion and stable naming.
- Resume after interruption within a repetition.
- Seed reproducibility.
- Aggregation with failures and missing repetitions.
- Custom YAML version strings such as `10.10` remain strings.

#### Exit criterion

A fake-runtime batch can run three repetitions in deterministic mixed order,
resume safely, and produce auditable summary statistics.

### Phase 5A: Add BIRD architecture workload controls

#### Work

- Add a peer-scaling workload that can increase session count while keeping
  total route count modest.
- Add a path-diversity mode in which multiple peers announce competing paths
  for the same prefixes instead of always generating disjoint prefixes.
- Add configurable export fan-out so one target table can feed multiple
  receiver sessions without treating the extra receivers as route sources.
- Add bounded withdrawal/reannouncement bursts with explicit operation counts
  and completion events.
- Add a loaded-table policy reload/recalculation action and record its start,
  completion, resulting route counts, and CPU interval.
- Preserve independent ingress, table-selection, export, and monitor timing so
  parallel work is not collapsed into one end-to-end number.

These controls target BIRD 3's documented worker-thread responsibilities:
BGP protocols, routing-table maintenance, and decoupled exports. They are
generic benchmark primitives, not BIRD-specific shortcuts.

#### Tests

- Prefix overlap and competing-path accounting.
- Multiple receiver counts without multiplying ingress counts.
- Deterministic churn operation generation and completion.
- Policy reload completion, failure, and final-state validation.
- Small Docker checks for each topology before a combined calibration.

#### Exit criterion

A bounded fake/runtime suite can distinguish high peer count, competing-path
selection, export fan-out, policy recalculation, and churn while preserving
correct final route counts and timing events.

### Phase 6: Calibration and release gate

#### Work

- Add the smallest realistic synthetic and MRT calibration configs.
- Demonstrate a controlled slow tester and a controlled target/observer tail.
- Run one BIRD synthetic and one bgpdump2 MRT calibration on the local host.
- Review CPU contention, memory, correctness, provenance, and event ordering.
- Record the measurement schema version used by the follow-up campaign.

#### Release gate

The follow-up campaign may begin only when all are true:

- actual tester completion is independently recorded for BIRD and bgpdump2;
- derived timing fields have unit tests;
- controlled calibration cases produce the expected findings;
- a real synthetic and MRT smoke run passes;
- results identify all tester images/builds;
- repetition and order controls pass resume tests;
- the BIRD architecture workload controls pass their topology and accounting
  tests;
- the full unit suite remains Docker-free;
- documentation and report generators use the new contract.

## Explicit Non-Goals

- Rewriting the orchestrator.
- Distributed execution before a single-host ceiling is demonstrated.
- Adding every dynamic BGP workload before initial-table timing is trustworthy.
- Buying or assuming access to larger-memory hardware.
- Re-running the completed baseline under changed semantics.
- Publishing a composite score.

## Review and Commit Discipline

Each phase should be a reviewable change set. Before committing:

1. Run focused unit tests.
2. Run the full unit suite when shared lifecycle or result code changed.
3. Run a real benchmark only when the phase requires Docker verification.
4. Review the working and staged diff.
5. State explicitly whether a real benchmark was run.
6. Keep `AGENTS.md` and `CLAUDE.md` aligned when the operator contract changes.

## Continuation Prompt Contract

Use this exact prompt in a new session:

> continue the bgperf2 measurement implementation plan

The operator contract for that prompt is:

1. Read this plan and inspect the working tree, recent commits, tests, and any
   durable phase notes.
2. Resume unfinished work before selecting a new phase.
3. Implement exactly one smallest reviewable change set from the first
   incomplete phase.
4. Run the proportionate tests and required Docker verification.
5. Review the complete diff and fix findings.
6. Stop after that change set is complete and reviewed.
7. Tell the user to use the exact same prompt for the next change set.

## Suggested Execution Order

1. Correct the published measurement contract.
2. Introduce typed lifecycle events and event artifacts.
3. Instrument the BIRD synthetic tester.
4. Instrument ten-peer bgpdump2 completion and provenance.
5. Derive conservative bottleneck findings.
6. Add repetitions, stable IDs, order control, and summaries.
7. Add peer-scaling, path-diversity, export-fan-out, policy-reload, and churn
   workload controls.
8. Run controlled and real calibration checks.
9. Open the release gate for the 64 GB timing validation campaign.

## Bottom Line

The next implementation work is not a rewrite and not a larger benchmark. It
is a sequence of small, tested changes that makes tester completion observable,
keeps old results readable, and creates a release gate for the new campaign.
Use the same continuation prompt after every reviewed change set.
