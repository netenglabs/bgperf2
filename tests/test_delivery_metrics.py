"""`measurements.delivery_metrics()` -- when the target finished delivering.

The measurement exists because a daemon that never crosses the run's
check-point publishes no `monitor_required_reached`, and with it no
`convergence_s`, `assurance_s` or `post_injection_tail_s`. Two online rules for
that event were built, verified and backed out; this is the retrospective
version, and the tests below are mostly about the ways it refuses rather than
the ways it answers.

The replayed series at the bottom is a real recorded run, kept here because
`results/` is gitignored -- the same reason `test_convergence_mrt_replay.py`
carries its series.
"""
import measurements


def sample(t, age=0.1, monitor=None, exported=None, **extra):
    # `witness_monotonic_s` is when the reading was taken and `witness_age_s`
    # how old it was when this monitor sample took it, so `bench()` derives
    # one from the other around the sample's own clock (bgperf2.py). Built the
    # same way here, because the difference between two plateau samples
    # sharing a read timestamp and each having its own is what separates a
    # frozen sampler from a working one.
    row = {'monotonic_s': t, 'witness_age_s': age,
           'witness_monotonic_s': None if age is None else round(t - age, 6),
           'monitor_accepted': monitor, 'exported_to_monitor': exported}
    row.update(extra)
    return row


def climb_then_settle(final=1000, settled=4, start=1.0):
    """A count that climbs and then holds `final` for `settled` polls."""
    rows = [sample(start + i, monitor=(i + 1) * 100, exported=(i + 1) * 100)
            for i in range(9)]
    rows += [sample(start + 9 + i, monitor=final, exported=final)
             for i in range(settled)]
    return rows


def test_the_point_is_the_start_of_the_terminal_plateau():
    """Not the end of it, and not the last sample. The target stopped
    exporting when the count last changed, and every later poll is evidence
    that it stayed stopped rather than a further part of the delivery."""
    got = measurements.delivery_metrics(climb_then_settle())
    assert got['unresolved_reason'] is None
    assert got['complete_s'] == 10.0
    assert got['plateau_start_s'] == 10.0
    assert got['plateau_samples'] == 4
    assert got['exported_final'] == 1000


def test_a_plateau_that_resumes_climbing_is_not_the_plateau():
    """The whole reason this is retrospective. Both backed-out online rules
    stamped the event from the samples in hand, so a count that paused and then
    climbed again had already been recorded -- permanently, at a fraction of
    the table, with nothing in the artifact saying which rule supplied it."""
    rows = climb_then_settle(final=1000, settled=3)
    rows += [sample(20.0 + i, monitor=2000, exported=2000) for i in range(3)]
    got = measurements.delivery_metrics(rows)
    assert got['complete_s'] == 20.0
    assert got['exported_final'] == 2000
    assert got['plateau_samples'] == 3


def test_the_monitor_has_to_draw_level_and_the_point_waits_for_it():
    """Delivery is the far end holding what the target sent. The target can
    stop exporting several polls before the monitor has taken it all."""
    rows = climb_then_settle(final=1000, settled=0)
    rows += [sample(10.0, monitor=920, exported=1000),
             sample(11.0, monitor=960, exported=1000),
             sample(12.0, monitor=1000, exported=1000)]
    got = measurements.delivery_metrics(rows)
    assert got['plateau_start_s'] == 10.0
    assert got['complete_s'] == 12.0
    assert got['monitor_lag_s'] == 2.0


def test_a_monitor_that_never_draws_level_is_refused():
    """Exactly, not within a tolerance: a monitor ending below the target's own
    export count is the disagreement `check_timing_evidence.py`'s consistency
    check exists to flag, and absorbing it here would publish a delivery time
    for a session whose two ends do not agree."""
    rows = climb_then_settle(final=1000, settled=3)
    for row in rows[-3:]:
        row['monitor_accepted'] = 999
    got = measurements.delivery_metrics(rows)
    assert got['complete_s'] is None
    assert got['unresolved_reason'] == 'monitor_never_drawn_level'
    assert got['plateau_samples'] == 3


def test_a_plateau_of_one_reading_says_the_run_stopped_not_the_target():
    rows = climb_then_settle(final=1000, settled=1)
    got = measurements.delivery_metrics(rows)
    assert got['complete_s'] is None
    assert got['unresolved_reason'] == 'still_changing'
    assert got['plateau_samples'] == 1


def test_a_frozen_sampler_is_not_a_plateau():
    """A target poll thread that dies leaves `bench()` appending its last
    reading to every later monitor sample: a perfect plateau made of one
    observation. Every reading in it has to have been taken."""
    rows = climb_then_settle(final=1000, settled=4)
    frozen_at = rows[-4]['witness_monotonic_s']
    for index, row in enumerate(rows[-4:]):
        # One reading, re-paired with every later monitor sample: the age
        # rises and the read timestamp does not move.
        row['witness_monotonic_s'] = frozen_at
        row['witness_age_s'] = round(row['monotonic_s'] - frozen_at, 6)
    got = measurements.delivery_metrics(rows)
    assert got['complete_s'] is None
    assert got['unresolved_reason'] == 'gauge_carried_across_plateau'
    # And it is caught by the read timestamps rather than by the age bound,
    # which every one of these samples is inside.
    assert max(r['witness_age_s'] for r in rows[-4:]) \
        <= measurements.DELIVERY_WITNESS_MAX_AGE_S


def test_a_withheld_reading_inside_the_plateau_is_refused():
    """A withheld sum is not a carried one, and only the carried kind trips the
    staleness rule: `table_witness()` returns None for a peering that is not
    reporting while the read itself is perfectly fresh, so the hole would
    otherwise pass every check while "and it never changed again" is
    unsupported across it. A peering dropping after convergence is exactly
    when that doubt matters.

    No recorded run on this host reaches this -- 0 of 1303 post-first-reading
    samples withhold an export sum -- so it is pinned here rather than left to
    be discovered by the first run that does."""
    rows = climb_then_settle(final=1000, settled=5)
    # Fresh read, sums withheld: the age stays blameless.
    rows[-3]['exported_to_monitor'] = None
    got = measurements.delivery_metrics(rows)
    assert got['complete_s'] is None
    assert got['unresolved_reason'] == 'gauge_withheld_across_plateau'
    assert got['plateau_samples'] == 4
    assert rows[-3]['witness_age_s'] == 0.1


def test_a_withheld_reading_before_the_plateau_is_not_a_hole_in_it():
    """The rule is about the terminal plateau, not the climb. A session coming
    up withholds the sums on every poll until every peering reports, which is
    what every BIRD run does during ramp-up -- refusing on that would withhold
    the measurement from every run there is."""
    rows = climb_then_settle(final=1000, settled=4)
    rows[2]['exported_to_monitor'] = None
    got = measurements.delivery_metrics(rows)
    assert got['unresolved_reason'] is None
    assert got['complete_s'] == 10.0


def test_a_series_with_no_ages_at_all_is_refused_rather_than_assumed_fresh():
    """Artifacts written before `witness_age_s` existed carry none, and a
    reading that cannot be dated cannot attest to the sample it sits on. Four
    recorded runs from that era withhold on this rule."""
    rows = climb_then_settle()
    for row in rows:
        del row['witness_age_s']
        del row['witness_monotonic_s']
    got = measurements.delivery_metrics(rows)
    assert got['unresolved_reason'] == 'gauge_undated'


def test_a_truncated_series_is_refused():
    """The witness stopped reporting while the monitor polled on, so the last
    reading describes the middle of the run and the flatness after it is an
    absence of evidence rather than a settled table."""
    rows = climb_then_settle(final=1000, settled=3)
    rows += [sample(20.0 + i, monitor=1000, exported=None) for i in range(6)]
    got = measurements.delivery_metrics(rows)
    assert got['complete_s'] is None
    assert got['unresolved_reason'] == 'series_truncated'


def test_a_daemon_with_no_export_gauge_says_so():
    rows = [sample(1.0 + i, monitor=100 * i) for i in range(5)]
    got = measurements.delivery_metrics(rows)
    assert got['unresolved_reason'] == 'no_export_gauge'
    assert got['complete_s'] is None
    assert measurements.delivery_metrics([])['unresolved_reason'] == 'no_samples'


def test_every_field_is_present_on_every_path():
    """A section whose keys come and go cannot be read without knowing which
    branch produced it, and the branch is what the reader is trying to find
    out."""
    paths = [measurements.delivery_metrics([]),
             measurements.delivery_metrics(climb_then_settle()),
             measurements.delivery_metrics(climb_then_settle(settled=1))]
    keys = set(paths[0])
    for got in paths:
        assert set(got) == keys, got
        assert got['derived'] is True
        assert got['derived_from'] == 'target_table.samples'
        assert got['rule'] == measurements.DELIVERY_RULE


def test_it_is_published_inside_the_target_table_section():
    section = measurements.target_table_section(climb_then_settle())
    assert section['delivery']['complete_s'] == 10.0
    # Derived from the samples it is published beside, and nothing else moved.
    assert section['series']['exported_to_monitor']['final'] == 1000


# One recorded 2-injector 500,000-prefix bgpdump2 run against bird 3.3.2:
# (monotonic_s, witness_age_s, monitor_accepted, exported_to_monitor).
RECORDED = [
    (0.000219, -0.00242, 0, 0),
    (1.02661, 0.00745, 0, 0),
    (2.050889, 0.009137, 66133, 65916),
    (3.099295, 0.024919, 112767, 111649),
    (4.169167, 0.071264, 165214, 159809),
    (5.268977, 0.151741, 203283, 199616),
    (6.369721, 0.232551, 235068, 227940),
    (7.475625, 0.31894, 271031, 262077),
    (8.592598, 0.400043, 306371, 293798),
    (9.723995, 0.512274, 336912, 322136),
    (10.858868, 0.621, 365091, 352153),
    (12.046845, 0.777412, 391776, 371694),
    (13.224819, -0.090174, 418579, 420082),
    (14.404797, 0.060314, 451696, 450511),
    (15.594077, 0.228225, 479006, 475296),
    (16.851843, 0.46474, 500171, 486375),
    (18.051105, 0.644946, 500885, 500882),
    (19.285335, -0.171172, 500908, 500908),
    (20.544662, 0.062757, 500945, 500944),
    (21.745971, 0.240191, 501120, 501120),
    (22.949298, 0.414163, 501124, 501120),
    (24.155547, 0.592794, 501154, 501153),
    (25.405529, 0.814731, 501186, 501175),
    (26.616235, -0.025599, 501242, 501269),
    (27.826421, 0.159634, 501306, 501306),
    (29.029565, 0.339667, 501360, 501360),
    (30.288513, 0.569599, 501390, 501368),
    (31.499168, 0.758125, 501401, 501391),
    (32.704906, -0.07699, 501441, 501441),
    (33.911379, 0.100508, 501461, 501461),
    (35.15807, 0.320541, 501469, 501469),
    (36.363067, 0.506271, 501471, 501471),
    (37.571503, 0.693602, 501471, 501471),
    (38.765812, -0.159088, 501471, 501471),
    (39.967106, 0.023213, 501471, 501471),
    (41.213202, 0.250095, 501471, 501471),
    (42.412746, 0.429861, 501471, 501471),]
RECORDED_REQUIRED_REACHED_S = 16.851843
RECORDED_CONVERGENCE_CONFIRMED_S = 42.412746


def recorded_samples():
    return [sample(t, age=age, monitor=monitor, exported=exported)
            for t, age, monitor, exported in RECORDED]


def test_the_recorded_runs_plateau_is_every_reading_freshly_taken():
    """Why the carried-reading refusal can be strict rather than a count: in
    all 34 recorded runs on this host that resolve, every sample in the
    plateau is its own read, and the oldest any of them got was 1.02s against
    a 5s bound. A repeated read timestamp is a stopped sampler, not a slow
    one."""
    rows = recorded_samples()
    got = measurements.delivery_metrics(rows)
    plateau = [r for r in rows if r['monotonic_s'] >= got['plateau_start_s']]
    reads = [r['witness_monotonic_s'] for r in plateau]
    assert len(set(reads)) == len(reads)
    assert max(r['witness_age_s'] for r in plateau) \
        < measurements.DELIVERY_WITNESS_MAX_AGE_S


def test_the_recorded_run_resolves_between_its_own_two_monitor_events():
    """The ordering that holds across every recorded run with a gauge: the
    target cannot finish delivering before the monitor crosses the check-point,
    and cannot still be delivering after the monitor has confirmed the count
    stable.

    Asserted strictly *here* because this run's two points are 19.5s apart. It
    is an ordering at poll resolution in general, not a strict inequality: in 5
    of the 34 recorded runs that resolve, the monitor drew level on the very
    poll that crossed the check-point, and the two then differ by under 500ns
    in either direction -- the sample series' 6-place `monotonic_s` against the
    event's raw value. See the campaign plan's Block 5 record."""
    got = measurements.delivery_metrics(recorded_samples())
    assert got['unresolved_reason'] is None
    assert RECORDED_REQUIRED_REACHED_S < got['complete_s'] \
        < RECORDED_CONVERGENCE_CONFIRMED_S


def test_the_recorded_run_shows_this_is_not_convergence_s():
    """On MRT playback the check-point is `0.99 * -p` -- the per-injector cap,
    a threshold part-way up the climb. This run crossed it at 16.85s with
    500,171 prefixes visible and went on exporting to 501,471 until 36.36s, so
    publishing the derived point as `convergence_s` would move that row by 20
    seconds. On a synthetic run the check-point *is* the whole table and the
    two land on the same poll, which is why the column is derived for every run
    rather than only for the daemons that lose the event.
    """
    got = measurements.delivery_metrics(recorded_samples())
    assert got['complete_s'] == 36.363067
    assert got['exported_final'] == 501471
    assert got['complete_s'] - RECORDED_REQUIRED_REACHED_S > 19.0


def test_a_run_that_delivered_nothing_is_not_a_completed_delivery():
    """The cheapest series there is otherwise satisfies every rule: `0 >= 0`
    draws the monitor level on the first sample, every reading is fresh, and
    the plateau is the whole run. `bench()` writes a FAILED run's artifact
    with its samples exactly like a converged one's, and the tracker's
    "nothing arriving at all within 15s" failure produces precisely this
    shape, so without the guard such a run publishes a completed delivery at
    its first poll."""
    rows = [sample(0.1 + i, monitor=0, exported=0) for i in range(30)]
    got = measurements.delivery_metrics(rows)
    assert got['complete_s'] is None
    assert got['unresolved_reason'] == 'nothing_delivered'
    assert got['exported_final'] == 0


def test_a_collapse_to_zero_is_not_dated_as_the_delivery():
    """The same guard from the other side: an export count that falls to zero
    at the end is the monitor session dropping, and taking the last reading as
    `final` would date the delivery to the collapse. Churn's "a collapsed
    count is not a withdrawal", one more side over."""
    rows = climb_then_settle(final=1000, settled=3)
    rows += [sample(20.0 + i, monitor=0, exported=0) for i in range(3)]
    got = measurements.delivery_metrics(rows)
    assert got['unresolved_reason'] == 'nothing_delivered'


def test_the_monitor_may_draw_level_on_a_poll_whose_gauge_was_withheld():
    """`monitor_accepted` is recorded on every poll whatever the gauge did, so
    scanning only the polls that carry a reading makes such a crossing
    invisible -- and returns `monitor_never_drawn_level` for a session the
    document's own `monitor_final` disproves. The plateau's own validity is
    established separately, so nothing is weakened by reading the monitor's
    count where it exists."""
    rows = climb_then_settle(final=1000, settled=0)
    rows += [sample(10.0, monitor=900, exported=1000),
             sample(11.0, monitor=950, exported=1000),
             # A withheld tail shorter than the truncation window, which
             # `series_truncated` already tolerates -- and the monitor draws
             # level inside it.
             sample(12.0, monitor=1000, exported=None),
             sample(13.0, monitor=1000, exported=None)]
    got = measurements.delivery_metrics(rows)
    assert got['unresolved_reason'] is None
    assert got['complete_s'] == 12.0
    assert got['monitor_final'] == 1000
    assert got['plateau_start_s'] == 10.0


def test_samples_with_no_times_are_named_rather_than_resolved_emptily():
    """A null `unresolved_reason` beside a null `complete_s` contradicts the
    documented contract and leaves the branch unnameable, which is the one
    outcome `_delivery()` exists to prevent."""
    rows = climb_then_settle()
    for row in rows:
        del row['monotonic_s']
    got = measurements.delivery_metrics(rows)
    assert got['complete_s'] is None
    assert got['unresolved_reason'] == 'no_sample_times'


def test_every_reason_the_function_can_return_is_documented():
    """`docs/measurement-dictionary.md` is what a reader consults when a run
    withholds this measurement, so a reason that reaches an artifact without a
    row there is a null the operator cannot look up. Checked against the
    source rather than a hand-kept list, because a hand-kept list is the
    second copy that drifts -- which is the whole reason `AGENTS.md` is a
    symlink."""
    import re

    from conftest import REPO_ROOT

    source = (REPO_ROOT / 'measurements.py').read_text(encoding='utf-8')
    body = source[source.index('def delivery_metrics('):]
    body = body[:body.index('\ndef ', 10)]
    reasons = set(re.findall(r"""_delivery\(\s*['"]([a-z_]+)['"]""", body))
    # A floor, not a fixed list: a hand-kept list is the second copy that
    # drifts, but a regex that quietly matches nothing would keep this test
    # green forever. Raised deliberately when a reason is added.
    assert len(reasons) >= 11, sorted(reasons)

    dictionary = (REPO_ROOT / 'docs' / 'measurement-dictionary.md').read_text(
        encoding='utf-8')
    undocumented = sorted(r for r in reasons if '`%s`' % r not in dictionary)
    assert not undocumented, undocumented


def test_an_ordinary_carried_reading_does_not_withhold_the_measurement():
    """A repeated read timestamp is not a dead sampler. The target's poll and
    the monitor's are independent loops, so whenever the target's CLI read is
    the slower of the two a reading spans two monitor samples and is carried
    twice -- `TARGET_TABLE_RESAMPLED` says so, and 11 of the 39 recorded runs
    on this host contain one. That is likeliest on exactly the large-table
    runs this measurement exists for, so refusing on any duplicate would
    withhold the answer from the rows that need it, naming a dead sampler that
    was alive."""
    rows = climb_then_settle(final=1000, settled=4)
    # One reading spanning two monitor samples, both well inside the bound.
    rows[-2]['witness_monotonic_s'] = rows[-3]['witness_monotonic_s']
    rows[-2]['witness_age_s'] = round(
        rows[-2]['monotonic_s'] - rows[-2]['witness_monotonic_s'], 6)
    got = measurements.delivery_metrics(rows)
    assert got['unresolved_reason'] is None
    assert got['complete_s'] == 10.0
    assert got['plateau_samples'] == 4


def test_a_plateau_resting_on_one_reading_is_still_refused():
    """The relaxation above must not reach the case the rule exists for: a
    plateau whose every sample repeats one read is one observation, whatever
    its length, and its ages can all sit inside the carry bound."""
    rows = climb_then_settle(final=1000, settled=4)
    frozen_at = rows[-4]['witness_monotonic_s']
    for row in rows[-4:]:
        row['witness_monotonic_s'] = frozen_at
        row['witness_age_s'] = round(row['monotonic_s'] - frozen_at, 6)
    got = measurements.delivery_metrics(rows)
    assert got['unresolved_reason'] == 'gauge_carried_across_plateau'
    assert max(r['witness_age_s'] for r in rows[-4:]) \
        <= measurements.DELIVERY_WITNESS_MAX_AGE_S
