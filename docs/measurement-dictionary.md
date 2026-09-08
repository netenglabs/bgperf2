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
| `prefixes per peer` | count | Configured prefixes per tester peer. For MRT playback this is the configured/scanned workload value, not an independently observed offered count. The table the target ends up holding is `peers x prefixes per peer` only at the default path diversity; under `--path-diversity D` the peers are dealt into groups of `D` that each announce one shared block, so the fleet offers that many paths for `(peers / D) x prefixes per peer` distinct prefixes. The diversity is recorded as `run.path_diversity` in `<prefix>.versions.json` and appears in the artifact stem as `pd<D>`; it is not a CSV column, and a run whose workload came from a scenario file (`-f`) records `null` rather than asserting a diversity bgperf2 did not configure. |
| `required` | prefixes | Configured monitor accepted-prefix checkpoint. Reaching it shortens the stability-assurance window; stable completion may still be reported below it when target-neighbor completion evidence is available. It is 99% of the configured synthetic total, 99% of the scanned MRT prefix count for bgpdump2, or 93% of that MRT count for GoBGP playback. The synthetic total is the number of **distinct** prefixes, not the number of paths offered: the monitor counts what the target re-advertises, which is one best path per prefix, so it is `(peers / path diversity) x prefixes per peer`. |
| `received` | prefixes | GoBGP monitor accepted-prefix count in the sample that completed or failed the run. Unaffected by `--receivers`: export fan-out adds sessions the target advertises the same table to, and they announce nothing, so neither this nor `required` moves with the receiver count. The fan-out is recorded as `run.receivers` in both `<prefix>.events.json` and `<prefix>.versions.json` and appears in the artifact stem as `rx<N>`; it is not a CSV column, and a run whose sessions came from a scenario file (`-f`) records `null`. Receivers run the same `bgperf/gobgp` image as the monitor, so the `monitor version` column describes their build too. What the fan-out was served, and when, is in the artifact's `export` section and in no CSV column. |
| `monitor (s)` | seconds | Time spent waiting for the monitor's BGP session with the target to become established, before the measured sampling loop starts. |
| `elapsed (s)` | seconds | Monitor-observed convergence boundary in whole seconds from the tester launch origin. The controller estimates the boundary by subtracting the trailing stability-assurance samples from the final monitor sample. It is not necessarily a literal full-table time or the whole-run time. Unaffected by `--churn-prefixes` and `--policy-reload-blocks`: both run after this boundary has been settled, and what they cost is in the artifact's `churn` and `policy_reload` sections. |
| `prefix received (s)` | seconds | Whole seconds from tester launch origin to the first monitor sample with a nonzero accepted-prefix count. Zero also represents a run that never observed a prefix, so failure state must be checked. |
| `testers (s)` | seconds | Legacy post-first-prefix interval: `elapsed (s) - prefix received (s)`. Despite its name, it does not measure tester duration or tester completion and cannot establish an injection bottleneck. |
| `total time` | seconds | Wall-clock seconds from the start of benchmark setup through convergence/failure handling up to the stop point in `finish_bench()`. Post-stop log scanning, graphing, and artifact writing are excluded. **Churn is inside it**: the bursts run before that stop point, so a `--churn-prefixes` run's `total time` is not comparable with a run that did not churn. The artifact stem carries `ch<C>x<B>` so the two are at least distinguishable by name. The same holds for `--policy-reload-blocks`, whose stem carries `pr<N>`. |
| `max cpu %` | percent | Maximum sampled CPU use of the target container, rounded to an integer. Values may exceed 100% on multicore hosts. Covers the delivery of the table only: samples taken during churn bursts are drained and dropped, so a burst's peak does not enter this column and make a churn run's row mean something different while looking identical. A policy reload is the same: its samples are kept in the artifact's `policy_reload` section, not in this column. |
| `max mem (GB)` | GiB | Maximum sampled target-container memory use, divided by 1024^3 and rounded to three decimal places. The historical `GB` label is retained for compatibility. Covers the delivery of the table only, like `max cpu %`. |
| `min idle%` | percent | Minimum sampled host-wide idle CPU percentage, rounded to an integer. It includes bgperf2's own workload and is not a foreign-contention measure. |
| `min free mem (GB)` | GiB | Minimum sampled host available memory, divided by 1024^3 and rounded to three decimal places. The historical `GB` label is retained for compatibility. It is host-wide and includes bgperf2's own containers, so `--receivers N` is in it: each receiver is a full GoBGP holding its own copy of the table on the same host. A fan-out large enough relative to the table can therefore drive this column low enough for `findings.py` to raise the `low_free_memory` confounder and withhold `limiting_component` — on memory the run consumed by design. `bench` prints the mechanism when a run asks for receivers; it does not estimate the size, because what a GoBGP holds per route depends on the paths. |
| `flags` | string | `-s` when single-table mode was selected; otherwise empty. |
| `date` | date | Controller-local row creation date in `YYYY-MM-DD` form. |
| `cores` | count | Logical CPU count reported by the benchmark host. |
| `Mem (GB)` | string | Total benchmark-host memory formatted by `mem_human()` with binary divisors and a unit suffix. |
| `tester errors` | count | Tester log lines classified as errors after convergence timing stops. Known benign BIRD messages are excluded by the tester parser. |
| `tester timeouts` | count | Tester log lines classified as timeouts after convergence timing stops. |
| `failed` | string | `FAILED` when convergence tracking declares failure; otherwise empty. |
| `MSG` | string | Convergence failure explanation when available; otherwise empty. Also carries a churn sequence that did not complete, with `failed` left blank: the run converged and that measurement stands, but a batch of churn cells whose rows all read as ordinary would say nothing about the second workload. `summary.py` reads this column only for a row marked failed, so no summary is affected. A policy reload that did not complete is carried the same way. |
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

## Event artifact: the `export` section

Present only on a run that had receivers (`--receivers N`, batch: `receivers: N`
on a test), and absent otherwise, so a run with no fan-out keeps the document it
has always produced. It is the export side of the run: the monitor is one export
session and what it observes is the run's convergence, so without this a
`--receivers 20` run and a `--receivers 0` run differ in exactly one published
number — `elapsed (s)` — with the cost of the fan-out inside it.

Nothing in the CSV moves with it. `elapsed (s)` is the monitor's convergence and
means that in every row; what the fan-out cost is here, per receiver, and in the
lines `bench` prints beside the row.

Each receiver is polled by one round-robin loop at the monitor's cadence, and
the events are `receiver_first_prefix` and `receiver_table_reached` under the
`export` phase, produced under each receiver's container name.

**The window is the delivery of the table and closes at convergence**, the same
window `elapsed (s)`, `max cpu %` and `max mem (GB)` describe. A receiver not
served by then is in `incomplete_receivers` with the count it last held in its
`sessions` entry, which is how a session that just missed the window is told
from one that stalled, and the printed line names the window for the same
reason. The poll is stopped there rather than left running because a churn
burst or a policy reload takes the queue over afterwards, and because the run
itself ends there: there is no phase that waits for the fan-out, and adding one
would put a wait that grows with the receiver count inside `total time`.

**Read `monitor_delta_s` knowing that its positive side is bounded by that
window.** Convergence is declared `ASSURANCE_SAMPLES_AFTER_CHECKPOINT` (5)
polls after the monitor crosses the check-point on every run that reaches the
neighbour checkpoint, so a fan-out served *later* than about five seconds after
the instrument cannot be reported as a large positive delta — it is reported as
`incomplete_receivers` instead, with each session's last count. A large lag and
a stalled session therefore produce the same **shape** of artifact, and what
separates them is `accepted_prefixes` per receiver: a session one poll short of
the check-point missed the window, a session holding a fraction of the table
did not. The negative side has no such bound. Giving the positive side one
would mean a run phase that waits for the fan-out after convergence, which is
a separate decision and not one this section quietly assumes.

| Field | Unit/type | Definition and interpretation |
|---|---|---|
| `receivers` | count | Receiver sessions in this run — the number of `sessions` entries. |
| `receivers_complete` | count | How many were seen holding `required_prefixes`. |
| `monitor_reached_required` | boolean | Whether the **monitor** reached the same check-point. `false` beside a non-empty `incomplete_receivers` means the count was out of reach for every session in the run, so the fan-out's incompleteness is not a finding about the receivers — the usual cause is a `--filter_test` policy dropping enough of the table that the target never re-advertises the count. It is read off the event stream rather than from the flag, because whether a policy drops that much depends on the workload: `--filter_test transit` at 2 peers x 1000 prefixes reached the check-point on the development host, so refusing the measurement on the flag alone would withhold one that can be made. |
| `incomplete_receivers` | list of strings | The container names that were not, sorted. Non-empty means the table was never exported to the whole fan-out, and `table_reached_s`, `export_spread_s` and `monitor_delta_s` are all `null` as a result — an interval bounded by the receivers that *were* served describes a fan-out that was not. |
| `required_prefixes` | prefixes | The run's own monitor check-point, which is the yardstick a receiver is judged against. Deriving one from what the monitor has seen so far would couple the two instruments; the point of reading a receiver is that its answer does not depend on the monitor's. A policy that makes this count unreachable leaves the receivers incomplete exactly as it leaves `convergence_s` null. |
| `first_prefix_s` | seconds | Bench clock origin to the **earliest** receiver seen taking prefixes. Gated separately from the intervals below: `null` only when some receiver was never seen taking any, since a fan-out where one session stalled still has a real export start and that is the run where a reader wants it. |
| `first_prefix_resolution_s` | seconds | The gap bounding that round, read exactly as the tester and monitor resolutions are. |
| `table_reached_s` | seconds | Bench clock origin to the **slowest** receiver holding `required_prefixes`. `null` unless every receiver got there. |
| `table_reached_resolution_s` | seconds | The gap bounding that round. A round is one `docker exec` per receiver and cannot be batched, so this grows with the fan-out and with host load: a 6-receiver 1M-prefix run measured 3.8s. It is the gap the loop *achieved*, floored at the cadence asked for. |
| `export_spread_s` | seconds | Slowest minus fastest `receiver_table_reached`: how far apart the fan-out's sessions were served. **Read it against `export_spread_resolution_s` and nothing else.** Every receiver in one round shares that round's timestamp, so a receiver read late in a round is dated to its start and can appear to reach the table one round-gap ahead of one read early in it. That gap is each event's own resolution, so a fan-out served simultaneously is off by at most one gap and its spread can never exceed the resolution published beside it — a spread at or under that number says the sessions were served within one look of each other, not that they were served together. `null` unless every receiver was served. |
| `export_spread_resolution_s` | seconds | The wider of the two rounds bounding the spread. |
| `monitor_delta_s` | seconds | **Signed.** The slowest receiver's `receiver_table_reached` minus the monitor's `monitor_required_reached`: how much later the fan-out was served than the instrument. Negative is ordinary rather than a fault — the monitor is one export session among several and nothing orders them — and clamping it at zero would give such a run the same number as one whose fan-out finished exactly with the instrument. It is deliberately measured against the monitor rather than against the generators: a generator-relative export tail is `post_injection_tail_s + monitor_delta_s`, and publishing that here would repeat `tester_fleet`'s all-or-nothing completion rule in a second place where the two could drift. `null` when either end is missing. |
| `monitor_delta_resolution_s` | seconds | The wider of the receiver round and the monitor poll bounding it. A **magnitude** at or under this number says the two landed within one look of each other, in either direction. |
| `sessions` | object | One entry per receiver, keyed by container name, carrying that receiver's own `first_prefix_s`, `table_reached_s` and their resolutions, plus `accepted_prefixes` — the last count read from it, which is the only thing that says how far a receiver that never finished got, and `null` for one that was never legible. A `read_failures` object (`{"polls": N, "first_reason": ...}`) is present only where a round could not read that receiver at all. |
| `unmeasured_reason` | string | Present only when the run had receivers and the export measurement was never taken, in which case it is the **only** meaningful field: every interval is `null` and `incomplete_receivers` names them all. Two causes. The run's check-point is not positive — `gen_conf()` takes 99% of the table, so `-p 1` gives 0 — where a threshold of 0 would stamp every receiver complete on the first round and publish a table nobody was seen holding. Or the run also drives a churn or reload workload, whose intervals are measured off the same target across the same boundary; measuring both in one run means fixing an order and paying for it in a published column, and that is deferred. Deliberately not `observation_error`: a measurement never started and one abandoned partway are different findings, and an absent section would be indistinguishable from the document an older build wrote. |
| `poll_incomplete` | string | Present only when the poll had not returned by the end of the teardown wait, so a round still in flight may be missing from the events. That wait scales with the receiver count, because a round is one serialised `docker exec` per receiver and nothing bounds that count. Deliberately **not** `observation_error`: a rejected round killed the measurement, one that did not come back only truncates it — and that key is the retirement flag the controller reads, so a timeout written there would stop the still-running poll recording the very round the note is about. |
| `observation_error` | string | Present only when a round was rejected and the export recorder was retired mid-run — a round that went backwards, or one whose receiver set changed. The events recorded before that point are still published. |

Two properties are deliberate. A receiver that could not be read is recorded as
unread rather than as a receiver holding nothing, so the receivers that happen
to answer can never satisfy "the whole fan-out has the table". And the poll ends
itself once every receiver holds the table: a round cannot be batched, so
polling on to convergence would spend an exec per receiver per second on
sessions with nothing left to say.

That last cost is worth understanding, because **the instrument runs inside the
window it measures and no published column reports it**. The read happens
*inside* the receiver container, so bgperf2's own-process-tree exclusion does
not reach it; it is invisible to `max foreign cpu %` because `gobgp` is in
`contention.BGPERF_PROCESSES`, the by-name allowlist, exactly as `birdc` is for
the generator poll. Two things bound it: the round is serialised, which is
self-throttling (N execs every `round + wait` rather than N every second), and
**every** round waits at least as long as it took — not only one that overran
the cadence, since four receivers at a 200ms read give a 0.8s round inside a 1s
cadence without ever tripping an overrun. So the poll can never spend more than
half its time inside containers whatever the receiver count. What that costs is
resolution: the verified 6-receiver run's 3.8s rounds publish a gap of roughly
7s, and every interval publishes the resolution that bounds it.

**One closing round is taken when the window shuts**, because the gap between
rounds is wider than the window that follows the check-point — at six receivers
a round plus its floor, against the five monitor polls before convergence is
declared. Without it a fan-out served in that gap would be published as one
that was never served. That read is stamped when it is taken, after the window
closed, and carries the gap since the previous round as its resolution. **A run that also drives a churn or reload workload
is not measured here at all** — the section carries an `unmeasured_reason`
saying so. The poll's window closes at convergence, which is exactly where
those workloads begin, so coexisting costs something published either way:
letting the poll run on puts one `docker exec` per receiver inside a burst's
1.0s-resolution withdrawal or the reload's CPU interval, and waiting for it
puts that wait inside `total time` and makes the workload's recorder date its
first sample across the wait. The receivers still exist and still cost the
target its export work; only the timing is withheld.

**Table selection is not separable here or anywhere.** With this section a run
decomposes into ingress (measured at the generators), the target's own work, and
export (measured at the receivers); best-path selection happens inside the
target and the only external observable is when a session sees the result, so it
stays inside the target-side interval rather than being published as a number
nothing measured.

## Event artifact: the `churn` section

Present only on a run that asked for `--churn-prefixes` (batch:
`churn_prefixes` on a test) or that asked and could not run the sequence.
Everything else about a churn run is a normal run: the CSV row, `elapsed (s)`,
`max cpu %`, `max mem (GB)` and `min free mem (GB)` all describe the *initial
delivery* of the table and are settled before the first burst is issued. What
the bursts cost is here, per burst, and nowhere else.

A burst withdraws the last `churn_prefixes` of every peer's own list and puts
them back. Two counts describe it and they differ by exactly the path
diversity: the fleet performs `peers x churn_prefixes` withdrawals, and the
monitor — which reads what the target *re-advertises*, one best path per prefix
— sees `groups x churn_prefixes` prefixes go away. Under the default diversity
those are the same number.

| Field | Unit/type | Definition and interpretation |
|---|---|---|
| `requested_bursts` | count | How many withdraw/re-announce cycles the run asked for, read from the events rather than from the caller. `null` when no burst ever started. |
| `completed_bursts` | count | How many of them got the table back to its converged count. |
| `offered_withdrawals` | prefixes | The withdrawals one burst performs across the fleet: `peers x churn_prefixes`. This is the size of the workload. |
| `distinct_withdrawals` | prefixes | The prefixes one burst removes from what the monitor can see: `groups x churn_prefixes`. This is what a burst's completion is decided on. |
| `sequence_complete` | boolean | Whether every requested burst ran to the end. `false` also puts the reason in the row's `MSG` column, with the `failed` flag left blank — the run converged, and that measurement stands. |
| `incomplete_reason` | string or null | Why not: a session that did not carry the command out, an exec that raised, or a phase that stopped moving for `CHURN_STALL_SAMPLES` polls. |
| `bursts[].burst` | count | 1-based position in the sequence. |
| `bursts[].complete` | boolean | Whether this burst got the table back. A burst that started and did not finish keeps its partial intervals rather than being dropped. |
| `bursts[].withdraw_s` | seconds | From the sample the withdrawal was issued on to the sample where the whole distinct block had gone. |
| `bursts[].reannounce_s` | seconds | From that sample to the one where the count was back at its converged value. Reported separately from the withdrawal on purpose: dropping routes and re-selecting/re-exporting them are different mechanisms, and the second is one of the three BIRD 3's worker threads exist to parallelise. |
| `bursts[].burst_s` | seconds | Start to completion, and exactly the sum of the two above — the withdrawal's end and the re-announcement's start are one event, so the three intervals share two endpoints. Published so a reader does not have to add two rounded numbers, not as a third measurement. |
| `bursts[].*_resolution_s` | seconds | How coarsely each interval is placed, from the polls that bound it. |

**An interval of one poll is an upper bound, not a duration.** Both halves of a
burst are bounded below by one poll by construction: the command is issued just
after a sample and the soonest it can be seen is the next one. So
`withdraw_s == withdraw_resolution_s` means the block went away somewhere
inside one look, and reading it as the daemon's reaction time publishes the
monitor's cadence instead — a faster daemon would produce the same number. The
printed line says `within the 1.0s poll resolution` for exactly this case.

**A churn run is refused rather than interpreted** for an MRT or ExaBGP
generator (the block is switched with the BIRD generator's own `birdc
disable`/`enable` on a static protocol bgperf2 wrote), for `-f`/a scenario
target, for `-r/--repeat` (which builds no tester objects, so nothing would
issue the burst and nothing rewrites the generator config), and alongside
`--filter_test` (a policy that drops part of the block makes the burst's
completion count unreachable, so a correctly filtered run would be published as
a stalled one).

## Event artifact: the `policy_reload` section

Present only on a run that asked for `--policy-reload-blocks` (batch:
`policy_reload_blocks` on a test) or that asked and could not run the reload.
As with churn, everything else about a reload run is a normal run: the CSV row,
`elapsed (s)`, `max cpu %`, `max mem (GB)` and `min free mem (GB)` all describe
the *initial delivery* of the table and are settled before the policy is
changed. What the reload cost is here and nowhere else.

Once the run has converged, an import policy rejecting the last
`policy_reload_blocks` of the fleet's prefix blocks is installed and applied
with the target's own reload command. A **block** is the group of peers
`--path-diversity` deals the fleet into — one peer per block at the default —
and whole blocks are rejected rather than individual peers: rejecting some
peers of a shared block leaves the prefix behind a surviving path, so the
target does real best-path work and the monitor's count does not move at all.

| Field | Unit/type | Definition and interpretation |
|---|---|---|
| `requested` | boolean | Whether a reload was issued. `false` with an `incomplete_reason` is a run that asked for one and could not run it. |
| `complete` | boolean | Whether the event stream shows the reload finishing — derived from the events. |
| `reload_complete` | boolean | Whether the *controller* drove it to the end. Named apart from `complete` because one is what the events show and the other is what the controller knows; a disagreement is worth seeing. `false` also puts the reason in the row's `MSG` column with the `failed` flag left blank, exactly as an incomplete churn sequence does. |
| `incomplete_reason` | string or null | Why not: a daemon that did not report the new configuration accepted, an exec that raised, a count that stalled for `POLICY_RELOAD_STALL_SAMPLES` polls, or a count that collapsed below what the policy leaves. |
| `rejected_blocks` | count | How many prefix blocks the new policy rejects. |
| `rejected_peer_asns` | list of AS numbers | Exactly which peers it rejects — the tail of the fleet, ordered by AS. A reader can rebuild the workload from this without the config. |
| `rejected_prefixes` | prefixes | `rejected_blocks x prefixes per peer`: the distinct prefixes the policy removes from what the monitor can see. |
| `converged_prefixes` | prefixes | What the monitor accepted when the run converged, which is what the expected count is measured down from — not what the fleet offered, since the check-point carries a 0.99 factor for a target that does not hold everything offered to it. |
| `expected_accepted` | prefixes | `converged_prefixes - rejected_prefixes`. Completion is `accepted <= expected_accepted`, exactly. |
| `accepted_before` / `accepted_after` | prefixes | What the monitor saw on the sample the reload was issued from, and on the sample it completed. |
| `command_s` | seconds | How long issuing the change took — the `docker exec` and the daemon's reply. **Not the reload**: on BIRD the reply comes back in milliseconds and the table drains afterwards, so publishing one number would credit the daemon with an instant reload. |
| `reload_s` | seconds | From the sample the reload was issued on to the sample where the table had settled at `expected_accepted`. |
| `reload_resolution_s` | seconds | How coarsely that interval is placed, from the polls that bound it. |
| `target_cpu_percent_max` / `_mean` | percent | The target container's CPU across the interval, sampled from its existing stats thread. `null` where no sample fell inside — an interval too short to sample and an interval in which the target did nothing are different findings, and 0.0 would publish the second. |
| `target_cpu_samples` | count | How many samples that was, so a mean over one sample is not read as a distribution. |
| `mechanism` | string or null | What the reload was carried out with, e.g. `birdc configure`. Reported because applying policy by file reload, management CLI and transactional API are operationally different, and only like mechanisms compare. |
| `session_preserving` | boolean or null | Whether the BGP sessions stayed up. A reload that resets them measures a second table delivery and belongs in a separately labelled comparison. |

**An interval of one poll is an upper bound, not a duration**, the same rule the
churn intervals follow and for the same reason: the reload is issued just after
a sample and the soonest it can be seen is the next one. The printed line says
`within the 1.0s poll resolution` for that case.

**What BIRD actually does, verified on `bgperf/bird:2.19.2` and
`bgperf/bird:3.3.2`.** `birdc configure` holds the sessions up — their `Since`
is unchanged across the reconfigure and both stay Established — so these runs
belong in the no-reset comparison. But neither series re-evaluates purely
locally: both answer a changed import filter by asking their peers for a route
refresh, and each generator's `Export updates` counter doubles. So `reload_s`
covers re-import as well as re-decision. That is what an operator changing
policy on BIRD pays, and it is recorded rather than hidden; it is not
comparable with a daemon that re-filters from its own stored routes.

**A reload is refused rather than interpreted** for a target with no reload
mechanism (only BIRD has one here), for an MRT generator (the policy selects a
block by the peer AS bgperf2 assigned, and an MRT injector replays the AS paths
in the file), for `-f`/a scenario target, alongside `--filter_test` (the
target's import filter is already the policy under test and the reload is
written into the same place), alongside a churn workload (both run against the
converged table off the same monitor samples, so one would take the other's
outcome as its baseline and nothing would say which ran first), for
`-r/--repeat` (the completion count is `blocks x prefixes per peer`, and repeat
reuses whatever generator containers it finds, so `-p` need not be what they
are announcing), and for a block count covering every block (a target left
holding nothing cannot be told from one that lost its sessions).

## Event artifact: the `target_table` section

Present only on a run whose target has a table gauge this project knows how to
read. Only BIRD does so far, so every other daemon's artifact is exactly what
it has always been — the section is absent rather than empty, because an empty
one would say the target was asked and had nothing to say.

The monitor is one BGP session's view of the target and it is the instrument
every published timing is read from, so a move in its `accepted` count has
nothing to be compared against. This is the second witness: the target's own
`Routes:` line, which is a **gauge** of the table as it stands, unlike the
`Import updates accepted` counters `get_neighbors_state()` reads, which only
ever rise and so can witness delivery but never a loss.

`samples` is one entry per monitor poll — the raw observations, kept for the
reason `summary.py` keeps its own: a number whose inputs are gone is not
auditable, and where in the run a peak sits is the whole evidence. `series`
summarises each of the four.

| Field | Unit/type | Definition and interpretation |
|---|---|---|
| `samples[].monotonic_s` | seconds | The monitor sample this witness is paired with, from the bench clock origin. |
| `samples[].witness_monotonic_s` | seconds | When the target was actually read. The two poll loops are independent, so this says how stale the pairing is rather than hiding it. |
| `samples[].witness_age_s` | seconds, signed | How old the carried target reading was when this monitor sample took it. The target poll is a separate thread with no guard around its exec, so if it stops, every later sample repeats its last reading — without this, that reads as a perfectly stable table. Signed and unclamped for the reason `post_injection_tail_s` is: the two loops are independent, so a target read taken just after a monitor sample is ordinary and reads negative. Staleness is the positive side. |
| `samples[].monitor_accepted` | prefixes | What the monitor reported on that poll — the same number `elapsed (s)` is decided from. |
| `samples[].best_paths` | prefixes | Sum of each peering's `preferred`: one best route per prefix, so the count of **distinct prefixes the target holds**. This is the quantity `monitor_accepted` is supposed to track. |
| `samples[].imported_paths` | paths | Sum of each peering's `imported`: every path held, losers included. It moves with delivery rather than with selection, which is what separates the two. |
| `samples[].exported_to_monitor` | prefixes | The `exported` count on the monitor's own session — the target's end of the very session the monitor reads. `null` when the monitor's address could not be matched. |
| `samples[].peerings` / `peerings_expected` / `peerings_measured` | counts | How many BGP peerings the target was showing, how many the scenario configured, and how many reported a `Routes:` line. The sums are withheld (`null`) unless `measured` equals `expected`. It is deliberately not compared against `peerings`: BIRD targets use `neighbor range`, so an unconnected peer is not a protocol at all and a dropped session takes its `dynbgp` protocol away — the denominator would shrink with the numerator and the guard would never fire, letting a flapping tester publish a `best_paths` decline shaped exactly like real route loss. |
| `series[<name>].observations` | count | How many *monitor* polls carried a reading. A series nobody could read at all is absent, not null-filled. |
| `series[<name>].resampled_onto_monitor_polls` | boolean | True for the three target-side series. The target and the monitor are polled by independent loops and a sample is one monitor poll carrying the target's last read, so a target read taken between two monitor polls is dropped and one that lands between none is carried twice. Each sample's `witness_monotonic_s` shows which, per row. Their `decline_from_peak` therefore has the monitor's resolution, not the target's. |
| `series[<name>].peak` / `final` | as above | Highest reading, and the last one. |
| `series[<name>].final_monotonic_s` | seconds | When that last reading was taken. The target's sums are withheld on any poll where a session was not reporting, so a peer dropping near the end truncates the target series while `monitor_accepted` runs on; comparing two `decline_from_peak` values across different windows is comparing different runs, and this is what makes that visible. |
| `series[<name>].max_witness_age_s` | seconds or null | The oldest a carried reading got, for the three target-side series. `null` for `monitor_accepted`, which is read on the poll it is recorded with. No threshold is applied — there is no measured number to put on one. |
| `series[<name>].decline_from_peak` | fraction | `(peak - final) / peak`, rounded to six places. Against the peak rather than the previous sample because that is the comparison `ConvergenceTracker` makes, and the one that decides whether a run is failed. |

`unmeasured_reason` is present when the target *could* have been asked and no
sample arrived — its poll thread died on the first read, or the run converged
before the first target poll landed. A daemon with no gauge at all gets no
section and no reason, which is the document every non-BIRD run has always
written; without the distinction the two would be byte-identical. Same rule as
the `export` section's own `unmeasured_reason`.

**No verdict is derived here.** Whether a decline in the monitor's count is
route loss is exactly the question this measurement exists to answer, and a
rule shipped beside the first evidence for it would be fitted to the run in
front of it — which is how all three convergence rules in `convergence.py` were
broken.

**What it showed first.** On four 10 x 1,050,000 bgpdump2 MRT runs, three of
which `ConvergenceTracker` failed for a 1.2–1.5% decline, `best_paths` climbed
to 1,080,985 and stayed flat — the same number to the prefix every time — while
`exported_to_monitor` fell by the same fraction the monitor saw, agreeing with
it to three decimal places. The target lost no routes and the monitor was not
miscounting; what changed was which of the prefixes it held the target chose to
export, as the last injectors delivered and best paths moved.

## Event artifact: the `findings` section

The same artifact carries a `findings` object
(`bgperf2/measurement-findings/v1alpha1`), derived by `findings.py` from the
sections above plus the controller's own host samplers. It answers the one
question the intervals were added for — what was this run waiting for — and
most often refuses to answer it. It is not a validity boolean: every finding
carries the rule it applied and the raw durations it applied it to, so a
reader can disagree with the policy without re-deriving the numbers.

| Field | Unit/type | Definition and interpretation |
|---|---|---|
| `policy_version` | string | The named qualification policy that produced this verdict, versioned separately from the artifact schema. The same durations can be published under a changed policy, and a reader comparing two runs needs to know whether the verdicts were reached the same way. |
| `limiting_component` | string | `tester`, `target_or_monitor`, `unresolved`, or `inconclusive`. The last two are different statements and are kept apart deliberately: `inconclusive` means the measurement that would decide it was never made (no generator that can be asked, a generator that never completed, a monitor that never reached the check-point), and `unresolved` means the measurements exist and something forbids attributing them (a saturated or shared host, low free memory, blocked writes, or a generator whose completion is counted where the routes were queued rather than sent). |
| `decided_by` | string | Which finding produced the verdict, or `null` where nothing did. |
| `reason` | string | That finding's summary, repeated at the top so a verdict is never published without the sentence behind it. |
| `findings` | list of objects | Everything the policy concluded, including findings it then withheld. A run qualified by a busy host still publishes the `tester_limited` evidence it would otherwise have been attributed by: the verdict is withheld, not the measurement. |

Each entry in `findings` has `finding` (the rule's name), `kind`, `summary`,
`policy` (the rule in one sentence), `evidence` (the raw durations and counts
it ruled on), and `limiting_component` — set only on the two findings that
propose one.

`kind` says what a finding does to the verdict, and the four are resolved in
this order: `missing_evidence` (the deciding measurement was never made) beats
`confounder` (it was made and cannot be attributed), which beats `attribution`
(a proposed component), which beats `qualification` (a narrowing of how an
interval may be read that does not by itself prevent an attribution some other
interval supports).

| Finding | Kind | When it fires |
|---|---|---|
| `tester_limited` | attribution | The generators were measured sending for longer than the poll that bounds the interval, at a rate this instrument could observe, and the monitor reached the required count within one poll of their completion or before it. It requires that at least `INJECTION_COVERAGE` (half) of the offered table crossed the measured interval, which is what keeps a queue-side counter from being read as a send rate — BIRD 2.19 puts at most about 15% of its table inside that interval, and where the first poll lands decides how much. |
| `post_injection_tail` | attribution | The run continued past the last generator's completion by more than the polls bounding that interval. The time was spent somewhere between the target and the monitor, and nothing published here separates the two: the monitor is the instrument, so its own polling is inside the number. |
| `injection_unresolved` | qualification | The fleet injection was no wider than the look that bounds it. Every MRT run has this shape — a 10,000-prefix walk is over in about a millisecond — so it forbids reading the injection as the run's cost and forbids nothing about the tail. |
| `injection_boundary_unresolved` | confounder | Neither most of the table crossed the measured interval nor did any generator time its own send, so the generator's completion may sit anywhere inside its real sending and the boundary between injection and tail cannot be trusted. This is the BIRD 2.19 case. |
| `no_dominant_interval` | qualification | Both intervals finished inside what these poll loops can resolve. Neither end can be shown to have held the run up. |
| `tester_incomplete` | missing_evidence | A generator never reported completion, so the workload was never fully offered and no interval bounded by it can be read. |
| `missing_timing_evidence` | missing_evidence | No generator in the run could be asked what it offered (ExaBGP and GoBGP playback), or the monitor never reached the required count, which is also every failed run. |
| `backpressure_observed` | confounder | A generator reported cumulative blocked writes or send stalls. Which end of a blocked write was at fault is not in these numbers, so it withholds an attribution rather than supplying one. BIRD 3's `TX pending` queue depths are deliberately **not** read as backpressure: a session with something queued at the instant it is polled is what a working session looks like, and treating it as backpressure would withhold every BIRD 3 verdict there is. |
| `host_cpu_saturated` | confounder | Host idle fell to `HOST_IDLE_PERCENT` (5%) or below. `min idle%` is host-wide and includes bgperf2's own load, so it says the machine had nothing spare and not whose work that was — see the CPU attribution boundary in the implementation plan. Per-role, time-aligned CPU would be needed to say more, and no such measurement exists. |
| `foreign_cpu_contention` | confounder | `max foreign cpu %` reached `contention.CONTENTION_PERCENT` (one core). A run sharing the machine is not comparable with one that did not, and a version ranking read off it would be an artifact of the neighbour. |
| `low_free_memory` | confounder | Free memory fell below `LOW_FREE_MEMORY_FRACTION` (5%) of the host's total, so the intervals include page pressure. A fraction rather than a constant because the column is also moved by bgperf2's own logging when the bench directory is tmpfs. |

A run whose policy raised still writes its artifact: `write_event_artifact()`
catches, and publishes `limiting_component: inconclusive` with the exception in
`reason` and an empty `findings` list. The artifact preserves the evidence and
this section is an opinion about it, so the opinion must not be able to take
the evidence with it.

The host evidence comes from `bgperf2.host_evidence()`, which maps the
controller's sentinels back to "never sampled": the minima start above every
real value so the first sample can only lower them, and an untouched sentinel
must not read as an idle host with free memory.

## Batch summary: `<test>.summary.json`

A batch writes one summary document
(`bgperf2/batch-summary/v1alpha1`) beside its CSV, derived by `summary.py`
from the rows already in that CSV. It exists because one observation per cell
says nothing about run-to-run variance, and because a summary is only worth
having if the observations behind it are still there to argue with: every
statistic is published beside the values it was computed from and the passes
those came from, and the CSV keeps every row.

It is written before the first cell runs -- naming every cell the batch
intends, all `not run` -- and rewritten cell by cell like the CSV, so a batch
that dies in its third pass still says what its first two measured and never
leaves a discarded run's summary in place. `summary.py` reads the stats row
by **column name**, never by position — that row is positional for
`create_batch_graphs()` and has drifted by a column once already.

One entry per matrix cell, in matrix order whatever order the cells ran in.

| Field | Unit/type | Definition and interpretation |
|---|---|---|
| `cell` | int | The cell's `ordinal`: its position in one pass over the matrix. Unchanged by repetitions and by a shuffled execution order, so it is the same identity `--resume` matches on. |
| `name` | string | The run name (label, else target plus version) with no `#N` pass suffix: the passes are inside this entry. |
| `description` | string | How the cell is named in the printed line, from `batch_cell_description()` — the run name alone is the target, and two cells of one target differ only in their axes. |
| `identity` | object | What the cell asked for: `peers`, `prefixes`, `filter`, the whole `target` entry (so `threads`, `mrt_file` and `image` are recorded, none of which reach the run name), and `required` as the passes reported it. |
| `provenance` | object | `target image`, `tester version` and `monitor version` as the observed passes reported them. One value where they agree, the list where they do not. |
| `inconsistent` | object | Present only when the passes disagreed about a provenance or identity column, mapping the column to every value seen. Two passes that ran against different images are not two observations of one thing — the gcov trap one layer up — so a disagreement is surfaced rather than averaged over. |
| `passes_expected` | count | How many passes this cell has, i.e. the test's `repetitions`. |
| `observations` | count | How many of them produced a usable row. |
| `observed_passes` | list | Which repetitions those were, in the same order as every metric's `values`, so a reader can say which pass produced which number. |
| `passes` | list of objects | Every pass, in repetition order, with `state` `observed`, `failed` (plus the run's `MSG`), `not run`, or `unreadable`. A failed pass and a pass that has not run are counted apart: one is a result and the other is unfinished work. `unreadable` is a stored row that is not the current header's width — `--resume` onto a progress file written before a column was appended is a supported path, and such a row is one field short. It costs its own pass and nothing else; indexed against this header it would otherwise raise and cost the whole test's document. |
| `metrics` | object | One entry per column in `summary.METRIC_COLUMNS`, keyed by the CSV column name. |
| `variance` | object | Whether this cell's passes separate it from the cells drawn beside it, and so whether it has earned more of them. Decided against the *binding* rival, not the nearest — see [The variance rule](#the-variance-rule) below. |

Each metric entry carries `values` (the observations, in pass order), `n`, and
`mean`, `median`, `min`, `max`, `stdev`, `cv_percent`. `min` and `max` are
observations and are copied through unrounded — a summary must not report an
extreme no run produced — while the derived statistics are rounded to six
places, enough to keep a 0.4 MB spread in `max mem (GB)` from reading as
`0.0`. `mean` is published because `cv_percent` is otherwise a number a reader
cannot check. `stdev` is the **sample** standard deviation (n-1): three passes
are a sample of what the machine does, and the population formula understates
the spread of one, to exactly 0 at n=1.

Nothing here is published as a zero when it is really absent. A withheld
statistic is `null` and the reason is in a `withheld` object beside it:

| Reason | When |
|---|---|
| `no observation` | Every pass of the cell failed or has not run. |
| `non-numeric observation` | A pass reported something that is not a number in that column. The offending pass is not dropped — that would change `n` without saying so, which is the one thing a dispersion cannot survive. |
| `needs at least two observations` | `stdev` and `cv_percent` over a single pass. A CV of 0 there would say the measurement is perfectly repeatable on the strength of never having been repeated. |
| `the mean is not positive` | `cv_percent` where the mean is zero, which is the normal shape of `tester errors` and `tester timeouts` in a good run: the spread is real and zero, the ratio to the mean is a division nobody can do. |
| `never-sampled sentinel` | Any pass reported the value a run writes into that column when it never measured it — `min free mem (GB)` (`min_free` starts above every real value so the first sample can only lower it, and an untouched sentinel reaches the row as ~931,322 GB; `host_evidence()` maps the same sentinel back to `null` for the findings) and `max mem (GB)` (`max_mem` starts at 0 so the first sample can only raise it, and a peak under 0.5 MB is not something a daemon holding a BGP table can produce). The whole column is withheld for that cell rather than the pass being dropped: a cell where one pass of three lost its memory sampler would otherwise publish a ~310,474 GB mean and a 173% coefficient of variation on a 64 GB box, or an 87% one on the target's peak. `min idle%` and `max cpu %` are deliberately not treated this way — the first's sentinel is 100 and the second's rounds to 0 from any peak under 0.5%, both values a real run can report, and for `min idle%` an idle host and an unsampled one are the same finding anyway. |

### The variance rule

Phase 5 asks that a test expand from three passes to five *only under a named
variance rule*. The naming is the point. Without one, the decision to rerun
belongs to whoever read the CSV and did not like it, which selects for reruns
of the results somebody found surprising and quietly turns a benchmark into a
search for the expected answer. The rule is stated once, in
`summary.VARIANCE_RULE`, and repeated into every cell's verdict as `policy`:

> two cells are separated when their medians differ by more than the sum of
> their standard deviations, floored at the resolution of the metric

It is comparative rather than a threshold on a coefficient of variation,
because no CV means the same thing twice here: a 2% spread is nothing on a cell
whose targets are 40% apart and fatal on one where they are 0.12% apart — which
is what FRR 8.5, 9.1 and 10.0 were, finishing a 95s MRT run within 0.11s of
each other. A cell earns more passes when its own spread covers the difference
it is being asked to resolve, and not otherwise. It is deliberately weaker than
a significance test: this is a scheduling rule at n=3, where a t-test would be
arithmetic dressing up three numbers, and it errs toward spending machine time
rather than toward publishing a ranking the passes do not support.

The combined deviation is floored at the metric's resolution
(`summary.METRIC_RESOLUTION`, published as `metric_resolution` in the
evidence). `elapsed (s)` is whole seconds and not by choice: it is counted off
the monitor's poll loop at `MONITOR_POLL_INTERVAL_S`, one sample a second, with
an integer number of assurance samples subtracted, so there is no finer number
to publish. Passes of one cell therefore land in the same bucket routinely and
`stdev` comes out at exactly 0.0 — and a combined deviation of zero is cleared
by any gap at all, so without the floor the rule publishes `separated` on one
rounding boundary, silently. The pairs it exists for are inside that quantum:
the three FRR releases 0.11s apart over a 95s run are one measurement at this
resolution, and the honest verdict is that this instrument cannot tell them
apart. Same rule as `MONITOR_POLL_INTERVAL_S` flooring the published
`poll_resolution_s` — a span nothing crossed is not a measurement of zero.

It is applied to `elapsed (s)` only (`summary.DECISION_METRIC`) — the
end-to-end number every graph in `create_batch_graphs()` is keyed on and the
one a version comparison is read from. A rule ranging over all thirteen metrics
would ask for expansion on every batch ever run, since `min idle%` and `max cpu
%` are noisy by nature and nobody ranks a daemon by them.

A cell is compared only against cells sharing its `(peers, prefixes, filter)`
axes — `create_graph()` draws exactly those groups side by side, so the rule
answers a question somebody is going to ask of the picture, and a 10-peer cell
is not the rival of a 50-peer one — and within that group against **every**
rival, not the nearest one. Separating a cell from its closest neighbour
separates it from the rest only if every rival has the same dispersion: with
bird at 40 ± 0.01, frr at 41 ± 0.01 and gobgp at 45 ± 10, bird clears frr by a
mile and is nowhere near gobgp. The verdict is decided by the **binding**
rival, the one with the smallest `margin` (`gap` minus `combined_stdev`) — the
closest call in the group, and the one a reader would challenge first. That
rival is what `evidence` describes, and `rivals_considered` says how many had a
dispersion to be compared against.

The evidence's rival fields are `rival_*`, never `nearest_*`. Only the refusal
branch picks the nearest rival; this one picks the smallest margin, which in
the group bird 40, frr 41, gobgp 45 is gobgp — the cell *furthest* away. One
key name meaning two things in one document is how a reader of
`<test>.summary.json` concludes the rule compared a pair it did not, so
`rival_chosen_by` says which of the two selections produced it (`margin` or
`gap`).

Rivals that have a dispersion are preferred. A cell whose passes mostly failed
has a median and no deviation, and letting one of those be chosen as the
neighbour withheld the verdict for two cells that were plainly unseparated,
printing nothing to say the rule had been silenced.

Preferring them is not the same as ignoring them, and the difference decides a
`separated` verdict. Clearing every rival that *can* be judged is not clearing
the group: one rival with a dispersion was once enough to publish `separated`
while a rival at an identical median sat in the same bars unjudged — the
nearest-rival defect reached through the cell that was skipped instead of the
one that decided it. So every verdict names its unjudgeable rivals in
`rivals_unjudged` — the refusal above included, which names only the nearest
one in its reason string and would otherwise leave the rest unmentioned
anywhere, and rivals with no observation at all, which have no median and were
therefore dropped from the naming as well as from the comparison — and
`separated` is withheld when one of them is **at least as near**
as the binding rival, since that is the reading the picture invites and the
passes cannot support. A rival with no observation at all withholds it too, and
for a stronger reason: it is *less* known than one with a median and no
dispersion, so withholding for the second while publishing beside the first
would make the rule stricter about the case it knows more about. Only
`separated` is withheld this way: an unseparated verdict is already the
conservative answer, and degrading those is how a single mostly-failed cell
mutes its whole group.

| `verdict` | Meaning |
|---|---|
| `separated` | The medians differ by more than the combined deviation. The passes support the ranking; nothing is printed. |
| `expand` | They do not, and the cell has fewer observations than the ceiling. `passes_recommended` names the count to rerun at: `max(summary.EXPANSION_PASSES, the test's declared repetitions)`. Five is a floor under the recommendation, never a cap on it — telling a `repetitions: 7` test to rerun at five would reduce its passes and discard observations. Where the cell produced fewer observations than the passes it was given, `shortfall` says so as well — never instead: a failed pass to investigate and a rerun count are two different things to do about one cell, and printing only the first invites the operator to fix the pass, rerun at the count they already had, and come back unseparated again. `passes_recommended` is emitted only where following it would change something — that is, where the test declared *fewer* passes than the ceiling. A cell that already ran the ceiling and lost some of its passes to failure is short on observations, not on repetitions, so it carries `shortfall` alone; one that is fully observed while the binding rival is short carries `rival_shortfall` alone, naming that rival. Recommending the count a test already ran is a no-op printed as advice, and it was reachable through both the cell's own shortfall and the rival's. |
| `unseparated at the expansion limit` | They do not, and **both** cells of the pair have reached the ceiling in observations — both, because the claim is about the pair, and a rival that produced two of its five passes has not spent the passes *more passes will not decide it* assumes. This is a result, not a request for a sixth: those two targets are not distinguishable at this workload, and expanding without a limit is how a batch that cannot decide something spends a weekend failing to. |
| `undecided` | The rule could not be applied. `reason` says which case it was. |

The `undecided` reasons are kept apart because each is a different thing to do
about it: this cell has no dispersion; *no* rival has one; a rival at least as
near has none; a rival has no observation at all, so the group is not fully
measured; no rival has an observation, in which case each is named with why —
`frr_c (every pass failed); gobgp (has not run yet)`; or no other cell shares
this cell's axes. Only the last is a property of the test as written rather than of
what came back from the passes, and the two were once the same string — a cell
whose rivals had all failed was told it had no rivals, which is false about the
matrix and points at the wrong thing to fix. Not-run and produced-nothing are
kept apart for the same reason one layer down: the summary is written before
the first cell and rewritten after each one, so for most of a batch a finished
cell's rivals have simply not run — and an interrupted batch leaves exactly
that document behind, since the surviving file is the last checkpoint. They are
kept apart *per rival* and per pass, never as one clause over the group: an
`any(... not run ...)` reported a rival that ran and failed every pass as a
batch merely in progress as soon as one other rival was unstarted, and that
failed rival is the only thing in such a group an operator can act on. The
second and third still publish
the gap, so the reader is told which pair could not be judged and by how much
they differ.

Every `undecided` that names a rival is printed. `separated` is not: the rule
is silent about the results it supports. Leaving the refusals silent too meant
silence stood for both *the rule endorsed this ranking* and *the rule could not
judge it*, which are the two things a reader most needs told apart.

The first quotes the metric's own `withheld` entry for `stdev` rather than
restating it, so it says *which* of the four ways to arrive without one this
was: every pass failed, only one produced an observation, one reported the
never-sampled sentinel, or one reported something non-numeric. A second
vocabulary here answered the same question differently — a cell whose every
pass failed read as "this cell has no dispersion", which is exactly what one
observation looks like, and telling those apart is the whole reason the
refusals are kept separate.

Every verdict carries `metric`, `policy`, `observations` and, where a rival
was found, an `evidence` object with both medians, both deviations, the `gap`
between them, `combined_stdev`, `metric_resolution`, the rival's `rival_cell`
and `rival_description`, and `rival_chosen_by`.

`combined_stdev` is the two deviations' sum **floored at** `metric_resolution`,
and for `elapsed (s)` the floor is the normal case rather than an edge one:
passes landing in the same one-second bucket give both cells `stdev` 0.0, and
the document then publishes `combined_stdev: 1.0` beside two zeroes. A reader
auditing the file by adding the two published deviations would otherwise
conclude the number is wrong, which is the failure this document exists to
prevent. Every verdict also carries
`rivals_considered` and, where any could not be judged, `rivals_unjudged` —
including the refusals, so that `rivals_considered: 1` can be told from "one of
two".

A refusal that a *particular* cell caused also carries `withheld_by`, the
ordinal of that cell: the rival at least as near with no dispersion, the rival
with no observation at all, or the first rival where none has an observation.
It is load-bearing rather than incidental — the printed lines are
de-duplicated per pair, and this is the pair such a verdict is about, which is
not the rival in its `evidence`. Keying those on the `evidence` rival collapsed
two cells blocked by two different rivals onto one line. The count is `observations`, which
mirrors the cell's own field of that name — deliberately not `passes_observed`,
a near-anagram of the sibling `observed_passes`, which is a *list* of
repetition numbers. This is the shape `findings.py` publishes a verdict in,
and for the same reason: a verdict nobody can argue with is a boolean with
extra words. The document also repeats the rule once at the top level as
`variance_rule`.

A rule that raises costs the verdicts, not the statistics — the same rule
`write_event_artifact()` applies to `derive_findings()`, and for the same
reason: by the time it runs, those statistics are the only record of what the
passes measured, and `publish_batch_summary()` catches at the outer level, so a
raise here would lose the whole document at the end of a multi-hour batch. Such
a document carries `variance_failure` instead of `variance_rule`, no cell
carries a `variance` — partial verdicts are dropped, since the rule reads each
cell against its group and a half-judged group is a ranking nobody can argue
with — and the failure is printed under the repeatability heading, because a batch
whose rule raised otherwise looks exactly like a batch whose every cell was
separated. Under the heading and inside the same gate: a single-pass test
prints nothing at all, and no cell of one can carry a printable verdict anyway,
since every dispersion in it is withheld.

Every verdict except `separated`, and except a refusal that names no rival at
all, prints a line, and the lines are de-duplicated by unordered pair. A
refusal naming no rival — this cell has no dispersion, or nothing shares its
axes — has no pair, and its cause is already in the cell's own listed passes. The rule is silent about the results it
supports — a batch that prints a line per cell trains its reader to skip them
— and the pair is usually mutual, so a two-target group would otherwise state
one relation twice with identical numbers. The pair is keyed on the cell the
verdict is actually about, which for a withheld separation is the unjudgeable
cell that blocked it rather than the binding rival in its `evidence`: keying
those on the binding rival collapsed two cells blocked by two different rivals
onto one pair, and one of the two refusals then went unprinted.

Which half of that pair supplies the line is decided by what it asks the
operator to do, not by which cell has the lower ordinal. The two sides need not
agree: with `repetitions: 5` a cell whose passes all succeeded is `unseparated
at the expansion limit` — *more passes will not decide it* — while the rival
that lost two of them is `expand` carrying a `shortfall`, which is a failed
pass to go and look at. Printing whichever came first let matrix position
choose between those, and half the time printed the one that says to do
nothing.

`describe_batch_summary()` prints one line per cell for a repeated test —
observations, then `elapsed (s)` and `total time` medians, ranges and CVs, with
any pass that did not produce an observation named under it — and
nothing at all for a single-pass test, where every dispersion is withheld and a
block of "CV unavailable" would say only that the test asked for one pass. A
provenance disagreement is printed whichever it is: that is the finding, not
the statistic beside it.

A summariser that raises costs the summary and not the rows. It runs after the
CSV is on disk and `publish_batch_summary()` catches, printing `summary
unavailable: <exception>` — at the end of a batch that has already run for
hours, the rows are the evidence and this is an opinion about them. That line is
printed from every one of the three call sites, including the two that do not
ask for the description, because it is the only report that the document beside
the CSV is not the one describing it. A non-resumed batch also unlinks its
predecessor's summary along with its progress file, so a write that then fails
cannot leave a document describing passes that no longer exist.

Values are written with `allow_nan=False`, and a non-finite observation is
published as its own repr (`"nan"`) rather than as a bare `NaN`: the document
has to stay readable by jq and by every non-Python parser.
