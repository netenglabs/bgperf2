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

## Event artifact: the `testers` section

Each run also writes `<prefix>.events.json` (`bgperf2/measurement-events/v1alpha1`).
Generators that can be asked what they put on the wire — the BIRD synthetic
tester and each bgpdump2 MRT injector — get a `testers` entry keyed by
container name:

| Field | Unit/type | Definition and interpretation |
|---|---|---|
| `tester_startup_s` | seconds | Bench clock origin to the poll where *every* session this container drives was established. The last session, not the first. |
| `startup_resolution_s` | seconds | How coarsely `tester_startup_s` is placed: the gap between the poll that first saw every session established and the previous look. Sessions are routinely up on the very first poll, whose gap is measured from the bench clock origin — the clock starts before the testers are launched — so this is often the whole of `tester_startup_s`, which is the honest statement that readiness was not resolved at all. |
| `injection_s` | seconds | First poll with a nonzero offered count to the poll where every session had offered its whole configured table. `0.0` means the table was already fully offered when the instrument first looked — an unresolved interval, not an instant injection. |
| `injection_resolution_s` | seconds | How coarsely `injection_s` is placed: the wider of the two gaps bounding it, i.e. the looks that found the first update and the completion. It is the *achieved* gap, never the requested cadence — a poll reads before it waits, so the read is part of the resolution — floored at the requested cadence, which the loop cannot beat. Read `injection_s` against it: an injection at or under this number is unresolved, not fast. Deliberately **not** shared with `startup_resolution_s`: one number cannot bound two intervals, and folding in a late first poll would qualify a 1s-resolved injection with a 30s bound. `null` for an event stream not produced by a poll loop. |
| `offered_prefixes` | prefixes | The generator's own cumulative count at completion, summed across its sessions. Published only when every session was legible; a partial read reports `null` rather than a shortfall. |
| `offered_in_interval` | prefixes | How much of `offered_prefixes` arrived inside `injection_s`. The rate below is derived from this, not from the total. `null` means the generator's counter went backwards during the run — BIRD clears a protocol's route-change stats when the protocol restarts — so the interval is real but its content is unknown. |
| `offered_rate_pps` | prefixes/second | `offered_in_interval / injection_s`. It is `null` in two different cases, told apart by `offered_in_interval`: an injection that began and finished inside one look, so there is no interval to divide by (`injection_s` is `0.0` and `offered_in_interval` is `0` — see `injection_resolution_s` for how wide that look was), or a generator whose counter reset mid-run so nothing can be said about what crossed the interval (`offered_in_interval` is `null`). **Read it only beside `offered_in_interval`**: for BIRD 2.19 that share is usually a small tail of the table, and the rate is then a slope of the poll cadence rather than the generator's send rate. |
| `backpressure` | object | `{"available": false, "reason": ...}` where the generator exposes no blocked-write counter (BIRD 2.19), otherwise the maximum observed `TX pending` bytes/prefixes (BIRD 3). Never `0` for a daemon that cannot answer. |
| `read_failures` | object | `{"polls": N, "first_reason": ...}` when one or more polls could not be read at all (the container was gone, the control socket refused). Present only when it happened; its absence means every poll was read. |
| `observation_error` | string | Present only when a poll was rejected and the recorder was retired mid-run. The events recorded before that point are still published. |

Two properties are deliberate. `expected` is always the configured table size
(`len(paths)`), never the generator's own report of what it loaded, so a
generator that loaded half its config cannot look complete. And an event is
absent rather than synthesized: a run whose generator never reported completion
has no `tester_complete` and a `null` `injection_s`, never an interval inferred
from monitor timestamps.

**A BIRD 2.19 offered count is queue-side.** `Export updates accepted` counts a
route when it is handed to the BGP protocol, not when it reaches the wire, so
the count and the completion fact are trustworthy while the duration is not.
Do not derive a tester-limited finding from a BIRD 2.19 rate.
