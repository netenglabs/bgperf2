# Milestone A runtime validation

Prepared 2026-10-23. Status: authorized end-to-end functional workflow and early
timeout validation passed; performance/hardware qualification remains unassessed.
This is the bounded validation decision for the
[developer performance testing plan](performance-testing-development-plan.md).
The supported synthetic BIRD/BIRD/sink workflow is ready for feedback with real
return packages. No performance comparison or hardware qualification is claimed.

## Authorization and actual result — 2026-10-23

The operator explicitly authorized the sink-only download/build and functional
validation alongside ordinary work on `jpietsch-server`, superseding this
proposal's idle-development-host requirement for this check. Another active
benchmark remained excluded; the normal active-measurement guard passed before
build and execution. The root-backed disk `/var/tmp` exception was accepted for
this small functional check. Performance comparisons remain unsuitable. This
permission does not qualify hardware or authorize work on `9950`.

The original proposal below was executed at engine
`7b2d502d41d8d3e92ddf75bf59779d8c598502ea`:

- The selected sink-only build succeeded, including embedded Go vet and tests.
  Its immutable image is
  `sha256:311317014fc98e2cadf46941b4b23dab9dd724281dd50167a0f9187d8ac08f19`,
  recipe label `7d97ffab584f`, reported source hash `88869d1e0b01`,
  GoBGP/v4 `v4.9.0` and Go `1.25.14`. The original BIRD image below was reused
  for target and generator; no BIRD rebuild occurred. Build reconstruction claims
  remain limited to the saved build inputs/logs and observed identities.
- Export, validation, offline plan, selected preparation and prerequisite checks
  passed. One real attempt, `bgperf_recipe_4b9f99b245564518ad735608a1312aa2`,
  delivered 100 prefixes against the existing engine's required count of 99,
  with zero tester errors/timeouts. Its worker recorded `completed` and no
  cleanup errors. Observed role image IDs and versions matched the recipe.
- The controller returned `harness_failed` (exit 3): packaging attempted to copy
  BIRD's nonportable tester Unix control socket, owned by UID/GID 65534 with mode
  0660. The engine completed; end-to-end return-package acceptance failed.
  The failed package remained readable and passed checksum verification. The
  driver stopped at this failure: no benchmark retry or real timeout trial ran.
- Independent review confirmed all 62 original container IDs, names, image
  references, states, mount sets, labels and network sets were unchanged; network
  IDs were unchanged. No recipe container/network or worker/mpstat process
  remained. The legacy sink build left nine nonrunning intermediate containers;
  they and the selected image/build cache were retained. No broad Docker cleanup
  or unrelated-container modification was performed.
- `3165af2` fixes collection by identifying actual Unix socket types before
  opening them and recording checksummed `collection-omissions.json`. Symlinks,
  FIFOs and unreadable regular artifacts still fail collection. `8e9ed9b` adds
  a regression proving a regular file named `bird.ctl` is preserved. Independent
  review found no blockers; 32 package tests and the normal full 2,101-test
  Docker-free commit gate passed.
- The committed fix at full packaging revision
  `8e9ed9bb68b3e51aa63d4af47cd2ea66452c4f58` was applied offline to the retained
  work into a separate `repackage-001` result directory. It verified 27 packaged
  artifacts and all 23 source regular files, with `completed` / `reproduced` for
  the original completion question. The socket omission is explicit. Original
  work and the original failed package were byte-checked unchanged. A separate
  `packaging-tool.json` retains both packaging and execution revisions; the
  recipe/result still identify execution revision `7b2d502`, never the later
  packager as if it had executed the experiment.

At this first-attempt handoff, functional route delivery and owned cleanup had
passed, and corrected packaging had passed offline replay. Fresh end-to-end
execution and the real timeout check remained pending until the separately
authorized continuation recorded below. Raw CPU, memory and
timing observations reflect authorized concurrent work and support no performance
comparison, ranking or host qualification.

## Preserved local evidence

Evidence remains on the development host, outside Git:

- `/var/tmp/bgperf-recipe-a-validation`: authorization scope, host/resource
  snapshots, exact commands/process outcomes, rendered sink Dockerfile, build
  output, image inspections, before/after inventories, resource audit, offline
  package verification and preservation tools.
- `/var/tmp/bgperf-recipe-a-work/success-001`: original runtime work, including
  the nonportable socket; `/var/tmp/bgperf-recipe-a.json`: original recipe.
- `/var/tmp/bgperf-recipe-a-results/success-001`: original failed package.
- `/var/tmp/bgperf-recipe-a-results/repackage-001`: corrected offline package,
  with the original attempt identity and explicit separate packaging provenance.

`bgperf-recipe-a-validation/SHA256SUMS`, resolved from `/var/tmp`, verifies all
143 regular evidence/tool files, excluding the manifest and its preservation
report. The one runtime Unix socket is explicitly omitted from file-byte hashing
in `preservation-report.json`. The manifest SHA-256 is
`753109ca63f49ef1db77696e1b14f521f6e95327297df846c099e77c25b63c6c`.
No work or evidence was deleted, uploaded, published or copied off-device. The
local manifest is integrity evidence, not an independent backup or publisher
authentication. `9950`, provisioning and pushing remained excluded.

## Separately authorized retry — executed 2026-10-23

The operator explicitly approved the following bounded continuation. The
stop-on-failure rule remained in force:
reuse the exact BIRD and now-existing sink IDs above, with no downloads/builds,
and run exactly one fresh 120-second functional attempt at the final clean
socket-fix revision. Permit ordinary concurrent work under the same functional-
only limitation and root-backed disk exception. If it completes and its package
verifies, run one separate 0.01-second timeout attempt. Stop at the first
unexpected failure, preserve every attempt, and make no automatic retries.
The same no-9950, no-provisioning, no-push and no-transfer limits apply.

Under that explicit authorization, export a new recipe outside the clean source
checkout using the exact target/generator and observer image IDs recorded above
and the full current engine revision. Use `/var/tmp/bgperf-recipe-a-retry.json`,
new `retry-001` work/results names and `timeout-001` only after successful retry.
These paths do not replace or resume `success-001` or `repackage-001`.
Then use the commands below from the selected clean checkout:

```sh
venv/bin/python recipes.py export \
  --batch examples/recipes/synthetic-ipv4.yaml --test synthetic-ipv4 \
  --cell f94a3878b2dad49e --engine-revision "$(git -C . rev-parse HEAD)" \
  --target-image sha256:db0a8e144635b1d4b9f81f24ee78f11383c5b0cbd79f10353edcb8452e9af423 \
  --generator-image sha256:db0a8e144635b1d4b9f81f24ee78f11383c5b0cbd79f10353edcb8452e9af423 \
  --observer-image sha256:311317014fc98e2cadf46941b4b23dab9dd724281dd50167a0f9187d8ac08f19 \
  --question 'Functional-only under concurrent work: does one peer offering 100 prefixes complete?' \
  --output /var/tmp/bgperf-recipe-a-retry.json
venv/bin/python recipes.py check /var/tmp/bgperf-recipe-a-retry.json \
  --workdir /var/tmp/bgperf-recipe-a-work/retry-001 \
  --results-dir /var/tmp/bgperf-recipe-a-results/retry-001
venv/bin/python recipes.py run /var/tmp/bgperf-recipe-a-retry.json --timeout 120 \
  --workdir /var/tmp/bgperf-recipe-a-work/retry-001 \
  --results-dir /var/tmp/bgperf-recipe-a-results/retry-001
venv/bin/python recipes.py result-verify /var/tmp/bgperf-recipe-a-results/retry-001/result.json
# Only after successful completion and verification:
venv/bin/python recipes.py run /var/tmp/bgperf-recipe-a-retry.json --timeout 0.01 \
  --workdir /var/tmp/bgperf-recipe-a-work/timeout-001 \
  --results-dir /var/tmp/bgperf-recipe-a-results/timeout-001
venv/bin/python recipes.py result-verify /var/tmp/bgperf-recipe-a-results/timeout-001/result.json
```

The expected exits are 0 for successful functional completion and 5 for bounded
timeout; verify both packages, exact images, statuses, evidence and resource
cleanup. These two attempts have now run as recorded below; this completed
authorization grants no further runtime attempts.

## Fresh functional and early-timeout acceptance — 2026-10-23

Both authorized attempts ran at clean execution revision
`73fed28a94149f311b5562f1a0c42edd522d7ba7`. No images were downloaded or built;
target and generator reused the exact BIRD image, and observer reused the exact
sink image recorded above. The normal active-measurement and resource checks
passed. Ordinary concurrent work and the explicit root-backed disk exception
remained accepted for functional-only use.

| Attempt | Worker budget | Experiment outcome | Reproduction outcome | Package verification |
| --- | --- | --- | --- | --- |
| `bgperf_recipe_0dfbeb22eb2a47aba5e3173155f68a1b` (`retry-001`) | 120 s maximum | `completed`, exit 0 | `reproduced` for experiment completion | 26 artifacts verified; all 23 source regular files matched |
| `bgperf_recipe_3de3810e7cdb400097b55a554b9747e3` (`timeout-001`) | 0.01 s | `inconclusive`, exit 5, expected deadline | `inconclusive` | 6 artifacts verified; all 4 source regular files matched |

The fresh functional attempt delivered 100 prefixes at both target-export and
monitor witnesses, against the existing 99-prefix completion requirement, with
zero tester errors/timeouts. Observed role image IDs, daemon versions and engine
provenance matched the exported recipe. The BIRD control socket was retained in
original work and explicitly omitted from portable file evidence through the
checksummed omission record. The controller produced its complete return package
without offline repair or manual status changes.

The real deadline attempt preserved its recipe, prerequisites, controller log
and runtime outcome. Events, provenance, samples and generated configuration are
explicitly missing with reasons, never zero-valued substitutes. No configuration
was generated and no container activity was observed before the early deadline.
This establishes early worker timeout/status/partial-package behavior; it does
not qualify cleanup after a timeout while containers are actively running.
The latter path remains covered by fake-runtime tests, not a real qualification.

Independent review found no blocking issues in raw completion, exact identities,
status separation, socket omission, full copy coverage or resource preservation.
Both before/after inventories retained all 71 baseline container identities,
names, image references, states, mount sets, labels and network sets, with no new
container IDs and unchanged network IDs. No attempt containers, worker or mpstat
processes remained. The prior preservation manifest's 143 entries still matched.
No broad cleanup, further retry, download, build, 9950 access, provisioning, push
or evidence transfer occurred.

The authorized newcomer workflow and early-timeout validation are complete for
this supported subset on this host. Ordinary concurrent work excludes timing,
CPU or memory comparisons. Host qualification, resource estimation, real
`prepare --pull` acquisition, live-container timeout cleanup and broader adapter
or diagnostic qualification remain unassessed, not inferred from this smoke.
No broader runtime validation is required to review the delivered milestone A
workflow; selecting such work or milestone B is a separate decision.

### Additional preserved evidence

The new evidence is separate from the earlier sealed record:

- `/var/tmp/bgperf-recipe-a-validation-retry-001`: renewed authorization scope,
  exact commands, host/capacity/image snapshots, before/after inventories,
  resource/copy audit, acceptance summary and preservation tools.
- `/var/tmp/bgperf-recipe-a-retry.json`: the new recipe pinned to `73fed28`;
  both attempts reference canonical recipe SHA-256
  `37561654bbd556a2c05e139e6d8cfaf905ec58169b3054ffe458c2f372bb3887`.
- Original work: `/var/tmp/bgperf-recipe-a-work/retry-001` and
  `/var/tmp/bgperf-recipe-a-work/timeout-001`.
- Returned packages: `/var/tmp/bgperf-recipe-a-results/retry-001` and
  `/var/tmp/bgperf-recipe-a-results/timeout-001`.

The new `bgperf-recipe-a-validation-retry-001/SHA256SUMS`, relative to `/var/tmp`,
verified 120 regular evidence/tool files, excluding the checksum manifest and its
preservation report. Its SHA-256 is
`24330b75fd01f7789c8d89c5a828db1d4f6d7913f35a39bc9dd73f3e91651822`.
The one nonportable socket is explicitly listed in the preservation report.
The original failed package, offline repair and earlier evidence remain unchanged.
No evidence was deleted or moved off-device; these local checksums are not an
independent backup.

## Original proposal (retained)

The idle-host wording below records the original proposal. The explicit
functional-under-load authorization above superseded it only for the attempt
recorded here; it did not authorize performance comparisons or automatic retries.

## Decision requested

Recommended: authorize one functional BIRD/BIRD/sink smoke on `jpietsch-server`
after an explicit idle-host and storage check, and separately authorize obtaining
the missing sink image. Leave `9950` untouched. No remote host, provisioning,
push, upload, publication, MRT input or research checkout is involved.

Read-only local image inspection on 2026-10-23 found BIRD 2.19.2 at
`sha256:db0a8e144635b1d4b9f81f24ee78f11383c5b0cbd79f10353edcb8452e9af423`.
Use this same exact image for target and generator, recording its observed
version/provenance rather than assuming its tag proves a rebuild identity.
There is no local `bgperf/sink` image. No images were acquired or started while
preparing this proposal. The checked-in recipe's fake pins are never download
or execution targets.

Choose the sink supply boundary before running:

- Preferred if available: supply a trusted sink image already built from this
  engine's sink source, with its immutable image ID or repository digest and
  provenance. Explicitly authorize any import or digest pull. An absent bare
  image ID cannot be downloaded by `recipes.py prepare`.
- Alternative: authorize exactly `venv/bin/python bgperf2.py prepare -t sink`
  from the final clean milestone revision, on this idle development host. This
  builds only sink and may download the pinned Go/debian base images and Go
  modules selected by the committed `sink.py` build recipe and
  `sink/go.mod`/`sink/go.sum`. Save the
  build log, rendered Dockerfile, source revision and resulting image inspection.
  Download bytes and build time are unknown; allow a 20-minute operator budget
  and stop on error or unexpected image acquisition. Interrupting the Docker
  client does not guarantee cancellation of daemon-side build/cache work; inspect
  that state before continuing. No BIRD rebuild, broad prepare or other daemon
  build is included. If a hard build resource limit is required, defer this
  alternative and supply an approved prebuilt sink instead.

The authorization can cover the smoke alone once the sink is supplied; it need
not authorize source builds. Neither choice changes publisher trust or hardware
qualification automatically.

## Exact execution after authorization

Use the final committed milestone revision and existing locked Python 3.14
venv. Record `git -C /absolute/path/to/bgperf2 rev-parse HEAD`, host/kernel
facts and image IDs. Confirm no
active measurement locks/containers and no concurrent development, builds or
analysis during the run. Check mount type and available space for the selected
work and results parents. Require 10 GiB free disk and 2 GiB available memory as
conservative smoke admission floors, not workload estimates. The user must
accept this host for a functional smoke; results remain unsuitable for a
performance ranking. Its root-backed `/var/tmp` is an explicit small functional
smoke exception to the lab's measurement-storage policy, not a campaign layout.

Create `/var/tmp/bgperf-recipe-a-work` and `/var/tmp/bgperf-recipe-a-results` as
operator-owned disk-backed parents after confirming these names are unused and
suitable. Store the recipe and command logs separately outside the clean source
checkout. These shell variables are explicit values filled from the recorded
commit and approved image inspection, with no floating image references. Run
the commands below from that selected engine checkout:

```sh
ENGINE_REVISION=$(git -C /absolute/path/to/bgperf2 rev-parse HEAD)
BIRD_IMAGE=sha256:db0a8e144635b1d4b9f81f24ee78f11383c5b0cbd79f10353edcb8452e9af423
SINK_IMAGE=sha256:REPLACE_WITH_APPROVED_OBSERVED_64_HEX_IMAGE_ID
venv/bin/python recipes.py export \
  --batch examples/recipes/synthetic-ipv4.yaml --test synthetic-ipv4 \
  --cell f94a3878b2dad49e --engine-revision "$ENGINE_REVISION" \
  --target-image "$BIRD_IMAGE" --generator-image "$BIRD_IMAGE" \
  --observer-image "$SINK_IMAGE" \
  --question 'Does one BIRD peer offering 100 prefixes complete and return verifiable evidence?' \
  --output /var/tmp/bgperf-recipe-a.json
venv/bin/python recipes.py prepare /var/tmp/bgperf-recipe-a.json
venv/bin/python recipes.py check /var/tmp/bgperf-recipe-a.json \
  --workdir /var/tmp/bgperf-recipe-a-work/success-001 \
  --results-dir /var/tmp/bgperf-recipe-a-results/success-001
venv/bin/python recipes.py run /var/tmp/bgperf-recipe-a.json --timeout 120 \
  --workdir /var/tmp/bgperf-recipe-a-work/success-001 \
  --results-dir /var/tmp/bgperf-recipe-a-results/success-001
venv/bin/python recipes.py result-verify /var/tmp/bgperf-recipe-a-results/success-001/result.json
```

This selects one peer and 100 prefixes from the public example, not the whole
matrix. Check every exit status and stop at the first unexpected refusal/failure.
`prepare` above does not pull. No missing dependency is repaired automatically.
After the successful attempt, propose one optional timeout-path attempt using
the identical recipe and new `timeout-001` paths with `--timeout 0.01`. It should
exit 5, preserve partial evidence and clean its owned resources. Authorizing this
option allows two attempts total; total worker budgets are at most 120.01 seconds
plus bounded probes, cleanup and collection. No automatic retries or repetitions.
A forced target crash or interruption trial needs a separate selected scope.

## Evidence and acceptance

Keep both original work trees and local result packages. Verify result hashes,
recipe/engine identities, actual three-role image identities, raw events,
versions/provenance, samples, generated configurations and console logs. Check
that successful completion and reproduction outcomes are supported, missing
artifacts are declared, and no labelled attempt containers/network or sampler
processes remain. Confirm unrelated resources retain their identities. A failure
retains its artifacts and stops acceptance; it is not silently retried or turned
into a timing result. Manual disk review follows because collection duration and
log sizes are not hard-capped by the worker budget.

Record actual commands, host suitability, IDs, outcomes and limitations in the
main plan with a local documentation commit. Do not copy evidence to a remote
service. This functional smoke can establish real adapter compatibility and
packaging behavior on the selected host; it cannot qualify another host, prove
source reconstruction, diagnose crashes inside a still-running container or
establish performance comparability. Broader source/build trust, instrumentation
and diagnostics remain milestone B decisions.
