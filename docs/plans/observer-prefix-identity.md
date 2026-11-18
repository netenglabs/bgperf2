# Received IPv4 prefix identity

Selected 2026-11-01. Goal: detect an incorrect received prefix set even when
the observer count is correct. This replaces the current work priority; the
upstream BIRD reproducer investigation remains unfinished and deferred.

## Scope and acceptance

Add an explicitly selected standalone `run --observer-prefixes` capture and
`observer_prefix_identity` assertion for the supported synthetic IPv4 recipe.
The sink exposes a bounded snapshot of accepted prefixes over an optional local
Unix socket. The worker requests it after the existing measurement lifecycle
returns, before owned cleanup, within the worker budget. No listener or new
UPDATE locking exists without the opt-in. Existing logs, convergence, recipe
identities and five default assertions remain unchanged.

Compare the complete accepted set with the recipe's generated disjoint /32
prefixes starting at 100.0.0.0. Snapshot capacity is 100,000 held and accepted prefixes;
never compare a truncated set. Missing, invalid, oversized or interrupted
capture is unmeasured. Retain timestamps, session/update metadata, selection,
recipe binding and evidence hashes. This witnesses final state at one instant,
not convergence-time identity, route attributes or continuous correctness.

Meaningful checks: correct set; same count with substituted prefix; missing and
extra prefixes; duplicate/noncanonical/IPv6 evidence; old packages; byte changes;
bounded/failed socket reads; accepted/rejected replacement, withdrawals, session
reset and concurrent capture. Independently review code before local commit and
run native repository gates plus offline Go race/vet checks with cached modules.

Repeated comparison and bisection capture integration is deferred. Opt-in
functional investigation capture is now implemented in its
[follow-on milestone](investigation-prefix-identity.md). A
separately selected assertion on a package without capture remains unmeasured.
No source/build/worker execution, acquisition, push, publication or deletion is
authorized by this implementation goal. Performance policy stays disabled and
formal 10% calibration deferred. A new sink image and real runtime compatibility
remain separately approved validation work.

## Progress

- Checkout verified clean on `milestone-a-newcomer` at `987159c`; host guard passed.
- Read sink, assertion, runner, result, recipe and invariant contracts. Independent
  design review selected post-measurement capture over per-UPDATE logging or
  End-of-RIB-only snapshots, which would change costs or leave stale evidence.
- Implemented explicit standalone capture, bounded socket transport and the
  separately selected identity assertion. Default assertion bytes and limits
  remain unchanged. A controlled same-count substitution passes the count
  assertion and fails identity with one missing and one unexpected prefix.
- Independent source review accepted the final diff after resolving long Unix
  path handling and invalidating session snapshots before blocked reset logging.
  Each correction has a regression test. The container/host UID boundary uses
  a mode-0666 socket under a required private mode-0700 monitor bind directory.
- Native Python gate passed 2,691 tests before the final long-path regression;
  subsequent focused Python/docs checks passed 147 tests. Final native commit
  gate and pinned offline Go vet/race results are recorded in the external
  local checkpoint `/tmp/bgperf2-prefix-identity-20261101/completion.md`, including
  the actual implementation commit. No runtime case executed in that offline
  implementation checkpoint.

## Larger synthetic capture extension — selected 2026-11-08

Extend the same exhaustive IPv4 list snapshot and host set-difference oracle
to at most five million held/accepted prefixes. Do not replace identity with
count agreement, a truncated list or a sampled oracle. Preserve the current
100,000-prefix/4-MiB/three-second client bounds for smaller recipes; larger
selected recipes may use an explicit bounded 128-MiB/30-second post-measurement
transport. Keep the schema and existing clock/measurement definitions unchanged.
The sink must still copy one complete table atomically and release its UPDATE
lock before sorting, formatting and transport. Extend its bounded write window
for larger snapshots only. New capacity is not demonstrated native readiness:
review, required Python/Go checks, an immutable rebuilt sink and native exact-set
admission precede larger experiments. Original sink images and small-case
evidence remain retained.
Sink 0.3.0 exposes the explicit larger limit while retaining the 100,000 default.
The pretty-printed large capture envelope alone may use a bounded 256-MiB
offline inspection; this does not raise ordinary metadata limits.

Before larger fanout execution, also close the interruption gap in the public
controller: killing its host worker stops sampling, but owned container daemons
and generators otherwise continue allocating while diagnostics run. On an
interrupted/timed-out worker, promptly quiesce only re-inspected attempt-labelled
container IDs, prioritizing the target, before slower collection. Retain explicit
stop actions/errors and distinguish a controller-planned stop from a native
daemon crash. Do not remove resources before preserving their available logs;
normal completion/capture and final owned cleanup retain their current owners.
Unobtainable post-stop gauges/queries must remain unavailable, never zero or
successful correctness evidence. Source changes and meaningful regressions
require independent review before commit and native admission.
The selected mechanism pauses owned containers, target first, after rechecking
immutable IDs and attempt labels, and retains `owned-quiescence.json`. Normal
completion stays unchanged; interruption/timeout quiescence precedes collection.
Paused role state is explicit and cannot attest healthy running roles. The
existing final owner-checked cleanup removes the paused resources. A separate
network-isolated native preparation probe confirmed paused-state reporting and
forced removal without BGP traffic; its original receipt remains retained.

## Earlier remaining validation

The [2026-11-03 real-BIRD case](observer-prefix-runtime-validation.md#successful-existing-image-worker--2026-11-03)
now validates this specific runtime path: one 12.088-second worker, all six
assertions passed, exact 100-prefix snapshot, 45-artifact verified package,
observed directory/socket ownership and modes, and independently accepted owned
cleanup. Capture integration into repeated comparison/search and broader workload/UID
qualification remain deferred.

### Historical remaining-validation proposal

The paragraphs below retain the earlier manual admission refusal and original
next-case proposal as history.

Implementation is complete at `e7798ad` with the final 2,692-test gate and
independent review. The [real-BIRD runtime case](observer-prefix-runtime-validation.md)
was prepared at `9bcfe1d`; its approved single attempt stopped for concurrent
development at admission, with zero builds/probes/workers. It is closed; real
runtime compatibility needs a separately selected fresh case and approval.

The [public contract](../observer-prefixes.md) supplies exact selection and
evaluation commands. The implementation milestone is complete when final gates
and the reviewed local commit are retained. A future execution case must pin
a newly built supporting sink image and authorize its build plus a bounded
standalone BIRD worker. Existing source/image/evidence and prior authorizations
are preserved; no old image is automatically replaced. This goal's offline
checks do not qualify real container UID access, image startup, performance,
or upstream-bug detection. Comparison/search capture integration remains deferred.
