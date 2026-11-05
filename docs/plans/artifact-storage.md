# Shared artifact storage implementation

Selected by the operator on 2026-11-01 after local evidence cleanup showed that
successive report packages repeatedly copied the same tester logs and configs.
This is storage work; it authorizes no experiments, source builds or transfers.

Implementation branch: `feature/artifact-storage`. The storage core is published
in `6b56a29`, with test binding isolation in `9a9bf34`. Initial consumer
deployment was activated and verified on 2026-11-03 UTC (2026-11-02 Pacific).
Consumers retain ownership of their deployment and worker pins.

## Scope and ownership

The engine owns a documented versioned storage transport, direct attempt
collection, reference-aware result/report readers, independent materialized
exports, and optional derived Parquet tables. The lab owns explicit store
bindings, post-container cleanup integration and idle-host maintenance scheduling.
Historical attempts and frozen controller pins remain unchanged.

## Decisions

- Full-file content addressing and Zstandard; checksum original bytes.
- Separate transport catalog; existing result status/schema and attempt identity
  remain authoritative. Physical small files remain directly readable.
- No shared writable hard links to evidence and no repeated complete report trees.
- Store-wide publication/GC locking, durable immutable roots, verified reads,
  no overwrite, and no expiry of registered observations.
- Automatic reclamation only after verified publication, durable metadata and
  explicit successful backend cleanup; uncertainty preserves work.
- Standalone Parquet converter environment keeps the engine lock unchanged.
  Derived sample tables retain source checksum, nulls and measurement scope.

## Acceptance

- [x] Concurrent publications of identical content produce one valid object.
- [x] Repeated comparison packages reuse one object and reconstruct their reports.
- [x] Portable exports verify with the original store unavailable.
- [x] Corruption, changed sources, unknown cleanup and missing registered objects
  preserve work and stop unsafe reclamation/GC.
- [x] Explicit failed/interrupted attempts preserve outcomes and verified evidence.
- [x] Real Parquet conversion preserves values, nulls and source identities.
- [x] Lab public-CLI capture/reclamation and stored-report accounting tested.
- [x] Final full engine/lab suites and implementation review recorded.
- [x] Operator authorization to commit and push both implementations.
- [x] New local production engine/consumer pins and timer activation.

Activation covers explicitly configured new local workflows. Frozen running
jobs retain their original pins. No benchmarks are required to validate these
pure storage changes; existing runtime qualification remains unchanged.

## Initial deployment — 2026-11-03 UTC

The consumer installed dedicated clean release checkouts at engine `6eb876d`
and lab `5757f9a`, a persistent separate PyArrow 26.0.0 environment, storage
defaults and a pinned launcher. The idle-host maintenance timer is enabled;
its first apply run completed successfully with zero evidence expired. Installed
configuration hashes and the exact bindings are recorded by the consumer's
deployment journal, outside tracked source.

The maintained simulated smoke verified two independent attempts and three
checkpoints sharing two bulk objects, matching-work reclamation, an independently
verified portable export, and exported Parquet tables preserving nulls. No real
benchmark, historical evidence migration or remote evidence transfer was run.
Later source publication (`376ca38` and consumer `bf682b4`) supplies the generic
setup/delivery tools; it does not silently move those deployed worker pins.

## Local validation — 2026-11-01 Pacific

- Engine: 2,734 tests passed, including real Parquet conversion using the
  separately installed PyArrow 26.0.0 environment.
- Lab: 808 tests passed; two pre-existing opt-in integration checks skipped.
  The explicitly bound public storage CLI interoperability check passed.
- Maintained simulated smoke: two independent attempts, three reference
  checkpoints, two unique bulk objects, five registered packages, automatic
  verified work reclamation and successful independent export. The optional
  Parquet artifact reported exported with source checksum and two rows.
- Actual local maintenance dry-run against that simulated store: five roots,
  two verified objects, no orphan/staging work and zero evidence expiry.
- User service/timer unit verification, Python compilation and both working
  diffs' whitespace checks passed.
- Implementation review covered publication/GC ordering, concurrent writers,
  source mutation, corruption, unknown cleanup, unlisted references, independent
  exports and nested report checksums. Compound capture explicitly refuses
  nested catalogs; aggregate export preserves its constituent reports instead.
- Required `/code-review` found and prompted fixes for integral-float memory
  samples, killed-converter staging, optional receipt failures, all-work-root
  idle checks, bounded maintenance and nonfatal scratch reclamation. Catalog
  parsing is strict and preservation reuses verified immutable-object reads.
  Per-read engine catalog parsing remains a documented performance follow-up;
  it does not weaken checksum verification or change result semantics.
- Follow-up review fixes preserve legacy physical-package path behavior,
  partial collection results, read-only input stores and bisection export
  inventories. Series inherit a shared host lock, malformed reference exports
  fail cleanly, and converter staging is leased inside the store.

Review decisions: full source/archive readback intentionally uses independent
passes to preserve the existing integrity contract. The scheduled maintenance
budget intentionally fails closed for stores that need a longer selected idle
window; it never expires registered evidence. Missing-container runs retain work
with their existing capture error, and unsafe source packages are refused before
report copying. Per-artifact catalog parse caching remains a performance-only
follow-up; repeated entry-point destination guards and publication locking are
intentional safety boundaries.
The final review identified one cross-filesystem Parquet publication blocker;
publication now uses a work-volume temporary copy and a local atomic link, with
a regression that rejects cross-volume links. Additional fixes give clean
refusals for malformed roots and incomplete reference exports, preserve missing
object uncertainty in lab accounting, and retain integrity diagnostics in the
maintenance journal. Durability failures deliberately stop publication and retain
work; a written experiment manifest is not rewritten to claim durable storage.

The core locked environment was reused without installing packages into it;
an ephemeral worktree `venv` binding was used for initial prerequisite tests,
then locked environments were copied into the isolated worktrees for Git hooks. Only the
separate converter environment acquired PyArrow. No daemon build, benchmark,
remote transfer, evidence migration, production pin update or timer activation
was performed. Pre-commit `/code-review` is part of the authorized commit gates.
Historical frozen campaign sealers require materialized exports or
migration to the maintained reference-aware preservation path before adopting
the new transport.
