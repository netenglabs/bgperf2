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

Comparison, investigation and bisection capture integration is deferred. A
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
  the actual implementation commit. No runtime case has executed.

## Remaining validation

The [public contract](../observer-prefixes.md) supplies exact selection and
evaluation commands. The implementation milestone is complete when final gates
and the reviewed local commit are retained. A future execution case must pin
a newly built supporting sink image and authorize its build plus a bounded
standalone BIRD worker. Existing source/image/evidence and prior authorizations
are preserved; no old image is automatically replaced. This goal's offline
checks do not qualify real container UID access, image startup, performance,
or upstream-bug detection. Comparison/search capture integration remains deferred.
