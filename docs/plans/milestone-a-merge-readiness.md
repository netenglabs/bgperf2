# Milestone A branch merge readiness

Operator selected closing hosted CI, opening/reviewing a PR and merging
`milestone-a-newcomer` into the default branch `master` after `b2fc4f2`.
Runtime functional cases remain complete and closed. No new build, benchmark,
calibration or evidence transfer is part of this work. Six concurrent uncommitted
source/test edits in the development worktree remain outside the branch tip.

## Hosted CI blockers

Quality run42065646215 at `b2fc4f2` failed with110failures/12errors despite
3,141passing local tests/one skipped. Inert source preparation refused inherited
Git filter definitions; one batch identity fixture also assumed six online CPUs
on a four-CPU runner.

The hosted workflow removes only the ephemeral runner's unused system Git LFS
preset before tests. Production inherited-filter refusal stays unchanged, as do
local/global malicious-filter fixtures. The batch identity fixture explicitly
supplies its intended six-CPU topology; it tests identity rather than runner
hardware availability. The full locked suite and sink vet/race checks remain
required. No hook, guard or hosted check is bypassed.

## Merge acceptance

Review the accumulated branch against current master (99commits/158files at
selection), including the reviewed CI fixes. Preserve existing runtime evidence,
source bindings and declared qualification limits. Open a PR with user-facing
behavior, validation and explicit performance/source limits. Require green
hosted PR checks and no unresolved blocking review findings before merging.
Refresh and verify remote tips after merge. Do not include the six concurrent
edits or delete their branch/worktree during closeout.

Local review/check/PR/merge receipts live in
`/tmp/bgperf2-main-merge-20261105/`; the GitHub PR and commit history are the
remote delivery records. This plan records readiness criteria, not a successful
merge before those checks finish. Upstream investigation stays paused,
performance policy disabled and calibration deferred.
