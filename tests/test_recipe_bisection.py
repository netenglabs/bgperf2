"""Deterministic searches use fake builds/workers and real package verification."""
import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

import recipes
import recipe_bisection as bisect
import recipe_targets as targets
from recipe_comparison import make_comparison_plan
from test_recipe_comparison_report import package, ROOT


def fixture_plan(tmp_path, count=9, *, predicate='assertions', budget=32):
    recipe = recipes.read_document(ROOT / 'examples/recipes/synthetic-ipv4.recipe.json')
    recipe['reproduction']['question'] = 'SIMULATED deterministic regression, no real BIRD source/build'
    if predicate == 'target_crash':
        recipe['reproduction']['expected_outcome'] = 'target_crash'
    builds, objects, previous = [], [], None
    for i in range(count):
        raw = (f'tree {"0" * 40}\n' + (f'parent {previous}\n' if previous else '') +
               f'author SIMULATED <fixture@example.invalid> {i} +0000\n'
               f'committer SIMULATED <fixture@example.invalid> {i} +0000\n\nSIMULATED {i}\n').encode()
        revision = hashlib.sha1(b'commit ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
        source = {'requested_revision': revision, 'commit': revision, 'checkout_head': revision,
                  'dirty': False, 'include_dirty': False, 'patch_sha256': hashlib.sha256(b'').hexdigest(),
                  'untracked': [], 'snapshot_sha256': hashlib.sha256(f'SIMULATED {i}'.encode()).hexdigest()}
        builds.append({'schema': targets.BUILD_SCHEMA, 'recipe': recipe,
                       'recipe_sha256': recipes.recipe_sha256(recipe), 'source_root': str(tmp_path / f'source-{i}'),
                       'source': source, 'toolchain_image': 'sha256:' + 'a' * 64,
                       'runtime_image': 'sha256:' + 'b' * 64, 'instrumentation': 'debug',
                       'cflags': '-O0 -g', 'configure_flags': [], 'build_recipe': 'bird-local/v1',
                       'network': 'none', 'requirements': ['SIMULATED no toolchain is invoked'],
                       'limits': ['SIMULATED source/build identities; not authentic execution']})
        objects.append(raw)
        previous = revision
    return bisect.make_plan(recipe, builds, objects, predicate=predicate, max_trials=budget)


def fake_target(build):
    image = 'sha256:' + bisect.digest(build)
    provenance = {'kind': 'local_source', 'source': build['source'], 'instrumentation': build['instrumentation'],
                  'limits': build['limits'], 'build': {
                      'recipe': build['build_recipe'], 'toolchain_image': build['toolchain_image'],
                      'runtime_image': build['runtime_image'], 'toolchain_image_id': build['toolchain_image'],
                      'runtime_image_id': build['runtime_image'], 'compiler_flags': build['cflags'],
                      'linker_flags': build['cflags'], 'configure_flags': build['configure_flags'],
                      'source_snapshot_sha256': build['source']['snapshot_sha256'], 'build_log_sha256': 'c' * 64,
                      'image_id': image, 'binary_sha256': None, 'reconstructible': False,
                      'dockerfile_sha256': hashlib.sha256(targets._dockerfile(build['toolchain_image'], build['runtime_image'], build).encode()).hexdigest()}}
    return {'schema': targets.TARGET_SCHEMA, 'recipe_sha256': build['recipe_sha256'], 'adapter': 'bird',
            'image': image, 'label': 'SIMULATED ' + build['source']['commit'][:8], 'provenance': provenance}


def rehash_result(path):
    result = json.loads(path.read_text())
    for artifact in result['artifacts']:
        if artifact['availability'] == 'present':
            artifact['sha256'] = hashlib.sha256((path.parent / artifact['path']).read_bytes()).hexdigest()
    path.write_text(json.dumps(result))


def fake_backends(tmp_path, plan, *, first_bad=4, skips=(), ambiguous=(), unstable=False):
    builds, runs = [], []
    revision_indices = {c['revision']: i for i, c in enumerate(plan['candidates'])}

    def build(document, *, output_dir, emit_disclosure, timeout):
        i = revision_indices[document['source']['commit']]
        builds.append(i)
        output_dir.mkdir(parents=True)
        emit_disclosure({'SIMULATED': True, 'revision': document['source']['commit']})
        if i in skips:
            (output_dir / 'build.log').write_text('SIMULATED compiler failure')
            (output_dir / 'build-result.json').write_text('{"status":"failed"}')
            raise recipes.ContractError('SIMULATED unbuildable revision')
        return fake_target(document)

    def run(recipe, *, target, workdir, results_dir, timeout, diagnostics):
        i = revision_indices[target['provenance']['source']['commit']]
        repeat = i in runs
        runs.append(i)
        bad = i >= first_bad
        if unstable and repeat:
            bad = not bad
        status = 'harness_failed' if i in ambiguous else 'experiment_failed' if bad else 'completed'
        p = make_comparison_plan(recipe, baseline_target=target, candidate_target=target, repetitions=1)
        result = package(tmp_path / f'fixture-{len(runs)}', p,
                         {'id': f'SIMULATED-unique-{len(runs)}', 'role': 'baseline'}, status=status,
                         diagnostic_mode='basic')
        budget = result.parent / 'work/execution-budget.json'
        data = json.loads(budget.read_text()); data['timeout_seconds'] = timeout
        data.update(started_monotonic_s=1, ended_monotonic_s=21)
        budget.write_text(json.dumps(data))
        live = {'samples': [{'role': 'target', 'container_id': 'SIMULATED-container', 'monotonic_s': 2,
                             'bird_process_present': True, 'errors': []}]}
        if bad:
            live['samples'].append({'role': 'target', 'container_id': 'SIMULATED-container', 'monotonic_s': 11,
                                   'bird_process_present': False, 'daemon_exit_code': 139, 'errors': []})
        relative = 'work/live-diagnostics.json'
        (result.parent / relative).write_text(json.dumps(live))
        document = json.loads(result.read_text())
        document['artifacts'].append({'path': relative, 'availability': 'present', 'reason': None,
                                     'kind': 'other', 'sha256': '0' * 64})
        result.write_text(json.dumps(document))
        rehash_result(result)
        shutil.copytree(result.parent, results_dir)
        return json.loads((results_dir / 'result.json').read_text())

    return builds, runs, build, run


@pytest.mark.parametrize('predicate', ['assertions', 'target_crash'])
def test_confirmed_boundary_cached_builds_fresh_confirmations_and_portable_report(tmp_path, predicate):
    plan = fixture_plan(tmp_path, predicate=predicate)
    session = tmp_path / 'session'
    bisect.initialize(plan, session)
    builds, runs, build, run = fake_backends(tmp_path, plan)
    result = bisect.run_search(session, build=build, run=run)
    assert result['state'] == 'confirmed'
    assert result['last_observed_good'] == plan['candidates'][3]['revision']
    assert result['first_observed_bad'] == plan['candidates'][4]['revision']
    assert len(runs) == 7 and len(builds) == 5
    assert runs[-2:] == [3, 4]  # fresh workers, cached images
    report = tmp_path / 'portable'
    assert bisect.report(session, report)['valid']
    assert bisect.verify_report(report / 'bisection.json')['conclusion'] == result
    document = json.loads((report / 'bisection.json').read_text())
    assert document['performance'] == {'qualification': 'not_assessed', 'policy': 'disabled'}
    assert len({x['observed']['source_attempt_id'] for x in document['trials']}) == 7


def test_skipped_revision_preserves_ambiguous_first_bad_range(tmp_path):
    plan = fixture_plan(tmp_path)
    bisect.initialize(plan, tmp_path / 'session')
    _, _, build, run = fake_backends(tmp_path, plan, skips=(4,))
    result = bisect.run_search(tmp_path / 'session', build=build, run=run)
    assert result['state'] == 'unresolved'
    assert result['possible_first_bad'] == [plan['candidates'][i]['revision'] for i in (4, 5)]
    assert bisect.report(tmp_path / 'session', tmp_path / 'report')['valid']
    _, records = bisect.history(tmp_path / 'session')
    assert any(r['classification'] == 'skipped' and r['result'] is None for r in records)


def test_ambiguous_runtime_pauses_and_explicit_resume_never_retries_it(tmp_path):
    plan = fixture_plan(tmp_path)
    bisect.initialize(plan, tmp_path / 'session')
    _, runs, build, run = fake_backends(tmp_path, plan, ambiguous=(4,))
    result = bisect.run_search(tmp_path / 'session', build=build, run=run)
    assert result['state'] == 'paused_ambiguous'
    assert runs == [0, 8, 4]
    result = bisect.run_search(tmp_path / 'session', build=build, run=run)
    assert result['state'] == 'unresolved' and runs.count(4) == 1


def test_confirmation_failure_is_not_a_boundary(tmp_path):
    plan = fixture_plan(tmp_path)
    bisect.initialize(plan, tmp_path / 'session')
    _, _, build, run = fake_backends(tmp_path, plan, unstable=True)
    result = bisect.run_search(tmp_path / 'session', build=build, run=run)
    assert result['state'] == 'unresolved'
    assert 'confirmation failed' in result['reason']


def test_trial_budget_is_never_extended(tmp_path):
    plan = fixture_plan(tmp_path, budget=4)
    bisect.initialize(plan, tmp_path / 'session')
    _, runs, build, run = fake_backends(tmp_path, plan)
    assert bisect.run_search(tmp_path / 'session', build=build, run=run)['state'] == 'budget_exhausted'
    assert len(runs) == 4


def test_pending_trial_blocks_retry_and_explicit_abandon_consumes_budget(tmp_path):
    plan = fixture_plan(tmp_path)
    session = tmp_path / 'session'; bisect.initialize(plan, session)
    selected = bisect.next_trial(session)
    bisect.write(session / 'pending.json', selected)
    assert bisect.next_trial(session)['state'] == 'recovery_required'
    with pytest.raises(recipes.ContractError, match='recover'):
        bisect.step(session, build=lambda *a, **k: pytest.fail('build started'))
    assert bisect.report(session, tmp_path / 'report')['conclusion']['state'] == 'recovery_required'
    bisect.recover(session, reason='Operator verified stopped; original incomplete work retained')
    assert bisect.next_trial(session)['state'] == 'unresolved'
    assert len(bisect.history(session)[1]) == 1


def test_append_finished_before_marker_clear_is_reconciled_without_rerun(tmp_path):
    plan = fixture_plan(tmp_path)
    session = tmp_path / 'session'; bisect.initialize(plan, session)
    _, runs, build, run = fake_backends(tmp_path, plan)
    record = bisect.step(session, build=build, run=run)
    bisect.write(session / 'pending.json', record['request'])
    assert bisect.next_trial(session)['phase'] == 'endpoint-bad'
    assert runs == [0] and not (session / 'pending.json').exists()


@pytest.mark.parametrize('kind', ['performance', 'chain-gap', 'commit-hash', 'dirty', 'flags', 'budget', 'infinite'])
def test_unsupported_or_changed_plans_refuse_before_runtime(tmp_path, kind):
    plan = fixture_plan(tmp_path)
    if kind == 'performance': plan['predicate'] = 'performance'
    elif kind == 'chain-gap': del plan['candidates'][3]
    elif kind == 'commit-hash': plan['candidates'][0]['commit_object'] = base64.b64encode(b'altered').decode()
    elif kind == 'dirty':
        plan['candidates'][1]['build_plan']['source'].update(dirty=True, include_dirty=True)
    elif kind == 'flags': plan['candidates'][1]['build_plan']['cflags'] = '-O1'
    elif kind == 'budget': plan['max_trials'] = 3
    else: plan['worker_timeout'] = float('inf')
    with pytest.raises(recipes.ContractError): bisect.initialize(plan, tmp_path / 'session')
    assert not (tmp_path / 'session').exists()


def test_cli_execution_is_opt_in_and_never_runs_from_next(tmp_path, monkeypatch, capsys):
    plan = fixture_plan(tmp_path)
    session = tmp_path / 'session'; bisect.initialize(plan, session)
    monkeypatch.setattr(bisect, 'step', lambda *a, **k: pytest.fail('runtime started'))
    assert bisect.main(['step', str(session)]) == 0
    assert json.loads(capsys.readouterr().out)['phase'] == 'endpoint-good'


def test_changed_package_and_rehashed_human_report_cannot_change_conclusion(tmp_path):
    plan = fixture_plan(tmp_path)
    session = tmp_path / 'session'; bisect.initialize(plan, session)
    _, _, build, run = fake_backends(tmp_path, plan)
    bisect.run_search(session, build=build, run=run)
    output = tmp_path / 'report'; bisect.report(session, output)
    prose = output / 'REPORT.md'; prose.write_text('Unsupported performance improvement claim')
    manifest = json.loads((output / 'checksums.json').read_text())
    for item in manifest['files']:
        item['sha256'] = hashlib.sha256((output / item['path']).read_bytes()).hexdigest()
    (output / 'checksums.json').write_text(json.dumps(manifest))
    with pytest.raises(recipes.ContractError, match='human report'):
        bisect.verify_report(output / 'bisection.json')
    (session / 'evidence/t0001/work/runtime.json').write_text('{"status":"invented"}')
    with pytest.raises(recipes.ContractError, match='SHA-256'):
        bisect.next_trial(session)


@pytest.mark.parametrize('mutation', ['backwards', 'outside-budget', 'missing-clock', 'dropped', 'probe-error', 'other-container'])
def test_incomplete_or_unordered_crash_witness_is_ambiguous(tmp_path, mutation):
    plan = fixture_plan(tmp_path, predicate='target_crash')
    _, _, build, run = fake_backends(tmp_path, plan, first_bad=0)
    result_dir = tmp_path / 'result'
    run(plan['recipe'], target=fake_target(plan['candidates'][0]['build_plan']),
        workdir=tmp_path / 'work', results_dir=result_dir, timeout=120, diagnostics='basic')
    live_path = result_dir / 'work/live-diagnostics.json'
    live = json.loads(live_path.read_text())
    if mutation == 'backwards': live['samples'][1]['monotonic_s'] = 1
    elif mutation == 'outside-budget': live['samples'][1]['monotonic_s'] = 999
    elif mutation == 'missing-clock': del live['samples'][1]['monotonic_s']
    elif mutation == 'dropped': live['dropped_samples'] = 1
    elif mutation == 'probe-error': live['samples'][1]['errors'] = ['bird_process: OSError']
    else: live['samples'][1]['container_id'] = 'SIMULATED-unrelated-container'
    live_path.write_text(json.dumps(live)); rehash_result(result_dir / 'result.json')
    assert bisect.classification(plan, 0, result_dir / 'result.json')['classification'] == 'ambiguous'


def test_public_planner_reads_real_local_commit_objects_without_checkout_changes(tmp_path, capsys, monkeypatch):
    source = tmp_path / 'source'
    source.mkdir()
    traps = [tmp_path / name for name in ('trap-git-dir', 'trap-work-tree', 'trap-index')]
    for key, trap in zip(('GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE'), traps):
        monkeypatch.setenv(key, str(trap))
    isolated_env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
    def git(*args):
        return subprocess.run(['git', '-C', str(source), *args], env=isolated_env,
                              check=True, capture_output=True).stdout.decode().strip()
    git('init', '-q')
    (source / 'README').write_text('SIMULATED inert source; never built\n')
    (source / 'configure.ac').write_text('# SIMULATED inert BIRD-style fixture\n')
    (source / 'Makefile.in').write_text('# SIMULATED never executed\n')
    git('add', 'README', 'configure.ac', 'Makefile.in')
    git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'first')
    first = git('rev-parse', 'HEAD')
    recipe = fixture_plan(tmp_path)['recipe']
    def build(revision):
        return targets.plan_source_build(recipe, source, revision, toolchain_image='sha256:' + 'a' * 64,
                                         runtime_image='sha256:' + 'b' * 64)
    old = build(first)
    (source / 'README').write_text('SIMULATED changed inert source\n')
    git('add', 'README')
    git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'second')
    second = git('rev-parse', 'HEAD')
    new = build(second)
    recipe_path = tmp_path / 'recipe.json'; bisect.write(recipe_path, recipe)
    arguments = ['plan', '--recipe', str(recipe_path), '--predicate', 'assertions', '--max-trials', '4']
    for i, document in enumerate((old, new)):
        path = tmp_path / f'build-{i}.json'; bisect.write(path, document)
        arguments += ['--build-plan', str(path)]
    path = tmp_path / 'plan.json'
    assert bisect.main(arguments + ['--output', str(path)]) == 0
    capsys.readouterr()
    assert [c['revision'] for c in bisect.load(path)['candidates']] == [first, second]
    assert git('rev-parse', 'HEAD') == second and git('status', '--porcelain') == ''
    assert not any(trap.exists() for trap in traps)


def test_recovery_preserves_failure_written_before_journal(tmp_path, monkeypatch):
    plan = fixture_plan(tmp_path)
    session = tmp_path / 'session'; bisect.initialize(plan, session)
    _, _, build, run = fake_backends(tmp_path, plan, skips=(0,))
    real_write = bisect.write
    def interrupted_write(path, value):
        if Path(path).parent.name == 'trials':
            raise OSError('SIMULATED interrupted before journal write')
        return real_write(path, value)
    with monkeypatch.context() as changes:
        changes.setattr(bisect, 'write', interrupted_write)
        with pytest.raises(OSError): bisect.step(session, build=build, run=run)
    original = (session / 'failures/t0001.json').read_bytes()
    record = bisect.recover(session, reason='Operator requests recovery; retain original build failure')
    assert record['classification'] == 'skipped'
    assert (session / 'failures/t0001.json').read_bytes() == original
    assert bisect.next_trial(session)['state'] == 'unresolved'


def test_recovery_preserves_partial_copy_and_reimports_verified_original(tmp_path, monkeypatch):
    plan = fixture_plan(tmp_path)
    session = tmp_path / 'session'; bisect.initialize(plan, session)
    _, runs, build, run = fake_backends(tmp_path, plan)
    def interrupted_copy(source, manifest, destination):
        destination.mkdir()
        (destination / 'partial.txt').write_text('SIMULATED interrupted copy')
        raise OSError('SIMULATED interrupted copying')
    with monkeypatch.context() as changes:
        changes.setattr(bisect, '_copy_package', interrupted_copy)
        with pytest.raises(recipes.ContractError, match='recover'): bisect.step(session, build=build, run=run)
    record = bisect.recover(session, result_path=session / 'results/t0001/result.json')
    assert record['classification'] == 'good' and runs == [0]
    partial = list((session / 'failures').glob('t0001-partial-*'))
    assert len(partial) == 1 and (partial[0] / 'partial.txt').read_text() == 'SIMULATED interrupted copy'
    assert bisect.report(session, tmp_path / 'report')['valid']


@pytest.mark.parametrize('name', ['session.lock', 'cache', 'work'])
def test_session_symlinks_refused_before_any_external_write(tmp_path, name):
    plan = fixture_plan(tmp_path)
    session = tmp_path / 'session'; bisect.initialize(plan, session)
    external = tmp_path / 'external'
    existing = session / name
    if existing.is_dir(): existing.rmdir()
    existing.symlink_to(external)
    with pytest.raises(recipes.ContractError, match='symlink'): bisect.next_trial(session)
    assert not external.exists()


def test_crash_without_exact_worker_clock_anchors_stays_ambiguous(tmp_path):
    plan = fixture_plan(tmp_path, predicate='target_crash')
    _, _, build, run = fake_backends(tmp_path, plan, first_bad=0)
    result_dir = tmp_path / 'result'
    run(plan['recipe'], target=fake_target(plan['candidates'][0]['build_plan']),
        workdir=tmp_path / 'work', results_dir=result_dir, timeout=120, diagnostics='basic')
    budget_path = result_dir / 'work/execution-budget.json'
    budget = json.loads(budget_path.read_text())
    del budget['started_monotonic_s']; del budget['ended_monotonic_s']
    budget_path.write_text(json.dumps(budget)); rehash_result(result_dir / 'result.json')
    assert bisect.classification(plan, 0, result_dir / 'result.json')['classification'] == 'ambiguous'


def test_completed_crash_trial_with_unexplained_absence_cannot_be_good(tmp_path):
    plan = fixture_plan(tmp_path, predicate='target_crash')
    _, _, build, run = fake_backends(tmp_path, plan)
    result_dir = tmp_path / 'result'
    run(plan['recipe'], target=fake_target(plan['candidates'][0]['build_plan']),
        workdir=tmp_path / 'work', results_dir=result_dir, timeout=120, diagnostics='basic')
    live_path = result_dir / 'work/live-diagnostics.json'
    live = json.loads(live_path.read_text())
    live['samples'].append({'role': 'target', 'container_id': 'SIMULATED-container', 'monotonic_s': 11,
                            'bird_process_present': False, 'daemon_exit_code': None, 'errors': []})
    live_path.write_text(json.dumps(live)); rehash_result(result_dir / 'result.json')
    assert bisect.classification(plan, 0, result_dir / 'result.json')['classification'] == 'ambiguous'
