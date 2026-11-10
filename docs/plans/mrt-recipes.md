# Input-bound MRT recipes

Selected 2026-11-09 following consumed-input inventory and explicit source-peer
selection. Extend the existing bounded recipe controller, worker, result package
and exact-prefix assertions. Do not create another benchmark runtime.

Add a distinct MRT recipe schema as a strict variant of a selected synthetic
batch topology. The embedded batch cell remains topology provenance only; the
MRT specification, role images, input identity and declared expected prefix set
define the actual workload. Preserve all old synthetic envelopes and behavior.
Bind ordered peer indexes, original peer ASNs and declared per-peer offered
counts, explicit target/observer ASNs, whole input size/hash and a canonical
unique IPv4 expected set. Reject missing/unknown fields, duplicate peers,
overlapping role ASNs, invalid prefixes and resource-bound violations.

Read the input through a canonical regular file and verify its complete identity
before execution and after the existing lifecycle, outside its timing boundary.
Mount it read-only. Scope the existing bgpdump2 adapter to the selected immutable
image, fixed peer mapping, explicit IPv4 and `-T 0` (no truncation), with existing
next-hop-self and log/offering semantics. Preserve ordinary engine convergence,
15-second no-progress rules, ownership, pinning, worker budget and cleanup.

Expected prefixes are declarations, never learned from target output. This
delivery does not infer export policy from arbitrary MRT input. Small fixed
protocol fixtures must qualify the path before full-table use. Full-table
expectation generation and ambiguous best-path/policy handling remain explicit
subsequent work. Comparisons, minimization, investigations and source builders
remain synthetic-only until separately qualified for this schema.

Verify modeled schema refusals, tampering, full-file identity and mutation,
read-only adapter binding, fixed mapping, no prefix cap and exact missing/extra
prefix detection. Review before committing and run the engine quality gate.
Native qualification is a separate explicitly authorized experiment with fresh
paths, frozen source/image identities, lab pressure guards and retained failures.


Native full-table calibration exposed an assertion CLI loader mismatch: package
verification accepts the explicit 24 MB MRT recipe, but `assertions-check` reused
the investigation-only 8 MiB loader and refused before producing assertions.
Add a scoped packaged-recipe loader with 128 MiB absolute read bound and strict
MRT-only admission above the prior 8 MiB bound. Retain regular-file/no-follow,
complete schema validation and existing package/digest verification. Leave other
JSON artifacts and investigation contracts unchanged. Test valid large MRT,
large non-MRT refusal, absolute byte/path bounds and CLI forwarding. Preserve
the interrupted native original independently of this reporting fix.
