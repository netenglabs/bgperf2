# Repetitions, order and the pass summary

How a matrix becomes an ordered list of runs, and what the passes of one cell are allowed to say about each other.

**Read this before editing:** `bgperf2.py` (`expand_batch_cells()`, `batch_report_rows()`, `bench_output_prefix()`, `create_batch_graphs()`), `summary.py`, `graphs.py`, `scripts/timing_variance_review.py`

These are invariants, not background: every rule here was written because the obvious alternative was tried and published a wrong number quietly. `CLAUDE.md` carries the one-line index; this file carries the argument.

---

## Repetitions

One observation per cell says nothing about run-to-run variance. A test may declare
`repetitions: N`; `expand_batch_cells()` turns the matrix into the ordered list of runs, and
`batch_repetitions()` rejects anything that is not a positive int **before the first container
starts** — a `repetitions: 0` that ran nothing would otherwise be found hours in. `check_batch_test()`
does the same for the matrix axes, which had no such check: a test with no `filter_test` reached
expansion as a bare `KeyError` naming neither the test nor the key, which is what
`benchmarks/big-tests.yaml` did. An axis is required rather than defaulted, so a typo cannot quietly
run the matrix unfiltered.

- **A repetition repeats the whole matrix, not each cell.** Three back-to-back runs of one cell
  share a page cache, a thermal state, and whatever else the machine was doing a minute ago, so
  part of what they measure is that. Block order also means an interrupted batch holds one
  observation of everything rather than every observation of the first few cells.
- **A repetition is part of the run's *name*, not a column beside it.** Everything a run writes is
  named from `bench_output_prefix()` — `<prefix>.events.json`, `<prefix>.versions.json`, the six
  per-run PNGs — and those are written with `os.replace`/`open(...,'w')`, so a second pass under
  the same name silently replaces the first one's evidence and the CSV grows two rows nothing can
  tell apart. `create_graph()` needs it too: it keys the x axis off a dict of row names and appends
  one bar height per row, so rows sharing a name give it fewer ticks than heights — a wrong graph
  or a crash, depending on the matplotlib version, at the end of a batch that has already run for
  hours. The artifacts also carry `run.repetition` so a summary does not have to parse a label to
  group passes.
- **`bench_output_prefix()` is the one place that names a run's files**, for the same reason, and
  it must carry every dimension a batch iterates. `filter_test` was missing: the three policy cells
  of `benchmarks/2026-filters.yaml` all wrote `bird_2.19.2_bgpdump2_1050000_10.*`, so two thirds of
  that suite's per-run evidence was overwritten and no `run` dict recorded which policy the
  survivor came from. The periodic mid-run graphs were worse — built from `args.target` alone, they
  dropped label, version, filter and repetition. Both now use the same stem, and each dimension is
  appended only when set, so an unfiltered single-pass run keeps the name it has always had.
- **A cell id says what the cell is, never when it ran.** `ordinal` is its position within one pass
  and `repetition` says which pass, so raising a test from two passes to three does not move the
  ids of the two that already have results, and resume keeps matching once execution order can be
  permuted.
- **The id and the name must agree about a single-pass test.** Both say "no repetition" — the cell
  carries `repetition: None` and the id omits the key entirely. Suffixing only when `repetitions >
  1` while the id always said `repetition: 1` meant a completed single-pass batch whose config
  later gained `repetitions: 3` matched its stored pass-1 ids under `--resume`, reused those rows,
  and produced a CSV holding `bird` beside `bird #2` and `bird #3`. Omitting the key also means a
  single-pass id has exactly its pre-repetition shape, so `BATCH_PROGRESS_SCHEMA_VERSION` did not
  have to move and an in-flight batch from an older build still resumes instead of costing the
  operator every completed cell.

## Order

A test may also declare `order: shuffle` (default `matrix`) and, optionally, `seed: <int>`. A test
key outside `BATCH_TEST_KEYS` + `BATCH_TEST_OPTIONAL_KEYS` is rejected: `seeds: 7` under
`order: shuffle` would otherwise draw a fresh permutation every invocation while looking pinned,
and a misspelt `repetitions` runs one pass of a matrix someone asked three of. Matrix
order runs every cell of one target next to every other cell of that target, so anything that
drifts over a batch — a thermal ramp, a filling page cache, a neighbour's job that starts an hour
in — lands on the axes as a pattern and comes back out as a difference between the daemons.
Shuffling does not remove that drift; it stops it lining up with one axis.

- **The permutation is inside a pass, never across one.** A repetition stays a block for the
  reason above, so dealing the passes together would take that back. Each pass draws its own
  permutation — one permutation reused for all three applies the same position bias three times
  and the repetitions cannot average it out.
- **The order is a digest of the seed and the cell id, not `random.shuffle`.** The point of
  recording a seed is that the sequence can be rebuilt later, and a Mersenne Twister draw is a
  property of the interpreter as much as of the seed. `tests/test_batch_order.py` pins one seed's
  order so changing the keying scheme has to be deliberate.
- **The seed is recorded in the progress file before the first cell runs**, and `--resume` uses
  the recorded one. A seed written only on a cell's completion would be missing from exactly the
  batches that died early, and a resumed batch drawing a fresh permutation has run two orders,
  neither of which is the one it recorded. Only a *drawn* seed is recovered that way — a seed the
  config states is left alone, since editing it by hand is an instruction to re-sequence. An
  omitted seed is drawn rather than defaulted to a constant: one shared default is itself a
  permutation nobody chose. A `seed` under `order: matrix` is rejected rather than ignored.
- **Execution order is not report order.** `batch_report_rows()` emits the CSV and the graphs in
  matrix order whatever order the cells ran in, because `create_graph()` keys the x axis off the
  row names it sees and appends one bar height per row, pairing the two positionally — that only
  holds while each (peers, prefixes, filter) group arrives with its targets in the same order. A
  shuffled batch reporting in execution order would produce bars under the wrong labels, or a
  length mismatch, at the end of a batch that has already run for hours.
- Identity is untouched by the order: `ordinal` stays a cell's place in the matrix, so `--resume`
  matches its completed cells whichever way either pass ran.
- **A superseded sequence stays in the file.** The progress document is rewritten whole on every
  checkpoint, so a sequence dropped when the config is edited mid-batch leaves the record
  describing an order that some of its own completed rows did not run in. It moves to
  `previous_seeds` instead, and only when rows exist to describe. That covers a matrix pass
  resumed as a shuffle, not just a changed seed — a file naming no order at all was written before
  ordering existed, and is read as matrix, because that was the only order there was.

## Summarising the passes — `summary.py`

A batch writes `<test>.summary.json` beside its CSV: one entry per matrix cell, with the
distribution of that cell's passes. Pure and Docker-free like `contention.py`, `convergence.py`,
`churn.py` and `findings.py`, and it reads the stats row **by column name** — that row is positional for
`create_batch_graphs()` and has drifted by a column once already, so a summary keyed on index 12
would be arithmetic nobody could check. `docs/measurement-dictionary.md` has the field list.

- **The summary never replaces the rows.** Every pass keeps its CSV row and its own artifacts; the
  summary carries the observations it computed each statistic from, and which pass produced each
  one. A number whose inputs are gone is not auditable.
- **Nothing absent is published as a zero.** A withheld statistic is `null` with its reason beside
  it. `stdev`/`cv_percent` need two observations — a CV of 0 over one pass says the measurement is
  perfectly repeatable on the strength of never having been repeated — and `cv_percent` needs a
  positive mean, which `tester errors` never has in a good run. `stdev` is the **sample** (n-1)
  deviation: the population formula understates the spread of one, to exactly 0 at n=1.
- **`min` and `max` are observations and are not rounded**; the derived statistics are, to six
  places, so a 0.4 MB spread in `max mem (GB)` does not read as `0.0`.
- **A failed pass is counted and named, never averaged in and never silently dropped.** Dropping it
  would change `n` without saying so, which is the one thing a dispersion cannot survive; a pass
  that has not run is counted apart from one that failed, because one is a result and the other is
  unfinished work.
- **An unsampled extreme is not an observation, here as well as in `findings.py`.** `min_free`
  starts above every real value and `max_mem` at 0, so an untouched sentinel reaches the row as
  ~931,322 GB or as 0.0 GB; `unsampled_row_values()` names both in the row's own units (via the
  single `row_gb()` formatter, so the two cannot drift) and the whole column is withheld for that
  cell. One pass of three losing its sampler would otherwise publish a ~310,474 GB mean and a 173%
  CV on a 64 GB box, or an 87% CV on the target's peak — and `Container.stats()` has no `try` around
  its walk, with a `mem` that comes from a `.get('usage', 0)`. `min idle%` and `max cpu %` are
  deliberately excluded: 100 and a peak rounding to 0 are both values a real run can report.
- **A stored row that is not the header's width costs its own pass, not the document.** `--resume`
  onto a progress file written before a column was appended is a supported path — the schema version
  deliberately did not move for `max foreign cpu %` — and one short row indexed against the current
  header raises, which the wrapper turns into *no summary at all* for that test. Such a pass is
  `unreadable`, kept apart from `failed`. A right-width, wrong-layout row cannot be caught here at
  all, which is why `stats_header()` is the contract.
- **Passes that disagree about an image are not observations of one thing.** `target image`,
  `tester version`, `monitor version` and `required` are checked for agreement across the passes
  and any disagreement lands in `inconsistent` and in a printed warning — the gcov trap (a freshly
  built version beside a cached one) reached one layer up.
- **Grouping and reporting are in matrix order**, sorted by `ordinal` rather than left in the order
  they arrived, for the same reason `batch_report_rows()` is: execution order is a property of the
  run, not of the report, and a summary dealt in shuffle order would sit under a CSV and a set of
  bars that were not.
- **A summariser that raises costs the summary, not the rows.** It runs after the CSV is on disk and
  `publish_batch_summary()` catches — same rule as `write_event_artifact()` and its findings.
- **It is written before the first cell, then after each one**, and a non-resumed batch unlinks its
  predecessor's summary along with its progress file — otherwise a write that then fails leaves the
  previous run's document beside a rewritten CSV. Every call site prints a failure line, including
  the two that do not ask for the description: it is the only report that the document beside the
  CSV is not the one describing it.
- **The document must stay readable by a strict parser.** `json.dump` runs with `allow_nan=False`
  and a non-finite observation is published as its own repr — a bare `NaN` is rejected by jq and by
  most non-Python parsers.
- **Whether a cell has earned more passes is a named rule, not a reader's judgement.**
  `apply_variance_rule()` says two cells are separated when their medians differ by more than the
  sum of their standard deviations, **floored at the metric's resolution**, applied to `elapsed (s)`
  alone. That floor is not a detail: `elapsed (s)` is whole seconds counted off the monitor's 1s
  poll loop, so passes of one cell agree exactly all the time, `stdev` is 0.0, and an unfloored
  rule clears any gap at all — publishing `separated` on one rounding boundary, in silence, for
  exactly the sub-second comparisons it exists to catch. `METRIC_RESOLUTION` is pinned against
  `MONITOR_POLL_INTERVAL_S` by `test_stats_contract.py`, since `summary.py` must not import
  `bgperf2`. Unnamed, the decision to rerun
  belongs to whoever read the CSV and disliked it, which reruns the surprising results and turns a
  benchmark into a search for the expected answer. It is comparative rather than a CV threshold
  because no CV means the same thing twice: 2% is nothing between targets 40% apart and fatal
  between ones 0.12% apart, which is what FRR 8.5, 9.1 and 10.0 were over a 95s MRT run. Three
  details are load-bearing. It is decided against **every** rival sharing the cell's (peers,
  prefixes, filter) axes and reported against the *binding* one — the smallest margin — since
  separating a cell from its nearest neighbour separates it from the rest only if every rival has
  the same dispersion, and `create_graph()` draws the whole group side by side. Rivals that have a
  dispersion are preferred, so one mostly-failed cell cannot sit between two unseparated ones and
  silently mute both — but preferred is not ignored. `separated` means *distinguishable from every
  cell drawn beside it*, so every rival that cannot be judged is a rival that cannot be cleared:
  each verdict names its unjudgeable rivals, and `separated` alone is withheld when one of them is
  at least as near as the binding rival, or has no observation at all. That one claim was got wrong
  three times, once per path into it — the rival that decided the verdict, the rival skipped for
  having no dispersion, the rival skipped for having no median — because each fix was written
  against the case instead of against the claim. The companion invariant, collapsed three times the
  same way: **a pass that failed and a pass that has not run are never described by one clause, at
  any level of aggregation** — one is a result to investigate, the other unfinished work, and only
  the first is something an operator can act on. And `EXPANSION_PASSES` (5) is a floor
  under the recommendation, never a cap: telling a `repetitions: 7` test to rerun at five would
  discard observations, and a cell with fewer observations than passes is told about its shortfall
  *beside* that count, never instead of it — fixing the failed pass and rerunning at the count you
  already had comes back unseparated again. Where a pair's two cells disagree, the printed line is the more
  actionable verdict, never the lower ordinal: a shortfall to investigate must not lose to "more
  passes will not decide it" on matrix position alone.
- The printed block is `elapsed (s)` and `total time` only, and nothing at all for a single-pass
  test; the cell is named by `batch_cell_description()`, since the run name alone is the target and
  two cells of one target differ only in their axes.

**Two targets in one test may not share a run name.** A run name is label, else target plus
version — nothing else — so entries differing only in `threads`, `mrt_file` or `image` are one
name, and that is the stem `bench_output_prefix()` builds every artifact from, the `name` column
of the CSV, and the x label `create_graph()` pairs bar heights against. `check_batch_run_names()`
refuses them before the first container and says to add a `label`; `expand_target_versions()`
already does the same thing along the version axis by labelling each version. This is also why
two identical target entries are refused rather than treated as two observations — that is what
`repetitions` is for, and it names its passes.

Note the container work directory (`<--dir>/<bench-name>`) is wiped at the start of every cell, so
raw daemon and tester logs only ever survive for the run in progress — that is true across cells
already, and repetitions do not change it. The published artifacts are the durable record.
