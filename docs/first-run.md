# Your first maintainer workflow

Use this path to learn how bgperf2 turns a correctness question into a
reproducer, a baseline/candidate investigation, a smaller workload and a source
boundary. You will get inspectable, verified reports from an explicitly
**simulated FRR example**. It does not run FRR or measure performance.

## Prepare a development checkout

The supported setup path needs:

- Linux, Git and Python 3.14 with venv/ensurepip support.
- A local Docker CLI and reachable daemon, accessible to your user. The normal
  bootstrap uses Docker for its read-only active-measurement guard, even though
  the example itself does not contact Docker. A remote Docker context is not a
  substitute for that local check.
- Network access to clone the repository and install the hashed Python wheels.
  After setup, the example runs offline.

Use a development host with no active BGP measurement. No FRR checkout,
compiler, daemon images, private lab repository or retained experiment is needed
for this example. Bootstrap installs the locked Python environment, enables
local hooks and runs the Docker-free test suite; it builds no daemon image.
The [environment guide](python-environment.md) owns the complete setup contract.

From a directory where you want the checkout:

```sh
git clone https://github.com/netenglabs/bgperf2.git
cd bgperf2
python3.14 scripts/bootstrap.py
venv/bin/python scripts/first_run.py --output "$HOME/bgperf2-first-run"
```

Choose a new absolute output directory outside the checkout, with an existing
writable parent and no symlink components or parent traversal. Existing output
is preserved and refused, so a second example
needs another name. The command also works from another directory when you use
absolute paths to this checkout's interpreter and script.

The example checks Python and required package versions before it starts. It
does not install missing dependencies or replace the bootstrap's full inventory
verification. It selects a scratch artifact store inside its output and ignores
an optional live Parquet converter binding during simulation. Your configured
store and existing output remain unchanged.

## Read the result

The command prints a short result and the path to `REPORT.md`. Open that report
in a Markdown viewer; its relative links lead to the underlying evidence.

| Result | What it teaches |
| --- | --- |
| Baseline count passes, prefix identity fails | Counting routes can miss a wrong route. This deliberate fixture failure is expected. |
| Rollback candidate passes | Check the same workload against an explicit rollback; this is not an upstream fix claim. |
| One peer/two prefixes, freshly confirmed | Minimize while preserving the selected failure; the result is bounded, not a global minimum. |
| Modeled adjacent source boundary confirmed | Search a declared history and confirm both sides with distinct observations. |
| Interrupted bookkeeping recovers the original | Recovery records the existing result without repeating its worker. |
| Eight portable report packages verify | Inspect results that reconstruct, relocate and refuse altered evidence. |

All revisions, builds, images, workers and numeric observations in this example
are simulated. A successful first run means those public workflow and evidence
contracts passed their modeled checks. It establishes no actual BGP exchange,
performance difference, pristine-source build or hardware qualification. The
generated JSON, reports and per-command receipts remain under your output path;
they are illustrative inputs and cannot be relabeled into real observations.

The lower-level example remains available in the
[FRR source guide](frr-source-workflow.md); the first-run command reuses it.

## Prepare your own investigation

Start a **new preparation** with your own question and inputs. Keep the simulated
output as an example. Choose the relevant path below; the linked guides own the
commands and exact contracts.

| Step | Choose and prepare | Authoritative guide |
| --- | --- | --- |
| 1 | One supported synthetic IPv4 recipe, expected outcome and explicit immutable role-image declarations | [Portable recipes](recipes.md) |
| 2a | Supplied FRR images, if you already have appropriate selected images | [Supplied-image FRR workflow](frr-maintainer-workflow.md) |
| 2b | Trusted local FRR source, full revisions and fixed source-build inputs | [FRR source workflow](frr-source-workflow.md#freeze-trusted-source-and-build-inputs) |
| 3 | An isolated consecutive revision range and a verified, unexecuted command handoff | [Prepare your checkout](maintainer-checkout.md) |
| 4 | A separately selected bounded correctness attempt, its prerequisites, capacity, storage and evidence paths | [Functional checks](functional-validation.md) |

Current source preparation accepts regular files, with explicit file/size
bounds. **Pristine FRR checkouts containing tracked topotest symlinks are not
supported by that contract.** Keep the original source intact; do not silently
delete or dereference aliases to make it look supported. Any selected packaging
adaptation needs recorded attribution and an explicit transformation. Planning
does not prove an image exists or execute source, builds or workers.

For real execution, select the exact supported recipe/source/images, budgets
and fresh destinations, and check the host through the existing public commands.
Real runs also need their documented system tools and supporting role images.
Read an unexecuted handoff before selecting any build or worker. A first-run
success or preparation report supplies no runtime authorization.

For timing, CPU or memory comparisons, use the separately qualified comparison
protocol. Performance policy stays disabled and calibration deferred. FRR crash
witnesses and thread controls remain unsupported; existing live qualification
limits are recorded in the [roadmap](roadmap.md).

## If setup stops

| Symptom | Next action |
| --- | --- |
| `python3.14` or venv support is missing | Install Python 3.14 with venv/ensurepip through your normal system setup; bootstrap does not install Python. |
| Docker socket permission denied | Give your user normal local Docker access. In a restricted agent sandbox, approve the complete guarded bootstrap command as described in the [environment guide](python-environment.md). |
| Active measurement or held measurement lock | Let that measurement finish before bootstrap or development; the guard remains required. |
| Required package missing or wrong version | Use this checkout's `venv/bin/python` after bootstrap. For an existing mismatched environment, follow the environment guide's rebuild procedure. |
| Output exists, is inside the checkout or has a missing parent | Choose a fresh absolute directory outside the checkout with an existing writable parent. |
| The example reports a failure after creating output | Keep the partial output and inspect its command receipts and error. A completed example should report the expected modeled outcomes above. |

## What CI checks

The quality workflow creates a fresh checkout and locked environment, runs the
normal suite, then invokes the same `scripts/first_run.py --output ...` command
with a fresh directory under the runner's temporary root. Its separate step is
named **Run the documented first-run workflow (simulated)**. The suite also runs
the actual CLI from another directory with subprocess/network operations
forbidden, verifies its reports and checks existing-output refusal. These checks
cover onboarding and modeled contracts, not live daemon qualification.
