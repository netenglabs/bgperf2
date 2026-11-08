# Supplied-image admission for existing daemon families

Selected 2026-11-07. Status: implementation and qualification in progress.

## Research need

Current-build characterization needs the existing OpenBGPD and RustyBGP
adapters to use the bounded synthetic recipe and exact-prefix assertion path
already available for BIRD and FRR. A legacy batch adapter alone does not
establish that a fresh build delivers the declared routes or cleans up.

## Scope and acceptance

Support supplied immutable `openbgp` and `rustybgp` target images for the
existing synthetic IPv4 workload, BIRD generators and sink observer. Preserve
the workload, schemas, BIRD/FRR identities and measurement definitions. Use
the existing scoped worker, lifecycle, owned cleanup and result/assertion
verification; do not create a second benchmark runtime.

1. Export, validate and substitute targets with matching adapter identities.
2. Classify actual target container names correctly in live/final diagnostics.
   Preserve container-level health/memory evidence. Daemon process presence,
   daemon exit/crash witnesses and target thread controls remain BIRD-only.
3. Refuse new local-source builds and revision searches before source/host
   probes or checkout creation. BIRD/FRR source builders retain their scope.
4. Test actual adapter constructors/configuration, modeled lifecycle dispatch,
   prefix expectations, diagnostic limits and all unsupported-path refusals.
5. Run the repository review and required gates before committing. Separately
   qualify selected real images using bounded small correctness cases and
   preserve original packages, failures and cleanup evidence.

## Runtime qualification protocol

For each explicitly selected local image, freeze the engine commit and exact
target/generator/observer IDs. Use a fresh work/results identity, two generator
peers with 100 distinct prefixes each, a 120-second worker deadline and the
six existing assertions including final received-prefix identity. Record
capacity, concurrent activity and storage decisions. Inspect prerequisites
before each worker and stop on a failed/unknown assertion or uncertain cleanup.

Small functional admission uses the immediate bounded protocol in
[functional validation](../functional-validation.md). Elapsed time is not a
performance comparison. Missing images, capture support or other prerequisites
refuse execution rather than selecting substitutes. A failed attempt remains
separate from any later retry; no retry authority follows from this document.

## Boundaries

New daemon adapters, policy/attribute oracles, IPv6, source builders for these
two daemons and performance calibration are outside this change. Research owns
build selection, matrix order and interpretation. Lab owns serial orchestration,
capacity/quiet admission, preservation and campaign progress. This public plan
is usable without private campaign files and grants no independent execution,
build, acquisition, provisioning or publication authority.
