# Reproducible Python environment

The supported locked environment is CPython 3.14 on Linux (tested on x86-64).
Install that interpreter with venv/ensurepip support using the host's normal
system setup. The bootstrap refuses another Python minor before creating or
changing an environment. It does not install Python, system packages or Docker.
Run only on an idle development host, never during a measurement.

From a fresh checkout:

```sh
python3.14 scripts/bootstrap.py
```

The script resolves paths from its own checkout, creates an isolated `venv`,
installs every runtime/test dependency from `requirements.lock` with
`pip install --require-hashes --only-binary=:all:`, checks `pip freeze --all --exclude pip` for an
exact normalized name/version match, runs `pip check`, and runs the Docker-free
suite. Only wheels are accepted, so source builds cannot introduce unlocked
build dependencies. A platform without the locked wheels fails explicitly.
The venv's seed pip is installation tooling and is explicitly excluded from the comparison;
pip also hides the `argparse` backport installed by nsenter; the script checks
all distribution metadata as well, so this package and any extras remain checked.
pip-tools is used separately and is not installed in the application environment.
The locks are resolved for Linux/Python 3.14 and contain no environment markers;
unsupported requirement syntax is refused rather than silently ignored.
Hashes cover accepted distribution files; the lock does not pin the OS,
interpreter patch release, container images or historical measurement environments.

An existing isolated Python 3.14 venv can be reused if it already matches the
lock. Drift or extra packages are refused before installation changes it. Move an old or contaminated `venv` aside before bootstrapping
again. The script never deletes it. Inspect an existing install without
installing or running tests:

```sh
python3.14 scripts/bootstrap.py --check
```

## Updating dependencies

Edit `test-requirements.txt` (and, for the engine, its included
`pip-requirements.txt`); these remain the human-edited dependency sources.
Generate the lock on Python 3.14, from this repository root, in a separate tool
environment:

```sh
python3.14 -m venv /tmp/bgperf-lock-tools
/tmp/bgperf-lock-tools/bin/python -m pip install pip-tools==7.6.2
/tmp/bgperf-lock-tools/bin/pip-compile --generate-hashes --allow-unsafe \
  --strip-extras --no-emit-index-url --no-emit-trusted-host --no-header \
  --pip-args='--only-binary=:all:' --output-file requirements.lock \
  test-requirements.txt
```

Without `--upgrade`, pip-compile retains existing transitive pins where possible.
Use `--upgrade-package NAME` for a deliberate transitive update. Review the lock,
bootstrap a fresh environment, run the suite, and commit the source and lock
together. Do not hand-edit hashes or generate a replacement with `pip freeze`.
Do not commit private index URLs or credentials. Package downloads need network
access, or a separately supplied cache of the matching wheels.

## Local Git quality gates

The guard requires readable Linux procfs and a reachable local Docker daemon,
even though the Python suite itself does not use Docker.

If Docker inspection fails, the guard retains the last 2,000 characters of its
diagnostic and stops before installation or tests. A socket permission denial
can mean the current execution sandbox cannot reach Docker even when host-side
commands work. For a sandboxed coding agent, request approved host execution
for the complete Docker-dependent bootstrap/check/hook command, including its
child processes. Check the reported cause first: an unavailable daemon and a
permission denial require different remedies. Neither a refusal nor a generic
nonzero exit establishes host load or a broken Python environment. Keep the
guard enabled and retain failed check reports; no automatic retry or repair
is performed.

Bootstrap enables this checkout's tracked `.githooks/`. `--check` only verifies
an existing environment. Pre-commit runs this repository's locked Docker-free
suite and `git diff --check` for staged and unstaged edits. Stage the complete
reviewed change before committing: tests exercise the working tree.

Pre-push also runs `scripts/sink_go_test.sh` when outgoing `sink/` files change.
New refs conservatively include the whole sink tree. The pinned toolchain runs
Go vet and race tests in local Docker; set a writable `GOMODCACHE_DIR` if the
default cache location is unavailable.

Pre-push requires every non-deletion tip to be the checked-out HEAD, with a clean
tree and index, including untracked files, so tests cover the pushed code. Whitespace checks cover
current edits, preserving historical fixture whitespace. Unknown remote objects
refuse change selection: fetch them explicitly before retrying. Deletion-only
pushes still run the suite. Only local Unix Docker sockets are used; remote
Docker contexts are ignored. Hooks do not launch benchmarks or authorize pushes.

Linked worktrees also require their own bootstrapped venv. Install hooks with
bootstrap in every clone; Git does not enable them on clone.
Agent commits use the same hooks; no `--no-verify` without operator approval.
Historical cross-repository guard validation is preserved in the
[cleanup record at lab cd2d9e9](https://github.com/jopietsch/second-looks-lab/blob/cd2d9e98e159b4467a6e8fc7ba26f28fba1ca6c7/docs/infrastructure-cleanup-plan.md#4-local-quality-gate-in-git-hooks).

## Hosted quality checks

The [quality workflow](../.github/workflows/quality.yml) defines the engine's
checks for pushes, pull requests and manual dispatch on a standard GitHub-hosted
Ubuntu 24.04 runner. Once published, it uses the existing Python 3.14 bootstrap
to install hashed wheels, verify the locked inventory/freeze, run `pip check`,
enable hooks and run the Docker-free suite. The runner must have a reachable
local Docker daemon for the bootstrap's normal idle guard. There is no separate
CI Python installation script, and the pip download cache is keyed by the lock;
each job creates a fresh venv.

Incoming whitespace is checked against the push's previous commit or the pull
request's base. The pull request tests the checkout action's default merge
revision. A force-push predecessor absent from the fetched history is fetched
explicitly; failure to retrieve it fails the check. New refs and manual runs
check only the current commit's whitespace, preserving legacy fixtures, and
conservatively run the entire sink suite.

Existing refs run `scripts/sink_go_test.sh` when `sink/`, `sink.py`, the sink
runner or this workflow changes. It runs Go vet and race tests using the same
digest-pinned toolchain image as the sink recipe; its module cache lives under
the runner's temporary directory. No daemon image is built and no benchmark
runs. Python checks run on every event regardless of sink selection.

The workflow uses immutable action commit pins, a read-only contents token,
checkout without persisted credentials, no private repository bindings or
secrets, a 20-minute job limit and cancellation of superseded runs on the same
ref or pull request. It uses `pull_request`, never `pull_request_target`, and
no self-hosted or measurement runner. Local hooks remain required. Publishing
the workflow activates hosted execution; changing repository Actions settings
or branch-protection requirements is a separate operator action.

For action inputs and workflow semantics, see the official
[checkout](https://github.com/actions/checkout/tree/v7.0.1),
[setup-python](https://github.com/actions/setup-python/tree/v7.1.0) and
[workflow syntax](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax)
documentation. Update action SHA pins and version comments together after
review; Python dependencies continue to use the lock update process above.
