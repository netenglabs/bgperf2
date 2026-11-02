#!/usr/bin/env python3
"""Exercise automatic local storage using an explicitly SIMULATED backend.

No Docker, image acquisition, daemon build or benchmark. Output must be new.
"""
import argparse
import csv
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from artifact_store import Store, capture_tree, export_tree, publish, canonical, safe_absolute
from artifact_samples import COLUMNS
from recipe_results import verify_result_package
from recipe_run import run_recipe
import recipes


class Simulated:
    def execute(self, document, work, attempt, timeout):
        (work / 'tester.conf').write_bytes(b'SIMULATED identical configuration\n' * 40000)
        (work / 'tester.log').write_bytes(b'SIMULATED identical diagnostic evidence\n' * 40000)
        with (work / 'raw-samples.csv').open('w', newline='') as stream:
            writer = csv.writer(stream)
            writer.writerow(COLUMNS)
            writer.writerows([[0, 12.5, 100, 0, 0, 80, 1000], [1, None, None, 100, 1, 90, 900]])
        result = {'status': 'completed', 'reason': 'SIMULATED backend; no benchmark executed', 'cleanup_errors': []}
        publish(work / 'runtime.json', canonical(result))
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    output = safe_absolute(args.output)
    if os.path.lexists(output):
        parser.error('Output must not already exist')
    output.mkdir(parents=True, mode=0o700)
    previous = os.environ.get('BGPERF_ARTIFACT_STORE')
    os.environ['BGPERF_ARTIFACT_STORE'] = str(output / 'store')
    try:
        recipe = recipes.read_document(ROOT / 'examples/recipes/synthetic-ipv4.recipe.json')
        recipe['reproduction']['question'] = 'SIMULATED storage smoke; no measured result or host qualification.'
        for index in range(2):
            name = f'attempt-{index + 1}'
            work, result = output / 'work' / name, output / 'attempts' / name
            run_recipe(recipe, workdir=work, results_dir=result, backend=Simulated(),
                       check=lambda *a, **k: {'status': 'checks_passed', 'scope': 'SIMULATED prerequisite bypass'})
            assert not (work / 'tester.log').exists()
            assert not (work / 'tester.conf').exists()
            assert verify_result_package(result / 'result.json')['valid']
        store = Store(output / 'store')
        for index in range(3):
            destination = output / 'checkpoints' / str(index + 1)
            capture_tree(output / 'attempts/attempt-1', destination, store)
            assert verify_result_package(destination / 'result.json')['valid']
        export_tree(output / 'attempts/attempt-1', output / 'portable')
        assert verify_result_package(output / 'portable/result.json')['valid']
        report = store.maintain(apply=True)
        assert report['objects'] == 2
        summary = {'scope': 'SIMULATED storage only; no benchmark executed',
                   'independent_attempts': 2, 'reference_checkpoints': 3,
                   'unique_bulk_objects': report['objects'], 'registered_packages': report['roots'],
                   'original_bulk_work_reclaimed': True, 'portable_export_verified': True,
                   'optional_parquet': bool(os.environ.get('BGPERF_PARQUET_PYTHON'))}
        publish(output / 'STORAGE-SMOKE.json', canonical(summary))
        print(json.dumps(summary, indent=2))
    finally:
        if previous is None:
            os.environ.pop('BGPERF_ARTIFACT_STORE', None)
        else:
            os.environ['BGPERF_ARTIFACT_STORE'] = previous


if __name__ == '__main__':
    main()
