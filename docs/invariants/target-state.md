# Asking the target what it holds

The per-daemon `get_neighbors_state` wart, the table witness, and the delivery measurement derived off it.

**Read this before editing:** `bgperf2.py` (the monitor poll), `base.py` (`Target.sample_target_state()`), `frr.py`, `frr_compiled.py`, `bird.py`, `gobgp.py`, `measurements.py` (`target_table_section()`, `delivery_metrics()`, `check_events()`), `scripts/check_timing_evidence.py`

These are invariants, not background: every rule here was written because the obvious alternative was tried and published a wrong number quietly. `CLAUDE.md` carries the one-line index; this file carries the argument.

---

## get_neighbors_state — the per-daemon wart

`bench` needs to know how many prefixes each neighbor has sent, and every daemon reports this
differently. There is no common API, so each target parses its own CLI:

- FRR: `vtysh -c 'sh ip bgp summary json'`, JSON
- BIRD: `birdc 'show protocols all'`, parsed by `bird.parse_protocols()` — which reads the
  route-change-stats table by **column name**. It replaced a positional TextFSM template
  (`bird.tfsm`, now deleted, along with the `textfsm` dependency): BIRD 3 inserts `RX limit`
  and `limit` into that table, so the field that is `accepted` on 2.19 is `RX limit` on 3.3.2.
  Every BIRD 3 target therefore reported `accepted` 0 for every neighbor, `neighbors_checked`
  never went all-True, and that route to `note_neighbors_checkpoint()` was dead — quietly, since
  runs still converged through `neighbors_received_full`. Never read a BIRD stats table
  positionally.
- Junos/EOS/SR Linux: vendor JSON via their own CLIs

**Those counters are not the whole of what a target can be asked, and reading
only them cost a whole phase.** `Import updates accepted` is a cumulative event
counter: it only ever rises, so it can witness delivery and cannot witness a
loss. `birdc show protocols all` also prints `Routes: N imported, N filtered, N
exported, N preferred` per channel, which is a *gauge* of the table as it
stands, and `parse_protocols()` had always parsed it while nothing read it. It
is now `bird.table_witness()`, reaching the progress line and the events
artifact's `target_table` section as three numbers: `best_paths` (the sum of
each peering's `preferred` -- one best route per prefix, so the count of
distinct prefixes held, which is what the monitor's `accepted` tracks),
`imported_paths` (the sum of `imported` -- every path, losers included, so it
moves with delivery rather than selection) and `exported_to_monitor` (the
`exported` count on the monitor's own session: the target's end of the very
session the monitor reads).

- **The monitor cannot check itself.** It is one BGP session's view of the
  target and it is the instrument every published timing comes from, so a move
  in its count had nothing to be compared against -- which is how
  `bgperf2-dcs` reached a state where an MRT run failed deterministically on a
  1.5% decline nobody could attribute. With the gauge, four runs showed the
  target's table climbing to 1,080,985 distinct prefixes and staying flat while
  the *export* fell 1.35%, with the target's own export count agreeing with the
  monitor to three decimal places. Neither instrument was wrong and no routes
  were lost.
- **One CLI read serves both.** `Target.sample_target_state()` is the single
  call the poll makes, and `BIRDTarget` overrides it to parse one `show
  protocols all` twice rather than exec twice: two reads would be two execs a
  second into the container being measured, and -- worse for a number whose only
  job is to be compared against another number -- two different instants. The
  sample is stamped before the read, on the rule both poll loops already follow.
- **Two daemons answer, with different halves, and a partial answer is not a
  wrong one.** BIRD publishes all three sums. FRR publishes
  `exported_to_monitor` and `imported_paths` (`frr.table_witness()`), off the
  same `sh ip bgp summary json` its neighbour counters already come from -- one
  exec, one instant, BIRD's rule. `exported_to_monitor` is the monitor
  session's own `pfxSnt`, and `imported_paths` the per-peer `pfxRcd` sum, which
  is what the MRT size floor is built on; both need no interpretation.

  It withholds **`best_paths`** deliberately, and only that one: FRR does
  report a table size, but `ribCount` and `show bgp ipv4 unicast statistics`'
  `Total Prefixes` disagreed (1,081,000 against 1,080,985 on one measured run)
  and neither has been established to mean "prefixes holding a selected best
  path", which is what BIRD's `preferred` sum means and what the convergence
  rule compares against its own peak. A witness that is subtly wrong is worse
  than none -- it excuses declines it has no standing to excuse -- and `None`
  is the documented way to attest to nothing, so adding FRR's halves changed
  nothing about how an FRR run converges.
- **A daemon with no gauge reports `None`, never 0**, and a run with no witness
  gets no `target_table` section at all, so every other daemon's artifact and
  progress line are exactly what they were. A sum is withheld when any peering
  did not report -- `tester_offering()`'s rule, and it matters more here: a
  partial read looks exactly like a table that shrank, which is the one thing
  this measurement exists to rule on.
- **The measurement publishes no verdict; the rule that reads it lives in
  `convergence.py`.** `measurements.target_table_section()` records the
  per-poll series and each series' peak and final value and derives nothing --
  it was shipped one change set *before* the rule, deliberately, because a rule
  shipped beside the first evidence for it is fitted to the run in front of it,
  which is how all three convergence rules were broken. The rule is in
  `docs/invariants/convergence.md`; what it did with the witness comes back into
  this section as `witness_rule`, from the tracker that decided the run rather
  than recomputed from the series.

FRR is a special case worth knowing about: it has no received-prefix counter, so
`FRRoutingTarget.get_neighbor_received_routes()` overrides the base method and greps `bgpd.log` for
`End-of-RIB` messages instead.

**That log read must stay incremental.** `write_config()` sets `log stdout debug` purely so
End-of-RIB is visible, which means `bgpd.log` grows with the route count — a 10-peer 1.05M-prefix
MRT run puts it past **1 GB**. `_get_EOR_from_log()` used to `readlines()` the whole file and
rematch every line once per second, costing 4+ seconds of CPU against a 1-second poll interval: the
loop fell permanently behind, stopped printing progress, and the run never finished even though the
target had converged minutes earlier. Measured on a real 1.04 GB log, same neighbors found either
way: **4.14s per poll before, 0.0000s after the first.** It now tracks a byte offset and reads only
what was appended, and:

- it stops at the last complete line, so a half-written one is not consumed and lost;
- the restart reset keys on **inode**, not size — a replaced log that had already grown past the
  saved offset would otherwise be resumed from the wrong place, and since FRR reaches its
  checkpoint only via End-of-RIB, missing those lines means the run never converges;
- the per-poll read is capped, and matching happens on bytes with the decode deferred to lines that
  hit, because this process's own RSS feeds the recorded `min_free` column.

**`monitor_required_reached` is the monitor's count against the check-point,
and a second rule for it was tried and backed out.** The check-point is `n * p`
for a synthetic run -- a statement of fact, since bgperf2 generated the prefix
lists -- and `0.99 * -p` for MRT playback, where `-p` is the per-injector cap
and the union of ten overlapping peer views cannot be known in advance. Daemons
legitimately export different shares of one RIB: measured on a single
routeviews file, RustyBGP 1,081,178, BIRD and OpenBGPD 1,056,779 each, every
FRR release ~961,000 (0.91% apart across four releases and master). **A daemon
below that guess emits no `monitor_required_reached` and so publishes no
`convergence_s`, `assurance_s` or `post_injection_tail_s`** -- a known gap, not
a bug to patch casually.

The second rule was the target's own account, which is what the blog series
this project comes from did when filtering raised the identical problem ("we
don't know what will get filtered"): the target has received everything from
every neighbour, and has sent it on to the monitor. It was built, verified, and
removed, for a reason worth keeping:

- **The neighbour checkpoint says every generator has *sent* everything, not
  that the target has finished *exporting*.** So one poll in which the export
  count does not advance, with the monitor drained to that same number, stamps
  the event mid-delivery -- at a fraction of the table, permanently, since the
  event is recorded once and nothing in the artifact says which rule supplied
  it. An earlier version that required only `monitor_accepted >= exported` was
  worse still: the witness is resampled onto the monitor's polls and can be
  seconds old, so a fast climb lets the monitor overtake a stale export count.
  That one escaped the measured FRR case only because bgpdump2's injectors were
  blocked on FRR draining (75s to complete against OpenBGPD's 2.4s).
- **Whether the target finished exporting is only decidable in retrospect**, so
  a sound version is a measurement derived off the completed `target_table`
  series -- named as its own thing, never synthesised into the event stream as
  though it had been observed -- with `event_coverage` accepting it in place of
  an event that legitimately cannot fire.

**That measurement is `target_table.delivery`** (`measurements.delivery_metrics()`),
and it is deliberately *not* a replacement for `convergence_s`. It is the
earliest reading of the terminal export plateau at or after which the monitor
holds it: the target stopped exporting at `plateau_start_s`, and the far end had
it at `complete_s`. Because the series is complete, "and it never changed again"
is checked rather than assumed -- which is the whole difference from the two
backed-out rules, both of which decided from the samples in hand.

- **It answers a different question from `convergence_s`, and the recorded runs
  say so loudly.** The MRT check-point is `0.99 * -p`, the per-injector cap,
  which is a threshold part-way up the climb: on one recorded 2-injector 500k
  run the monitor crossed it at 16.85s with 500,171 prefixes visible while the
  target went on exporting to 501,471 until 36.36s. On a *synthetic* run the
  check-point is the whole table and the two land on the same poll. Across the
  34 recorded runs that resolve, `complete_s` lands at or after
  `monitor_required_reached` and at or before `convergence_confirmed` every
  time -- **at** poll resolution, not strictly between: in the 5 same-poll runs
  the two differ by under 500ns in either direction, which is the sample
  series' 6-place rounding against the event's raw timestamp. Compare them as
  an ordering at poll resolution; a strict inequality reads the rounding.
- **Derived for every run with an export gauge**, not only the daemons that lose
  the event, so the column is comparable across daemons rather than appearing
  only where there is trouble.
- **The final reading is the table, not the peak.** 11 of 39 recorded runs end
  1.35%-1.55% below their peak and every one settles on exactly 1,056,779 --
  what BIRD and OpenBGPD both converge to on this RIB -- so the peak is a
  convergence overshoot. Taking it would wait for the monitor to reach a count
  the target does not hold and withhold every MRT run. A target that delivered
  and then really lost routes is dated to the loss, and is failed by the
  tracker's drop rule and rejected by `check_timing_evidence.py` before anyone
  reads the number.
- **Whether the table was the right *size* is not judged here.** The function
  gets samples and no denominator, so a target stalled at a fraction of the RIB
  has a terminal plateau like any other; that is the checker's call, which
  knows the check-point. The zero case is refused for a different reason -- the
  rule degenerates, since `0 >= 0` makes the monitor trivially level -- and
  that is the line between the two.
- **Ten refusals, each because the alternative publishes a number that looks
  measured and is not**: no gauge or no samples; a final count of zero; a
  truncated series; a plateau of one reading (the run stopped, which is not the
  target finishing); a withheld poll inside the plateau; a *carried* reading in
  the plateau; a plateau that cannot be dated at all; a stale reading past the
  carry bound; a monitor that never drew level; and samples that cannot be
  dated at all. Five of those ten were added by review of the first version,
  each having been reproduced against the shipped function, which is why the
  list is worth reading rather than summarising:
  - **A final count of zero is not a delivery.** `bench()` writes a FAILED
    run's artifact with its samples exactly like a converged one's, and an
    all-zero series satisfies every other rule here -- `0 >= 0` draws the
    monitor level on the first sample -- so the tracker's "nothing arriving
    within 15s" failure published a completed delivery at 0.1s. The same guard
    stops an export count that *collapses* to zero from dating the delivery to
    the collapse. Churn's "a collapsed count is not a withdrawal" and the
    tracker's "a monitor count of zero never attests", on a third side.
  - **A single-reading plateau is checked against the read timestamps, not the
    ages**, because the age bound does not implement the rule it states: a dead
    poll thread is re-paired with every later monitor sample, so its ages are
    1s..5s and all *within* bound. It requires **two distinct** reads and not
    all-distinct ones: a repeated read is ordinary whenever the target's poll
    is the slower loop (11 of 39 recorded runs contain one), which is likeliest
    on the very large-table runs this measurement is for -- so refusing on any
    duplicate would withhold the answer from the rows that need it while naming
    a dead sampler that was alive. A first version got this wrong on evidence
    that only covered the other sign.
  - **A withheld sum is not a carried one** and the age rule cannot see it:
    the read stays fresh while the sums are None, so a hole in the plateau
    left "and it never changed again" unsupported across it. `series_truncated`
    one step inward. No recorded run reaches it (0 of 1303 post-first-reading
    samples), so it closes a blind spot rather than explaining a run.
  - **Undated and stale are named apart**, on `findings.py`'s `inconclusive`
    vs `unresolved` rule: the five recorded withholdings are four artifacts
    written before the fields existed (`gauge_undated`) and one frozen sampler
    (`gauge_carried_across_plateau`), a split the plan used to have to make in
    prose because the reason string could not.
  - **The draw-level scan reads every sample from the plateau's start**, not
    only those carrying a gauge reading: `monitor_accepted` is recorded on
    every poll, so restricting it made a crossing during a withheld poll
    invisible and returned `monitor_never_drawn_level` for a session the
    document's own `monitor_final` disproved. It asks whether the monitor
    *ever* drew level, not whether it ended there -- a monitor that draws level
    and then declines has taken delivery, and those declines are ordinary here
    (the tracker's fourth rule exists for them) -- and the comparison is exact
    rather than tolerant.
  - **A resolved section always has an answer in it.** Samples with no
    `monotonic_s` fell through to a null reason beside a null `complete_s`,
    contradicting the documented contract and leaving the branch unnameable --
    the one outcome `_delivery()` exists to prevent. It is `no_sample_times`.
- **The staleness bound is the tracker's own carry bound**
  (`WITNESS_CARRY_SAMPLES` polls), pinned in `tests/test_stats_contract.py`
  rather than imported, since `measurements.py` stays free of project imports.
  A bound invented here would be one fitted to whichever run was in front of it.
- **`check_events()` reads it, and only it.** It shipped one change set before
  that rule, deliberately -- the same reason `target_table` itself did, since a
  rule landed beside the first evidence for it is fitted to that evidence,
  which is how all three convergence rules were broken. The rule accepts a
  *resolved* `delivery` in place of `monitor_required_reached`, under three
  limits: **only for an MRT generator** (a synthetic run's check-point is
  `n * p`, a statement of fact, so a target that misses it lost routes --
  tested by membership in `MRT_TESTER_TYPES`, because a `-f` run records
  `tester_type: null` and states its own check-point too); **only for that one
  event** (the other three are recorded by every run that got that far, so a
  missing one is a broken run rather than a yardstick that did not fit); and
  **only when it resolved** (a withheld `delivery` names why, so reading one as
  a substitute would replace a missing measurement with an absent one).
  `findings.py` does **not** read it: such a row still reports
  `limiting_component: inconclusive`, which the checker accepts, and
  `convergence_s`, `assurance_s` and `post_injection_tail_s` are still not
  published for it -- they are intervals measured *from* the event. The 64 GB
  plan's Required Measurements carries the amendment saying so, because the
  campaign may not silently re-define what a correct row is between blocks.

**`check_timing_evidence.py` judges an MRT row on consistency plus a size
floor**, never on the absolute alone -- that part stayed. Consistency is the
monitor's count against the target's own export count; but those are the two
ends of one link and agree whenever the link works, so a target that imported a
tenth of the RIB would show them agreeing at a tenth. The floor is the target's
accepted-path count against what the generators report offering. Neither half of the
check-point survives as a rule on its own: treating it as *necessary* rejected
every FRR row, and it is not *sufficient* either, because `0.99 * -p` is about
4% below the union the ten peers actually hold -- so a target can clear it
having dropped several percent of the table, and the convergence tracker will
not catch that, since routes never delivered are not a decline from the run's
own peak. The floor therefore applies as well as the check-point wherever there
is a gauge, and clearing the check-point is the *fallback* where there is none,
which is how OpenBGPD and RustyBGP rows are still judged. A row below the
check-point with no usable import gauge is rejected, because nothing vouches
for it. A **filtered** MRT row is that same fallback reached from the other
side: its gauge exists but is post-policy for both daemons that publish one, so
it cannot be compared with the offered count either, and the check-point is all
that is left -- clearing it passes the row, below it nothing bounds the table
and the row is rejected. The refusal that names the missing evidence names
*which half of the run* it is missing from, never generalising to the target: a
gauge that reported fine beside generators that publish no offered count
(`gobgp`, `exabgp_mrtparse`) is not a target without a gauge.
