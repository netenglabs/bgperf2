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
