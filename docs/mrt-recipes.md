# Input-bound MRT recipes

Use `recipes.py export ... --mrt-spec /absolute/mrt-spec.json` to bind an MRT
workload to a selected supported batch topology cell. Supply the immutable
bgpdump2 image as `--generator-image`. This emits the distinct
`bgperf2/mrt-recipe/v1alpha1` schema. Ordinary exports retain their exact schema
and behavior. No Docker, input read, image acquisition or execution occurs at
export. The existing `validate`, `inspect`, `plan`, `check`, `assertions-export`,
`run`, `result-verify` and `assertions-check` commands consume the variant.

The embedded batch source and `legacy` identity describe only the selected
topology cell. They do not name the MRT workload. `resolved.target.tester_type`
and `roles.generator.adapter` identify bgpdump2; the complete recipe digest
binds the actual MRT workload and declared expectations.

The strict MRT specification has these fields:

```json
{
  "schema": "bgperf2/mrt-workload/v1alpha1",
  "input": {"path": "/absolute/input.mrt", "bytes": 1234, "sha256": "64 lowercase hex characters"},
  "peers": [{"index": 6, "asn": 34549, "prefixes": 1000000}],
  "target_asn": 64515,
  "observer_asn": 64516,
  "expected_prefixes": ["192.0.2.0/24"],
  "expectation_description": "Explain the predeclared expectation and its policy assumptions."
}
```

Choose 1–128 unique peer indexes below 4096. Preserve their explicit order and
original nonzero four-byte ASNs. Each declares 1–5 million offered IPv4 entries.
The topology's neighbor count must equal the selected peer count and its resolved
per-peer prefix parameter must equal the largest declared peer count. These
topology parameters are not the expected exported set size. Role ASNs must
differ from each other and every selected source ASN. Verify role ASNs against
the actual input paths separately if an artificial own-AS loop is unwanted.

`expected_prefixes` is an explicit, unique, lexically sorted list of canonical
IPv4 networks (1–5 million), not just a count or digest. It is carried with the
recipe into the portable result package. It cannot exceed the sum of declared
offered entries. The final observer snapshot is compared exhaustively with this
set. The engine does not infer arbitrary MRT export policy, best paths or a set
from target output. A source RIB entry count alone is insufficient to construct
the expectation. Attribute correctness and continuous health are not established
by final prefix equality.

`check` first passes the existing environment/measurement guard, then reads the
whole canonical regular input with a 120-second identity-verification deadline.
The worker repeats complete buffered SHA-256 verification before and after the
existing lifecycle, outside its measurement boundary and inside its worker
budget. Size, hash, file/path identity and the selected peer-table indexes/ASNs
must match. There is no cold-cache claim. Expected entry counts remain declared
and are cross-checked through the existing generator offering evidence; the
identity verifier does not re-parse all RIB attributes. A whole-file preparation
inventory remains necessary for constructing valid workloads. Changes between
checks that restore the original identity cannot be detected. Worker interruption
can leave the final receipt missing; it never attests successful execution.

The input is mounted read-only. The scoped existing bgpdump2 adapter uses fixed
peer mapping, original source ASNs, explicit `-4`, `-T 0` (no prefix truncation),
and the existing `-S` next-hop-self rewrite. Ordinary bgpdump2/batch/scenario
behavior stays unchanged. Existing setup, clock, convergence/assurance,
15-second no-progress, pin/readback, ownership, timeout and cleanup rules apply.
No trace-I/O instrumentation or target policy tuning is added. The existing
monitor checkpoint uses 99% of the declared expected set, floored at one;
independent assertions still require exact count and prefix equality.

Prepare small deterministic fixtures with:

```sh
venv/bin/python scripts/make_mrt_control.py --case plain \
  --target-asn 64515 --observer-asn 64516 --source-asn 64520 \
  --output-dir /absolute/fresh-fixture-directory
```

Cases are `plain`, `export-scope`, `as-loops`, `as-set`, and `long-paths`.
Each includes ordinary positive routes; negative cases never rely on an empty
observer table attesting convergence. Scope communities cover NO_EXPORT,
NO_ADVERTISE and NO_EXPORT_SUBCONFED across eBGP. Loop cases contain the target
or observer ASN. AS_SET expectation follows the default rejection in
[RFC 9774 section 3](https://www.rfc-editor.org/rfc/rfc9774.html#section-3).
Long paths contain 254–258 and 260 ASNs in legal segments of at most 255 ASNs.
They are diagnostic controls, not real-table policy qualification or proof of
preserved received attribute values. Native outcomes remain unqualified until
measured; mismatches must not silently change expectations or daemon settings.

Comparisons, minimization, investigations and local source builders currently
refuse this schema. Use explicit bounded originals; modeled tests and successful
export alone authorize neither a native worker nor a performance conclusion.

## Injector attribute grouping

The unmodified upstream injector can reuse a shorter attribute block for a
later, longer block because its attribute cache uses populated longest-prefix
lookup. This can erase trailing communities while preserving prefix counts.
Exact route-set equality alone cannot detect that transformation. The small
community control is required before relying on community export expectations.

The opt-in `FULL_40_HEX_COMMIT-pa-exact-v1` bgpdump2 build profile changes the
single cache lookup to upstream's existing `ptree_search_exact`. It requires the
exact old source statement, checks the replacement, and fails on drift. For
example, build only the selected new tag through:

```sh
venv/bin/python bgperf2.py update bgpdump2 \
  --versions a0191842fedf001abbda6364ab5c70d3f1c0788d-pa-exact-v1
```

Ordinary refs/default recipes remain unpatched. A profile is not an upstream
release. The retained source commit remains upstream's commit, with an explicit
local one-call patch; queried versions include `[pa-exact-v1]`. Preserve the
recipe, complete upstream commit, actual source diff, patch identity, image ID,
binary hash and build logs. The image marker is a build record, not independent
binary-to-source proof. Existing images/results stay intact, and fresh native
qualification is necessary before adopting the corrected generator. This fixes
only the identified grouping defect; it does not qualify every BGP attribute,
remove next-hop-self or expand the injector's supported attribute set.

## Prepare exact source-prefix profiles

`venv/bin/python scripts/prepare_mrt_profiles.py --input /absolute/input.mrt
--expected-bytes N --expected-sha256 SHA --profile-spec /absolute/selection.json
--output /absolute/fresh/inventory.json` performs offline full-file preparation.
The output parent must already exist; `inventory.json` and its sibling
`workloads/` must be fresh. It launches no Docker or benchmark processes.

Selection schema `bgperf2/mrt-profile-selection/v1alpha1` has exactly `schema`,
`peer_indexes` (ordered unique indexes, at most 128), `group_sizes` (one to three
increasing lengths of nested peer subsets, ending at the peer count),
`target_asn`, and `observer_asn`. Both role ASNs must be absent from the entire
source peer table and every selected path. For example, a single-peer selection
uses `peer_indexes: [6]` and `group_sizes: [1]`.

The two profiles are `as-set-reject-v1` (union of paths without AS_SET) and
`as-set-forward-v1` (union allowing AS_SET). Both are declared source-derived
prefix sets; target output never selects their membership. They assume import
rejection of AS_SET before selection in the rejecting profile, and downstream
transit for ordinary paths. NOPEER is retained: its advisory scope concerns
bilateral peer relations ([RFC 3765 section 2](https://www.rfc-editor.org/rfc/rfc3765.html#section-2)).
Choose the target's profile before measuring and report behavioral differences.

The preparer refuses per-peer duplicate IPv4 prefixes across records,
malformed or missing ORIGIN/AS_PATH/IPv4 NEXT_HOP, unexpected first AS, AS0 or
role-AS paths, confederations, MP_REACH, export-scope communities, and encoded
attribute blocks over 4061 bytes (a conservative standard UPDATE bound with seven bytes reserved for prepend/length growth).
These are explicit scope limits, not a complete RFC attribute validator or
best-path simulator. Unsupported conditions refuse every workload; they never
silently filter valid source routes into an easier expectation. First-segment
length 255 and segment counts are recorded separately for known prepend-boundary
investigations; a long total path alone does not establish that condition.

Complete size/hash and path/file identity checks precede workload publication.
One to three nested groups share a bounded five-million-prefix universe; input,
record and parse-time bounds are inherited from the inventory reader. Specs
contain full explicit canonical IPv4 lists and actual per-peer offered counts.
Keep these potentially large derived artifacts outside Git, retaining their
size/SHA-256 descriptors and source inventory with evidence. Files are exclusive,
mode 0600, with no resume or overwrite; interrupted publication can leave partial
artifacts and is not a successful preparation. A prepared source expectation
still requires injector controls, exact native observations and independent
campaign acceptance. Preparation does not qualify a daemon or prove on-wire
attribute preservation.


The standalone `assertions-check` permits packaged MRT recipes up to 128 MiB
because their explicit expected-prefix lists can exceed ordinary JSON metadata.
The bounded loader parses at most 128 MiB before checking schema, then refuses
non-MRT recipes over the prior 8 MiB limit. All recipe schema, package integrity
and canonical digest checks remain required. Other JSON evidence retains its
existing limits; this does not broaden investigation/comparison workloads or
change original experiment outcomes.


An observer must accept valid unknown extended-community subtypes. Sink 0.3.0's
GoBGP v4.9.0 parser can treat unknown EVPN subtype 249 as withdraw, losing a route
that the target exported. The [0.4.0 correction](plans/sink-unknown-evpn.md)
uses the explicit `unknown-ec-v1` dependency correction and reports that profile.
It differs deliberately from the unpatched reference for this RFC 7606 defect.
Original inputs and declared sets stay intact; native qualification and fresh
instrument-bound originals remain necessary. Go vet/race tests use
`scripts/sink_go_test.sh`, which applies the same guarded dependency copy as the build;
a direct unpatched `go test` exposes the dependency's counterexample instead.

Dependency-copy mechanics and source-integrity guarantees are documented in the
[observer correction plan](plans/sink-unknown-evpn.md).


Additional controlled fixtures are `unknown-extended-community` (ordinary route,
the original correctly sized unknown-EVPN community payload, and an unrelated
unknown transitive type; all must transit) and `extended-community-length`
(ordinary positive route and one malformed seven-byte attribute; only the
ordinary route is expected). Both derive expectations from RFC 7606 section
7.14 before target output. They qualify prefix behavior, not preserved exported
attribute values. The unchanged basic attribute inventory is not a complete
validator for the deliberately malformed extended-community fixture.

## Pre-replay supervisor gate

An MRT recipe supervisor may pass `recipes.py run --pre-replay-gate`.
After container setup and observer session establishment, the worker publishes
`pre-replay-ready.json` in the fresh attempt work directory. The supervisor
releases replay by atomically writing the same `bgperf2/pre-replay/v1alpha1`
document to `pre-replay-release.json`. Its `attempt_id` binds the release to
the worker. The existing worker timeout includes the wait. The gate precedes
the observation clock, target sampling and generator launch. The legacy total
wall-time column includes the wait.
