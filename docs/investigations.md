# Test and diagnose a BIRD fix

Use one immutable [recipe](recipes.md), with separate target/build identity
records for the baseline and candidate. The recipe's workload, generator,
observer, engine revision, completion contract and reproduction question stay
fixed. The initial supported adapter is synthetic IPv4 BIRD/BIRD/sink. This is
one functional investigation; statistical performance comparison remains a later
milestone.

For repeated target comparisons and named observable correctness checks, follow
the [comparison guide](comparisons.md). The single-pair workflow here preserves
its functional meaning; repeated descriptive statistics do not enable calibrated
performance or universal bug-fix verdicts.

Use the existing locked Python 3.14 environment. All paths resolve from the
caller's directory. Recipe, target and plan JSON files, work, build output and results must be
explicitly selected outside source checkouts. Create a separate artifact
directory first and replace `/absolute/artifacts` consistently below; writing
generated JSON into the engine checkout makes its clean-revision check refuse. Commands never install OS prerequisites, change a
maintainer's checkout, provision a host or upload evidence.

## Start with controlled evidence

From a public engine checkout with its locked environment already installed:

```sh
venv/bin/python scripts/investigation_smoke.py --output /absolute/new/investigation-demo
venv/bin/python recipes.py investigation-verify \
  /absolute/new/investigation-demo/resolved/results/report/investigation.json
```

Open `resolved/results/report/REPORT.md`. The script exercises the public target,
source-plan, build, run, investigate and report commands through exact simulated
Git, Docker and runtime responses. It refuses unmodeled subprocess/network work.
No daemon is built or run. The synthetic source is an inert stand-in, not BIRD
source or a real BIRD bug/fix. The human report's question starts `SIMULATED`.

Three retained cases show a baseline child-daemon crash followed by candidate
completion, an unsuccessful diagnostic collector with candidate `not_run`, and
unavailable memory reported as `null` with reasons. A direct target-override run
and report-only rebuild are also exercised. Simulated diagnostics demonstrate
report behavior and do not establish real source-build, adapter or host
qualification.

## Use an existing immutable target image

Begin with a valid recipe pinned to the clean engine revision you intend to
execute. Export it using the recipe guide, choosing `--expected-outcome target_crash` only when that is the problem being investigated. Both targets
are bound to that same canonical recipe SHA-256:

```sh
venv/bin/python recipes.py target-image /absolute/artifacts/recipe.json \
  --image sha256:BASELINE_64_HEX_IMAGE_ID --label released-baseline \
  --instrumentation unknown --output /absolute/artifacts/baseline-target.json
venv/bin/python recipes.py target-image /absolute/artifacts/recipe.json \
  --image sha256:CANDIDATE_64_HEX_IMAGE_ID --label local-fix \
  --instrumentation debug --output /absolute/artifacts/candidate-target.json
venv/bin/python recipes.py target-validate /absolute/artifacts/candidate-target.json --recipe /absolute/artifacts/recipe.json
venv/bin/python recipes.py check /absolute/artifacts/recipe.json --target /absolute/artifacts/candidate-target.json \
  --workdir /absolute/disk/work/candidate-check \
  --results-dir /absolute/disk/results/candidate-check
```

Replace the conspicuous image placeholders. Tags, implicit latest versions,
other adapters, mismatched recipe bindings and arbitrary extra fields are
refused. The override changes only the target image. `check --target` checks that
selected image rather than requiring the recipe's original baseline target
image to be installed as well. `run --target` uses the same override through the
existing benchmark lifecycle. `plan` and `prepare` continue to describe the base
recipe; they do not acquire a target override. Supply the chosen image separately
through an explicitly authorized path.

Supplied-image source, toolchain, flags, binary hash and reconstructibility stay
unknown. `--instrumentation` accepts `unknown`, `optimized`, `debug`, `asan` and
`profiling`. For supplied images this is a caller declaration, never a verified
binary property. Instrumented and optimized targets remain visibly distinct in
the report; their timings are not normalized or automatically compared.

## Plan a trusted local source build

Source planning is read-only. Select a full local Git checkout at the requested
full commit. The maintained `bird-local/v1` recipe requires BIRD-style
`configure.ac` and `Makefile.in` files, and a toolchain/runtime pair already
present under exact immutable identities:

```sh
venv/bin/python recipes.py target-source-plan /absolute/artifacts/recipe.json \
  --source /absolute/path/to/bird-source --revision FULL_40_HEX_SOURCE_COMMIT \
  --toolchain-image sha256:TOOLCHAIN_64_HEX_IMAGE_ID \
  --runtime-image sha256:RUNTIME_BASE_64_HEX_IMAGE_ID \
  --instrumentation debug --cflags='-O0 -g' \
  --include-dirty --output /absolute/artifacts/candidate-build-plan.json
```

Omit `--include-dirty` for a clean source tree. Explicit dirty inclusion captures
tracked modifications/deletions and nonignored untracked regular files, with
binary patch, snapshot and per-untracked-file hashes. Ignored files are not
included. Requested revision, checkout HEAD and actual commit must agree. The
planner does not check out another revision, edit source, run its configure code
or contact Docker. It refuses source symlinks/submodules, sparse/hidden-index
views, partial/promisor clones and configured Git filters, including inherited
filter configuration. Lazy Git fetching and interactive prompts are disabled.
Source snapshots have a 256 MiB/20,000-file bound. The snapshot identifies the
captured bytes; this is not a transactional lock on an actively edited checkout.

Pristine BIRD release trees containing BSD symlink aliases do not meet this
regular-file-only source contract. The approved
[BIRD 2.19.2 validation](plans/milestone-b-runtime-validation.md#approved-packaging-source-validation-completed--2026-10-26)
used an explicitly reviewed local packaging commit that materialized the two
aliases as byte-identical regular files. It validates that adapted case;
unmodified-release support is not claimed and the guard remains enabled.

The toolchain image must contain Bash, tar, autoreconf, a C compiler, make and all
BIRD development dependencies. The runtime base must contain Bash, iproute2 and
all dynamic libraries required by the selected build, including sanitizer or
profiling libraries when needed. These are manual prerequisites; no image,
package or dependency is downloaded automatically.

Review the generated plan before explicitly building:

```sh
venv/bin/python recipes.py target-build /absolute/artifacts/candidate-build-plan.json \
  --output-dir /absolute/disk/build/candidate-001 --timeout 1200
```

`target-build` is a real source build and needs applicable authorization. It
rechecks the snapshot, exact engine and local bases, discloses the build, and
rechecks the active-measurement guard before mutation. It uses a fixed Dockerfile
on the selected local daemon with BuildKit disabled and no Buildx fallback,
with `--network=none`, `--pull=false`, a new unique tag and a context containing
only the Dockerfile and source archive. The local legacy builder must be available; a missing builder is a failure.
No arbitrary recipe hooks, apt commands,
Git clones or fallback builds are accepted. Trusted source configure/make code
still executes inside the selected builder: reviewing local source/build inputs
is a separate trust boundary from accepting a declarative reproduction recipe.

Compiler flags are also passed as linker flags; declarative configure options
may be supplied with repeated `--configure-flag=--OPTION`. Sanitizer/profiling
modes require corresponding flags. The recipe checks installed BIRD and birdc
executables at its fixed prefix and puts that prefix first in the runtime PATH.
Requested flags are recorded configuration: trusted build code can override
them, so the build log remains important. No verified binary hash or hermetic
reconstruction claim is made.

The new build directory retains `target.json`, source archive/patch, rendered
Dockerfile, plan/disclosure, build log and outcome. A failed or interrupted build
retains partial work and any Docker cache progress. The client process group is
bounded; cancellation cannot guarantee Docker daemon/cache work has stopped.
Existing result images are never retagged. Keep this build evidence; the
investigation packages retain its identity hashes, not an automatic copy of
source archives or patches for redistribution.

## Run one serial investigation

After host suitability, images and any intended build are explicitly resolved:

```sh
venv/bin/python recipes.py investigate /absolute/artifacts/recipe.json \
  --baseline-target /absolute/artifacts/baseline-target.json \
  --candidate-target /absolute/disk/build/candidate-001/target.json \
  --workdir /absolute/disk/work/investigation-001 \
  --results-dir /absolute/disk/results/investigation-001 \
  --diagnostics basic --timeout 300
venv/bin/python recipes.py investigation-verify \
  /absolute/disk/results/investigation-001/report/investigation.json
```

Both target selections are checked before either runs. At most one baseline and
one candidate execute, serially, each with its own new work/result directory and
worker budget. A normal failed experiment, including an evidenced baseline
crash, can be followed by the candidate. A setup/harness failure, interruption or
inconclusive attempt stops further execution and leaves a report distinguishing
the failed attempt from a candidate that never ran. There is no automatic retry.
The outer CLI preserves setup/harness/stop/inconclusive exit codes; exit 0 means
the planned functional pair was recorded, not that a bug is fixed.

The report directory bundles verified copies of both available result packages,
`investigation.json`, `REPORT.md` and a file checksum manifest. It shows exact
source/build/target differences, reproduction witnesses, diagnostics, memory
boundaries, missing evidence and limitations. Its strongest functional outcome
is `baseline_reproduced_candidate_not_reproduced` under the recorded question;
this is not proof of a general bug fix. Unknown identities or failed harnesses
withhold that outcome. Changing the canonical recipe, requested generator or
observer, or their observed image IDs, refuses the pair. Different target
instrumentation/build inputs are recorded, with performance unassessed.

Rebuild a report from existing evidence without runtime access:

```sh
venv/bin/python recipes.py investigation-report \
  --baseline /absolute/results/baseline/result.json \
  --candidate /absolute/results/candidate/result.json \
  --output-dir /absolute/new/report
```

`investigation-report` and `investigation-verify` need no Docker. Verification
checks every bundled package, artifact bytes and recipe/build binding, then
reconstructs the JSON assessment and human report from those records. Changed,
missing, unlisted or unsafe files are refused. Checksums do not authenticate the
publisher or prove that a declared experiment actually ran.

## Diagnostic meanings and limits

`--diagnostics basic` is the default for `run` and `investigate`. It adds optional
Docker stats, fixed BIRD process-list/exit-status capture and bounded final
state/log/cgroup observations before owned cleanup. Its overhead is uncalibrated.
`none` disables those optional probes and daemon-exit wrapper; stage bookkeeping
and the existing owned-container health guard remain. Neither mode qualifies a
performance comparison.

The packages preserve:

- `host.json`: bounded, read-only hostname/kernel/architecture, Python, CPU and
  boot identity before the worker starts, with explicit unavailable fields. It
  reads no environment, persistent machine ID or privileged serials. Host
  differences withhold controlled target-change attribution; the snapshot is
  not hardware or performance qualification.
- `target.json` and `target-selection.json`: base-recipe binding, selected roles,
  source/build identity and declared instrumentation.
- `stages.json`: setup, session establishment, observation, collection, cleanup
  and terminal control stages on the controller's monotonic clock. Setup/session/
  observation are bounded by the worker timeout; final collection and cleanup
  use separate bounded operations. Stages do not redefine convergence clocks.
- `live-diagnostics.json`: a bounded optional diagnostic series with dropped
  sample count, retained sampled peaks, BIRD presence and supported exit witness.
- `diagnostics.json` and bounded role logs: owned IDs/images, filtered container
  states/exits/OOM, explicit capture errors/missing facts and truncation flags.
  Final collection has a 20-second probe budget plus bounded client termination,
  up to 128 owned containers,
  64 KiB per probe and a requested tail of 200 log lines.
- Preserved CSV/event material before final graph/provenance collectors. The
  `raw-samples.csv` file is the retained legacy graph series after its existing
  assurance slicing, not every observed poll. `raw-samples.metadata.json` states
  this scope. `partial-stats.csv` and `raw-events.json` preserve available final
  observations when later collectors fail. Earlier unrecorded observations are
  not reconstructed or invented.

BIRD presence followed by disappearance is a failure observation, not by itself
a crash verdict. A supported nonzero foreground-daemon exit witness establishes
the scoped abnormal exit; missing exit evidence remains inconclusive. A stopped
container's nonzero exit is a separately named container-level witness. Neither
identifies a root cause, signal attribution or a core backtrace. No privileged
journal/core collection runs.

Memory is whole-container cgroup v2 accounting, including file-backed/cache
costs. `peak_bytes` is kernel `memory.peak` over the container lifetime, including
setup. `ending_bytes` is `memory.current` at the final pre-cleanup observation.
`sampled_peak_bytes` is the maximum of achieved optional live observations, not
an unsampled extreme. Daemon-only RSS remains explicitly unavailable; container
memory is not relabeled as process RSS. Missing cgroup reads remain null with
reasons. Lower memory in a candidate is not a leak diagnosis or calibrated
regression conclusion.

Collector/cleanup failures retain supported reproduction evidence and available
work while reporting harness failure. Background health-monitor failures
captured before terminal finalization cannot become a successful worker outcome.
A malformed container inspection
keeps diagnostic observations already collected for other containers and marks
the collection partial. Evidence packaging records unsafe or
unavailable files and socket omissions under the recipe guide. A hard kill,
power loss or unwritable evidence storage can still prevent final packaging.
Review paths, logs and local source/patch information before sharing any
artifacts. No automatic archive upload, deletion or evidence expiry is added.
