# Source-derived MRT prefix profiles

Selected 2026-11-09. Prepare exact source-prefix expectations offline, before
any target output. Reuse the bounded TABLE_DUMP_V2 reader and attribute decoder;
add no benchmark runtime, convergence policy or daemon configuration changes.

Accept an explicit ordered peer selection, up to three nested prefix lengths,
and distinct role ASNs. Derive unique IPv4 unions for two declared profiles:
allow AS_SET, or reject AS_SET before path selection. Refuse ambiguous inputs:
per-peer duplicate prefixes, malformed/missing required attributes, role-AS/AS0
paths, unexpected first AS, confederations, export-scope communities, MP_REACH,
and oversized attribute blocks. Record first-segment lengths separately from
total path length so callers can assess known prepend boundaries honestly.

Whole input size/hash and file identity must pass before publishing specs.
Write exclusive private workload artifacts outside Git, with size/hash
references in a small inventory. Bound input/records/time through the existing
reader, unique prefixes to five million, selected peers to 128, and groups to
three. Preparation never reads target output or proves wire attribute fidelity.

Verify overlapping unions, profile differences, refusals, bounds, source
mutation and fresh-output behavior. Review code before committing and run the
engine quality gate. Native preparation and measurements remain separate
explicitly authorized operations with frozen sources and host guards.
