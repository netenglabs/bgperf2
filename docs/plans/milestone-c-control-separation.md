# Milestone C interleaved noise/control separation — preparation only

Prepared 2026-10-30 after the [completed background-load diagnostic](milestone-c-control-eligibility-queued.md#diagnostic04-completed-and-analyzed--2026-10-30).
Status: **reviewable design; no execution authorized**. Source/helper/packet
validation is recorded below as preparation completes. This is a proposed
bounded case, not an installed job, runtime result or calibrated policy.

## Question and evidence for the next step

The completed diagnostic had longer debug-image observer windows in all eight
fresh pairs: geometric change +72.23%, range +60.54% to +83.06%, similar block
means and balanced AB/BA order. It had no contemporaneous same-image condition.
Earlier A/A studies are design context, not observations to pool or subtract.

Can the selected workload show a large optimized/debug contrast that separates
from nearby same-image fluctuations under the same recorded operating profile?
Interleave A/A and optimized/debug sessions, with both pair orders represented
inside every chronological macroblock. This addresses local chronology and
supplies a contemporary reference; it does not establish a known 10% effect,
statistical detection performance or an isolated causal target-cost estimate.

The operator's explicit diagnostic preference persists: record background CPU
as a confounder without CPU-only admission or successor refusal. Actual capacity,
correctness, provenance, placement, pressure-monitoring and cleanup safeguards
remain. The proposed case makes no quiet-host claim. Performance policy remains
`disabled`, qualification `not_assessed`, and calibration pending.

## Frozen design proposed for approval

Select **zero builds and at most 32 unique serial workers**, 120 seconds each:
eight A/A pairs and eight optimized/debug pairs. Eight public sessions each
contain two pairs in AB,BA order. A is the byte-identical optimized baseline;
B is the optimized control under a different label in AA, or the existing
debug image in AD. Four macroblocks each contain one AA and one AD session.

| Macroblock | First session | Second session | Pair order in each session |
| --- | --- | --- | --- |
| 1 | block-1: AA | block-2: AD | AB,BA |
| 2 | block-3: AD | block-4: AA | AB,BA |
| 3 | block-5: AA | block-6: AD | AB,BA |
| 4 | block-7: AD | block-8: AA | AB,BA |

Every session after the first requires the immediately preceding accepted final
public review. Baseline and recipe declarations remain byte-identical across
all sessions. Each condition has four AB and four BA pairs. Each macroblock
has two pairs per condition; that is a small local reference, not a distribution
estimate. The four macroblocks are chronological subdivisions, not assumed
independent days, hardware replications or independent statistical blocks.

The fixed budget is an engineering qualification screen, not a power result.
Maximum worker budget is 3,840 seconds (64 minutes); native sampling, collection,
cleanup, sixteen independent first/final reviews and preservation are additional.
No elapsed-time worker-start cutoff is selected. No warmups, replacements,
extra worker, adaptive extension, favorable-timing stop or post-start retry.

## Unchanged inputs and safeguards

- Explicit clean `/tmp/bgperf2-milestone-a`, branch `milestone-a-newcomer`;
  final preparation binds its exact documentation revision. No engine behavior
  or source change is selected by this case.
- Existing `comparison-repeatability-control.yaml`, cell `8d043e8dc2f9f660`;
  two BIRD peers × 1,000,000 synthetic IPv4 prefixes to BIRD target/sink;
  unchanged role placement `target=0,16,monitor=1-2,17-18,testers=3-14,19-30`.
- Actual optimized image
  `sha256:8cc3a97c01b7dd3aa188fb040067aeb70244fd4382183fb5763cb09d5db12f88`;
  actual debug image
  `sha256:7fae42bfc8b00fc0aab6d1321cc7cb8a29f6a25e965949c6e012d0f1242dd3b8`.
  Same packaging-materialized source `ff132d4`, snapshot
  `526022eb0dea09be71b98c60f0582e0ba30a06388baf3692e132b2cd5176d249`.
  Preserve original `-O2 -g`/`-O0 -g` and cached-build/compiler evidence;
  unknown binary hashes and reconstructibility false remain unchanged.
- Existing generator/runtime
  `sha256:db0a8e144635b1d4b9f81f24ee78f11383c5b0cbd79f10353edcb8452e9af423`
  and observer
  `sha256:311317014fc98e2cadf46941b4b23dab9dd724281dd50167a0f9187d8ac08f19`.
  Four recorded-worker-budget assertions, exact 2,000,000 observer count,
  diagnostics `none`, observer supplements and unchanged pressure policy.
- Native `jpietsch-server`, excluding `9950`; guard against overlapping BGP
  measurements, verify topology/governors/kernel/host/immutable images/mounts,
  and capture baseline plus post-worker native inventories. At approval renew
  the intentional persistent `/dev/sda5` ext4 root-backed storage exception
  limited to this case; it is not hardware qualification or independent backup.
- Record native CPU intervals and all-UID activity. Require ≥48 GiB available
  memory and ≥64 GiB free disk before each worker, valid probes and fresh
  one-use receipts. Refresh an expired unconsumed receipt automatically for the
  same unstarted worker before reservation/Popen; never extend timestamps,
  consume another worker or hide an uncertain launch.
- Each returned worker needs synchronous original-package/assertion/count,
  budget, uniqueness, observer-resolution, requested/effective placement,
  pressure-coverage, provenance and cleanup verification. Background CPU is
  retained, with each raw finding finite/nonnegative, without a CPU-only stop.
  Missing/malformed monitoring, actual pressure/memory/capacity, correctness,
  timeout, placement, provenance, resolution or cleanup failure stops successors.
  Never signal unrelated work or automatically retry failed/uncertain work.

## Prespecified descriptive analysis

Retain all 32 positions and 16 pairs, plus failed/interrupted/never-run outcomes
if incomplete. Reconstruct integer-nanosecond 10%-to-90% observer spans and
crossing bounds. Per pair use `d=log(W_B/W_A)` and
`[lower_ratio,upper_ratio]=[L_B/U_A,U_B/L_A]`. Report individual values,
`100*(exp(mean(d))-1)`, sample log SD and ranges separately by AA/AD, AB/BA
and macroblock; retain chronological second/first descriptions and confounders.
Do not pool conditions, prior cases or failed/missing positions, fit/subtract
an order effect, trim observations or impute missing pairs.

For each macroblock, form the two-sided local A/A envelope
`E=max(1, upper_ratio_1, 1/lower_ratio_1, upper_ratio_2, 1/lower_ratio_2)`.
Compare each of its two AD lower ratios with E. Report whether all, some or
none of the eight AD brackets exceed their own local envelopes, together with
the actual values. This handles A/A fluctuations in either direction and is
only **observed sample separation**, not a statistical acceptance policy.
Complete the fixed design regardless of this descriptive outcome unless a
runtime safety/correctness/evidence rule stops the case.

Timestamp brackets are not confidence intervals. The tiny local A/A reference,
shared background load, temporal dependence, selected images and deliberate
instrumentation difference remain explicit limitations. No p-value, achieved
power, calibrated false-positive rate, required powered sample size, known 10%
positive control or 10%-detection claim follows. Known-effect control design,
inferential error goals, a justified held-out budget and fresh confirmation
remain later scientific decisions before calibration or policy activation.

## Concrete preparation and approval boundary

Proposed fresh work and results roots:
`/home/jpietsch/bgperf-work/2026-10-c-control-separation-01` and
`/home/jpietsch/bgperf-results/2026/2026-10-c-control-separation-01`.
No work/results directory is created during preparation. Lab's offline
`prepare_control_separation_case.py` exports the recipe/assertions/three
target declarations/eight public plans, exact command arrays and finite
controller copies. The packet carries diagnostic04 preservation anchors and
selected sealed source/build references. No old evidence is edited.

The copied controller adaptation selects eight sessions/four workers each and
32 total, preserving all other reviewed guard semantics. Source and negative
tests, a complete simulated 32-launch rehearsal and independent packet/design
review precede handoff. `execution_authorized=false` in the prepared case and
authorization, plus absent live baseline/reviews, prevent launch. No job is
enrolled and no timer is changed.

If the operator approves this concrete case, preserve the false-authorization
preparation, materialize a fresh runtime coordinator/authorization/invocation,
refresh cumulative prior original IDs if needed, and independently bind the
actual native baseline, case and helper hashes before launch. Accept public
first/final reviews for workers 1/4 of all eight sessions. A completed case
requires 32 distinct completed workers, sixteen public reviews, independent
final accounting/owned cleanup and full native source/copy/archive preservation.
Preserve every refusal/failure/interruption and unused position without
fabricating final reviews. Keep final receipts outside sealed roots, retain
originals and make no independent-backup claim. No deletion, remote transfer,
push, publication, provisioning or acquisition is included.

The operator decision is to approve or revise this exact bounded diagnostic
noise/control screen. Preparation does not grant that approval.

## Source validation record

Lab preparation source is committed at
`86e292f7ff3a2972f4fb6662fc328592e9eb95ef`; its full Docker-free gate passed
385 tests with two historical skips. Five focused checks cover the balanced
macroblock design, all 32 simulated launches across eight sessions, fifth-worker
and ninth-session refusal, and false-authorization refusal. These tests use
fake host/process boundaries and do not count as measured workers.

Independent source/design review accepted the copied helper adaptations,
explicit replacement-match checks, topology binding and unchanged guard
semantics. Frozen source/build references are selected from sealed coverage,
so an expected missing build record cannot be silently omitted. The final
13-command offline export and concrete data/helper/manifest review occur after
this engine documentation commit is clean; their exact prepared identities are
recorded in the separate preparation receipt. No live acceptance or execution
is implied by source/test success.
