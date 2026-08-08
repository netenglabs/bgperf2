'''The CSV header, the stats row, and the graph column indices are coupled by
position only. Nothing in the code enforces that they agree, and when they drift
the failure is silent: the CSV mislabels its columns and the graphs plot the
wrong series. These tests are the enforcement.
'''
import bgperf2


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


def test_graph_indices_point_at_the_columns_their_labels_claim():
    '''create_batch_graphs() indexes the row positionally. Pin each index to the
    header name it is supposed to be plotting, so a change to the row layout
    fails here instead of silently mislabeling a graph.
    '''
    fields = header_fields()
    expected = {
        6: 'received',
        8: 'elapsed (s)',
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
