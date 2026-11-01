# Received IPv4 prefix identity

The optional `observer_prefix_identity` assertion compares the sink's complete
accepted IPv4 prefix set with the selected synthetic recipe. It detects, for
example, 100 received routes containing one substituted prefix even when
`observer_route_count` passes. It checks one final state, not route attributes,
delivery history or identity at convergence confirmation.

## Select capture and assertion separately

Use the existing supported disjoint synthetic IPv4 BIRD/BIRD/sink recipe with
at most 100,000 expected prefixes. The observer must be an explicitly selected
immutable image built from sink 0.2.0 or later with snapshot support. Existing
0.1.0 images do not support this flag; the runner never rebuilds, pulls or
substitutes them. Ordinary runs without the flag still support existing images.
Export the recipe at the clean engine revision and pin the actual new observer
image before authorizing execution. The fixture recipe's image IDs are examples.

```sh
# Explicit execution, only after the host, images, destinations and budget are approved:
venv/bin/python recipes.py run /absolute/artifacts/recipe.json \
  --observer-prefixes --timeout 120 --diagnostics none \
  --workdir /absolute/disk/work/identity-001 \
  --results-dir /absolute/disk/results/identity-001
# Offline export/evaluation; neither starts a worker:
venv/bin/python recipes.py assertions-export /absolute/artifacts/recipe.json \
  --capability observer_route_count --capability observer_prefix_identity \
  --output /absolute/artifacts/prefix-assertions.json
venv/bin/python recipes.py assertions-check /absolute/artifacts/prefix-assertions.json \
  --result /absolute/disk/results/identity-001/result.json
```

Snapshot selection is independent of `--diagnostics basic|none`. The five default
assertions and their exported bytes stay unchanged; identity must be selected
explicitly. The recipe/result envelopes are unchanged. Old engines refuse the
new capability rather than treating it as count agreement. Old packages without
the new evidence evaluate identity as `unmeasured`, leaving the overall assertion
outcome inconclusive unless another selected assertion fails.

Capture currently belongs only to standalone `run`. Comparison, investigation
and bisection plans do not enable it. Selecting this assertion for their packages
without snapshot evidence yields unmeasured, not an inferred pass. No action,
policy, IPv6 or broader workload support is added.

## Snapshot and evidence boundaries

With capture enabled, the worker sets the operator-owned monitor bind directory
to mode 0700 and starts the sink with `-snapshot-socket /root/config/prefixes.sock`.
The socket requires a mode-0700 parent and has mode 0666 so an unprivileged host
client can read a socket created by container root across UID mappings; directory
traversal supplies the access boundary. Without the opt-in, no socket or new
UPDATE-path mutex is enabled. The socket is local and read-only in operation;
it cannot change routes. Existing paths are never replaced or unlinked.

After the existing bench lifecycle returns, the worker connects once, inside its
original timeout and before parent cleanup. The sink copies accepted keys from
the active session under a mutex, then sorts/encodes/writes outside that lock.
Session identity, UPDATE count, accepted count and monotonic timestamp describe
the same state. Rejected-but-held entries are excluded from the accepted set.
Session loss invalidates the exposed table; an inactive session is unavailable.

Both held and accepted tables are limited to 100,000 entries for capture. A
larger table returns unavailable without scanning/copying it. The server handles
one response at a time with a two-second write deadline; the client has one
three-second total request budget and a 4 MiB response limit. Socket failures,
partial replies and malformed evidence do not alter convergence or become a
prefix mismatch. The worker retains an unavailable receipt; if the worker itself
times out, its existing inconclusive/interruption semantics still apply.

The Linux host client connects through an open parent-directory descriptor at
`/proc/self/fd`, so deep work paths do not exceed Unix socket pathname limits.
It does not change the working directory or create a shorter-path alias.

`work/observer-prefix-selection.json` records explicit selection and recipe
binding. `work/observer-prefixes.json` holds the versioned capture receipt and
sink snapshot. Existing full-work packaging hashes both. Runtime socket entries
are omitted with metadata by the existing result collector. Assertions inspect
only listed, hash-verified regular JSON evidence and reject duplicate fields,
duplicate/noncanonical/non-IPv4 prefixes, inconsistent counts, invalid session
metadata or a snapshot outside its request/lifecycle/worker interval. Both
controller and sink must share the existing monotonic clock domain.

Expected identities come from the existing generator's contiguous disjoint /32
sequence starting at 100.0.0.0, independently tested against its Mako generator.
The assertion reports full missing/unexpected counts and at most 20 samples of
each. It does not use the observer count to derive expected identities.

The assertion uses deadline `post_measurement_snapshot`. A positive result also
requires a satisfied recorded worker budget. It cannot establish that the set
was correct at the earlier convergence event or stayed correct before/after the
snapshot. Optional locking and snapshot collection have uncalibrated overhead;
enabling capture does not qualify performance comparisons. No new timing column
or convergence rule is introduced. Performance policy remains disabled and
formal 10% calibration deferred.

Implementation and offline validation are tracked in the
[milestone plan](plans/observer-prefix-identity.md). Real image/build/worker
compatibility is separate validation and has not been established by unit tests.
