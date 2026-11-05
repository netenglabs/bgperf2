"""Session lifecycle uses modeled workers and real immutable package readers."""
import hashlib
import json
from pathlib import Path
import shutil
import uuid

import pytest

import recipes
import recipe_minimization as core
import recipe_minimization_session as session
from recipe_targets import supplied_target
from test_recipe_comparison_report import package, ROOT


def plan(**kwargs):
    recipe = recipes.read_document(ROOT / 'examples/recipes/synthetic-ipv4.recipe.json')
    recipe['reproduction']['question'] = 'SIMULATED bounded minimization; no real worker'
    return core.make_plan(recipe, assertion='experiment.complete', timeout=120, **kwargs)


def initialize(tmp_path, **kwargs):
    document = plan(**kwargs)
    root = tmp_path / 'session'
    session.init_session(document, workdir=tmp_path / 'work', results_dir=root)
    return root


def fake_runner(tmp_path, *, failed=True, identity=None, after=None):
    calls = []

    def run(recipe, *, workdir, results_dir, target, timeout, diagnostics, observer_prefixes):
        calls.append(recipe)
        assert timeout == 120 and diagnostics == 'basic' and observer_prefixes is False
        assert target == supplied_target(recipe, recipe['roles']['target']['image'])
        workdir.mkdir()
        (workdir / 'partial.log').write_text('SIMULATED retained work')
        failing = failed(recipe, len(calls)) if callable(failed) else failed
        path = package(tmp_path / ('source-' + uuid.uuid4().hex),
                       {'recipe': recipe, 'targets': {'baseline': target}},
                       {'role': 'baseline', 'id': identity or uuid.uuid4().hex},
                       status='experiment_failed' if failing else 'completed')
        result = json.loads(path.read_text())
        runtime = path.parent / 'work/runtime.json'
        value = json.loads(runtime.read_text())
        value['cleanup_errors'] = []
        runtime.write_text(json.dumps(value))
        budget = path.parent / 'work/execution-budget.json'
        value = json.loads(budget.read_text())
        value.update(timeout_seconds=timeout, started_monotonic_s=1, ended_monotonic_s=21)
        budget.write_text(json.dumps(value))
        for artifact in result['artifacts']:
            if artifact['availability'] == 'present':
                artifact['sha256'] = hashlib.sha256((path.parent / artifact['path']).read_bytes()).hexdigest()
        path.write_text(json.dumps(result))
        shutil.copytree(path.parent, results_dir)
        if after:
            after()
        return {'result': str(results_dir / 'result.json')}

    return run, calls


def test_plan_next_status_are_offline_and_read_only(tmp_path):
    root = initialize(tmp_path)
    before = session._inventory(root)
    proposal = session.step_session(root)
    assert proposal['next']['phase'] == 'baseline'
    assert proposal['paths']['result'] == str(root / 'attempts/t0001/result.json')
    assert proposal['argv'][0:2] == ['recipes.py', 'run']
    assert '--observer-prefixes' not in proposal['argv']
    assert session.status_session(root)['trials_reserved'] == 0
    assert session._inventory(root) == before
    assert not Path(proposal['paths']['recipe']).exists()


@pytest.mark.parametrize('execute', ['false', 0, 1, None])
def test_mistyped_execution_cannot_reserve_or_launch(tmp_path, execute):
    root = initialize(tmp_path)
    before = session._inventory(root)
    with pytest.raises(recipes.ContractError, match='explicit boolean'):
        session.step_session(root, execute=execute,
                             run=lambda *a, **k: pytest.fail('worker must not run'))
    assert session._inventory(root) == before


def test_one_step_and_distinct_fresh_confirmation(tmp_path):
    root = initialize(tmp_path, max_trials=4)
    run, calls = fake_runner(tmp_path)
    state = session.step_session(root, execute=True, run=run)
    assert len(calls) == 1 and state['trials_recorded'] == 1
    while state['next']:
        state = session.step_session(root, execute=True, run=run)
    assert state['confirmed'] and state['conclusion'] == 'confirmed_smaller'
    records = [json.loads(path.read_text()) for path in sorted((root / 'trials').iterdir())]
    assert records[-1]['request']['phase'] == 'confirmation'
    assert len({record['assessment']['attempt_id'] for record in records}) == len(records)
    assert len(calls) <= 4


def test_nonreproduced_original_stops_successors(tmp_path):
    root = initialize(tmp_path)
    run, calls = fake_runner(tmp_path, failed=False)
    status = session.step_session(root, execute=True, run=run)
    assert status['conclusion'] == 'original_not_reproduced'
    assert status['next'] is None and len(calls) == 1
    with pytest.raises(recipes.ContractError, match='terminal'):
        session.reserve_trial(root)


def test_interrupted_worker_requires_explicit_verified_recovery(tmp_path):
    root = initialize(tmp_path)

    def interrupt():
        raise KeyboardInterrupt('SIMULATED stop after package publication')

    run, calls = fake_runner(tmp_path, after=interrupt)
    with pytest.raises(KeyboardInterrupt):
        session.step_session(root, execute=True, run=run)
    before = session._inventory(root)
    status = session.status_session(root)
    assert status['state'] == 'recovery_required' and status['trials_reserved'] == 1
    assert status['next'] is None and session._inventory(root) == before
    with pytest.raises(recipes.ContractError, match='Pending'):
        session.step_session(root, execute=True, run=run)
    assert len(calls) == 1
    assert session.recover_trial(root)['trials_recorded'] == 1
    assert len(calls) == 1 and not (root / 'pending.json').exists()


def test_missing_or_alternate_pending_result_never_clears_reservation(tmp_path):
    root = initialize(tmp_path)
    reserved = session.reserve_trial(root)
    with pytest.raises((recipes.ContractError, OSError)):
        session.recover_trial(root)
    with pytest.raises(recipes.ContractError, match='exact pending'):
        session.record_trial(root, result=tmp_path / 'other/result.json')
    assert session.status_session(root)['pending'] == reserved['next']


def test_duplicate_original_is_refused_and_pending_retained(tmp_path):
    # Dimensions already at their floor go directly to same-shape confirmation.
    original = plan()['recipe']['resolved']
    root = initialize(tmp_path, min_peers=original['neighbors'], min_routes=original['prefixes_per_peer'])
    run, _ = fake_runner(tmp_path, identity='same-original')
    session.step_session(root, execute=True, run=run)
    with pytest.raises(recipes.ContractError, match='distinct original'):
        session.step_session(root, execute=True, run=run)
    status = session.status_session(root)
    assert status['trials_recorded'] == 1 and status['trials_reserved'] == 1


def test_fresh_failed_confirmation_has_distinct_conclusion(tmp_path):
    root = initialize(tmp_path, max_trials=3)
    run, _ = fake_runner(tmp_path, failed=lambda recipe, count: count < 3)
    for _ in range(3):
        status = session.step_session(root, execute=True, run=run)
    assert status['conclusion'] == 'confirmation_not_preserved'
    assert status['confirmed'] is False


def test_journaled_pending_recovery_only_clears_marker(tmp_path):
    root = initialize(tmp_path)
    run, _ = fake_runner(tmp_path)
    session.step_session(root, execute=True, run=run)
    record = json.loads((root / 'trials/t0001.json').read_text())
    session._write(root / 'pending.json', record['request'])
    before = session._inventory(root)
    assert session.status_session(root)['pending_already_recorded']
    assert session._inventory(root) == before
    recovered = session.recover_trial(root)
    assert recovered['trials_recorded'] == 1 and recovered['trials_reserved'] == 0


def test_worker_holds_session_lock(tmp_path):
    root = initialize(tmp_path)

    def inspect_lock():
        with pytest.raises(recipes.ContractError, match='already active'):
            session.reserve_trial(root)

    run, _ = fake_runner(tmp_path, after=inspect_lock)
    session.step_session(root, execute=True, run=run)


def test_report_reconstructs_after_relocation_and_refuses_rehashed_prose(tmp_path):
    root = initialize(tmp_path, max_trials=3)
    run, _ = fake_runner(tmp_path)
    while session.status_session(root)['next']:
        session.step_session(root, execute=True, run=run)
    output = tmp_path / 'report'
    document = session.report(root, output_dir=output)
    root.rename(tmp_path / 'absent-session')
    output.rename(tmp_path / 'relocated')
    output = tmp_path / 'relocated'
    assert session.verify_report(output)['status'] == document['status']
    session.rebuild_report(output, output_dir=tmp_path / 'rebuilt')
    assert session.verify_report(tmp_path / 'rebuilt')['valid']
    (output / 'REPORT.md').write_text('A global minimum was established.')
    checksums = session._load(output / 'checksums.json')
    checksums['files'] = [item for item in session._inventory(output) if item['path'] != 'checksums.json']
    (output / 'checksums.json').write_text(json.dumps(checksums))
    with pytest.raises(recipes.ContractError, match='prose'):
        session.verify_report(output)


def test_pending_report_is_read_only_and_cannot_create_confirmation(tmp_path):
    root = initialize(tmp_path)
    session.reserve_trial(root)
    before = session._inventory(root)
    report = session.report(root, output_dir=tmp_path / 'pending-report')
    assert report['status']['state'] == 'recovery_required'
    assert report['status']['trials_reserved'] == 1 and not report['status']['confirmed']
    assert session._inventory(root) == before


def test_changed_recorded_package_and_symlink_are_refused(tmp_path):
    root = initialize(tmp_path)
    run, _ = fake_runner(tmp_path)
    session.step_session(root, execute=True, run=run)
    raw = root / 'evidence/t0001/work/runtime.json'
    raw.write_text('{}')
    with pytest.raises(recipes.ContractError):
        session.status_session(root)
    (root / 'plan.json').rename(root / 'saved-plan.json')
    (root / 'plan.json').symlink_to(root / 'saved-plan.json')
    with pytest.raises(recipes.ContractError, match='symlink'):
        session.status_session(root)


def test_partial_preparation_remains_visible_and_charged(tmp_path, monkeypatch):
    root = initialize(tmp_path)
    original = session._write
    writes = []

    def fail_control(path, document):
        writes.append(path)
        if len(writes) == 3:  # pending + first proposal published; second proposal interrupted
            Path(path).write_bytes(b'{"SIMULATED truncated":')
            raise OSError('SIMULATED disk error')
        return original(path, document)

    monkeypatch.setattr(session, '_write', fail_control)
    with pytest.raises(OSError, match='disk error'):
        session.reserve_trial(root)
    monkeypatch.setattr(session, '_write', original)
    assert (root / 'proposals/t0001/recipe.json').exists()
    assert not (root / 'proposals/t0001/assertions.json').exists()
    assert not (root / 'proposals/t0001/target.json').exists()
    retained = list((root / 'unpublished').iterdir())
    assert len(retained) == 1 and retained[0].read_bytes() == b'{"SIMULATED truncated":'
    assert session.status_session(root)['trials_reserved'] == 1
    assert session.next_trial(root)['state'] == 'recovery_required'
    output = tmp_path / 'interrupted-proposal-report'
    assert session.report(root, output_dir=output)['status']['trials_reserved'] == 1
    assert session.verify_report(output)['valid']
    with pytest.raises((recipes.ContractError, OSError)):
        session.recover_trial(root)  # No original package exists; never relaunch.
    with pytest.raises(recipes.ContractError, match='Pending'):
        session.reserve_trial(root)
    request = session.status_session(root)['pending']
    proposal = session._proposal(session._load(root / 'plan.json'), request)
    paths = session._paths(root, session._config(root), request)
    run, calls = fake_runner(tmp_path)
    run(proposal['recipe'], workdir=Path(paths['workdir']), results_dir=Path(paths['results_dir']),
        target=proposal['target'], timeout=120, diagnostics='basic', observer_prefixes=False)
    assert session.recover_trial(root)['trials_recorded'] == 1
    assert len(calls) == 1
    assert sorted(p.name for p in (root / 'proposals/t0001').iterdir()) == ['assertions.json', 'recipe.json', 'target.json']
    assert retained[0].read_bytes() == b'{"SIMULATED truncated":'


def test_report_materializes_stored_evidence_without_rewriting_original_manifest(tmp_path, monkeypatch):
    monkeypatch.setenv('BGPERF_ARTIFACT_STORE', str(tmp_path / 'store'))
    root = initialize(tmp_path)
    run, _ = fake_runner(tmp_path)
    session.step_session(root, execute=True, run=run)
    record = session._load(root / 'trials/t0001.json')
    original = (root / 'attempts/t0001/result.json').read_bytes()
    assert hashlib.sha256(original).hexdigest() == record['assessment']['result_sha256']
    output = tmp_path / 'portable-report'
    session.report(root, output_dir=output)
    assert (output / 'session/evidence/t0001/result.json').read_bytes() == original
    (tmp_path / 'store').rename(tmp_path / 'absent-store')
    root.rename(tmp_path / 'absent-session')
    monkeypatch.delenv('BGPERF_ARTIFACT_STORE')
    assert session.verify_report(output)['valid']


def test_verified_pending_package_is_bundled_without_promoting_observation(tmp_path):
    root = initialize(tmp_path)
    reserved = session.reserve_trial(root)
    run, _ = fake_runner(tmp_path)
    run(reserved['recipe'], workdir=Path(reserved['paths']['workdir']),
        results_dir=Path(reserved['paths']['results_dir']), target=reserved['target'],
        timeout=120, diagnostics='basic', observer_prefixes=False)
    output = tmp_path / 'pending-report'
    document = session.report(root, output_dir=output)
    assert document['pending_evidence']['availability'] == 'present'
    assert document['pending_evidence']['assessment']['classification'] == 'preserved'
    assert document['status']['trials_recorded'] == 0
    assert document['status']['trials_reserved'] == 1 and not document['status']['confirmed']
    original = Path(reserved['paths']['result']).read_bytes()
    assert (output / 'pending/result.json').read_bytes() == original
    root.rename(tmp_path / 'absent-session')
    assert session.verify_report(output)['valid']
    session.rebuild_report(output, output_dir=tmp_path / 'rebuilt-pending')
    rebuilt = session._load(tmp_path / 'rebuilt-pending/minimization.json')
    assert rebuilt == document


def test_relocated_session_is_read_only_execution_authority(tmp_path):
    root = initialize(tmp_path)
    copied = tmp_path / 'copied'
    shutil.copytree(root, copied)
    assert session.status_session(copied)['state'] == 'ready'
    assert session.next_trial(copied)['next']['phase'] == 'baseline'
    with pytest.raises(recipes.ContractError, match='original session root'):
        session.reserve_trial(copied)
    with pytest.raises(recipes.ContractError, match='original session root'):
        session.recover_trial(copied)


def collected(tmp_path, document):
    recipe = document['recipe']
    run, _ = fake_runner(tmp_path)
    work, results = tmp_path / ('work-' + uuid.uuid4().hex), tmp_path / ('results-' + uuid.uuid4().hex)
    run(recipe, workdir=work, results_dir=results,
        target=supplied_target(recipe, recipe['roles']['target']['image']),
        timeout=document['timeout'], diagnostics='basic', observer_prefixes=False)
    return results / 'result.json'


def change_artifact(path, relative, update):
    artifact = path.parent / relative
    value = json.loads(artifact.read_text())
    update(value)
    artifact.write_text(json.dumps(value))
    manifest = json.loads(path.read_text())
    for item in manifest['artifacts']:
        if item['path'] == relative:
            item['sha256'] = hashlib.sha256(artifact.read_bytes()).hexdigest()
    path.write_text(json.dumps(manifest))


@pytest.mark.parametrize('change', ['wrong_timeout', 'invalid_anchors', 'cleanup_failed', 'harness_failed', 'missing_image'])
def test_operational_uncertainty_cannot_preserve_observed_selected_failure(tmp_path, change):
    document = plan()
    path = collected(tmp_path, document)
    assert core.classify_result(document, document['recipe'], path)['classification'] == 'preserved'
    if change == 'wrong_timeout':
        change_artifact(path, 'work/execution-budget.json', lambda d: d.update(timeout_seconds=119))
    elif change == 'invalid_anchors':
        change_artifact(path, 'work/execution-budget.json', lambda d: d.update(ended_monotonic_s=2))
    elif change == 'cleanup_failed':
        change_artifact(path, 'work/runtime.json', lambda d: d.update(cleanup_errors=['SIMULATED owned resource remains']))
    elif change == 'missing_image':
        change_artifact(path, 'work/prerequisites.json', lambda d: d['checks'][0]['details'].pop('image_id'))
    else:
        manifest = json.loads(path.read_text())
        manifest.update(status='harness_failed', exit_code=3)
        path.write_text(json.dumps(manifest))
    assessment = core.classify_result(document, document['recipe'], path)
    assert assessment['assertion']['status'] == 'failed'
    assert assessment['classification'] == 'inconclusive'
    if change == 'missing_image':
        assert None in assessment['observed_images'].values()


def test_unmeasured_selected_assertion_does_not_inherit_other_failure(tmp_path):
    document = core.make_plan(plan()['recipe'], assertion='observer.count', timeout=120)
    path = collected(tmp_path, document)
    # The engine completion assertion failed, but observer count initially passed.
    assert core.classify_result(document, document['recipe'], path)['classification'] == 'not_preserved'
    change_artifact(path, 'work/raw-events.json', lambda d: d.update(events=[]))
    assessment = core.classify_result(document, document['recipe'], path)
    assert assessment['assertion']['status'] == 'unmeasured'
    assert assessment['classification'] == 'inconclusive'


def test_same_repository_pin_cannot_change_physical_image_between_trials(tmp_path):
    recipe = plan()['recipe']
    repository_pin = 'example.invalid/bird@sha256:' + 'f' * 64
    recipe['roles']['target']['image'] = repository_pin
    document = core.make_plan(recipe, assertion='experiment.complete', timeout=120,
                              min_peers=recipe['resolved']['neighbors'], min_routes=recipe['resolved']['prefixes_per_peer'])
    records = []
    for digit in ('a', 'b'):
        request = core.summarize(document, records)['next']
        path = collected(tmp_path, document)

        def physical_identity(value):
            for check in value['checks']:
                if check['name'] == 'image.target':
                    check['details'].update(image_id='sha256:' + digit * 64, repo_digests=[repository_pin])

        change_artifact(path, 'work/prerequisites.json', physical_identity)
        assessment = core.classify_result(document, recipe, path)
        assert assessment['classification'] == 'preserved'
        record = {'request': request, 'assessment': assessment}
        if records:
            with pytest.raises(recipes.ContractError, match='changed from baseline'):
                core.summarize(document, records + [record])
        else:
            records.append(record)


@pytest.mark.parametrize('refusal', ['prerequisites', 'host_busy'])
def test_known_pre_execution_refusal_closes_charged_session_and_has_portable_receipt(tmp_path, refusal):
    from recipe_run import RecipeNotStarted
    root = initialize(tmp_path)
    calls = []

    def never_started(*args, **kwargs):
        calls.append(kwargs)
        assert not kwargs['workdir'].exists() and not kwargs['results_dir'].exists()
        if refusal == 'host_busy':
            raise RecipeNotStarted('SIMULATED cooperating host lock is busy')
        return {'status': 'setup_refused', 'exit_code': 2,
                'reason': 'Prerequisites refused; no attempt was started.',
                'prerequisites': {'status': 'refused', 'checks': [
                    {'name': 'tool.mpstat', 'status': 'refused', 'reason': 'SIMULATED missing prerequisite'}]}}

    status = session.step_session(root, execute=True, run=never_started)
    assert len(calls) == 1
    assert status['state'] == status['conclusion'] == 'operational_refused'
    assert status['trials_reserved'] == 1 and status['trials_recorded'] == 0
    assert status['next'] is None and not status['confirmed']
    assert 'fresh session' in status['recovery_instruction']
    assert status['controller_stop']['kind'] == ('host_busy' if refusal == 'host_busy' else 'setup_refused')
    with pytest.raises(recipes.ContractError, match='closed this session'):
        session.recover_trial(root)
    with pytest.raises(recipes.ContractError):
        session.step_session(root, execute=True, run=never_started)
    assert len(calls) == 1
    output = tmp_path / 'refused-report'
    report = session.report(root, output_dir=output)
    assert report['status'] == status
    assert (output / 'session/controller-stop.json').read_bytes() == (root / 'controller-stop.json').read_bytes()
    root.rename(tmp_path / 'retained-refused-session')
    assert session.verify_report(output)['status'] == status
    assert 'No attempt started' in (output / 'REPORT.md').read_text()
    assert 'partial original work' not in (output / 'REPORT.md').read_text().lower()
    assert report['pending_evidence']['reason'].startswith('Known pre-execution refusal')
    session.rebuild_report(output, output_dir=tmp_path / 'refused-rebuilt')
    assert session.verify_report(tmp_path / 'refused-rebuilt')['status'] == status


@pytest.mark.parametrize('interruption', ['staging_copy', 'legacy_partial', 'journal_publication'])
def test_interrupted_snapshot_can_recover_original_without_worker_retry(tmp_path, monkeypatch, interruption):
    import recipe_investigation
    root = initialize(tmp_path)
    run, calls = fake_runner(tmp_path)
    original_copy = recipe_investigation._copy_package
    copies = []
    publish = session._publish

    def interrupted_copy(source, result, destination):
        copies.append(destination)
        if len(copies) == 1 and interruption == 'staging_copy':
            destination.mkdir()
            (destination / 'retained-partial').write_bytes(b'SIMULATED interrupted copy')
            raise OSError('SIMULATED interrupted copy')
        original_copy(source, result, destination)

    def interrupted_journal(path, relative, document):
        if relative.startswith('trials/') and interruption == 'journal_publication':
            raise OSError('SIMULATED interrupted journal publication')
        return publish(path, relative, document)

    monkeypatch.setattr(recipe_investigation, '_copy_package', interrupted_copy)
    monkeypatch.setattr(session, '_publish', interrupted_journal)
    if interruption == 'legacy_partial':
        reserved = session.reserve_trial(root)
        run(reserved['recipe'], workdir=Path(reserved['paths']['workdir']),
            results_dir=Path(reserved['paths']['results_dir']), target=reserved['target'],
            timeout=120, diagnostics='basic', observer_prefixes=False)
        legacy = root / 'evidence/t0001'
        legacy.mkdir()
        (legacy / 'retained-partial').write_bytes(b'SIMULATED legacy partial snapshot')
    else:
        with pytest.raises(OSError, match='SIMULATED interrupted'):
            session.step_session(root, execute=True, run=run)
    assert len(calls) == 1
    assert session.status_session(root)['state'] == 'recovery_required'
    monkeypatch.setattr(session, '_publish', publish)
    recovered = session.recover_trial(root)
    assert recovered['trials_recorded'] == 1 and recovered['trials_reserved'] == 0
    assert len(calls) == 1
    if interruption == 'journal_publication':
        assert len(copies) == 1  # Reuse only the complete independently verified copy.
    else:
        retained = list((root / 'snapshots').rglob('retained-partial'))
        assert len(retained) == 1 and retained[0].read_bytes().startswith(b'SIMULATED')


def test_readers_refuse_snapshot_during_mutating_worker(tmp_path):
    root = initialize(tmp_path)

    def concurrent_reads():
        for read in (session.next_trial, session.status_session, lambda p: session.step_session(p, execute=False),
                     lambda p: session.report(p, output_dir=tmp_path / 'racing-report')):
            with pytest.raises(recipes.ContractError, match='already active'):
                read(root)
        assert not (tmp_path / 'racing-report').exists()

    run, _ = fake_runner(tmp_path, after=concurrent_reads)
    assert session.step_session(root, execute=True, run=run)['trials_recorded'] == 1


@pytest.mark.parametrize('invalid', [None, [], {}, {'results_dir': '/tmp'},
    {'schema': session.SCHEMA, 'workdir': None, 'results_dir': '/tmp/example-result', 'plan_sha256': 'a' * 64},
    {'schema': session.SCHEMA, 'workdir': '/tmp/example-work', 'results_dir': [], 'plan_sha256': 'a' * 64},
    {'schema': session.SCHEMA, 'workdir': '/tmp/example-work', 'results_dir': '/tmp/example-result', 'plan_sha256': None}])
def test_malformed_session_configuration_is_contract_refusal_without_mutation(tmp_path, invalid, capsys):
    import minimization_cli
    root = initialize(tmp_path)
    (root / 'session.json').write_text(json.dumps(invalid))
    before = session._inventory(root)
    for operation in (session.status_session, session.next_trial, session.reserve_trial, session.recover_trial):
        with pytest.raises(recipes.ContractError):
            operation(root)
    for command in ('status', 'next', 'reserve', 'recover'):
        assert minimization_cli.main([command, str(root)]) == 2
        assert 'minimization:' in capsys.readouterr().err
    assert session._inventory(root) == before
