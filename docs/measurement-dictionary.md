# Legacy CSV Measurement Dictionary

This dictionary describes the compatibility CSV emitted by `bgperf2.py`
alongside typed lifecycle events. The column order is a compatibility contract:
new fields must be appended, not inserted. Historical rows used wall-clock
sampling. Current rows use the monitor's monotonic observation timestamps but
preserve the existing whole-second rounding and legacy formulas; the separately
named monotonic phase intervals live in each run's `.events.json` artifact.

| Column | Unit/type | Definition and interpretation |
|---|---|---|
| `name` | string | Run label used in CSV rows and graph filenames. Defaults to the target name and selected version; `--label` overrides it. |
| `target` | string | Target implementation key selected by `--target`. |
| `version` | string | Version reported by the running target container. |
| `peers` | count | Configured number of route-source tester peers. |
| `prefixes per peer` | count | Configured prefixes per tester peer. For MRT playback this is the configured/scanned workload value, not an independently observed offered count. |
| `required` | prefixes | Configured monitor accepted-prefix checkpoint. Reaching it shortens the stability-assurance window; stable completion may still be reported below it when target-neighbor completion evidence is available. It is 99% of the configured synthetic total, 99% of the scanned MRT prefix count for bgpdump2, or 93% of that MRT count for GoBGP playback. |
| `received` | prefixes | GoBGP monitor accepted-prefix count in the sample that completed or failed the run. |
| `monitor (s)` | seconds | Time spent waiting for the monitor's BGP session with the target to become established, before the measured sampling loop starts. |
| `elapsed (s)` | seconds | Monitor-observed convergence boundary in whole seconds from the tester launch origin. The controller estimates the boundary by subtracting the trailing stability-assurance samples from the final monitor sample. It is not necessarily a literal full-table time or the whole-run time. |
| `prefix received (s)` | seconds | Whole seconds from tester launch origin to the first monitor sample with a nonzero accepted-prefix count. Zero also represents a run that never observed a prefix, so failure state must be checked. |
| `testers (s)` | seconds | Legacy post-first-prefix interval: `elapsed (s) - prefix received (s)`. Despite its name, it does not measure tester duration or tester completion and cannot establish an injection bottleneck. |
| `total time` | seconds | Wall-clock seconds from the start of benchmark setup through convergence/failure handling up to the stop point in `finish_bench()`. Post-stop log scanning, graphing, and artifact writing are excluded. |
| `max cpu %` | percent | Maximum sampled CPU use of the target container, rounded to an integer. Values may exceed 100% on multicore hosts. |
| `max mem (GB)` | GiB | Maximum sampled target-container memory use, divided by 1024^3 and rounded to three decimal places. The historical `GB` label is retained for compatibility. |
| `min idle%` | percent | Minimum sampled host-wide idle CPU percentage, rounded to an integer. It includes bgperf2's own workload and is not a foreign-contention measure. |
| `min free mem (GB)` | GiB | Minimum sampled host available memory, divided by 1024^3 and rounded to three decimal places. The historical `GB` label is retained for compatibility. |
| `flags` | string | `-s` when single-table mode was selected; otherwise empty. |
| `date` | date | Controller-local row creation date in `YYYY-MM-DD` form. |
| `cores` | count | Logical CPU count reported by the benchmark host. |
| `Mem (GB)` | string | Total benchmark-host memory formatted by `mem_human()` with binary divisors and a unit suffix. |
| `tester errors` | count | Tester log lines classified as errors after convergence timing stops. Known benign BIRD messages are excluded by the tester parser. |
| `tester timeouts` | count | Tester log lines classified as timeouts after convergence timing stops. |
| `failed` | string | `FAILED` when convergence tracking declares failure; otherwise empty. |
| `MSG` | string | Convergence failure explanation when available; otherwise empty. |
| `filters` | string | Requested filter/policy test identifier; otherwise empty. |
| `max foreign cpu %` | percent of one core | Maximum sampled CPU attributed to non-bgperf2 processes above the controller's baseline, rounded to an integer. Use it to qualify contention; it is not host utilization. |
| `target image` | string | Normalized container image reference used by the target. |
| `tester version` | string | Sorted, semicolon-separated versions reported for distinct tester images. An empty or `UNKNOWN` value means provenance was unavailable, not that all testers shared a known build. |
| `monitor version` | string | Version reported by the GoBGP monitor container. |

The canonical compatibility test for the positional schema and the legacy
`testers (s)` formula is `tests/test_stats_contract.py`. Historical CSV rows
must be interpreted with this dictionary; they must not be rewritten to match
future lifecycle-event semantics.

## Event artifact: the `measurements` section

Each run writes `<prefix>.events.json` (`bgperf2/measurement-events/v1alpha1`),
whose `measurements` object holds the intervals the monitor owns. They are
derived from named events on the controller's monotonic clock, whose origin is
stamped once per run before the testers are launched.

| Field | Unit/type | Definition and interpretation |
|---|---|---|
| `first_prefix_s` | seconds | Bench clock origin to the first monitor sample with a nonzero accepted count. The unrounded monotonic form of the legacy `prefix received (s)` column. |
| `first_prefix_resolution_s` | seconds | How coarsely `first_prefix_s` is placed: the gap between the poll that saw the first prefix and the previous look, measured from the clock origin on the first poll. The monitor loop execs `gobgp neighbor -j` and only then waits, so this is the gap it *achieved*, floored at the 1s cadence it asked for. A `first_prefix_s` at or under this number was not resolved by the monitor. |
| `convergence_s` | seconds | Bench clock origin to the first monitor sample at or above the configured check-point. `null` for a run that never reached it. |
| `convergence_resolution_s` | seconds | The gap bounding that poll, read the same way. |
| `assurance_s` | seconds | Required count to the sample at which the assurance policy declared the run complete. `null` for a run that failed or was still in assurance. |
| `assurance_resolution_s` | seconds | The wider of the two monitor polls bounding it. The confirmation carries the resolution of the sample it ruled on, not a gap to the moment the verdict was stamped: assurance is a decision about a sample, not a fresh look at the monitor. |

## Event artifact: the `testers` section

Each run also writes `<prefix>.events.json` (`bgperf2/measurement-events/v1alpha1`).
Generators that can be asked what they put on the wire — the BIRD synthetic
tester and each bgpdump2 MRT injector — get a `testers` entry keyed by
container name:

| Field | Unit/type | Definition and interpretation |
|---|---|---|
| `tester_startup_s` | seconds | Bench clock origin to the poll where *every* session this container drives was established. The last session, not the first. |
| `startup_resolution_s` | seconds | How coarsely `tester_startup_s` is placed: the gap between the poll that first saw every session established and the previous look. Sessions are routinely up on the very first poll, whose gap is measured from the bench clock origin — the clock starts before the testers are launched — so this is often the whole of `tester_startup_s`, which is the honest statement that readiness was not resolved at all. |
| `injection_s` | seconds | First poll with a nonzero offered count to the poll where every session had offered its whole configured table. `0.0` means the table was already fully offered when the instrument first looked — an unresolved interval, not an instant injection. **Not comparable across `--tester-trace-io`**: that flag multiplies a bgpdump2 injector's log volume by roughly the size of the table the target echoes back to it, and the log reader consumes at most `BlasterLogReader.READ_MAX` per poll, so a completion the generator wrote can be read several polls later and stamped late. Measured on a 2 x 500,000-prefix traced run: one injector wrote 22.5 MB before its `End-of-RIB` and this field read 5.0s against the generator's own 1.4996s. Read `reported_injection_s` for a traced run. |
| `injection_resolution_s` | seconds | How coarsely `injection_s` is placed: the wider of the two gaps bounding it, i.e. the looks that found the first update and the completion. It is the *achieved* gap, never the requested cadence — a poll reads before it waits, so the read is part of the resolution — floored at the requested cadence, which the loop cannot beat. Read `injection_s` against it: an injection at or under this number is unresolved, not fast. Deliberately **not** shared with `startup_resolution_s`: one number cannot bound two intervals, and folding in a late first poll would qualify a 1s-resolved injection with a 30s bound. `null` for an event stream not produced by a poll loop, and `null` whenever `injection_s` is -- an interval that was never measured has no bound to publish. |
| `post_injection_tail_s` | seconds | **Signed.** From this generator's completion to the first monitor sample at or above the check-point: what the run spent once the workload had been handed over. This is the measurement the legacy `testers (s)` column was read as providing and never was — that column starts at the monitor's first prefix and knows nothing about the generator. A negative value is a result, not a fault: the monitor reaches the check-point while the generator is still finishing whenever the check-point sits below the full table, or the generator is still flushing sessions the check-point did not need, and clamping it at zero would publish such a run as one with an instant tail. `null` when either end is missing — a run that never reached the check-point, or a generator that never completed. It is never measured from `tester_last_update` instead: that is the last increase *observed*, not the end of the workload, and substituting it would produce a plausible number for exactly the runs where the generator is under suspicion. |
| `post_injection_tail_resolution_s` | seconds | The wider of the two polls bounding it — one from the generator's loop and one from the monitor's, since it is the only published interval spanning both instruments. A tail whose **magnitude** is at or under this number says the two events landed within one look of each other, in either direction — each end could have happened anywhere inside its own look, so the interval is not distinguishable from zero. It does not say the tail was short. |
| `reported_injection_s` | seconds | The generator's *own* measurement of its send, where it makes one — for bgpdump2, the `End-of-RIB, walk time` it logs. It is **not** a sharper `injection_s`: a different clock and the generator's own definition of sending (bgpdump2's walk time is encode time bounded by its 256KB write buffer, so it tracks the wire only on a table large enough to fill that buffer). Read it beside `injection_s`, never instead of it — and it is the only thing that says anything at all when `injection_s` is `0.0` because the whole walk finished inside one look. Across a container's sessions it is the longest, not the sum: sessions send at the same time, so it is a lower bound on the container's whole send span. Published only when every session reported one; `null` for a generator that measures nothing (BIRD). No rate is derived from it — dividing an encode-side count by an encode-side interval gives a send rate the generator never achieved. |
| `offered_prefixes` | prefixes | The generator's own cumulative count at completion, summed across its sessions. Published only when every session was legible; a partial read reports `null` rather than a shortfall. |
| `offered_in_interval` | prefixes | How much of `offered_prefixes` arrived inside `injection_s`. The rate below is derived from this, not from the total. `null` means the generator's counter went backwards during the run — BIRD clears a protocol's route-change stats when the protocol restarts — so the interval is real but its content is unknown. |
| `offered_rate_pps` | prefixes/second | `offered_in_interval / injection_s`. It is `null` in three different cases, told apart by reading `injection_s` **and** `offered_in_interval` together — neither field discriminates on its own: (1) an injection that began and finished inside one look, so there is no interval to divide by (`injection_s` is `0.0`, `offered_in_interval` is `0` — see `injection_resolution_s` for how wide that look was); (2) a measured interval that none of the table crossed (`injection_s` is greater than `0.0`, `offered_in_interval` is `0`), which is the ordinary shape for a generator that reports its own completion, since a bgpdump2 injector's count is final at the poll before it logs `End-of-RIB` — the interval is real and says nothing about the send, and `0 prefixes/s` would describe a generator that delivered everything as one that sent nothing; (3) a generator whose counter reset mid-run, so nothing can be said about what crossed the interval (`offered_in_interval` is `null`). **Read it only beside `offered_in_interval`**: for BIRD 2.19 that share is usually a small tail of the table, and the rate is then a slope of the poll cadence rather than the generator's send rate. |
| `octets_on_wire` | bytes | The generator's cumulative count of bytes a successful `write()` put on the socket, read at the poll that saw completion and summed across sessions. The one wire-side number here: `offered_prefixes` is counted at the encoder, so where the encoder outruns the socket the two diverge — a real bgpdump2 mid-walk line reads 9,981 prefixes encoded against 88 octets written. It is a property of the paths played back, not of the prefix count: two injectors sending 10,000 prefixes each from different MRT peers wrote 183,852 and 259,226 octets. Published only when every session was legible; `null` for a generator that does not count bytes (BIRD). |
| `backpressure` | object | `{"available": false, "reason": ...}` where the generator reported no blocked-write counter, otherwise `{"available": true, ...}` carrying whichever of four maxima the generator supplied. Two are queue depths, from BIRD 3: `max_tx_pending_bytes` and `max_pending_prefixes` (BIRD 2.19 has neither). Two are cumulative counts, from bgpdump2 and only when the run passed `--tester-trace-io`: `max_blocked_writes`, writes the socket took only part of, and `max_send_stalls`, encode passes that found no room in the 256KB session buffer — which is also the only place a `write()` returning `EAGAIN` appears, since bgpdump2 logs nothing for one. Each is a maximum over sessions as well as polls, never a sum, so it stays a lower bound when one session could not be read. Never `0` for a generator that cannot answer: for bgpdump2 the counts are published as `0` only when the log itself proves the class was on, so `available: false` on an injector means either that the generator has no counter **or** that the run did not ask for one — a distinction the flag, not this field, decides. |
| `read_failures` | object | `{"polls": N, "first_reason": ...}` when one or more polls could not be read at all (the container was gone, the control socket refused). Present only when it happened; its absence means every poll was read. |
| `observation_error` | string | Present only when a poll was rejected and the recorder was retired mid-run. The events recorded before that point are still published. |

Two properties are deliberate. `expected` is always the configured table size
(`len(paths)`), never the generator's own report of what it loaded, so a
generator that loaded half its config cannot look complete. And an event is
absent rather than synthesized: a run whose generator never reported completion
has no `tester_complete` and a `null` `injection_s`, never an interval inferred
from monitor timestamps.

## Event artifact: the `tester_fleet` section

The same artifact carries one `tester_fleet` object beside `testers`, present
whenever a run had at least one generator that could be polled. It answers a
different question from the per-generator sections: those say which generator
was slow, this says whether the workload was offered at all. A ten-injector
full-internet run is why — reading that off ten sections means noticing the one
with a null interval.

Every aggregate is taken pessimistically, the way a container's own sessions
are combined: ready at the **last** generator, injection from the **earliest**
first update to the **slowest** completion, and completion all-or-nothing.

| Field | Unit/type | Definition and interpretation |
|---|---|---|
| `testers` | count | Generators polled in this run — the number of `testers` entries. |
| `testers_complete` | count | How many of them reported completion. |
| `incomplete_testers` | list of strings | The container names that did not, sorted. Non-empty means the workload was never fully offered, and every interval below is `null` as a result: an interval bounded by the generators that *did* finish would describe a run that did not happen. A generator that was never legible at all appears here too. |
| `tester_startup_s` | seconds | Bench clock origin to the readiness of the **last** generator, not the first. `null` if any generator was never seen ready. Note that `bench()` launches the tester containers serially before polling starts, so on a large fleet this absorbs the launch cost of the whole fleet. |
| `startup_resolution_s` | seconds | How coarsely `tester_startup_s` is placed: the gap bounding the poll that found the last generator ready. Same reading as the per-generator field. |
| `first_update_s` | seconds | Bench clock origin to the earliest first update across the fleet. `null` unless every generator completed. |
| `complete_s` | seconds | Bench clock origin to the slowest generator's completion. `null` unless every generator completed. |
| `injection_s` | seconds | `complete_s - first_update_s`: one span covering the whole fleet, **not** a sum of the generators' intervals — they send at the same time, so summing would total time nobody spent sending. |
| `injection_resolution_s` | seconds | The wider of the two polls bounding that span, which belong to two different generators. Read `injection_s` against it exactly as for a single generator. |
| `post_injection_tail_s` | seconds | **Signed**, and measured from `complete_s` — the **slowest** generator's completion — to the monitor's required count. A tail measured from the first generator to finish would charge the target with time it spent waiting for another injector. `null` unless every generator completed, under the same all-or-nothing rule as the rest of this section. Read exactly as the per-generator field. |
| `post_injection_tail_resolution_s` | seconds | The wider of the slowest generator's completion poll and the monitor's poll. |
| `reported_injection_s` | seconds | The **longest** of the generators' own reported send durations, never their sum, and a lower bound on the fleet's send span since generators that started at different moments cover more than the longest of them. Published only when every generator reported one. |
| `offered_prefixes` | prefixes | Summed across generators, published only when every one of them was legible. Nine of ten injectors is not a 10% shortfall, it is a different measurement. |
| `offered_in_interval` | prefixes | The sum of the per-generator `offered_in_interval` values. Each generator's own interval sits inside the fleet span and what it had already offered when its first poll landed is outside both, so this is a **lower bound** on what crossed the fleet span. |
| `offered_rate_pps` | prefixes/second | `offered_in_interval / injection_s`, and therefore a **lower bound**: a numerator measured over each generator's own interval divided by the wider fleet span. `null` under the same three rules as the per-generator field, and case (2) is the *normal* MRT shape rather than an edge case — every injector's sub-millisecond walk is over before its own first poll, so a span bounded by two injectors completing at different polls contains none of the table. The verified ten-injector run measured `injection_s` 1.0s with `offered_in_interval` 0 for 100,000 delivered prefixes. |
| `octets_on_wire` | bytes | Summed across generators under the same all-or-nothing rule; `null` where any generator does not count bytes. |

**A BIRD 2.19 offered count is queue-side.** `Export updates accepted` counts a
route when it is handed to the BGP protocol, not when it reaches the wire, so
the count and the completion fact are trustworthy while the duration is not.
Do not derive a tester-limited finding from a BIRD 2.19 rate.
