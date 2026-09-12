# Asking the generator what it sent

Tester offering polls, the fleet summary, and what a bgpdump2 injector reports about itself.

**Read this before editing:** `bgperf2.py` (the offering poll), `base.py` (`Tester.offering_stats()`), `tester.py`, `mrt_tester.py`, `measurements.py` (`TesterOffering`, `TesterEventRecorder`, `tester_metrics()`, `tester_fleet_metrics()`), `bird.py`, `bgpdump2.py`, `exabgp.py`, `monitor.py` (`Monitor.stats()`'s cadence and the rule that
both poll loops stamp the sample before the read)

These are invariants, not background: every rule here was written because the obvious alternative was tried and published a wrong number quietly. `CLAUDE.md` carries the one-line index; this file carries the argument.

---

## Asking the generator what it sent — tester offering polls

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

## What a bgpdump2 injector says about itself

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
