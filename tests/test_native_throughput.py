"""Native throughput controls, offline reconstruction and attempt phase records."""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest

import bgperf2 as engine
import deferred_graphs as graphs
import native_mrt as native
from native_phases import Journal


def test_list_cells_is_offline_and_preserves_legacy_keys(tmp_path):
    config=tmp_path/'batch.yaml'
    config.write_text('tests:\n- name: offline\n  targets: [{name: bird}]\n  neighbors: [1, 2]\n  prefixes: [10]\n  filter_test: [None]\n')
    env=dict(os.environ,DOCKER_HOST='unix:///no-such-docker.sock',MPLCONFIGDIR='/proc/forbidden',PYTHONDONTWRITEBYTECODE='1')
    program="import sys,json;import bgperf2;args=bgperf2.create_args_parser().parse_args(sys.argv[1:]);args.func(args);assert 'matplotlib.pyplot' not in sys.modules;assert 'numpy' not in sys.modules;assert bgperf2.dckr._value is None"
    cmd=[sys.executable,'-B','-c',program,'batch','-c',str(config),'--list-cells']
    result=subprocess.run(cmd,env=env,cwd=Path(engine.__file__).parent,capture_output=True,text=True,check=True)
    plain=json.loads(result.stdout)
    result=subprocess.run(cmd+['--defer-graphs'],env=env,cwd=Path(engine.__file__).parent,capture_output=True,text=True,check=True)
    deferred=json.loads(result.stdout)
    a=plain['tests'][0]['cells'];b=deferred['tests'][0]['cells']
    assert len(a)==len(b)==2 and all(x['key']!=y['key'] for x,y in zip(a,b))
    assert all(json.loads(c['id']).get('defer_graphs') is None for c in a)
    assert all(json.loads(c['id'])['defer_graphs'] is True for c in b)
    assert sorted(p.name for p in tmp_path.iterdir())==['batch.yaml']


def test_graph_inputs_roundtrip_and_reject_tampering(tmp_path):
    samples=[[1.,2.,3.,4.,5.,6.,7.]];calls=[]
    runtime=SimpleNamespace(atomic_write_json=engine.atomic_write_json,create_bench_graphs=lambda rows,**kw:calls.append((rows,kw)))
    root=tmp_path/'source';root.mkdir();graphs.save(runtime,samples,'original',root)
    graphs.render(runtime,SimpleNamespace(input=root,results_dir=tmp_path/'output'))
    assert calls[0][0]==samples and calls[0][1]['prefix']=='original'
    path=root/'original.graph-data.json';doc=json.loads(path.read_text());doc['samples'][0][0]=99
    path.write_text(json.dumps(doc))
    with pytest.raises(ValueError,match='checksum'):graphs.render(runtime,SimpleNamespace(input=path,results_dir=tmp_path/'output'))


@pytest.mark.parametrize('name',['../escape','','/absolute'])
def test_graph_prefix_cannot_escape(tmp_path,name):
    runtime=SimpleNamespace(atomic_write_json=engine.atomic_write_json)
    with pytest.raises(ValueError):graphs.save(runtime,[],name,tmp_path)


def test_phase_journal_is_attempt_bound_ordered_and_exclusive(tmp_path):
    path=tmp_path/'phases.jsonl';journal=Journal(path,'attempt');journal.note('admitted');journal.note('terminal',status='failed')
    rows=[json.loads(line) for line in path.read_text().splitlines()]
    assert [r['sequence'] for r in rows]==[0,1,2]
    assert all(r['attempt_id']=='attempt' and r['pid']==os.getpid() for r in rows)
    assert [r['monotonic_ns'] for r in rows]==sorted(r['monotonic_ns'] for r in rows)
    assert rows[-1]['details']['status']=='failed'
    with pytest.raises(FileExistsError):Journal(path,'reused')


def synthetic(tmp_path):
    return engine.create_args_parser().parse_args(['-d',str(tmp_path/'work'),'bench','-t','bird','-g','bird','-n','2','-p','10',
        '-i','sha256:'+'0'*64,'--generator-image','sha256:'+'1'*64,'--observer-image','sha256:'+'2'*64,'--results-dir',str(tmp_path/'results')])


@pytest.mark.parametrize('field,value',[('repeat',True),('tester_type','exa'),('path_diversity',2),('receivers',1),('image','mutable:tag'),('prefix_num',5000000)])
def test_synthetic_control_rejects_unsupported_before_files(tmp_path,field,value):
    args=synthetic(tmp_path);setattr(args,field,value)
    with pytest.raises(ValueError):native.bench(engine,args)
    assert not Path(args.dir).exists()


@pytest.mark.parametrize('failure',[False,True])
def test_synthetic_native_uses_same_lifecycle_exact_capture_and_cleanup(tmp_path,monkeypatch,failure):
    args=synthetic(tmp_path)
    monkeypatch.setattr(engine,'img_exists',lambda _:True)
    monkeypatch.setattr(engine,'controller_stop',threading.Event())
    cleanup=[]
    monkeypatch.setattr(native,'cleanup',lambda *a,**kw:cleanup.append(kw))
    def run(runtime,actual):
        runtime.native_scenario(dict(testers=[dict(neighbors=[{},{}])]))
        runtime.native_phase('measurement_finished')
        events=[dict(event='tester_complete',producer=actual.bench_name+'_generator',counters=dict(
            sessions=2,sessions_measured=2,expected_prefixes=20,offered_prefixes=20))]
        engine.atomic_write_json(str(Path(actual.results_dir)/(engine.bench_output_prefix(actual)+'.events.json')),dict(events=events))
        row=['']*29;row[6]=20;row[20]=row[21]=0;return row
    monkeypatch.setattr(native.run_lifecycle,'bench',run)
    monkeypatch.setattr(native.prefixes,'capture',lambda *a:{})
    monkeypatch.setattr(native.prefixes,'inspect',lambda *a:dict(missing_count=int(failure),unexpected_count=0))
    if failure:
        with pytest.raises(ValueError,match='completion'):native.bench(engine,args)
    else:assert native.bench(engine,args)[6]==20
    receipt=json.loads(next(Path(args.results_dir).glob('*.native.json')).read_text())
    assert receipt['generator_containers']==1 and cleanup==[dict(expected_count=3)]
    rows=[json.loads(line) for line in Path(receipt['phases']).read_text().splitlines()]
    assert rows[-1]['phase']=='terminal' and rows[-1]['details']['status']==('failed' if failure else 'completed')
    assert not any('input_' in r['phase'] for r in rows)


def test_preflight_checks_all_bindings_without_lifecycle(tmp_path,monkeypatch,capsys):
    args=synthetic(tmp_path);selected=[]
    config=tmp_path/'batch.yaml'
    import yaml
    config.write_text(yaml.safe_dump(dict(tests=[dict(name='preflight',targets=[dict(name='bird',label='bird',tester_type='bird',
        image=args.image,generator_image=args.generator_image,observer_image=args.observer_image)],neighbors=[1,2],prefixes=[10],filter_test=['None'])])))
    monkeypatch.setattr(engine,'img_exists',lambda image:selected.append(image) or True)
    actual=engine.create_args_parser().parse_args(['batch','-c',str(config),'--preflight'])
    engine.batch(actual);value=json.loads(capsys.readouterr().out)
    assert value['cells']==2 and len(selected)==3 and not Path(args.dir).exists()


def test_phase_io_failure_cannot_skip_owned_cleanup(tmp_path,monkeypatch):
    args=synthetic(tmp_path);cleaned=[];original=Journal.note
    monkeypatch.setattr(engine,'img_exists',lambda _:True)
    monkeypatch.setattr(engine,'controller_stop',threading.Event())
    def note(self,phase,**details):
        if phase in ('cleanup_started','terminal'):raise OSError('journal disk failure')
        return original(self,phase,**details)
    monkeypatch.setattr(Journal,'note',note)
    monkeypatch.setattr(native.run_lifecycle,'bench',lambda *a:(_ for _ in ()).throw(engine.StopRequested('cancelled')))
    monkeypatch.setattr(native,'cleanup',lambda *a,**kw:cleaned.append(True))
    with pytest.raises(ValueError,match='phase journal failed'):native.bench(engine,args)
    assert cleaned==[True]
    receipt=json.loads(next(Path(args.results_dir).glob('*.native.json')).read_text())
    assert receipt['status']=='failed' and receipt['phase_error']=='journal disk failure'
