"""Controlled investigation walkthroughs preserve evidence without a runtime."""
import json
from pathlib import Path
import subprocess
import sys

import pytest
import recipes
from recipe_investigation import verify_investigation_report
from recipe_results import verify_result_package
from scripts import investigation_smoke as smoke

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def simulated(tmp_path):
    output = tmp_path / 'investigation'
    return output, smoke.run_smoke(output)


def report(output, scenario):
    return json.loads((output / scenario / 'results/report/investigation.json').read_text())


def test_smoke_returns_coherent_frozen_baseline_fix_pair(simulated):
    output, summary = simulated
    assert summary['simulation'] is True and summary['status'] == 'passed'
    assert {'target-image', 'target-source-plan', 'target-build', 'investigate',
            'target-validate', 'run', 'result-verify', 'investigation-report',
            'investigation-verify'} <= set(summary['operations'])
    primary = report(output, 'resolved')
    assert primary['assessment']['outcome'] == 'baseline_reproduced_candidate_not_reproduced'
    assert primary['assessment']['performance']['qualification'] == 'not_assessed'
    assert primary['attempts']['baseline']['status'] == 'experiment_failed'
    assert primary['attempts']['candidate']['status'] == 'completed'
    assert len(summary['cases']['resolved']['attempts']) == 2
    recipe = recipes.read_document(output / 'recipe.json')
    assert primary['recipe_sha256'] == recipes.recipe_sha256(recipe)
    baseline, candidate = (primary['attempts'][role] for role in ('baseline', 'candidate'))
    assert baseline['effective_roles']['target']['image'] == smoke.BASELINE_IMAGE
    assert candidate['effective_roles']['target']['image'] == smoke.CANDIDATE_IMAGE
    for role in ('generator', 'observer'):
        assert baseline['effective_roles'][role] == candidate['effective_roles'][role] == recipe['roles'][role]
    assert verify_investigation_report(summary['report'])['valid'] is True
    assert verify_result_package(summary['direct_override']['result'])['valid'] is True
    assert summary['direct_override']['attempts'][0]['target'] == smoke.CANDIDATE_IMAGE
    baseline_root = output / 'resolved/results/baseline'
    diagnostic = json.loads((baseline_root / 'work/diagnostics.json').read_text())
    assert diagnostic['containers'][0]['state']['Running'] is True
    live = json.loads((baseline_root / 'work/live-diagnostics.json').read_text())
    assert live['samples'][0]['bird_process_present'] is True
    assert live['samples'][1]['bird_process_present'] is False
    assert live['samples'][1]['daemon_exit_code'] == 139
    assert (output / 'smoke.json').is_file()
    assert 'SIMULATED' in (output / 'SIMULATION.txt').read_text()


def test_smoke_source_fix_records_dirty_patch_untracked_and_build_inputs(simulated):
    output, summary = simulated
    primary = report(output, 'resolved')
    baseline = primary['attempts']['baseline']['target']['provenance']
    candidate = primary['attempts']['candidate']['target']['provenance']
    assert baseline['kind'] == 'supplied_image' and baseline['source'] is None
    assert baseline['instrumentation'] == 'optimized'
    assert candidate['kind'] == 'local_source' and candidate['instrumentation'] == 'debug'
    assert candidate['source']['dirty'] is True
    assert candidate['source']['include_dirty'] is True
    assert candidate['source']['commit'] == smoke.SOURCE_REVISION
    assert candidate['source']['patch_sha256']
    assert candidate['source']['untracked'][0]['path'] == 'local-note.txt'
    assert candidate['build']['toolchain_image'] == smoke.TOOLCHAIN_IMAGE
    assert candidate['build']['runtime_image'] == smoke.RUNTIME_IMAGE
    assert candidate['build']['compiler_flags'] == '-O0 -g'
    assert candidate['build']['reconstructible'] is False
    assert candidate['build']['binary_sha256'] is None
    assert 'SIMULATED' in (output / 'simulated-source/fixture.c').read_text()
    assert 'SIMULATED' in (output / 'simulated-build/build.log').read_text()
    assert len(summary['build_commands']) == 1
    assert '--pull=false' in summary['build_commands'][0]
    assert '--network=none' in summary['build_commands'][0]
    assert summary['source_git_commands']


def test_collector_failure_retains_partial_package_and_does_not_run_candidate(simulated):
    output, summary = simulated
    partial = report(output, 'collector-failure')
    assert partial['assessment']['outcome'] == 'inconclusive'
    assert partial['attempts']['baseline']['status'] == 'harness_failed'
    assert partial['attempts']['baseline']['reproduction']['outcome'] == 'inconclusive'
    assert partial['attempts']['candidate']['status'] == 'not_run'
    assert len(summary['cases']['collector-failure']['attempts']) == 1
    baseline = output / 'collector-failure/results/baseline'
    assert verify_result_package(baseline / 'result.json')['valid'] is True
    diagnostic = json.loads((baseline / 'work/diagnostics.json').read_text())
    assert diagnostic['status'] == 'partial'
    assert diagnostic['errors'] == ['SIMULATED collector failure']
    assert 'SIMULATED' in (baseline / 'work/runtime.log').read_text()


def test_unavailable_memory_stays_null_with_accounting_and_reasons(simulated):
    output, _ = simulated
    case = report(output, 'missing-memory')
    assert case['assessment']['outcome'] == 'baseline_reproduced_candidate_not_reproduced'
    for attempt in case['attempts'].values():
        memory = attempt['diagnostics']['value']['memory']['target']
        assert memory['peak_bytes'] is None and memory['ending_bytes'] is None
        assert memory['sampled_peak_bytes'] is None
        assert memory['daemon_process_rss_bytes'] is None
        assert memory['reason'] and memory['daemon_process_reason']
        assert memory['units'] == 'bytes'
        assert 'cgroup' in memory['accounting']
    prose = (output / 'missing-memory/results/report/REPORT.md').read_text()
    assert 'None' in prose
    assert 'not a leak diagnosis' in prose


def test_smoke_only_allows_selected_image_inspection_and_fake_build(simulated):
    _, summary = simulated
    docker = [command for command in summary['probe_commands'] if command[0] == 'docker']
    assert docker
    assert all(command[1:5] == ['--host', 'unix:///var/run/docker.sock', 'image', 'inspect'] for command in docker)
    fixture = recipes.read_document(ROOT / 'examples/recipes/synthetic-ipv4.recipe.json')
    host = smoke.InvestigationHost(fixture, None)
    with pytest.raises(AssertionError, match='unmodelled'):
        host.command(['docker', '--host', 'unix:///var/run/docker.sock', 'pull', 'unselected:latest'])
    with pytest.raises(AssertionError, match='Unmodelled build'):
        host.build(['docker', 'build', '.'], env={}, timeout=1, log_path=Path('/unused'))


def test_smoke_refuses_existing_relative_and_checkout_destinations(tmp_path):
    output = tmp_path / 'existing'
    output.mkdir()
    sentinel = output / 'keep'
    sentinel.write_text('original')
    with pytest.raises(FileExistsError):
        smoke.run_smoke(output)
    assert list(output.iterdir()) == [sentinel]
    assert sentinel.read_text() == 'original'
    with pytest.raises(ValueError, match='absolute'):
        smoke.run_smoke('relative')
    with pytest.raises(ValueError, match='outside'):
        smoke.run_smoke(ROOT / 'smoke-artifact')


def test_standalone_smoke_runs_from_outside_checkout(tmp_path):
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/investigation_smoke.py'),
                             '--output', str(tmp_path / 'standalone')], cwd=tmp_path,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    document = json.loads(result.stdout)
    assert document['simulation'] is True
    assert Path(document['report']).is_file()
