"""Investigation reports are bound to verified artifacts and frozen recipe controls."""
import copy
import hashlib
import json
from pathlib import Path

import pytest

import recipes
from recipe_investigation import (run_investigation, verify_investigation_report,
                                   write_investigation_report)
from recipe_results import write_result_package
from recipe_targets import supplied_target, effective_roles

ROOT = Path(__file__).resolve().parents[1]
BASE = 'sha256:' + '4' * 64
FIX = 'sha256:' + '5' * 64


@pytest.fixture
def recipe():
    document = recipes.read_document(ROOT / 'examples/recipes/synthetic-ipv4.recipe.json')
    document['reproduction'] = {'question': 'SIMULATED crash/fix question', 'expected_outcome': 'target_crash'}
    recipes.validate_recipe(document)
    return document


def package(root, recipe, image, *, status='completed', outcome='not_reproduced',
            memory=True, observations=True):
    root.mkdir(parents=True)
    work = root / 'work'
    work.mkdir()
    target = supplied_target(recipe, image, instrumentation='debug' if image == FIX else 'optimized')
    (work / 'target.json').write_text(json.dumps(target))
    checks = [{'name': 'image.' + role, 'status': 'pass',
               'details': {'requested': item['image'], 'image_id': item['image'], 'repo_digests': []}}
              for role, item in effective_roles(recipe, target).items()] if observations else []
    (work / 'prerequisites.json').write_text(json.dumps({'checks': checks}))
    (work / 'runtime.json').write_text(json.dumps({'status': status, 'reason': 'SIMULATED evidence'}))
    (work / 'diagnostics.json').write_text(json.dumps({'memory': {'target': {
        'peak_bytes': 200 if memory else None, 'ending_bytes': 100 if memory else None,
        'accounting': 'SIMULATED whole-container accounting',
        'reason': None if memory else 'SIMULATED unavailable observation'}}}))
    (work / 'stages.json').write_text(json.dumps({'events': [{'stage': 'terminal', 'status': status}]}))
    (work / 'console.log').write_text('SIMULATED runtime\n')
    (work / 'scenario.yaml').write_text('SIMULATED workload\n')
    (work / 'samples.csv').write_text('simulation\ntrue\n')
    (work / 'events.json').write_text('{}')
    (work / 'versions.json').write_text('{}')
    write_result_package(recipe, results_dir=root / 'result', workdir=work, attempt_id=root.name,
                         status=status, reason='SIMULATED fixture',
                         reproduction={'outcome': outcome, 'reason': 'SIMULATED witness',
                                       'evidence': ['work/runtime.json'] if outcome in ('reproduced', 'not_reproduced') else []})
    return root / 'result/result.json'


def pair(tmp_path, recipe, **kwargs):
    baseline = package(tmp_path / 'baseline', recipe, BASE, status='experiment_failed', outcome='reproduced')
    candidate = package(tmp_path / 'candidate', recipe, FIX, **kwargs)
    return baseline, candidate


def rehash_report(root):
    path = root / 'checksums.json'
    checksums = json.loads(path.read_text())
    for item in checksums['files']:
        item['sha256'] = hashlib.sha256((root / item['path']).read_bytes()).hexdigest()
    path.write_text(json.dumps(checksums))


def test_pair_report_verifies_artifacts_and_explains_fixed_controls(tmp_path, recipe):
    baseline, candidate = pair(tmp_path, recipe)
    original = baseline.read_bytes()
    output = tmp_path / 'report'
    report = write_investigation_report(baseline=baseline, candidate=candidate, output_dir=output)
    assert report['assessment']['outcome'] == 'baseline_reproduced_candidate_not_reproduced'
    assert report['assessment']['performance']['qualification'] == 'not_assessed'
    assert report['recipe_sha256'] == recipes.recipe_sha256(recipe)
    assert verify_investigation_report(output / 'investigation.json')['valid']
    prose = (output / 'REPORT.md').read_text()
    assert 'SIMULATED crash/fix question' in prose
    assert 'optimized' in prose and 'debug' in prose
    assert 'not prove a general bug fix' in prose
    assert baseline.read_bytes() == original
    with pytest.raises(recipes.ContractError, match='new'):
        write_investigation_report(baseline=baseline, candidate=candidate, output_dir=output)


def test_missing_memory_stays_unknown(tmp_path, recipe):
    baseline, candidate = pair(tmp_path, recipe, memory=False)
    output = tmp_path / 'report'
    report = write_investigation_report(baseline=baseline, candidate=candidate, output_dir=output)
    memory = report['attempts']['candidate']['diagnostics']['value']['memory']['target']
    assert memory['peak_bytes'] is None and memory['ending_bytes'] is None
    assert memory['reason']
    assert '`None` bytes' in (output / 'REPORT.md').read_text()


@pytest.mark.parametrize('status', ['harness_failed', 'interrupted', 'inconclusive', 'setup_refused'])
def test_failed_or_stopped_attempts_do_not_become_functional_pair_verdicts(tmp_path, recipe, status):
    baseline, candidate = pair(tmp_path, recipe, status=status, outcome='inconclusive')
    report = write_investigation_report(baseline=baseline, candidate=candidate, output_dir=tmp_path / 'report')
    assert report['assessment']['outcome'] == 'inconclusive'
    assert report['attempts']['candidate']['status'] == status


def test_never_run_is_distinct_from_failed(tmp_path, recipe):
    baseline = package(tmp_path / 'baseline', recipe, BASE, status='harness_failed', outcome='inconclusive')
    report = write_investigation_report(baseline=baseline, output_dir=tmp_path / 'report',
        candidate_missing={'status': 'not_run', 'reason': 'The baseline harness stopped the investigation.'})
    assert report['attempts']['baseline']['status'] == 'harness_failed'
    assert report['attempts']['candidate']['status'] == 'not_run'
    assert report['assessment']['outcome'] == 'inconclusive'
    assert verify_investigation_report(tmp_path / 'report/investigation.json')['valid']


def test_missing_observed_identities_withholds_pair_conclusion(tmp_path, recipe):
    baseline, candidate = pair(tmp_path, recipe, observations=False)
    report = write_investigation_report(baseline=baseline, candidate=candidate, output_dir=tmp_path / 'report')
    assert report['assessment']['outcome'] == 'inconclusive'
    assert any('identities' in reason for reason in report['assessment']['reasons'])


def test_different_recipe_refused_before_report_creation(tmp_path, recipe):
    baseline = package(tmp_path / 'baseline', recipe, BASE)
    changed = copy.deepcopy(recipe)
    changed['roles']['generator']['image'] = 'sha256:' + '6' * 64
    candidate = package(tmp_path / 'candidate', changed, FIX)
    with pytest.raises(recipes.ContractError, match='same frozen recipe'):
        write_investigation_report(baseline=baseline, candidate=candidate, output_dir=tmp_path / 'report')
    assert not (tmp_path / 'report').exists()


@pytest.mark.parametrize('mutation', ['bytes', 'extra', 'symlink'])
def test_tampered_source_package_refused(tmp_path, recipe, mutation):
    baseline, candidate = pair(tmp_path, recipe)
    path = candidate.parent / 'work/console.log'
    if mutation == 'bytes':
        path.write_text('changed')
    elif mutation == 'extra':
        (candidate.parent / 'extra').write_text('unlisted')
    else:
        path.unlink()
        path.symlink_to(tmp_path / 'baseline/result/work/console.log')
    with pytest.raises(recipes.ContractError):
        write_investigation_report(baseline=baseline, candidate=candidate, output_dir=tmp_path / 'report')


def test_altered_assessment_rejected_even_when_report_hash_is_recomputed(tmp_path, recipe):
    baseline, candidate = pair(tmp_path, recipe)
    output = tmp_path / 'report'
    write_investigation_report(baseline=baseline, candidate=candidate, output_dir=output)
    path = output / 'investigation.json'
    document = json.loads(path.read_text())
    document['assessment']['outcome'] = 'invented_fix_claim'
    path.write_text(json.dumps(document))
    rehash_report(output)
    with pytest.raises(recipes.ContractError, match='assessment'):
        verify_investigation_report(path)


def test_nonnested_package_report_destinations(tmp_path, recipe):
    baseline, candidate = pair(tmp_path, recipe)
    with pytest.raises(recipes.ContractError, match='nonnested'):
        write_investigation_report(baseline=baseline, candidate=candidate, output_dir=baseline.parent / 'report')


def test_investigation_prechecks_both_targets_before_execution_or_creation(tmp_path, recipe):
    targets = [supplied_target(recipe, image) for image in (BASE, FIX)]
    called = []
    def check(document, **kwargs):
        called.append(kwargs['target']['image'])
        return {'status': 'refused' if kwargs['target']['image'] == FIX else 'checks_passed'}
    result = run_investigation(recipe, baseline_target=targets[0], candidate_target=targets[1],
        workdir=tmp_path / 'work', results_dir=tmp_path / 'results', check=check,
        run=lambda *a, **k: pytest.fail('execution occurred'))
    assert called == [BASE, FIX]
    assert result['status'] == 'setup_refused'
    assert not list(tmp_path.iterdir())


def test_serial_investigation_continues_after_expected_baseline_experiment_failure(tmp_path, recipe):
    targets = [supplied_target(recipe, image) for image in (BASE, FIX)]
    calls = []
    def execute(document, **kwargs):
        label = 'baseline' if kwargs['target']['image'] == BASE else 'candidate'
        calls.append(label)
        root = Path(kwargs['results_dir'])
        # Build fixtures in a separate root and copy the verified package to the
        # result destination selected by the controller; no runtime is consulted.
        source = package(tmp_path / ('fixture-' + label), document, kwargs['target']['image'],
                         status='experiment_failed' if label == 'baseline' else 'completed',
                         outcome='reproduced' if label == 'baseline' else 'not_reproduced')
        import shutil
        shutil.copytree(source.parent, root)
        return recipes.read_document(root / 'result.json')
    result = run_investigation(recipe, baseline_target=targets[0], candidate_target=targets[1],
        workdir=tmp_path / 'work', results_dir=tmp_path / 'results',
        check=lambda *a, **k: {'status': 'checks_passed'}, run=execute)
    assert calls == ['baseline', 'candidate']
    assert result['status'] == 'recorded'
    assert verify_investigation_report(result['report'])['valid']


def test_serial_investigation_stops_after_harness_failure_with_readable_report(tmp_path, recipe):
    targets = [supplied_target(recipe, image) for image in (BASE, FIX)]
    calls = []
    def execute(document, **kwargs):
        calls.append(kwargs['target']['image'])
        raise RuntimeError('SIMULATED collector failure')
    result = run_investigation(recipe, baseline_target=targets[0], candidate_target=targets[1],
        workdir=tmp_path / 'work', results_dir=tmp_path / 'results',
        check=lambda *a, **k: {'status': 'checks_passed'}, run=execute)
    assert calls == [BASE]
    assert result['exit_code'] == 3
    report = recipes.read_document(result['report'])
    assert report['attempts']['baseline']['status'] == 'harness_failed'
    assert report['attempts']['candidate']['status'] == 'not_run'


def test_altered_prose_rejected_even_when_report_hash_is_recomputed(tmp_path, recipe):
    baseline, candidate = pair(tmp_path, recipe)
    output = tmp_path / 'report'
    write_investigation_report(baseline=baseline, candidate=candidate, output_dir=output)
    (output / 'REPORT.md').write_text('Invented performance or universal bug-fix conclusion')
    rehash_report(output)
    with pytest.raises(recipes.ContractError, match='Human report'):
        verify_investigation_report(output / 'investigation.json')


def test_altered_scope_cannot_add_unsupported_claims(tmp_path, recipe):
    baseline, candidate = pair(tmp_path, recipe)
    output = tmp_path / 'report'
    write_investigation_report(baseline=baseline, candidate=candidate, output_dir=output)
    path = output / 'investigation.json'
    report = json.loads(path.read_text())
    report['scope'] = 'Invented performance ranking'
    path.write_text(json.dumps(report))
    rehash_report(output)
    with pytest.raises(recipes.ContractError, match='scope'):
        verify_investigation_report(path)


def test_invalid_optional_diagnostics_preserved_without_losing_other_evidence(tmp_path, recipe):
    baseline, candidate = pair(tmp_path, recipe)
    diagnostic = candidate.parent / 'work/diagnostics.json'
    diagnostic.write_text('{SIMULATED interrupted JSON write')
    result = json.loads(candidate.read_text())
    for item in result['artifacts']:
        if item['path'] == 'work/diagnostics.json':
            item['sha256'] = hashlib.sha256(diagnostic.read_bytes()).hexdigest()
    candidate.write_text(json.dumps(result))
    output = tmp_path / 'report'
    report = write_investigation_report(baseline=baseline, candidate=candidate, output_dir=output)
    observation = report['attempts']['candidate']['diagnostics']
    assert observation['availability'] == 'present'
    assert observation['value'] is None and 'inspection failed' in observation['reason']
    assert (output / 'candidate/work/diagnostics.json').read_bytes() == diagnostic.read_bytes()
    assert verify_investigation_report(output / 'investigation.json')['valid']


@pytest.mark.parametrize('payload', [[], {'memory': []}, {'memory': {'target': []}},
    {'containers': [1]}, {'containers': [{'state': []}]},
    {'containers': [{'log': []}]}, {'errors': None},
    {'memory': {'target': {'peak_bytes': 'invented'}}},
    {'memory': {'target': {'units': 'kilobytes', 'ending_bytes': 1}}}])
def test_malformed_optional_diagnostic_shapes_never_erase_report(tmp_path, recipe, payload):
    baseline, candidate = pair(tmp_path, recipe)
    diagnostic = candidate.parent / 'work/diagnostics.json'
    diagnostic.write_text(json.dumps(payload))
    result = json.loads(candidate.read_text())
    for item in result['artifacts']:
        if item['path'] == 'work/diagnostics.json':
            item['sha256'] = hashlib.sha256(diagnostic.read_bytes()).hexdigest()
    candidate.write_text(json.dumps(result))
    output = tmp_path / 'report'
    report = write_investigation_report(baseline=baseline, candidate=candidate, output_dir=output)
    observation = report['attempts']['candidate']['diagnostics']
    assert observation['value'] is None and 'inspection failed' in observation['reason']
    assert (output / 'candidate/work/diagnostics.json').read_bytes() == diagnostic.read_bytes()
    assert verify_investigation_report(output / 'investigation.json')['valid']


def test_changed_host_identity_withholds_controlled_target_change_conclusion(tmp_path, recipe):
    baseline, candidate = pair(tmp_path, recipe)
    # Add host observations to source packages before creating the final reports.
    for path, name in ((baseline, 'first-host'), (candidate, 'different-host')):
        content = json.dumps({'hostname': name, 'kernel_release': 'fixture', 'architecture': 'fixture'})
        artifact = path.parent / 'work/host.json'
        artifact.write_text(content)
        result = json.loads(path.read_text())
        result['artifacts'].append({'kind': 'other', 'path': 'work/host.json',
            'sha256': hashlib.sha256(content.encode()).hexdigest(), 'availability': 'present', 'reason': None})
        path.write_text(json.dumps(result))
    report = write_investigation_report(baseline=baseline, candidate=candidate, output_dir=tmp_path / 'report')
    assert report['assessment']['outcome'] == 'inconclusive'
    assert any('Host identity changed' in reason for reason in report['assessment']['reasons'])
    assert verify_investigation_report(tmp_path / 'report/investigation.json')['valid']


def test_malformed_attempt_envelope_is_a_contract_refusal_not_keyerror(tmp_path, recipe):
    baseline, candidate = pair(tmp_path, recipe)
    output = tmp_path / 'report'
    write_investigation_report(baseline=baseline, candidate=candidate, output_dir=output)
    path = output / 'investigation.json'
    report = json.loads(path.read_text())
    report['attempts']['baseline'] = {'availability': 'missing'}
    path.write_text(json.dumps(report))
    rehash_report(output)
    with pytest.raises(recipes.ContractError):
        verify_investigation_report(path)
