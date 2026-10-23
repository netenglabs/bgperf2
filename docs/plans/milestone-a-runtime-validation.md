# Milestone A runtime validation proposal

Prepared 2026-10-23. Status: proposed, no runtime authorization granted.
This is the bounded validation decision for the
[developer performance testing plan](performance-testing-development-plan.md).
The implementation and fake workflow are ready for feedback; real adapter and
hardware acceptance remain pending. No performance comparison is proposed.

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
