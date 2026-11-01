"""A prepared maintainer handoff freezes wiring, never execution readiness."""
import copy
import hashlib
import json
from pathlib import Path
import shutil

import pytest

import recipe_handoff as handoff
import recipe_source_range as source_range
import recipes
from test_recipe_bisection import fixture_plan
from test_source_range import source, TOOLCHAIN, RUNTIME, state as source_state


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(handoff._json(value))


@pytest.fixture
def selected(tmp_path, monkeypatch):
    """Strict synthetic commit proofs/plans; local source verification is injected."""
    prepared = tmp_path / 'prepared'
    prepared.mkdir()
    plan = fixture_plan(prepared, count=3, predicate='target_crash', budget=8)
    save(prepared / 'bisection-plan.json', plan)
    paths = []
    snapshots = {}
    for number, row in enumerate(plan['candidates']):
        build = row['build_plan']
        Path(build['source_root']).mkdir()
        snapshots[build['source_root']] = copy.deepcopy(build['source'])
        path = prepared / f'build-plans/{number}.json'
        save(path, build)
        paths.append(path)
    manifest = prepared / 'source-range.json'
    original = tmp_path / 'original-source'
    original.mkdir()
    (original / 'maintainer-note').write_text('retain original checkout unchanged')
    save(manifest, {'recipe': plan['recipe'], 'bisection_plan': 'bisection-plan.json', 'source_root': str(original)})
    fix = copy.deepcopy(plan['candidates'][-1]['build_plan'])
    fix['source_root'] = str(tmp_path / 'fix-source')
    Path(fix['source_root']).mkdir()
    fix['source'].update(dirty=True, include_dirty=True, patch_sha256='d' * 64, snapshot_sha256='e' * 64)
    snapshots[fix['source_root']] = copy.deepcopy(fix['source'])
    fix_path = tmp_path / 'fix-plan.json'
    save(fix_path, fix)
    state = {'range_checks': [], 'snapshots': snapshots, 'source_checks': [], 'range_valid': True}
    def verify(path):
        state['range_checks'].append(Path(path))
        assert Path(path) == manifest
        if not state['range_valid']:
            raise recipes.ContractError('SIMULATED prepared range changed')
        return {'valid': True}
    def snapshot(root, revision, include_dirty):
        state['source_checks'].append((root, revision, include_dirty))
        value = snapshots[str(root)]
        assert revision == value['requested_revision'] and include_dirty == value['include_dirty']
        return copy.deepcopy(value), b'SIMULATED snapshot', b'SIMULATED patch'
    monkeypatch.setattr(source_range, 'verify_preparation', verify)
    monkeypatch.setattr(handoff.targets, '_snapshot', snapshot)
    def forbidden(*args, **kwargs):
        raise AssertionError('No host, image, build or worker operation is permitted')
    monkeypatch.setattr(handoff.targets.runtime, 'run_command', forbidden)
    monkeypatch.setattr(handoff.targets.runtime, 'check_recipe', forbidden)
    monkeypatch.setattr(handoff.targets, 'build_target', forbidden)
    options = dict(baseline_build_plan=paths[-1], candidate_build_plan=fix_path,
        build_root=tmp_path / 'builds', work_root=tmp_path / 'work', results_root=tmp_path / 'results',
        session=tmp_path / 'search', output_dir=tmp_path / 'handoff')
    return manifest, plan, paths, fix, state, options


def documents(options):
    root = Path(options['output_dir'])
    return root, recipes.read_document(root / 'handoff.json'), recipes.read_document(root / 'commands.json')


def reseal(root):
    checksums = recipes.read_document(root / 'checksums.json')
    for entry in checksums['files']:
        entry['sha256'] = hashlib.sha256((root / entry['path']).read_bytes()).hexdigest()
    save(root / 'checksums.json', checksums)


def test_handoff_freezes_actual_inputs_future_targets_and_valid_public_wiring(selected):
    manifest_path, plan, paths, fix, state, options = selected
    before = {p: p.read_bytes() for p in (manifest_path, *paths, options['candidate_build_plan'])}
    verified = handoff.prepare_handoff(manifest_path, **options)
    assert verified['valid'] and verified['execution'] == 'not_requested'
    assert all(verified[key] == 'unassessed' for key in
               ('local_image_availability', 'host_suitability', 'execution_authorization'))
    root, manifest, graph = documents(options)
    assert (root / 'inputs/bisection-plan.json').read_bytes() == (manifest_path.parent / 'bisection-plan.json').read_bytes()
    assert manifest['budgets']['maximum_worker_invocations'] == 11
    assert manifest['budgets']['maximum_source_build_invocations'] == 5
    assert manifest['comparison'] is None
    assert any(row['field'] == 'source' for row in manifest['target_build_differences'])
    seen = set()
    for step in graph['steps']:
        assert set(step['depends_on']) <= seen
        seen.add(step['id'])
        assert step['execution'] == 'not_requested'
        assert step['argv'][0] == str(handoff.ROOT / 'venv/bin/python')
        assert Path(step['argv'][1]).name in ('recipes.py', 'recipe_bisection.py')
    steps = {step['id']: step for step in graph['steps']}
    assert steps['build_baseline']['argv'][2] == 'target-build'
    assert steps['reproduce']['argv'][2] == 'run' and 'exit 4' in steps['reproduce']['condition']
    assert steps['export_assertions']['argv'][2] == 'assertions-export'
    assert steps['check_reproduction_assertions']['argv'][2] == 'assertions-check'
    assert steps['init_bisection']['argv'][3] == str(root / 'inputs/bisection-plan.json')
    assert '--execute' not in steps['preview_bisection']['argv']
    assert '--execute' in steps['step_bisection']['argv']
    assert not any(step['argv'][2] in ('pull', 'prepare') for step in graph['steps'])
    assert all(value['image'] is None for value in graph['future_targets'].values())
    assert graph['future_targets']['candidate']['path'] == str(options['build_root'] / 'candidate/target.json')
    for name in ('build_root', 'work_root', 'results_root', 'session'):
        assert not options[name].exists()
    assert {p: p.read_bytes() for p in before} == before
    assert 'candidate is not assumed to fix' in (root / 'RUNBOOK.md').read_text()
    assert handoff.verify_handoff(root / 'handoff.json')['valid']


@pytest.mark.parametrize('order,seed', [('alternating', None), ('shuffle', 23)])
def test_optional_comparison_uses_supported_controls_and_finite_budget(selected, order, seed):
    manifest_path, plan, paths, fix, state, options = selected
    handoff.prepare_handoff(manifest_path, **options, compare_repetitions=4, compare_order=order, compare_seed=seed)
    root, manifest, graph = documents(options)
    assert manifest['budgets']['comparison_workers'] == 8
    assert manifest['budgets']['maximum_worker_invocations'] == 19
    step = next(s for s in graph['steps'] if s['id'] == 'plan_comparison')
    assert step['argv'][step['argv'].index('--order') + 1] == order
    assert ('--seed' in step['argv']) is (seed is not None)
    assert step['argv'][step['argv'].index('-o') + 1] == str(options['build_root'] / 'comparison-plan.json')
    assert manifest['performance_policy'] == 'disabled'


def test_candidate_instrumentation_and_build_environment_changes_are_exposed(selected):
    manifest_path, plan, paths, fix, state, options = selected
    fix.update(instrumentation='optimized', cflags='-O2 -g', toolchain_image='sha256:' + 'f' * 64)
    save(options['candidate_build_plan'], fix)
    handoff.prepare_handoff(manifest_path, **options)
    root, manifest, graph = documents(options)
    differences = {row['field']: row for row in manifest['target_build_differences']}
    assert differences['instrumentation']['candidate'] == 'optimized'
    assert differences['cflags']['candidate'] == '-O2 -g'
    assert differences['toolchain_image']['candidate'] == 'sha256:' + 'f' * 64
    images = {row['reference']: row['roles'] for row in graph['required_declared_images']}
    assert 'candidate.toolchain_image' in images['sha256:' + 'f' * 64]
    assert plan['recipe']['roles']['target']['image'] not in images


def test_assertion_range_keeps_its_original_recipe_and_predicate(selected):
    manifest_path, plan, paths, fix, state, options = selected
    plan['predicate'] = 'assertions'
    plan['recipe']['reproduction']['expected_outcome'] = 'experiment_completed'
    for row in plan['candidates']:
        row['build_plan']['recipe'] = plan['recipe']
        row['build_plan']['recipe_sha256'] = recipes.recipe_sha256(plan['recipe'])
    fix['recipe'] = copy.deepcopy(plan['recipe'])
    fix['recipe_sha256'] = recipes.recipe_sha256(plan['recipe'])
    for path, row in zip(paths, plan['candidates']):save(path, row['build_plan'])
    save(options['candidate_build_plan'], fix)
    preparation = recipes.read_document(manifest_path)
    preparation['recipe'] = plan['recipe']
    save(manifest_path, preparation)
    save(manifest_path.parent / 'bisection-plan.json', plan)
    handoff.prepare_handoff(manifest_path, **options)
    copied = recipes.read_document(options['output_dir'] / 'inputs/bisection-plan.json')
    assert copied['predicate'] == 'assertions'
    assert copied['recipe']['reproduction']['expected_outcome'] == 'experiment_completed'


@pytest.mark.parametrize('change', ['range', 'candidate_plan_bytes', 'source_snapshot', 'frozen_input',
    'argv', 'budget', 'readiness', 'unknown_field', 'extra_file', 'extra_directory', 'symlink', 'relocation'])
def test_verification_refuses_changed_inputs_tampered_commands_and_unsafe_layout(selected, change):
    manifest_path, plan, paths, fix, state, options = selected
    handoff.prepare_handoff(manifest_path, **options)
    root, manifest, graph = documents(options)
    document = root / 'handoff.json'
    if change == 'range':state['range_valid'] = False
    elif change == 'candidate_plan_bytes':
        options['candidate_build_plan'].write_bytes(options['candidate_build_plan'].read_bytes() + b' ')
    elif change == 'source_snapshot':state['snapshots'][fix['source_root']]['snapshot_sha256'] = 'f' * 64
    elif change == 'frozen_input':
        value = recipes.read_document(root / 'inputs/candidate-build-plan.json')
        value['cflags'] = '-O1 -g';save(root / 'inputs/candidate-build-plan.json', value)
    elif change == 'argv':
        graph['steps'][0]['argv'].append('--pull')
        save(root / 'commands.json', graph)
        manifest['commands_sha256'] = hashlib.sha256((root / 'commands.json').read_bytes()).hexdigest()
    elif change == 'budget':manifest['budgets']['maximum_worker_invocations'] += 1
    elif change == 'readiness':manifest['execution_authorization'] = 'authorized'
    elif change == 'unknown_field':manifest['execute'] = True
    elif change == 'extra_file':(root / 'extra').write_text('unlisted')
    elif change == 'extra_directory':(root / 'empty-extra').mkdir()
    elif change == 'symlink':
        path = root / 'RUNBOOK.md';path.rename(root / 'original-runbook');path.symlink_to(root / 'original-runbook')
    elif change == 'relocation':
        copied = root.with_name('copied-handoff');shutil.copytree(root, copied);document = copied / 'handoff.json'
    if change != 'symlink':
        save(root / 'handoff.json', manifest);reseal(root)
    with pytest.raises((OSError, ValueError)):
        handoff.verify_handoff(document)


@pytest.mark.parametrize('kind', ['nested', 'existing', 'source', 'engine', 'relative', 'symlink', 'ancestor_file', 'root_alias'])
def test_destination_refusals_do_not_create_or_replace_selected_paths(selected, kind, tmp_path):
    manifest_path, plan, paths, fix, state, options = selected
    if kind == 'nested':options['results_root'] = options['work_root'] / 'results'
    elif kind == 'existing':options['work_root'].mkdir()
    elif kind == 'source':options['build_root'] = Path(fix['source_root']) / 'build'
    elif kind == 'engine':options['build_root'] = handoff.ROOT / 'new-build'
    elif kind == 'relative':options['session'] = Path('relative-session')
    elif kind == 'ancestor_file':
        file = tmp_path / 'file';file.write_text('retain me');options['work_root'] = file / 'work'
    elif kind == 'root_alias':
        options['work_root'] = Path('/' + str(options['results_root'])) / 'nested-work'
    elif kind == 'symlink':
        alias = tmp_path / 'alias';alias.symlink_to(fix['source_root'], target_is_directory=True)
        options['build_root'] = alias / 'build'
    before = set(tmp_path.iterdir())
    with pytest.raises((OSError, ValueError)):
        handoff.prepare_handoff(manifest_path, **options)
    assert set(tmp_path.iterdir()) == before and not options['output_dir'].exists()


@pytest.mark.parametrize('arguments', [dict(compare_repetitions=True), dict(compare_repetitions=101),
    dict(compare_repetitions=2, compare_seed=7), dict(compare_repetitions=2, compare_order='shuffle'),
    dict(compare_seed=7)])
def test_invalid_comparison_choices_refuse_without_creating_handoff(selected, arguments):
    manifest_path, plan, paths, fix, state, options = selected
    with pytest.raises(recipes.ContractError):handoff.prepare_handoff(manifest_path, **options, **arguments)
    assert not options['output_dir'].exists()


def test_existing_future_output_is_not_a_retry_or_authorization_claim(selected):
    manifest_path, plan, paths, fix, state, options = selected
    handoff.prepare_handoff(manifest_path, **options)
    options['build_root'].mkdir()
    result = handoff.verify_handoff(options['output_dir'] / 'handoff.json')
    assert result['valid'] and result['execution_authorization'] == 'unassessed'
    with pytest.raises(recipes.ContractError, match='fresh'):
        handoff.prepare_handoff(manifest_path, **{**options, 'output_dir': options['output_dir'].with_name('another')})


@pytest.mark.parametrize('field', ['output_dir', 'build_root', 'work_root', 'results_root', 'session'])
def test_every_destination_protects_original_checkout_even_with_both_plans_prepared(selected, field):
    manifest_path, plan, paths, fix, state, options = selected
    original = Path(recipes.read_document(manifest_path)['source_root'])
    options['candidate_build_plan'] = paths[0]
    options[field] = original / 'new-artifact'
    before = {p.relative_to(original).as_posix(): p.read_bytes() for p in original.rglob('*') if p.is_file()}
    with pytest.raises(recipes.ContractError, match='overlaps selected source'):
        handoff.prepare_handoff(manifest_path, **options)
    assert {p.relative_to(original).as_posix(): p.read_bytes() for p in original.rglob('*') if p.is_file()} == before
    assert not (original / 'new-artifact').exists()


@pytest.mark.parametrize('field', ['build_root', 'work_root', 'results_root', 'session'])
def test_verifier_refuses_resealed_destination_inside_original_checkout(selected, field):
    manifest_path, plan, paths, fix, state, options = selected
    original = Path(recipes.read_document(manifest_path)['source_root'])
    options['candidate_build_plan'] = paths[0]
    handoff.prepare_handoff(manifest_path, **options)
    root, manifest, graph = documents(options)
    manifest['destinations'][field] = str(original / 'new-artifact')
    save(root / 'handoff.json', manifest);reseal(root)
    with pytest.raises(recipes.ContractError, match='overlaps selected source'):
        handoff.verify_handoff(root / 'handoff.json')
    assert not (original / 'new-artifact').exists()


def test_original_checkout_is_only_lexically_protected_after_preparation(selected):
    manifest_path, plan, paths, fix, state, options = selected
    original = Path(recipes.read_document(manifest_path)['source_root'])
    options['candidate_build_plan'] = paths[0]
    original.rename(original.with_name('original-moved'))
    handoff.prepare_handoff(manifest_path, **options)
    assert handoff.verify_handoff(options['output_dir'] / 'handoff.json')['valid']


def test_public_cli_has_no_execution_option_and_emits_only_verified_bundle(selected, capsys):
    manifest_path, plan, paths, fix, state, options = selected
    argv = ['prepare', '--source-range', str(manifest_path)]
    for field, value in options.items():argv += ['--' + ('output' if field == 'output_dir' else field.replace('_', '-')), str(value)]
    with pytest.raises(SystemExit) as refused:handoff.main(argv + ['--execute'])
    assert refused.value.code == 2 and not options['output_dir'].exists()
    capsys.readouterr()
    assert handoff.main(argv) == 0
    assert json.loads(capsys.readouterr().out)['execution'] == 'not_requested'
    assert handoff.main(['verify', str(options['output_dir'] / 'handoff.json')]) == 0
    assert json.loads(capsys.readouterr().out)['valid']


@pytest.mark.parametrize('predicate', ['assertions', 'target_crash'])
def test_real_prepared_range_and_dirty_fix_produce_a_verified_action_handoff(
        tmp_path, source, monkeypatch, predicate):
    source_root, revisions = source
    recipe = recipes.read_document(handoff.ROOT / 'examples/recipes/synthetic-ipv4.recipe.json')
    recipe['reproduction']['question'] = 'INERT local maintainer handoff fixture; no source code runs'
    recipe['reproduction']['expected_outcome'] = 'target_crash' if predicate == 'target_crash' else 'experiment_completed'
    (source_root / 'main.c').write_text('/* retained dirty local fix; never compiled */\n')
    before = source_state(source_root)
    def forbidden(*args, **kwargs):
        raise AssertionError('No image inspection, build or worker is permitted')
    monkeypatch.setattr(handoff.targets.runtime, 'inspect_image', forbidden)
    monkeypatch.setattr(handoff.targets, 'build_target', forbidden)
    import recipe_run
    monkeypatch.setattr(recipe_run, 'run_recipe', forbidden)
    prepared = tmp_path / 'real-prepared'
    manifest = source_range.prepare_range(recipe, source_root=source_root, good=revisions[0], bad=revisions[-1],
        toolchain_image=TOOLCHAIN, runtime_image=RUNTIME, predicate=predicate, max_trials=8, output_dir=prepared)
    fix = handoff.targets.plan_source_build(recipe, source_root, revisions[-1], toolchain_image=TOOLCHAIN,
        runtime_image=RUNTIME, instrumentation='optimized', cflags='-O2 -g', include_dirty=True)
    fix_path = tmp_path / 'real-fix-plan.json'
    save(fix_path, fix)
    output = tmp_path / 'real-handoff'
    result = handoff.prepare_handoff(prepared / 'source-range.json',
        baseline_build_plan=prepared / manifest['candidates'][-1]['build_plan'], candidate_build_plan=fix_path,
        build_root=tmp_path / 'real-builds', work_root=tmp_path / 'real-work',
        results_root=tmp_path / 'real-results', session=tmp_path / 'real-search', output_dir=output,
        compare_repetitions=2)
    assert result['valid'] and result['execution_authorization'] == 'unassessed'
    assert source_state(source_root) == before
    assert (output / 'inputs/bisection-plan.json').read_bytes() == (prepared / 'bisection-plan.json').read_bytes()
    assert handoff.verify_handoff(output / 'handoff.json')['valid']
    (source_root / 'main.c').write_text('/* subsequent edit requires new explicit source planning */\n')
    with pytest.raises(recipes.ContractError, match='source snapshot'):
        handoff.verify_handoff(output / 'handoff.json')
