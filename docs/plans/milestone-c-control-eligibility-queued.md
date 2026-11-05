# Milestone C fresh queued debug-control screen

Prepared 2026-10-30 UTC after the closed [eligibility case](milestone-c-control-eligibility.md#execution-and-descriptive-outcome--2026-10-30-utc),
recorded at `1fc573e`. Current status: **diagnostic04 completed and independently
analyzed**; see the [execution record](#diagnostic04-completed-and-analyzed--2026-10-30).
The following original design remains historical preparation; explicit later
operator choices and the actual operating profile are recorded below.
The operator proposed using the existing hourly queue, freed storage and
instructed continued work. This selects one fresh bounded measured case;
zero-worker CPU/capacity admission deferrals may wait for later hourly ticks.
Any post-start stop closes this case and blocks the job for operator review.
The old completed job and stopped case remain closed.

## Question and selected budget

Do fresh optimized/debug pairs again have a larger observed delivery window,
with both execution orders represented in each of two chronological blocks?
This is eligibility/replication of a deliberately large, unknown effect. It is
not a known 10% positive control, powered detection test, causal estimate or
held-out calibration confirmation. Performance policy remains `disabled`,
qualification `not_assessed`, calibration pending.

The preserved 16-pair same-image study supplies design context: paired-log SD
0.0859475, individual changes −11.39% to +20.94%, order/block imbalance and
nonzero outside CPU. The next closed case supplied eight fresh A/A pairs and
three complete optimized/debug pairs before outside CPU stopped worker 23.
The latter had observed changes +66.31% to +82.28%; their confounding and
incomplete accounting remain. Neither study is pooled into this fresh case or
relabelled as confirmation. The three-pair result motivates this screen,
without proving the size or cause of a control effect.

Select **eight fresh optimized/debug pairs, sixteen unique serial workers**:
two separately gated four-pair blocks, each AB,BA,AB,BA (two of each order).
Both use byte-identical baseline and candidate declarations; block 2 requires
accepted block-1 final review. This adds replication within condition across
blocks and reduces checkpoint-copy storage growth compared with sixteen-worker
blocks. Eight pairs is a bounded exploratory budget, not a power calculation.
No new A/A workers, builds, warmups, replacement pairs, adaptive exclusions,
extensions, workload changes or post-start retries are selected.

## Frozen execution inputs

Reuse the [closed case's inputs and gates](milestone-c-control-eligibility.md#frozen-inputs-and-bounds)
with only these changes: zero builds, both blocks optimized/debug, four pairs
per block, and sixteen workers maximum. Timeout remains 120 seconds per worker
(1,920 worker seconds maximum); admission, reviews, cleanup and preservation
are additional. Actual optimized image remains
`sha256:8cc3a97c01b7dd3aa188fb040067aeb70244fd4382183fb5763cb09d5db12f88`;
actual debug image remains
`sha256:7fae42bfc8b00fc0aab6d1321cc7cb8a29f6a25e965949c6e012d0f1242dd3b8`.
Their source/build/instrumentation provenance stays unchanged. The debug build
was cached; it is not fresh compilation. Binary hashes remain unknown and
reconstructibility false. Target recipe bindings change for a clean frozen
documentation revision and a question describing this fresh screen. The workload, pins, four assertions, observer
supplements, diagnostics none and pressure policy remain unchanged.

Use native otherwise-idle `jpietsch-server`, excluding `9950`. Renew the
intentional persistent `/dev/sda5` ext4 root-backed storage exception for this
case and queue records; this does not qualify hardware or establish an
independent backup. Free space was 99 GiB at preparation. Require ≥64 GiB free
disk and ≥48 GiB MemAvailable at every admission; projected space is not a waiver.
Six fresh five-second CPU intervals each ≤one busy logical core, all-UID
no-heavy-job review, active-measurement/locks, exact image/topology/governor/
kernel/mount checks and all original pressure/placement/resolution/cleanup
gates remain. Raw outside CPU >100% permanently stops successors.

The operator's removal of arbitrary elapsed-time cutoffs persists: explicit
matching null deadline in case/authorization/invocation, finite worker budget,
and all per-worker admission/review requirements. A successor that cannot be
admitted after measurement starts closes this bounded case for review.
Before any worker, proven CPU/capacity refusal defers to a later hourly tick;
missing evidence, code changes or non-operational failures block.

## Review, scheduling and preservation

Lab owns the existing minute-10 dispatcher and a fresh hash-bound job ID,
`bgperf2-c-debug-eligibility-02`. Work/results are fresh per-dispatch roots under
`/home/jpietsch/bgperf-work/quiet-debug-eligibility/` and
`/home/jpietsch/bgperf-results/2026/quiet-debug-eligibility/`.
The explicit engine checkout is `/tmp/bgperf2-milestone-a`, branch
`milestone-a-newcomer`; freeze its clean documentation commit in deployment.
Enrollment does not invoke an immediate tick or alter the existing crontab.

Independently review the prepared packet/controller and simulated launch,
deadline, budget and deferral checks before enrollment. At dispatch independently
accept actual case/data/native baseline, every synchronous worker assessment,
first/final public reviews in both blocks and final accounting/cleanup/
preservation. Old receipts never grant acceptance. Preserve all original IDs,
commands, streams, refused/failed/interrupted/never-run positions and evidence;
no resuming the prior case or consuming its unused nine workers.

Use the [existing descriptive definitions](milestone-c-control-eligibility.md#prespecified-descriptive-assessment):
retain every pair/position, paired-log ratios and geometric changes with crossing
brackets, block/order descriptions and confounders. No calibrated threshold or
performance verdict. Any later statistical/control qualification and held-out
confirmation need a separately frozen design. Keep originals, verify complete
source/copy/archive path/type/checksum/metadata coverage and independently review
preservation. Same-device local preservation is not independent backup. No
deletion, remote transfer, push, publication or provisioning is included.

## Preparation checks

Docker-free checks passed: 123 focused controller/deadline/budget/deferral/queue
tests, including complete simulated sixteen-worker launches and refusal of a
ninth worker in a block; broader lab BGP checks passed359, skipped2; engine
documentation checks passed78. The first offline public packet export passed
all six commands without builds/workers; final frozen packet/deployment still
requires verification after the clean documentation commit. The lab operational
record retains source/deployment/enrollment identities outside measured roots.

## Diagnostic04 completed and analyzed — 2026-10-30

The operator explicitly chose “Run now and record background load,” accepting
an exploratory diagnostic without a calibration claim. CPU-only activity was
recorded rather than used as an admission/successor refusal. Fresh case04 used
that explicit mode with native isolation, capacity, provenance, correctness,
placement, observer/pressure monitoring and cleanup protections retained.

| Case | Original workers completed | Never run | Terminal reason |
| --- | ---: | ---: | --- |
| queued eligibility02, `20261030T071001Z-9c3c60c7cc` | 2 | 14 | Stale unconsumed admission closed the case under then-frozen instructions; expiry handling was subsequently corrected. Supervisor later lost model capacity before final reporting |
| fresh eligibility03, `20261030T162645Z-780cc751f3` | 1 | 15 | Operator selected background-load diagnostic mode while worker1 was running; that worker finished before the strict supervisor was paused |
| diagnostic04, `20261030T163822Z-3f08e524c1` | 16 | 0 | Complete, independently reviewed and preserved |

The two stopped cases remain permanently closed and separately preserved;
queue accounting was reconciled from actual packages and independent native
cleanup evidence. No stopped case was resumed or its unused budget reused.
The stale-receipt rule was corrected: before consumption/reservation/Popen,
refresh the receipt for the same unstarted worker without closing the case.

Diagnostic04 completed at `d4bee5dac05d1d96512236b05fc076e5e1af394c` with zero
builds and sixteen unique original workers, eight natural optimized/debug pairs,
two AB,BA,AB,BA blocks, zero failed/interrupted/replaced/never-run positions,
four accepted public first/final reviews and independently accepted cleanup.
Every worker passed exact 2M count, four assertions, requested/effective role
placement, observer reconstruction/resolution, pressure coverage and budget.

An independent Decimal60 reconstruction from original sink count records and a
separate engine-backed analysis agreed on all sixteen integer windows, eight
pair ratios/brackets and grouped summaries. All eight debug windows were longer.
Geometric paired change was **+72.23%**, range **+60.54% to +83.06%**; sample
paired-log SD was **0.052018**. Block means were +72.16% and +72.30%; AB/BA
means +72.83%/+71.63%, with four pairs of each order. The chronological
second/first summary +0.35% is a balanced identity mixture, not a causal order
estimate or fitted correction. Individual timestamp-ratio bounds remain above
zero change; these bounds are not statistical confidence intervals.

Raw per-worker outside CPU maxima were 4–11% of one logical CPU. Actual load
was modest despite permission to run with background activity. Every worker's
nonzero outside CPU and the optimized/debug instrumentation difference remain
confounders; original public controlled deltas remain withheld. There is no
contemporaneous A/A condition, known 10% effect, powered sample requirement,
error-rate calibration or held-out confirmation. Prior studies remain design
context only. Policy remains disabled, qualification not_assessed, calibration
pending. This result motivates a prepared [interleaved noise/control screen](milestone-c-control-separation.md),
which remains unapproved and unexecuted.

The authoritative detailed analysis and reproducible script belong to research
commit `fa25c7d8aad72e4b9c635d26694d46a8245cc715`, paths
`bgp/2026/docs/bgperf2-diagnostic04-analysis.md` and
`bgp/2026/scripts/analyze_observer_pairs.py`. Research's 32 Docker-free checks
passed, including ten arithmetic/bad-evidence tests; independent verification
checked 112 numerical fields and 130 directly consumed sealed-source records.
Maximum numerical discrepancy was 1.64e-14. These records are evidence history,
not an external prerequisite for using the engine.

Original results are under
`/home/jpietsch/bgperf-results/2026/quiet-debug-eligibility/20261030T163822Z-3f08e524c1`.
Native independent source/copy/archive verification accepted 5,308 source entries,
5,278 archive members, 4,506 regular payloads, 214 coordinator copies and 32
socket type-only records. Archive 1,456,206,107 bytes, SHA-256
`95781d2695f5afffba10d8910ca8d772521cda2ab11d6658e13a6130f3979ebd`;
coverage `bbf0d9869b9fb894d953e5b84e9cb63a756cc00072c2c8255843789d12f63666`;
manifest `ae84c7795e00bb2768c6e01e266c96c3b88a9466b505f305aa0afc39ac571180`.
The independent final receipt hash is
`34307463f87441a896ccf2e5c04edb30ad77be9d5a28fb0d535bb57020b2a1bf`.
Analysis is preserved separately from sealed originals. Same-device local
preservation is not independent backup. No original removal, remote transfer,
push, publication or provisioning is authorized by this closeout.
