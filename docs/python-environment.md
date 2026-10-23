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
