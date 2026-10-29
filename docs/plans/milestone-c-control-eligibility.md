# Milestone C debug-control eligibility case

Prepared 2026-10-29 from engine `3594dfe`, branch `milestone-a-newcomer`.
**Preparation only; execution approval pending.** Performance policy remains
`disabled`, qualification `not_assessed`, and calibration pending. This document
owns this fresh case; the [repeatability record](milestone-c-repeatability-validation.md#queued-repeatability-study-and-analysis-completed--2026-10-29)
owns the completed 16-pair study and its preserved analysis. No old job restarts.

## Question and limits

Can a same-source unoptimized target produce an observable change inside the
existing 10%-to-90% observer delivery window, making it worth further
positive-control qualification? Choose the supported `debug`, `-O0 -g` build
instead of introducing an unreviewed source-delay hook. The retained optimized
target uses `-O2 -g`. This changes real target execution, but its effect on this
window is **unknown**: generators or observer may limit delivery, and a build
change may affect startup without affecting this window. Neither emitted flags
nor a larger mean establishes a known 10% effect.

The preserved study's sample paired-log SD is 0.0859475, with individual changes
−11.39% to +20.94%, opposite block means and unbalanced order allocation.
Its 13 sealed analysis files are checked before preparation; the original
archive, reports, work and analysis remain unchanged. These are design data,
never new observations or held-out confirmation. The illustrative normal
sample-count calculations do not justify this case's budget.

This is an **eligibility/discovery screen**, not completed control qualification
or a powered regression test. One A/A block followed by one A/debug block
confounds condition with chronological block. It supplies no cross-block
replication within a condition. Fresh repeated control qualification, a frozen
statistical design and separate held-out same-image/control confirmation remain
necessary. The earlier draft 32-pair-per-condition ceiling is not selected here.

## Frozen inputs and bounds

| Item | Selected choice |
| --- | --- |
| Engine | Clean explicit `/tmp/bgperf2-milestone-a`, `milestone-a-newcomer`; freeze final documentation revision in generated packet |
| Recipe | Existing `comparison-repeatability-control.yaml`, cell `8d043e8dc2f9f660`; two peers × 1,000,000 synthetic IPv4 prefixes, BIRD/BIRD/sink, unchanged workload and role pins |
| Baseline | Actual optimized image `sha256:8cc3a97c01b7dd3aa188fb040067aeb70244fd4382183fb5763cb09d5db12f88`; preserve original source/build provenance |
| Candidate source | Clean trusted packaging commit `ff132d4180f8f56882f0e977cd979992e9eb3b64`, snapshot `526022eb0dea09be71b98c60f0582e0ba30a06388baf3692e132b2cd5176d249`; no source patch |
| Candidate build | One public `bird-local/v1` invocation, `instrumentation=debug`, compiler/linker `-O0 -g`, no extra configure flags, timeout 1,200 seconds |
| Builder/runtime/generators | Existing `sha256:db0a8e144635b1d4b9f81f24ee78f11383c5b0cbd79f10353edcb8452e9af423` |
| Observer | Existing `sha256:311317014fc98e2cadf46941b4b23dab9dd724281dd50167a0f9187d8ac08f19` |
| Measurements | Diagnostics `none`, observer supplements, exactly the four worker-budget session/injection/count/completion assertions; exact 2,000,000 observer count |
| Block 1 | Eight fresh optimized/optimized natural pairs, alternating AB, BA, AB, BA, AB, BA, AB, BA |
| Block 2 | Eight fresh optimized/debug natural pairs, same balanced order; shared byte-identical baseline declaration and accepted block-1 final review required |
| Worker budget | At most 32 unique serial original attempts, 120 seconds each; 3,840 worker seconds |
| Combined budget | At most one build plus 32 workers, 5,040 budget seconds; admission, reviews, collection/cleanup and preservation are additional |

A means baseline, B means the selected candidate label. Block 1's candidate is
the same optimized image with a separate label. Block 2's real image ID remains
pending until the authorized build returns. No hypothetical candidate image is
an executable target. No warm-ups, replacement pairs, retries, extensions,
adaptive flags or workload changes are included. A build failure stops the case;
unreconciled daemon-side build activity blocks measurements even after a client
timeout. Cache reuse, actual compiler/linker commands and unknown binary hash /
reconstructibility must be recorded truthfully.

## Execution procedure requiring approval

The selected host is otherwise-idle `jpietsch-server`; `9950` remains excluded.
Request a new intentional root-backed persistent-storage exception limited to
this exploratory case. Proposed new roots, not created during preparation:

- Work/build: `/home/jpietsch/bgperf-work/2026-10-c-control-eligibility-01`.
- Results: `/home/jpietsch/bgperf-results/2026/2026-10-c-control-eligibility-01`.
- Preparation: `/tmp/bgperf2-c-control-eligibility-20261029`.

Use all [repeatability admission, placement, pressure and failure gates](milestone-c-repeatability-validation.md#host-and-storage-admission),
including native active-measurement/lock and all-UID checks; six fresh five-second
CPU intervals each ≤1 logical CPU busy in aggregate; no competing heavy work;
≥48 GiB MemAvailable and ≥64 GiB free disk before build and every worker.
Verify actual persistent mounts for packet, work, results and Docker; no tmpfs
or automatic missing-mount fallback. The deliberate `/dev/sda5` root exception
requires fresh approval and does not qualify the host for performance acceptance.
Revalidate topology, governors, kernel, Docker identity and every exact image.
Retain effective target/observer/tester placement evidence for every worker.
CPU layout remains `target=0,16,monitor=1-2,17-18,testers=3-14,19-30`.

1. Verify the clean engine revision, locked environment and preparation hashes.
   Independently accept the packet, exact destinations and source/build trust.
   After fresh native build admission, execute the packet's single public
   `target-build` command with network none, no pulls or installation.
2. Independently review actual build artifacts, observed flags, snapshot, image
   and owned cleanup. Run the offline candidate binder against the actual build.
   It must reject mismatched plans/provenance/artifacts and the baseline image
   masquerading as a new candidate. Freeze the resulting two public plans and
   exact command arrays; accept the binding before worker admission. This
   anticipated binding phase supplies the actual image, not another build or
   authority to change the selected design.
3. Execute explicit public `comparison-start`/`comparison-step` commands, one
   worker at a time, with `--observer-window` and fixed pressure policy. No
   unbounded `compare` loop, timer or queue enrollment. Use the unchanged
   validated admission/launch/verification helpers for the zero-build worker
   phase after independently accepting fresh case data. Their historical
   receipts are not new case acceptance. Freeze a worker-start deadline no
   later than four hours after approved execution begins; expiry leaves all
   remaining workers never run. Candidate image availability requires its own
   fresh exact-ID check in addition to the unchanged helper's baseline checks.
4. Independently assess every package, assertion, placement, resolution, raw
   foreign CPU and cleanup before successors. Take public first/final reviews
   in both blocks; block 2 starts only with accepted block-1 final receipt.
   Missing review waits; no extra worker is issued while waiting. Keep prior
   original attempt identities across all historical cases to reject reuse.
5. Any postlaunch assertion, verification, timeout, placement, resolution,
   pressure, memory, cleanup or raw foreign CPU >100% failure permanently stops
   successors. The unchanged live pressure screen uses one-second samples,
   gap ≤2.5 seconds, busy ≥75% AND PSI some avg10 ≥20% for two consecutive
   intervals, or memory <16 GiB. Missing monitoring coverage stops too.
   Nonzero foreign CPU can still withhold ordinary deltas below this cap.
   No unrelated work is interrupted. Preserve uncertain launches and reconcile
   them before any successor; a reservation is not proof a worker ran.
6. Preserve every original work/package, build, source/plan, command, review,
   pressure record, failed/interrupted and never-run entry. Independently
   verify package/report reconstruction, owned cleanup, native Docker inventory
   differences, full file/type/checksum coverage and local archive readback.
   Retain original roots. Same-device preservation is not independent backup.

No downloads, remote transfers, pushes, publication, provisioning, unrelated
cleanup or schedule change is included. Do not develop, build or analyze on an
active measurement host; the synchronous prescribed assessment gates belong to
this runtime workflow. Correctable proven prelaunch preparation errors follow
the existing [recovery contract](milestone-c-repeatability-validation.md#offline-controller-validation-and-preparation-recovery--2026-10-28).

## Prespecified descriptive assessment

For every natural pair retain `d = log(W_B/W_A)` from original integer-nanosecond
10%-to-90% crossing spans; report `100*(exp(mean(d))-1)` separately by condition
and AB/BA order, all individual ratios, chronological windows, log SD and range.
Retain crossing-ratio bounds `[L_B/U_A, U_B/L_A]`; these are timestamp bounds,
not confidence intervals. Also retain second/first ratios and all ordinary
report confounders. Do not pool conditions, fit/subtract an order correction,
trim outliers, impute missing pairs or run a significance/power calculation.
Incomplete execution gets descriptive accounting without a complete-case claim.

Report eligibility as **unresolved** pending further qualification. A consistent
larger A/debug window may motivate a separately reviewed replicated design;
absent, conflicting, order-dependent or confounded changes may rule out this
candidate. A sample mean above 10% alone never qualifies it. Compiler/debug
differences deliberately retain the instrumentation confounder and withheld
controlled deltas, even if foreign CPU is zero. No p-value, confidence interval,
achieved power, false-positive rate, known 10% slowdown, calibrated verdict or
performance-policy activation follows. Selecting estimator/error goals and a
justified held-out sample budget remains a later concrete decision.

## Preparation record

The packet's offline exporter verifies the preserved 13-file analysis seal and
baseline build references against the original sealed coverage. It exports the
unchanged recipe with explicit engine binding, four assertions, same-source
debug build plan and balanced A/A plan. The offline binder supplies the balanced
A/debug plan only from a verified actual build. Helper simulations and negative
binding checks must pass before the execution handoff; simulated outputs remain
visibly separate from real inputs. Source/build/worker activity remains zero
during preparation. No prior measurement or archive is rewritten.

Independent design/source review accepted the bounded eligibility scope. The
candidate binder passed 17 offline checks, including source/plan/flags/image/
artifact and destination mismatch refusals and a labeled simulated successful
public-plan rehearsal. A fresh copy of the unchanged historical controller and
public-workflow tests passed 49 checks in 59.58 seconds; historical and copied
source hashes matched before/after. These exercise separate simulated boundaries,
not an end-to-end live case. Final worker-phase case data and its independent
acceptance remain conditional on the actual build. The generated preparation
packet records its final documentation commit; the initial draft retains
`3594dfe`. A clean-tree refusal during regeneration was a proven prelaunch
preparation error, with no build or worker started.
