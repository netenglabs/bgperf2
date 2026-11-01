"""Interrupted control-record publication preserves originals and permits recovery."""
from pathlib import Path

import pytest

import recipe_bisection as bisection
from test_recipe_bisection import fixture_plan, fake_backends


def prepared(tmp_path, **options):
    plan = fixture_plan(tmp_path)
    session = tmp_path / 'session'
    bisection.initialize(plan, session)
    builds, runs, build, run = fake_backends(tmp_path, plan, **options)
    return session, plan, builds, runs, build, run


@pytest.mark.parametrize('fault', ['partial_stage', 'before_publication', 'after_publication'])
def test_journal_interruption_recovers_original_without_another_worker(tmp_path, monkeypatch, fault):
    session, plan, builds, runs, build, run = prepared(tmp_path)
    real_write, real_link, real_unlink = bisection.write, bisection.os.link, Path.unlink

    def write(path, value):
        if fault == 'partial_stage' and 'request' in value and path.parent.name == 'unpublished':
            path.write_text('{"incomplete":')
            raise OSError('SIMULATED partial staging write')
        return real_write(path, value)

    def link(source, destination, **kwargs):
        if fault == 'before_publication' and Path(destination).parent.name == 'trials':
            raise OSError('SIMULATED interrupted publication')
        return real_link(source, destination, **kwargs)

    def unlink(path, *args, **kwargs):
        if (fault == 'after_publication' and path.parent.name == 'unpublished'
                and path.name.startswith('t0001.json-')):
            raise OSError('SIMULATED interruption after publication')
        return real_unlink(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(bisection, 'write', write)
        patch.setattr(bisection.os, 'link', link)
        patch.setattr(Path, 'unlink', unlink)
        with pytest.raises(bisection.recipes.ContractError, match='recover'):
            bisection.step(session, build=build, run=run)
    assert builds == runs == [0]
    original = session / 'results/t0001/result.json'
    original_bytes = original.read_bytes()
    staged = {p.name: p.read_bytes() for p in (session / 'failures/unpublished').iterdir()}
    assert len(staged) == 1
    status = bisection.session_status(session)
    assert status['conclusion']['state'] == 'recovery_required'
    assert status['pending_already_recorded'] is (fault == 'after_publication')
    recovered = bisection.recover(session, result_path=original)
    assert recovered.get('classification', recovered.get('state')) in ('good', 'reservation_reconciled')
    assert builds == runs == [0] and original.read_bytes() == original_bytes
    assert bisection.session_status(session)['trials_recorded'] == 1
    assert {p.name: p.read_bytes() for p in (session / 'failures/unpublished').iterdir()} == staged
    output = tmp_path / 'report'
    assert bisection.report(session, output)['valid']
    assert {p.name: p.read_bytes() for p in (output / 'failures/unpublished').iterdir()} == staged


def test_incomplete_reservation_publication_starts_no_build_or_worker(tmp_path, monkeypatch):
    session, plan, builds, runs, build, run = prepared(tmp_path)
    real_write = bisection.write

    def partial(path, value):
        if path.name.startswith('pending.json-'):
            path.write_text('{"partial":')
            raise OSError('SIMULATED interrupted reservation')
        return real_write(path, value)

    with monkeypatch.context() as patch:
        patch.setattr(bisection, 'write', partial)
        with pytest.raises(OSError, match='reservation'):
            bisection.step(session, build=build, run=run)
    assert builds == runs == [] and not (session / 'pending.json').exists()
    status = bisection.session_status(session)
    assert status['trials_recorded'] == 0 and status['conclusion']['state'] == 'trial_required'
    assert list((session / 'failures/unpublished').iterdir())


def test_publication_never_overwrites_an_existing_record(tmp_path):
    session, *_ = prepared(tmp_path)
    destination = session / 'trials/t0001.json'
    destination.write_bytes(b'original immutable evidence\n')
    with pytest.raises(FileExistsError):
        bisection._publish_record(session, 'trials/t0001.json', {'replacement': 'refused'})
    assert destination.read_bytes() == b'original immutable evidence\n'
    assert len(list((session / 'failures/unpublished').iterdir())) == 1


def test_supplied_result_cannot_override_an_already_published_failure(tmp_path, monkeypatch):
    session, plan, builds, runs, build, run = prepared(tmp_path, skips=(0,))
    real_publish = bisection._publish_record

    def interrupted(path, relative, document):
        if relative.startswith('trials/'):
            raise OSError('SIMULATED stop after failure publication')
        return real_publish(path, relative, document)

    with monkeypatch.context() as patch:
        patch.setattr(bisection, '_publish_record', interrupted)
        with pytest.raises(OSError):
            bisection.step(session, build=build, run=run)
    failure = session / 'failures/t0001.json'
    before = failure.read_bytes()
    # A separately supplied valid package is not the trial whose build failed.
    from test_recipe_bisection import fake_target
    external = tmp_path / 'external-result'
    run(plan['recipe'], target=fake_target(plan['candidates'][0]['build_plan']),
        workdir=tmp_path / 'external-work', results_dir=external, timeout=120, diagnostics='basic')
    recovered = bisection.recover(session, result_path=external / 'result.json')
    assert recovered['classification'] == 'skipped' and recovered['result'] is None
    assert failure.read_bytes() == before
    assert bisection.session_status(session)['counts'] == dict(good=0, bad=0, skipped=1, ambiguous=0)
    assert bisection.report(session, tmp_path / 'report')['valid']
