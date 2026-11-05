"""The maintained newcomer smoke leaves an inspectable, explicitly simulated package."""

import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts import recipe_smoke


ROOT = Path(__file__).resolve().parent.parent


def test_smoke_walks_public_workflow_and_retains_verified_package(tmp_path):
    from recipe_results import verify_result_package

    output = tmp_path / 'newcomer'
    summary = recipe_smoke.run_smoke(output)
    assert summary['simulation'] is True
    assert summary['status'] == 'passed'
    assert set(summary['operations']) == {
        'export', 'validate', 'inspect', 'plan', 'check', 'prepare',
        'run', 'result-validate', 'result-verify'}
    assert len(summary['attempts']) == 1
    selected = {role['image'] for role in summary['attempts'][0]['roles'].values()}
    docker = [argv for argv in summary['probe_commands'] if argv[0] == 'docker']
    assert docker
    assert {argv[-1] for argv in docker} == selected
    assert all(argv[1:5] == ['--host', 'unix:///var/run/docker.sock', 'image', 'inspect']
               for argv in docker)
    assert verify_result_package(output / 'results/result.json')['valid'] is True
    assert json.loads((output / 'check.json').read_text())['status'] == 'checks_passed'
    assert json.loads((output / 'prepare.json').read_text())['acquisition'] == 'none'
    assert json.loads((output / 'smoke.json').read_text()) == summary
    assert 'SIMULATED' in (output / 'results/work/runtime.log').read_text()


def test_smoke_refuses_an_existing_output_without_modification(tmp_path):
    output = tmp_path / 'existing'
    output.mkdir()
    sentinel = output / 'keep'
    sentinel.write_text('original')
    with pytest.raises(FileExistsError):
        recipe_smoke.run_smoke(output)
    assert list(output.iterdir()) == [sentinel]
    assert sentinel.read_text() == 'original'


def test_smoke_refuses_relative_and_checkout_output(tmp_path):
    with pytest.raises(ValueError, match='absolute'):
        recipe_smoke.run_smoke('relative-smoke-output')
    with pytest.raises(ValueError, match='outside'):
        recipe_smoke.run_smoke(ROOT / 'smoke-output')


def test_simulated_command_allowlist_refuses_unselected_image():
    fixture = json.loads((ROOT / 'examples/recipes/synthetic-ipv4.recipe.json').read_text())
    host = recipe_smoke.SimulatedHost(fixture)
    with pytest.raises(AssertionError, match='unmodelled'):
        host.command(['docker', '--host', 'unix:///var/run/docker.sock',
                      'image', 'inspect', 'unselected:latest'])
    with pytest.raises(AssertionError, match='unmodelled'):
        host.command(['docker', '--host', 'unix:///var/run/docker.sock',
                      'image', 'pull', fixture['roles']['target']['image']])


def test_standalone_entrypoint_works_outside_checkout(tmp_path):
    output = tmp_path / 'standalone'
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/recipe_smoke.py'),
                             '--output', str(output)], cwd=tmp_path,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report['simulation'] is True
    assert report['status'] == 'passed'
    assert Path(report['result']).is_file()
