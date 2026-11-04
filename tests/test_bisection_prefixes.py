"""SIMULATED prefix histories and inert Git never run BIRD or a compiler."""
import copy
import hashlib
import json
from pathlib import Path
import shutil

import pytest

import recipe_bisection as bisect
import recipe_handoff as handoff
import recipe_source_range as ranges
import recipes
from test_investigation_prefixes import package
from test_recipe_bisection import fixture_plan, fake_target
from test_source_range import source, TOOLCHAIN, RUNTIME, state as source_state


def prefix_backends(root, plan, *, first_bad=4, unavailable=(), interrupt_index=None):
    """Fresh sealed observations at each call; the modeled change preserves count."""
    built, ran = [], []
    indices = {row['revision']: index for index, row in enumerate(plan['candidates'])}

    def build(document, *, output_dir, emit_disclosure, timeout):
        index = indices[document['source']['commit']]
        built.append(index)
        output_dir.mkdir(parents=True)
        emit_disclosure({'SIMULATED': True, 'revision': document['source']['commit']})
        return fake_target(document)

    def run(recipe, *, target, workdir, results_dir, timeout, diagnostics, observer_prefixes):
        assert observer_prefixes is True
        index = indices[target['provenance']['source']['commit']]
        ran.append(index)
        capture = 'unavailable' if index in unavailable else 'wrong' if index >= first_bad else 'correct'
        original = package(root / f'SIMULATED-original-{len(ran)}', recipe, target['image'],
                           target=target, capture=capture)
        workdir.mkdir(parents=True)
        shutil.copytree(original.parent, results_dir)
        if index == interrupt_index:
            raise RuntimeError('SIMULATED controller stopped after original publication')
        return recipes.read_document(results_dir / 'result.json')

    return built, ran, build, run


def test_prefix_boundary_preserves_count_and_uses_fresh_confirmations_and_cache(tmp_path):
    plan = fixture_plan(tmp_path, predicate='prefix_assertions')
    session = tmp_path / 'session'
    bisect.initialize(plan, session)
    built, ran, build, run = prefix_backends(tmp_path / 'fixtures', plan)
    conclusion = bisect.run_search(session, build=build, run=run)
    assert conclusion['state'] == 'confirmed'
    assert conclusion['last_observed_good'] == plan['candidates'][3]['revision']
    assert conclusion['first_observed_bad'] == plan['candidates'][4]['revision']
    assert len(ran) == 7 and len(built) == 5 and ran[-2:] == [3, 4]
    _, records = bisect.history(session)
    assert len({row['observed']['source_attempt_id'] for row in records}) == len(ran)
    for row in records:
        assertions = {item['name']: item for item in row['observed']['assertions']['assertions']}
        assert set(assertions) == {'sessions.ready', 'injection.complete', 'observer.count',
                                   'experiment.complete', 'observer.prefixes'}
        assert assertions['observer.count']['status'] == 'passed'
        identity = assertions['observer.prefixes']
        assert identity['status'] == ('failed' if row['classification'] == 'bad' else 'passed')
    status = bisect.session_status(session)
    assert any(row['failed_assertions'] == ['observer.prefixes'] for row in status['trials'])
    output = tmp_path / 'report'
    bisect.report(session, output)
    relocated = tmp_path / 'relocated'
    shutil.copytree(output, relocated)
    assert bisect.verify_report(relocated / 'bisection.json')['conclusion'] == conclusion


@pytest.mark.parametrize('capture', ['missing', 'legacy', 'unavailable'])
def test_unavailable_prefix_evidence_is_ambiguous_with_passing_counts(tmp_path, capture):
    plan = fixture_plan(tmp_path, predicate='prefix_assertions')
    target = fake_target(plan['candidates'][0]['build_plan'])
    original = package(tmp_path / 'original', plan['recipe'], target['image'], target=target, capture=capture)
    observed = bisect.classification(plan, 0, original)
    assert observed['classification'] == 'ambiguous'
    rows = {row['name']: row for row in observed['assertions']['assertions']}
    assert rows['observer.count']['status'] == 'passed'
    assert rows['observer.prefixes']['status'] == 'unmeasured'


def test_decisive_count_failure_does_not_claim_a_measured_prefix_mismatch(tmp_path):
    plan = fixture_plan(tmp_path, predicate='prefix_assertions')
    target = fake_target(plan['candidates'][0]['build_plan'])
    original = package(tmp_path / 'original', plan['recipe'], target['image'], target=target, capture='missing')
    events_path = original.parent / 'work/raw-events.json'
    events = recipes.read_document(events_path)
    events['events'][-1]['counters']['accepted_prefixes'] = 99
    events_path.write_text(json.dumps(events))
    result = recipes.read_document(original)
    for item in result['artifacts']:
        if item['path'] == 'work/raw-events.json':
            item['sha256'] = hashlib.sha256(events_path.read_bytes()).hexdigest()
    original.write_text(json.dumps(result))
    observed = bisect.classification(plan, 0, original)
    assert observed['classification'] == 'bad'
    rows = {row['name']: row for row in observed['assertions']['assertions']}
    assert rows['observer.count']['status'] == 'failed'
    assert rows['observer.prefixes']['status'] == 'unmeasured'
    assert 'decisive failed witness' in observed['reason']


def test_pending_original_recovers_without_repeating_capture_or_build(tmp_path):
    plan = fixture_plan(tmp_path, predicate='prefix_assertions')
    session = tmp_path / 'session'
    bisect.initialize(plan, session)
    built, ran, build, run = prefix_backends(tmp_path / 'fixtures', plan, interrupt_index=4)
    bisect.step(session, build=build, run=run)
    bisect.step(session, build=build, run=run)
    with pytest.raises(recipes.ContractError, match='explicit recover'):
        bisect.step(session, build=build, run=run)
    assert ran == [0, 8, 4]
    before = (list(built), list(ran))
    with pytest.raises(recipes.ContractError, match='Pending trial'):
        bisect.step(session, build=build, run=run)
    original = session / 'results/t0003/result.json'
    original_id = recipes.read_document(original)['attempt']['id']
    bisect.recover(session, result_path=original)
    assert (built, ran) == before and not (session / 'pending.json').exists()
    _, records = bisect.history(session)
    assert records[-1]['classification'] == 'bad'
    assert records[-1]['observed']['source_attempt_id'] == original_id


def test_prefix_capture_cap_refuses_before_git_or_preparation_mutation(tmp_path, monkeypatch):
    plan = fixture_plan(tmp_path, predicate='prefix_assertions')
    recipe = copy.deepcopy(plan['recipe'])
    import recipe_prefixes
    monkeypatch.setattr(recipe_prefixes, 'MAX_PREFIXES', 1)
    def forbidden(*args, **kwargs):
        pytest.fail('Git or source preparation started before prefix bounds refusal')
    monkeypatch.setattr(ranges, 'LocalGit', forbidden)
    with pytest.raises(recipes.ContractError, match='100000'):
        ranges.prepare_range(recipe, source_root=tmp_path / 'absent', good='1' * 40, bad='2' * 40,
            toolchain_image=TOOLCHAIN, runtime_image=RUNTIME, output_dir=tmp_path / 'prepared',
            predicate='prefix_assertions')
    assert not (tmp_path / 'prepared').exists()
    with pytest.raises(recipes.ContractError, match='100000'):
        bisect.make_plan(recipe, [], [], predicate='prefix_assertions', max_trials=8)


def test_public_prefix_plan_cap_refuses_before_git_and_output(tmp_path, monkeypatch):
    import recipe_prefixes
    import recipe_targets
    recipe = recipes.read_document(ranges.ENGINE_ROOT / 'examples/recipes/synthetic-ipv4.recipe.json')
    path = tmp_path / 'recipe.json'
    path.write_text(json.dumps(recipe))
    monkeypatch.setattr(recipe_prefixes, 'MAX_PREFIXES', 1)
    monkeypatch.setattr(recipe_targets, '_git', lambda *a, **k: pytest.fail('Git queried before capture cap'))
    output = tmp_path / 'plan.json'
    with pytest.raises(SystemExit) as stopped:
        bisect.main(['plan', '--recipe', str(path), '--predicate', 'prefix_assertions',
            '--build-plan', str(tmp_path / 'absent-1.json'), '--build-plan', str(tmp_path / 'absent-2.json'),
            '--max-trials', '8', '--output', str(output)])
    assert stopped.value.code == 2 and not output.exists()


@pytest.mark.parametrize('alteration', ['summary', 'prose'])
def test_rehashed_prefix_report_cannot_change_assertion_or_prose(tmp_path, alteration):
    plan = fixture_plan(tmp_path, count=3, predicate='prefix_assertions')
    session = tmp_path / 'session'
    bisect.initialize(plan, session)
    _, _, build, run = prefix_backends(tmp_path / 'fixtures', plan, first_bad=1)
    bisect.step(session, build=build, run=run)
    bisect.step(session, build=build, run=run)
    output = tmp_path / 'report'
    bisect.report(session, output)
    if alteration == 'summary':
        path = output / 'bisection.json'
        report = recipes.read_document(path)
        report['trials'][1]['observed']['assertions']['assertions'][-1]['status'] = 'passed'
        path.write_text(json.dumps(report))
    else:
        with (output / 'REPORT.md').open('a') as stream:
            stream.write('\nSIMULATED unsupported prefix success\n')
    checksums = recipes.read_document(output / 'checksums.json')
    for row in checksums['files']:
        row['sha256'] = hashlib.sha256((output / row['path']).read_bytes()).hexdigest()
    (output / 'checksums.json').write_text(json.dumps(checksums))
    with pytest.raises(recipes.ContractError):
        bisect.verify_report(output / 'bisection.json')


def test_prefix_source_preparation_and_handoff_keep_capture_selection(source, tmp_path):
    recipe = recipes.read_document(ranges.ENGINE_ROOT / 'examples/recipes/synthetic-ipv4.recipe.json')
    original, revisions = source
    before = source_state(original)
    prepared = tmp_path / 'prepared'
    ranges.prepare_range(recipe, source_root=original, good=revisions[0], bad=revisions[-1],
        toolchain_image=TOOLCHAIN, runtime_image=RUNTIME, output_dir=prepared,
        predicate='prefix_assertions', max_trials=8)
    assert source_state(original) == before
    assert ranges.verify_preparation(prepared / 'source-range.json')['valid']
    plan = recipes.read_document(prepared / 'bisection-plan.json')
    assert plan['predicate'] == 'prefix_assertions'
    manifest = recipes.read_document(prepared / 'source-range.json')
    build_paths = [prepared / row['build_plan'] for row in manifest['candidates']]
    output = tmp_path / 'handoff'
    handoff.prepare_handoff(prepared / 'source-range.json', baseline_build_plan=build_paths[-1],
        candidate_build_plan=build_paths[0], build_root=tmp_path / 'builds', work_root=tmp_path / 'work',
        results_root=tmp_path / 'results', session=tmp_path / 'search', output_dir=output,
        compare_repetitions=2)
    assert handoff.verify_handoff(output / 'handoff.json')['valid']
    commands = {row['id']: row for row in recipes.read_document(output / 'commands.json')['steps']}
    for name in ('reproduce', 'investigate', 'plan_comparison'):
        assert '--observer-prefixes' in commands[name]['argv']
    exported = commands['export_assertions']['argv']
    assert 'observer_prefix_identity' in exported
    comparison = commands['plan_comparison']['argv']
    assert comparison[comparison.index('--diagnostics') + 1] == 'basic'
    assert '--side' in commands['check_candidate_correctness']['argv']
    assert source_state(original) == before
