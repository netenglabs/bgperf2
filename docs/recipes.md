# Portable recipe and result contracts

The recipe interface exports, validates, inspects and plans one existing batch
cell offline. Its explicit `check` command reports observed local prerequisites
without changing the host or acquiring images. `prepare` reports a local image
acquisition plan; explicit `prepare --pull` may acquire selected missing
repository digests. Explicit `run` executes the selected supported recipe and
returns a verified local result package. Existing
`bench`, `batch`, CSV, event and provenance formats retain their current behavior.

For baseline/local-fix target overrides, trusted source builds, bounded diagnostics
and verified investigation reports, follow the [local-fix guide](investigations.md).
The original recipe remains frozen while an external target identity selects
only its target image.

Use the locked Python environment described in [the environment guide](python-environment.md).
The standalone entry point is `venv/bin/python recipes.py`; importing `recipes`
or `batch_cells` does not initialize the engine or Docker client. Paths supplied
to this entry point resolve from the caller's working directory. Keep generated
recipe/target/plan JSON outside the engine checkout so its clean-revision check
remains satisfied; create the separate artifact directory before exporting.

## Export one cell

The initial supported workload is synthetic IPv4 with a BIRD target, BIRD
generator and sink observer, with disjoint prefixes and no policy filter or
additional receivers. Scenario files, Mako, MRT, hooks, local build instructions,
other adapters and workload extensions are refused. These limits keep downloaded
recipes declarative and prevent unsupported fields from silently changing what
runs.

An optional test-level `pin` uses the existing `bench` CPU layout syntax:

```yaml
pin: target=0,monitor=1,testers=2-3
```

All three roles must be named, nonempty and disjoint. `monitor` and `testers`
are the CLI names for the recipe's observer and generator. Receivers remain
unsupported. Portable layouts are limited to 4,096 characters and CPU IDs
0–4095 with at most four decimal digits per endpoint; oversized ranges are
refused before expansion. These are declarative parsing bounds, not hardware
or workload-capacity estimates.

Pinning is opt-in. Omitting it preserves existing recipe bytes and identities.
When present, its canonical layout is included in `resolved.pin` and the legacy
cell identity, while the original source text stays intact. Equivalent layouts
share a cell key; changing the original source spelling still changes the full
recipe digest. Older engine revisions refuse this source field rather than
silently ignoring it.

`plan` reports the layout without probing the host. `check` refuses pinned
recipes when their CPU IDs are offline or the online-CPU snapshot is unreadable;
it reads host sysfs rather than the controller's affinity. Explicit `run` passes
the layout to the existing lifecycle, whose container cpuset/readback guards
apply. This does not establish physical-core/SMT separation, reserve the host,
pin the controller or kernel work, or qualify performance. Inspect the actual
host topology before selecting CPU IDs.

Export requires a test name and one cell key. The key is the existing
`batch --list-cells` key; a recipe never implicitly selects a whole matrix.
Shuffled definitions must state an integer seed. Source definitions and original
target fields are preserved, while normalized values and legacy identity are
recorded separately.

The [public example batch](../examples/recipes/synthetic-ipv4.yaml) has two cells.
The [checked-in recipe](../examples/recipes/synthetic-ipv4.recipe.json) selects
one. Its conspicuous fixture image digests are synthetic: they identify no
downloadable images and must be replaced with actual immutable image identities
before using `prepare --pull` or `run`.
The fixture declares the historical planning baseline engine revision. Phase 0
validates identity syntax and consistency; it does not probe Git objects, image
existence, registries or artifact availability.

```sh
venv/bin/python recipes.py inspect examples/recipes/synthetic-ipv4.recipe.json
venv/bin/python recipes.py validate examples/recipes/synthetic-ipv4.recipe.json
venv/bin/python recipes.py export \
  --batch examples/recipes/synthetic-ipv4.yaml --test synthetic-ipv4 \
  --cell f94a3878b2dad49e --engine-revision FULL_40_HEX_COMMIT \
  --target-image sha256:TARGET_64_HEX_IMAGE_ID \
  --generator-image sha256:GENERATOR_64_HEX_IMAGE_ID \
  --observer-image sha256:OBSERVER_64_HEX_IMAGE_ID \
  --question 'Does the target complete this synthetic workload?' \
  --output /absolute/artifacts/recipe.json
```

Replace every uppercase placeholder with a real value. Role images accept a full
`sha256:` image ID or a repository digest such as
`registry.example/namespace/image@sha256:<64 hex digits>`. Tags alone, including
release tags, are insufficient. The engine revision must be a full commit hash.
An immutable image identity records the requested binary; it does not prove that
unlocked source, toolchains or base images can reconstruct that binary.

`export` writes JSON to stdout when no output file is selected. A supplied output
file must not already exist; export preserves earlier files. All phase 0 commands
exit 0 for a valid contract and 2 for input, selection, validation or write
refusal. These are contract-operation exits, not runtime experiment verdicts.

## Plan and check prerequisites

Use this read-only path before explicit execution. Use the same hashed bootstrap as the
rest of the engine; there is no separate recipe installer. On an idle development
host, create the locked environment using `python3.14 scripts/bootstrap.py`, then:

```sh
venv/bin/python recipes.py plan examples/recipes/synthetic-ipv4.recipe.json
venv/bin/python recipes.py check /absolute/artifacts/recipe.json \
  --workdir /var/tmp/bgperf-attempt-001 \
  --results-dir /var/tmp/bgperf-results-001
```

`plan` validates the recipe and emits an offline prerequisite report. It does not
probe executables, Git, Docker, the filesystem or the network. `inspect` retains
its existing contract summary. `check` validates first, then takes a bounded,
read-only snapshot of Linux/Python, required tools (`docker`, `mpstat`, `free`),
the exact clean engine revision and the existing hashed Python environment via
`scripts/bootstrap.py --check`. That bootstrap check retains its idle measurement
guard; `check` never installs dependencies or repairs the environment.
Engine inspection requires visible tracked index entries rather than
assume-unchanged/skip-worktree views, and Git replacement objects cannot redefine
the pinned revision. Hidden modifications cannot be qualified as clean source.

Only a local Unix-socket Docker endpoint is supported. Remote endpoints are
refused before Docker or bootstrap is contacted. Accepted endpoint probes use
an explicit host and an environment isolated from Docker context overrides.
Only the three selected immutable role identities are inspected. The report
records the actual image ID, repository digests and available metadata; a missing
image or identity mismatch is a refusal. A tag alongside an immutable pin cannot
substitute for the pin. No images are pulled, built, imported, tagged or run.

Both destination paths must be absolute and new, distinct and nonnested, outside
the engine checkout, with writable and searchable nearest existing disk-backed
ancestors.
Resolved paths are checked so symlinks cannot bypass isolation; RAM-backed
destinations are refused. The command never creates either directory or modifies
existing files. It records available memory, CPU count and destination capacity
as observations, without deriving workload resource estimates.

Reports use `bgperf2/prerequisites/v1alpha1`. Each `checks` entry has a `name`,
`status` (`pass`, `refused` or `unknown`), `reason` and `details`. The top-level
`status` is `checks_passed` or `refused`; every prerequisite report states
`execution: not_requested` and `comparison: not_assessed`. `plan` exits 0 for
a valid recipe. `check` exits 2 and emits the JSON refusal report when an observed
prerequisite fails; satisfied observed checks exit 0. Malformed recipes exit 2
before any probe.

`checks_passed` describes only the listed observations at that instant. Workload
resource estimates, foreign CPU qualification, runtime capabilities, hardware
suitability and source/build reconstruction remain unknown or unassessed. It is
not a readiness or performance-comparison verdict. The supported synthetic
BIRD/BIRD/sink functional workflow and early-timeout path have passed separately
authorized real checks; see the [validation record and limits](plans/milestone-a-runtime-validation.md).
Those checks establish neither hardware suitability nor performance comparability.
Explicit execution is described below.
The public fixture has synthetic image pins and a historical engine revision;
its successful offline plan does not imply that it can pass a local check.

## Prepare selected images

Use the same locked Python bootstrap above on an idle development host. Review
the recipe's selected digest references and the publisher you trust before
authorizing acquisition:

```sh
venv/bin/python recipes.py prepare /absolute/artifacts/recipe.json
venv/bin/python recipes.py prepare /absolute/artifacts/recipe.json --pull
```

Unlike the fully offline `plan`, `prepare` probes the local prerequisites and
inspects all selected immutable images to produce a local acquisition plan.
Its default performs no pull. Existing exact images are kept; shared role
references are inspected and acquired once, with all roles retained in the report.
Only `--pull` permits Docker to pull missing selected `repository@sha256:...`
references. The complete acquisition plan is printed to stderr and flushed
before the first pull; the final JSON report is written to stdout. The library
entry point requires an `emit_disclosure` callback whenever a pull is needed.

A bare `sha256:...` image ID can be reused if present locally. If missing, it
cannot be pulled: the ID supplies no repository name. That blocks every pull in
the request. Supply that exact image separately or obtain a recipe with a real
repository digest; preparation never infers a repository, substitutes a tag,
builds images, or invokes the legacy `bgperf2.py prepare` command.

Preparation checks the exact clean engine revision, Linux, tools, local Docker
endpoint and existing hashed environment with the same active measurement
guard as `check`. All selected references are inspected before acquisition.
Only a typed Docker inspect failure naming the exact missing image counts as
absence; permissions, timeouts, malformed responses and identity mismatches
block all pulls. The guard runs again after disclosure before every pull.
Pulls have a separate bounded timeout from the 15-second read-only probes.
Timeout or interruption stops and reaps the owned Docker CLI process group;
it cannot guarantee cancellation of the Docker daemon's download or cache work.
Ctrl-C and SIGTERM propagate with exits 130 and 143 respectively, without a
guaranteed final JSON report. Ordinary acquisition failures return a JSON refusal
report recording partial progress.
Each successful pull is reinspected against the selected immutable pin before
continuing. A failure stops pending acquisitions. Images already acquired stay
cached and the report records partial progress; no rollback or deletion occurs.

Reports use `bgperf2/preparation/v1alpha1`, with `status` equal to `planned`,
`prepared` or `refused`. Each deduplicated `items` entry retains its exact
`requested` reference and `roles`, its `action` (`keep`, `pull` or `unavailable`)
and its `state` (`available`, `missing`, `acquired`, `failed` or `skipped`).
Observed image identity, repository digests, platform and local size are recorded
when available. Download and incremental storage sizes remain unknown;
Docker's local `Size` is not a download size. Source, build and binary provenance
also remain unverified. Digest pinning identifies selected content and does not
establish publisher trust or prove a reconstructible build.

The CLI exits 0 for `planned` or `prepared`, and 2 for `refused`. Malformed
recipes are refused before probing or mutation. `execution: not_requested`
and `comparison: not_assessed` remain explicit. Preparation does not start
containers, change runtime networks or volumes, collect measurements, execute a
recipe or satisfy full phase 1 acceptance. The public fixture's synthetic image
pins are examples, not downloadable acquisition targets.

## Run and return one attempt

After the OS prerequisites, locked environment and selected exact images are
available, use one clean checkout at the recipe's full engine revision. Running
a recipe executes containers with the current user's Docker authority. Read the
recipe, trust the selected images and choose an otherwise idle suitable Linux
host before execution. This initial adapter is synthetic IPv4 BIRD/BIRD/sink.
The public fixture's fake image pins cannot run.

```sh
venv/bin/python recipes.py validate /absolute/artifacts/recipe.json
venv/bin/python recipes.py plan /absolute/artifacts/recipe.json
venv/bin/python recipes.py prepare /absolute/artifacts/recipe.json
# Only if acquisition is intended and approved:
venv/bin/python recipes.py prepare /absolute/artifacts/recipe.json --pull
venv/bin/python recipes.py check /absolute/artifacts/recipe.json \
  --workdir /absolute/disk/work/attempt-001 \
  --results-dir /absolute/disk/results/attempt-001
# Explicit experiment execution; no pulls or builds occur here:
venv/bin/python recipes.py run /absolute/artifacts/recipe.json --timeout 300 \
  --workdir /absolute/disk/work/attempt-001 \
  --results-dir /absolute/disk/results/attempt-001
venv/bin/python recipes.py result-verify /absolute/disk/results/attempt-001/result.json
```

The parent directories must already be suitable writable disk storage; both
attempt destinations must be new, absolute, distinct, nonnested and outside the
checkout. A refusal returns an actionable JSON prerequisite report on stdout and
exit 2 without starting a worker. Choose new paths for every retry; earlier work
and evidence are retained. Check the command's exit status and `status` rather
than treating the existence of `result.json` as success.

`run --target TARGET.json` binds a strict external target identity to this
recipe. Optional `--diagnostics basic` (default) or `none` selects the supported
diagnostic probes; see the investigation guide for their overhead and accounting.
Additional artifacts are recorded using the existing result envelope.

The [comparison guide](comparisons.md) adds separately exported, recipe-bound
observable assertions and repeated target comparisons. It retains these recipe
and result envelopes, names exact count agreement separately from convergence,
and leaves calibrated performance policy disabled. New executions retain
`work/execution-budget.json` with the finite worker timeout and observed worker
elapsed interval, excluding final diagnostics and cleanup. Old evidence without
this record cannot establish deadline-dependent assertion success.

The controller holds an advisory lock across checks, execution and cleanup for
cooperating recipe attempts by the same user. The existing active-measurement
guard still runs. This does not lock out arbitrary Docker users or qualify host
idleness, resource sufficiency or hardware. Capacity requirements remain unknown.
The worker runs the existing engine lifecycle with isolated container/network
names and the selected immutable target, generator and observer images. It does
not invoke the engine's broad image-preparation or prior-container cleanup paths.
Only resources bearing this attempt's ownership label are cleaned, by inspected
IDs. Work directories are preserved, including failed and interrupted work.
If inspection or removal of one resource fails, cleanup records that failure
and continues checking the remaining owned resources. Foreign or uncertain
resources are retained; any cleanup error still makes the attempt a harness
failure.

`--timeout` is a finite positive wall-clock worker budget, covering setup and
observation (default 300 seconds). It is separate from the engine's convergence
rules and from bounded prerequisite/cleanup probes. Expiry stops the worker
process group and yields `inconclusive` (exit 5). A worker observed to finish
after the selected budget is also inconclusive, even when its process returned
successfully. Ctrl-C or SIGTERM during the
worker yields `interrupted` (130 or 143). Cleanup failures yield `harness_failed`
(exit 3) with details, retaining evidence. A hard kill, disk failure or power loss
can prevent packaging or cleanup; there is no automatic retry or recovery claim.

An existing engine stats row determines `completed` (0) or
`experiment_failed` (4); a missing row is inconclusive and worker exceptions are
harness failures. Bounded diagnostic collection/cleanup failures report harness
failure while retaining available evidence and any supported reproduction
witness. A completion witness can decide the `experiment_completed`
reproduction predicate. A completed run with `target_crash` intent is
`not_reproduced`; a failed run without a specific supported crash witness remains
inconclusive. No failed setup or missing measurement becomes a reproduced bug.

The results directory contains `result.json`, `recipe.json`, `SUMMARY.txt` and a
`work/` snapshot of available configurations, raw artifacts and controller logs.
Each available file is checksummed; unavailable required artifact kinds and
collection errors are explicit. Runtime Unix-domain sockets, such as BIRD control
sockets, are omitted without opening or contacting them; their paths, types and
reasons are recorded in checksummed `collection-omissions.json`. Other unsafe or
unreadable artifacts remain collection failures. Verification checks hashes, refuses unlisted or
unsafe files, and checks the canonical recipe binding. It does not authenticate a
publisher or re-evaluate convergence.
Review the package for local paths and other information before returning it to
a maintainer. No upload, publication, archive creation or automatic deletion runs.

## Exercise the workflow without Docker

From a fresh public checkout with the locked environment already installed:

```sh
venv/bin/python scripts/recipe_smoke.py --output /absolute/new/simulated-attempt
venv/bin/python recipes.py result-verify /absolute/new/simulated-attempt/results/result.json
```

This maintained smoke entry point exports one cell and walks through validation,
inspection, planning, checks, selected preparation, execution and verification
using explicitly simulated prerequisites and a fake runtime. It refuses real
subprocess and network operations inside the modeled runtime path. Reports and
a return package remain at the requested new path. Every runtime artifact is
marked simulated; no performance numbers or hardware qualification are produced.
The fake smoke is usable on a developer machine and does not establish that the
real adapter, image publisher or host is qualified.

## Recipe envelope

The schema name is `bgperf2/recipe/v1alpha1`. Unknown fields are refused at every
supported level. Validation re-derives the selected cell from the embedded source
and checks the source checksum, normalized values and legacy identity.

| Field | Meaning |
|---|---|
| `engine.revision` | Requested immutable engine revision |
| `source` | Batch format, exact source text, SHA-256 and original selected target |
| `selection` | Explicit test name and selected cell key |
| `legacy` | Existing batch cell ID and key, retaining compatibility omission rules |
| `resolved` | Explicit normalized workload and target defaults |
| `roles` | Target, generator and observer adapters and immutable images |
| `inputs` | Empty for this synthetic workload; external inputs are unsupported |
| `seeds` | Batch order and stated seed; no synthetic workload seed is currently used |
| `resources` | CPU, memory and storage requirements, currently unknown (`null`) |
| `completion` | Existing engine convergence contract and its engine revision |
| `reproduction` | The question and expected outcome, independently of comparison suitability |

Unknown resources remain unknown; validation is not host qualification. The
completion contract names the existing convergence semantics without changing
thresholds or timing boundaries. `experiment_completed` and `target_crash` are
supported descriptions of reproduction intent. Phase 0 does not evaluate them.
A recipe can describe a crash reproducer without establishing that timings on
different hardware are comparable.

## Result envelope

The separate result schema is `bgperf2/result/v1alpha1`. Validate a supplied
manifest with:

```sh
venv/bin/python recipes.py result-validate result.json
```

The [public result fixture](../examples/recipes/synthetic-ipv4.result.json)
references the example recipe's canonical JSON SHA-256. It declares no executed
attempt or collected evidence: every artifact is explicitly missing, reproduction
is `not_evaluated` and comparison is `not_assessed`. Validate it with
`venv/bin/python recipes.py result-validate examples/recipes/synthetic-ipv4.result.json`.

The envelope references existing event, provenance, sample, configuration and
log artifacts. It does not replace or reinterpret their contents. Available
artifacts carry checksums; unavailable evidence carries an explicit reason.
`run` emits this envelope around existing artifacts; it introduces no new
benchmark measurement definition. `result-validate` checks declarations only;
`result-verify` checks the package bytes and bundled recipe identity.

| Field | Meaning |
|---|---|
| `recipe_sha256` | SHA-256 of the recipe's canonical JSON bytes, defined below |
| `engine.revision` | Recorded full engine revision |
| `attempt.id` | Nonempty attempt identifier |
| `status`, `exit_code` | Experiment status and its declared runtime exit |
| `reproduction` | Outcome, reason and paths to supporting present artifacts |
| `comparison` | `not_assessed` qualification with an explicit reason |
| `artifacts` | Present or missing references for each required artifact kind |

Canonical recipe JSON uses Python JSON encoding with `ensure_ascii=True`, sorted
object keys and compact comma/colon separators, without a trailing newline.
Non-ASCII characters use ASCII `\u` escapes; astral characters use UTF-16 surrogate
pairs (for example, `🚀` becomes `\ud83d\ude80`). Whitespace inside strings,
including embedded source text, remains unchanged in value and is escaped by
JSON as needed. Encode that canonical text as UTF-8 and hash those bytes. Pretty
printing and file-ending newlines do not enter the digest.

Each artifact has `kind`, `path`, `sha256`, `availability` and `reason`. A present
artifact requires a unique relative POSIX path and SHA-256, with a null reason.
Absolute paths and parent-directory traversal are refused. Missing artifacts
require a reason and null checksum; their path may be null. The five required
kinds are `events`, `provenance`, `samples`, `configuration` and `log`; `other`
permits additional references. Decided reproduction outcomes require supporting
present artifact references. Validation checks declarations without opening the
referenced files or recomputing their checksums.

Experiment status and reproduction outcome answer separate questions:

| Experiment status | Declared runtime exit | Meaning |
|---|---|---|
| `setup_refused` | 2 | Prerequisites or setup requirements were not satisfied |
| `harness_failed` | 3 | The measurement harness failed |
| `experiment_failed` | 4 | The experiment did not complete successfully |
| `interrupted` | 130 or 143 | An interruption stopped the attempt |
| `inconclusive` | 5 | Available evidence cannot establish experiment completion |
| `completed` | 0 | The experiment completed under its existing contract |

Reproduction outcome is independently `reproduced`, `not_reproduced`,
`inconclusive` or `not_evaluated`. A target crash may yield
`experiment_failed` and `reproduced` together. A completed experiment can fail to
reproduce a reported problem. Performance comparison remains `not_assessed`;
the envelope supplies no automatic performance qualification or regression rule.
A setup refusal cannot decide reproduction and therefore requires `inconclusive`
or `not_evaluated`. A harness failure may follow already collected evidence and
does not automatically erase a supported reproduction outcome.

The recipe controller maps its bounded worker outcome to these statuses. Legacy
`bench` and `batch` exit semantics remain unchanged.
