# Read-only functional investigation status

Selected 2026-11-03 after the successful real-BIRD two-side prefix validation.
The next maintainer usability step is a concise view of verified evidence:
existing `investigation-verify` returns integrity and reproduction, while the
full report contains substantially more detail than routine status inspection
needs. No new worker, capture, predicate or performance policy is selected.

## Contract and implementation

`recipes.py investigation-status /absolute/report/investigation.json` verifies
the entire existing report and its bundled packages before returning a compact
JSON summary. `--format text` renders a printable terminal view. A shared
internal verifier returns its verified in-memory document, controller stop and
original packages; status does not reread an unverified replacement summary.
The established `investigation-verify` output remains unchanged.

The new `bgperf2/investigation-status/v1alpha1` view preserves recipe binding,
reproduction assessment, controller stop, each side's availability/status/reason
and original attempt ID. Selected correctness retains each named assertion's
status, expected/observed values and reason. Count and identity stay separate.
Legacy unselected correctness is null, missing attempts have null original IDs,
and unavailable capture stays unmeasured. No aggregate acceptance verdict or
permission to execute is inferred. Exit 0 means verified inspection, including
when assertions failed or remain unmeasured.

## Acceptance

Offline checks cover successful selected pairs, count-pass/identity-failure,
legacy/unmeasured capture, unavailable attempts, controller stops, changed
report/prose refusal, reordered JSON side keys, relocation/rebuild and both CLI
formats. Tests forbid runtime/preflight subprocess work during status inspection
and check evidence remains unchanged. Terminal text escapes control characters.

Validate the public command against both preserved real-BIRD reports without
changing their source or evidence. Complete independent source review, required
repository gates and a local conventional commit. Retain command logs and
progress under `/tmp/bgperf2-investigation-status-20261103/`. No real execution,
image/package acquisition, scheduler or publication is needed. Upstream BIRD
investigation remains paused; calibration and broader capture remain deferred.

## Completed offline qualification — 2026-11-03 UTC

The new status tests passed all 23 cases, including a failed health observation
alongside missing or malformed other role states. Existing prefix, investigation
and documentation checks passed 135 tests. Both public CLI formats
accepted the retained real-BIRD original and rebuilt reports, exposed two
distinct original IDs with six passed assertions and 100 exact prefixes each,
and produced identical JSON summaries. All 840 previously sealed regular files
were verified before and after these four read-only commands. No new worker,
build or probe ran. Full source review, native commit-gate evidence and the local
delivery checkpoint remain with the external task evidence named above.
