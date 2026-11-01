# Prepare a local revision range for deterministic bisection

Use `recipe_source_range.py` to prepare an existing local source repository for
the [deterministic bisection workflow](bisection.md). Select full good and bad
commit IDs and one fixed [recipe](recipes.md). Preparation copies local Git
objects once into an independent bare repository, creates detached checkouts
inside a new output directory, and freezes a build plan for every consecutive
first-parent revision. It produces the existing versioned bisection plan.

No source configure script, build, image acquisition, hook, submodule operation
or worker runs. Preparation does not initialize or execute a search. The good
and bad endpoint names declare intended outcomes; they are not observations.
Performance predicates remain unsupported and performance policy stays disabled.

Use the existing [locked environment](python-environment.md) on a development
host where no measurement is active. Choose an existing absolute source checkout
and a new absolute output directory whose parent exists, outside both source
and engine checkouts. Replace all uppercase placeholders:

```sh
venv/bin/python recipe_source_range.py prepare \
  --recipe /absolute/artifacts/recipe.json \
  --source /absolute/path/to/local-bird-checkout \
  --good FULL_40_HEX_GOOD_COMMIT --bad FULL_40_HEX_BAD_COMMIT \
  --toolchain-image sha256:TOOLCHAIN_64_HEX_IMAGE_ID \
  --runtime-image sha256:RUNTIME_64_HEX_IMAGE_ID \
  --instrumentation debug --cflags='-O0 -g' \
  --predicate assertions --max-trials 12 \
  --worker-timeout 120 --build-timeout 1200 \
  --output /absolute/new/source-range
venv/bin/python recipe_source_range.py verify \
  /absolute/new/source-range/source-range.json
```

Use `--predicate target_crash` with a recipe whose expected outcome is
`target_crash`. `assertions` requires `experiment_completed`. Build flags,
instrumentation, optional repeated `--configure-flag=--OPTION`, immutable
toolchain/runtime identities, predicate and trial/time budgets are fixed for
the complete range. Image pins are declarations: preparation does not inspect
Docker, prove that images exist, or select replacement images.

Open the generated `REPORT.md` and inspect these records:

| Path | Meaning |
| --- | --- |
| `source-range.json` | Frozen recipe, endpoints, controls, candidate paths/hashes, resource accounting and original-repository preservation signatures. |
| `bisection-plan.json` | Existing bisection contract with all selected raw commit proofs and per-revision build plans. |
| `repository.git/` | One independent local bare clone; object files are copied with `--no-hardlinks`, without alternates or registration in the original repository. |
| `checkouts/000-FULLSHA/` | Owned detached worktrees for selected revisions. |
| `build-plans/000-FULLSHA.json` | Existing strict `bird-local/v1` plans, with absolute checkout paths and source snapshot hashes. |
| `git-commands.json` | Bounded preparation Git operations and output hashes; existing source-planner probes retain their documented implementation. |
| `progress/`, `outcome-started.json`, `outcome.json` | Retained progress and final prepared/failed outcome. Failure keeps available clone, checkouts and plans. |

After reviewing the preparation, initialize a separate new search session:

```sh
venv/bin/python recipe_bisection.py init \
  /absolute/new/source-range/bisection-plan.json \
  --session /absolute/new/search-session
venv/bin/python recipe_bisection.py status /absolute/new/search-session
```

Follow the bisection guide for later explicit execution or trial import.
Preparation grants no build or worker authorization. For a local dirty fix,
use the [source investigation guide](investigations.md) to create a separate
explicit `--include-dirty` candidate plan. The range represents committed
revisions; dirty tracked edits and untracked notes in the original checkout are
preserved and excluded from its generated clean plans.

Preparation accepts 2–256 inclusive consecutive first-parent revisions, with
the selected good revision older than the bad revision on that chain. The
original source must be a full standalone checkout with a real `.git`
directory. Linked worktrees, bare source repositories and root `commondir`
redirection require manual preparation. Existing source-planner restrictions
remain: every selected revision needs regular `configure.ac` and `Makefile.in`
files, no source symlink/submodule, and at most 256 MiB/20,000 source files.
Pristine BIRD trees containing symlink aliases remain unsupported; preparation
does not dereference or replace those aliases.

Effective local, inherited and included Git filters are refused before any
status/diff or checkout operation. Partial/promisor, shallow, alternate-object,
replacement-ref, grafted, sparse and hidden-index source views are refused.
Git metadata/object symlinks and special endpoints are refused. Preparation
does not fetch missing objects. The fixed local clone is the sole operation
that allows the local file protocol; its source is an absolute validated local
directory and `--local` is mandatory. Other transports are disabled. Owned Git
operations use empty hooks/templates, ignore global/system configuration,
disable lazy fetching, replacement objects, submodule recursion, fsmonitor and
automatic maintenance, and never register worktrees in the original repository.

Resource bounds include at most 1 GiB of local object files, 200,000 object or
metadata entries, 64 MiB of other Git metadata, and at most 1 GiB/200,000 entries
across materialized checkouts. Selected tree/blob identities are checked by
recomputing Git object hashes on the original, the independent clone before
checkout, and again during verification. Reading an object with `cat-file`
alone does not authenticate its stored bytes. The selected raw tree metadata
has a 64 MiB bound. Individual preparation Git commands have a 30-second budget
and 64 MiB output bound; selected blob hashing permits up to the existing
256 MiB source limit. Owned command groups stop on timeout or oversized output.

Native checkout conversion needs a conservative disk budget. Owned Git ignores
external attributes and fixes automatic line-ending defaults; committed CRLF
attributes remain supported with a two-times source-byte allowance. Committed
`working-tree-encoding` or `ident` declarations require manual preparation.
Actual checkout sizes are checked before accepting plans. Free disk is an
observed preflight value, not a reservation or a guarantee against concurrent
disk use. A resource or later source-plan failure retains partial owned output;
choose another fresh destination for a separately reviewed preparation.

Verification checks the reciprocal `.git`, `commondir` and `gitdir` ownership
chain before invoking Git on a checkout, validates raw selected object hashes,
reconstructs strict source plans, checks the frozen bisection contract, and
rebuilds the expected human report. It rejects altered or missing artifacts and
malformed contracts. It reads the owned clone/checkouts and never reopens the
original source path. It can therefore verify after the original is moved or
removed. Keep the preparation itself at its selected path: absolute source roots
inside the build plans make relocation an explicit re-preparation operation.
Portable execution evidence remains the separate result/report contract.

Before/after signatures cover original HEAD, refs, index, effective configuration,
status and tracked diff. They record a bounded consistency check, not an atomic
lock or authentication of an actively changing repository. Keep the source
stable during preparation. Local checksums and object hashes establish neither
publisher trust, an actual experiment, nor reproducible binaries.
