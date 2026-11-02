"""Comparison outputs preserve observations and reconstruct every claimed result."""
import copy
import csv
import hashlib
import json
from pathlib import Path

import pytest

import recipes
from measurements import EVENT_PHASE, EventKind, LifecycleEvent
from recipe_comparison import make_comparison_plan
from recipe_comparison_report import build_comparison_report, verify_comparison_report
from recipe_diagnostics import memory_record
from recipe_results import write_result_package
from recipe_targets import supplied_target, effective_roles

ROOT = Path(__file__).resolve().parents[1]


def test_repeated_reports_reference_one_object_and_export_without_store(tmp_path, plan, monkeypatch):
    from artifact_store import export_tree, Store
    entries = attempts(tmp_path / 'sources', plan)
    raw = b'unchanged generator config\n' * 60000
    for entry in entries:
        path = Path(entry['result'])
        (path.parent / 'work/peer.conf').write_bytes(raw)
        document = json.loads(path.read_text())
        document['artifacts'].append({'kind': 'configuration', 'path': 'work/peer.conf',
                                      'sha256': hashlib.sha256(raw).hexdigest(),
                                      'availability': 'present', 'reason': None})
        path.write_text(json.dumps(document))
    monkeypatch.setenv('BGPERF_ARTIFACT_STORE', str(tmp_path / 'store'))
    for index in range(3):
        output = tmp_path / 'reports' / f'report-{index}'
        build_comparison_report(plan, entries, output)
        assert verify_comparison_report(output / 'comparison.json')['valid']
        assert not list(output.glob('attempts/*/work/peer.conf'))
    assert len(list((tmp_path / 'store/objects').glob('*/*.zst'))) == 1
    export_tree(tmp_path / 'reports', tmp_path / 'portable')
    (tmp_path / 'store').rename(tmp_path / 'absent-store')
    for index in range(3):
        assert verify_comparison_report(tmp_path / 'portable' / f'report-{index}' / 'comparison.json')['valid']


@pytest.fixture
def plan():
    recipe = recipes.read_document(ROOT / 'examples/recipes/synthetic-ipv4.recipe.json')
    recipe['reproduction']['question'] = 'SIMULATED controlled comparison'
    targets = [supplied_target(recipe, 'sha256:' + digit * 64, instrumentation='optimized')
               for digit in ('4', '5')]
    return make_comparison_plan(recipe, baseline_target=targets[0], candidate_target=targets[1], repetitions=3)


def package(root, plan, entry, *, elapsed=10, memory=200, status='completed',
            host='simulated-host', foreign=0, diagnostic_mode='none', instrumentation=None,
            stats=True, sampled_gib=0.123, final_diagnostics=True):
    work = root / 'work'
    work.mkdir(parents=True)
    recipe = plan['recipe']
    target = copy.deepcopy(plan['targets'][entry['role']])
    if instrumentation:
        target['provenance']['instrumentation'] = instrumentation
    documents = {
        'target.json': target,
        'host.json': {'hostname': host, 'kernel_release': 'SIMULATED', 'architecture': 'simulated',
                      'boot_id': 'fixture-boot', 'cpu_model': 'fixture-cpu', 'cpu_count': 4,
                      'cpu_affinity': [0, 1, 2, 3]},
        'prerequisites.json': {'checks': [
            {'name': 'image.' + role, 'status': 'pass', 'details': {
                'requested': item['image'], 'image_id': item['image'], 'repo_digests': []}}
            for role, item in effective_roles(recipe, target).items()]},
        'diagnostic-options.json': {'mode': diagnostic_mode},
        'diagnostics.json': {'memory': {'target': memory_record(
            {'peak_bytes': memory, 'ending_bytes': memory - 10} if memory is not None else None,
            reason=None if memory is not None else 'SIMULATED memory unavailable',
            sampled_peak_bytes=memory)}, 'containers': [
                {'role': role, 'state': {'Running': True, 'OOMKilled': False, 'Error': ''}}
                for role in ('target', 'generator', 'observer')]},
        'runtime.json': {'status': status, 'reason': 'SIMULATED engine outcome'},
        'execution-budget.json': {'schema': 'bgperf2/execution-budget/v1alpha1', 'scope': 'worker',
                                 'timeout_seconds': 300, 'elapsed_seconds': 20,
                                 'completed_within_budget': True}}
    # Explicit synthetic witnesses exercise the real assertion evaluator.
    sessions = recipe['resolved']['neighbors']
    count = sessions * recipe['resolved']['prefixes_per_peer']
    events = [LifecycleEvent(kind, timestamp, producer, EVENT_PHASE[kind], counters=counters).to_dict()
              for kind, timestamp, producer, counters in (
                  (EventKind.BENCH_CLOCK_STARTED, 1, 'controller', {}),
                  (EventKind.TESTER_SESSION_READY, 2, 'tester', {'sessions': sessions}),
                  (EventKind.TESTER_FIRST_UPDATE, 2.5, 'tester', {'sessions': sessions}),
                  (EventKind.TESTER_COMPLETE, 3, 'tester', {'sessions': sessions}),
                  (EventKind.CONVERGENCE_CONFIRMED, 10, 'controller', {'accepted_prefixes': count}))]
    documents['raw-events.json'] = {'events': events}
    if not final_diagnostics:
        documents['diagnostics.json'] = {'status': 'disabled', 'containers': [],
            'memory': {'target': memory_record(reason='Optional diagnostics were explicitly disabled.')}}
    for name, value in documents.items():
        (work / name).write_text(json.dumps(value))
    (work / 'simulated.log').write_text('SIMULATED no daemon was executed\n')
    (work / 'scenario.yaml').write_text('simulated: true\n')
    if stats:
        with (work / 'stats.csv').open('w', newline='') as output:
            writer = csv.writer(output)
            writer.writerow(['elapsed (s)', 'total time', 'max cpu %', 'max foreign cpu %',
                             'min idle%', 'min free mem (GB)', 'max mem (GB)', 'failed'])
            writer.writerow([elapsed, elapsed + 2, 50, foreign, 80, 8, sampled_gib,
                             '' if status == 'completed' else 'FAILED'])
    write_result_package(recipe, results_dir=root / 'results', workdir=work, attempt_id=entry['id'],
                         status=status, reason='SIMULATED controlled evidence')
    return root / 'results/result.json'


def attempts(tmp_path, plan, **changes):
    entries = []
    for entry in plan['sequence']:
        values = {'elapsed': 10 if entry['role'] == 'baseline' else 20}
        values.update(changes.get(entry['id'], {}))
        path = package(tmp_path / entry['id'], plan, entry, **values)
        entries.append({**entry, 'result': str(path), 'status': values.get('status', 'completed'),
                        'reason': 'SIMULATED ledger'})
    return entries


def rehash(root):
    manifest = json.loads((root / 'checksums.json').read_text())
    for item in manifest['files']:
        item['sha256'] = hashlib.sha256((root / item['path']).read_bytes()).hexdigest()
    (root / 'checksums.json').write_text(json.dumps(manifest))


def replace_artifact(manifest_path, relative, value):
    path = manifest_path.parent / relative
    path.write_text(json.dumps(value))
    manifest = json.loads(manifest_path.read_text())
    for artifact in manifest['artifacts']:
        if artifact['path'] == relative:
            artifact['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest))


def test_known_difference_is_descriptive_and_verified(tmp_path, plan):
    entries = attempts(tmp_path, plan)
    output = tmp_path / 'report'
    report = build_comparison_report(plan, entries, output)
    metric = report['measurements']['timing']['monitor_elapsed_seconds']
    assert metric['baseline']['n'] == metric['candidate']['n'] == 3
    assert metric['baseline']['statistics']['median'] == 10
    assert metric['candidate']['statistics']['median'] == 20
    assert report['descriptive_deltas']['timing']['monitor_elapsed_seconds']['candidate_minus_baseline_median'] == 10
    assert report['performance']['qualification'] == 'not_assessed'
    assert report['performance']['policy'] == 'disabled'
    assert report['correctness']['baseline']['passed'] == 3
    assert verify_comparison_report(output / 'comparison.json')['valid']
    prose = (output / 'REPORT.md').read_text()
    assert 'SIMULATED controlled comparison' in prose
    assert 'one-second resolution' in prose
    assert 'no calibrated performance verdict' in prose
    assert 'not process RSS' in prose


def test_noise_keeps_individual_observations_and_sample_dispersion(tmp_path, plan):
    entries = attempts(tmp_path, plan, **{'r001-baseline': {'elapsed': 5}, 'r003-baseline': {'elapsed': 15}})
    report = build_comparison_report(plan, entries, tmp_path / 'report')
    distribution = report['measurements']['timing']['monitor_elapsed_seconds']['baseline']
    assert [item['value'] for item in distribution['observations']] == [5, 10, 15]
    assert distribution['statistics']['stdev'] == 5
    assert distribution['statistics']['cv_percent'] == 50
    assert report['performance']['policy'] == 'disabled'


@pytest.mark.parametrize(('change', 'code'), [
    ({'host': 'different-host'}, 'changed_host'),
    ({'foreign': 0.1}, 'foreign_cpu_observed'),
    ({'diagnostic_mode': 'basic'}, 'diagnostic_overhead')])
def test_confounded_measurements_survive_but_delta_is_withheld(tmp_path, plan, change, code):
    entries = attempts(tmp_path, plan, **{'r001-candidate': change})
    report = build_comparison_report(plan, entries, tmp_path / 'report')
    assert code in {item['code'] for item in report['confounders']}
    distribution = report['measurements']['timing']['monitor_elapsed_seconds']['candidate']
    assert distribution['n'] == 3 and distribution['statistics']['median'] == 20
    delta = report['descriptive_deltas']['timing']['monitor_elapsed_seconds']
    assert delta['candidate_minus_baseline_median'] is None and delta['reason']


def test_failed_not_run_and_missing_measurement_remain_separate(tmp_path, plan):
    entries = attempts(tmp_path, plan, **{'r001-baseline': {'status': 'experiment_failed'},
                                        'r001-candidate': {'memory': None}})
    entries[-1].update(result=None, status='not_run', reason='SIMULATED earlier stop')
    report = build_comparison_report(plan, entries, tmp_path / 'report')
    baseline = report['measurements']['memory']['target_cgroup_peak_bytes']['baseline']
    candidate = report['measurements']['memory']['target_cgroup_peak_bytes']['candidate']
    assert baseline['n'] == 2 and baseline['failed'] == 1 and baseline['not_run'] == 0
    assert candidate['n'] == 1 and candidate['missing'] == 1 and candidate['not_run'] == 1
    assert candidate['observations'][0]['value'] is None
    assert candidate['observations'][0]['reason'] == 'SIMULATED memory unavailable'
    assert report['attempts'][-1]['assertions'] is None
    assert verify_comparison_report(tmp_path / 'report/comparison.json')['valid']


def test_no_attempts_have_null_statistics_and_reasons(tmp_path, plan):
    entries = [{**entry, 'result': None, 'status': 'not_run', 'reason': 'SIMULATED not requested'}
               for entry in plan['sequence']]
    report = build_comparison_report(plan, entries, tmp_path / 'report')
    distribution = report['measurements']['cpu']['target_peak_cpu_percent']['baseline']
    assert distribution['n'] == 0 and distribution['not_run'] == 3
    assert set(distribution['statistics'].values()) == {None}
    assert all(distribution['withheld_reasons'].values())


def test_single_observation_cannot_claim_zero_dispersion(tmp_path, plan):
    plan['repetitions'] = 1
    plan['sequence'] = plan['sequence'][:2]
    report = build_comparison_report(plan, attempts(tmp_path, plan), tmp_path / 'report')
    distribution = report['measurements']['timing']['monitor_elapsed_seconds']['baseline']
    assert distribution['statistics']['stdev'] is None
    assert distribution['statistics']['cv_percent'] is None
    assert distribution['withheld_reasons']['stdev']


def test_missing_stats_is_not_replaced_by_zero_or_partial_data(tmp_path, plan):
    report = build_comparison_report(plan, attempts(tmp_path, plan, **{'r001-candidate': {'stats': False}}), tmp_path / 'report')
    distribution = report['measurements']['timing']['monitor_elapsed_seconds']['candidate']
    assert distribution['n'] == 2 and distribution['missing'] == 1
    assert distribution['observations'][0]['value'] is None
    assert 'partial samples' in distribution['observations'][0]['reason']


def test_legacy_sampled_memory_keeps_gib_and_delivery_boundary(tmp_path, plan):
    entries = attempts(tmp_path, plan, **{'r001-candidate': {'sampled_gib': 1.234}})
    report = build_comparison_report(plan, entries, tmp_path / 'report')
    observation = report['measurements']['memory']['target_delivery_sampled_peak_gib']['candidate']['observations'][0]
    assert observation['value'] == 1.234 and observation['units'] == 'GiB'
    assert observation['source'] == 'work/stats.csv'
    assert 'delivery window' in observation['definition']
    assert 'rounded to three decimals' in observation['definition']
    assert 'not a lifetime cgroup peak' in observation['definition']
    assert report['measurements']['memory']['target_cgroup_peak_bytes']['candidate']['observations'][0]['value'] == 200


def test_none_diagnostics_cgroup_absence_does_not_withhold_other_metrics(tmp_path, plan):
    plan['assertions']['assertions'] = [item for item in plan['assertions']['assertions']
                                      if item['capability'] != 'observed_role_health']
    entries = attempts(tmp_path, plan, **{entry['id']: {'final_diagnostics': False} for entry in plan['sequence']})
    report = build_comparison_report(plan, entries, tmp_path / 'report')
    assert not report['confounders']
    cgroup = report['measurements']['memory']['target_cgroup_peak_bytes']['baseline']
    assert cgroup['n'] == 0 and cgroup['missing'] == 3
    assert cgroup['observations'][0]['value'] is None and cgroup['observations'][0]['reason']
    assert report['descriptive_deltas']['memory']['target_cgroup_peak_bytes']['candidate_minus_baseline_median'] is None
    assert report['descriptive_deltas']['timing']['monitor_elapsed_seconds']['candidate_minus_baseline_median'] == 10
    assert report['descriptive_deltas']['cpu']['target_peak_cpu_percent']['candidate_minus_baseline_median'] == 0
    assert report['measurements']['memory']['target_delivery_sampled_peak_gib']['baseline']['n'] == 3
    assert verify_comparison_report(tmp_path / 'report/comparison.json')['valid']


@pytest.mark.parametrize('value', [0, -1, 'missing', 'NaN'])
def test_legacy_unsampled_or_invalid_memory_is_null(tmp_path, plan, value):
    entries = attempts(tmp_path, plan, **{'r001-candidate': {'sampled_gib': value}})
    report = build_comparison_report(plan, entries, tmp_path / 'report')
    metric = report['measurements']['memory']['target_delivery_sampled_peak_gib']['candidate']
    assert metric['n'] == 2 and metric['missing'] == 1
    assert metric['observations'][0]['value'] is None and metric['observations'][0]['reason']


def test_worker_budget_must_match_frozen_plan(tmp_path, plan):
    entries = attempts(tmp_path, plan)
    plan['timeout'] = 1
    with pytest.raises(recipes.ContractError, match='worker timeout'):
        build_comparison_report(plan, entries, tmp_path / 'report')
    assert not (tmp_path / 'report').exists()


@pytest.mark.parametrize('mutation', ['definition', 'accounting', 'huge_memory'])
def test_malformed_diagnostic_metadata_retains_raw_evidence_and_null_metric(tmp_path, plan, mutation):
    plan['repetitions'] = 1
    plan['sequence'] = plan['sequence'][:2]
    entries = attempts(tmp_path, plan)
    path = Path(entries[0]['result'])
    diagnostic = json.loads((path.parent / 'work/diagnostics.json').read_text())
    memory = diagnostic['memory']['target']
    if mutation == 'definition':
        memory['peak_definition'] = {'malformed': True}
    elif mutation == 'accounting':
        memory['accounting'] = {'malformed': True}
    else:
        memory['peak_bytes'] = 10 ** 400
    replace_artifact(path, 'work/diagnostics.json', diagnostic)
    report = build_comparison_report(plan, entries, tmp_path / 'report')
    metric = report['measurements']['memory']['target_cgroup_peak_bytes']['baseline']
    assert metric['n'] == 0 and metric['missing'] == 1
    assert metric['observations'][0]['value'] is None and metric['observations'][0]['reason']
    assert (tmp_path / 'report/attempts/r001-baseline/work/diagnostics.json').read_bytes() == (path.parent / 'work/diagnostics.json').read_bytes()
    assert verify_comparison_report(tmp_path / 'report/comparison.json')['valid']


def test_duplicate_original_attempts_cannot_invent_repetitions(tmp_path, plan):
    entries = attempts(tmp_path, plan)
    path = Path(entries[3]['result'])
    document = json.loads(path.read_text())
    document['attempt']['id'] = plan['sequence'][0]['id']
    path.write_text(json.dumps(document))
    with pytest.raises(recipes.ContractError, match='unique original result attempt IDs'):
        build_comparison_report(plan, entries, tmp_path / 'report')
    assert not (tmp_path / 'report').exists()


def test_verifier_rejects_rehashed_duplicate_original_attempt(tmp_path, plan):
    output = tmp_path / 'report'
    build_comparison_report(plan, attempts(tmp_path, plan), output)
    path = output / 'attempts/r002-baseline/result.json'
    document = json.loads(path.read_text())
    document['attempt']['id'] = 'r001-baseline'
    path.write_text(json.dumps(document))
    rehash(output)
    with pytest.raises(recipes.ContractError, match='unique original result attempt IDs'):
        verify_comparison_report(output / 'comparison.json')


@pytest.mark.parametrize('mutation', ['prose', 'statistics', 'verdict', 'assertions', 'extra', 'empty_directory', 'symlink', 'bytes'])
def test_tampering_cannot_be_hidden_by_rehashing(tmp_path, plan, mutation):
    output = tmp_path / 'report'
    build_comparison_report(plan, attempts(tmp_path, plan), output)
    path = output / 'comparison.json'
    document = json.loads(path.read_text())
    if mutation == 'prose':
        (output / 'REPORT.md').write_text('Candidate is proven faster')
    elif mutation == 'statistics':
        document['measurements']['timing']['monitor_elapsed_seconds']['candidate']['statistics']['median'] = 1
    elif mutation == 'verdict':
        document['performance']['qualification'] = 'regression'
    elif mutation == 'assertions':
        document['attempts'][0]['assertions']['outcome'] = 'failed'
    elif mutation == 'extra':
        (output / 'unlisted.txt').write_text('extra')
        checksums = json.loads((output / 'checksums.json').read_text())
        checksums['files'].append({'path': 'unlisted.txt', 'sha256': '0' * 64})
        (output / 'checksums.json').write_text(json.dumps(checksums))
    elif mutation == 'empty_directory':
        (output / 'empty-extra').mkdir()
    elif mutation == 'symlink':
        (output / 'REPORT.md').unlink()
        (output / 'REPORT.md').symlink_to(tmp_path / 'r001-baseline/results/SUMMARY.txt')
    else:
        (output / 'attempts/r001-baseline/work/simulated.log').write_text('modified evidence')
    path.write_text(json.dumps(document))
    rehash(output)
    with pytest.raises(recipes.ContractError):
        verify_comparison_report(path)


def test_mismatched_target_and_recipe_refused_before_writing(tmp_path, plan):
    entries = attempts(tmp_path, plan)
    changed = copy.deepcopy(plan)
    changed['targets']['baseline']['label'] = 'different planned identity'
    with pytest.raises(recipes.ContractError, match='target'):
        build_comparison_report(changed, entries, tmp_path / 'report')
    assert not (tmp_path / 'report').exists()


@pytest.mark.parametrize('mutation', ['sequence', 'status', 'relative', 'missing_package'])
def test_malformed_attempt_ledger_refused(tmp_path, plan, mutation):
    entries = attempts(tmp_path, plan)
    if mutation == 'sequence':
        entries.reverse()
    elif mutation == 'status':
        entries[0]['status'] = 'harness_failed'
    elif mutation == 'relative':
        entries[0]['result'] = 'result.json'
    else:
        entries[0]['result'] = None
    with pytest.raises(recipes.ContractError):
        build_comparison_report(plan, entries, tmp_path / 'report')


def test_report_requires_new_nonnested_destination(tmp_path, plan):
    entries = attempts(tmp_path, plan)
    with pytest.raises(recipes.ContractError, match='nonnested'):
        build_comparison_report(plan, entries, Path(entries[0]['result']).parent / 'report')
    output = tmp_path / 'report'
    output.mkdir()
    with pytest.raises(recipes.ContractError, match='new'):
        build_comparison_report(plan, entries, output)
