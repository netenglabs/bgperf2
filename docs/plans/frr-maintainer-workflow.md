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

## Reviewed implementation delivered — 2026-11-04 UTC

Implementation commit: `f81404bd2bd65eb16f58ff334d135b3acc295e2d`.
The actual repository `/code-review` workflow accepted the frozen complete diff
with no findings; its SHA256 is
`a8127b59aa2322ef26199927c13ed17f01e72ac73a0b724f6551d42c911f6569`.
The ready review matched the source/index/Git state immediately before the local
commit. The ordinary native hook passed its measurement guard, checked the
34-package locked environment, and passed **3,071 tests, one skipped** in
255.50 seconds. No hook was bypassed. Review/provider output, gate receipts,
commit output and checks are retained under the evidence root; no push occurred.

Final modeled evidence is `modeled-staged-final/REPORT.md`: 60 public CLI
receipts, 14 distinct simulated originals and nine valid verification receipts.
The accepted code review is preserved in `accepted-review/`. The earlier
`modeled/` refusal and both intermediate successful walkthroughs remain intact.
Implementation and modeled-contract acceptance are complete. Live FRR adapter,
diagnostic and original-pair qualification remain unassessed.

## Concrete live validation scope for one approval

The supplied-image metadata and prior prefix-capable observer evidence select
one same-image FRR A/A pair. This is a compatibility question: does the existing
compiled FRR adapter deliver exactly 100 expected IPv4 /32 routes through the
portable workflow on each independent original? It alleges no bug, fix, changed
binary, source revision or performance difference. Generator and observer stay
fixed. Source, binary build flags and instrumentation of FRR remain unknown.

| Role | Existing immutable local image |
| --- | --- |
| FRR target, both sides | `sha256:2ab2018dfe70088f318ee9b9c976bd2fd610580460e1715fe14548042dcc133d` |
| BIRD generator | `sha256:db0a8e144635b1d4b9f81f24ee78f11383c5b0cbd79f10353edcb8452e9af423` |
| Prefix-capable sink, currently untagged | `sha256:58491f5d3ad4d4872c13d53243f482f3cf7245997991b924990358795212ab38` |

Budget: two serial original workers, one baseline and one candidate, each at
most 120 seconds, one peer and 100 prefixes, no retries. Two are needed to test
the investigation's independent-original accounting; a copied result cannot
supply the other side. Zero builds, acquisitions or additional probe workers.
The first worker must pass all six assertions, original-package checks and an
actual independent review before the second can start. Candidate checks, report
verification, correctness/status inspection and fresh report reconstruction then
require final independent acceptance. Each invocation has a practical 240-second
outer cancellation bound plus 15-second termination grace; unknown cleanup stops
successors and never authorizes another worker.

The packet freezes the final clean checkout into an independent detached clone,
copies its locked environment and inventories private source/Git/environment
dependencies. Exact public argv, environment allowlist, source/image bindings,
evidence paths, conditional review gates and recovery live in
`preparation/case01/` under the evidence root. `preparation/prepare_case.py`
prepares and verifies that packet without executing it. Independent tooling
review `preparation/tool-review-02.json` resolved the initial metadata-step and
environment-pinning findings. Frozen packet readback remains a separate required
acceptance step after this documentation checkpoint; actual results belong only
under the fresh `execution01/` sibling after explicit approval.

Read-only readiness observed the exact images, native guard, locked environment
and required tools successfully. The available-memory/disk snapshots exceeded
the declared 16 GiB/20 GiB floors. Recheck before each worker; snapshots are not
reservations. `/tmp` is disk-backed ext4 on root device `/dev/sda5`, requiring
an explicit **functional-only root-storage exception** in execution approval.
No quiet-CPU wait, hourly scheduling or measurement-host qualification is implied.
Advisory activity and runtime contention/missing reasons remain evidence.

This small case deliberately uses standalone unconverted result packages and
retains original work; it changes no deployed artifact-store defaults, timer or
existing evidence. Any refusal, failed assertion, missing capture, interruption,
unknown launch/cleanup, changed identity or rejected review stops successors.
Preserve every partial output and reconcile exact owned resources; no automatic
retry, broad Docker cleanup, evidence deletion or acquisition is authorized.
No live worker/build has run in this milestone. Performance policy stays
disabled, formal 10% calibration deferred and the upstream investigation paused.
