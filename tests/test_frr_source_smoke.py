"""Source-bound FRR workflow: modeled fault, reduction and fresh boundary evidence."""
import json
import re
import shutil
import socket
import subprocess

import pytest

import recipes
import recipe_bisection as bisect
from scripts import frr_source_smoke as smoke


def read(path):
    return json.loads(path.read_text())


@pytest.fixture(scope='module')
def walked(tmp_path_factory):
    output = tmp_path_factory.mktemp('frr-source') / 'walkthrough'
    return output, smoke.run_smoke(output)


def test_source_bound_builds_and_candidate_ci(walked):
    output, summary = walked
    assert summary['status'] == 'passed' and summary['simulation']
    for side in ('baseline', 'candidate'):
        target = read(output / ('build-' + side) / 'target.json')
        assert target['adapter'] == 'frr_c'
        assert target['provenance']['kind'] == 'local_source'
        assert target['provenance']['build']['recipe'] == 'frr-local/v1'
    pair = read(output / 'return/pair/investigation.json')
    baseline = pair['correctness']['attempts']['baseline']
    candidate = pair['correctness']['attempts']['candidate']
    assert baseline['outcome'] == 'failed' and candidate['outcome'] == 'passed'
    assertions = {row['name']: row['status'] for row in baseline['assertions']}
    assert assertions['observer.count'] == 'passed'
    assert assertions['observer.prefixes'] == 'failed'


def test_minimization_replans_recipe_bound_source_and_confirms_boundary(walked):
    output, summary = walked
    assert summary['minimization']['confirmed']
    assert summary['minimization']['best'] == {'peers': 1, 'routes': 2}
    original, reduced = read(output / 'recipe.json'), read(output / 'reduced-recipe.json')
    assert recipes.recipe_sha256(original) != recipes.recipe_sha256(reduced)
    plan = read(output / 'bisection-plan.json')
    assert plan['recipe'] == reduced and plan['predicate'] == 'prefix_assertions'
    assert all(row['build_plan']['recipe_sha256'] == recipes.recipe_sha256(reduced)
               for row in plan['candidates'])
    conclusion = summary['conclusion']
    assert conclusion['state'] == 'confirmed'
    report = read(output / 'return/search/bisection.json')
    # Fresh good/bad confirmations are additional observations, never aliases
    # of endpoint or midpoint packages.
    ids = [row['id'] for row in summary['attempts']]
    assert len(ids) == len(set(ids))
    assert all(row['roles']['target']['adapter'] == 'frr_c' for row in summary['attempts'])
    assert report['plan']['max_trials'] == 16


def test_recovery_never_repeats_pending_original(walked):
    output, summary = walked
    pending = read(output / 'pending-status.json')
    assert pending['conclusion']['state'] == 'recovery_required'
    assert pending['trials_recorded'] == 2
    records = read(output / 'commands.json')
    recoveries = [row for row in records if row['arguments'][0] == 'recover']
    assert len(recoveries) == 1 and recoveries[0]['exit_code'] == 0
    import hashlib
    assert hashlib.sha256((output / 'search/results/t0003/result.json').read_bytes()).hexdigest() == summary['recovered_original_sha256']
    assert not (output / 'search/pending.json').exists()


def test_portable_reports_verify_without_runtime_and_tampering_refuses(walked, tmp_path, monkeypatch):
    output, summary = walked
    assert all(row['valid'] for row in read(output / 'verification.json').values())
    for path in re.findall(r'\]\(([^)]+)\)', (output / 'REPORT.md').read_text()):
        assert (output / path).is_file()
    relocated = tmp_path / 'portable'
    shutil.copytree(output / 'return', relocated)
    monkeypatch.setattr(subprocess, 'Popen', smoke._forbidden)
    monkeypatch.setattr(socket.socket, '__init__', smoke._forbidden)
    assert bisect.verify_report(relocated / 'search/bisection.json')['valid']
    assert recipes.main(['investigation-verify', str(relocated / 'pair/investigation.json')]) == 0
    with (relocated / 'search/REPORT.md').open('a') as stream:
        stream.write('altered conclusion\n')
    with pytest.raises(recipes.ContractError):
        bisect.verify_report(relocated / 'search/bisection.json')
    assert summary['performance_policy'] == 'disabled' and summary['calibration'] == 'deferred'
