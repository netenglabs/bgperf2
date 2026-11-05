"""SIMULATED functional pairs keep prefix identity separate from route count."""
import hashlib
import json
from pathlib import Path
import shutil

import pytest

import recipe_investigation as investigation
import recipe_prefixes
import recipes
from recipe_results import write_result_package
from recipe_targets import effective_roles, supplied_target
from test_recipe_assertions import evidence
from test_recipe_prefixes import captured

ROOT = Path(__file__).resolve().parents[1]
BASE = 'sha256:' + '4' * 64
CANDIDATE = 'sha256:' + '5' * 64


@pytest.fixture
def recipe():
    value = recipes.read_document(ROOT / 'examples/recipes/synthetic-ipv4.recipe.json')
    value['reproduction']['question'] = 'SIMULATED exact received-prefix comparison'
    recipes.validate_recipe(value)
    return value


def package(root, recipe, image, *, capture='correct', status='completed', large=False, target=None):
    """Build sealed evidence only; no source, daemon, socket or network executes."""
    root.mkdir(parents=True)
    work = root / 'source'
    work.mkdir()
    files = evidence(recipe)
    target = target if target is not None else supplied_target(recipe, image, label='SIMULATED target')
    files['target.json'] = target
    files['prerequisites.json'] = {'checks': [
        {'name': 'image.' + role, 'status': 'pass',
         'details': {'requested': selected['image'], 'image_id': selected['image'], 'repo_digests': []}}
        for role, selected in effective_roles(recipe, target).items()]}
    files['stages.json'] = {'events': [{'stage': 'terminal', 'status': status}]}
    if capture != 'legacy':
        files['observer-prefix-selection.json'] = {
            'recipe_sha256': recipes.recipe_sha256(recipe), 'enabled': True,
            'phase': 'post_measurement', 'max_prefixes': recipe_prefixes.MAX_PREFIXES}
        if capture != 'missing':
            receipt = captured(recipe)
            if capture == 'wrong':
                receipt['snapshot']['prefixes'][0] = '192.0.2.1/32'
            elif capture == 'unavailable':
                receipt.update(status='unavailable', snapshot=None, reason='SIMULATED unavailable capture')
            files['observer-prefixes.json'] = receipt
    for name, value in files.items():
        (work / name).write_text(json.dumps(value))
    if large:
        (work / 'large.log').write_bytes(b'SIMULATED retained evidence\n' * 50000)
    write_result_package(recipe, workdir=work, results_dir=root / 'result', attempt_id=root.name,
                         status=status, reason='SIMULATED sealed package',
                         reproduction={'outcome': 'reproduced', 'reason': 'SIMULATED completion evidence',
                                       'evidence': ['work/runtime.json']})
    return root / 'result/result.json'


def pair(tmp_path, recipe, **candidate_options):
    baseline = package(tmp_path / 'baseline', recipe, BASE)
    candidate = package(tmp_path / 'candidate', recipe, CANDIDATE, **candidate_options)
    return baseline, candidate


def selected_report(tmp_path, recipe, **candidate_options):
    baseline, candidate = pair(tmp_path, recipe, **candidate_options)
    output = tmp_path / 'report'
    report = investigation.write_investigation_report(baseline=baseline, candidate=candidate,
        output_dir=output, observer_prefixes=True)
    return report, output


def answers(report, side):
    return {row['capability']: row for row in report['correctness']['attempts'][side]['assertions']}


def rehash(root):
    path = root / 'checksums.json'
    value = recipes.read_document(path)
    for row in value['files']:
        row['sha256'] = hashlib.sha256((root / row['path']).read_bytes()).hexdigest()
    path.write_text(json.dumps(value))


def test_opted_in_pair_shows_all_six_assertions_and_count_separately_from_identity(tmp_path, recipe):
    report, output = selected_report(tmp_path, recipe)
    assert report['correctness']['observer_prefixes'] is True
    for side in ('baseline', 'candidate'):
        selected = answers(report, side)
        assert len(selected) == 6
        assert report['correctness']['attempts'][side]['outcome'] == 'passed'
        assert selected['observer_route_count']['observed'] == 100
        assert selected['observer_prefix_identity']['observed']['missing_count'] == 0
        assert selected['observer_prefix_identity']['observed']['unexpected_count'] == 0
    prose = (output / 'REPORT.md').read_text()
    assert 'observer.count' in prose and 'observer.prefixes' in prose
    assert investigation.verify_investigation_report(output / 'investigation.json')['valid']
    assert report['assessment']['performance']['qualification'] == 'not_assessed'


def test_equal_counts_with_different_identity_cannot_be_presented_as_identity_success(tmp_path, recipe):
    report, output = selected_report(tmp_path, recipe, capture='wrong')
    baseline, candidate = answers(report, 'baseline'), answers(report, 'candidate')
    assert baseline['observer_route_count']['status'] == candidate['observer_route_count']['status'] == 'passed'
    assert baseline['observer_prefix_identity']['status'] == 'passed'
    identity = candidate['observer_prefix_identity']
    assert identity['status'] == 'failed'
    assert identity['observed']['missing_count'] == identity['observed']['unexpected_count'] == 1
    assert identity['observed']['missing_sample'] == ['100.0.0.0/32']
    assert identity['observed']['unexpected_sample'] == ['192.0.2.1/32']
    assert report['correctness']['attempts']['candidate']['outcome'] == 'failed'
    assert 'failed' in (output / 'REPORT.md').read_text()
    assert investigation.verify_investigation_report(output / 'investigation.json')['valid']


def test_both_sides_render_in_one_contiguous_named_assertion_table(tmp_path, recipe):
    _, output = selected_report(tmp_path, recipe, capture='wrong')
    blocks, current = [], []
    for line in (output / 'REPORT.md').read_text().splitlines() + ['']:
        if line.startswith('|'):
            current.append(line)
        elif current:
            blocks.append(current)
            current = []
    selected = [block for block in blocks
                if block[0] == '| Attempt | Assertion | Status | Observed |']
    assert len(selected) == 1
    table = selected[0]
    assert len(table) == 14  # One header/separator followed by six rows per side.
    rows = [[cell.strip() for cell in line.strip('|').split('|')] for line in table[2:]]
    expected = {'sessions.ready', 'injection.complete', 'observer.count',
                'experiment.complete', 'roles.healthy', 'observer.prefixes'}
    for side in ('baseline', 'candidate'):
        assert {row[1] for row in rows if row[0] == side} == expected
    assert len({(row[0], row[1]) for row in rows}) == 12
    assert next(row[2] for row in rows if row[:2] == ['candidate', 'observer.count']) == 'passed'
    assert next(row[2] for row in rows if row[:2] == ['candidate', 'observer.prefixes']) == 'failed'


@pytest.mark.parametrize('capture', ['legacy', 'missing', 'unavailable'])
def test_absent_or_unavailable_capture_stays_unmeasured_with_a_reason(tmp_path, recipe, capture):
    report, output = selected_report(tmp_path, recipe, capture=capture)
    selected = answers(report, 'candidate')
    assert selected['observer_route_count']['status'] == 'passed'
    identity = selected['observer_prefix_identity']
    assert identity['status'] == 'unmeasured' and identity['observed'] is None and identity['reason']
    assert report['correctness']['attempts']['candidate']['outcome'] == 'inconclusive'
    assert investigation.verify_investigation_report(output / 'investigation.json')['valid']


def test_default_report_preserves_existing_shape_even_for_prefix_capable_packages(tmp_path, recipe):
    baseline, candidate = pair(tmp_path, recipe)
    output = tmp_path / 'legacy-report'
    report = investigation.write_investigation_report(baseline=baseline, candidate=candidate, output_dir=output)
    assert 'correctness' not in report
    assert 'observer.prefixes' not in (output / 'REPORT.md').read_text()
    rebuilt = investigation.rebuild_investigation_report(output / 'investigation.json', output_dir=tmp_path / 'rebuilt')
    assert rebuilt == report


@pytest.mark.parametrize('mode', ['missing_candidate', 'both_missing'])
def test_selected_capture_and_unavailable_attempt_reasons_survive_rebuild(tmp_path, recipe, mode):
    baseline = package(tmp_path / 'baseline', recipe, BASE) if mode == 'missing_candidate' else None
    missing = {'status': 'not_run', 'reason': 'SIMULATED finite controller stop before candidate'}
    output = tmp_path / 'report'
    report = investigation.write_investigation_report(baseline=baseline, candidate=None,
        baseline_missing=missing if baseline is None else None, candidate_missing=missing,
        output_dir=output, observer_prefixes=True)
    candidate = report['correctness']['attempts']['candidate']
    assert candidate == {'outcome': 'inconclusive', 'assertions': [], 'reason': missing['reason']}
    assert report['attempts']['candidate']['status'] == 'not_run'
    rebuilt = investigation.rebuild_investigation_report(output / 'investigation.json', output_dir=tmp_path / 'rebuilt')
    assert rebuilt == report
    assert investigation.verify_investigation_report(tmp_path / 'rebuilt/investigation.json')['valid']


@pytest.mark.parametrize('mutation', ['answer', 'selection_boolean', 'session_boolean', 'deadline_integer', 'prose'])
def test_rehashed_report_changes_do_not_override_bundled_prefix_evidence(tmp_path, recipe, mutation):
    report, output = selected_report(tmp_path, recipe)
    if mutation == 'prose':
        with (output / 'REPORT.md').open('a') as stream:
            stream.write('\nSIMULATED edited conclusion\n')
    else:
        if mutation == 'answer':
            report['correctness']['attempts']['candidate']['assertions'][-1]['observed']['missing_count'] = 1
        elif mutation == 'selection_boolean':
            report['correctness']['observer_prefixes'] = 1
        elif mutation == 'session_boolean':
            report['correctness']['attempts']['candidate']['assertions'][0]['observed'] = True
        else:
            report['correctness']['attempts']['candidate']['worker_deadline']['satisfied'] = 1
        (output / 'investigation.json').write_text(json.dumps(report))
    rehash(output)
    with pytest.raises(recipes.ContractError):
        investigation.verify_investigation_report(output / 'investigation.json')


def test_selected_report_relocation_and_stored_packages_keep_assertion_meaning(tmp_path, recipe, monkeypatch):
    monkeypatch.setenv('BGPERF_ARTIFACT_STORE', str(tmp_path / 'store'))
    baseline = package(tmp_path / 'baseline', recipe, BASE, large=True)
    candidate = package(tmp_path / 'candidate', recipe, CANDIDATE, large=True)
    output = tmp_path / 'report'
    report = investigation.write_investigation_report(baseline=baseline, candidate=candidate,
        output_dir=output, observer_prefixes=True)
    moved = tmp_path / 'relocated'
    shutil.copytree(output, moved)
    assert investigation.verify_investigation_report(moved / 'investigation.json')['valid']
    rebuilt = investigation.rebuild_investigation_report(moved / 'investigation.json', output_dir=tmp_path / 'rebuilt')
    assert rebuilt == report
    assert list((tmp_path / 'store/objects').glob('*/*.zst'))


@pytest.mark.parametrize('enabled', [False, True])
def test_controller_forwards_capture_symmetrically_and_preserves_default_runner_kwargs(tmp_path, recipe, enabled):
    targets = [supplied_target(recipe, image) for image in (BASE, CANDIDATE)]
    called = []
    def execute(document, **kwargs):
        label = 'baseline' if kwargs['target']['image'] == BASE else 'candidate'
        called.append((label, kwargs.get('observer_prefixes', 'not supplied')))
        source = package(tmp_path / ('fixture-' + label), document, kwargs['target']['image'], target=kwargs['target'])
        root = Path(kwargs['results_dir'])
        shutil.copytree(source.parent, root)
        return recipes.read_document(root / 'result.json')
    result = investigation.run_investigation(recipe, baseline_target=targets[0], candidate_target=targets[1],
        workdir=tmp_path / 'work', results_dir=tmp_path / 'results',
        observer_prefixes=enabled, check=lambda *a, **k: {'status': 'checks_passed'}, run=execute)
    expected = True if enabled else 'not supplied'
    assert called == [('baseline', expected), ('candidate', expected)]
    plan = recipes.read_document(tmp_path / 'results/investigation-plan.json')
    assert (plan.get('observer_prefixes') is True) is enabled
    if not enabled:
        assert 'observer_prefixes' not in plan
    report = recipes.read_document(result['report'])
    assert ('correctness' in report) is enabled
    if enabled:
        assert result['correctness'] == report['correctness']
    else:
        assert 'correctness' not in result


def test_oversize_capture_is_refused_before_precheck_or_output_creation(tmp_path, recipe, monkeypatch):
    monkeypatch.setattr(recipe_prefixes, 'MAX_PREFIXES', 1)
    targets = [supplied_target(recipe, image) for image in (BASE, CANDIDATE)]
    with pytest.raises(recipes.ContractError, match='100000'):
        investigation.run_investigation(recipe, baseline_target=targets[0], candidate_target=targets[1],
            workdir=tmp_path / 'work', results_dir=tmp_path / 'results', observer_prefixes=True,
            check=lambda *a, **k: pytest.fail('Unsupported selection reached prerequisites'),
            run=lambda *a, **k: pytest.fail('Unsupported selection reached runner'))
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('enabled', [1, None, 'yes'])
def test_nonboolean_capture_selection_is_refused_before_prerequisites(tmp_path, recipe, enabled):
    targets = [supplied_target(recipe, image) for image in (BASE, CANDIDATE)]
    with pytest.raises(recipes.ContractError, match='boolean'):
        investigation.run_investigation(recipe, baseline_target=targets[0], candidate_target=targets[1],
            workdir=tmp_path / 'work', results_dir=tmp_path / 'results', observer_prefixes=enabled,
            check=lambda *a, **k: pytest.fail('Invalid selection reached prerequisites'),
            run=lambda *a, **k: pytest.fail('Invalid selection reached runner'))
    assert list(tmp_path.iterdir()) == []


def test_changed_prefix_bytes_refuse_report_creation(tmp_path, recipe):
    baseline, candidate = pair(tmp_path, recipe)
    (candidate.parent / 'work/observer-prefixes.json').write_text('{}')
    output = tmp_path / 'report'
    with pytest.raises(recipes.ContractError):
        investigation.write_investigation_report(baseline=baseline, candidate=candidate,
            output_dir=output, observer_prefixes=True)
    assert not output.exists()


def test_controller_stop_keeps_selected_capture_and_never_runs_candidate(tmp_path, recipe):
    targets = [supplied_target(recipe, image) for image in (BASE, CANDIDATE)]
    calls = []
    def execute(document, **kwargs):
        calls.append(kwargs['target']['image'])
        assert kwargs['observer_prefixes'] is True
        source = package(tmp_path / 'fixture-baseline', document, BASE, target=kwargs['target'])
        shutil.copytree(source.parent, kwargs['results_dir'])
        raise KeyboardInterrupt('SIMULATED controller stop after immutable package')
    result = investigation.run_investigation(recipe, baseline_target=targets[0], candidate_target=targets[1],
        workdir=tmp_path / 'work', results_dir=tmp_path / 'results', observer_prefixes=True,
        check=lambda *a, **k: {'status': 'checks_passed'}, run=execute)
    report = recipes.read_document(result['report'])
    assert calls == [BASE] and result['exit_code'] == 130
    assert report['assessment']['outcome'] == 'inconclusive'
    assert report['correctness']['attempts']['baseline']['outcome'] == 'passed'
    assert report['correctness']['attempts']['candidate']['assertions'] == []
    rebuilt = investigation.rebuild_investigation_report(result['report'], output_dir=tmp_path / 'rebuilt')
    assert rebuilt == report and 'controller_stop' in rebuilt


def test_public_report_cli_selects_prefix_evaluation(tmp_path, recipe, capsys):
    baseline, candidate = pair(tmp_path, recipe)
    output = tmp_path / 'report'
    assert recipes.main(['investigation-report', '--baseline', str(baseline), '--candidate', str(candidate),
                         '--output-dir', str(output), '--observer-prefixes']) == 0
    assert json.loads(capsys.readouterr().out)['correctness']['observer_prefixes'] is True


@pytest.mark.parametrize('enabled', [False, True])
def test_public_investigate_cli_only_forwards_explicit_capture(tmp_path, recipe, monkeypatch, capsys, enabled):
    recipe_path = tmp_path / 'recipe.json'
    recipe_path.write_text(json.dumps(recipe))
    targets = []
    for label, image in (('baseline', BASE), ('candidate', CANDIDATE)):
        path = tmp_path / (label + '.json')
        path.write_text(json.dumps(supplied_target(recipe, image)))
        targets.append(path)
    calls = []
    def execute(document, **kwargs):
        calls.append(kwargs)
        return {'status': 'SIMULATED', 'exit_code': 0}
    monkeypatch.setattr(investigation, 'run_investigation', execute)
    argv = ['investigate', str(recipe_path), '--baseline-target', str(targets[0]),
            '--candidate-target', str(targets[1]), '--workdir', str(tmp_path / 'work'),
            '--results-dir', str(tmp_path / 'results')]
    if enabled:
        argv.append('--observer-prefixes')
    assert recipes.main(argv) == 0
    capsys.readouterr()
    assert len(calls) == 1
    if enabled:
        assert calls[0]['observer_prefixes'] is True
    else:
        assert 'observer_prefixes' not in calls[0]
