continue the 2026 daemon comparison

You are running headless. `scripts/spot_boot.sh` started you because the batch
`{{CONFIG}}` has just finished, with its results in `{{RESULTS}}`. Nobody is
watching and nobody can answer a question. Follow the `2026-daemon-comparison`
skill and `CLAUDE.md`, with these differences, which the operator set up on
2026-10-05:

- **What is approved.** The operator approved the plan's remaining benchmark
  steps and their re-runs in advance (plan §9, Progress, "the rest of item 3 is
  approved in advance" and the later approval of every remaining step). That
  covers recording a finished step and queuing what those approvals name. It
  does not cover anything marked "(operator)", anything those rules do not
  name, or a result you cannot explain. Those are a GATE, below.
- **Your unit is recording `{{CONFIG}}`.** Record it in
  `docs/2026-daemon-comparison-plan.md` in the same form as the steps before
  it, and update item 3's line and the bead as the skill says. Read the step
  with `venv/bin/python scripts/comparison_step_table.py {{RESULTS}}`. Every
  figure you write comes from that output or from a file you read yourself;
  re-check anything surprising against the row's own `events.json`. If the
  config's results are only partly there (a resumed step), record what is
  there and say what is missing.
- **The plan may already record this step.** A reclaim can land after a
  session committed its record and before it edited the queue, and then you
  are started on the same step again. Check the plan first. If it already
  records `{{CONFIG}}`'s result, do not record it twice. Bring the queue in
  line, and write `RECORDED` saying that is all you did.
- **The approved rules.** A row that converged with `tester_incomplete`, or
  that was decided on one witness while a generator had not completed, is
  excluded, and its cell is re-run: write a re-run config the way
  `benchmarks/2026-comparison-rrc00-n24-rustybgp-rerun.yaml` was written (its
  own test name, three passes, the same pin and monitor), commit it, and put
  its path as the **first** line of `{{QUEUE}}`. A row whose `min free mem
  (GB)` is below the 15% guardrail is recorded and excluded, not re-run.
- **You never start a benchmark.** `spot_boot.sh` runs the queue. Do not run
  `bgperf2.py` or `docker`.
- **The queue.** When `{{CONFIG}}` is recorded and committed, delete its line
  from `{{QUEUE}}`. If the plan's next item is a benchmark the approval covers
  and its config is committed, append that config's path. If the plan's work
  is complete, close what the skill says to close and leave the queue empty.
- **Git.** You are in the repository, on branch `{{BRANCH}}`. Commit there with
  plain `git` (not `git -C`). Never push, never switch branch. You may write
  only the plan, documentation and benchmark configs; code, tests, hooks and
  settings are not writable here. If the step needs a code change, that is a
  GATE.
- **Finish by writing `{{STATUS}}`.** First line exactly one of:
  - `RECORDED`: the step is recorded and committed, and the queue is updated.
  - `GATE`: the operator must decide something. Lay out the options the plan
    records, record the open decision in the plan, commit, and stop.
  - `FAILED`: you could not finish, for a reason that is not a decision.

  Then a few plain lines for the operator's phone: what you recorded (cells,
  medians, anything excluded) or what they must decide. This is what they
  read first, so make it accurate and short.
