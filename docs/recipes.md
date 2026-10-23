# Portable recipe and result contracts

The recipe interface exports, validates, inspects and plans one existing batch
cell offline. Its explicit `check` command reports observed local prerequisites
without changing the host or acquiring images. It does not prepare images or
execute experiments. Existing
`bench`, `batch`, CSV, event and provenance formats retain their current behavior.

Use the locked Python environment described in [the environment guide](python-environment.md).
The standalone entry point is `venv/bin/python recipes.py`; importing `recipes`
or `batch_cells` does not initialize the engine or Docker client. Paths supplied
to this entry point resolve from the caller's working directory.

## Export one cell

The initial supported workload is synthetic IPv4 with a BIRD target, BIRD
generator and sink observer, with disjoint prefixes and no policy filter or
additional receivers. Scenario files, Mako, MRT, hooks, local build instructions,
other adapters and workload extensions are refused. These limits keep downloaded
recipes declarative and prevent unsupported fields from silently changing what
runs.

Export requires a test name and one cell key. The key is the existing
`batch --list-cells` key; a recipe never implicitly selects a whole matrix.
Shuffled definitions must state an integer seed. Source definitions and original
target fields are preserved, while normalized values and legacy identity are
recorded separately.

The [public example batch](../examples/recipes/synthetic-ipv4.yaml) has two cells.
The [checked-in recipe](../examples/recipes/synthetic-ipv4.recipe.json) selects
one. Its conspicuous fixture image digests are synthetic: they identify no
downloadable images and must be replaced with actual immutable image identities
for a future execution workflow.
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
  --output recipe.json
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

Phase 1a is a partial newcomer workflow. Use the same hashed bootstrap as the
rest of the engine; there is no separate recipe installer. On an idle development
host, create the locked environment using `python3.14 scripts/bootstrap.py`, then:

```sh
venv/bin/python recipes.py plan examples/recipes/synthetic-ipv4.recipe.json
venv/bin/python recipes.py check recipe.json \
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
`status` is `checks_passed` or `refused`; every report states
`execution: not_implemented` and `comparison: not_assessed`. `plan` exits 0 for
a valid recipe. `check` exits 2 and emits the JSON refusal report when an observed
prerequisite fails; satisfied observed checks exit 0. Malformed recipes exit 2
before any probe.

`checks_passed` describes only the listed observations at that instant. Workload
resource estimates, foreign CPU qualification, runtime capabilities, hardware
suitability and source/build reconstruction remain unknown or unassessed. It is
not a readiness or performance-comparison verdict. Preparation and recipe
execution remain unimplemented, so phase 1 acceptance has not been reached.
The public fixture has synthetic image pins and a historical engine revision;
its successful offline plan does not imply that it can pass a local check.

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
Phase 0 validates this contract; the current run lifecycle does not automatically
emit it, and no new benchmark result definition is introduced.

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

Future runtime support must define and test mappings to these statuses. The
phase 0 CLI does not claim that existing benchmark exit codes implement them.
