# Supplied-image FRR maintainer workflow

Selected 2026-11-04 after minimization checkpoint `506ff4b`. Explicit checkout:
`/tmp/bgperf2-milestone-a`, branch `milestone-a-newcomer`, verified clean at
`506ff4b972b188234649bff5195bfb44ff15cc53` before changes. This Markdown plan
tracks the new goal because the thread goal register still holds the unrelated
paused upstream investigation; that investigation is not resumed or marked done.

## Goal and first scope

Apply the existing portable maintainer workflow to the engine's existing
`frr_c` target adapter, retaining BIRD generators and the sink observer. A user
can export/check/run a supported synthetic IPv4 FRR recipe, substitute a second
supplied FRR image, evaluate assertions and comparisons, and use bounded
peer/prefix-count minimization with verified evidence.

Preserve BIRD defaults, recipe/result identities and existing measurement
definitions. Resolve target identity and role naming consistently rather than
changing a single CLI flag. FRR daemon-specific behavior must use its existing
adapter; do not reuse BIRD's foreground-daemon exit witness for FRR. Unsupported
FRR target-crash reproduction, source builds and revision search fail explicitly
before source/host probes or side effects. Target thread controls remain BIRD-only
in this first supplied-image scope. Supported pinning, counts, health snapshots,
owned cleanup, raw evidence and portable reports retain their existing meaning.

## Complete milestone

1. Extend strict recipe/target validation and immutable role identities to
   `frr_c`, with clear early refusals for unsupported paths and unchanged BIRD
   defaults. Keep generator `bird` and observer `sink` fixed.
2. Route scoped execution through the existing FRR target class, account for its
   actual container names, and provide conservative basic container/memory/
   failure diagnostics without manufacturing FRR daemon-exit evidence.
3. Exercise supplied-image investigation, assertions, repeated/staged comparison,
   and minimization through maintained modeled CLI evidence. Cover partial work,
   unsupported capabilities, changed images and report verification/relocation.
4. Independently review, resolve findings, run meaningful focused checks and
   required repository gates, document exact scope and commit locally.
5. Inspect existing local images and preserved evidence read-only before
   selecting a bounded real validation proposal. If suitable images exist,
   prepare exact commands, evidence destinations, expected outcomes, recovery
   and natural worker budget for one separate execution approval. Missing images
   remain a gap, never an acquisition or build instruction.

No real builds/workers, acquisitions, provisioning, evidence deletion, remote
transfer, push or publication are authorized by this goal. Preserve earlier
evidence and frozen source copies. Performance policy stays disabled, formal
10% calibration deferred, and unrelated source investigation/localization paused.
Use internal checkpoints; do not stop at individual helper changes or routine
implementation choices. Evidence root: `/tmp/bgperf2-frr-workflow-20261104/`.

## Implementation checkpoint — 2026-11-04 UTC

Strict recipes infer `bird` or `frr_c` from the selected source cell and bind the
role/image identity to that adapter. Supplied target overrides cannot cross
adapters. FRR source-build and revision-search plans refuse before source/host
probes. Existing BIRD fixture exports remain unchanged.

Scoped execution selects the existing compiled FRR class and recognizes its
`_frrouting_compiled_target` container suffix. Its startup/configuration remain
unchanged. Basic FRR diagnostics retain container state and target memory while
declaring daemon-process and exit-status witnesses unsupported. Running shell
containers cannot establish bgpd liveness or crash reproduction.

The first focused selection passed 176 tests (contracts, actual adapter shape,
modeled orchestration, supplied targets and existing recipe compatibility),
retained in `focused-01.xml`. No real worker/build was run. The maintained
[FRR guide](../frr-maintainer-workflow.md) supplies public commands and the
strictly simulated walkthrough. Independent review, complete native repository
gate, local commit and frozen live-case review remain required before delivery.

An additional compatibility selection passed 201 tests (`compatibility-01.xml`):
documentation index, diagnostics, existing lifecycle, deterministic bisection
and source-range preparation. Independent manifest readback verified 12,234
preserved regular files, 17 native sockets and 26 symlinks across the previous
minimization, normal/staged prefix and historical cases, with zero findings
(`preserved-evidence-readback.json`). Readback hashed bytes and metadata only;
it neither interprets nor resumes the paused investigation. Local preservation
does not constitute independent backup.

The expanded FRR walkthrough passed eight focused tests and retains 60 public
CLI receipts with 14 distinct simulated original attempts: reproduction (one),
investigation (two), repeated comparison (four), staged comparison (two) and
minimization (five). Staged execution refuses before required first/final
reviews; completed reports reconstruct, relocate and verify. Minimization
confirms the selected modeled count failure at one peer/two routes. All image
identities, failures and observations in these walkthroughs are simulated and
establish no FRR defect or live qualification. Initial inherited-store refusal
and earlier successful outputs remain preserved separately; the smoke now uses
its private artifact store.
