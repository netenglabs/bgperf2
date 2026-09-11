'''The CSV header, the stats row, and the graph column indices are coupled by
position only. Nothing in the code enforces that they agree, and when they drift
the failure is silent: the CSV mislabels its columns and the graphs plot the
wrong series. These tests are the enforcement.
'''
import bgperf2
import summary


def header_fields():
    return [f.strip() for f in bgperf2.stats_header().split(',')]


def test_header_and_row_have_the_same_length(bench_args, bench_stats):
    '''Regression: the header was missing 'tester timeouts', so every batch CSV
    was shifted by one column from 'failed' onward.
    '''
    row = bgperf2.create_output_stats(bench_args, 'v1.2.3', bench_stats)
    assert len(header_fields()) == len(row)


def test_header_and_row_agree_when_failed(bench_args, bench_stats):
    '''The failure path appends a message, so it must line up too.'''
    bench_stats['fail_msg'] = 'FAILED: stuck received count 0'
    row = bgperf2.create_output_stats(bench_args, 'v1.2.3', bench_stats, fail=True)
    assert len(header_fields()) == len(row)


def test_row_values_land_in_their_named_columns(bench_args, bench_stats):
    '''Spot-check that specific values appear under the right header name.'''
    row = bgperf2.create_output_stats(bench_args, 'v1.2.3', bench_stats)
    named = dict(zip(header_fields(), row))

    assert named['target'] == 'bird'
    assert named['version'] == 'v1.2.3'
    assert named['peers'] == '10'
    assert named['prefixes per peer'] == '100'
    assert named['required'] == 990
    assert named['received'] == 1000
    assert named['monitor (s)'] == 3
    assert named['elapsed (s)'] == 42
    assert named['tester errors'] == 0
    assert named['tester timeouts'] == 0
    assert named['cores'] == '32'


def test_legacy_testers_field_is_post_first_prefix_interval(bench_args, bench_stats):
    '''Pin the historical formula without endorsing the misleading column name.

    There is no tester-completion timestamp in this schema. The field must stay
    elapsed minus the first monitor-visible prefix until a new named metric is
    appended to the compatibility row.
    '''
    row = bgperf2.create_output_stats(bench_args, 'v1.2.3', bench_stats)
    named = dict(zip(header_fields(), row))

    assert named['testers (s)'] == 35


def test_graph_indices_point_at_the_columns_their_labels_claim():
    '''create_batch_graphs() indexes the row positionally. Pin each index to the
    header name it is supposed to be plotting, so a change to the row layout
    fails here instead of silently mislabeling a graph.
    '''
    fields = header_fields()
    expected = {
        6: 'received',
        7: 'monitor (s)',          # plotted as 'neighbor'
        8: 'elapsed (s)',
        9: 'prefix received (s)',
        10: 'testers (s)',         # plotted as 'route reception'
        11: 'total time',
        12: 'max cpu %',
        13: 'max mem (GB)',
        14: 'min idle%',
        15: 'min free mem (GB)',
        20: 'tester errors',
    }
    for index, name in expected.items():
        assert fields[index] == name, f"index {index} is '{fields[index]}', expected '{name}'"


def test_label_overrides_name_but_not_target(bench_args, bench_stats):
    bench_args.label = 'frr 8'
    row = bgperf2.create_output_stats(bench_args, 'v1', bench_stats)
    named = dict(zip(header_fields(), row))
    assert named['name'] == 'frr 8'
    assert named['target'] == 'bird'


def test_the_variance_rules_resolution_matches_the_monitor_poll_interval():
    '''`elapsed (s)` is not quantised by choice.

    It reaches the row as `stats['elapsed'].seconds`, counted off the monitor's
    poll loop with an integer number of assurance samples subtracted, so two
    things quantise it and the coarser wins: the `timedelta.seconds`
    truncation, always 1s, and the poll interval, 1s today and a real knob.
    Hence `max(1.0, ...)` rather than the interval alone -- pinning to the
    interval would go red if somebody polled twice a second and invite setting
    the resolution to 0.5, which understates the truncation, and two cells one
    whole second apart would then clear the floor and be published `separated`
    on a rounding boundary.

    `summary.METRIC_RESOLUTION` cannot import that constant -- bgperf2 imports
    summary, not the other way round, and the Docker-free import property
    depends on it staying that way -- so the two are pinned against each other
    here instead.

    If they drift apart the rule silently goes back to publishing `separated`
    on a difference of one rounding boundary, which is the one thing it must
    never do: it prints nothing about the results it supports, so there is no
    line to notice.
    '''
    assert summary.METRIC_RESOLUTION[summary.DECISION_METRIC] == max(
        1.0, float(bgperf2.MONITOR_POLL_INTERVAL_S))


def test_the_mrt_witness_tolerance_is_the_trackers_drop_fraction():
    '''The MRT correctness check compares two counts of one session -- the
    monitor's and the target's own -- and allows the same 1% the convergence
    tracker allows before it calls a monitor decline route loss. That is
    deliberate: it is the same kind of comparison one step later, and reusing
    the measured constant is what keeps it from being a tolerance invented to
    make a particular block pass.

    `scripts/check_timing_evidence.py` must not import bgperf2 -- it reads
    published documents and re-derives no measurement, which is what lets it
    run anywhere -- so the two are pinned against each other here, on the rule
    `summary.METRIC_RESOLUTION` follows above.
    '''
    import importlib.util

    import convergence
    from conftest import REPO_ROOT

    spec = importlib.util.spec_from_file_location(
        'check_timing_evidence_contract',
        REPO_ROOT / 'scripts' / 'check_timing_evidence.py')
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    assert checker.WITNESS_AGREEMENT_FRACTION == convergence.DROP_FRACTION


def test_the_stale_witness_bound_is_the_trackers_carry_bound():
    '''A target reading older than the tracker will carry one is not a
    cross-check either. Pinned here because the checker must not import
    bgperf2, on the rule the two constants above follow.'''
    import importlib.util

    import bgperf2 as _bgperf2
    import convergence
    from conftest import REPO_ROOT

    spec = importlib.util.spec_from_file_location(
        'check_timing_evidence_stale',
        REPO_ROOT / 'scripts' / 'check_timing_evidence.py')
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    assert checker.STALE_WITNESS_S == (
        convergence.WITNESS_CARRY_SAMPLES
        * float(_bgperf2.MONITOR_POLL_INTERVAL_S))


def test_the_delivery_age_bound_is_the_trackers_carry_bound():
    '''`delivery_metrics()` refuses a plateau any of whose readings was
    carried rather than taken, and the span it allows is the one
    `ConvergenceTracker` refuses to carry a reading past. Reusing the measured
    constant is what keeps it from being a staleness bound invented to make a
    particular run resolve -- and `measurements.py` stays free of project
    imports, like `summary.py` and the checker, so the two are pinned against
    each other here.'''
    import bgperf2 as _bgperf2
    import convergence
    import measurements

    assert measurements.DELIVERY_WITNESS_MAX_AGE_S == (
        convergence.WITNESS_CARRY_SAMPLES
        * float(_bgperf2.MONITOR_POLL_INTERVAL_S))


def test_the_checkers_synthetic_generator_list_matches_bgperf2s():
    '''A generator bgperf2 builds the prefix lists for has a `required` that is
    a statement of fact; an MRT injector's is a guess. A third synthetic
    generator added to bgperf2 and not to the checker would route its rows down
    the MRT branch and quietly stop applying `received >= required`.'''
    import importlib.util

    import bgperf2 as _bgperf2
    from conftest import REPO_ROOT

    spec = importlib.util.spec_from_file_location(
        'check_timing_evidence_synthetic',
        REPO_ROOT / 'scripts' / 'check_timing_evidence.py')
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    assert (tuple(checker.SYNTHETIC_TESTER_TYPES)
            == tuple(_bgperf2.SYNTHETIC_TESTER_TYPES))


def test_the_checkers_mrt_generator_list_matches_bgperf2s():
    '''`required` is a guess only for a generator that replays a file. A `-f`
    scenario run records `tester_type: null` and states its own check-point, so
    reading "not synthetic" as "MRT" would relax its correctness test too.'''
    import importlib.util

    import bgperf2 as _bgperf2
    from conftest import REPO_ROOT

    spec = importlib.util.spec_from_file_location(
        'check_timing_evidence_mrt',
        REPO_ROOT / 'scripts' / 'check_timing_evidence.py')
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    assert (tuple(checker.MRT_TESTER_TYPES)
            == tuple(_bgperf2.MRT_TESTER_TYPES))
