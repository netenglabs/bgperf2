# FRR source-to-fix and correctness localization

Use the existing `frr_c` adapter with explicitly selected trusted local FRR
source, BIRD generators and sink observer. The separate
[supplied-image workflow](frr-maintainer-workflow.md) retains its completed
functional qualification; that pair establishes no FRR source-build qualification.
The [implementation record](plans/frr-source-workflow.md) owns delivery progress.

## Start with the maintained modeled workflow

```sh
venv/bin/python scripts/frr_source_smoke.py --output /absolute/new/frr-source-demo
```

Open its `REPORT.md`. All source inspection, revisions, builds, images and worker
observations are **SIMULATED**. Subprocess and socket guards forbid actual Git,
compiler, container, download or network work throughout this walkthrough.
Source-range/handoff tests separately exercise inert real local Git repositories;
they never execute the inert source files.

The public CLI connects source planning/building, reproduction, candidate CI,
bounded minimization and correctness bisection. The modeled baseline preserves
count while returning one wrong prefix; the candidate is explicitly a rollback
to pre-fault source, not an upstream fix. Minimization confirms one peer/two
routes with a fresh original. Source plans are regenerated for that reduced
recipe before searching the same history with `prefix_assertions`. Interrupted
bookkeeping recovers the exact original package without another build or worker.
Fresh good/bad confirmations, report rebuild/relocation and tampered-evidence
refusal complete the workflow. Numeric fixture values are not measurements.

## Freeze trusted source and build inputs

Use the same `target-source-plan` and `target-build` commands documented in the
[investigation guide](investigations.md#plan-a-trusted-local-source-build):

```sh
venv/bin/python recipes.py target-source-plan /absolute/artifacts/recipe.json \
  --source /absolute/maintainer/frr --revision FULL_40_HEX_SOURCE_COMMIT \
  --toolchain-image sha256:TOOLCHAIN_64_HEX_IMAGE_ID \
  --runtime-image sha256:RUNTIME_64_HEX_IMAGE_ID \
  --instrumentation debug --cflags='-O0 -g' \
  --output /absolute/artifacts/baseline-build-plan.json
```

The recipe selects `frr_c`; no additional daemon flag or implicit build is
introduced. Planning is read-only and never executes bootstrap/configure code.
An exact checkout HEAD, regular `configure.ac`, `Makefile.am` and `bootstrap.sh`,
and the existing 256 MiB/20,000-file snapshot limits are required. Explicit
`--include-dirty` records local tracked changes and nonignored untracked files.
Git filters, hidden/sparse index entries, partial clones and source symlinks or
submodules retain their existing refusals. **Pristine FRR trees with tracked
topotest symlinks are not supported by this regular-file source contract.**
Do not remove files or silently materialize links to make a source look pristine.
Any separately selected packaging adaptation needs its own recorded commit,
attribution, exact transformation and review; the original checkout stays intact.

`frr-local/v1` uses the local legacy Docker builder, fixed two-job compilation,
no network, no pulls and no package installation. Immutable selected images
must already contain dependencies; no missing dependency is repaired implicitly.
Builder prerequisites include Bash, tar, coreutils, autoreconf/autotools, C tools,
make, Python and the selected FRR development libraries (including a compatible
libyang). The runtime requires Bash, iproute2, coreutils, the `frr` user/group,
`frrvty` group and all libraries required by the installed binaries. Runtime
base `/etc/frr.old` must be absent. These are prerequisites, not facts established
by offline planning.

The fixed configure inputs are `/usr`, `/usr/lib/frr`, the `/etc` configuration
base and `/var/run/frr` local state, with `frr` daemon user/group and `frrvty`
socket group. The configuration base matches the existing compiled adapter
recipe and [current FRR installation guidance](https://docs.frrouting.org/en/stable-10.1/installation.html).
Newer FRR versions append `frr` to that base; older sources can use the base
directly. The adapter explicitly passes `/etc/frr/bgpd.conf` with `-f`; its
configuration generation/startup is unchanged. Source-version-specific default
file lookup and runtime-directory behavior remain live qualification questions. Caller
configure options cannot override those paths/accounts. Build checks require
installed `bgpd` and `vtysh`; all installed files are copied into the selected
runtime base. Root startup and owned FRR directories support the unchanged
compiled adapter. Optimized declarations refuse explicit gcov configuration.
Compiler/linker flags are requested controls; trusted source can override them.
Binary hash and bit-reconstructibility remain unestablished, as for BIRD builds.

After separate execution approval, one explicit command builds one source plan:

```sh
venv/bin/python recipes.py target-build /absolute/artifacts/baseline-build-plan.json \
  --output-dir /absolute/new/baseline-build --timeout 1200
```

It returns `target.json` with adapter, exact recipe/source bindings, requested
and observed base image identities, Dockerfile/log hashes and observed built
image ID. Build work and partial failure logs remain retained. Stopping the
client cannot prove Docker daemon-side cache work ended. No automatic retry,
retagging or broad cleanup occurs. Keep build directories: result reports bind
their identities but do not automatically redistribute source archives.

## Investigate, reduce and localize

Select baseline and candidate targets returned by separately selected builds.
Use `run --target`, `investigate --observer-prefixes --diagnostics basic`,
`investigation-check --side candidate`, and offline report verification/rebuild
as in the [investigation guide](investigations.md). Both targets must match the
same exact recipe and adapter. Count and prefix identity retain separate meanings.

The [minimizer](minimization.md) remains image-only. Explicitly export a new recipe
using the built failing target's returned immutable image. Preserve the original
source-bound recipe, target and build evidence alongside that exported recipe;
the image-only recipe does not itself claim source provenance. Minimize one
selected assertion, retaining a fresh baseline, charged budget and confirmation.
After reduction, create **new source plans bound to the reduced recipe**. The
old source-bound target must fail validation against that recipe; do not edit
its hashes to make it appear reusable.

[Source-range preparation](source-range.md) and the
[maintainer handoff](maintainer-handoff.md) accept FRR plans through the existing
commands. Use a complete consecutive first-parent chain, fixed build controls
and either `assertions` or `prefix_assertions`. The latter selects the bounded
final prefix snapshot on every trial/confirmation. Good/bad endpoint labels
declare expectations; only fresh original witnesses establish classifications.
The [bisection guide](bisection.md) owns cache, monotonicity, ambiguous/skipped
outcomes, finite budgets, recovery and fresh boundary-confirmation semantics.
Minimization does not prove a global minimum and bisection does not establish
an upstream defect, a general fix or behavior outside the selected recipe.

FRR `target_crash` and thread controls remain unsupported. Backgrounded bgpd
startup supplies no BIRD foreground-exit witness; container health remains a
bounded snapshot. Performance policy stays disabled, formal calibration deferred
and unrelated upstream investigation paused. No command in this guide authorizes
real execution, acquisition, evidence transfer, push or publication. The
[source-build functional record](plans/frr-source-runtime-validation.md)
records the completed retained-image pair and its source/base limitations.
The [controlled local regression case](plans/frr-correctness-localization-validation.md)
exercises changed-revision public-run evidence/reporting, native image-only
minimization and source-bound external-trial prefix bisection. Its local fault,
rollback, finite budgets and fresh confirmations establish only the recorded
functional scope; combined-controller execution and broader source support
remain separate qualifications.
