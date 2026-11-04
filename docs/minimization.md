# Bounded reproducer minimization

`recipe_minimization.py` reduces the peer count and prefixes per peer of one
synthetic IPv4 BIRD/BIRD/sink recipe while preserving one existing named
[correctness assertion](comparisons.md). The preservation predicate is exactly
that assertion's observed `failed` status. For example, `observer.count` checks
count agreement, not route identities or attributes. A failure of
`experiment.complete` does not preserve an `observer.count` failure.

Planning, status and reporting are offline. Execution requires `step --execute`.
The workflow uses the recipe's immutable supplied role images and fixes their
observed physical image IDs from the fresh baseline; it offers no
target override, build, acquisition or source-history search. See the
[recipe guide](recipes.md) for supported workloads, prerequisite checks and
verified result packages. The [implementation plan](plans/reproducer-minimization.md)
records the selected scope and acceptance receipts.

## Freeze a search

Start with an exported recipe and select the observed failure by its exact
assertion name. These commands create new local output:

```sh
venv/bin/python recipe_minimization.py plan recipe.json \
  --assertion observer.count --dimension peers --dimension routes \
  --min-peers 1 --min-routes 1 --max-trials 20 --timeout 120 -o plan.json
venv/bin/python recipe_minimization.py init plan.json \
  --workdir /data/minimization-work --results-dir /data/minimization-session
venv/bin/python recipe_minimization.py status /data/minimization-session
venv/bin/python recipe_minimization.py next /data/minimization-session
venv/bin/python recipe_minimization.py step /data/minimization-session
```

`status` returns JSON by default; `--text` gives a concise display. `next` and a
plain `step` only preview the next proposal. Each explicit execution launches
at most one existing bounded recipe worker:

```sh
venv/bin/python recipe_minimization.py step /data/minimization-session --execute
```

Inspect status between steps. A fresh execution of the unchanged original
recipe establishes the baseline first. Selected dimensions are tried in the
declared order, using deterministic floor, midpoint and unit-decrement
proposals. Accepted reductions restart proposals. Passing candidates do not
establish monotonicity or a global minimum.

The finite budget (3–256 trials) includes the baseline, reservations, in-flight
work and a separate fresh final confirmation. Timeout must be finite, positive
and at most 3,600 seconds. Unmeasured or operationally uncertain evidence stops
successors. Baseline absence of the selected failure and unsuccessful fresh
confirmation remain distinct conclusions. A confirmed reduction requires a
smaller recipe and a fresh matching final observation.

## Reservation and interrupted bookkeeping

`reserve SESSION` journals one proposal without launching it and discloses its
candidate, owned paths and expected result location. An operator can return the
verified original package there and call `record SESSION`; `--result PATH`
accepts only the expected location. Reservations consume budget immediately.
`recover SESSION` completes bookkeeping only for an already collected verified
pending result. It never launches, retries, fills missing measurements or
discards partial evidence. A pending attempt prevents another launch, and
duplicate original attempt IDs are refused.

A returned prerequisite refusal or the runner's explicit pre-launch host-lock
refusal produces `operational_refused`, with a retained controller-stop receipt.
No worker started; the reservation remains charged and the session is closed.
Resolve the recorded cause and initialize fresh paths for another session.
`recover` does not request a nonexistent result for these known refusals. Other
controller exceptions remain uncertain until an existing original is recovered;
missing files alone never prove that no worker started.

Interrupted evidence copies remain in the session's `snapshots/` directory.
Recovery copies the verified original into staging, verifies it and publishes
atomically before recording the trial; it never reruns the worker. Partial
staging bytes are retained locally and are not bundled as measured evidence.
Concurrent session inspection refuses an active session rather than reading a
half-written journal.

CLI exit 0 means the requested operation/inspection was valid; it does not mean
a reduction was confirmed. Inspect `state`, `conclusion` and `confirmed`.
Malformed operations and an executed step with a known pre-launch refusal exit
2; the latter retains its inspectable JSON status on stdout.

```sh
venv/bin/python recipe_minimization.py reserve /data/minimization-session
# Review the returned argv and collect its result at the disclosed owned path.
venv/bin/python recipe_minimization.py record /data/minimization-session
# If collection finished but recording was interrupted:
venv/bin/python recipe_minimization.py recover /data/minimization-session
```

The original embedded source and recipe are retained unchanged. Derived
candidates project to a disclosed canonical single-cell per-peer source.
Selection, legacy identity, ordinal, repetition, order and seed metadata are
regenerated. Engine revision, immutable role images, raw target settings,
pinning, completion contract and reproduction question stay fixed.
Candidate-dependent assertion expectations regenerate exactly. This is a
workload-size search; arbitrary route subsets, MRT, attributes, IPv6, new
adapters and performance predicates are unsupported.

## Portable evidence

```sh
venv/bin/python recipe_minimization.py report /data/minimization-session \
  --output-dir /data/minimization-report
venv/bin/python recipe_minimization.py verify /data/minimization-report/minimization.json
venv/bin/python recipe_minimization.py rebuild /data/minimization-report/minimization.json \
  --output-dir /data/minimization-rebuilt
```

Reports bundle candidate recipes and original result packages. Verification
rehashes files and independently reconstructs proposals, assessments and the
bounded conclusion after relocation, without runtime access. Missing, changed
or duplicate evidence is refused. Report generation does not run a worker.
Performance qualification remains unassessed and performance policy disabled.
An already verified pending package can be retained in a report without being
recorded or confirmed; unavailable partial work is disclosed explicitly.
Copied sessions support offline inspection; their mutation commands refuse a
different session root.

## Maintained modeled walkthrough

```sh
venv/bin/python scripts/minimization_smoke.py --output /tmp/my-new-minimization-smoke
```

Choose a new absolute directory outside the engine checkout. All identities,
observations and controlled failures are explicitly **SIMULATED**. The
walkthrough exercises the public CLI with exact modeled prerequisite probes,
a private modeled host lock, bounded fake runtime observations and global
subprocess/network refusal. Local accounting, packaging, verification and
rebuilding execute normally. It retains successful reduction, unrelated
failure, unmeasured work, budget exhaustion and failed fresh confirmation,
interrupted reservation recovery, duplicate identity refusal, relocated
verification and tamper refusal. It establishes no actual BIRD
fault, source change, hardware qualification or performance conclusion.
