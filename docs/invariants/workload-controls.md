# Workload controls

What `bench`/`batch` may be asked to run, and the guards that refuse the rest.

**Read this before editing:** `prefix_length.py` (the synthetic prefix walks and their refusals), `cpu_pinning.py` (pure CPU lists and role-pinning validation), `recipes.py` (portable source validation), `recipe_worker.py` (recipe CPU layout forwarding), `recipe_preflight.py` (online CPU availability), `batch_cells.py` (pure matrix construction, prefix scope and legacy identities), `run_lifecycle.py` (run orchestration), `bgperf2.py` (argument guards, `bench()`, `batch()`, `batch_cell_args()`, `check_batch_test()`, `bench_output_prefix()`), `base.py` (`gen_conf()`, `gen_paths()`, `Target.scenario_neighbors()`, `Target.policy_loaded_failure()`), `churn.py`, `policy.py`, `import_policy.py` (the generated import policy and its expected counts), `policy_render.py` (its BIRD and FRR text), `bird.py` (the churn protocol, the reload command and the policy-loaded check), `frr.py` (the import policy's config and its policy-loaded check), `tester.py` (`check_policy_blocks()`, `write_policy_block_protocols()`, `carries_policy_blocks()`, `BIRDTester.configure_neighbors()`)
`recipe_minimization.py` governs explicit selected-cell projection and bounded peer/prefix reductions.

These are invariants, not background: every rule here was written because the obvious alternative was tried and published a wrong number quietly. `CLAUDE.md` carries the one-line index; this file carries the argument.

---

## Peer scaling

`gen_conf()` gives each neighbour its own `gen_paths(p)` off one shared iterator, so peers get
*disjoint* prefixes and the table is `n * p`. **Session count and table size are therefore one
axis**, and every synthetic matrix in `benchmarks/` sweeps both at once: `2026-core-synth.yaml`'s
`neighbors: [10, 50]` x `prefixes: [50_000, 100_000]` holds 500k, 1M, 2.5M and 5M routes, so
nothing downstream can separate "50 sessions were slower" from "five times the routes were slower".

## `--prefix-scope total` — read `-p` as the whole table

`--prefix-scope total` (batch: `prefix_scope: total` on a test) reads `-p` as the whole table and
splits it across the peers instead. `benchmarks/2026-peer-scaling.yaml` is the shape it exists for.

- **It is normalised to a per-peer count before anything reads it** -- in `bench()` beside the
  image resolution, and in `expand_batch_cells()` for a batch. `-n 50 -p 100000 --prefix-scope
  total` and `-n 50 -p 2000` are the *same workload* and must produce the same scenario (verified
  byte-identical), the same cell identity, the same row and the same bar. Everything downstream is
  keyed on the per-peer number: the CSV column is literally `prefixes per peer`,
  `bench_output_prefix()` names artifacts from `prefix_num`, and `create_graph()` groups by it. A
  scope surviving into those would be a fourth dimension in all three. The batch sets
  `a.prefix_scope = 'per-peer'` on the synthesized args for that reason -- passing the test's scope
  through as well would divide twice.
- **The division must be exact, and an inexact one is refused before the first container.** A
  remainder means the peers do not all offer the same table, so `prefixes per peer` is true of none
  of them, each neighbour's `check-points` differs, and the monitor's stops being `n * p`.
  `check_batch_test()` checks every (neighbors, prefixes) combination, not just the first: 1,050,000
  divides by 10 and 25 but not by 9, and finding that out at cell three is hours lost. The message
  names peer counts and prefix counts that would work.
- **It is refused for the MRT testers, on the batch path as well as the CLI.** `gen_conf()` sets
  the monitor check-point straight from `-p` for `gobgp` and `bgpdump2`, so it is already the whole
  table. Refusing it only on the CLI let a batch divide a 1.05M-prefix MRT table by its peer count
  and report CONVERGED at a tenth of it, silently -- `check_batch_test()` therefore reads the
  tester from the test's targets, and one MRT target refuses the whole test, since `prefixes` is a
  single axis shared by every target.

**A rule that refuses something must be applied at every entry point, and there are four:**
`bench`, `bench -f`, `config`, and `batch` (which synthesizes args and so bypasses argparse *and*
`bench`'s own guards for anything it pins). The peer-scaling change got this wrong seven times in
review, each time refusing on one path while another accepted it silently -- three of them in
guards added by an earlier round of the same review, because a guard is code and gets the rule as
wrong as the code it guards. Note `gen_conf()` routes on `tester_type not in ('exa', 'bird')`, so
anything unrecognised is an MRT injector: a batch target's `tester_type` is validated against
`TESTER_TYPES` (the CLI's own `choices`) because a batch target bypasses argparse. A default for a batch
target belongs in `BATCH_FIELD_DEFAULTS` and must be **read** through `batch_target_field()`, never
written into the target dict: that dict is part of the cell identity, so filling a default into it
renames every completed cell of every in-flight batch. **A default needs its own guard**, because it
can replace a loud failure with a quiet wrong answer -- defaulting `tester_type` to `bird` turned a
target that named `mrt_file` and no generator from an immediate `invalid mrt_injector: None` into a
synthetic run that never read the MRT file, converged, and published a row. **A `file:` target
takes no defaults at all** (`batch_target_defaults()`): its generator is inert, but `tester_type`
still reaches `write_provenance()` and `bench_output_prefix()`, so a default there writes
`"tester_type": "bird"` into the manifest of a run that played back MRT. Provenance never guesses. `batch` is the path that
matters: a CLI mistake costs one run, a batch mistake costs a matrix, and nobody is watching it.

A test key written under a *target* is refused (`BATCH_TEST_ONLY_KEYS`). There is no allowlist of
target keys -- `batch_cell_args()` reads a fixed field list and ignores the rest -- and every knob an operator
sets is a target key, so a test key one level too deep is the natural slip and fails silently:
`prefix_scope: total` under a target runs that target at `neighbors x prefixes`, converges, and
writes rows that read as a peer sweep.

## `--path-diversity D` — make the target choose a best path

`--path-diversity D` (batch: `path_diversity: D`, a *test* key) is the other half of
that separation: it deals the peers into groups of `D` and gives each group one shared prefix
block, so the fleet offers `n * p` paths for `(n / D) * p` distinct prefixes and the target
actually has to select a best path. Without it every route the target learns is the only path it
holds for that prefix, so a run measures reception and re-advertisement and publishes it as
convergence -- and best-path selection is one of the three things BIRD 3's worker threads exist to
parallelise.

- **The monitor's check-point counts distinct prefixes, not offered paths** (`groups * p`), since
  the monitor reads what the target *re-advertises* and that is one best path per prefix.
  `path_diversity_groups()` is the only place that arithmetic lives, because the block a neighbour
  is given in `gen_conf()` and the check-point are far apart and must agree: too high never
  converges, too low reports CONVERGED on a fraction of the table. Per-neighbour `count` stays `p`
  -- a peer still offers `p` and the target still accepts all of them, since BGP holds the losers.
- **The default renders the scenario it always did.** `gen_paths()` takes an optional `block` and
  the caller omits it at diversity 1 (verified byte-identical); the cell id omits the key at the
  default too, so an in-flight batch from an older build still resumes.
- **The block is keyed on the count of configured neighbours, not the loop index**, which skips the
  target's and monitor's addresses.
- **Refused, at all four entry points, for**: an MRT generator (no paths are synthesised there),
  `-f`/a scenario target (the file states its own paths), a diversity above the peer count, and an
  inexact division -- the remainder group would announce a block with fewer competing paths than
  the rest. `check_batch_test()` checks every peer count on the axis, not the first.
- **`--prefix-scope total` and `--path-diversity` are refused together**, deliberately: "the whole
  table" then has two readings differing by exactly `D` (paths offered vs. distinct prefixes held),
  and the reading would decide the `prefixes per peer` column, the cell identity and every artifact
  name. Choosing one is its own change set.
- **It is in the artifact stem (`pd<D>`) and in `run.path_diversity`, not in the CSV.** Nothing
  else in `bench_output_prefix()` carries it -- a disjoint run and a competing one have the same
  peer and per-peer prefix counts -- so two tests differing only in it would overwrite each other's
  artifacts, which is the `filter_test` failure. A `-f` run records `null`: provenance never
  guesses about a workload bgperf2 did not build. **Both `run` blocks carry it** --
  `write_provenance()` and `write_event_artifact()` -- because the events artifact is what
  `findings.py` reads, and stating `peers` and `prefixes_per_peer` alone describes a table five
  times the one the target held, uncorrectably. Same rule as `repetition`.
- **A refusal names the fault, not the nearest rule it trips.** The scope cross-check tests against
  `PREFIX_SCOPES`, so a typo'd `prefix_scope: totl` beside a diversity gets `unknown prefix scope`
  from the function that owns that diagnosis, rather than being blamed on the combination -- which
  sends the operator to remove the diversity and meet the same typo again.

## `--receivers N` — export fan-out

`--receivers N` (batch: `receivers: N`, a *test* key) is export fan-out: N sessions the
target advertises its whole table to and which announce nothing back. Without it a run has exactly
one export session -- the monitor -- so what a table costs to *send* and what it costs to *receive*
have been one number in every result this tool has produced, and decoupled exports are the third
thing BIRD 3's worker threads exist to parallelise.

- **A receiver is not a route source.** It is a top-level `receivers` key in the scenario, never an
  entry in `conf['testers']`: `get_test_counts()` reads the testers, so a receiver is never waited
  on for a table it will never send, and the monitor's check-point and the whole ingress side do
  not move with the receiver count. Verified: 2 peers x 10 prefixes gives `required` 19 and
  `received` 20 with 0 receivers and with 3.
- **It is not a second monitor.** The monitor is the single instrument every published timing is
  read from; a second one polled into the same queue would be an unlabelled second `recved` series.
  `Receiver(Monitor)` inherits the gobgpd config, the startup script and the establishment wait, and
  **refuses `stats()`** so that cannot happen by accident. It *is* read --
  `accepted_prefixes()`, see `docs/invariants/export-timing.md` -- but into a recorder and an
  artifact section of its own, never into the queue the row is built from.
- **`Target.scenario_neighbors()` (base.py) is the one place that knows a target has three kinds of
  session.** Eight target modules built `flatten(testers) + [monitor]` independently, and a receiver
  added to seven of them is a target quietly exporting to fewer sessions than the run claims.
  `sort=False` for `frr.py` and `gobgp.py`, which never sorted -- ordering in a generated config is
  cosmetic and changing it puts an unrelated diff in front of anyone comparing against an older run.
  `tests/test_export_fanout.py` asserts no module still builds that list by hand.
- **Receivers are established before any generator launches**, since a session that came up mid-run
  would take a partial table and put the export work at a moment nothing recorded. Their wait is
  *not* folded into `monitor (s)`: that column is the instrument coming up, and a `--receivers 20`
  run would otherwise read as a slow monitor in every row.
- **They are removed like testers** (`bgperf_receiver<i>`), because `batch()` reuses the process per
  cell and a leftover fails the next cell on a duplicate name.
- **Their addresses continue the peers' own index**, so neither the address nor the AS number
  (`1000 + i`) can collide whatever the peer count -- a separate region would be safe only until
  someone ran enough peers to reach it.
- Unlike `--path-diversity` and `--prefix-scope`, it is refused for **nothing** except a bad count
  and `-f`/a scenario target: a receiver is a target-side session, so an MRT run has the same reason
  to want fan-out as a synthetic one. Stem gets `rx<N>`, both `run` blocks record it, `-f` records
  `null`.
- **A receiver follows the monitor's lifecycle, not the testers'.** `--repeat` reuses the *tester*
  containers and has never reused the monitor: `Container.run()` removes and recreates anything it
  finds by name, and the target is rebuilt under `-r` too, so every receiver session has to re-peer
  regardless. Receivers are therefore built and established on **every** run. Skipping them under
  `-r` -- the first version -- meant the count the target was configured for, the count in the
  artifact name and the count in both manifests were three claims about sessions that did not
  exist, and the establishment wait that keeps the export work from landing mid-run went with them.
  `surplus_receiver_names()` covers the one case recreating by name does not: a run asking for fewer
  than the last built leaves the rest up, `--repeat` skips `remove_old_containers()`, and a
  dynamic-neighbour target's `neighbor range 10.0.0.0/8` accepts every one of them.
- **No call that asks the world may run before the guards that read only the command line.**
  `bench()`'s argument guards are covered by a suite that deliberately needs no Docker daemon, so a
  Docker call ahead of them makes that suite depend on machine state -- it went green or red
  according to whether a verification run had left receiver containers up. `target_image()` was
  doing the same thing and older: a mistyped `-p` was answered by `ImageNotBuilt` on a host with no
  daemon or no built image rather than by the typo. Image resolution now sits after every pure guard
  and still above the teardown, which is the invariant
  `test_image_resolves_before_containers_are_torn_down` was always about.
- **The fan-out is in `min free mem (GB)`, and that column feeds a confounder.** Each receiver holds
  its own copy of the table on the same host, and a low value becomes `findings.py`'s
  `low_free_memory`, which withholds `limiting_component` -- so a run can be told its intervals
  include page pressure caused by memory it consumed on purpose. `describe_export_fanout_cost()`
  says so before the run and deliberately **does not estimate the size**, for the reason
  `LOG_SPACE_FLOOR_GB` is not an estimate: what a GoBGP holds per route depends on the paths, and an
  invented number gets quoted back as though it had been measured.
- **A `-f` scenario's own `receivers` key is validated where the file is parsed**
  (`scenario_receivers()`). `resolve_receivers()` guards every path that *builds* a scenario; this
  guards the one path that is handed one, so `receivers: 3` written into a scenario file is refused
  by name instead of reaching `enumerate()` as a bare `TypeError`.

## `--churn-prefixes C` / `--churn-bursts B` — make a converged table move

`--churn-prefixes C` and `--churn-bursts B` (batch: `churn_prefixes` / `churn_bursts`, *test* keys)
are the fourth workload control: once the run has converged, the last `C` prefixes of every peer's
own list are withdrawn and re-announced, `B` times. Every run this tool has published measures a
table arriving at a daemon that has never seen it, and a router spends almost none of its life
doing that -- it spends it holding a table while parts of it move, which is removing routes from a
loaded table, re-running best-path selection for every prefix that had a competing path, and
withdrawing and re-advertising on every export session.

- **A burst is switched, not reconfigured.** The block goes into a `protocol static churn` of its
  own in each peer's generator config and a burst is `birdc -s <sock> disable churn` / `enable
  churn`, one `docker exec` for the whole fleet. A `configure` would re-read the whole file --
  several hundred thousand static routes on a real run -- so the interval measured would be BIRD
  parsing its own config rather than the target reacting to a withdrawal. Verified on
  `bgperf/bird:2.19.2` and `:3.3.2`: both answer exactly `churn: disabled` / `churn: enabled`, and
  `churn: already disabled` for a protocol in that state, which is **not** success -- the sequence
  alternates, so reaching a `disable` on an already-disabled protocol means the previous `enable`
  was lost.
- **The block is the tail of each peer's own list.** A sampled block would need a seed, and a seed
  is a fourth dimension in the cell identity, the stem and the manifest -- what `--prefix-scope`
  and `--path-diversity` both refuse to become. Taking the tail also keeps the block *shared* under
  `--path-diversity`: peers in a group are handed the same list, so they churn the same prefixes
  and the target loses the prefix rather than falling back to a surviving path. That is why the
  monitor-visible count is `groups * C` and not `n * C`; `churn_operation_counts()` publishes both,
  because reporting only the second understates a diversity-5 fleet's work fivefold.
- **The two halves of a burst are timed separately.** Dropping routes and re-selecting/re-exporting
  them are different mechanisms and the second is one of the three BIRD 3 parallelises, so one
  end-to-end number would hide what the workload exists to expose. `burst_s` *is* their sum -- the
  withdrawal's end and the re-announcement's start are one event -- and is published so a reader
  need not add two rounded numbers, never as a third measurement.
- **An interval of one poll is an upper bound, not a duration.** Both halves are bounded below by
  one poll by construction -- the command is issued just after a sample and the soonest it can be
  seen is the next. The printed line says `within the 1.0s poll resolution` for that case, on the
  same rule `print_tester_metrics()` applies to a sub-poll injection, reached from the other side.
- **A burst nobody performed is caught when it is issued.** `churn_failures()` checks every
  session's reply against the sessions asked about (not against the sections that came back), so a
  lost withdrawal is named immediately instead of arriving `CHURN_STALL_SAMPLES` later as a stall
  that reads as a stuck target.
- **A collapsed count is not a withdrawal.** Completion is `accepted <= converged - groups * C`,
  and a post-convergence sample of 0 -- a session that flapped, a target that restarted -- satisfies
  that for every block there is. Read as a withdrawal it would stamp the burst complete, issue the
  re-announcement against a table that never lost the block, and publish the session re-learning the
  whole table as `reannounce_s`. A count more than `CHURN_COLLAPSE_FRACTION` of the converged count
  below the floor fails the sequence by name instead, in either phase and between bursts --
  `ConvergenceTracker`'s `DROP_FRACTION` rule on the other side of convergence. The message names
  the phase, and distinguishes a collapse before the first burst from one between bursts, for the
  reason the stall message names its phase: the three send the reader to different logs.
- **A run that asked for churn and issued none still says so**, and that fallback lives in
  `write_event_artifact()` rather than at the `FAILED` branch that needs it. That branch is inside
  `bench()`'s monitor loop, which no Docker-free test can drive, so a fix written there passed the
  whole suite when review deleted it again. Anything that builds a run's document gets the
  fallback; a caller that supplies real evidence always wins.
- **`MSG` is rewritten through `row_message()`** -- commas to `;`, whitespace folded -- because a
  churn failure quotes birdc's own reply and `syntax error, unexpected CF_SYM_UNDEFINED, expecting
  CF_SYM_KNOWN` is two extra CSV fields, shifting `filters`, `max foreign cpu %` and all three
  provenance columns. Same rule as `Container.version_string()`. **`name` and `filters` are still
  unguarded**, which is pre-existing: a comma in a batch `label` shifts the row the same way, and
  the fix there is a guard in `check_batch_run_names()` rather than a rewrite, since a label also
  names every artifact the run writes.
- **The withdrawal target is exact, and a target that never held part of the block stalls rather
  than being tolerated.** Completion is `accepted <= converged - groups * C`, so a target holding
  fewer prefixes than the fleet offered -- the reason the monitor check-point carries a 0.99 factor
  in the first place -- can leave that count unreachable if any of the missing prefixes fall in the
  tail. The stall message names the count it held and the count it wanted, which is diagnosable; a
  tolerance would have to be a number nobody measured, and it would let a burst that only half
  landed be published as complete.
- **The published row describes the delivery, not the churn.** `elapsed (s)` is settled before the
  first burst, and the churn loop drains every other producer's queue messages without acting on
  them, so `max cpu %`, `max mem (GB)` and `min free mem (GB)` do not move with a burst's peak.
  `total time` *does* include churn, since it is wall clock. What a burst cost is in
  `<prefix>.events.json`'s `churn` section, per burst.
- **A sequence that did not complete leaves the run converged and says so in `MSG`.** The
  convergence measurement is real and marking the row FAILED would corrupt `elapsed (s)`, which is
  computed on the CONVERGED path; but a batch of churn cells whose rows all read as ordinary would
  say nothing about the second workload. `summary.py` reads `MSG` only for a row marked failed, so
  no summary changes.
- **Refused, at all four entry points, for**: any generator but synthetic `bird` (the handle is
  BIRD's own `birdc`), `-f`/a scenario target, `-r/--repeat` (which builds no tester objects at
  all, so nothing would issue the burst and nothing rewrites the generator config the churn
  protocol lives in -- the `--receivers` shape one round earlier), a block larger than the per-peer
  count *after* `--prefix-scope total` has divided, a burst count with no block, and
  `--filter_test` (a policy that drops part of the block makes the burst's completion count
  unreachable, so a correctly filtered run would be published as a stalled one -- a deferred
  definition, like `total` under `--path-diversity`). `check_batch_test()` checks every
  (generator, filter, peers, prefixes) combination, not the first.
- **One rule cannot be checked before the run**: the converged count is not known until the table
  is delivered, so a run that accepted fewer prefixes than it offered can reach a block the flag
  guards passed. `ChurnBurstTracker` refuses it there and the sequence is reported incomplete
  rather than raising -- by then the convergence measurement is the thing being preserved.
- Stem gets `ch<C>x<B>`, both `run` blocks record both numbers, `-f` records `null`. Not a CSV
  column, for the reason `--path-diversity` is not.

## `--policy-reload-blocks N` — change the policy over a table already held

`--policy-reload-blocks N` (batch: `policy_reload_blocks: N`, a *test* key) is the fifth workload
control and the last of Phase 5A's: once the run has converged, an import policy rejecting the last
`N` of the fleet's prefix blocks is installed on the target and applied with that daemon's own
reload command. Churn makes a converged table move; this makes the *policy over* a converged table
move, which is the thing an operator does most often and the thing nothing here has measured. The
daemon re-reads its config, re-evaluates its import policy against routes it already holds, and
withdraws the rejected ones from every export session, with the sessions staying up.

- **The workload is stated in blocks, not peers, and whole blocks are rejected.** A block is the
  group `--path-diversity` deals the fleet into -- one peer per block at the default. Rejecting
  *part* of a shared block leaves the prefix behind a surviving path, so the target does real
  best-path work and the monitor's count does not move at all: the reload could never be observed
  to complete. Same reason `split_churn_paths()` shares its block, reached from the other side.
- **The blocks are the tail, so there is no seed** -- churn's determinism rule. The set is
  rebuildable from the peer count, the diversity and the block count alone, and is published as
  `rejected_peer_asns` so nobody has to. The peers are ordered by **AS**, not by mapping order: a
  scenario is YAML and a mapping's order is not part of what the file means, while `gen_conf()`
  assigns the address and the AS from the same index it keys the diversity block on.
- **The expected count is exact and measured down from what the run converged on**, not from what
  the fleet offered -- the check-point's 0.99 factor exists because a target does not always hold
  everything offered to it. A target missing prefixes that fall *inside* a rejected block stalls,
  naming both counts, on `ChurnBurstTracker`'s rule: a tolerance would have to be a number nobody
  measured, and it would let a half-applied policy be published as an applied one.
- **`command_s` is published beside `reload_s`, never as it.** Measured on 3.3.2, `birdc configure`
  returns in ~20ms while the table drains over the following polls, so one number would credit the
  daemon with an instant reload. The started event is dated to the *sample* the reload was issued
  from rather than to the command's return -- the rule both poll loops already follow.
- **The CPU across the interval is the measurement, and an unsampled interval is `null`.**
  Re-evaluating a table is mostly CPU, and a reload finishing inside one poll would otherwise have
  no measurement beyond "it happened". Samples come from the target's existing stats thread and stay
  in the artifact -- `max cpu %` still describes the delivery, on churn's rule. `0.0` would publish
  an interval too short to sample as a daemon that did no work; those are different findings.
- **A collapsed count is not an applied policy**, in either phase, and the message names which.
  `DROP_FRACTION` and `CHURN_COLLAPSE_FRACTION` on a third side of convergence. Rejecting *every*
  block is refused up front for the same reason: an empty table cannot be told from an empty session.
- **What BIRD does was measured, not assumed** (2.19.2 and 3.3.2, two peers each). `birdc configure`
  holds the sessions up -- `Since` unchanged, both Established -- so these runs belong in the
  no-reset comparison `docs/policy-testing-plan.md`'s P4 asks for. But neither series re-evaluates
  purely locally: both answer a changed import filter by asking their peers for a route refresh, and
  each generator's `Export updates` doubled. `reload_s` therefore covers re-import as well as
  re-decision. Recorded as `mechanism` and `session_preserving` rather than hidden, and not
  comparable with a daemon that re-filters from its own stored routes.
- **Refused for**: a target with no reload mechanism (only BIRD has one -- read through
  `Target.SUPPORTS_POLICY_RELOAD`, never a list of names), an MRT generator (the policy selects a
  block by the peer AS bgperf2 assigned, and an injector replays the file's own paths), `-f`/a
  scenario target, `--filter_test` (the target's import filter is already the policy under test and
  the reload is written into the same place, so the run would change two policies at once), a churn
  workload, and a block count covering every block. `check_batch_test()` checks every
  (target, filter, peers) combination, not the first.
- **Refused alongside churn, deliberately**: both run against the converged table off the same
  monitor samples, so running both means fixing an order, and the second would take the first's
  outcome as its baseline with nothing in the row, the stem or the manifest saying which ran first.
  A deferred definition, like `total` under `--path-diversity`.
- **Refused under `-r/--repeat` too**, for a different reason than churn's. Churn needs the
  *generator* config rewritten; a reload is target-side and the target is rebuilt anyway, so the
  first version accepted `-r`. What breaks is the completion count: it is `blocks x prefixes per
  peer`, and repeat reuses whatever tester containers it finds while regenerating the scenario, so
  `-p` need not be what the generators are announcing. Measured -- `-n 4 -p 1000 -r` behind a
  `-p 10000` run converged at 40,000, expected the policy to leave 39,000, and the rejected peer
  took 10,000 with it. The collapse guard named it correctly, which is the point: it named it after
  a full run, and this is knowable from the command line.
- **There are three entry points here, not four.** `config` deliberately does not take the flag: a
  reload is a runtime action on the target and changes no part of the scenario, so `config` has
  nothing to emit for it and offering it there would print a scenario that reads as though it
  encoded a workload it does not.
- Stem gets `pr<N>`, both `run` blocks record it, `-f` records `null`. Not a CSV column, for the
  reason `--path-diversity` is not. The evidence key is `reload_complete`, not `complete`:
  `policy_reload_metrics()` derives a `complete` off the event stream, and
  `_policy_reload_section()` refuses a caller that lands on a derived name.

## `--prefix-length L` — the shape of every synthetic prefix

`--prefix-length L` (batch: `prefix_length: L`, a *test* key) sets the length of every synthetic
prefix. Every table before it was `/32` host routes, and a prefix-list over `/32`s does not cost
what one over a real table's `/24`s does, so the policy workload needs the shape to be a dimension.
Phase 1 supports 24 and 32 (`prefix_length.py`).

- **The `/32` walk is the historical one and is not touched.** It starts at 100.0.0.0 and does not
  skip reserved space, and it cannot start to: a 50 x 100,000 table already walks through
  100.64.0.0/10, so a skip at `/32` would change the prefixes of runs that have been published.
  `gen_mako_macro()` returns its preamble byte for byte at the default, the cell id, stem and
  description omit the key there, and `prefix_length.walk()` refuses to produce a `/32` walk, so a
  second definition of every published table cannot appear.
- **A shorter walk skips special-purpose space and the peering subnet.** It is drawn from 1.0.0.0
  up to multicast with `RESERVED_NETWORKS` taken out, because a daemon may drop a loopback or
  link-local prefix without counting it and the run would read as route loss; and the run's own
  `--local-address-prefix` is taken out, because a route covering it would capture the next hop
  every route is announced with. So is an explicitly set target or monitor address, which may lie
  outside that subnet: `prefix_length.walk_exclusions()` is the one list `gen_conf()` and every
  capacity check use. The scenario preamble imports `prefix_length.walk()`, so what a
  run announces and what the capacity check counted are one piece of code, and a `config -o`
  scenario renders the same walk under `bench -f`.
- **Capacity is checked against distinct prefixes, after the scope and the diversity.** The walk
  holds 14,461,947 `/24`s, and a table needing more is refused before any container -- for a batch,
  for every (target, peers, prefixes) combination on the axes, since each target may name its own
  peering subnet.
- **Refused, at all four entry points, for**: a value outside `SUPPORTED_PREFIX_LENGTHS` (`True`
  and quoted values included), an MRT generator (it plays back the file's own prefixes), ExaBGP
  (unpinned and unversioned images, so a run on one cannot say which generator it measured, and no
  per-block attribute filters for the policy workload), `-f`/a scenario target (the file states
  its prefixes), `-r/--repeat` (the reused generators keep announcing what they were started with,
  and the counts would agree, which is what makes it silent; a batch refuses a shortened test and a
  `repeat` target anywhere in it, in either order, as `--pin` does), `-e/--prefix-list-num` (its
  entries are `/32`s from 90.0.0.0, which match no route of another length and sit inside the walk),
  `--filter_test` (`filters/*` select by length -- `ixp` drops anything longer than `/24`, so it
  rejects a `/32` table whole and accepts a `/24` one whole; a batch checks every filter on the
  axis), native controlled cells (`native_mrt.synthetic_spec()`, whose post-run inspection expects the
  `/32` walk), and recipes (whose prefix-identity
  layout is contiguous `/32` host routes; their strict key list refuses it). Churn, the policy
  reload, path diversity and `--prefix-scope total` are length-agnostic -- they work on each peer's
  path list and on peer ASNs -- and are allowed.
- **`-r` is also refused the other way round**: a default-length `bench -r` after a separate `/24`
  run would reuse `/24` generators under a `/32` stem. `-r` rewrites no generator config, so the
  length a reused generator announces is the first `route` line of the config in the directory
  *that container* has bind-mounted (`reused_generator_prefix_lengths()`), read beside the
  reused-cpuset check and before the teardown. Through the container, never `--dir`/`--bench-name`:
  container names are fixed, so the generators may have been started from another directory. A
  route that cannot be read refuses rather than passing the check unmade. A batch meets this per
  cell rather than up front, because an earlier non-`repeat` cell rebuilds the generators and an
  up-front read would refuse batches that run correctly. A `-p` mismatch under `-r` remains the
  undetected hazard the policy-reload section measured.
- Stem gets `pl<L>`, both `run` blocks record `prefix_length` (`recorded_prefix_length()`), and `-f`
  and MRT playback record `null`, since neither table was synthesised. Not a CSV
  column, for the reason `--path-diversity` is not.

## The generated import policy — model and expected counts (policy phase 1)

`import_policy.py` builds the import policy for policy phase 1 (delivered 2026-11-27; its scope,
non-goals and candidate next phases are in the
[policy design](../plans/policy-testing-engine-design.md)) from the rule count, match type, hit
position, peers and prefixes per peer, and states the exact accepted count a target must reach. It
measures what a policy costs a daemon loading a table, never whether the daemon evaluates it
correctly: the exact count is a guard against unequal work, not a correctness check. `--tester-attributes`
puts the block attributes on the generator (below); `policy_render.py` writes the policy as BIRD
and FRR text; and `--policy-rules` puts it on a `bench` run's target (both sections after this
one).

- **The shape is fixed: guard, then the `N` generated rules, then default accept.** Each peer's list
  is cut into `BLOCKS_PER_PEER` (4) contiguous blocks and the **last block of every peer** is
  rejected by a guard evaluated before the generated rules. The guard has to be outside the `N`:
  under `miss` no generated rule may match, so a policy of generated rules alone decides every
  route by one default action, and rejects all or nothing. It goes *first* so the rejected routes
  leave before the generated rules, and every route that reaches them meets them exactly as `hit`
  says; last, it would make every rejected route evaluate all `N` whatever `hit` was. It uses the
  run's own match type, since mixed match types are a non-goal.
- **The tail of every peer, not the tail of the fleet.** Rejecting whole peers would give some
  neighbour an expected count of 0, which cannot be told from a session that delivered nothing —
  `--policy-reload-blocks`' empty-table rule, applied per checkpoint. Every peer therefore expects
  `p - p // 4` and loses `p // 4`, and fewer than 4 prefixes per peer is refused: the rejected
  block would be empty and the policy invisible.
- **The expected count depends on the fleet alone**, never on `N`, the match type or the hit, so
  every policy cell of one fleet shape expects the same count. With no policy it is the whole table.
- **Block attributes do not depend on the policy.** Each block carries an AS path of its own ASN
  and its class's ASN (private 32-bit), and communities naming the block and its class (private
  16-bit ASNs), so changing the policy never changes what the generator sends. The block's own
  value is there so the value a rule looks for is not the only one on the route. Those ASNs are
  bogons to `filters/*.conf`' `reject_bogon_asns()`, so a `filter_test` beside a policy would
  reject every route before the policy saw it — a second reason the two are refused together.
- **A block's `peer` is its walk slice, never an AS position.** The scenario draws slices in
  rendered neighbour order, which `yaml.dump` sorts by router-id text, so from ten peers on the
  AS-1010 peer holds slice 0. `gen_conf()` therefore deals each neighbour its blocks with
  `scenario_policy_blocks()`, in sorted router-id text order, as a `policy-blocks` list in the
  scenario; the generator renders that list and derives nothing from its AS or its addresses.
- **The generator sets the attributes once per route, at load.** `BIRDTester` writes one static
  protocol per block (`policy_block<k>`) whose own import filter prepends the block's path and adds
  its communities, never a filter on the BGP session that would run again on every export. It
  accepts every route, so the static `imported` counts still sum to the peer's whole table and the
  offering counters are unchanged. A scenario with no `policy-blocks` writes the one unnamed static
  protocol byte for byte as before.
- **`--tester-attributes` (batch: `tester_attributes: true` on a test) turns them on with no
  policy on the target**, so what carrying them costs the generator is measured before any policy
  cost is read beside it. `import_policy.resolve_tester_attributes()` holds the refusals, applied by
  `bench`, `config` and `check_batch_tester_attributes()` over every target, filter and fleet on
  the axes: any generator but BIRD, `--path-diversity` (a shared prefix would carry two blocks'
  attributes), churn (its tail cuts across the blocks), `filter_test` (the private ASNs are bogons),
  `--policy-reload-blocks` and the scenario filter counts `-a`/`-e`/`-c`/`-x` (each a policy on the
  target, a second variable), and a fleet the blocks cannot number. `-f` has nothing to attach and
  is refused at `bench` and in batch; native controlled cells refuse it.
- **Attributes cost the target, not the generator, so a policy is read against the
  attributes-only run, never plain permit-all.** Measured 2026-11-25 on BIRD 2.17.1 target and
  generators, 10 peers × 500,000 prefixes at `/32` and `/24`, two interleaved repetitions each.
  - The target set the pace either way. The generators' sockets held over 1 MB unsent for 84–94%
    of every send window, the target sat flat at about 1.24 cores, and the generators used less CPU
    with attributes (8.3–8.5 cores against 9.5–9.8).
  - Target intake fell from about 263k to 222k prefixes/s at `/32`, and from 264k to about 212k
    at `/24`, and elapsed time rose from 22–24 s to 26–27 s.
  - Wire bytes rose only 5% at `/32` (6.0 to 6.4 bytes/prefix) and 13% at `/24` (4.8 to 5.5). The
    extra time is therefore the target's per-route attribute handling, not update size. These byte
    counts include the testers' ACKs for the table re-advertised to them, so they are upper bounds.
  - An earlier, quieter set measured a larger penalty, about 270k to 200k prefixes/s. The set
    reported here ran at load average 8–10.
- A scenario file that
  carries `policy-blocks` itself is checked before the teardown (`check_scenario_policy_blocks()`):
  the counts must partition each peer's paths, with no churn block, on a BIRD generator, since any
  other drops them silently.
- **Under `-r` it is refused in both directions**, as `--prefix-length` is: with the flag outright,
  and without it when a reused generator's config, read through that container's own bind mount,
  holds a `policy_block` protocol (`reused_generators_with_attributes()`). Across a batch,
  `check_batch_prefix_length_and_repeat()` refuses a `tester_attributes` test beside a test with a
  `repeat` target, in either order. It reaches the stem as `ta`, both manifests' `run` blocks as
  `tester_attributes` (`null` under `-f` and for MRT playback), and the cell identity only when
  set, so every existing id is unchanged. `gen_conf()` keeps its own refusal of a non-BIRD
  generator, diversity and churn as a last line. **Not covered: `-f` with `-r`.** Neither reused
  generator check runs for a scenario file, so `bench -f plain.yaml -r` after a `ta` (or `/24`) run
  sends what the reused generators were started with while the manifests record `null`.
- **Filler rules reject values no route carries**: ASNs and communities from their own ranges, and
  prefixes in class E, which neither walk reaches. Prefix rules name the walk's own addresses
  through `prefix_length.walk_address_ranges()`, whose `/32` bounds are checked against the
  scenario preamble rather than being a second definition of the historical walk.
- `tests/test_import_policy.py` evaluates every route of a rendered `gen_conf()` table through
  guard, rules and default, for every match type and hit position at both lengths, and checks the
  deciding rule and the per-peer counts against the model.
- **`MAX_POLICY_RULES` is 65533, set by the tightest renderer**: FRR numbers route-map entries 1 to
  65535 and needs one for the guard, one per rule and one for the default. A cap one daemon could
  not render would make that cell a single-daemon result.

### The renderers — `policy_render.py`

- **One model statement is one test in each language, in the model's order.** BIRD gets one
  `filter` of one `if <test> then accept|reject;` per statement and a final action; FRR gets one
  `route-map` whose entries each match one list of their own, and a final entry with no match. A
  route therefore meets the same number of tests on both daemons and stops at the same one. Folding
  several rules into one set, or one FRR list shared by several entries, would make the two daemons
  do different amounts of work for the same `N`.
- **The tests are the same predicate in both languages.** Prefix: inside a cover *and* exactly the
  run's length (`P{L,L}`; `P ge L le L`, or plain `P` when the cover is `/L`, because FRR refuses a
  `ge` equal to the prefix's own length). AS path: containment anywhere on the path (`[= * A * =]`;
  `_A_`, whose `_` anchors at path boundaries so `4200000001` cannot match inside
  `14200000001`). Community: membership (`(a, b) ~ bgp_community`; one standard community-list
  line per value, because a line naming two communities requires both).
- FRR lists are written before the route-map that names them. The text is yielded line by line.
- `tests/test_policy_render.py` reads both renderings back with evaluators that accept exactly the
  forms written and refuse anything else, and runs every route of a rendered `gen_conf()` table
  through BIRD, FRR and the model: all three must decide at the same statement. Broken renderers
  (an unanchored FRR regex, a BIRD set without the length, `ge`/`le` dropped, swapped actions, the
  guard moved last, a denying default) each fail that test on its own. Exact-text fixtures pin
  small policies.
- **The daemons themselves were checked once, by hand, not by the suite**: `bird -p` on BIRD
  2.19.2, 3.3.2 and 2.17.1 (`latest`), and `bgpd --dryrun` on FRR 8.5 and 10.7. Two traps for whoever
  repeats that: FRR's dry run **exits 0 even when lines fail**, so read its output for `Config
  Failed`/`Unknown command`; and it **aborts on any `neighbor` line** (`bgp_keepalives_off()`
  assertion), so dry-run the policy without the session config.
- **FRR's config read is quadratic in the rule count; BIRD's is not.** Measured 2026-11-25 with
  `bgpd --dryrun` on FRR 10.7 and `bird -p` on BIRD `latest`, one parse per shape, 300 s cap.
  - FRR as-path: 22 s at 1,000 rules and 90 s at 2,000, about 4× per doubling.
  - Community went 16 → 62 → 255 s and prefix 42 → 122 s, about 4× and 2.9× per doubling. Those
    runs overlapped earlier timed-out parses that `timeout` had left running, so their times and
    their growth rates are both unreliable. Only the as-path pair is clean.
  - Every FRR parse at 8,000 rules, and as-path and prefix at 4,000, exceeded the cap.
  - Extrapolated, 65,533 as-path rules would take about a day.
  - BIRD read every shape up to 8,000 in under a second.

  So `MAX_POLICY_RULES` is what FRR can *represent*, not what it can start in a run's time. An FRR
  cell's startup wait has to scale with `N`, or its large cells must be refused (see "FRR's slow
  config read is waited out" below).
- **FRR's evaluation is slow for one shape, not for every one.** The 2026-11-27 qualification ran
  10 peers × 10,000 prefixes with 1,000 rules on BIRD 2.17.1 and FRR 10.7.0, one run per cell. FRR
  converged in about 4 s for every match type with `first`, and for `prefix` with `last`. It took
  11 s for `community`/`last` and about 276 s for `as-path`/`last`, at both `/24` and `/32`. BIRD
  took 7 s for that cell. So walking 1,000 failing AS-path access-lists costs FRR far more per
  route than walking 1,000 prefix-lists. Whether that cost grows quadratically with `N` was not
  measured, because only one `N` ran. The cause is unexplained; FRR's AS-path lists use regular
  expressions, and that is the first place to look.

### On a run — `--policy-rules N --policy-match M --policy-hit H`

- **It turns `--tester-attributes` on**, whatever the match type: the as-path and community rules
  match the blocks' attributes, and a policy cell's baseline is the attributes-only run (measured above), so
  a prefix policy without them would carry a different table from its baseline. Every refusal of
  the attributes is therefore a refusal of the policy, re-raised naming `--policy-rules`
  (`import_policy.resolve_import_policy()`), and so are `--receivers` (a second cost in the run)
  and `--target_config_file` (the target runs that file and never writes its own config, so the
  policy would be recorded in the stem, the row and both manifests without ever being rendered).
  Neither `--policy-match` nor `--policy-hit` has a default — a default would be a dimension set by
  omission — and naming either without rules is refused.
- **Support is declared on the adapter**: `Target.IMPORT_POLICY_MATCHES`, set on `BIRDTarget` and
  `FRRoutingTarget` (and so `frr_c`), `None` everywhere else. The entry point refuses an undeclared
  target or match type before anything starts, and `Target.import_policy()` refuses again if a
  scenario reaches a target that declares none.
- **Where it is refused.** `bench` runs it. `bench -f` refuses the flags, and refuses a scenario
  whose target carries `import-policy` before the teardown (`check_scenario_import_policy()`):
  the checkpoints and the count guard come from the command line, and a file states its own.
  `config` refuses the flags, since it names no target and writes for `-f`. `-r` is refused, as
  the attributes are. Native controlled cells refuse it.
- **In `batch` the three are list axes on a test**, all three or none. They are refused
  on a target (`BATCH_TEST_ONLY_KEYS`), because a target key nothing reads would run the cell with
  no policy under a config naming one.
  - `policy_rules` must hold a positive count, since a matrix of baselines measures nothing.
  - A `0` is **one** baseline cell per workload (`batch_policy_points()`): the baseline has no
    match type or hit position, and one per pair would be one cell under several names.
  - Every cell of a policy test carries the generator's attributes, the baseline included,
    because the baseline is the attributes-only run. `tester_attributes: false` beside the keys
    is refused.
  - `check_batch_policy()` puts every target, filter, fleet and point through
    `resolve_import_policy()` before the first cell, and the baseline through the attributes'
    refusals. It also refuses scenario-file targets and `repeat`, the latter across tests too
    (`check_batch_prefix_length_and_repeat()`).
  - The points run inside the filter axis and outside the targets. A test without the keys
    keeps every ordinal and cell id it had; a policy cell's id adds the three keys.
  - `prefix_length` stays one value per test: the stats row has no prefix-length column, so two
    lengths in one test would merge rows in its graphs.
- **The scenario carries the arguments, not the rules**: the target's `import-policy` entry is
  exactly what `build_policy()` takes, including the walk's exclusions, which `gen_conf()` now
  computes once and uses for both the walk and the policy. The target rebuilds the policy
  (`import_policy.policy_from_scenario()`, which refuses a missing or extra field) and writes it
  line by line. BIRD: the filter beside the others and `import filter bgperf_import_policy` on the
  one `neighbor range` protocol. FRR: lists and route-map **before `router bgp`**, and
  `route-map BGPERF-IMPORT in` on every session. Both apply it to the monitor's and receivers'
  sessions too, which announce nothing.
- **Every checkpoint is the expected accepted count**, never the configured count, which a
  filtered run never reaches (`convergence.py`'s "a filtered run" case). A shortfall still ends:
  BIRD's pre-policy `received` reaches the full table and opens the convergence gate, the run ends
  on stability, and the count guard below withholds its timing. Each neighbour's
  `check-points`, and the monitor's, which is exact — no 0.99 allowance — because the guard below
  compares to it exactly. Each neighbour keeps its offered count as `offered-check-point`, and
  `Target.get_offered_counts()` holds the pre-policy `received` counter to it. Held to the accepted
  count, `received` would call a peer complete at three quarters of its table and open the
  convergence gate early.
- **The count guard** (`import_policy.count_failure()`): a converged run whose monitor's final
  count is not exactly the expected count is published `FAILED`, with the received count, the
  expected count and their difference in `MSG`. The events artifact's monitor intervals are
  nulled and named in `measurements_withheld_reason`: `MONITOR_REQUIRED_REACHED` is recorded when
  the count crosses the check-point, so `convergence_s` would otherwise still be derived.
  `findings.py` reads that reason and publishes a `timing_withheld` confounder in place of the
  timing findings, so `limiting_component` is `unresolved`: read as absent, the nulled intervals
  would say the monitor never reached the count, which an over-accepting policy did reach. The CSV
  row keeps its `elapsed (s)` beside `FAILED`, as every failed row does. It is a guard against
  unequal work, never evidence of correct evaluation. A run that already failed keeps its own
  reason.
- **The exact check-point drops the 0.99 allowance** ("bird seems to reject several handfuls of
  routes"). Checked live on 2026-11-25 at 2 peers × 1,000 `/24`s, 10 rules: BIRD 2.17.1 (as-path,
  `last`) and FRR 10.7 (prefix, `last`) both ended at exactly 1,500, the expected count. That is
  one small shape; a larger run that loses routes would now be published `FAILED`, which is the
  guard doing its job rather than a reason to restore the allowance.
- **The policy-loaded check** (`Target.policy_loaded_failure()`) runs once, after the
  monitor's and receivers' sessions are up and before the clock, any sampler or any generator
  starts. A failure is a **FAILED row**, recorded through `finish_bench()` with nothing sampled:
  `MSG` names what differs, the events artifact withholds every interval by that reason, no
  per-run graph is drawn from no samples, and the containers are left for inspection. A batch
  records the cell and goes on, and `bench` exits 1 as it does for any failed row. The count guard
  cannot replace it: a daemon that dropped filler rules accepts the
  same routes with less work, and would be published as a fast policy run.
  - **BIRD** (`bird.policy_loaded_failure()` over one `show protocols all`): every BGP protocol's
    ipv4 `Input filter:` must be `bgperf_import_policy`, and a `neighbor range` listener must be
    among them, since no generator has connected yet and the listener is what their sessions are
    spawned from. The name is enough: BIRD refuses to start on a config it cannot parse.
  - **FRR** (`frr.policy_loaded_failure()` over one `show running-config`): the name is not
    enough, because bgpd logs and skips a config line it cannot read and starts anyway. Every list
    entry, every `BGPERF-IMPORT` route-map entry (action and body) and every session's
    `route-map BGPERF-IMPORT in` must match `frr_policy_lines()`, ignoring only the ` seq N` FRR
    inserts into list entries. Lists are read wherever they print — FRR 10.7 puts prefix-lists
    before `router bgp` and as-path and community lists after it. Asked after the monitor's session
    is up because bgpd reads its whole config before it opens a session.
  - **Every other adapter fails closed**: the base method refuses any run carrying a policy, so an
    adapter that gains a renderer cannot run one until it has its own check, which a test requires
    of every `IMPORT_POLICY_MATCHES` target.
- A scenario file carrying `offered-check-point` on a neighbour, which only a policy run writes, is
  refused with `import-policy`, at `bench -f` and for a batch `file:` target up front.
- Stem `po<N><pfx|asp|com><first|last|miss>` after `ta`; both manifests' `run.import_policy`
  records the three dimensions and the expected counts, `null` without a policy.
- **FRR's slow config read is waited out, not capped.** The monitor's establishment wait has no
  deadline once the sink is writing, so an FRR target parsing a large policy shows as a long
  `monitor (s)`, not a failed run. The clock starts after it, so convergence time excludes the
  parse. At 1,000 rules on FRR 10.7 (2026-11-27), `monitor (s)` was 13–30 s, against 0 s for the
  baselines. No FRR-specific cap on `N` exists yet.
- **The stats row carries `policy rules`, `policy match`, `policy hit` and `policy bytes`**, after
  `max foreign cpu %` and before the provenance columns, which stay last. Without them a policy row
  and its attributes-only baseline are the same row. `policy bytes` is counted as the target writes
  its config (`Target.write_import_policy()`), so it is the text the daemon read, never a second
  rendering; it is blank where no size was recorded (a remote target), never 0. A cell result
  written before these columns is four fields short and `summary.py` reports that pass
  `unreadable`, the supported path for `--resume` across an added column.

## `-s/--single-table` — refused, because nothing has honoured it since 2021

`-s` (batch: `single_table` on a target; scenario: `single-table` on the target) is refused at all
four entry points, and `False`/absent is accepted so an older file that spells the default out
still runs. It is refused rather than removed so the operator is told why instead of meeting
argparse's bare `unrecognized arguments`.

- **It never did what its name says.** The only reader was `BIRDTarget`'s per-neighbour
  path, which built a per-peer table and a `protocol pipe` copying `master4` into it -- but no
  session used that table, and the `sorted` and `secondary` values it computed were passed to
  format strings that never referenced them. So even when it ran, the only effect of *omitting*
  `-s` was N extra copies of the table -- a real difference, so rows from before the date below
  (the README's 2021-08-02 output) do measure two layouts.
- **That path stopped running on 2021-08-13**, when BIRD moved to one `neighbor range` protocol
  behind a `DYNAMIC_NEIGHBORS` switch nothing ever flipped back; a later edit made it raise on any
  call (bgperf2-app). Every BIRD run since is the single-table shape with or without `-s`, and no
  other daemon read the key at all. `benchmarks/baseline/baseline-benchmark.csv` therefore holds
  `bird -s` and `bird` rows that are **one configuration measured twice** -- max mem 0.556 GB in
  both at 50x100k. Read them as a repeat, never as a table-layout comparison.
- The dead path and the switch were deleted together with the flag, which is safe only because
  of the second point: the rendered BIRD config is byte-identical before and after (verified
  across threads, filter test and policy reload).
- **The `-f` refusal reads the scenario before the teardown.** The main parse sits after it, so a
  refusal there would already have cost the previous run's containers -- the rule every guard in
  `bench()` follows. A batch `file:` target's scenario is read in `check_batch_test()` for the
  same reason one level up: refused at its cell, the `SystemExit` would end the whole matrix.
- `gen_conf()` no longer writes `single-table` into the scenario; the stats row keeps its `flags`
  column (always empty) for the stats contract.

## `--pin ROLE=CPUS,...` — confine each role to its own cores

`--pin target=0-7,monitor=8-9,testers=10-15` (batch: `pin:`, a *test* key) gives every container of
a role one Docker cpuset (`Container.cpuset`, applied in `Container.run()`). Without it target,
generators, monitor and receivers share every core, and a co-located role's CPU lands in the
target's timing. Comparison plan §4 item 2 and §5's bias check are why it exists.

- **Every role the run has must be named, and the sets must be disjoint.** An unnamed role runs on
  every core, the pinned ones included, so a run pinning only the target would be published as
  isolated when it was not. `receivers` is required exactly when the run has receivers, and refused
  when it has none -- from `--receivers` on a generated run, from the scenario's own list under `-f`.
- **A CPU the host does not have is refused before the teardown**, read from
  `/sys/devices/system/cpu/online` (`host_cpus()`), not from this process's affinity. Docker would
  refuse it too, but only once the previous run's containers were gone. It is the one guard that
  reads the host, so `bench()` resolves the pin after every command-line guard.
- **The cpuset is read back after the container is created.** A daemon that dropped it would
  publish an unpinned run under a pinned name, so a mismatch raises.
- **Refused under `-r/--repeat`, in both directions.** `--repeat` builds no tester objects and a
  container's cpuset is fixed at creation, so `--pin -r` would run the generators on whatever cores
  they already had. The reverse is the quieter one: an unpinned `-r` after a pinned run reuses
  pinned generators. `pinned_tester_containers()` refuses that before the teardown, which makes it a
  Docker call after the pure guards. A batch target with `repeat` refuses a pinned test outright, and
  `check_batch_pin_and_repeat()` refuses a *batch* mixing a pinned test with a repeat target in
  either order (shuffle and `--resume` decide which runs first). It also checks the host once for
  pinned generators left behind. Found in review: per-test checks passed it, and the matrix
  ended at the second test's first cell.
- **Refused for a remote target** (`-f` only): bgperf2 does not start it, so there is nothing to
  confine.
- **Three entry points, not four**, for the reason `--policy-reload-blocks` has three: a cpuset is a
  property of the containers, not of the scenario, so `config` does not take the flag.
- **Canonical form.** Role order is fixed and each set is written as its shortest cpulist, so two
  spellings of one layout give one cell id, one stem and one manifest entry. Commas separate both
  roles and CPUs; a token with no `=` extends the role before it.
- **Recorded, unlike the workload keys, under `-f` too.** Both `run` blocks carry `pin` as
  `{role: cpus}`, or `null` when unpinned: bgperf2 starts the containers whatever wrote the
  scenario. The stem gets `pin.target0-7.monitor8-9.testers10-15` (commas become `+`), and the cell
  id and description carry the canonical spec, only when it is set, so every existing id resumes.
  It is not a CSV column, for the reason `--path-diversity` is not.
- **What it does not pin:** the controller itself (bgperf2, `mpstat`, the `docker exec` polls) and
  the kernel's network softirqs still run anywhere. Disjoint sets are only disjoint physical cores
  where a vCPU is a core, not an SMT sibling; check `lscpu`'s `Thread(s) per core` on the host
  before relying on it (plan §4 item 2).

## `--monitor gobgp|sink` — which instrument measures the run

`--monitor` (batch: `monitor:`, a *test* key) chooses the monitor class from `MONITOR_CLASSES`.
**`DEFAULT_MONITOR` is `sink` since measurement plan 7d (2026-10-02).** GoBGP stays selectable
as the reference a sink result can be re-checked against, one cell at a time, so the monitor
stays a run dimension. The bridge block (7c) that would have compared the two up front was
dropped by the operator in favour of re-benching.

- **Three entry points, not four**, for the reason `--pin` has three: the monitor is a container,
  not part of the scenario, so `config` does not take it. A batch value is checked against
  `MONITOR_TYPES` by `check_batch_test()`, since `batch()` bypasses argparse's `choices`.
- **The image is checked after every command-line guard and before the teardown**, on both the
  generated and the `-f` path (a `-f` run starts the monitor too), and once per batch by
  `check_batch_monitor_images()`. The GoBGP monitor's image had never been checked at all. A run
  with receivers checks `RECEIVER_CLASSES[monitor]`'s image as well: review found that under
  `--monitor sink` the receivers were still GoBGP and their image went unchecked.
- **Named only away from `UNMARKED_MONITOR`, which is not `DEFAULT_MONITOR`.** The stem gets
  `mon-sink`, and the cell id and description carry `monitor` only for the sink, so every existing
  artifact and cell id is unchanged. The omission is tied to the instrument the old rows were
  measured on rather than to the default: tied to the default, the 7d flip would have handed the
  unmarked name to the sink and renamed every GoBGP cell measured before it. So since the flip a
  default run is the marked one: `bench -t bird -n1 -p1` writes `bird_bird_1_1_mon-sink.*`.
- **A config that ran before the flip says so.** Every 2026 config under `benchmarks/` states its
  monitor, and those that ran under GoBGP say `monitor: gobgp` (`test_static.py` enforces it).
  Without the key, re-reading one after the flip describes its cells as sink cells:
  `check_repetition_configs.py` reported exactly that for the archived timing-validation blocks,
  and review found the GoBGP half of all three monitor-pair configs had become a second sink run.
  With it, their cell ids are byte-identical to the ones recorded, because GoBGP is the unmarked
  instrument.
- **`--resume` refuses rows another instrument measured** (`check_resumable()`), before anything
  asks Docker. A cell id names its instrument, so such rows are results for cells the config no
  longer lists, and continuing would report them beside rows measured under the new one. It
  catches both ways in: a config with no `monitor:` key that ran GoBGP before the flip, and a
  `monitor:` edited between runs. The way out is a new `--results-dir`, or stating the instrument
  the rows ran under.
- **An absent monitor in a cell id is `UNMARKED_MONITOR`** (`cell_monitor()`), never the
  default, and `batch()` runs a cell under the same reading. An id omits the key on GoBGP, and
  analysis reads ids back from recorded results; read as the default, every
  GoBGP cell measured before the flip would be described as a sink cell.
- **Recorded under `-f` too**, in both `run` blocks and as the manifest's `monitor.daemon`,
  because bgperf2 starts the monitor whatever wrote the scenario. Not a CSV column: the
  `monitor version` column already names the build.
- **The receivers follow the monitor** (`RECEIVER_CLASSES`): GoBGP under `gobgp`, sinks under
  `sink`, so one dimension names every instrument in the run, and a GoBGP re-check compares
  whole instruments rather than a sink monitor beside GoBGP receivers.

## `--threads N` — worker threads on the target

`--threads N` sets worker threads on the target (`conf['target']['threads']`). Only BIRD reads it
so far: **BIRD 3 runs one worker unless the config says otherwise**, so benching 3.x against 2.x
without it measures nothing (verified: 3.3.2 gives 2 OS threads by default, 5 with `threads 4`;
2.19.2 accepts the keyword and stays at 1).

`bench()` and `batch()` resolve and verify images before starting any container, so a version that
was never built costs a second rather than an hour.

Batch configs take `versions: [...]` on a target, expanded by `expand_target_versions()` into one
run per version with an auto label. Batch yaml is parsed with `BatchLoader`, which drops YAML's
float resolver — plain `yaml.safe_load` reads `10.10` as `10.1` and would silently bench the wrong
release.

## Portable recipe source validation

The read-only `recipes.py` interface validates a strict subset of batch YAML
for portable synthetic IPv4 BIRD/BIRD/sink recipes. It uses `batch_cells.py`
for shared construction and historical IDs, and rejects unsupported source
fields before selecting a cell. Optional CPU pinning uses the shared pure
`cpu_pinning.py` rules; every role is required and the sets must be disjoint.
The recipe reader bounds CPU ranges before expansion, preserves absent-pin
identities, and binds a canonical declared layout into the cell and recipe.
Read-only prerequisites check online IDs; the scoped worker must forward the
layout into the same lifecycle guards and artifact fields as `bench`.
The authoritative envelope and
status contracts live in [the recipe guide](../recipes.md). The existing batch
and scenario guards above retain their behavior.
