'''`-s/--single-table` is refused at every entry point (bgperf2-0ma).

No target implemented it: BIRD's only reader was a per-neighbour config path
nothing had run since 2021, and every other daemon never read it. The baseline
published `bird -s` and `bird` as two configurations that were one, so the flag
is refused rather than accepted -- on all four paths, since a refusal applied
to three is a silent acceptance on the fourth.
'''
from argparse import Namespace

import pytest

import bgperf2
from bird import BIRDTarget


def a_test(**overrides):
    test = {'name': 'scale', 'neighbors': [10], 'prefixes': [100],
            'filter_test': ['None'], 'targets': [{'name': 'bird'}]}
    test.update(overrides)
    return test


def test_bench_refuses_the_flag_before_anything_else():
    # Only what the guard reads: a refusal that needed more would have run
    # some other code first.
    args = Namespace(single_table=True, file=None, dir='/tmp', bench_name='x',
                     docker_network_name=None)
    with pytest.raises(SystemExit) as raised:
        bgperf2.bench(args)
    assert '-s/--single-table is refused' in str(raised.value)


def test_bench_refuses_the_flag_beside_a_scenario_file_too():
    args = Namespace(single_table=True, file='scenario.yaml', dir='/tmp',
                     bench_name='x', docker_network_name=None)
    with pytest.raises(SystemExit) as raised:
        bgperf2.bench(args)
    assert '-s/--single-table is refused' in str(raised.value)


def test_a_scenario_asking_for_it_is_refused_before_the_teardown(tmp_path, monkeypatch):
    scenario = tmp_path / 'scenario.yaml'
    scenario.write_text('target: {as: 1000, single-table: true}\n')
    torn_down = []
    monkeypatch.setattr(bgperf2, 'remove_target_containers',
                        lambda: torn_down.append(True))
    args = Namespace(single_table=False, file=str(scenario), dir=str(tmp_path),
                     bench_name='x', docker_network_name=None, repeat=True)
    with pytest.raises(SystemExit) as raised:
        bgperf2.bench(args)
    assert "scenario's target `single-table` is refused" in str(raised.value)
    assert not torn_down


def test_config_refuses_the_flag():
    args = Namespace(single_table=True, neighbor_num=1, prefix_num=1)
    with pytest.raises(SystemExit) as raised:
        bgperf2.config(args)
    assert '-s/--single-table is refused' in str(raised.value)


def test_a_batch_target_asking_for_it_is_refused():
    test = a_test(targets=[{'name': 'bird', 'label': 'bird -s',
                            'single_table': True}])
    with pytest.raises(SystemExit) as raised:
        bgperf2.check_batch_test(test)
    assert "target 'bird -s' carries single_table" in str(raised.value)


@pytest.mark.parametrize('value', [False, None])
def test_the_default_spelled_out_still_runs(value):
    '''An older batch file that writes the default out asks for nothing.'''
    bgperf2.check_batch_test(a_test(targets=[{'name': 'bird',
                                              'single_table': value}]))
    bgperf2.refuse_single_table(value, 'x')


def test_the_scenario_no_longer_carries_the_key():
    args = Namespace(
        neighbor_num=1, prefix_num=1, filter_type='in', as_path_list_num=0,
        prefix_list_num=0, community_list_num=0, ext_community_list_num=0,
        single_table=False, target_config_file=None,
        local_address_prefix='10.10.0.0/16', target_local_address=None,
        target_router_id=None, monitor_local_address=None,
        monitor_router_id=None, filter_test=None, license_file=None,
        mrt_file=None, tester_type='bird')
    assert 'single-table' not in bgperf2.gen_conf(args)


def test_bird_renders_without_the_key(tmp_path):
    '''What `gen_conf()` now writes, and what an older scenario still says.'''
    for conf in ({}, {'single-table': False}):
        target = object.__new__(BIRDTarget)
        target.conf = dict(conf, **{'as': 1000, 'router-id': '10.10.255.254',
                                    'local-address': '10.10.255.254'})
        target.host_dir = str(tmp_path)
        target.scenario_global_conf = {'testers': [], 'monitor': {
            'as': 1001, 'router-id': '10.10.0.2', 'local-address': '10.10.0.2'}}
        target.write_config()
        config = (tmp_path / BIRDTarget.CONFIG_FILE_NAME).read_text()
        assert 'neighbor range 10.0.0.0/8 external;' in config
        assert 'protocol pipe' not in config


def test_the_row_flags_column_stays_and_is_empty(bench_args, bench_stats):
    header = bgperf2.stats_header().split(',')
    row = bgperf2.create_output_stats(bench_args, 'v', bench_stats)
    assert row[[c.strip() for c in header].index('flags')] == ''


def test_a_batch_file_target_asking_for_it_is_refused_before_any_cell(tmp_path):
    '''Refused at its cell, the SystemExit would leave batch() hours in.'''
    scenario = tmp_path / 'old.yaml'
    scenario.write_text('target: {as: 1000, single-table: true}\n')
    test = a_test(targets=[{'name': 'bird', 'file': str(scenario)}])
    with pytest.raises(SystemExit) as raised:
        bgperf2.check_batch_test(test)
    assert "scenario file" in str(raised.value)
    assert 'sets single-table, which is refused' in str(raised.value)


def test_a_scenario_asking_for_nothing_passes(tmp_path):
    scenario = tmp_path / 'ok.yaml'
    scenario.write_text('target: {as: 1000, single-table: false}\n')
    bgperf2.check_batch_test(a_test(targets=[{'name': 'bird',
                                              'file': str(scenario)}]))


def test_a_scenarios_bad_receivers_are_refused_before_the_teardown(tmp_path, monkeypatch):
    '''bgperf2-urp: this used to run after the previous run was torn down.'''
    scenario = tmp_path / 'scenario.yaml'
    scenario.write_text('target: {as: 1000}\nreceivers: 3\n')
    torn_down = []
    monkeypatch.setattr(bgperf2, 'remove_target_containers',
                        lambda: torn_down.append(True))
    args = Namespace(single_table=False, file=str(scenario), dir=str(tmp_path),
                     bench_name='x', docker_network_name=None, repeat=True)
    with pytest.raises(SystemExit) as raised:
        bgperf2.bench(args)
    assert 'must be a list of sessions' in str(raised.value)
    assert not torn_down
