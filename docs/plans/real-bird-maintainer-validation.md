# Real BIRD maintainer validation: neutral release transition

Prepared 2026-11-01 UTC. The operator approved execution; the single admission
attempt **stopped before any build or worker** because other development tests
were running. This case is closed under its stop rules; see the execution record
below. This is the next concrete
case after checkout-preparation completion at `883f72e`, within the
[developer performance testing plan](performance-testing-development-plan.md).
It is a functional source/build/handoff check; performance policy stays disabled
and formal reliable-10% calibration remains deferred.

## Question and source selection

Do packaging-adapted BIRD pre-2.19.2 and 2.19.2 both establish one BGP session,
finish injection of 100 disjoint synthetic IPv4 prefixes, deliver exactly 100
prefixes to the sink and complete within a 120-second worker budget?

| Selection | Exact identity |
| --- | --- |
| Original local source | `/tmp/bgperf2-milestone-d-live-20261026/source` |
| Older upstream baseline | `62d6c38c2ddfbd74119641c7da251b6b7578c7e7` |
| Newer upstream candidate, v2.19.2 | `1d201ed0360c749dfe3d3b3b079329e7148159cd` |
| Engine checkout and branch | `/tmp/bgperf2-milestone-a`, `milestone-a-newcomer` |
| Preparation/evidence parent | `/tmp/bgperf2-real-bird-validation-20261101` |
| Final frozen case | `/tmp/bgperf2-real-bird-validation-20261101/case01` |

The upstream commits are adjacent on the first-parent chain. The older changes
a README link; the newer changes NEWS/VERSION for release. Their transition
contains no selected routing change. Both are expected to pass. Neither endpoint
is an observed good/bad witness, and no regression, upstream bug, fix, or
intentional routing fault is alleged. This deliberately modest question moves
the maintained preparation workflow onto actual daemon source without inventing
a bug for bisection. A real failure would be retained as a new observation,
requiring diagnosis before any further case.

Both trees contain `sysdep/bsd-netlink/netlink.c` and `netlink.Y` symlinks to their
Linux counterparts. The strict source builder continues to reject symlinks.
The maintained [packaging preparer](../../scripts/bird_alias_source.py) creates
an isolated derived two-commit history, materializing only these two aliases
with the exact target blobs and regular-file modes. Every other path, mode and
blob must equal its upstream tree. A retained independent upstream clone and
raw Git object verification support independent reconstruction. The mapping
records upstream and derived revisions separately; derived commits must never
be reported as pristine upstream commits. The original checkout and all prior
packaging/count-fault source histories and evidence remain unchanged.

## Existing materials and trust limits

Read-only inspection found no active BGP measurement and only the unrelated
`second-looks-box` container running. Local exact image identities are:

| Role | Local image ID |
| --- | --- |
| Toolchain, runtime base, fixed BIRD generator, recipe target declaration | `sha256:db0a8e144635b1d4b9f81f24ee78f11383c5b0cbd79f10353edcb8452e9af423` |
| Fixed sink observer | `sha256:311317014fc98e2cadf46941b4b23dab9dd724281dd50167a0f9187d8ac08f19` |

The [earlier source-build record](milestone-b-runtime-validation.md#approved-packaging-source-validation-completed--2026-10-26)
retains successful autoreconf/configure/make/install and two functional workers
using the same local BIRD image and an equivalent alias-only adaptation of
2.19.2 (`ff132d4180f8f56882f0e977cd979992e9eb3b64`). Its debug build and consumed
authorization are separate. Local inventory receipts, prior evidence paths and
hashes are under the new parent's `inventory/`; historical evidence is read-only.
Earlier count-fault bisection proves only its deliberately introduced fault.
Neither it nor the inert checkout examples count as a real upstream bug case.

Local image IDs identify retained content, not publisher trust. Historical
image acquisition metadata is not authenticated upstream provenance. No image
is treated as a hermetic toolchain, no binary reproducibility is asserted, and
no missing dependency may be fetched. Source configure/make code is trusted
only for these reviewed local trees and executes only after approval inside
the existing offline Docker build. Both builds request `-O2 -g` for compilation
and linking, `optimized` instrumentation and no extra configure options. Logs
must show what actually ran; Docker may reuse cache and that must be reported.

## Recreate and verify preparation

Use the existing locked Python 3.14 environment on a development host with no
active measurement. At the final clean committed engine revision:

```sh
/tmp/bgperf2-milestone-a/venv/bin/python /tmp/bgperf2-milestone-a/scripts/prepare_real_bird_case.py --source /tmp/bgperf2-milestone-d-live-20261026/source --output /tmp/bgperf2-real-bird-validation-20261101/case01
```

The output must be fresh. Preserve any partial failure and select a separately
named preparation rather than overwriting it. This command copies local Git
objects, packages aliases, exports the exact existing `synthetic-ipv4` cell
`f94a3878b2dad49e`, prepares both derived revisions and freezes the handoff.
It starts no Docker command, source build, daemon, worker or network operation.
The recipe records the actual final engine HEAD. Generated JSON stays outside
the engine. `verification.json` records the recipe digest and engine revision;
`packaging/packaging.json` records the derived source identities.

```sh
/tmp/bgperf2-milestone-a/venv/bin/python /tmp/bgperf2-milestone-a/scripts/bird_alias_source.py verify /tmp/bgperf2-real-bird-validation-20261101/case01/packaging
/tmp/bgperf2-milestone-a/venv/bin/python /tmp/bgperf2-milestone-a/recipe_source_range.py verify /tmp/bgperf2-real-bird-validation-20261101/case01/range/source-range.json
/tmp/bgperf2-milestone-a/venv/bin/python /tmp/bgperf2-milestone-a/recipe_handoff.py verify /tmp/bgperf2-real-bird-validation-20261101/case01/handoff/handoff.json
/tmp/bgperf2-milestone-a/venv/bin/python /tmp/bgperf2-milestone-a/scripts/prepare_real_bird_case.py --verify /tmp/bgperf2-real-bird-validation-20261101/case01
```

The last command reconstructs the selected scope and human runbook from the
verified handoff, checks the fixed upstream/derived mappings, image/build
controls, recipe/current engine revision and absent execution destinations.
It rejects changed selected commands or budgets even if their JSON is valid.
Use it before execution; after execution begins, its absent-destination gate
intentionally refuses the packet as no longer an unexecuted approval case.

Open `case01/CASE.md` for the complete selected argument arrays rendered as
shell commands, actual plan filenames, future target paths and evidence paths.
`execution-scope.json` narrows the general handoff: **no bisection or comparison
commands are selected**. The range API calls its endpoints good/bad and retains
a minimum four-trial plan; those are unobserved declarations required by that
preparation contract. Its monotone-transition assumption is not established by
this neutral case. Do not initialize or execute its search. The full generic
handoff ceiling is not the approval budget.

## One execution approval, with bounded internal reviews

Approval would cover exactly this case, at its frozen clean engine revision,
on the current development host, using only existing images:

1. Read-only source, recipe, environment, tool, image, host and destination
   rechecks; record host identity, mount/capacity and initial container/network/
   volume inventories. Stop if an active measurement or incompatible image,
   engine, source, Python environment or OS prerequisite is found. No repair,
   installation, acquisition, substitution or repeated admission loop.
2. Build the baseline once through `target-build` and verify its returned
   `builds/baseline/target.json` against the selected source plan. Inspect build
   logs and actual image IDs, not just CLI exit. Use the existing legacy local
   Docker builder with network none and pull false; no Buildx fallback.
3. Run one baseline reproduction with basic diagnostics, verify its original
   result package and evaluate the four named worker-budget assertions. An
   independent reviewer must accept source/build identity, completion/count,
   diagnostic limitations, worker budget and owned cleanup before continuation.
4. Build the candidate once; verify the corresponding source/build binding.
   Execute one fresh serial baseline/candidate investigation (two workers),
   verify and independently rebuild its report, then check the same four
   assertions on both original packages. All three attempt IDs must differ.
   The public investigation runs its two sides serially and stops successors
   on setup/harness/interruption/inconclusive outcomes. It has no external
   review gate between its two workers; review occurs after the pair.
5. Independently review all available packages, original/rebuilt report,
   build/cache accounting and final inventories. Write an append-only local
   execution receipt and complete local checksums/readback; retain every partial
   artifact. No remote preservation or publication is included.

The exact selected build/run/report commands are in the generated `CASE.md`.
Only after approval may the absent `builds`, `work` and `results` parent roots
be created. Use their declared locations; `unused-search` must stay absent.
The four assertions are session establishment, injection completion, exact
observer route count and experiment completion. Basic diagnostics remain
enabled for supported health/crash/cleanup evidence, but optional missing
memory reads are preserved as null and are not a new memory acceptance claim.

The proposed storage is intentionally root-backed ext4 `/tmp` on `/dev/sda5`,
not tmpfs or a qualified measurement volume. **The single approval must explicitly
include this functional-only root-volume exception.** The engine's existing
root-storage warning remains visible; no guard is bypassed. This exception
provides no performance qualification. Recheck at least 16 GiB available memory
and 20 GiB free disk immediately before each build/standalone worker/pair.
These conservative operational floors for a 100-prefix case are not measured
resource estimates or reservations. If a floor fails, stop the case; no queue,
wait-until-idle service or automatic retry is authorized. Other development must
not run here during the approved attempt. Record outside CPU observations and
all existing contention/withholding signals; derive no timing ranking.

## Budget and expected outcomes

Two builds × 1,200 seconds plus three workers × 120 seconds = **2,760 seconds
(46 minutes) of build/worker budgets**, serially. The fixed builder uses `make
-j2`; no additional compilation parallelism is selected. Prior same-image
packaging-source completion justifies trying one build per revision; a 20-minute
ceiling bounds unexpected configure/compile stalls. One tiny reproduction and
one separate pair provide fresh source identity and workflow witnesses; three
workers are an engineering coverage budget, not a statistical sample size.
The 120-second budget includes setup/session/observation and matches existing
functional practice. Final diagnostics, owned cleanup and prerequisite probes
are separately bounded by existing contracts and excluded from those 46 minutes.
Use a 90-minute operator elapsed-time ceiling for the entire case: reaching it
stops successors and triggers supported interruption/retention, never an extra
worker or cleanup deletion. Build daemon/cache work can outlive a canceled CLI;
inspect before declaring it stopped. There is no automatic 90-minute scheduler.

Expected: both source plans build; all three workers complete (exit 0,
`experiment_completed` reproduced), each observer count is exactly 100 and all
four assertions pass. The investigation may name completion as reproduced on
both sides; it must not be described as a resolved bug. Report verification
proves internal consistency and evidence bytes, not a general fix. No timing,
memory reduction, regression boundary or 10% detection result is expected.

Stop on any build failure, unexpected source/flags, failed assertion, unresolved
prerequisite, interrupted/inconclusive worker, controller stop, invalid package,
cleanup error or rejected review. A normal failed experiment that the generic
investigation permits must still end this case at review. Preserve all evidence
and never spend unused positions as retries. New diagnosis or retry needs a
separate selected case/decision.

## Recovery and preservation

Before recovery, inspect owned build/client/worker state and retain logs. Do not
rerun an uncertain command. Build failures keep source archive, patch,
Dockerfile, disclosure, log and outcome at the original `builds/SIDE` path; no
result image is retagged or removed. A build with no valid `target.json` does
not count as an available target. The 2-build ceiling counts attempted builds.

After interruption of reproduction, verify any original
`results/reproduction/result.json`; absent/invalid packaging stays unknown and
does not authorize another worker. After investigation interruption, use
`investigation-verify` on `results/investigation/report/investigation.json`, then
the selected `investigation-rebuild` into the fresh `results/investigation-rebuilt`
destination. This preserves controller stops, missing reasons and never-run
candidate status. If no valid report exists, retain partial roots and document
what is missing; do not fabricate a package or infer nonexecution from absence.
If rebuild already ran, verify its existing output; do not overwrite it.
No search is initialized, so no bisection recovery or extra trial is selected.

Owned cleanup uses existing attempt labels and inspected IDs. Compare inventories
to the initial snapshot and retain unrelated resources; do not perform broad
Docker cleanup or remove caches, work directories, original evidence or source.
Retain generated local receipts and full evidence at their original paths.
Transfer to independent storage, deletion, pushes and publication remain outside
this approval. `/tmp` retention is host-dependent; do not represent it as an
off-device backup or permanent archive.

## Preparation acceptance

Required before asking approval: original checkout/branch verified; local
materials and prior evidence inspected; alias-only source provenance verified;
actual source/build/range/handoff artifacts independently checked; destination
roots absent; exact selected commands and bounded budget reviewed; meaningful
negative/preservation tests and repository gates passed; local reviewed commits
complete. Runtime compatibility of both newly planned optimized builds, actual
worker results, current host admission and cleanup remain uncertain until the
single approved execution. Preparation itself authorizes none of them.

Preparation review accepted the code and concrete rehearsal with no outstanding
findings. It fixed duplicate raw-tree path acceptance, added independent selected
scope/runbook reconstruction and bound the actual runtime recipe/build plans to
the selected range. Fourteen packaging tests cover preservation, safe alias
mapping, object corruption, filters, hidden index views and malformed hash-valid
trees. Two orchestration tests exercise the real local Git/public preparation
contracts using inert source, forbidden runtime operations, changed approval
commands/prose and cross-handoff substitution refusal. All sixteen focused tests
passed; the broader focused/documentation check passed 94 tests. The existing
locked environment matches all 34 packages. These checks are Docker-free and
provide no new real build/worker qualification. Native commit gates and the
final frozen packet are recorded in the completion checkpoint below.

### Approved execution stopped at admission — 2026-11-01 UTC

The operator approved the frozen case at engine
`45c914a021807400d3ad3baa44895966a48e1a6b`, including the explicit root-backed
storage exception, source/image trust limits and admission/stop conditions.
The checkout was clean on `milestone-a-newcomer` before the single admission.

The engine's active-measurement guard passed and Docker listed only the
unrelated `second-looks-box` container. The same host process snapshot showed
multiple actual Python pytest processes in that container, including four-worker
NBA suites and a facts-regeneration test. The plan's requirement that other
development not run during the attempt was therefore unmet. No CPU threshold
was measured or inferred; the refusal is concurrent development, not a claimed
performance-capacity measurement. Available memory was 36,337,996 KiB and free
disk 152,249,479,168 bytes, both above their selected floors; ext4 `/dev/sda5`
was confirmed. These passing observations do not override the failed condition.

The case stopped before creating any build/work/results/search root. Accounting
is **zero attempted builds, zero workers, two builds and three workers never
run**, with zero failed worker experiments. Source/image/environment rechecks
and full Docker network/volume inventories were not completed after the host
refusal. No worker result, successful build, fix or performance finding exists.
Other workloads and containers were left untouched. There was no admission
retry, wait service, acquisition, deletion, evidence transfer, push or publication.

The append-only local admission record is
`/tmp/bgperf2-real-bird-validation-20261101/execution01/REPORT.md`, with
`admission.json`, independent `review.md` and local preservation readback.
The original frozen `case01` and prior evidence remain at their original paths;
its original pending-approval metadata remains historical preparation evidence.
This execution record governs the approved case's terminal refusal. Unused
build/worker positions do not authorize a retry. A subsequent execution needs
explicit new operator scope resolving host admission, with fresh paths/pins
where required. Performance policy stays disabled and calibration deferred.

### Local completion checkpoint

Implementation commit `12bf6a0` completed the source adaptation, selected-scope
verifier, negative tests and execution-case documentation. Independent review
accepted all changes and the retained real-BIRD rehearsal. The native pre-commit
gate passed **2,655 tests in 208.02 seconds**, including the sixteen new tests;
the locked 34-package environment and whitespace checks also passed. Its
initial sandbox-only environment check refused Docker socket access; the normal
approved host-side read-only check passed without changing the environment or
bypassing the measurement guard.

The early `rehearsal01` packet remains retained at its original `883f72e` pin.
It must not be executed from the final engine revision. Regenerate the selected
`case01` once at this clean documentation checkpoint, then run the complete case
verifier and independent final readback. The final external receipts are
`case01/verification.json`, `review-final.md` and `completion.json` under
`/tmp/bgperf2-real-bird-validation-20261101`; they record the actual final engine
pin, source mapping, recipe digest, packet hashes and review result without
creating a self-referential engine commit. They are local preparation evidence,
not execution authorization. The frozen final packet and independent review
must both be present and valid before requesting the single execution approval.
