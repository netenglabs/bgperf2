# Workload controls

What `bench`/`batch` may be asked to run, and the guards that refuse the rest.

**Read this before editing:** `bgperf2.py` (argument guards, `bench()`, `batch()`, `check_batch_test()`, `bench_output_prefix()`), `base.py` (`gen_conf()`, `gen_paths()`, `Target.scenario_neighbors()`), `churn.py`, `policy.py`, `bird.py` (the churn protocol and the reload command)

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
target keys -- `batch()` reads a fixed field list and ignores the rest -- and every knob an operator
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
