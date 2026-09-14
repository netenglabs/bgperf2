# Repetitions, order and the pass summary

How a matrix becomes an ordered list of runs, and what the passes of one cell are allowed to say about each other.

**Read this before editing:** `bgperf2.py` (`expand_batch_cells()`, `batch_report_rows()`, `bench_output_prefix()`, `create_batch_graphs()`), `summary.py`, `graphs.py`, `scripts/timing_variance_review.py`, `scripts/check_block10_configs.py`

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

## Pooling the passes of a partial repetition

A campaign block does not always repeat the whole of what an earlier block ran. Block 10 repeats
three of Block 8's five screen scenarios, and within the peer sweep only the three 250-peer cells —
the 50-peer comparison lies inside the 1s resolution of `elapsed (s)` and no number of passes can
separate it, and the 500-peer comparison had two of its three rows excluded on `tester_health`,
which the plan does not allow expanding. Two rules hold that together, and each replaces something
that used to be implicit.

- **A cell's cross-pass identity is its axes and its target, never its ordinal.**
  `cell_identity_key()` drops `test`, `repetition` *and* `ordinal`. The first two are obvious; the
  third is the one that bites. `ordinal` is a cell's position within its own matrix, so it is stable
  across passes over the same matrix and only across those: dropping six of nine cells moves the
  survivors from ordinals 3–5 to 0–2 while they stay the same three cells, and keyed on ordinal they
  pool with nothing — each pass reporting three cells missing from the other two, every comparison
  stuck at one observation, which is the exact opposite of what a repetition block is for. Two cells
  of one matrix cannot share axes and target, because `check_batch_run_names()` refuses two targets
  in one test that share a run name, so nothing is lost by dropping it. Report order is unaffected:
  `build_groups()` takes the ordinal from the first pass that holds the cell.
- **A pass that runs part of a series must declare what it covers**, and the declaration is checked
  in both directions. Dropping ordinal from the key also drops what ordinal was quietly doing —
  catching a matrix that moved between passes with nothing saying so — so that check moves somewhere
  it can be stated rather than inferred. A pass entry's `covers` names the identity fields its cells
  all share; a cell inside that coverage which the pass does not hold is still missing work and is
  reported, and a cell the pass holds which its coverage excludes is refused, because otherwise the
  declaration is decoration and a config that ran more than was asked has its extra row pooled into
  a comparison nobody planned. A pass with no `covers` is expected to hold every cell of its series,
  exactly as before.

Three consequences follow from dropping `ordinal`, and each was found by review rather than
foreseen.

- **A matrix axis lists each value once.** `neighbors: [250, 250]` produced two cells with distinct
  ids and *one* cross-pass identity, so `build_groups()` kept whichever it read last and published
  `n` as though the other run never happened — where `ordinal` used to keep them apart.
  `check_batch_test()` refuses a repeated value now (`repetitions:` is the mechanism for measuring a
  cell twice, and it names its passes), and `build_groups()` reports a collision anyway, because a
  progress file written before that guard can still hold one.
- **An execution position is comparable only across passes of the same length.** Pass 1 of the peer
  sweep has positions 1–9 and passes 2–3 have 1–3; sorted onto one scale, the pass that ran first
  can come out "latest" purely because its matrix was larger, and `order_relation()` would publish
  "rises with position" off an artifact of matrix size. It is withheld by name for a series whose
  passes ran different-sized matrices — a relation that cannot be read is not a relation of
  `neither`.
- **What a series' caption promises has to be true of every cell under it.** `screen-peers` is
  repeated *in part*, so three of its nine cells have three observations and six still have one.
  Dropping "(one observation per cell)" because the scenario gained passes promises a dispersion for
  rows that do not have one; the caveat says which cells were repeated instead.

And one about the selection document: **a selection is a plan, and what may be asked of it depends on
whether the block it plans has run.** Before, the question is whether it adds an observation — asking
for three where three already ran is refused. After, the question is whether it was *carried out*,
and asking the first question again fires on the selection being executed: Block 10 **is** passes 2
and 3 of the scenarios its own selection names, so every entry reported "asks for 3 passes and 3
already ran". Simply excluding the planned block's passes fixes that and costs the guard entirely —
the count would be pinned at 1 forever and a later selection could never be refused. The check
changes question instead, and the second question catches a block that ran fewer passes than the
selection asked for, which nothing else here would notice.

The same split shows up one level out. `review_blocks()` checks COMPLETE markers, host class and
image ids for **the blocks the reviewed series actually read**, not for every block in the campaign:
under `--series`, demanding a marker on blocks whose rows nobody opened is a refusal about evidence
the review never looked at. And a block's own passes cannot be in the pooled read until that block
is accepted — which is why Block 10 guards its matrix with `check_block10_configs.py`, a pure
document check that the cells each config runs are exactly the cells its selection names and that
the passes of a comparison differ in the test `name` and nothing else. The pooled read of those
passes happens at acceptance, not during the block.

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
