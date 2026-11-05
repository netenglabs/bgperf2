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

## Approved same-image functional pair completed — 2026-11-04 UTC

The operator explicitly approved the frozen case and functional-only root-storage
exception. Execution used the independent clean source at
`2689ad1ee50d5394575a8daaebc04417c5f04e22`, the exact three image IDs above,
and the reviewed case manifest
`dce85a25d1022961e09ffe69001100392b9abd2d21a3dec66c55e9b591a7c12a`.
The separately sealed host-Git supplement
`1aa8b3fdab7dc3be5856aae20cec149451f35860bd2b5040a61d564978952014`
binds actual configuration dependencies after the runner sanitizes Git variables.
No frozen source, environment, case, supplement or earlier evidence was changed.
Actual execution evidence is `/tmp/bgperf2-frr-workflow-20261104/execution01/`.

| Original | Attempt UUID suffix | Worker seconds | Outer command seconds | Assertions | Exact prefix set |
| --- | --- | ---: | ---: | --- | --- |
| baseline | `2c45f853ed364839a126beefb875c270` | 12.13472594297491 | 14.84437992493622 | 6/6 passed | 100 received, zero missing/unexpected |
| candidate | `c1fa9524c11f490ab41babe2b366ab17` | 11.803601235849783 | 14.356481462018564 | 6/6 passed | 100 received, zero missing/unexpected |

Both original packages verified. Count and prefix-set assertions independently
passed; experiment completion and reproduction retained their existing meanings.
Actual first independent acceptance preceded the fresh candidate prerequisite
checks and second worker. All 47 exact frozen/supplement operation receipts show
exit zero, no outer timeout and empty stderr. There were exactly two original
workers, zero retries, zero builds, zero acquisitions and no scheduler job.

Final independent review accepted with no findings:
`execution01/final-review.json`, SHA256
`069836d6210d5c4866f1aff977e0fa8d33af5bcb4b53cfb7addc7c98f9be5edf`.
It verified approval, source/image/recipe bindings, finite original budgets,
all twelve assertions and original permissions; native lstat found collector-owned
mode0700 monitor directories and mode0666 sockets. Both runtimes record explicit
empty cleanup errors. Native inventories confirm all six exact owned container
IDs and both attempt-scoped networks absent. Foreign resources were unchanged
semantically: 75 containers, six networks and 495 volumes.

Public investigation reporting, verification, correctness checking and status
inspection succeeded. A fresh reconstruction verified and matched all 91 report
files physically and semantically. The portable report is
`execution01/report/REPORT.md`; original work/packages, raw omissions, receipts,
review records and reconstructed report remain preserved. Local preservation is
not independent backup or authenticated execution provenance.

An incomplete automated first-review check initially treated comma-separated
Docker mount order as meaningful and stopped before the independent review was
complete. The exact parser artifact and subsequent review versions are retained.
Set comparison confirmed identical foreign mounts; the completed actual first
review accepted the original. `execution01/protocol-assessment.json` records why
this was not an actual independent rejection or runtime harness failure. No
worker was rerun and no measurement evidence was modified.

The observed target banner was `FRRouting 10.7.0-my-manual-build`; generator
reported BIRD 2.19.2 and observer 0.2.0. This does not establish source revision,
build flags, instrumentation or reconstructibility. FRR zclient warnings remain
in the original logs. Recorded peak foreign CPU was 542%/734%; the selected
immediate functional protocol permits unrelated activity and supplies no quiet
host or performance qualification. Role health remains a bounded container
snapshot, not continuous FRR daemon liveness or a daemon-exit witness.

This completes bounded real-image qualification of the selected FRR
reproduction/assertion/original-pair/report path. Broader live FRR comparisons,
minimization, source builds, revision search, crash reproduction and target thread
controls are not qualified by this case; unsupported interfaces retain their
explicit refusals. No general fix, changed binary or performance improvement is
claimed. Performance policy remains disabled, formal 10% calibration deferred
and the upstream investigation paused. Nothing was pushed or published.
