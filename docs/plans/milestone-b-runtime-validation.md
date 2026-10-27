# Milestone B runtime validation

Prepared 2026-10-23. Status: supplied-image functional pair passed under explicit
operator authorization; source-build and broader diagnostic qualification remain
deferred. The original proposal below grants no further execution authority.

## Authorized functional validation — 2026-10-23

The operator authorized exactly one serial baseline/candidate investigation on
`jpietsch-server`, reusing the three pinned images below, basic diagnostics and a
120-second worker budget per attempt. Ordinary concurrent work and the milestone A
small-run root-backed storage exception were explicitly allowed. Downloads,
builds, provisioning, remote transfers, retries, automatic repairs, `9950` access
and pushing remained excluded. This authorization is consumed.

Execution used clean branch `milestone-a-newcomer` at
`9a9af8ca6569f5daa752d9745f832def61a63fd5`, with its existing locked Python 3.14
environment. Exact local image availability was verified before setup. The normal
active-measurement guard passed before execution and after cleanup; no competing
benchmark was observed. Host kernel was `7.0.0-38-generic`, architecture `x86_64`.
`/var/tmp` was writable ext4 on root-backed `/dev/sda5`, with about 264 GiB free
and 56.9 GB available memory at admission, exceeding the 10 GiB/2 GiB smoke floors.
These are suitability snapshots, not performance or hardware qualification.

| Attempt | Identity | Result |
| --- | --- | --- |
| Baseline, observed BIRD 2.19.2 | `bgperf_recipe_3cf00bb3f5e04470a7acbad4d5c787af` | `completed`, exit 0; `reproduced` |
| Candidate, observed BIRD 3.3.2 | `bgperf_recipe_9ebdc602808c436386f5c1a0f8e5600d` | `completed`, exit 0; `reproduced` |

Both attempts delivered 100 prefixes against the existing 99-prefix completion
requirement, with zero tester errors/timeouts. Both reference canonical recipe
SHA-256 `6a9375c18ef18bc61dbb1666cda78c472efade7f26f2505898e23a788a673df0`.
Only target image and descriptive label differ; the generator remained the pinned
BIRD 2.19.2 and observer remained the pinned sink. Supplied-image source, build
flags and instrumentation remain unknown. The report assessment is
`same_observed_reproduction`, with performance `not_assessed`; this released-version
substitution establishes no real bug-fix claim.

Both result packages verify (40 artifacts each), and investigation verification
passes for 84 report files. Each attempt retained five live diagnostic samples,
none dropped, with observed target BIRD presence. Final diagnostics captured
owned states, logs and whole-container cgroup v2 peak/ending memory without final
collection errors. Two optional live generator memory reads timed out in each
attempt; generator sampled peaks remain null. Daemon RSS remains unmeasured.
Empty Docker role logs are retained alongside native BIRD/sink logs. These
supported optional-probe gaps did not produce a setup/harness/inconclusive outcome.
No memory, CPU or timing comparison is accepted under concurrent work and
uncalibrated diagnostic overhead.

The overall investigation command took 28.381 seconds. Setup through first
collection took 11.049/11.033 seconds for baseline/candidate. Total collection
stage spans were 0.279/0.289 seconds, including final diagnostic probe spans of
0.094/0.088 seconds; cleanup to terminal took 1.872/1.199 seconds. Worker budgets
remained 120 seconds each; collection, cleanup and packaging overhead is separate.

Independent review found no blocking issues in raw completion witnesses,
identities, diagnostics, coverage or cleanup. All 37 original regular files per
attempt match their packaged copies. Each original tester control socket remains
in work and is explicitly omitted from portable evidence. All 71 preexisting
container IDs, names, images, states, labels, mount sets and network memberships
match afterward; six network identities are unchanged. Docker reordered mount
lists for 24 containers: the initial positional audit stopped, and a corrected
set comparison and independent review confirmed preservation. This was an
evidence-only audit correction, with no runtime retry or repair. No owned worker,
investigate or mpstat process remained. No broad cleanup or work removal occurred.

### Preserved evidence

All evidence remains local, outside Git:

- `/var/tmp/bgperf-recipe-b-validation`: scope, recipe and target declarations,
  exact command/process logs, image/host/resource observations, before/after
  inventories, audit tools, independent review and preservation records.
- `/var/tmp/bgperf-recipe-b-work-001`: both original work trees and sockets.
- `/var/tmp/bgperf-recipe-b-results-001`: both return packages and the verified
  bundled `report/investigation.json` and `report/REPORT.md`.

`bgperf-recipe-b-validation/SHA256SUMS`, relative to `/var/tmp`, verified 302
regular files. Its SHA-256 is
`e366e2a9a86173eef8b0ad81aa53d3041da8c818652632f405d37b910f5fd542`.
The manifest excludes itself and `preservation-report.json`; that report records
the two retained socket omissions. Both earlier milestone A manifests still
verify, covering 143 and 120 regular files. These local integrity checks are not
an independent backup. Nothing was uploaded, deleted or transferred remotely.

The supplied-image adapter, completion, basic-diagnostic availability and packaging
check is accepted. Real source builds/fixes, crash diagnosis, live-container
timeouts and calibrated performance/memory-regression qualification remain
unassessed and require separately selected scope.

## Original proposal (retained; authorization consumed)

## Recommended first authorization: supplied-image functional pair

Authorize exactly one serial BIRD/BIRD/sink investigation on `jpietsch-server`,
with two maximum 120-second worker budgets and the new basic diagnostics enabled.
Permit ordinary concurrent work only for this functional check, with the same
explicit small-run root-backed disk exception as milestone A. This validates
selected-target substitution, completion, diagnostic availability and packaging;
it supplies no performance comparison or real bug-fix claim.

The earlier local inventory recorded these images. Reinspect exact identities
before execution; a missing or changed image stops the procedure without pulling,
building, importing or retagging anything:

| Role | Immutable local image ID |
| --- | --- |
| Baseline target, generator for both attempts | `sha256:db0a8e144635b1d4b9f81f24ee78f11383c5b0cbd79f10353edcb8452e9af423` (BIRD 2.19.2 as observed in A) |
| Candidate target | `sha256:7f60bf1483ccf766c768f0a3d894b52176748a4d76f9d18cc9af8730520b9142` (previously inventoried BIRD 3.3.2, reverify actual version) |
| Observer for both attempts | `sha256:311317014fc98e2cadf46941b4b23dab9dd724281dd50167a0f9187d8ac08f19` (sink built and observed in A) |

Use one clean checkout at the final committed B implementation and its existing
locked Python environment. Record source revision, host/kernel and capacity
observations. Require the normal active-measurement guard, no other benchmark,
at least 10 GiB free disk and 2 GiB available memory as smoke admission floors,
not workload estimates. Verify `/var/tmp` mount/write suitability. Do not install
or repair missing prerequisites automatically. Keep all earlier A evidence.

After authorization, create an owner-only new `/var/tmp/bgperf-recipe-b-validation`
for recipe, target selections, command logs, exact image inspections and
before/after resource inventories. From the selected clean engine checkout:

```sh
venv/bin/python recipes.py export \
  --batch examples/recipes/synthetic-ipv4.yaml --test synthetic-ipv4 \
  --cell f94a3878b2dad49e --engine-revision "$(git -C . rev-parse HEAD)" \
  --target-image sha256:db0a8e144635b1d4b9f81f24ee78f11383c5b0cbd79f10353edcb8452e9af423 \
  --generator-image sha256:db0a8e144635b1d4b9f81f24ee78f11383c5b0cbd79f10353edcb8452e9af423 \
  --observer-image sha256:311317014fc98e2cadf46941b4b23dab9dd724281dd50167a0f9187d8ac08f19 \
  --question 'Functional milestone B adapter/diagnostic check: do both supplied BIRD targets complete?' \
  --output /var/tmp/bgperf-recipe-b-validation/recipe.json
venv/bin/python recipes.py target-image /var/tmp/bgperf-recipe-b-validation/recipe.json \
  --image sha256:db0a8e144635b1d4b9f81f24ee78f11383c5b0cbd79f10353edcb8452e9af423 \
  --label released-baseline --instrumentation unknown \
  --output /var/tmp/bgperf-recipe-b-validation/baseline-target.json
venv/bin/python recipes.py target-image /var/tmp/bgperf-recipe-b-validation/recipe.json \
  --image sha256:7f60bf1483ccf766c768f0a3d894b52176748a4d76f9d18cc9af8730520b9142 \
  --label supplied-candidate --instrumentation unknown \
  --output /var/tmp/bgperf-recipe-b-validation/candidate-target.json
venv/bin/python recipes.py investigate /var/tmp/bgperf-recipe-b-validation/recipe.json \
  --baseline-target /var/tmp/bgperf-recipe-b-validation/baseline-target.json \
  --candidate-target /var/tmp/bgperf-recipe-b-validation/candidate-target.json \
  --workdir /var/tmp/bgperf-recipe-b-work-001 \
  --results-dir /var/tmp/bgperf-recipe-b-results-001 \
  --timeout 120 --diagnostics basic
venv/bin/python recipes.py investigation-verify \
  /var/tmp/bgperf-recipe-b-results-001/report/investigation.json
```

This selects one peer and 100 prefixes. Both completions are expected; the
report's functional assessment should be `same_observed_reproduction`, with
performance `not_assessed`. Source/flags remain unknown for supplied images.
Do not present a released-version substitution as a real fix investigation.

Stop on the first unexpected setup/harness/inconclusive outcome or failed
verification. No automatic retries, forced terminations, timeout extension or
other workloads are authorized. Probe/collection/cleanup budgets are additional
to the two worker budgets; final diagnostics have a 20-second collection budget
per attempt (plus bounded client termination), and cleanup/packaging overhead
is recorded separately.

Review both verified packages, stage records, exact target-only identity change,
fixed generator/observer, observed versions, optional BIRD presence, logs and
memory accounting. Missing cgroup/peak/RSS observations remain unknown. Confirm
owned resources/samplers stop and unrelated identities remain unchanged. Preserve
all original work, build/target declarations, command logs and checksum/coverage
manifests locally. Record actual results in the engine plan with a local commit.
No evidence removal, upload, 9950 access, provisioning or push is included.

## Separate source-fix/build qualification decision

The controlled fixture proves the source-plan/build/target/report paths with
fakes, not real BIRD compilation or a real bug. A real source-fix investigation
requires the operator to name a concrete trusted BIRD source checkout, requested
full commit and reviewed local changes, plus already-provisioned immutable
builder and runtime base images. No such selection is inferred from a sibling
checkout or made by downloading source.

Once selected, the exact read-only planning action is:

```sh
venv/bin/python recipes.py target-source-plan /absolute/recipe.json \
  --source /absolute/operator-selected/bird --revision FULL_40_HEX_COMMIT \
  --toolchain-image sha256:APPROVED_LOCAL_TOOLCHAIN_64_HEX_ID \
  --runtime-image sha256:APPROVED_LOCAL_RUNTIME_64_HEX_ID \
  --instrumentation debug --cflags='-O0 -g' --include-dirty \
  --output /absolute/new/candidate-build-plan.json
```

The source tree must meet the full-checkout/no-filter/no-lazy-fetch restrictions
in the [investigation guide](../investigations.md). Review the actual snapshot,
patch/untracked hashes, configure/link flags and plan before authorizing exactly
one `target-build PLAN --output-dir NEW_DIR --timeout 1200`. It uses
`--network=none` and `--pull=false` through the required local legacy builder,
with BuildKit disabled and no remote Buildx fallback. All build tools, headers and runtime/sanitizer
libraries must already exist. A missing prerequisite is a refusal, not permission
for package installation, image acquisition or a broader build. Timeout stops
owned clients but cannot guarantee Docker daemon/cache cancellation.

After successful identity verification, a separate two-attempt functional
investigation can reuse the same frozen recipe and instruments, selecting the
new local target. The concrete bug and expected outcome must be stated first;
a reproduced baseline and nonreproduced candidate are observations, not a
universal fix guarantee. Core dumps, privileged journals, forced daemon faults,
active-container timeout trials and real memory-regression qualification are not
included in either authorization proposed here. Prepare their exact procedure,
budget, owned resources and evidence expectations separately if selected.

## Decision at the milestone B handoff

Review the returned controlled reports and public commands first. Recommended
first real check is the supplied-image pair above, requiring no downloads or
builds. Alternatively, select the real BIRD bug/source pair and reviewed local
base images so the source plan can be made concrete before any build approval.
No additional stage is authorized to execute; the supplied-image authorization
was consumed by the recorded pair above.

## Source-build and interruption validation — 2026-10-26

Status: concrete bounded procedure prepared under the operator's instruction
to resume milestone B. Earlier one-shot supplied-image authorizations remain
consumed. This new functional check reuses only existing local source/images.

Select clean BIRD 2.19.2 commit
`1d201ed0360c749dfe3d3b3b079329e7148159cd` at
`/tmp/bgperf2-milestone-d-live-20261026/source`. This checkout was copied locally
from the already selected immutable BIRD image, whose retained full Git history
and clean worktree were inspected; no source was downloaded. It remains
unchanged. Use `bird-local/v1`, debug instrumentation, `-O0 -g`, no extra
configure options, and the same existing local image as both builder and
runtime base:
`sha256:db0a8e144635b1d4b9f81f24ee78f11383c5b0cbd79f10353edcb8452e9af423`.
Read-only, network-disabled image inspection confirmed Bash, tar, autoreconf,
gcc, make, flex, bison, readline/ncurses headers, iproute2 and BIRD 2.19.2.
The daemon reports local Docker 29.1.3; the actual legacy-builder execution is
still to be qualified by the explicit build, without a Buildx fallback.

Use one new owner-only evidence root:
`/tmp/bgperf2-milestone-b-source-20261026`. Deliberately select its persistent
ext4 root-backed `/dev/sda5` storage as a bounded functional-validation exception,
not a performance measurement layout. Admission observed 231,865,225,216 disk
bytes free and 58,435,776,512 bytes MemAvailable. Recheck at least 20 GiB disk
and 16 GiB available memory before build and each attempt; these are protective
reservations, not estimates of demand. The active-measurement guard passed;
the unrelated `second-looks-box` container remains untouched. Ordinary light
background work is permitted. No performance/hardware qualification is implied.

Freeze the engine at the clean commit containing this procedure. Export public
cell `synthetic-ipv4/f94a3878b2dad49e`: one peer, 100 prefixes, fixed supplied
BIRD generator/baseline image above and fixed observer
`sha256:311317014fc98e2cadf46941b4b23dab9dd724281dd50167a0f9187d8ac08f19`.
The question is clean-source build/adapter/diagnostic compatibility, with
`experiment_completed` expected. This is not a selected BIRD bug/fix or a
performance comparison; both targets are expected to complete.

After independent review of the frozen source/build plan and commands:

1. Execute exactly one public `target-build` with a 1,200-second build-client
   budget. Keep network disabled and pulls false, use only the selected local
   daemon and bases, and retain source archive/patch, Dockerfile, disclosure,
   logs, target identity and new image. Do not build while a measurement runs.
2. Inspect the resulting image and BIRD version; verify source/build/image
   bindings. Recheck both public target prerequisites. Run exactly one public
   serial `investigate` pair: released baseline then source-built candidate,
   each with 120 worker seconds and basic diagnostics. Verify both original
   packages and the portable investigation report. Expected assessment is
   `same_observed_reproduction`; performance remains `not_assessed`.
3. After accepted pair/cleanup review, run one further source-built recipe with
   a 120-second worker budget and basic diagnostics. Identify its worker by
   exact parent/workdir/attempt identity, wait at most 30 seconds for one of
   its owned containers to run, then send SIGTERM only to that public recipe
   controller. Expect exit 143, `interrupted` accounting, verified partial
   package and no owned resources left. This explicitly exercises interruption
   with live containers. If no owned running container appears within the
   admission window, stop that controller and record the check as not qualified;
   never retry or extend it. No daemon crash is deliberately injected.

Execution is serial. Stop at the first unexpected build, setup, runtime,
verification or cleanup failure; preserve all work without retry, timeout
extension or automatic repair. Diagnostic and cleanup probe budgets remain the
documented bounds outside worker time. Verify initial/final container identity/
state, network and volume inventories, unique attempt IDs, diagnostic presence/
missing facts, source cleanliness and exact engine pin. Review the interruption
controller and outcome independently. Original artifacts stay local with a
complete path/type/hash inventory; sockets are recorded without opening them.
Run no development/tests/analysis while recipe workers are active. Only read-only
operational supervision and owned interruption/cleanup are permitted then.

No downloads, additional builds/attempts, forced daemon faults, privileged cores/
journals, memory-regression verdicts, new timers, provisioning, `9950` access,
push, remote evidence transfer or deletion are included. A successful check
qualifies real clean-source building and the exercised basic diagnostic/cleanup
paths. It does not prove a source bug fixed, qualify all failure diagnostics or
complete live bisection/performance calibration.
