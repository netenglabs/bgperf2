# Milestone D bounded live-bisection validation

Prepared and validated 2026-10-26. **The deliberately injected local count-fault
case confirmed its boundary with three public builds and five workers.** Earlier
admission-only stops remain recorded below. Execution is finished; its budget
and authorization are consumed. Any new execution requires fresh authorization.
Prior A/B and
discovery-run authorizations are consumed. This procedure authorizes nothing by
itself. Milestone C calibration remains pending; performance policy stays
`disabled`, performance qualification `not_assessed`, and performance predicates
remain unsupported. See the [development plan](performance-testing-development-plan.md),
[bisection contract](../bisection.md) and
[completed packaging-source validation](milestone-b-runtime-validation.md#approved-packaging-source-validation-completed--2026-10-26).

## Selected case and trust boundary

Validate the public live source-build/search/cache/confirmation/report path with
an explicitly introduced local **one-route export fault** in packaging-patched
BIRD 2.19.2. This is a functional validation with a known boundary, not discovery
of an upstream regression, a source fix, route-identity conformance, hardware
qualification or a performance comparison. No daemon crash or signal is injected.

The new owner-only preparation/evidence root is
`/tmp/bgperf2-milestone-d-bounded-20261026`. It is distinct from every previous
attempt, including the earlier `milestone-d-live` source extraction. Its `history`
repository was cloned locally without hardlinks from the preserved B source.
The original release checkout, B packaging checkout and all prior evidence
remain unchanged. No download or source code execution was used in preparation.

Three clean, separate `source-0`, `source-1`, `source-2` checkouts freeze this
complete consecutive first-parent chain:

| Index | Full revision | Change / expected assertion classification |
| --- | --- | --- |
| 0 | `ff132d4180f8f56882f0e977cd979992e9eb3b64` | Previously validated packaging patch: materialize two BSD aliases; good |
| 1 | `f6f9adbdf0603b416413126b9c7f5b85c5600bbc` | Add one inert comment before `bgp_preexport`; good |
| 2 | `4bddf6abe71be7459e84b19f1a9cca9751b398db` | Reject exactly `100.0.0.0/32` in `bgp_preexport`; bad |

The injected check first tests `NET_IP4`, then prefix length 32 and
`ip4_to_u32(net4_prefix(...)) == 0x64000000`, returning the existing export-reject
value `-1`. Independent static review accepted the API usage, short-circuit type
guard, patch and predicate compatibility before fixture commits. All other
behavior and inherited source attribution/license notices are retained.
`history.patch`, `proposed-regression.patch` and local Git history retain the
actual changes. These commits are validation fixtures, not engine changes or
upstream BIRD commits. Strict symlink/source guards remain enabled.

Use public `synthetic-ipv4/f94a3878b2dad49e`: one generator peer, 100 prefixes
beginning at `100.0.0.0/32`, no filters/receivers/churn or extra workload.
The existing monitor checkpoint is 99. Both good revisions should complete
with exactly 100 routes and all four bounded assertions passing. The injected
bad revision should complete with 99 routes: its exact observer-count assertion
fails decisively while sessions, injection and experiment completion pass.
This deliberately exercises the distinction between legacy convergence and
the exact-count assertion without altering either engine definition.
Static expectation is not a measured result. A timeout, missing witness,
different count, setup failure or crash does not establish this expected fault.

Freeze `bird-local/v1`, debug instrumentation, `-O0 -g` for compile/link,
no extra configure flags, network none, pulls false, local legacy builder only.
Use the following existing immutable local IDs, rechecked before execution:

| Role | ID |
| --- | --- |
| Toolchain, runtime base and fixed supplied generator | `sha256:db0a8e144635b1d4b9f81f24ee78f11383c5b0cbd79f10353edcb8452e9af423` |
| Fixed sink observer | `sha256:311317014fc98e2cadf46941b4b23dab9dd724281dd50167a0f9187d8ac08f19` |

Each candidate target must be built through its own frozen build plan. Do not
import the old B image/build/result or fabricate a target identity. Fresh boundary
workers reuse only the matching session build cache, never measurements.
Binary hashes/reconstructibility retain the builder's documented unknown/false
limits. Source/configure/make are trusted executable inputs; approval must cover
these exact local revisions and the deliberate routing fault.

## Offline preparation and proposed commands

The local `prepare_inputs.py` records public export, three `target-source-plan`
calls, `plan`, `init`, nonexecuting `next`/`step`/`run`, and report/verify commands
in `offline-commands.json`. Run only once with a clean engine on
`/tmp/bgperf2-milestone-a`, branch `milestone-a-newcomer`, at the commit containing
this proposal. `binding.json` records the exact engine pin and SHA-256 of each
frozen input; source plans record exact normalized snapshots. The recipe question
explicitly identifies this deliberate local fault. Preparation starts zero
source builds/workers and requires no Docker operation in the public planners.
The normal host guard and locked-environment check are separate read-only checks.

The frozen plan uses predicate `assertions`, **max trials 5**, worker timeout
**120 seconds**, build-client timeout **1,200 seconds**, and basic diagnostics.
The initialized `session` must have zero journal trials, no pending reservation,
and no cache/work/results before approval. Its portable `pre-execution-report`
verifies an unmeasured state, not a successful boundary.

After fresh authorization, use the pinned engine and existing locked environment:

```sh
/tmp/bgperf2-milestone-a/venv/bin/python \
  /tmp/bgperf2-milestone-a/recipe_bisection.py next \
  /tmp/bgperf2-milestone-d-bounded-20261026/session
# Execute once, then perform the mandatory review below before another step:
/tmp/bgperf2-milestone-a/venv/bin/python \
  /tmp/bgperf2-milestone-a/recipe_bisection.py step \
  /tmp/bgperf2-milestone-d-bounded-20261026/session --execute
```

Do not use automatic `run --execute`: it can continue after skipped builds and
does not enforce these stricter operational review gates. A successful reviewed
step permits only the next listed step within the newly approved scope:

| Trial | Request | Expected index/classification | Build |
| --- | --- | --- | --- |
| 1 | endpoint-good | 0 / good | New |
| 2 | endpoint-bad | 2 / bad | New |
| 3 | search (midpoint) | 1 / good | New |
| 4 | confirm-good | 1 / good | Exact cache reuse, fresh worker |
| 5 | confirm-bad | 2 / bad | Exact cache reuse, fresh worker |

Maximum **three new builds and five workers**, strictly serial, no retries or
budget extension. Build-client budgets total at most 3,600 seconds and worker
budgets 600 seconds; their sum is 70 minutes, **not a total wall-clock deadline**.
Prerequisite, source snapshot, probes, diagnostics, cleanup, packaging and review
add overhead under their existing bounds. Final diagnostic collection has its
existing 20-second budget plus bounded client termination. A stopped build
client does not guarantee Docker daemon-side work has ended; inspect and stop
all further work if termination is uncertain. Do not assume a safe idle host.

## Admission, gates and stop rules

Select the development host only for this small functional check, explicitly
accepting persistent ext4 root-backed storage under the evidence root and light
ordinary background work. These are **requested exceptions**, not inherited
authorizations. Verify actual `findmnt -T`, free capacity and host facts first.
Require at least 20 GiB free disk and 16 GiB MemAvailable before every step;
these are protective floors, not demand estimates or enforced resource caps.
Keep the active-measurement guard enabled and require no other benchmark or
source build. Missing local prerequisites stop without acquisition or repair.

Before execution and each step, verify the clean engine branch/full pin, input
hashes, three clean source revisions/snapshots, exact fixed local image IDs and
expected `next` request. Take initial container identity/state, network, volume
and image inventories. Preserve unrelated resources. No development, tests or
analysis may run while builds/workers are active; only read-only operational
supervision and owned-resource cleanup are permitted then. Independent evidence
review happens only after the active work stops.

After each step, independently review before permitting the next:

- Verify the original result package, recipe/target/source/build bindings,
  recorded generator/observer identities and basic diagnostics. Inspect original
  build disclosure/logs/archive/snapshot and target identity for each new build.
- Check the expected four assertion outcomes and actual 100/99 count, completed
  runtime status and satisfied 120-second budget; do not accept just `good`/`bad`.
  Optional missing observations stay null with their recorded errors. No RSS,
  memory regression or performance result is required or inferred.
- Verify no pending reservation, unique attempt identity and exact journal
  classification/request. Confirmations must be fresh distinct workers with the
  expected exact cache identity and no additional build.
- Inspect collection/cleanup errors, owned processes/containers/networks and
  before/after unrelated identities/states/volumes. Existing unrelated resources
  must remain unchanged; only the selected new build images/cache may be added.
  Classification is not a substitute for cleanup acceptance.

Stop permanently on the first unexpected build, skipped/ambiguous result,
predicate discrepancy, failed verification, cleanup/collection error, resource
floor/guard failure, external stop, or uncertain build/worker state. Retain the
original reservation and evidence. Do not automatically recover, abandon,
resume, retry, repair, change source/recipe or add trials under this approval.
An inconclusive trial is a valid recorded limitation, never a guessed bad/good.

After all five accepted reviews, generate and verify the portable report with
public `report SESSION --output NEW_REPORT_DIR` and `verify REPORT/bisection.json`.
Expected state is `confirmed`, adjacent boundary index 1 → 2, both fresh
confirmations, performance `{policy: disabled, qualification: not_assessed}`.
Rebuild into a second new directory and verify the same conclusion offline.
Review the actual artifacts independently and record the engine pin/results
in this document before claiming live qualification.

## Preservation and exact decision

Preparation review accepted the source/predicate, consecutive clean snapshots,
offline helper and this bounded procedure. The focused Docker-free bisection,
walkthrough and documentation-index checks passed **120 tests** in 72.19 seconds.
The active-measurement guard passed and the existing locked environment matched
all 34 packages with `pip check` successful. Preparation-time mount inspection
observed ext4 `/dev/sda5[/tmp]`, with 230,625,681,408 bytes available; this is a
read-only observation, not runtime admission or a storage exception approval.
Final input/engine hashes and offline verification are retained in the local
binding/command records described above. None of these checks qualifies live D.

Retain all prior evidence unchanged. Retain this root's complete local source
Git history/three snapshots, reviewed patches, recipe/build/search plans and
hashes, commands/stdout/stderr, inventories, journal/reservations, cache/build
archives/logs/disclosures/images, original worker work/packages, diagnostics,
reports and independent review receipts. Create complete path/type/hash coverage
after work stops; inventory sockets without opening them. Verify package/work
coverage and CSV readability. This is local retention, not an off-device backup;
no expiry, deletion or remote transfer is authorized.

**Recommended decision:** authorize exactly this deliberately injected local
count-fault case, its three builds/five workers, per-step independent reviews,
specified storage/background-work exceptions and unchanged instruments/budgets.
Alternatively defer live D or select a different trusted real-source case; a
different case requires fresh preparation/review, not reuse of this authorization.
Downloads, dependency/image acquisition, extra builds/workers, forced crashes,
timeout/interruption experiments, privileged capture, new schedules, `9950`
access, provisioning, pushing/publication, remote evidence transfer and
performance-policy activation are outside the proposed scope.

## Approved execution stopped at admission — 2026-10-26

The operator approved the concrete procedure with **“go ahead”**. Admission used
clean engine `6d66b2f60a2a45cb74e0408fef248306309d9d8c` on
`milestone-a-newcomer`; the frozen recipe, three recomputed source plans,
session plan bytes, expected first request and selected local image IDs matched.
The approval is retained separately in `execution-authorization.json`; original
preparation bindings and inventory remain unchanged.

The first sandboxed inventory could not reach the Docker socket. Its original
`before-1-inventory.json` and stderr retain that access refusal, which supplies
no host-load conclusion. The required read-only guard was then run with approved
host execution and passed. The separate `before-1-host-inventory.json` records
71 existing containers, only unrelated `second-looks-box` running, the selected
ext4 `/dev/sda5` mount, 57,352,159,232 bytes MemAvailable and 230,468,829,184 free
disk bytes. The protective memory/disk floors passed. No image was acquired,
built, retagged or removed.

Manual process admission found an unrelated classifier invoked with
`fit_classifier.py --v2 --workers 30` (parent PID 2047001). A read-only delta of
its process tree's `/proc` CPU ticks over 1.001777569 seconds measured
**2,997.671% of one core**, about 30 cores, across 33 processes. This is active
CPU use, not a lifetime `ps %CPU` average. `background-admission.json` retains
the command, per-process deltas, interval and load average. This exceeds the
approved **light ordinary background work** exception. The procedure stopped
permanently before the first public `step --execute`; the unrelated job was
not interrupted or changed. No broader concurrency exception was inferred.

Accounting is **zero source builds, zero workers, zero trials**. The session has
no pending reservation; its initialized artifact directories remain empty.
The first good endpoint, injected fault, cache reuse, fresh confirmations and
live boundary remain unmeasured. No timeout, build or daemon failure occurred.
This admission stop is not a bisection result and does not qualify live D.
Performance policy remains `disabled`, qualification `not_assessed`, and C
calibration pending. All prior evidence, the preparation root and new admission
records remain local; no deletion or remote transfer occurred. Another attempt
must recheck actual host suitability and receive fresh execution approval under
the recorded stop rule; it must not silently retry this stopped request.

## Approved waited execution completed — 2026-10-26

After a second **“go ahead”**, a new admission sample still found heavy work
(about 28 cores). That separate admission-only record remains at
`/tmp/bgperf2-milestone-d-attempt2-20261026`; no build or worker ran in it.
The operator then explicitly selected **“Wait for heavy jobs to finish”**.
This authorized waiting and continuation of the same bounded case after fresh
admission, without widening the concurrency exception or repeating a worker.
Only foreground read-only monitoring was used; no service or schedule was added.

The actual execution has its own owner-only root:
`/tmp/bgperf2-milestone-d-waited-20261026`. It uses clean engine
`43965e6dcab6b25b74754d728554e7433e6bbe75` on `milestone-a-newcomer`, fresh
recipe/build/search inputs and three new clean source checkouts at the same
reviewed revisions above. Independent preparation review recomputed all three
snapshots and verified the frozen hashes, controls and empty initialized session.
Both earlier roots, their original bindings and refusal records remain intact.

### Actual boundary and accounting

Exactly three public source-build invocations and five serial workers ran.
No worker was retried, abandoned, recovered or extended. Each source archive's
481 regular files matched its selected checkout. The good endpoint's new public
build used Docker's existing cached compilation layer and returned the prior
packaging-source image with a new tag; it did not establish fresh compilation.
The bad endpoint and midpoint logs show actual configure/compilation with the
requested debug compile/link flags, and produced two new image IDs. All builds
retained local legacy-builder/network-none/pull-false controls and their
1,200-second client budgets. No old target declaration or measurement was imported.

| Trial | Phase / source index | Original attempt UUID suffix | Count / classification | Worker seconds |
| --- | --- | --- | --- | --- |
| 1 | endpoint-good / 0 | `e75b27c9f98f4938bfe5a188a3a8f947` | 100 / good | 12.196126110 |
| 2 | endpoint-bad / 2 | `dbef8029aac9466e9b6cf85b429ed7ff` | 99 / bad | 11.632815886 |
| 3 | search / 1 | `86dd3097fa0e4089b91147b114804548` | 100 / good | 11.034060907 |
| 4 | confirm-good / 1 | `ab763b7e7a96426caeaaa17068a1deb8` | 100 / good | 11.031672814 |
| 5 | confirm-bad / 2 | `466f22e6b03042e998157566bd25c89a` | 99 / bad | 11.083180260 |

Original attempt names prefix those UUIDs with `bgperf_recipe_`. All five
experiments completed within their 120-second worker budgets. Good trials passed
all four assertions; bad trials failed only exact observer count, while session,
injection and experiment completion passed. Each worker had a distinct identity.
Independent evidence/cleanup review accepted each gate before the next worker.
Both confirmations reused only the exact matching build cache: all 36 cache-file
hashes stayed unchanged, with exactly three cache entries and no further build.

The confirmed adjacent boundary is
`f6f9adbdf0603b416413126b9c7f5b85c5600bbc` →
`4bddf6abe71be7459e84b19f1a9cca9751b398db`.
Public `report`/`verify` and an independent rebuild into `report-final` and
`report-rebuilt` verified **219 files each**, produced identical JSON conclusions,
and reconstructed the boundary and both fresh confirmations. Independent final
report review accepted the results. No pending reservation or unresolved trial
remains. This validates live deterministic assertion bisection for this expressly
introduced local fault; it does not discover an upstream BIRD regression.

### Host contention and diagnostic limits

Fresh admission checked the active-measurement guard, source/engine/plan/image
identities, mount and protective memory/disk floors before each step. Later
heavy work caused further waiting before the midpoint; no extra trial ran then.
The early waiting monitor sampled only user-owned processes and missed root-owned
CPU work. The first worker's retained preflight warning observed about 10.4
foreign cores, and its measured interval recorded about 8.1. **The first trial
does not establish an idle or lightly loaded execution**, despite its satisfied
functional assertions and deadline. Independent review accepted its functional
witness with this explicit confounder, not a performance qualification.

The local admission monitor was corrected to inspect all readable UIDs and
cross-check aggregate `/proc/stat` busy CPU ticks, retaining raw counters.
Independent review accepted it. A linked `--admit && step --execute` check
subsequently reduced the check-to-launch gap without adding automatic retries.
Such a check cannot prevent another workload starting afterward. Legacy CSV
maximum foreign CPU values remain **811%, 142%, 38%, 42%, 163% of one core** for
trials 1–5 respectively; those columns are rounded observations, not zeros or
evidence of continuous idleness. Timing/performance attribution is withheld.

Generator BIRD 2.19.2, sink 0.1.0 and target BIRD 2.19.2 identities remained fixed
apart from the selected source-built target image. Basic diagnostics were
collected, with empty top-level collection and cleanup errors in all attempts.
Each worker retained one optional generator live-memory read timeout and null
memory observation. No per-daemon RSS, continuous health, diagnostic overhead,
memory regression or crash-path qualification is inferred. Binary hashes remain
unverified and reconstructibility false under the existing source-build contract.

### Cleanup, preservation and remaining decisions

Initial, between-step and final inventories agree on all **71 pre-existing
containers, six networks and 495 volumes** and their recorded states/identities.
Only the selected build images/tags/cache were added; no original image was
removed. Both confirmation inventories, including images, were identical.
All owned runtime work stopped before reports, preservation or normal commit
checks. No unrelated job was interrupted or modified.

All ten original/session-copied packages independently verified 41 artifacts
each. Preservation audit matched **all 190 original-work regular files** to
their packaged hashes and parsed **75 CSV files** across original work and
retained package/report copies. Full source Git history, snapshots, archives,
patches, build disclosure/logs, input hashes, commands/stdout/stderr, refusal and
waiting records, original work/packages, journals, diagnostics, inventories,
reports and independent review receipts remain local. Socket entries are
inventoried without opening them. Complete local path/type/hash inventories
cover the retained roots; this is not an independent/off-device backup. No
original work or image was deleted and no expiry or remote transfer was added.

The owner-only local copy is
`/home/jpietsch/bgperf-results/2026/2026-10-milestone-d-live-validation/evidence.tar.zst`
(102,712,615 bytes), SHA-256
`6e74692caa2a2f1d4cbd1245a7e8d2dae127a724e96f55ba12f5b780102116c4`.
Streamed readback verified 5,953 members: 4,919 regular files (including three
preservation metadata files) and 1,034 directories, with all 75 CSVs readable.
Five socket entries were explicitly omitted without opening them. All 5,955
source path/type/hash/metadata entries matched before and after archiving.
The nine-file preservation bundle was copied locally with per-file hash checks,
directory mode 0700 and file modes 0600. Source roots and the verified temporary
bundle remain in place. Both destinations are on the same `/dev/sda5` ext4
device: **local preservation, not an independent or off-device backup**.

Milestone D's bounded live count-assertion search is accepted with these limits.
Live crash bisection, interrupted-search recovery, skipped/ambiguous source
histories, pristine-source support and broader adapters remain outside this
live check; their controlled tests do not turn into live qualifications.
**Milestone C calibration remains pending, policy `disabled`, qualification
`not_assessed`; performance predicates remain unsupported.** No further runtime,
download, provisioning, publication or push is authorized by this completion.
