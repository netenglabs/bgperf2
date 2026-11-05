"""Actual local Git preparation leaves a dirty maintainer checkout untouched."""
import json
from pathlib import Path
import re
import socket
import subprocess

import pytest

import recipes
import recipe_handoff as handoff
from scripts import checkout_workflow_smoke as smoke


def read(path):
    return json.loads(path.read_text())


@pytest.fixture(scope='module', params=['assertions', 'target_crash'])
def prepared(request, tmp_path_factory):
    output = tmp_path_factory.mktemp('checkout-workflow') / 'demo'
    return output, smoke.run_smoke(output, predicate=request.param)


def test_actual_git_range_preserves_original_and_dirty_fix(prepared):
    output, summary = prepared
    before, after = read(output / 'original-before.json'), read(output / 'original-after.json')
    assert before == after and before['status']
    assert summary['status'] == 'passed' and summary['fixture_source'] is True
    assert summary['prepared_revisions'] == 4 and summary['original_source_preserved'] is True
    assert not (output / 'UNEXPECTED-HOOK-EXECUTION').exists()
    manifest = read(output / 'prepared-range/source-range.json')
    plan = read(output / 'prepared-range/bisection-plan.json')
    assert [row['revision'] for row in manifest['candidates']] == [row['revision'] for row in plan['candidates']]
    assert manifest['good'] == plan['candidates'][0]['revision']
    assert manifest['bad'] == before['head'] == plan['candidates'][-1]['revision']
    assert plan['predicate'] == summary['predicate']
    assert all(not row['build_plan']['source']['dirty'] for row in plan['candidates'])
    candidate = read(output / 'candidate-build-plan.json')
    assert candidate['source']['dirty'] is candidate['source']['include_dirty'] is True
    assert candidate['source']['commit'] == before['head']
    assert [row['path'] for row in candidate['source']['untracked']] == ['local-fix.txt']
    assert candidate['recipe_sha256'] == summary['recipe_sha256']


def test_handoff_references_actual_future_artifacts_without_starting_work(prepared):
    output, summary = prepared
    manifest = read(output / 'handoff/handoff.json')
    graph = read(output / 'handoff/commands.json')
    assert all(not Path(path).exists() for path in manifest['destinations'].values())
    assert summary['execution'] == graph['execution'] == manifest['execution'] == 'not_requested'
    assert all(step['execution'] == 'not_requested' for step in graph['steps'])
    assert all(target['image'] is None and target['availability'] == 'unassessed'
               for target in graph['future_targets'].values())
    assert summary['handoff_readiness'] == dict(local_image_availability='unassessed',
        host_suitability='unassessed', execution_authorization='unassessed', performance_policy='disabled')
    assert manifest['comparison'] == dict(repetitions=2, order='shuffle', seed=7)
    assert handoff.verify_handoff(output / 'handoff/handoff.json')['valid'] is True
    assert all(receipt['valid'] for receipt in read(output / 'verification.json').values())
    steps = {step['id']: step for step in graph['steps']}
    assert {'build_baseline', 'build_candidate', 'reproduce', 'investigate',
            'export_assertions', 'plan_comparison', 'step_bisection'} <= steps.keys()
    assert '--execute' in steps['step_bisection']['argv']  # text only, never dispatched
    assert not any(command['arguments'][0] in ('target-build', 'run', 'investigate', 'compare', 'step')
                   for command in read(output / 'commands.json'))


def test_readable_index_and_public_command_records_exist(prepared):
    output, summary = prepared
    text = (output / 'REPORT.md').read_text()
    assert 'real local Git' in text and 'inert' in text
    assert Path(summary['index']).is_file()
    for relative in re.findall(r'\]\(([^)]+)\)', text):
        assert (output / relative).is_file(), relative
    records = read(output / 'commands.json')
    assert records == [read(path) for path in sorted((output / 'commands').glob('*.json'))]
    assert {'prepare', 'verify', 'target-source-plan'} <= {row['arguments'][0] for row in records}


def test_guard_allows_no_unmodelled_process_transport_or_runtime(tmp_path, monkeypatch):
    def probe(output, predicate):
        for command in (['docker', 'build', '.'], ['python', '-c', 'pass'],
                        ['git', 'fetch', 'https://example.invalid/source'],
                        ['git', 'clone', 'https://example.invalid/source'],
                        ['git', 'worktree', 'remove', '/tmp/never-remove']):
            with pytest.raises(AssertionError, match='unmodelled'):
                subprocess.Popen(command)
        with pytest.raises(AssertionError, match='unmodelled'):
            socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        return {'guarded': True}
    monkeypatch.setattr(smoke, '_run_smoke', probe)
    assert smoke.run_smoke(tmp_path / 'unused') == {'guarded': True}


def test_output_is_exclusive_and_outside_checkout(tmp_path):
    existing = tmp_path / 'existing'
    existing.mkdir()
    sentinel = existing / 'keep'
    sentinel.write_text('original')
    with pytest.raises(FileExistsError):
        smoke.run_smoke(existing)
    assert sentinel.read_text() == 'original'
    with pytest.raises(recipes.ContractError, match='absolute'):
        smoke.run_smoke('relative')
    with pytest.raises(recipes.ContractError, match='outside'):
        smoke.run_smoke(smoke.ROOT / 'new-output')
