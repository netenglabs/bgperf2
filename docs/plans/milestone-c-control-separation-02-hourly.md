# Milestone C hourly control-separation case 02 — completed

## Completed execution and analysis — 2026-10-31 UTC

Following operator approval and reviewed enrollment, actual case
`20261031T111001Z-db6a28e20c` completed all 32 unique workers and sixteen
pairs (eight AA, eight AD), with sixteen accepted public first/final reviews,
zero failed/interrupted/never-run/retried workers and zero builds. It ran from
11:10:31 to 12:48:30 UTC at runtime engine revision
`a9e1fb45fc13c4dc13fb2745656c0d80a1c2241a`. The queue job is terminal;
this record authorizes no successor execution.

The [research analysis](https://github.com/jopietsch/second-looks-lab-research/blob/research/bgperf2-c-diagnostic04/bgp/2026/docs/bgperf2-control-separation-02-analysis.md)
finds AD geometric observer-window change +78.40%, with all eight AD lower
timestamp-ratio bounds exceeding their contemporaneous local AA envelopes.
AA paired changes range from −14.96% to +10.23%. This demonstrates observed
separation for a large contrast, not reliable detection of a 10% regression.
Quiet-start scheduling completed operationally; background activity and build
instrumentation remain confounders. No causal quiet-host or error-rate claim.
Calibration remains pending and performance policy disabled. The next
preparation is a justified small-control calibration design with explicit
false-positive/missed-regression goals and a fixed confirmation budget.
Research source/report commit: `c4f49d0` (local; publication is separate).

Original sealed results remain under
`/home/jpietsch/bgperf-results/2026/quiet-control-separation/20261031T111001Z-db6a28e20c`.
Archive SHA-256:
`0755a0a42e498eba5677f7a1595a50c4ad6493c771a1713c63fc978c659d4ce3`.
Independent final preservation receipt SHA-256:
`9da1d0c43cd8ee4419298fdf93a177761a1529989b87ce4560ce91cb13360ba6`.
Source, runtime copies, archive and full accounting are retained locally;
same-device retention is not an independent backup.

## Original preparation (retained historical proposal)

2026-10-30 UTC. **Reviewable proposal; no new execution or enrollment authorized.**
The operator asked whether the existing hourly scheduled work can wait for a
quiet computer. The dispatcher is still installed at minute 10 each hour, with
no pending job. This prepares one fresh bounded job for that scheduler; it does
not resume [closed case01](milestone-c-control-separation.md#approved-execution-and-partial-outcome--2026-10-30-utc),
reuse its twenty unrun positions, or change cron. The false-authorization
preparation and all original case01 evidence remain unchanged.

## Concrete proposed execution

Use the same reviewed workload, images, role pins, assertions, observer
definitions, live pressure policy and interleaved design as case01: **zero
builds and at most 32 unique serial workers of 120 seconds**, eight AA and eight AD
pairs in eight sessions/four chronological macroblocks. Sessions are AA,AD,
AD,AA,AA,AD,AD,AA, with two AB,BA pairs per session. Every session requires
independent first/final public review after workers 1/4, sixteen reviews total;
every returned worker requires synchronous operational verification. Each
session after 1 requires the immediately preceding accepted final review.

Only the initial scheduling profile changes: the existing hourly dispatcher
requires six five-second CPU intervals, each at most one busy logical core,
available memory of at least 48 GiB, disk of at least 64 GiB and the native
measurement guard. If unsuitable,
the job stays pending until a later hourly tick, consuming no experiment. There
is no fixed four-window limit, expiry or elapsed-time worker-start cutoff.
No unrelated job is paused or killed. The scheduler serializes explicitly
enrolled BGP jobs, not unrelated work on this shared computer.

This is **quiet-start scheduling**, not a guaranteed quiet study or hardware
qualification. Once dispatched, background CPU remains recorded without a
CPU-only admission/successor refusal, as the operator previously selected.
Every worker still requires 48 GiB available memory and 64 GiB disk, valid native
identity/provenance/topology/image checks, exact requested/effective placement,
four assertions/exact2Mcount, observer resolution, pressure coverage and clean
owned cleanup. Existing live thresholds and all original confounders remain.
No calibrated performance policy, known 10% effect or statistical error claim.

Only independently verified zero-worker load/capacity deferrals can return to
the hourly queue. If capacity falls after any actual worker, or a correctness,
provenance, placement, resolution, monitoring, pressure or cleanup check fails,
the case permanently closes and the job blocks for operator review. There is
**no automatic post-start fresh case, retry, replacement or extra worker**.
An expired UNCONSUMED receipt before reservation/Popen is refreshed for the
same unstarted worker without consuming budget or closing for bookkeeping.
One-process native sampling/launch avoids tool-call delays aging receipts.

## Reviewable queue handoff

Proposed job ID `bgperf2-c-control-separation-02`, with fresh per-dispatch IDs:
work beneath `/home/jpietsch/bgperf-work/quiet-control-separation/` and results
beneath `/home/jpietsch/bgperf-results/2026/quiet-control-separation/`.
The engine checkout is explicitly `/tmp/bgperf2-milestone-a`; the clean final
documentation revision is frozen in the deployment. Existing optimized/debug,
generator and observer images are reused exactly. The intentional persistent
`/dev/sda5` ext4 root-backed storage exception is proposed for this bounded case
and its queue records only; approval must renew it. Local retention is not an
independent backup. `9950` remains excluded.

Lab's named `control-separation-02` adapter profile selects 32 workers,
eight sessions/four workers each/two repetitions; the old 16-worker default is
unchanged. Offline export retains an immutable false-authorization preparation
and an inspectable concrete example. At an approved dispatch, a separate actual
runtime materializes new data bindings and refreshed prior IDs, including all
twelve case01 originals. Immutable helpers are copied, never generated or
repaired during measurement. Independent review must bind the actual case,
native baseline, six helper hashes and the immediate-launch wrapper hash before
any worker. The supervisor inherits the shared queue flock through all reviews,
cleanup and full local source/copy/archive preservation. No analysis or source
commit runs during dispatch.

`prepare_control_separation_queue.py` freezes source/config/spec and 13 offline
public exports only after clean reviewed commits. By default **both job spec
and runtime config are false**, so they cannot enroll or launch. An approved
deployment must be fresh and carry explicit operator authorization; never mutate
the preserved false preparation. Independent concrete-deployment review precedes
enrollment with the existing dispatcher. Enrollment does not invoke an immediate
tick or replace the hourly timer. Source/deployment hashes and zero-worker
activation state are retained outside Git.

The case retains all 32 positions and 16 pairs, including stopped/failed/interrupted/
never-run outcomes. No case01 or historical control is pooled or imputed.
After measurement, the prespecified paired-log AA/AD/order/macroblock analysis
and exact local-envelope screen describe observed samples only. Incomplete
macroblocks remain unassessed, with no global success/failure claim. Case01's
one-of-two available separation result remains evidence to retain, not a reason
to alter the estimator, thresholds or fixed budget adaptively.

Approval would authorize exactly this one new job/case, its local storage
exception and existing hourly enrollment, with policy disabled. No new build,
image acquisition, remote transfer, deletion, push, publication or provisioning
is included. Source/test/deployment review alone authorizes no measurement.
