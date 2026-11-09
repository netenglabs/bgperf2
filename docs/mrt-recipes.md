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
