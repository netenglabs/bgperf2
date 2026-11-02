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

Cross-repository delivery, worktree/bootstrap preparation and historical data
migration are deferred; see the [implementation plan](plans/local-delivery-checks.md).
