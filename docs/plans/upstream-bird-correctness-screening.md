# Upstream BIRD correctness case screening

Updated 2026-11-02 UTC. Status: investigation resumed; **no execution-ready
upstream bug/fix case selected**. This record is the source-bug investigation,
separate from the neutral release-transition validation and prefix-identity
implementation. Neither establishes an upstream reproduction.

## Evidence and scope

Screened four ordinary correctness fixes in the existing local upstream history.
This is not an exhaustive search of BIRD history and does not establish that no
suitable BIRD bug exists. The selected source checkout is
`/tmp/bgperf2-milestone-d-live-20261026/source`, whose origin names
`https://gitlab.nic.cz/labs/bird.git`. Its HEAD, refs, status, tracked diff and
effective configuration signatures remained unchanged during collection.

Retained evidence: `/tmp/bgperf2-upstream-screen-20261102/`. `local-screen.json`
records exact parents, fix commits, trees, containing local tags and symlinks.
Each saved raw commit was rehashed as a Git commit object and matched its ID.
Saved `.tree` files are listings, not independent whole-tree authentication.
The upstream HTTPS patch for each fix was retrieved successfully and its diff
body matched local Git output after removing index-hash abbreviation lines;
`remote-verification.json` retains URLs, hashes and comparison scope. This is
source-document verification, not binary provenance or runtime reproduction.

Issue 436's original issue body could not be retrieved: web open was unavailable
and native curl with `--fail` exited 22. The commit itself names the issue and
reporter. Do not imply the original report, reproducer or discussion was read.
The reload fix also supplies a mailing-list link; its body remains unverified.

Existing local image metadata was inspected without running containers.
`selected-images.txt` records five exact IDs/tags/labels: the prior BIRD 2.19.2
build environment/generator, sink 0.1, supplied BIRD 3.3.2 and the two neutral
release-transition images. These are existing inputs and prior functional
evidence, not an affected/fixed pair for any candidate below. Tags alone do not
prove source ancestry, and an image with absent labels is not authenticated by
its name. No claim that all local images were inspected follows from this file.

## Screened candidates

| Fix | Immediate parent | Required state and present gap |
| --- | --- | --- |
| [Pending-export statistics, issue 436](https://gitlab.nic.cz/labs/bird/-/commit/0c1d13466995a981cbe7a46842b5f2fe5aa69f26) `0c1d13466995a981cbe7a46842b5f2fe5aa69f26` | `0f5e8e9889a6e272db9c7457f82f7661f019a7ef` | Plausibly reachable through normal monitoring, but no verified overlap between a statistics poll and an affected pending export bucket. Not reproduced or ruled out. |
| [Reload after session restart, issue 387](https://gitlab.nic.cz/labs/bird/-/commit/3a34912eb88e0b8ac061962362e1322bfce34ecd) `3a34912eb88e0b8ac061962362e1322bfce34ecd` | `9910fdafe7714290c3d9b28798ff1b9ea04897b6` | Requires a session restart followed by route reload/refresh. The portable recipe exposes neither that sequence nor a recovery oracle. Initial establishment does not exercise it. |
| [MED route replacement](https://gitlab.nic.cz/labs/bird/-/commit/6b4a6917daa888d062ac5fd32b54ade9b9a218ed) `6b4a6917daa888d062ac5fd32b54ade9b9a218ed` | `25b9c0e5cb07130f80eb9df119e8258a8c369f1c` | Requires deterministic MED and replacement of competing same-prefix routes. The current template does not enable deterministic MED; the recipe fixes disjoint prefixes, path diversity one and no churn/policy. |
| [Obsolete routes during refeed](https://gitlab.nic.cz/labs/bird/-/commit/7bc06c76729b741c3925625099c669e815862e68) `7bc06c76729b741c3925625099c669e815862e68` | `9181a1792e3cc8edfd511157e5a811444155c741` | Requires refeed involving obsolete route/journal history. No declared refeed/replacement sequence exists. Final prefix count/set alone cannot distinguish redundant obsolete announcements that settle to the same final set. |

These are real documented upstream fixes; none is an intentionally introduced
fault. Immediate parents identify the code before each fix, not an observed bad
result or a verified full affected-release range. Local containing tags describe
this clone only; for example the statistics fix is contained in v3.3.1/v3.3.2,
and its parent VERSION reads 3.3.0. No broader affected-version claim is inferred.

## Why issue 436 remains the nearest candidate

The upstream commit identifies BIRD 3.3.0 as affected. It changes only
`proto/bgp/attrs.c`, replacing traversal in `bgp_bucket_pending()` with counting
from the dense representation. In the fixed revision, `proto/bgp/bgp.c`'s
channel display walks `tx->bucket_queue` and calls this helper for each queued
bucket. An empty queue bypasses it.

The current `BIRDTarget.show_protocols()` in `bird.py` executes
`birdc 'show protocols all'`; `sample_target_state()` uses that same read.
`base.py`'s neighbor sampler sleeps one second between reads. Thus the normal
monitor has a relevant call path. Static reachability does not establish that a
bounded injection overlaps an affected queue state at a poll, or that the
baseline crashes. Increasing prefix count or timeout would be an experiment,
not proof of overlap or permission to run it.

An exploratory baseline/fixed endpoint pair could investigate natural
reachability within the supported workload. It must be described as exploratory
until actual original packages establish a difference. A completed baseline
without a crash means not reproduced for that attempt; it does not disprove
the upstream report. A timeout, unavailable daemon read or harness failure is
not a target-crash witness. A useful result would require a verified target
process crash on the older code and a distinct fixed-revision result, with
source/build identities and all controller/cleanup limitations retained.

No source build plans, good/bad endpoint labels, runtime recipe or handoff are
manufactured here to imply that missing semantic evidence exists. The
[source-range](../source-range.md) and [handoff](../maintainer-handoff.md)
contracts prepare declared questions; their verification cannot establish that
a real upstream bug is triggered. The older-good/newer-bad source-range ordering
must not be mislabeled to turn a fixing commit into a regression boundary.

All four inspected trees contain the same two BSD-netlink symlink aliases.
Strict source planning still refuses raw symlinks. Any later selected case needs
the supported explicit alias-only derivation, independently verified against
these exact revisions. Prior BIRD 2.19.2 derivations do not qualify different
BIRD revisions or establish build compatibility for them.

## Contract boundary and next decision

`recipes.py` restricts accepted source fields and fixes path diversity one,
receivers zero and default churn/reload controls. [Recipes](../recipes.md)
explicitly refuse custom scenarios, hooks, policy and workload extensions.
The existing assertions cover declared session/injection/count/completion/role
health facts. Optional [prefix identity](../observer-prefixes.md) measures one
final set; capture is supported for standalone run, not automatically for
investigation/comparison/bisection. It cannot substitute for an update-history
or recovery witness.

No candidate among this screen is a qualified deterministic distinguishing
case. The precise gaps are missing trigger evidence for issue 436, unsupported
lifecycle control for issue 387, unsupported competing-route inputs for MED,
and missing refeed plus ordered-history observation for the refeed fix. These
findings do not authorize widening the recipe or adding arbitrary commands.

The investigation remains open. Before requesting execution approval for issue
436, resolve the original-report evidence limit where possible and prepare an
explicitly exploratory question, exact supported workload, independent source
derivations/build plans, actual input-image checks, bounded build/worker budget,
evidence destinations, conditional expected outcomes and terminal recovery rules.
Do not promise reproduction or silently turn that exploration into calibrated
performance testing. Alternatively select another documented fix with a stronger
supported trigger and observable witness. No build or worker budget is allocated
by this screening record, and no execution approval is requested.

## Safe readback and preservation

Existing evidence can be inspected without invoking a build or worker:

```sh
git -C /tmp/bgperf2-milestone-d-live-20261026/source show --format=fuller 0c1d13466995a981cbe7a46842b5f2fe5aa69f26
git -C /tmp/bgperf2-milestone-d-live-20261026/source show 0f5e8e9889a6e272db9c7457f82f7661f019a7ef:VERSION
git -C /tmp/bgperf2-milestone-a show 972ca319e95b1c01e87a779cb3693fb21c02dc3b:bird.py
git -C /tmp/bgperf2-milestone-a show 972ca319e95b1c01e87a779cb3693fb21c02dc3b:base.py
```

Collection scripts use exclusive creates. Do not rerun them into this evidence
root, overwrite partial outputs or delete prior evidence. An interrupted
collection calls for inspection and a new named output, never a build/worker
retry. Checksums and independent review are retained with the external record;
local same-device preservation is not independent backup. This investigation
ran zero builds, workers or containers and acquired no images/packages. Other
previously authorized cases retain their separate original accounting.
Performance policy stays disabled and formal 10% calibration deferred.
