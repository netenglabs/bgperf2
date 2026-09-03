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
