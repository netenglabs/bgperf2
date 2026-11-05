import datetime
import sys
from types import ModuleType
from argparse import Namespace
from pathlib import Path

import pytest


@pytest.fixture(scope='session', autouse=True)
def isolate_production_storage():
    """Tests select scratch bindings explicitly; never inherit the live store."""
    with pytest.MonkeyPatch.context() as environment:
        environment.delenv('BGPERF_ARTIFACT_STORE', raising=False)
        environment.delenv('BGPERF_PARQUET_PYTHON', raising=False)
        yield

# The modules under test live at the repo root, not in a package.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


class NoDocker:
    """Allow method patching, but fail any unmocked runtime operation."""
    _version = '1.41'

    @property
    def api_version(self):
        return self._version

    def __getattr__(self, name):
        def forbidden(*args, **kwargs):
            raise AssertionError(f'Docker forbidden in engine unit tests: {name}')
        return forbidden


settings = ModuleType('settings')
settings.dckr = NoDocker()
sys.modules['settings'] = settings

FIXTURES = Path(__file__).resolve().parent / 'fixtures'


@pytest.fixture
def fixture_text():
    def _read(name):
        return (FIXTURES / name).read_text()
    return _read


@pytest.fixture
def bench_args():
    '''A Namespace with the attributes create_output_stats() reads.'''
    return Namespace(
        target='bird',
        label=None,
        neighbor_num=10,
        prefix_num=100,
        single_table=False,
        filter_test=None,
    )


@pytest.fixture
def bench_stats():
    '''A stats dict with the keys create_output_stats() reads.'''
    return {
        'elapsed': datetime.timedelta(seconds=42),
        'first_received_time': datetime.timedelta(seconds=7),
        'required': 990,
        'recved': 1000,
        'monitor_wait_time': 3,
        'total_time': 61.5,
        'max_cpu': 123.4,
        'max_mem': 5 * 1024 * 1024 * 1024,
        'min_idle': 88.0,
        'min_free': 50 * 1024 * 1024 * 1024,
        'cores': 32,
        'memory': 64 * 1024 * 1024 * 1024,
        'tester_errors': 0,
        'tester_timeouts': 0,
    }
