"""SIMULATED comparison capture retains exact-set and partial-evidence meanings."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

import pytest

import comparison_session as staged
import recipe_prefixes
import recipes
from recipe_assertions import default_assertions
from recipe_comparison import make_comparison_plan, run_comparison, validate_comparison_plan
from recipe_comparison_report import build_comparison_report, verify_comparison_report
from recipe_targets import supplied_target
from test_investigation_prefixes import BASE, CANDIDATE, package, recipe
from test_recipe_comparison_report import replace_artifact


def plan_for(recipe, **options):
    return make_comparison_plan(recipe,
        baseline_target=supplied_target(recipe, BASE, instrumentation='optimized'),
        candidate_target=supplied_target(recipe, CANDIDATE, instrumentation='optimized'),
        repetitions=options.pop('repetitions', 2), timeout=120, diagnostics='basic', **options)


def entries_for(root, plan, *, wrong=None, capture='correct', large=False):
    entries = []
    for entry in plan['sequence']:
        selected = plan['targets'][entry['role']]
        path = package(root / entry['id'], plan['recipe'], selected['image'],
                       capture='wrong' if entry['id'] == wrong else capture,
                       target=selected, large=large)
        entries.append({**entry, 'result': str(path), 'status': 'completed', 'reason': 'SIMULATED package'})
    return entries


def row(report, identifier, name):
    attempt = next(item for item in report['attempts'] if item['id'] == identifier)
    return next(item for item in attempt['assertions']['assertions'] if item['name'] == name)


def rehash(root):
    path = root / 'checksums.json'
    manifest = json.loads(path.read_text())
    for entry in manifest['files']:
        entry['sha256'] = hashlib.sha256((root / entry['path']).read_bytes()).hexdigest()
    path.write_text(json.dumps(manifest))


def test_selected_plan_freezes_six_assertions_and_preserves_explicit_specs(recipe):
    legacy = plan_for(recipe)
    assert 'observer_prefixes' not in legacy and len(legacy['assertions']['assertions']) == 5
    assert plan_for(recipe, observer_prefixes=False) == legacy
    selected = plan_for(recipe, observer_prefixes=True)
    assert selected['observer_prefixes'] is True
    assert len(selected['assertions']['assertions']) == 6
    assert selected['assertions']['assertions'][-1]['capability'] == 'observer_prefix_identity'
    explicit = default_assertions(recipe)
    explicit['assertions'] = explicit['assertions'][:4]
    custom = plan_for(recipe, observer_prefixes=True, assertions=explicit)
    assert custom['assertions'] == explicit
    assert selected['sequence'] == legacy['sequence']


@pytest.mark.parametrize('selected', [False, True])
def test_public_plan_cli_is_offline_and_selection_is_explicit(tmp_path, recipe, monkeypatch, selected):
    inputs = {'recipe': recipe, 'baseline': supplied_target(recipe, BASE),
              'candidate': supplied_target(recipe, CANDIDATE)}
    for name, value in inputs.items():
        (tmp_path / (name + '.json')).write_text(json.dumps(value))
    def forbidden(*args, **kwargs):
        pytest.fail('Offline comparison planning started a subprocess or probe')
    monkeypatch.setattr(subprocess, 'run', forbidden)
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    output = tmp_path / 'plan.json'
    args = ['comparison-plan', str(tmp_path / 'recipe.json'),
            '--baseline-target', str(tmp_path / 'baseline.json'),
            '--candidate-target', str(tmp_path / 'candidate.json'),
            '--repetitions', '2', '--output', str(output)]
    if selected:
        args.append('--observer-prefixes')
    assert recipes.main(args) == 0
    plan = recipes.read_document(output)
    assert (plan.get('observer_prefixes') is True) is selected
    assert len(plan['assertions']['assertions']) == (6 if selected else 5)
    if not selected:
        assert 'observer_prefixes' not in plan


@pytest.mark.parametrize('value', [None, 0, 1, 'true', [], {}])
def test_capture_selection_is_a_strict_boolean_in_the_planner(recipe, value):
    with pytest.raises(recipes.ContractError, match='boolean'):
        plan_for(recipe, observer_prefixes=value)


@pytest.mark.parametrize('value', [False, None, 0, 1, 'true'])
def test_serialized_optional_selection_requires_true(recipe, value):
    plan = plan_for(recipe)
    plan['observer_prefixes'] = value
    with pytest.raises(recipes.ContractError, match='boolean true'):
        validate_comparison_plan(plan)


def test_capture_limit_refuses_before_probes_or_destination_changes(tmp_path, recipe, monkeypatch):
    plan = plan_for(recipe, observer_prefixes=True)
    monkeypatch.setattr(recipe_prefixes, 'MAX_PREFIXES', 1)
    def forbidden(*args, **kwargs):
        pytest.fail('Unsupported capture reached runtime or prerequisite checks')
    with pytest.raises(recipes.ContractError, match='100000'):
        plan_for(recipe, observer_prefixes=True)
    with pytest.raises(recipes.ContractError, match='100000'):
        run_comparison(plan, workdir=tmp_path / 'work', results_dir=tmp_path / 'results',
                       run=forbidden, check=forbidden)
    with pytest.raises(recipes.ContractError, match='100000'):
        staged.start_session(plan, workdir=tmp_path / 'work', results_dir=tmp_path / 'results', check=forbidden)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('selected', [False, True])
def test_every_serial_role_receives_only_selected_capture_kwargs(tmp_path, recipe, selected):
    plan = plan_for(recipe, observer_prefixes=selected)
    called = []
    def execute(document, **kwargs):
        called.append(kwargs)
        target = kwargs['target']
        path = package(tmp_path / ('fake-' + str(len(called))), document, target['image'], target=target)
        shutil.copytree(path.parent, kwargs['results_dir'])
        return recipes.read_document(Path(kwargs['results_dir']) / 'result.json')
    result = run_comparison(plan, workdir=tmp_path / 'work', results_dir=tmp_path / 'results',
                            run=execute, check=lambda *a, **k: {'status': 'checks_passed'})
    assert result['exit_code'] == 0 and len(called) == 4
    for options, entry in zip(called, plan['sequence']):
        assert options['target'] == plan['targets'][entry['role']]
        if selected:
            assert options['observer_prefixes'] is True
        else:
            assert 'observer_prefixes' not in options
    stored = recipes.read_document(tmp_path / 'results/comparison-plan.json')
    assert stored == plan


def test_equal_count_changed_set_is_separate_and_reconstructed(tmp_path, recipe):
    plan = plan_for(recipe, observer_prefixes=True)
    entries = entries_for(tmp_path / 'fixtures', plan, wrong='r001-candidate')
    output = tmp_path / 'report'
    report = build_comparison_report(plan, entries, output)
    assert row(report, 'r001-candidate', 'observer.count')['status'] == 'passed'
    identity = row(report, 'r001-candidate', 'observer.prefixes')
    assert identity['status'] == 'failed'
    assert identity['observed']['missing_count'] == identity['observed']['unexpected_count'] == 1
    assert report['correctness']['candidate'] == {'passed': 1, 'failed': 1, 'inconclusive': 0, 'unavailable': 0}
    assert 'observer_prefix_capture' in {item['code'] for item in report['confounders']}
    assert report['performance']['policy'] == 'disabled'
    prose = (output / 'REPORT.md').read_text()
    assert '| r001-candidate | passed | 100 | failed | 100 | 1 | 1 |' in prose
    assert verify_comparison_report(output / 'comparison.json')['valid'] is True
    moved = tmp_path / 'moved'
    shutil.copytree(output, moved)
    assert verify_comparison_report(moved / 'comparison.json')['valid'] is True
    rebuilt = build_comparison_report(report['plan'], entries, tmp_path / 'rebuilt')
    assert rebuilt == report
    assert verify_comparison_report(tmp_path / 'rebuilt/comparison.json')['valid'] is True


@pytest.mark.parametrize('capture', ['legacy', 'missing', 'unavailable'])
def test_missing_or_unavailable_capture_remains_unmeasured(tmp_path, recipe, capture):
    plan = plan_for(recipe, observer_prefixes=True)
    report = build_comparison_report(plan, entries_for(tmp_path / 'fixtures', plan, capture=capture), tmp_path / 'report')
    for entry in plan['sequence']:
        assert row(report, entry['id'], 'observer.count')['status'] == 'passed'
        answer = row(report, entry['id'], 'observer.prefixes')
        assert answer['status'] == 'unmeasured' and answer['observed'] is None
    assert report['correctness']['candidate']['inconclusive'] == 2


def test_explicit_four_assertions_do_not_hide_selected_capture_overhead(tmp_path, recipe):
    spec = default_assertions(recipe)
    spec['assertions'] = spec['assertions'][:4]
    plan = plan_for(recipe, observer_prefixes=True, assertions=spec)
    report = build_comparison_report(plan, entries_for(tmp_path / 'fixtures', plan), tmp_path / 'report')
    assert all(item['assertions']['outcome'] == 'passed' for item in report['attempts'])
    assert 'observer_prefix_capture' in {item['code'] for item in report['confounders']}
    assert all(delta['candidate_minus_baseline_median'] is None
               for group in report['descriptive_deltas'].values() for delta in group.values())
    assert 'not selected' in (tmp_path / 'report/REPORT.md').read_text()


@pytest.mark.parametrize('alteration', ['summary', 'prose', 'confounder'])
def test_rehashed_summary_prose_or_capture_confounder_is_refused(tmp_path, recipe, alteration):
    plan = plan_for(recipe, observer_prefixes=True)
    output = tmp_path / 'report'
    report = build_comparison_report(plan, entries_for(tmp_path / 'fixtures', plan), output)
    if alteration == 'summary':
        report['attempts'][0]['assertions']['assertions'][-1]['status'] = 'failed'
    elif alteration == 'confounder':
        report['confounders'] = [item for item in report['confounders'] if item['code'] != 'observer_prefix_capture']
    else:
        with (output / 'REPORT.md').open('a') as stream:
            stream.write('\nSIMULATED unsupported prefix claim\n')
    if alteration != 'prose':
        (output / 'comparison.json').write_text(json.dumps(report))
    rehash(output)
    with pytest.raises(recipes.ContractError):
        verify_comparison_report(output / 'comparison.json')


def test_stopped_sequence_preserves_capture_and_never_run_positions(tmp_path, recipe):
    plan = plan_for(recipe, observer_prefixes=True)
    called = []
    def execute(document, **kwargs):
        called.append(kwargs)
        return {'status': 'interrupted', 'exit_code': 143, 'reason': 'SIMULATED stopped original'}
    result = run_comparison(plan, workdir=tmp_path / 'work', results_dir=tmp_path / 'results',
                            run=execute, check=lambda *a, **k: {'status': 'checks_passed'})
    assert result['exit_code'] == 143 and len(called) == 1
    report = recipes.read_document(result['report'])
    assert report['plan']['observer_prefixes'] is True
    assert report['attempts'][0]['status'] == 'interrupted'
    assert all(item['status'] == 'not_run' for item in report['attempts'][1:])
    assert all(item['assertions'] is None for item in report['attempts'])


def test_stored_report_relocation_and_export_preserve_exact_prefix_view(tmp_path, recipe, monkeypatch):
    from artifact_store import export_tree
    plan = plan_for(recipe, observer_prefixes=True)
    entries = entries_for(tmp_path / 'fixtures', plan, wrong='r001-candidate', large=True)
    monkeypatch.setenv('BGPERF_ARTIFACT_STORE', str(tmp_path / 'store'))
    output = tmp_path / 'report'
    report = build_comparison_report(plan, entries, output)
    assert list((tmp_path / 'store/objects').glob('*/*.zst'))
    portable = tmp_path / 'portable'
    export_tree(output, portable)
    (tmp_path / 'store').rename(tmp_path / 'retained-store')
    assert verify_comparison_report(portable / 'comparison.json')['valid'] is True
    retained = recipes.read_document(portable / 'comparison.json')
    assert retained == report
    assert row(retained, 'r001-candidate', 'observer.prefixes')['status'] == 'failed'


@pytest.mark.parametrize('selected', [False, True])
def test_staged_public_controller_command_carries_only_frozen_capture(tmp_path, recipe, monkeypatch, selected):
    plan = plan_for(recipe, observer_prefixes=selected)
    results = tmp_path / 'session'
    assert staged.start_session(plan, workdir=tmp_path / 'work', results_dir=results,
                                check=lambda *a, **k: {'status': 'checks_passed'})['status'] == 'ready'
    calls = []
    class Process:
        def wait(self, timeout=None):
            return 0
        def poll(self):
            return 0
    def process(argv, **kwargs):
        calls.append(argv)
        return Process()
    monkeypatch.setattr(staged.subprocess, 'Popen', process)
    for entry in plan['sequence']:
        assert staged._execute(plan, entry, workdir=tmp_path / entry['id'],
            results_dir=tmp_path / ('result-' + entry['id']), session=results, pressure=None)['exit_code'] == 0
    assert len(calls) == 4
    assert all(('--observer-prefixes' in argv) is selected for argv in calls)
    assert all('--diagnostics' in argv for argv in calls)


@pytest.mark.parametrize('capture, expected_exit', [('wrong', 4), ('unavailable', 5), ('legacy', 5)])
def test_staged_failure_preserves_completed_original_and_stops_successors(tmp_path, recipe, capture, expected_exit):
    plan = plan_for(recipe, observer_prefixes=True)
    results = tmp_path / 'session'
    staged.start_session(plan, workdir=tmp_path / 'work', results_dir=results,
                         check=lambda *a, **k: {'status': 'checks_passed'})
    calls = []
    def execute(document, entry, *, results_dir, **kwargs):
        calls.append(entry['id'])
        target = document['targets'][entry['role']]
        path = package(tmp_path / 'fake' / entry['id'], recipe, target['image'], target=target, capture=capture)
        replace_artifact(path, 'work/runtime.json', {'status': 'completed', 'cleanup_errors': []})
        shutil.copytree(path.parent, results_dir)
        return {'exit_code': 0}
    result = staged.step_session(results, execute=execute, check=lambda *a, **k: {'status': 'checks_passed'})
    assert result['status'] == 'stopped' and result['exit_code'] == expected_exit
    assert calls == ['r001-baseline']
    ledger = recipes.read_document(results / 'attempts.json')
    assert ledger[0]['status'] == 'completed'
    assert all(item['status'] == 'not_run' for item in ledger[1:])
    with pytest.raises(recipes.ContractError, match='stopped'):
        staged.step_session(results, execute=lambda *a, **k: pytest.fail('stopped session executed'),
                            check=lambda *a, **k: {'status': 'checks_passed'})


def test_observer_window_requires_its_explicit_four_assertions_before_outputs(tmp_path, recipe):
    selected = plan_for(recipe, observer_prefixes=True)
    with pytest.raises(recipes.ContractError, match='exactly the four'):
        staged.start_session(selected, workdir=tmp_path / 'work', results_dir=tmp_path / 'results',
                             observer_window=True, check=lambda *a, **k: pytest.fail('incompatible plan reached probes'))
    assert list(tmp_path.iterdir()) == []


def test_explicit_four_assertions_can_capture_with_the_separate_observer_window(tmp_path, recipe):
    spec = default_assertions(recipe)
    spec['assertions'] = spec['assertions'][:4]
    plan = plan_for(recipe, observer_prefixes=True, assertions=spec)
    assert staged.start_session(plan, workdir=tmp_path / 'work', results_dir=tmp_path / 'results',
        observer_window=True, check=lambda *a, **k: {'status': 'checks_passed'})['status'] == 'ready'
    stored = recipes.read_document(tmp_path / 'results/comparison-plan.json')
    assert stored['observer_prefixes'] is True and stored['assertions'] == spec
