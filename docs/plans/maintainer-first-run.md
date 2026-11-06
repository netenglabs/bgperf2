# Maintainer first-run release readiness

Selected by the operator after storage recovery merged into master at `e9431ee`.
This is a bounded delivery/usability goal: a newcomer can start from a fresh
checkout, run an explicitly simulated FRR investigation, understand the verified
result and find the preparation path for their own source and workload.

The engine owns this entry point and its public documentation. Lab execution,
experiment design, evidence backup and research conclusions remain with their
existing projects. No private checkout, historical plan or retained image is
needed for the example. This work authorizes no new benchmark, source build,
image acquisition, calibration campaign or historical-case rerun.

## Deliverables and acceptance

- A prominent README path and one authoritative first-run guide, including the
  existing Python 3.14/Linux/Docker bootstrap prerequisites and idle-host guard.
- A concise first-run command that reuses the maintained simulated FRR source
  workflow; missing/wrong required packages, wrong Python and unsuitable output
  paths produce actionable errors before the example starts.
- The command explains the intentional count-versus-prefix failure, passing
  rollback, smaller reproducer and confirmed modeled source boundary. It points
  to verified portable reports and distinguishes simulation from live evidence.
- A separate transition to the existing own-source preparation contracts,
  including current regular-file source limits and unassessed runtime readiness.
- CI runs the documented command from its fresh checkout after the normal
  hashed bootstrap. A subprocess test runs the actual CLI from another working
  directory with process/network access forbidden, checks verified artifacts and
  confirms existing outputs cannot be overwritten.
- Required local review, normal commit/push gates and green hosted checks before
  declaring the PR ready. No release tag or runtime execution is included.

The first-run command does not install dependencies, change runtime contracts,
relax source/image guards or alter measurement definitions. Bootstrap remains
the full locked-environment authority; the first-run command checks its required
package versions and leaves unexpected setup failures visible. Runtime
qualification remains exactly the separately recorded bounded cases. Upstream
investigation stays paused, performance policy disabled and calibration deferred.

Implementation and delivery records live with the commit/PR and local review
receipts under `/tmp/bgperf2-first-run-review-20261105/`. The original worktree
and its preserved six draft edits remain unchanged.
