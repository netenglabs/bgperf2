"""Report guards: invalid timings, replacement cells and CSV mismatches."""
import copy
import csv
import importlib.util
import json
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location(
    'plot_daemon_comparison', Path(__file__).resolve().parents[1] / 'scripts/plot_daemon_comparison.py')
plotter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plotter)


def cell(name='rustybgp 2026-08', peers=38):
    metric = {'median': 12, 'min': 10, 'max': 14, 'n': 3, 'values': [10, 12, 14]}
    return {'name': name, 'description': f'{name}, peers={peers}',
            'identity': {'peers': peers},
            'passes': [{'repetition': n, 'state': 'observed'} for n in (1, 2, 3)],
            'metrics': {key: copy.deepcopy(metric) for key in
                        ('elapsed (s)', 'max mem (GB)', 'max cpu %', 'received', 'min free mem (GB)')}}


def test_memory_exclusion_withholds_time_but_keeps_memory():
    evidence = plotter.Evidence('.')
    row = evidence.record('source', cell(), 'rrc00-n38')
    assert row['excluded']
    assert 'elapsed (s)' not in row['metrics']
    assert row['metrics']['max mem (GB)']['max'] == 14
    assert not any(c['metric'] == 'elapsed (s)' for c in evidence.claims.values())


def test_replacement_does_not_pool_invalid_original():
    class FakeEvidence:
        def batch(self, step, test=None, omit=()):
            candidates = [{'name': n, 'source': step} for n in
                          ('bird 2.19.2', 'rustybgp 2026-08') if n not in omit]
            if step.endswith('rerun'):
                return [{'name': 'rustybgp 2026-08', 'source': step}]
            return candidates
    _, rows = plotter.load_comparison(FakeEvidence())
    points = [r for r in rows if r['name'] == 'rustybgp 2026-08']
    assert len(points) == 5
    assert all(r['source'] != 'rrc00-n24' for r in points)
    assert sum(r['source'] == 'rrc00-n24-rustybgp-rerun' for r in points) == 1


def write_batch(tmp_path, changed=False):
    directory = tmp_path / plotter.COMPARISON / 'synth'
    directory.mkdir(parents=True)
    data = cell('bird 2.19.2', 50)
    (directory / '2026-comparison-synth.summary.json').write_text(json.dumps({'cells': [data]}))
    fields = ['name', 'failed', 'MSG', *data['metrics']]
    with (directory / '2026-comparison-synth.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for n, value in enumerate((10, 12, 14), 1):
            row = {m: value for m in data['metrics']}
            row.update(name=f'bird 2.19.2 #{n}', failed='', MSG='')
            if changed and n == 2:
                row['elapsed (s)'] = 999
            writer.writerow(row)


def test_changed_csv_refuses_plot(tmp_path):
    write_batch(tmp_path, changed=True)
    with pytest.raises(ValueError, match='values disagree'):
        plotter.Evidence(tmp_path).batch('synth')


def test_failed_pass_stays_failed_in_export(tmp_path):
    write_batch(tmp_path)
    evidence = plotter.Evidence(tmp_path)
    records = evidence.batch('synth')
    source = records[0]['source']
    evidence.raw_rows[(source, 'bird 2.19.2')].append(
        {'name': 'bird 2.19.2 #4', 'failed': 'FAILED', 'MSG': 'stuck',
         **{m: '0' for m in records[0]['metrics']}})
    plotter.write_data(evidence, records, tmp_path)
    with (tmp_path / 'comparison-passes.csv').open() as f:
        rows = list(csv.DictReader(f))
    assert rows[-1]['selection_status'] == 'failed'
    assert rows[-1]['selection_reason'] == 'stuck'
    assert len([r for r in rows if r['selection_status'] == 'included']) == 3
