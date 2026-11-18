# Exact MRT input inventory

Selected 2026-11-09 as preparation for explicitly requested exact-input MRT
testing. This plan adds consumed-input inspection to the engine. It does not
select a source-peer set, predict target export policy, or authorize traffic.

First deliver a bounded, Docker-free TABLE_DUMP_V2 inventory command. Require an
explicit absolute regular input and its expected byte size/SHA-256. Stream the
entire input, retain the peer-index table and IPv4/IPv6 unicast RIB entry counts
per peer, and reject truncation, unknown types/subtypes, invalid peer references,
oversized records, identity changes and deadline expiry. Bound memory by record
size and peer count; never hold all route attributes or prefix sets. Counts are
RIB entries, not a claim of unique prefixes or eligible exported routes. Treat
attribute bytes as opaque and say so. Follow RFC 6396 sections 2 and 4.3.

Tests must cover IPv4/IPv6 peers, two/four-byte ASNs, mixed RIB families,
truncation/length errors, duplicate peer entries within one prefix record,
unknown types, nonexistent peer indexes, wrong identities, deadlines and safe
fresh output. Review and run engine checks before committing. Native inspection
requires an idle host and lab-owned serialization/pressure guards. Its result
is preparation evidence, never a route assertion or measurement.

Subsequent work remains separate: explicit fixed nested source-peer selection,
input-bound workload/exhaustive expected-prefix support, attribute/protocol
controls and native qualification through existing bounded orchestration.
Do not silently use the legacy dynamic eligible-peer mapping as a fixed set.

Implemented the standalone `scripts/inspect_mrt.py` and pure `mrt_inventory`
module, with 21 focused checks passed before review. It retains explicit
unsupported forms and opaque-attribute limits; no native MRT inspection or
replay is qualified by these modeled checks. Native preparation must bind the
committed implementation and preserve both failures and successes.

Next add explicitly selected encoded-attribute facts to this same streaming
inspection. Select peer indexes and ASNs to check, retaining input identity and
all default opaque-attribute behavior when omitted. Count standard export-scope
communities, checked ASNs in four-byte AS_PATH, AS sets/confederation segments,
first-AS/attribute-presence facts and malformed known attributes. Keep bounded
examples and per-peer counters rather than all routes. These are encoded facts,
not a best-path/export model or expected set. Use them to determine whether the
selected real input can support an unambiguous declared oracle before replay.


Select bounded exact-prefix diagnostics after a full-table one-prefix mismatch.
Extend optional attribute inventory with up to eight canonical IPv4 prefixes
and sixteen source peers; retain the original opaque/default behavior. Capture
raw source attribute bytes as hex and hash, plus existing decoded facts, for
matching peer/prefix entries only. Reject duplicate selected entries, bound raw
hex/detailed facts to 4096 bytes per entry, and explicitly report withheld facts
or absent entries. Reuse complete input identity/deadline checks; no new parser,
route oracle, injection or target policy is introduced. Review and test bounds,
malformed/large raw data, exact prefix matching and default compatibility.

Review followups: retain the original counter/MP_REACH interpretation scope and
append the selected-prefix limitation. Preserve encoded source NLRI and its
unused-bit status separately from canonical network matching through a small
optional observer callback on the same reader. Test nonzero unused bits without
calling them an invalid network or changing default inventory behavior.
