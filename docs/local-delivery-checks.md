# Local review and validation receipts

Use the existing bootstrapped environment on an idle development host. The
hooks remain the check authority. This workflow does not commit or push.

1. Finish the bounded implementation and stage the complete change.
2. Freeze/review it once:

   ```sh
   venv/bin/python -I scripts/local_review.py --output .dev-checks/review-01
   ```

3. Address concrete blockers and stage those fixes. Verify the findings rather
   than requesting another general review:

   ```sh
   venv/bin/python -I scripts/local_review.py --output .dev-checks/review-02 \
     --previous .dev-checks/review-01/review.json
   ```

4. Verify the review still matches, then validate through the same gate used by
   pre-commit. Request approved host execution if the sandbox cannot reach Docker.

   ```sh
   venv/bin/python -I scripts/local_review.py --verify .dev-checks/review-02/review.json
   venv/bin/python -I scripts/quality_gate.py validate
   ```

5. Commit/push only when authorized. Their normal hooks still run. Fix a new
   blocker before declaring completion; leave review followups as separate work.

The default reviewer is installed Claude Code in plan mode, restricted to
Read/Grep/Glob and no MCP servers. The prompt invokes `/code-review` adapted to a
local diff, with no PR lookup/comments, tests, edits or delegation. It expects
strict JSON with findings, stable IDs and resolved IDs. The runner does not
replace a missing reviewer installation, credentials, or repository review
requirements. Review readiness only describes review; it does not mean tests
passed. Prompts and scope are constraints, not an operating-system security
sandbox. A custom backend is trusted executable code.

The default five-minute deadline kills the process group; API/network errors
visible in output stop immediately. No automatic retry or second broad review
runs. Complete logs and the frozen diff remain in the selected output, even
when the reviewer exits zero with an API error or emits invalid JSON. Output
must be Git-ignored or outside the checkout. Use `--timeout SECONDS` for an
explicit different budget. `--backend-json '["/absolute/reviewer", "arg"]'`
supports another backend without shell evaluation; it receives the contract on
stdin and returns the documented JSON on stdout.

A `--previous` review verifies only the earlier blocker IDs. Omitting a blocker
from the response does not resolve it, and a change to unrelated files or to
the review baseline requires a new broad review. Followups stay visible but do
not block readiness.

Successful validation receipts live in ignored `.dev-checks/receipts/`; full
stdout/stderr and failed-run records live in `.dev-checks/runs/`. A receipt
matches actual tracked/untracked source bytes and modes, Git HEAD/index/status/
configuration, command/profile, checkout location, environment digest, Python
version/package inventory, bound source checkouts and checker implementation.
Explicit `BGPERF_*_PYTHON` environments are inventoried too. Secret environment
values are hashed, not written into receipts. Shell bookkeeping (`_`, `PWD`,
`OLDPWD`, `SHLVL`, `GIT_PREFIX`, `CODEX_TOOL_CALL_ID`) and the verified default `GIT_INDEX_FILE` do not
change receipt matching. An alternate index, including Git's temporary commit
index, runs checks without caching. Logs and command arguments can
contain tool output; keep this local directory private. Avoid credentials in
command arguments. Receipts expire after 24 hours; delete `.dev-checks/` to
discard local records. They are not benchmark evidence and are never archived
with results or committed.

Success is recorded only if the state matches before and after the command.
Failures, timeouts and changed sources keep diagnostics and require a fresh
successful run. Actual bytes catch changes hidden by assume-unchanged or
skip-worktree flags. Directory symlink referents (including skill aliases) are
fingerprinted recursively. Unsupported directories/submodules/special source
files run checks without reuse. Review freezing refuses hidden index flags and
alternate indexes. Ignored generated data, system binaries and external
services are not exhaustively fingerprinted; use these profiles only for the
repository's deterministic development checks. Hosted CI always runs afresh.
Local receipts are trusted records and cannot prove that their owner did not
modify them.

Known limits: Git injects PATH and editor variables into hooks, so a manual
validation can miss the hook's receipt even before HEAD changes; identical hook
retries do reuse their own receipt. `dev_checks.py` gives each command a
20-minute default deadline (`--timeout`). Recursive or special symlink
referents run without reuse; a source alias the checker cannot read is not
worked around.

### Pushing without an idle connection

`git push` connects to the remote *before* it runs the pre-push hook, so the
connection sits idle while the suite runs. GitHub closed it after about five
and a half minutes on 2026-11-26, after the checks had passed, so the push
failed, and the retry needed only the receipt that run had left. To run the
checks before anything connects:

```sh
venv/bin/python -I scripts/push.py               # check, then push
venv/bin/python -I scripts/push.py --check-only  # check only
```

It runs the pre-push hook through `git hook run`, which hands it the same
environment, working directory, arguments and stdin as a real push (verified
with Git 2.53, and by `tests/test_push_helper.py` on every run) without opening
a connection. Then it runs `git push <remote> refs/heads/<branch>:<upstream>`,
whose own hook reuses the receipt and repeats only the quick guards. It pushes
only the checked-out branch to its configured upstream, the one shape pre-push
accepts, to the remote `git push` would pick (`branch.<name>.pushRemote`, then
`remote.pushDefault`, then `branch.<name>.remote`). It refuses a detached HEAD,
a branch with no upstream, and a checkout with no pre-push hook installed —
the last said as such, since no gate would run. The remote's tip is asked of
the remote (`ls-remote`, exact ref only), as a push would, rather than read
from a possibly stale tracking ref. Committing or editing between the two
steps changes the receipt identity, and the push then reruns the suite itself.

GitHub's idle close can also be prevented at the SSH layer: with
`ServerAliveInterval 30` for `github.com` in `~/.ssh/config`, an idle push
session stayed open for 7 minutes where one without it was closed.

Git-aware tests are conservatively kept in the suite: a commit changes HEAD,
index or status and can require a fresh run. This intentionally saves repeated
runs at the same state without claiming arbitrary pre-/post-commit equivalence.
Every hook still checks host idleness, exact locked environment and whitespace.
Pre-push also checks cleanliness, checked-out outgoing tips and bound-engine
readiness. Sink Go vet/race checks use a separate receipt profile whenever the
existing push selector requires them.

The standard-library checker is reusable by explicitly bound consumers:

```sh
/absolute/engine/venv/bin/python -I /absolute/engine/scripts/dev_checks.py \
  --repo /absolute/consumer --profile consumer-python \
  --python /absolute/consumer/venv/bin/python --binding /absolute/engine \
  -- /absolute/consumer/venv/bin/python -m pytest -q
```

Consumers must ignore `/.dev-checks/` and keep their existing host/environment
guards. The lab uses this public CLI when `BGPERF_ENGINE_ROOT` names a checkout
with the checker; otherwise its checks run without reuse. Integration and pure
lab tests retain distinct profiles and interpreters. No engine binding is
required for ordinary lab tests.

Consumers can read the exact local source identity without running a check:

```sh
venv/bin/python -I scripts/dev_checks.py --repo /absolute/checkout --snapshot
```

The `bgperf2/local-source/v1` response contains `snapshot` with the same source
identity used by receipts. It initializes no runtime and publishes no receipt.
Consumers own delivery journals, worktree setup and deployment; none is required
for this engine workflow. Historical data migration remains separate.
