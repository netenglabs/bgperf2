# Localize a deterministic BIRD regression

`recipe_bisection.py` searches an explicitly selected consecutive first-parent
revision chain using one frozen recipe and fixed local-source build controls.
It supports the existing four observable correctness assertions or a captured
target-daemon crash. Performance predicates are refused; regression policy
remains `disabled` and performance qualification `not_assessed`.

This implementation is validated with controlled, Docker-free histories and one
[bounded live count-fault case](plans/milestone-d-runtime-validation.md#approved-waited-execution-completed--2026-10-26).
The deliberately introduced local fault confirmed its boundary with fresh workers;
its record retains source/build, contention and diagnostic limitations. Broader
source-build and live crash-bisection qualification remain deferred; the
[milestone B record](plans/milestone-b-runtime-validation.md) covers one validated
packaging-patched BIRD source/build case. No selected
daemon range, source build, download or benchmark is authorized by this guide.
The completed case consumes its execution authorization and authorizes no new
build, worker or revision range.

## Inspect a controlled history

For the complete reproduction-to-investigation-to-bisection story, start with
the [maintainer walkthrough](maintainer-workflow.md). The focused bisection
examples below retain their separate edge cases.

```sh
venv/bin/python scripts/bisection_smoke.py --output /absolute/new/bisection-demo
venv/bin/python recipe_bisection.py status /absolute/new/bisection-demo/assertions/session
```

All source identities, builds, daemon outcomes and observations in that demo are
explicitly simulated. It exercises the real search, package verification,
confirmation and portable-report contracts without invoking Docker or building
source. Normal tests also inspect an inert local Git history through the public
planner and verify that its checkout is unchanged.

## Inspect progress without starting another trial

```sh
venv/bin/python recipe_bisection.py status /absolute/new/search-session
venv/bin/python recipe_bisection.py status /absolute/new/search-session --json
```

The readable status shows the search state, recorded/reserved/remaining trial
budget, good/bad/skipped/ambiguous counts, trial reasons, failed assertion names
and evidence paths relative to the session. A completed search shows its last
observed good and first observed bad revisions and any unresolved range. An
available next trial is explicitly marked **not started**. JSON retains the same
verified information for tools.

Status takes the session's coordination lock and verifies its immutable plan,
journal and available packages. It invokes no Git, Docker, build or worker,
and refuses inspection while another command holds the session lock rather
than reading a partially written trial.
It creates no report and never removes or reconciles a pending reservation. A
reserved trial without a recorded outcome requires recovery; a stale marker
for an already recorded trial is identified separately and also left intact.
Follow the recovery instructions below. Changed evidence or an inconsistent
reservation is refused. Status exit 0 means inspection succeeded, not that a
boundary was found or a regression fixed. Existing JSON `next` output and
portable report formats are unchanged.

## Freeze a revision chain

Use the [local-source build guide](investigations.md) to prepare a build-plan
JSON for every revision in the selected chain, oldest first. Each source plan
must identify an explicitly selected clean existing checkout whose HEAD equals
that full commit. Preparing separate checkouts is an operator responsibility;
this workflow never switches or modifies them. The recipe, build recipe,
instrumentation, flags, immutable toolchain/runtime images and network policy
must match across candidates. Supplied images with unknown source cannot
establish a revision boundary.

```sh
venv/bin/python recipe_bisection.py plan \
  --recipe /absolute/artifacts/recipe.json \
  --build-plan /absolute/artifacts/oldest-build.json \
  --build-plan /absolute/artifacts/middle-build.json \
  --build-plan /absolute/artifacts/newest-build.json \
  --predicate assertions --max-trials 12 \
  --worker-timeout 120 --build-timeout 1200 \
  --output /absolute/artifacts/bisection-plan.json
venv/bin/python recipe_bisection.py init /absolute/artifacts/bisection-plan.json \
  --session /absolute/new/search-session
venv/bin/python recipe_bisection.py next /absolute/new/search-session
```

Planning reads existing local Git commit objects, records their bytes and
checks their hashes and consecutive first-parent links. It invokes no source
code or Docker, acquires no objects, and accepts 2–256 candidates and a fixed
4–1024-trial budget. Include every intermediate first-parent revision: deleting
one is refused. The plan explicitly assumes one monotone good-to-bad transition;
sampling cannot prove that assumption for untested revisions or other recipes.

The selected oldest endpoint must be witnessed good and the newest bad before
searching the midpoint. Unsupported, unbuildable, failed-harness, interrupted,
missing and ambiguous outcomes never become good. Only an attested local build
failure becomes `skipped`; other missing build evidence stays ambiguous.

## Execute or import one trial

`step` and `run` default to displaying the next request. Their explicit
`--execute` flag authorizes the fixed trusted-source build path and bounded
recipe execution described in the [investigation guide](investigations.md).
Already available immutable images and an appropriate unoccupied host are
prerequisites. Build timeout cleanup has the existing limitation: stopping the
owned build client does not prove Docker daemon-side build work has ended.

```sh
venv/bin/python recipe_bisection.py step /absolute/new/search-session --execute
# Or, after explicitly selecting the complete bounded search:
venv/bin/python recipe_bisection.py run /absolute/new/search-session --execute
```

Each step reserves its request before any build or worker, runs serially under
an exclusive session lock, caches a completed target by the complete build-plan
identity, verifies its source/build binding and copies its verified package into
immutable trial evidence. Caching never substitutes an old measurement for a
new worker. Every source attempt ID must be unique, including confirmations.
There are no arbitrary predicate scripts, automatic repairs, budget extensions
or measurement retries. Original work, results and build logs remain local.

`assertions` means session establishment, injection completion, exact observer
count and experiment completion, all within the selected worker budget. These
are the [existing named observable assertions](comparisons.md), not route or
attribute truth. A decisive failure from an otherwise measured experiment may
be bad; harness failure or an unsupported/missing witness stays ambiguous.

`target_crash` requires a recipe whose expected outcome is `target_crash`, basic
diagnostics, a clean process-presence observation followed by absence and a
captured nonzero exit in the same target container, and an experiment-failed
outcome. Ordered finite sample timestamps must lie within explicit controller
worker start/end monotonic anchors, whose difference matches recorded elapsed
time. Missing anchors, dropped samples, probe errors or contradictory evidence
stay ambiguous. A good trial requires completed correctness assertions and
target presence without a captured exit. This is an observed crash predicate,
not continuous health, signal attribution or general freedom from crashes.
Basic diagnostic overhead remains uncalibrated.

An externally executed verified result can be imported for the exact next
request with `record SESSION --result /absolute/package/result.json`. It must
match the frozen recipe, source revision, target build and worker timeout.
Declaring provenance and hashing files do not authenticate their author or
prove a reproducible binary; trusted execution remains an explicit boundary.

## Resume without repeating an uncertain worker

An interrupted reservation blocks all new execution. Inspect the owned worker
and build state and retain the original work before explicitly recovering:

```sh
venv/bin/python recipe_bisection.py recover /absolute/new/search-session \
  --result /absolute/original/result.json
# If no usable result exists:
venv/bin/python recipe_bisection.py recover /absolute/new/search-session \
  --abandon-reason 'Worker stopped; original incomplete evidence retained'
```

Recovery imports a verified original or consumes that trial as ambiguous; it
does not repeat it. An already written failure record retains its original
classification and reason. An incomplete copied package is preserved before
the verified original is copied again. A journal entry completed before its
reservation marker was removed is reconciled without rerunning a worker.
An ambiguous measured trial pauses `run`; an explicit subsequent invocation
can search other untested revisions. It never silently retries that revision.

An existing failure also takes precedence when `recover --result` supplies a
different package: recovery journals the original classification/reason and
leaves that supplied package unused. It cannot turn an attested failed build
into a good trial.

New reservation, failure and journal records are staged under
`failures/unpublished/`, flushed, then published with an atomic create-only link.
Interrupted staging cannot leave partial JSON in the authoritative trial journal.
Available staging fragments remain retained and included in portable reports;
they are not additional trials. If publication completed before bookkeeping
stopped, recovery reconciles that existing record without another worker.
This covers process interruption; it establishes no general power-loss guarantee.
An already malformed final journal remains refused for manual inspection; this
change does not repair or rewrite old evidence.

## Review the boundary

```sh
venv/bin/python recipe_bisection.py report /absolute/new/search-session \
  --output /absolute/new/search-report
venv/bin/python recipe_bisection.py verify /absolute/new/search-report/bisection.json
```

Reports work for in-progress, interrupted and completed sessions and bundle the
plan, original trial packages, failure evidence, journal, Markdown and file
checksums. Verification reconstructs predicates, requests, bounds, confirmations
and human prose from bundled bytes. Work directories and build caches stay at
their original paths; copying this report alone is not complete work retention
or an independent backup.

An adjacent boundary is `confirmed` only after fresh good-side and bad-side
workers agree with the search. A skipped or ambiguous hole yields an explicit
unresolved possible-first-bad range even when both bracket endpoints confirm.
Missing endpoints, failed confirmations, inconsistent observations and budget
exhaustion yield no confirmed boundary. `run --execute` exits 5 unless confirmed;
successful report verification proves consistency, not a successful regression
search. Review the trial classifications and limitations before interpreting
any boundary. Nothing posts an upstream issue or enables performance policy.
