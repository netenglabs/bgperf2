"""The maintained controlled walkthrough retains auditable simulated evidence."""
import json
from pathlib import Path
import socket
import subprocess
from unittest.mock import patch

import pytest
import recipes
from recipe_comparison_report import verify_comparison_report
from recipe_results import verify_result_package
from scripts import comparison_smoke as smoke


@pytest.fixture(scope='module')
def simulated(tmp_path_factory):
    output = tmp_path_factory.mktemp('comparison-smoke') / 'artifacts'
    return output, smoke.run_smoke(output)


def report(summary, name):
    return recipes.read_document(summary['cases'][name]['report'])


def test_known_difference_preserves_samples_and_separate_definitions(simulated):
    output, summary = simulated
    assert summary['status'] == 'passed' and summary['simulation'] is True
    assert set(summary['cases']) == set(smoke.CASES)
    assert {'comparison-plan', 'compare', 'comparison-report', 'comparison-verify',
            'assertions-export', 'assertions-check'} <= set(summary['operations'])
    primary = report(summary, 'known-difference')
    assert primary['recipe_sha256'] == summary['recipe_sha256']
    assert primary['confounders'] == []
    assert primary['performance']['qualification'] == 'not_assessed'
    assert primary['performance']['policy'] == 'disabled'
    timing = primary['measurements']['timing']['monitor_elapsed_seconds']
    assert [item['value'] for item in timing['baseline']['observations']] == [10, 11, 12]
    assert [item['value'] for item in timing['candidate']['observations']] == [15, 16, 17]
    assert timing['baseline']['n'] == timing['candidate']['n'] == 3
    assert timing['baseline']['statistics']['stdev'] == 1
    delta = primary['descriptive_deltas']['timing']['monitor_elapsed_seconds']
    assert timing['candidate']['statistics']['median'] - timing['baseline']['statistics']['median'] == 5
    assert delta['candidate_minus_baseline_median'] == 5
    assert delta['qualification'] == 'unqualified_descriptive_only'
    cpu = primary['measurements']['cpu']['target_peak_cpu_percent']
    assert cpu['candidate']['statistics']['median'] - cpu['baseline']['statistics']['median'] == 10
    memory = primary['measurements']['memory']['target_cgroup_peak_bytes']['baseline']
    assert memory['n'] == 0 and memory['missing'] == 3
    assert all(item['value'] is None and item['reason'] for item in memory['observations'])
    sampled = primary['measurements']['memory']['target_delivery_sampled_peak_gib']
    assert sampled['baseline']['n'] == sampled['candidate']['n'] == 3
    assert primary['descriptive_deltas']['memory']['target_delivery_sampled_peak_gib']['candidate_minus_baseline_median'] == 1
    assert 'SIMULATED' in (output / 'SIMULATION.txt').read_text()
    assert 'SIMULATED' in Path(summary['report']).with_name('REPORT.md').read_text()
    assert (output / 'smoke.json').is_file()


def test_counterbalanced_and_seeded_orders_remain_frozen(simulated):
    _, summary = simulated
    primary = report(summary, 'known-difference')
    sequence = primary['plan']['sequence']
    assert [item['role'] for item in sequence] == [
        'baseline', 'candidate', 'candidate', 'baseline', 'baseline', 'candidate']
    assert [item['id'] for item in primary['attempts']] == [item['id'] for item in sequence]
    noise = report(summary, 'noise')
    assert noise['plan']['order'] == 'shuffle' and noise['plan']['seed'] == 1729
    for metrics in noise['measurements'].values():
        for metric in metrics.values():
            assert metric['candidate']['statistics'] == metric['baseline']['statistics']
    for role in ('baseline', 'candidate'):
        stats = noise['measurements']['timing']['monitor_elapsed_seconds'][role]['statistics']
        assert stats['max'] > stats['min']
    assert noise['performance']['policy'] == 'disabled'


def test_debug_and_probe_confounders_withhold_delta_without_erasing_values(simulated):
    _, summary = simulated
    confounded = report(summary, 'confounded')
    assert {'instrumentation', 'diagnostic_overhead'} <= {item['code'] for item in confounded['confounders']}
    for metrics in confounded['descriptive_deltas'].values():
        assert all(item['candidate_minus_baseline_median'] is None and item['reason'] for item in metrics.values())
    timing = confounded['measurements']['timing']['monitor_elapsed_seconds']
    assert timing['baseline']['statistics']['median'] == 11
    assert timing['candidate']['statistics']['median'] == 16


def test_failed_and_never_run_attempts_stay_distinct_without_retry(simulated):
    _, summary = simulated
    stopped = report(summary, 'stopped')
    assert [item['status'] for item in stopped['attempts']] == [
        'completed', 'harness_failed', 'not_run', 'not_run', 'not_run', 'not_run']
    assert len(summary['cases']['stopped']['attempts']) == 2
    timing = stopped['measurements']['timing']['monitor_elapsed_seconds']
    assert timing['baseline']['n'] == 1 and timing['baseline']['not_run'] == 2
    assert timing['candidate']['n'] == 0
    assert timing['candidate']['failed'] == 1 and timing['candidate']['not_run'] == 2
    assert all(item['value'] is None and item['reason'] for item in timing['candidate']['observations'])
    assert all(item['package'] is None for item in stopped['attempts'][2:])


def test_missing_measurements_remain_null_and_named(simulated):
    _, summary = simulated
    missing = report(summary, 'missing-measurements')
    assert all(item['status'] == 'completed' for item in missing['attempts'])
    for category, name in (('timing', 'monitor_elapsed_seconds'), ('cpu', 'target_peak_cpu_percent'),
                           ('memory', 'target_cgroup_peak_bytes')):
        metric = missing['measurements'][category][name]['baseline']
        assert metric['n'] == 2 and metric['missing'] == 1
        unavailable = next(item for item in metric['observations'] if item['id'] == 'r002-baseline')
        assert unavailable['value'] is None and unavailable['reason']
        assert missing['descriptive_deltas'][category][name]['candidate_minus_baseline_median'] is None
    memory = missing['measurements']['memory']['target_cgroup_peak_bytes']['baseline']
    assert all(item['value'] != 0 for item in memory['observations'])


def test_all_bundled_and_rebuilt_reports_verify_and_assertions_are_explicit(simulated):
    _, summary = simulated
    for name, case in summary['cases'].items():
        primary = report(summary, name)
        assert verify_comparison_report(case['report'])['valid'] is True
        assert verify_comparison_report(case['report_only'])['valid'] is True
        assert recipes.read_document(case['report_only']) == primary
        assert case['assertions']['outcome'] == 'passed'
        assert len(case['assertions']['assertions']) == (4 if name in ('known-difference', 'noise') else 5)
        assert case['assertions']['worker_deadline']['satisfied'] is True
        for attempt in primary['attempts']:
            if attempt['package']:
                path = Path(case['report']).parent / attempt['package']
                assert verify_result_package(path)['valid'] is True


def test_guards_refuse_unmodelled_commands_and_network(simulated):
    _, summary = simulated
    document = recipes.read_document(smoke.ROOT / 'examples/recipes/synthetic-ipv4.recipe.json')
    host = smoke.ComparisonHost(document)
    with pytest.raises(AssertionError, match='unmodelled'):
        host.command(['docker', 'pull', 'unexpected:latest'])
    docker = [args for args in summary['probe_commands'] if args[0] == 'docker']
    assert docker and all(args[1:5] == ['--host', 'unix:///var/run/docker.sock', 'image', 'inspect'] for args in docker)
    with patch.object(subprocess, 'Popen', smoke._forbidden), \
            patch.object(socket, 'create_connection', smoke._forbidden):
        with pytest.raises(AssertionError, match='unmodelled'):
            subprocess.Popen(['unexpected-command'])
        with pytest.raises(AssertionError, match='unmodelled'):
            socket.create_connection(('example.invalid', 1))


def test_refuses_existing_relative_or_checkout_output(tmp_path):
    output = tmp_path / 'existing'
    output.mkdir()
    sentinel = output / 'keep'
    sentinel.write_text('untouched')
    with pytest.raises(FileExistsError):
        smoke.run_smoke(output)
    assert list(output.iterdir()) == [sentinel] and sentinel.read_text() == 'untouched'
    with pytest.raises(ValueError, match='absolute'):
        smoke.run_smoke('relative')
    with pytest.raises(ValueError, match='outside'):
        smoke.run_smoke(smoke.ROOT / 'smoke-artifacts')


def test_main_runs_from_outside_checkout(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert smoke.main(['--output', str(tmp_path / 'standalone')]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary['simulation'] is True and Path(summary['report']).is_file()
