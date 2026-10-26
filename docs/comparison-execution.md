# Staged comparison execution

Use `comparison-start`, `comparison-step` and `comparison-review` when a bounded
comparison needs preparation, explicit reviews and synchronous operational
checks. These commands use the existing frozen comparison plan and comparison
report schemas. Existing `compare` behavior is unchanged. No scheduler or
private campaign checkout is required.

Create a plan as described in [comparisons](comparisons.md). The plan fixes the
serial sequence, repetition count, diagnostics and worker timeout. The staged
workflow always requires the selected correctness assertions and an exact
worker-budget match. It never retries a stopped session, extends a worker
budget, downloads an image, builds a target or repairs host setup.

```sh
venv/bin/python recipes.py comparison-start /absolute/aa-plan.json \
  --workdir /absolute/new-aa-work --results-dir /absolute/new-aa-results \
  --observer-window
venv/bin/python recipes.py comparison-step /absolute/new-aa-results
```

Start checks both selected targets using the ordinary recipe prerequisites
before creating the new output roots. These verify image availability and
disk-backed destinations and disclose available memory and storage; unknown
recipe capacity requirements remain unknown. They do not establish hardware
suitability or authorize a campaign-specific root-backed disk exception. All
supplemental output directories are created before a worker can start.

Each step holds an exclusive session lock and executes at most one worker
through the public recipe controller. It waits for collection and cleanup,
verifies the original package and frozen bindings, evaluates assertions and
the worker budget, requires an explicit empty runtime `cleanup_errors` list,
and optionally writes and assesses an observer-window supplement. Only then
does it write an immutable comparison checkpoint and return. There is no
background postprocessing race. Original packages remain intact. The ledger
distinguishes attempts that failed or were interrupted from attempts never run;
a completed worker whose assessment failed remains a completed original package
in a stopped session.

`--observer-window` requires exactly the four worker-budget assertions exported
for session establishment, injection completion, observer route count and
experiment completion. It applies the existing [observer timing](observer-timing.md)
resolution screen; legacy whole-second timing fields are unchanged. Subsequent
steps reverify original packages, prior assessments and source attempt identities.
Missing supplements are errors, never silently recreated.

After the first attempt, the session waits in `first_review`. An external reviewer
must inspect the checkpoint report, package, assertion outcomes, supplements,
pressure records (when selected) and cleanup evidence. Record their written
assessment explicitly:

```sh
venv/bin/python recipes.py comparison-review /absolute/new-aa-results \
  --reviewer 'reviewer identity' --evidence /absolute/first-review.txt \
  --decision accepted
venv/bin/python recipes.py comparison-step /absolute/new-aa-results
```

Repeat step explicitly for each remaining attempt. After the frozen sequence,
the session waits in `final_review`; use the same review command with the final
written assessment. Review receipts bind the plan, immutable report, execution
policy, selected supplements/pressure records and copied reviewer evidence by
hash. The tool records an external attestation: it cannot establish that the
reviewer is independent. A rejection stops the session. A command interruption
or crash leaving stage `running` also refuses further execution; there is no
automatic resume or repair path.

For an A/A-to-A/B review gate, create the second session with
`--prior-review /absolute/new-aa-results/reviews/final.json`. Start requires a
verified accepted final review, a fully completed series with passed assertions,
the same canonical recipe and baseline target. Prior original attempt identities
cannot supply the new series. Omitting this option makes no claim about a prior
series or review. A scheduler, if used externally, must respect these explicit
review pauses and stopped states.

## Optional operational pressure screen

There is no default CPU threshold, no requirement for zero utilization, and no
implicit host-specific policy. Select an explicit JSON policy using
`comparison-start ... --pressure-policy /absolute/pressure.json`:

```json
{
  "sample_seconds": 5,
  "max_gap_seconds": 7.5,
  "busy_percent": 75,
  "cpu_psi_percent": 20,
  "consecutive_intervals": 2,
  "min_memory_bytes": 17179869184
}
```

These are illustrative operator-selected bounds, not recommended universal
thresholds. Sampling intervals must be between one and 60 seconds. The screen
records the aggregate CPU line, `MemAvailable` line and CPU pressure text from
the Linux procfs exposed to the controller; it
does not establish that this is an unrestricted host view. Busy CPU is computed
from aggregate counter deltas excluding idle and iowait. A severe interval
requires both selected busy CPU and CPU PSI `some avg10` bounds; a sustained
streak or any memory-floor breach latches refusal. One busy core on a many-core
host can pass. Missing, malformed, backward or excessively spaced observations
refuse continuation.

The controller records an initial sample before launch (which can screen memory,
but has no CPU delta yet), then samples while waiting and once at completion.
A selected live breach or monitoring failure gracefully terminates the owned
recipe controller and waits for its collection and cleanup. It does not kill
unrelated jobs or repair the host. This cleanup wait does not extend the worker
budget and intentionally has no forced-kill deadline that could abandon owned
resources. Original pressure records are replayed before another step and their
reviewed contents are hash-bound.

This workflow supports noise and resolution discovery. Operational screens and
review acceptance are not performance conclusions. Regression policy remains
disabled and performance qualification remains `not_assessed` in the unchanged
comparison reports.
