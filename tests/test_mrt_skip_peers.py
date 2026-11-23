'''`mrt_skip_peers`: keep named MRT source peers away from bgpdump2 injectors.

Some source peers tag every route with a well-known export-scope community.
In rib.20260808.0000, peer index 10 (AS37100) tags all 1,058,167 of its routes
`no-export`. A target that honors it (FRR) advertises fewer routes to the
monitor than one that does not, so the timings stop being comparable.
'''
from argparse import Namespace

import pytest

import bgperf2


@pytest.mark.parametrize('value, expected', [
    (None, set()),
    ('', set()),
    ('10', {10}),
    ('10, 12', {10, 12}),
    ([10, 12], {10, 12}),
    (10, {10}),
])
def test_bench_strings_and_batch_lists_read_the_same(value, expected):
    assert bgperf2.mrt_skip_peers(Namespace(mrt_skip_peers=value)) == expected


def test_absent_option_skips_nothing():
    assert bgperf2.mrt_skip_peers(Namespace()) == set()


@pytest.mark.parametrize('value', ['ten', '10,x', [-1], '-3'])
def test_a_value_that_is_not_a_peer_index_refuses(value):
    with pytest.raises(ValueError):
        bgperf2.mrt_skip_peers(Namespace(mrt_skip_peers=value))


def test_batch_copies_the_target_key_onto_bench_args():
    test = {'name': 't', 'neighbors': [1], 'prefixes': [10], 'filter_test': ['None'],
            'targets': [{'name': 'bird', 'mrt_skip_peers': [10]}]}
    [cell] = bgperf2.expand_batch_cells(test, test['targets'])
    assert bgperf2.batch_cell_args(Namespace(), cell).mrt_skip_peers == [10]
