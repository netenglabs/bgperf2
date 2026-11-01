# Real BIRD prefix-identity validation — approved attempt stopped at admission

The operator approved the frozen case at engine
`9bcfe1da1063f5d89a8cd258750ffabb163e542d`, including the functional root-storage
exception. Its single admission stopped before any build, probe container or
worker because other development tests were running. This case is closed;
unused positions authorize no retry. The preparation below remains historical.

Selected 2026-11-01 after implementation commit
`e7798ad1e2f91d7c7197dfc79bf7295cfb55bd3d`. This goal prepares one independently
reviewed case, without executing it. Performance policy stays disabled and
formal 10% calibration deferred.

## Question and inspected materials

Does sink 0.2.0 capture the exact 100 expected IPv4 /32 prefixes from one BIRD
generator through one BIRD target, with correct source/image/recipe bindings,
a satisfied 120-second worker budget and owned cleanup?

The [implementation](observer-prefix-identity.md) passed 2,692 Python tests and
pinned offline Go vet/race checks. Independently rechecked public CLI fixtures
show correct-set success, same-count substitution failure and old count-only
evidence remaining unmeasured. These are simulated packages. The earlier
[neutral real-BIRD case](real-bird-maintainer-validation.md) completed 100-prefix
workers using this BIRD image. Neither qualifies the new sink runtime, UID
boundary or capture lifecycle. No upstream bug, introduced routing fault or
timing effect is selected here. All prior evidence remains in place.

Engine `/tmp/bgperf2-milestone-a`, branch `milestone-a-newcomer`, started clean
at `e7798ad`; the final packet freezes its actual clean committed HEAD.
Existing local images were independently inspected:

| Role | Exact local image ID |
| --- | --- |
| Go 1.25.14 toolchain | `sha256:e3c6b02e53225e75dff3e6a3b4c0bf9567fe16564fb20a5f63d4e39361ee32e3` |
| Debian runtime base | `sha256:db9f02c6bde9fa90cc8074c92754b2b046947392f1a857726e77f041febb7b82` |
| BIRD 2.19.2 target and generator | `sha256:db0a8e144635b1d4b9f81f24ee78f11383c5b0cbd79f10353edcb8452e9af423` |

Go/Debian RepoDigests match `sink.py`'s pins. Existing sink 0.1.0 is retained
unchanged. Image IDs identify local content, not publisher trust or reproducible
binaries. No missing module, image or package may be acquired or substituted.

## Offline build gap and preparation

Changed embedded source invalidates normal compilation cache. The old runtime
image supplies no Go cache; do not assume the normal `go mod download` avoids
network access. The [preparer](../../scripts/prepare_prefix_identity_case.py)
freezes the exact source using the same deterministic archive as the standard
sink identity. It copies existing GoBGP v4.9.0 and x/sys v0.45.0 `.info`, `.mod`
and `.zip` inputs from `/tmp/step10-gomod/cache/download`, about 3.7 MB, into a
deterministic dependency archive. Raw inputs/hashes and bounded ZIP inspection
remain. Cached `.ziphash`, extracted trees, mutable lists and locks are excluded.
The build must recompute checksums against committed `go.sum`.

The Dockerfile uses the fixed local image IDs, `GOPROXY=off`, `GOSUMDB=off`,
`GOTOOLCHAIN=local`, `GOMAXPROCS=2`, `GOFLAGS="-mod=readonly -p=2"` and fresh
case-specific module/source directories that must be absent before extraction.
It verifies modules, vets/tests source and builds a static sink with the actual
source hash. The legacy builder has network none/pull false. Missing data fails;
no acquisition, Buildx or network fallback. Changed module pins/sink versions
are refused. This local validation image uses separate case/source labels,
not the standard recipe-current label. It does not change the standard builder
or tag/replace `bgperf/sink`. Record cache reuse; reproducibility is unassessed.
Build intermediates are retained (`--rm=false`).

Selected packet: `/tmp/bgperf2-prefix-runtime-20261101/case01`.
Future execution: `/tmp/bgperf2-prefix-runtime-20261101/execution01`.
Create only their shared parent if absent, then at the final clean HEAD:

```sh
/tmp/bgperf2-milestone-a/venv/bin/python /tmp/bgperf2-milestone-a/scripts/prepare_prefix_identity_case.py prepare \
  --cache /tmp/step10-gomod/cache/download \
  --output /tmp/bgperf2-prefix-runtime-20261101/case01 \
  --execution /tmp/bgperf2-prefix-runtime-20261101/execution01
/tmp/bgperf2-milestone-a/venv/bin/python /tmp/bgperf2-milestone-a/scripts/prepare_prefix_identity_case.py verify \
  /tmp/bgperf2-prefix-runtime-20261101/case01
```

Review CASE.md, case.json, commands.json, SHA256SUMS.json and context. Verification
reconstructs bytes/commands/budgets, checks original dependency bytes and clean
HEAD, refuses unsafe/unlisted files and requires execution absent. Destinations
are fixed siblings of caseNN, so a fully rehashed packet cannot redirect writes.
After work begins, `verify CASE --started` permits that existing root for
read-only verification, never resumption. Preserve partial preparations and
use new caseNN/executionNN paths instead of overwriting.

## One approval: admission, commands and evidence

Approval would cover exactly this frozen case on the current development host:

1. One admission: native measurement guard, clean pinned engine/environment,
   exact images/tools, mounts/capacity and Docker container/network/volume
   inventories. Require no active BGP measurement or other development/build/test
   run, plus six five-second aggregate busy-CPU observations at most one core.
   The exact mpstat command is in the packet; for each aggregate interval,
   busy fraction × reported CPU count must be at most one. This conservatively
   bounds outside work by including the admission tools themselves. Save all
   admission commands/stdout/stderr/exits in the fresh sibling admission01 root.
   Any
   failed/unreadable condition stops. No wait-until-idle loop or admission retry.
2. Create only execution/build roots; run the generated build command once
   with a 900-second timeout and ten-second client kill grace. Preserve
   build/build.log, actual exit in build/build-exit.json (`{"exit_code": N}`)
   and returned build/image-id.txt. Failure consumes the position and stops.
3. Offline `image-commands CASE` prints exact inspection/version-probe commands
   from that validated image ID. Preserve build/image-inspect.json and actual
   build/inspect-exit.json. Run one named/case-labeled version probe with network
   none, pull never, read-only filesystem, dropped capabilities, 15-second timeout
   and five-second client kill grace. Preserve build/version.txt and actual
   build/version-exit.json. Expect sink 0.2.0, exact source hash, GoBGP v4.9.0 and
   Go 1.25.14. Independently review source/build/cache/image evidence.
4. Offline `bind CASE` requires all three zero-exit receipts and exact image,
   source/case labels and version. It writes fresh bound/recipe.json,
   bound/assertions.json and binding receipt with the actual observer image ID.
   Workload: existing synthetic-ipv4 cell f94a3878b2dad49e, one peer × 100 disjoint
   prefixes. No image ID is guessed. Use `verify-bound CASE` before public check
   and immediately before run; it reconstructs all bound bytes. Labels/receipts
   are local evidence, not authenticated proof that commands executed.
5. Recheck memory/disk, guard, competing work and image identities. Run public
   check, then one public run with --observer-prefixes --diagnostics basic
   --timeout 120. This is one functional worker, not a performance comparison.
6. Verify original result and all six assertions. Independently review raw
   prefix equality, recipe/source/image identities, clocks/budget, directory and
   socket modes, tester errors/timeouts and cleanup. Record final inventories,
   separating retained case-labeled build intermediates from unrelated resources.
   Preserve stdout/stderr/exits, original work/results, reviews, checksums/readback.

Budget: **one 900-second build + one 120-second worker = 1,020 seconds (17
minutes)**, plus one 15-second version probe; Go parallelism two; zero retries.
Existing cached dependencies/native Go checks justify one 15-minute attempt,
not success. Previous tiny BIRD workers took about 12 seconds; 120 seconds allows
setup and bounded capture, without a performance/resource estimate. The
**30-minute operator ceiling** includes admission/reviews/probes/cleanup. No
automatic outer scheduler exists. Reaching it stops successors. Docker daemon
work can outlive client cancellation and must be inspected.

Require 16 GiB available memory and 20 GiB disk before build and worker. These
are conservative floors, not reservations or measured needs. Selected /tmp is
root-backed ext4 on /dev/sda5. **Approval must explicitly include the functional-only
root-storage exception.** Existing warnings remain. This qualifies neither
hardware nor performance; optional missing memory stays null, timing descriptive.

No BIRD source build, second build/probe/worker, comparison, investigation,
bisection, introduced fault, acquisition, queue enrollment, provisioning,
push/publication, remote transfer or evidence deletion is covered.

## Expected outcomes and recovery

Expect zero exits: worker completion, session ready, injection complete, exact
100-route count, all 100 expected /32 identities with zero missing/unexpected
prefixes, and healthy final roles. All six assertions must pass. Snapshot identity
is one final state, not convergence-time identity, attributes or continuous
correctness. Any failed/refused/late/interrupted/inconclusive action, unavailable
snapshot, assertion failure, wrong input, cleanup error or rejected review stops.
Count passing with identity unmeasured is not acceptance. No workaround or retry.

Do not rerun uncertain commands. After build timeout inspect client/daemon and
case-labeled intermediates; retain partial build evidence and images, without
tag replacement, pruning or deletion. After probe interruption inspect its exact
name/label/image/logs; stop/remove only that verified owned probe if necessary.
Worker ownership cleanup remains authoritative. After interruption verify any
original results/result.json; absent/invalid packaging stays unknown and grants
no extra worker. Preserve original work, partial runtime and socket metadata/
collection omissions. Do not fabricate packages or infer nonexecution from absence.

Checksum/read back all available preparation/build/work/result/review files,
including archives, cache inputs and failures. Runtime sockets are not regular
files: preserve metadata/omissions without contacting them. Originals remain.
Local same-device retention is not independent backup. Remote preservation,
publication and cleanup are outside approval.

## Preparation acceptance

Before asking approval: inspected inputs/prior evidence/storage; reviewed
source/context/commands and future-image binding; negative/preservation tests
and native gate passed; independent review accepted; local commit complete;
final packet verified at clean HEAD with execution absent and independent final
readback accepted. External receipts retain actual commit/packet hashes without
self-reference. Runtime compatibility and execution-time admission stay unknown.

Independent preparation review accepted the source, tests and plan after fixing
a fully rehashed execution-destination substitution. Seventeen focused tests
cover offline/nonexecution behavior, archive/source identity, original input
preservation, unsafe cache inputs, narrowed commands, destination substitution,
returned-image/exit/version binding and bound-recipe substitution. The focused
plus documentation gate passed 95 tests. No build/probe/worker ran. Actual native
gate, final commit, frozen-packet hashes and independent readback are recorded
under `/tmp/bgperf2-prefix-runtime-20261101/`, outside the source checkout.

## Approved attempt: admission refusal — 2026-11-01

The checkout was clean on `milestone-a-newcomer` at the frozen `9bcfe1d` pin.
All eleven selected read-only admission commands exited zero: packet, native
measurement guard, locked environment, exact image inspection, mount, disk,
memory, process snapshot and Docker container/network/volume inventories.
The process snapshot nevertheless records seven actual Python pytest processes,
including parallel suites in other worktrees. This violates the separately
required absence of other development/build/test work. A passing BGP guard
does not override that condition. Other processes and resources were untouched.

Available memory was 37,319,225,344 bytes and disk 147,083,284,480 bytes, both
above selected floors. Root-backed ext4 `/dev/sda5` was confirmed. The six-interval
CPU screen was not run after the process refusal: no CPU threshold, host quietness
or quiet-throughout claim is inferred. Passing capacity is not admission success.

Accounting is **zero attempted builds, zero version-probe containers and zero
workers**, with one of each never run and no failed worker experiment.
`execution01` remains absent; there is no built sink, bound runtime recipe,
worker package or new runtime-compatibility result. The approval is consumed.
No waiting loop, admission retry, hourly enrollment, acquisition, pruning,
remote transfer, push or publication occurred. Prior packet metadata remains
historical prepared-only evidence; the terminal admission record governs it.

Original command receipts, process/capacity witnesses, terminal inventories,
independent review and preservation readback are under
`/tmp/bgperf2-prefix-runtime-20261101/admission01/` and its parent. Preserve them
and all prior evidence. A further execution needs a separately selected fresh
case/decision resolving admission, with new destinations and appropriate pins;
do not silently reuse this packet or its unused positions. Real sink build and
capture compatibility remain unassessed. Policy stays disabled and calibration
deferred.
