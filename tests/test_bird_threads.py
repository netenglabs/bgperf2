'''BIRD's `threads` option.

BIRD 3 is the multi-threaded rewrite, but it starts a single worker unless the
config asks for more -- measured without this, 3.x looks like 2.x and the whole
reason to compare the two releases disappears. Verified against the real
daemons: bird 2.19.2 runs 1 OS thread whatever the config says, bird 3.3.2 runs
2 by default and 5 with `threads 4`.

Targets are built with object.__new__ so no container is created.
'''
from argparse import Namespace

import pytest

import bgperf2
from bird import BIRDTarget


def write(tmp_path, conf, scenario=None):
    target = object.__new__(BIRDTarget)
    target.conf = conf
    target.host_dir = str(tmp_path)
    target.scenario_global_conf = scenario or {'testers': [], 'monitor': {
        'as': 1001, 'router-id': '10.10.0.2', 'local-address': '10.10.0.2'}}
    target.write_config()
    return (tmp_path / BIRDTarget.CONFIG_FILE_NAME).read_text()


BASE_CONF = {'as': 1000, 'router-id': '10.10.255.254',
             'local-address': '10.10.255.254', 'single-table': False}


def test_threads_reaches_the_config(tmp_path):
    conf = dict(BASE_CONF, threads=4)
    assert 'threads 4;' in write(tmp_path, conf)


def test_threads_comes_before_router_id(tmp_path):
    '''BIRD wants the global option at the top of the file.'''
    config = write(tmp_path, dict(BASE_CONF, threads=8))
    assert config.index('threads 8;') < config.index('router id')


def test_absent_by_default(tmp_path):
    '''Leaving it out keeps every existing scenario byte-identical.'''
    assert 'threads' not in write(tmp_path, dict(BASE_CONF))


@pytest.mark.parametrize('value', [0, None])
def test_falsy_values_emit_nothing(tmp_path, value):
    assert 'threads' not in write(tmp_path, dict(BASE_CONF, threads=value))


def test_gen_conf_passes_threads_through():
    args = Namespace(
        neighbor_num=1, prefix_num=1, filter_type='in', as_path_list_num=0,
        prefix_list_num=0, community_list_num=0, ext_community_list_num=0,
        single_table=False, target_config_file=None, local_address_prefix='10.10.0.0/16',
        target_local_address=None, target_router_id=None, monitor_local_address=None,
        monitor_router_id=None, filter_test=None, license_file=None, threads=4,
        mrt_file=None, tester_type='bird',
    )
    conf = bgperf2.gen_conf(args)
    assert 'threads: 4' in conf or "threads: '4'" in conf


def test_batch_passes_threads_through_to_bench():
    '''batch() copies a fixed field list onto the bench args; a field missing
    from that list is silently dropped at runtime.
    '''
    import inspect
    assert "'threads'" in inspect.getsource(bgperf2.batch)
