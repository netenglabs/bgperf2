"""Historical batch identities remain stable through the pure-layer extraction."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

import bgperf2


def test_cell_contract_import_does_not_initialize_engine_or_docker(tmp_path):
    script = '''
import importlib.abc, sys
class BlockRuntime(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'bgperf2', 'settings', 'docker', 'base'}:
            raise AssertionError('runtime import forbidden: ' + fullname)
sys.meta_path.insert(0, BlockRuntime())
sys.path.insert(0, sys.argv[1])
import batch_cells
'''
    subprocess.run([sys.executable, '-c', script, str(Path(__file__).resolve().parents[1])],
                   cwd=tmp_path, check=True)


@pytest.mark.parametrize('monitor', ['gobgp', 'sink'])
@pytest.mark.parametrize('repetitions', [1, 2])
def test_legacy_identity_retains_original_target_and_omission_rules(monitor, repetitions):
    target = {'name': 'bird'}
    test = {'name': 'portable', 'neighbors': [2], 'prefixes': [100],
            'filter_test': ['None'], 'targets': [target],
            'monitor': monitor, 'repetitions': repetitions}
    cells = bgperf2.expand_batch_cells(test, [target])
    for index, cell in enumerate(cells):
        expected = {'test': 'portable', 'ordinal': 0, 'neighbors': 2,
                    'prefixes': 100, 'filter': 'None', 'target': {'name': 'bird'}}
        if monitor == 'sink':
            expected['monitor'] = 'sink'
        if repetitions > 1:
            expected['repetition'] = index + 1
        legacy = json.dumps(expected, sort_keys=True, separators=(',', ':'))
        assert bgperf2.batch_cell_id('portable', cell) == legacy
        assert bgperf2.batch_cell_key(legacy) == hashlib.sha256(legacy.encode()).hexdigest()[:16]
    assert target == {'name': 'bird'}


def test_total_prefix_normalization_preserves_raw_target_version_labels():
    target = {'name': 'bird', 'versions': ['2.19.2', '3.1.0']}
    targets = bgperf2.expand_target_versions([target])
    test = {'name': 'versions', 'neighbors': [2], 'prefixes': [200],
            'filter_test': ['None'], 'targets': [target], 'prefix_scope': 'total'}
    cells = bgperf2.expand_batch_cells(test, targets)
    assert [cell['prefixes'] for cell in cells] == [100, 100]
    assert [json.loads(bgperf2.batch_cell_id('versions', cell))['target']
            for cell in cells] == [
                {'name': 'bird', 'version': '2.19.2', 'label': 'bird 2.19.2'},
                {'name': 'bird', 'version': '3.1.0', 'label': 'bird 3.1.0'}]
    assert target == {'name': 'bird', 'versions': ['2.19.2', '3.1.0']}


def test_nondefault_workload_dimensions_still_reach_identity():
    target = {'name': 'bird', 'tester_type': 'bird'}
    test = {'name': 'dimensions', 'neighbors': [4], 'prefixes': [100],
            'filter_test': ['None'], 'targets': [target],
            'path_diversity': 2, 'receivers': 1,
            'churn_prefixes': 10, 'churn_bursts': 2,
            'pin': 'testers=4-5,target=0-1,monitor=2,receivers=3'}
    cell, = bgperf2.expand_batch_cells(test, [target])
    identity = json.loads(bgperf2.batch_cell_id('dimensions', cell))
    assert identity == {
        'test': 'dimensions', 'ordinal': 0, 'neighbors': 4, 'prefixes': 100,
        'filter': 'None', 'target': target, 'monitor': 'sink',
        'path_diversity': 2, 'receivers': 1, 'churn_prefixes': 10,
        'churn_bursts': 2,
        'pin': 'target=0-1,monitor=2,testers=4-5,receivers=3'}
