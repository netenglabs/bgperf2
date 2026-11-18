"""Whole native matrices and explicit recovery, with no Docker or measurements."""
import copy
import csv
import fcntl
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

import bgperf2 as engine
import native_batch as batch


class HardLoss(BaseException):
    pass


@pytest.fixture
def model(tmp_path, monkeypatch):
    config = tmp_path / 'comparison.yaml'
    targets = [dict(name='bird', label=name, image='sha256:'+'0'*64,
                    generator_image='sha256:'+'1'*64, observer_image='sha256:'+'2'*64) for name in ('first','second')]
    config.write_text(yaml.safe_dump(dict(tests=[dict(name='comparison',neighbors=[1],prefixes=[10],
        filter_test=['None'],targets=targets,repetitions=3)])))
    args = engine.create_args_parser().parse_args(['-d',str(tmp_path/'work'),'batch','-c',str(config),
                                                  '--results-dir',str(tmp_path/'results'),'--calibrate','--defer-graphs'])
    calls=[]; reports=[]; actual_report=engine.report_batch_from_cell_results
    monkeypatch.setattr(engine,'install_stop_handlers',lambda:None)
    monkeypatch.setattr(engine,'stop_signal',SimpleNamespace(is_set=lambda:False))
    monkeypatch.setattr(engine,'tool_revision',lambda:'frozen-engine')
    for name in ('check_batch_images','check_batch_monitor_images','check_batch_pin_and_repeat'):
        monkeypatch.setattr(engine,name,lambda *a:None)
    monkeypatch.setattr(engine,'report_batch_from_cell_results',lambda *a:reports.append(a))
    def native(selected, status='completed', error=None):
        attempt=selected.native_attempt_id;root=Path(selected.results_dir);work=Path(selected.dir)/attempt
        work.mkdir(parents=True);(root/attempt).mkdir()
        row=[1]*len(engine.stats_header().split(','));row[0]=engine.run_name(selected)
        row[[h.strip() for h in engine.stats_header().split(',')].index('failed')]=''
        document=batch.native_mrt.synthetic_spec(selected)
        receipt=dict(schema='bgperf2/native-result/v1',attempt_id=attempt,cell_id=selected.native_cell_id,storage_flushed=True,
            status=status,work=str(work),artifacts=str(root/attempt),error=error,
            images=dict(target=selected.image,generator=selected.generator_image,observer=selected.observer_image),
            workload_sha256=batch.native_mrt.recipes.recipe_sha256(document),row=row,
            identity=dict(missing_count=0,unexpected_count=0),offering=[dict(producer=attempt+'_generator')])
        engine.atomic_write_json(str(root/(attempt+'.native.json')),receipt)
        engine.atomic_write_json(str(work/'cleanup.json'),dict(attempt_id=attempt,errors=[]))
        return row
    def run(runtime,selected):
        calls.append((selected.label,selected.repetition));return native(selected)
    monkeypatch.setattr(batch.native_mrt,'bench',run)
    monkeypatch.setattr(batch,'recover_owned',lambda e,r,a,**kw:str(kw.get('destination','preserved-'+a)))
    def state():return batch.read(Path(args.results_dir)/'native-batch.json')
    return SimpleNamespace(args=args,calls=calls,reports=reports,native=native,state=state,run=run,actual_report=actual_report)


def test_one_invocation_calibrates_whole_matrix_and_resume_never_repeats(model):
    engine.batch(model.args)
    assert model.calls[:2]==[('first',None),('second',None)]
    assert model.calls[2:]==[('first',1),('second',1),('first',2),('second',2),('first',3),('second',3)]
    state=model.state();assert state['status']=='completed' and len(state['cells'])==8
    assert len(engine.load_batch_cell_results(model.args.results_dir,'comparison'))==6
    assert all(len(c['attempts'])==1 for c in state['cells'].values())
    before={p.name:batch.digest(p) for p in Path(model.args.results_dir).glob('*.native.json')}
    model.args.resume=True;engine.batch(model.args)
    assert len(model.calls)==8
    assert before=={p.name:batch.digest(p) for p in Path(model.args.results_dir).glob('*.native.json')}


def test_failed_calibration_blocks_only_its_own_repetitions(model,monkeypatch):
    def run(runtime,selected):
        model.calls.append((selected.label,selected.repetition))
        if selected.label=='first':
            model.native(selected,'failed','offering witness absent');raise ValueError('offering witness absent')
        return model.native(selected)
    monkeypatch.setattr(batch.native_mrt,'bench',run)
    engine.batch(model.args);state=model.state()
    assert state['status']=='completed_with_dispositions'
    assert [s for s in model.calls if s[0]=='first']==[('first',None)]
    assert sum(c['status']=='blocked' for c in state['cells'].values())==3
    assert len(engine.load_batch_cell_results(model.args.results_dir,'comparison'))==3
    model.args.resume=True;engine.batch(model.args);assert len(model.calls)==5


@pytest.mark.parametrize('loss', ['graceful','hard','after_receipt'])
def test_explicit_resume_retains_interruption_and_adopts_completed_receipt(model,monkeypatch,loss):
    def interrupted(runtime,selected):
        model.calls.append((selected.label,selected.repetition))
        if len(model.calls)!=2:return model.native(selected)
        model.native(selected,'completed' if loss=='after_receipt' else 'stopped' if loss=='graceful' else 'running')
        if loss=='graceful':raise engine.StopRequested('SIGTERM')
        raise HardLoss()
    monkeypatch.setattr(batch.native_mrt,'bench',interrupted)
    with pytest.raises((HardLoss,engine.StopRequested)):engine.batch(model.args)
    stopped=model.state();assert stopped['status']=='stopped'
    originals={p.name:batch.digest(p) for p in Path(model.args.results_dir).glob('*.native.json')}
    monkeypatch.setattr(batch.native_mrt,'bench',model.run)
    model.args.resume=True;engine.batch(model.args);state=model.state()
    assert state['status']=='completed'
    assert all(batch.digest(Path(model.args.results_dir)/name)==sha for name,sha in originals.items())
    assert len(model.calls)==(8 if loss=='after_receipt' else 9)
    attempts=[c['attempts'] for c in state['cells'].values()]
    if loss!='after_receipt':
        assert sum(len(a)==2 for a in attempts)==1
        assert any(a[0]['status']=='interrupted' and a[0]['recovery'] for a in attempts if len(a)==2)


def test_ordinary_failed_measurement_is_retained_not_retried(model,monkeypatch):
    def run(runtime,selected):
        model.calls.append((selected.label,selected.repetition))
        if selected.label=='first' and selected.repetition==1:
            model.native(selected,'failed','identity mismatch');raise ValueError('identity mismatch')
        return model.native(selected)
    monkeypatch.setattr(batch.native_mrt,'bench',run)
    engine.batch(model.args);state=model.state()
    failed=[c for c in state['cells'].values() if c['status']=='failed'];assert len(failed)==1
    row=failed[0]['row'];header=[h.strip() for h in engine.stats_header().split(',')]
    assert row[header.index('elapsed (s)')] is None and row[header.index('max mem (GB)')] is None
    assert row[header.index('failed')]=='FAILED'
    model.args.resume=True;engine.batch(model.args);assert len(model.calls)==8


def test_cleanup_uncertainty_stops_independent_successors(model,monkeypatch):
    def run(runtime,selected):
        model.calls.append((selected.label,selected.repetition));model.native(selected,'failed','offering')
        engine.atomic_write_json(str(Path(selected.dir)/selected.native_attempt_id/'cleanup.json'),
            dict(attempt_id=selected.native_attempt_id,errors=['container retained']))
        raise ValueError('offering')
    monkeypatch.setattr(batch.native_mrt,'bench',run)
    with pytest.raises(ValueError,match='cleanup'):engine.batch(model.args)
    assert len(model.calls)==1 and model.state()['status']=='stopped'
    model.args.resume=True
    with pytest.raises(ValueError,match='Unresolved'):engine.batch(model.args)
    assert len(model.calls)==1


def test_status_never_probes_or_mutates_and_changed_definition_refuses(model,monkeypatch,capsys):
    engine.batch(model.args);before=batch.digest(Path(model.args.results_dir)/'native-batch.json')
    monkeypatch.setattr(engine,'check_batch_images',lambda *a:pytest.fail('Read-only status probed images'))
    monkeypatch.setattr(engine,'sweep_stale_temp_files',lambda *a:pytest.fail('Read-only status removed evidence'))
    model.args.batch_status=True;capsys.readouterr();engine.batch(model.args)
    assert json.loads(capsys.readouterr().out)['counts']['completed']==8
    assert batch.digest(Path(model.args.results_dir)/'native-batch.json')==before
    config=Path(model.args.batch_config);config.write_text(config.read_text().replace('prefixes:\n  - 10','prefixes:\n  - 11'))
    # Change parsed YAML explicitly, independent of its emitted indentation.
    value=yaml.safe_load(config.read_text());value['tests'][0]['prefixes']=[11];config.write_text(yaml.safe_dump(value))
    with pytest.raises(ValueError,match='definition differs'):engine.batch(model.args)
    model.args.batch_config=None;engine.batch(model.args)
    assert json.loads(capsys.readouterr().out)['counts']['completed']==8


def test_offline_plan_counts_calibrations_without_runtime_or_result_creation(model,monkeypatch,capsys):
    monkeypatch.setattr(batch.native_mrt,'synthetic_spec',lambda *a:pytest.fail('Planning tried to qualify native input'))
    model.args.list_cells=True;engine.batch(model.args)
    plan=json.loads(capsys.readouterr().out)
    assert plan['maximum_originals']==8 and plan['runtime_qualified'] is False
    assert sum(p['kind']=='calibration' for p in plan['positions'])==2
    assert not Path(model.args.results_dir).exists() and not model.calls


def test_public_status_command_needs_no_yaml_workload_or_docker(model):
    engine.batch(model.args)
    environment=os.environ.copy();environment['DOCKER_HOST']='unix:///definitely/missing/docker.sock'
    environment['MPLCONFIGDIR']='/dev/null'
    before=batch.digest(Path(model.args.results_dir)/'native-batch.json')
    result=subprocess.run([sys.executable,'-B',engine.__file__,'batch','--status',
                           '--results-dir',model.args.results_dir],env=environment,capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr
    status=json.loads(result.stdout)
    assert status['counts']['completed']==8 and status['positions'][0]['kind']=='calibration'
    assert before==batch.digest(Path(model.args.results_dir)/'native-batch.json')


def test_exclusive_lease_and_fresh_results_protect_existing_work(model):
    root=Path(model.args.results_dir);root.mkdir()
    with (root/'.native-batch.lock').open('a') as lock:
        fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        with pytest.raises(ValueError,match='already active'):engine.batch(model.args)
    (root/'old-evidence.json').write_text('retained')
    with pytest.raises(ValueError,match='fresh results'):engine.batch(model.args)
    assert (root/'old-evidence.json').read_text()=='retained'


def test_existing_reports_exclude_calibrations_and_failed_timings(model,monkeypatch):
    monkeypatch.setattr(engine,'report_batch_from_cell_results',model.actual_report)
    def run(runtime,selected):
        if selected.label=='first' and selected.repetition==1:
            model.native(selected,'failed','identity failure');raise ValueError('identity failure')
        return model.native(selected)
    monkeypatch.setattr(batch.native_mrt,'bench',run)
    engine.batch(model.args)
    report=batch.read(Path(model.args.results_dir)/'comparison.summary.json')
    text=json.dumps(report)
    assert 'identity failure' in text and 'calibration:' not in text
    assert len(engine.load_batch_cell_results(model.args.results_dir,'comparison'))==6


def test_report_failure_is_separate_and_manual_resume_never_remeasures(model,monkeypatch):
    def failed_report(*a):raise ValueError('plot failed')
    monkeypatch.setattr(engine,'report_batch_from_cell_results',failed_report)
    with pytest.raises(ValueError,match='plot failed'):engine.batch(model.args)
    state=model.state();assert state['status']=='report_failed' and state['reporting']=='failed'
    assert len(model.calls)==8 and all(c['status']=='completed' for c in state['cells'].values())
    monkeypatch.setattr(engine,'report_batch_from_cell_results',lambda *a:None)
    model.args.resume=True;engine.batch(model.args)
    assert len(model.calls)==8 and model.state()['status']=='completed'
    assert model.state()['reporting']=='completed' and 'report_error' not in model.state()


def test_failed_row_preserves_csv_width_and_empty_text_fields(model,monkeypatch):
    monkeypatch.setattr(engine,'report_batch_from_cell_results',model.actual_report)
    def failed(runtime,selected):
        model.native(selected,'failed','missing capture, got [1, 2]\nno timing')
        raise ValueError('missing capture, got [1, 2]')
    monkeypatch.setattr(batch.native_mrt,'bench',failed)
    model.args.calibrate=False;model.args.durable=True;engine.batch(model.args)
    with (Path(model.args.results_dir)/'comparison.csv').open() as stream:
        rows=list(csv.reader(stream))
    assert all(len(row)==len(rows[0]) for row in rows)
    header=[h.strip() for h in rows[0]]
    assert all(row[header.index('MSG')]=='missing capture; got [1; 2] no timing' for row in rows[1:])
    assert all(row[header.index('filters')]=='' for row in rows[1:])


def test_unverified_success_is_unresolved_not_a_running_original(model,monkeypatch):
    def unverified(runtime,selected):
        row=model.native(selected)
        engine.atomic_write_json(str(Path(selected.dir)/selected.native_attempt_id/'cleanup.json'),
            dict(attempt_id=selected.native_attempt_id,errors=['unverified removal']))
        return row
    monkeypatch.setattr(batch.native_mrt,'bench',unverified)
    with pytest.raises(ValueError,match='cleanup'):engine.batch(model.args)
    state=model.state()
    assert sum(c['status']=='unresolved' for c in state['cells'].values())==1
    assert not any(c['status']=='running' for c in state['cells'].values())
    assert state['reporting']=='failed'


def test_unflushed_completion_never_becomes_a_checkpoint(model,monkeypatch):
    def unflushed(runtime,selected):
        row=model.native(selected)
        path=Path(selected.results_dir)/(selected.native_attempt_id+'.native.json')
        receipt=batch.read(path);receipt.pop('storage_flushed');engine.atomic_write_json(str(path),receipt)
        return row
    monkeypatch.setattr(batch.native_mrt,'bench',unflushed)
    with pytest.raises(ValueError,match='durability'):engine.batch(model.args)
    assert not any(c['status']=='completed' for c in model.state()['cells'].values())
    assert model.state()['status']=='stopped'


def test_resume_uses_saved_work_root_and_preserves_prior_recovery_references(model,monkeypatch):
    def stopped(runtime,selected):
        model.native(selected,'stopped');raise engine.StopRequested('SIGTERM')
    monkeypatch.setattr(batch.native_mrt,'bench',stopped)
    with pytest.raises(engine.StopRequested):engine.batch(model.args)
    state=model.state();entry=next(c for c in state['cells'].values() if c['attempts'])
    entry['attempts'][0]['recovery']='first-preservation'
    engine.atomic_write_json(str(Path(model.args.results_dir)/'native-batch.json'),state)
    monkeypatch.setattr(batch.native_mrt,'bench',model.run)
    model.args.resume=True;model.args.dir=engine.create_args_parser().get_default('dir')
    engine.batch(model.args)
    latest=next(c for c in model.state()['cells'].values() if len(c['attempts'])==2)
    assert latest['attempts'][0]['recoveries'][0]=='first-preservation'
    assert len(latest['attempts'][0]['recoveries'])==2
    assert model.state()['plan']['work_root']!=model.args.dir


def test_real_process_loss_releases_lease_and_preserves_completed_original(model,monkeypatch):
    def killed(runtime,selected):
        model.calls.append((selected.label,selected.repetition))
        row=model.native(selected,'running' if len(model.calls)==2 else 'completed')
        if len(model.calls)==2:os._exit(9)
        return row
    monkeypatch.setattr(batch.native_mrt,'bench',killed)
    child=os.fork()
    if child==0:
        try:engine.batch(model.args)
        finally:os._exit(2)
    _,status=os.waitpid(child,0)
    assert os.waitstatus_to_exitcode(status)==9
    retained=model.state();assert retained['status']=='running'
    before={p.name:batch.digest(p) for p in Path(model.args.results_dir).glob('*.native.json')}
    monkeypatch.setattr(batch.native_mrt,'bench',model.run)
    model.args.resume=True;engine.batch(model.args)
    assert model.state()['status']=='completed'
    assert sum(len(c['attempts']) for c in model.state()['cells'].values())==9
    assert all(batch.digest(Path(model.args.results_dir)/name)==sha for name,sha in before.items())


def test_failed_calibration_without_statistics_does_not_block_independent_daemon(model,monkeypatch):
    def run(runtime,selected):
        if selected.label=='first':
            model.native(selected,'failed','offering witness absent')
            path=Path(selected.results_dir)/(selected.native_attempt_id+'.native.json')
            value=batch.read(path);value['row']=None;engine.atomic_write_json(str(path),value)
            raise ValueError('offering witness absent')
        return model.native(selected)
    monkeypatch.setattr(batch.native_mrt,'bench',run)
    engine.batch(model.args)
    state=model.state();assert state['status']=='completed_with_dispositions'
    assert sum(c['status']=='completed' for c in state['cells'].values())==4
    assert sum(c['status']=='blocked' for c in state['cells'].values())==3


@pytest.mark.parametrize('failure', ['none','logs','shared'])
def test_recovery_preserves_before_deletion_and_never_touches_foreign_objects(tmp_path,monkeypatch,failure):
    attempt='bgperf_bench_'+'a'*32;own='b'*64;foreign='c'*64;events=[];running=True;removed=False;network_removed=False
    def containers(**kw):
        return ([] if removed else [dict(Id=own,Names=['/'+attempt+'_target'])])+[dict(Id=foreign,Names=['/foreign'])]
    def inspect(_):return dict(State=dict(Running=running))
    def network(_):return dict(Containers={foreign:{}} if failure=='shared' else {})
    def stop(cid,**kw):
        nonlocal running
        assert cid==own;events.append('stop');running=False
    def logs(cid,**kw):
        assert not running and kw['follow'] is False;events.append('logs')
        if failure=='logs':raise OSError('log capture failed')
        return [b'retained output']
    def remove(cid,**kw):
        nonlocal removed
        assert cid==own
        receipts=list(tmp_path.glob('recovery/*/preserved.json'));assert len(receipts)==1
        recorded=batch.read(receipts[0]);assert all(batch.digest(receipts[0].parent/name)==sha for name,sha in recorded['files'].items())
        events.append('remove');removed=True
    def remove_network(_):
        nonlocal network_removed
        network_removed=True
    runtime=SimpleNamespace(atomic_write_json=engine.atomic_write_json,dckr=SimpleNamespace(
        containers=containers,networks=lambda **kw:[] if network_removed else [dict(Id='network',Name=attempt+'-br')],
        inspect_network=network,inspect_container=inspect,stop=stop,logs=logs,remove_container=remove,remove_network=remove_network))
    if failure=='none':
        path=Path(batch.recover_owned(runtime,tmp_path,attempt))
        assert (path/(own+'.log')).read_bytes()==b'retained output'
        assert events==['stop','logs','remove'] and removed and network_removed
    else:
        with pytest.raises((ValueError,OSError)):batch.recover_owned(runtime,tmp_path,attempt)
        assert not removed and not network_removed


def managed(model, monkeypatch, *, reject=None, missing=None):
    control=Path(model.args.results_dir).parent/'control';control.mkdir()
    model.args.control_dir=str(control);model.args.operational_policy_sha256='a'*64
    def run(runtime,selected):
        model.run(runtime,selected)
        path=control/selected.native_attempt_id;path.mkdir()
        if selected.label==missing:raise HardLoss()
        review=dict(attempt_id=selected.native_attempt_id,policy_sha256='a'*64,
                    status='rejected' if selected.label==reject else 'passed',reason='modeled resource guard',
                    cohort=dict(cpu_model='simulated',memory_bytes=64*1024**3))
        engine.atomic_write_json(str(path/'operational-review.json'),review)
        engine.atomic_write_json(str(path/'completion-release.json'),dict(attempt_id=selected.native_attempt_id,
            status=review['status'],review_sha256=batch.digest(path/'operational-review.json')))
    monkeypatch.setattr(batch.native_mrt,'bench',run)


def test_managed_batch_requires_and_preserves_operational_qualification(model,monkeypatch):
    managed(model,monkeypatch,reject='first');engine.batch(model.args)
    state=model.state()
    assert len(model.calls)==5
    assert sum(c['status']=='blocked' for c in state['cells'].values())==3
    failed=next(c for c in state['cells'].values() if c['status']=='failed')
    assert failed['attempts'][0]['unqualified_reason'].startswith('operational_policy_rejected')
    assert failed['row'][state['columns'].index('elapsed (s)')] is None
    model.args.resume=True;engine.batch(model.args);assert len(model.calls)==5
    review=next((Path(model.args.results_dir)/'operations').glob('*.json'));review.write_text('{}')
    with pytest.raises(ValueError,match='review changed'):engine.batch(model.args)


def test_recovery_without_host_review_never_adopts_timing_or_launches(model,monkeypatch):
    managed(model,monkeypatch,missing='first')
    with pytest.raises(HardLoss):engine.batch(model.args)
    model.args.recover=True;model.args.control_dir=None;model.args.operational_policy_sha256=None
    engine.batch(model.args);state=model.state()
    assert len(model.calls)==1 and state['status']=='recovered'
    original=next(c for c in state['cells'].values() if c['attempts'])
    assert original['status']=='failed'
    assert original['row'][state['columns'].index('elapsed (s)')] is None
    assert 'missing' in original['attempts'][0]['unqualified_reason']


def test_finite_invocation_resumes_without_repeating_completed_originals(model):
    model.args.maximum_originals=3;engine.batch(model.args)
    assert model.state()['status']=='paused' and len(model.calls)==3
    retained={p.name:batch.digest(p) for p in Path(model.args.results_dir).glob('*.native.json')}
    model.args.resume=True;engine.batch(model.args)
    assert len(model.calls)==6 and model.state()['status']=='paused'
    engine.batch(model.args)
    assert len(model.calls)==8 and model.state()['status']=='completed'
    assert all(batch.digest(Path(model.args.results_dir)/name)==sha for name,sha in retained.items())


def test_recover_only_does_not_require_images_or_run_unrun_positions(model,monkeypatch):
    model.args.maximum_originals=1;engine.batch(model.args)
    monkeypatch.setattr(engine,'check_batch_images',lambda *a:pytest.fail('Recovery probed images'))
    model.args.recover=True;engine.batch(model.args)
    assert len(model.calls)==1 and model.state()['status']=='recovered'


@pytest.mark.parametrize('flag,value',[('maximum_originals',1),('timeout_seconds',10),('operational_policy_sha256','a'*64)])
def test_durable_controls_never_silently_fall_back_to_legacy(model,flag,value):
    model.args.calibrate=False;setattr(model.args,flag,value)
    with pytest.raises(ValueError,match='require --durable'):engine.batch(model.args)
    assert not model.calls


def test_missing_review_can_be_recovered_after_an_unsuccessful_resume(model,monkeypatch):
    managed(model,monkeypatch,missing='first')
    with pytest.raises(HardLoss):engine.batch(model.args)
    model.args.resume=True
    with pytest.raises(batch.MissingOperationalReview):engine.batch(model.args)
    assert next(c for c in model.state()['cells'].values() if c['attempts'])['status']=='interrupted'
    model.args.recover=True;model.args.control_dir=None;model.args.operational_policy_sha256=None
    engine.batch(model.args)
    assert next(c for c in model.state()['cells'].values() if c['attempts'])['status']=='failed'
    assert len(model.calls)==1


def test_relative_control_is_canonicalized_before_native_worker(model,monkeypatch):
    managed(model,monkeypatch)
    original=batch.native_mrt.bench
    model.args.control_dir=os.path.relpath(model.args.control_dir)
    def run(runtime,selected):
        assert Path(selected.control_dir).is_absolute()
        return original(runtime,selected)
    monkeypatch.setattr(batch.native_mrt,'bench',run);engine.batch(model.args)
    assert len(model.calls)==8
