# Exact-input MRT on the native performance CLI

Selected by the operator's correction on 2026-11-13: routine performance sweeps
use `bgperf2.py bench` and `batch`; portable recipes remain the reproduction /
troubleshooting interface. This work adds fixed-input support to those performance
commands without an export/check/run/package/verify subprocess chain per cell.

Reuse the existing MRT workload schema, input verifier, fixed-peer injector,
source-derived expectations and post-measurement prefix capture. Preserve the
existing convergence clock, sampler and row definitions. Native cells retain
input identities, offering, exact final identity, images and unique work/results;
ordinary commands without the opt-in keep their current behavior.

Add explicit MRT workload and immutable generator/observer image options to bench
and batch targets. A batch binds each workload file's hash into its cell identity
and validates all selected inputs before its first worker. The engine writes a
compact native result receipt, with post-measurement prefix evidence, rather than
creating a portable result package for every performance cell.

An optional local cell-control directory supplies an admission/replay handshake
for an external operational supervisor. The engine owns measurements and cleanup;
the supervisor owns quiet-host, memory/disk/CPU, swap and campaign budgets. No
private repository or policy is required to use native bench/batch. Each cell
has a fresh identity and bounded waiting; cancellation must interrupt waits and
owned cleanup must complete before another cell. Batch gains explicit opt-in
stop-on-failure. No automatic retries or implicit resumes.

Validate malformed/changed workloads before side effects, fixed peer/ASN mapping,
immutable image selection, capture after the measurement boundary, offering and
exact-set refusals, unique work, cancellation, cleanup, batch identity and legacy
behavior with modeled tests. Native campaign qualification is a separate step;
no existing historical evidence is reclassified by this implementation.

Status: native binding, owned cleanup, exact final evidence, batch identity and
optional operational handshake implemented and reviewed. Focused modeled CLI /
legacy batch checks pass; full native quality gate and live campaign qualification
remain required before performance conclusions. No existing originals changed.
