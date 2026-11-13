"""Native bench/batch exact MRT bindings without Docker or route workers."""
import copy
import hashlib
import json
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

import bgperf2 as engine
import native_mrt as native
from mrt_controls import control


def fixture(tmp_path):
    path=tmp_path/'input.mrt'
    data,spec=control('plain',path,target_asn=64515,observer_asn=64516,source_asn=64520)
    path.write_bytes(data)
    workload=tmp_path/'workload.json';workload.write_text(json.dumps(spec))
    digest=hashlib.sha256(workload.read_bytes()).hexdigest()
    argv=['-d',str(tmp_path/'work'),'bench','-t','bird','-g','bgpdump2',
          '-n','1','-p',str(spec['peers'][0]['prefixes']),
          '-i','sha256:'+'0'*64,'--generator-image','sha256:'+'1'*64,
          '--observer-image','sha256:'+'2'*64,'--mrt-spec',str(workload),
          '--mrt-spec-sha256',digest,'--results-dir',str(tmp_path/'results')]
    return engine.create_args_parser().parse_args(argv),spec


def test_changed_workload_refused_before_side_effects(tmp_path):
    args,_=fixture(tmp_path)
    Path(args.mrt_spec).write_text('{}')
    with pytest.raises(ValueError,match='SHA-256'):native.bench(engine,args)
    assert not Path(args.dir).exists()


@pytest.mark.parametrize('field,value',[('repeat',True),('file','scenario.yaml'),('tester_type','bird'),('image','mutable:tag')])
def test_incompatible_native_selection_refuses(tmp_path,field,value):
    args,_=fixture(tmp_path);setattr(args,field,value)
    with pytest.raises(ValueError):native.validate(args)


def test_fixed_offering_requires_one_complete_attempt_bound_witness_per_peer(tmp_path):
    _,spec=fixture(tmp_path);count=spec['peers'][0]['prefixes']
    events=[dict(event='tester_complete',producer='bgperf_bench_id_bgperf_bgpdump2_tester_mrt-injector0',
        counters=dict(configured_prefixes=count,expected_prefixes=count,offered_prefixes=count,sessions=1,sessions_measured=1))]
    assert native.offering(events,spec,'bgperf_bench_id')[0]['peer']==spec['peers'][0]
    for bad in ([],events*2,[dict(events[0],producer='foreign_mrt-injector0')]):
        with pytest.raises(ValueError):native.offering(bad,spec,'bgperf_bench_id')
    events[0]['counters']['offered_prefixes']-=1
    with pytest.raises(ValueError):native.offering(events,spec,'bgperf_bench_id')


@pytest.mark.parametrize('failure',[False,True])
def test_native_bench_calls_lifecycle_directly_captures_afterward_and_cleans(tmp_path,monkeypatch,failure):
    args,spec=fixture(tmp_path);order=[]
    monkeypatch.setattr(engine,'img_exists',lambda image:True)
    monkeypatch.setattr(engine,'controller_stop',threading.Event())
    created=[]
    monkeypatch.setattr(engine.dckr,'containers',lambda **kw:created)
    monkeypatch.setattr(engine.dckr,'inspect_container',lambda _:dict(State=dict(Running=True,OOMKilled=False)))
    monkeypatch.setattr(engine.dckr,'logs',lambda *a,**kw:[])
    monkeypatch.setattr(engine.dckr,'remove_container',lambda *a,**kw:None)
    monkeypatch.setattr(engine.dckr,'networks',lambda **kw:[])
    def run(runtime,actual):
        assert actual.bench_name.startswith('bgperf_bench_')
        assert actual.mrt_file==spec['input']['path']
        assert runtime.TARGET_CLASSES['bird'].require_image()==args.image
        assert runtime.MONITOR_CLASSES['sink'].require_image()==args.observer_image
        created.extend(dict(Id=str(i),Names=['/'+actual.bench_name+'_'+str(i)]) for i in range(3))
        order.append('lifecycle')
        count=spec['peers'][0]['prefixes']
        events=[dict(event='tester_complete',producer=actual.bench_name+'_bgperf_bgpdump2_tester_mrt-injector0',
            counters=dict(configured_prefixes=count,expected_prefixes=count,offered_prefixes=count,sessions=1,sessions_measured=1))]
        engine.atomic_write_json(str(Path(actual.results_dir)/(engine.bench_output_prefix(actual)+'.events.json')),dict(events=events))
        row=['']*29;row[6]=len(spec['expected_prefixes']);row[20]=row[21]=0
        return row
    monkeypatch.setattr(native.run_lifecycle,'bench',run)
    monkeypatch.setattr(native.prefixes,'capture',lambda *a:order.append('capture') or {})
    monkeypatch.setattr(native.prefixes,'inspect',lambda *a:dict(missing_count=int(failure),unexpected_count=0))
    if failure:
        with pytest.raises(ValueError,match='completion/identity'):native.bench(engine,args)
    else:
        assert native.bench(engine,args)[6]==len(spec['expected_prefixes'])
    assert order==['lifecycle','capture']
    receipt=json.loads(next(Path(args.results_dir).glob('*.mrt.json')).read_text())
    assert receipt['status']==('failed' if failure else 'completed')
    assert receipt['input_before']['status']==receipt['input_after']['status']=='verified'
    assert (Path(receipt['work'])/'cleanup.json').is_file()


def test_batch_forwards_bindings_and_control_without_recipe_commands(tmp_path):
    args,_=fixture(tmp_path)
    target=dict(name='bird',tester_type='bgpdump2',version=None,
        **{k:getattr(args,k) for k in ('image','mrt_spec','mrt_spec_sha256','generator_image','observer_image')})
    cell=dict(target=target,prefixes=args.prefix_num,neighbors=1,monitor='sink',filter='None',repetition=1)
    selected=engine.batch_cell_args(SimpleNamespace(control_dir='/tmp/control'),cell)
    assert selected.mrt_spec_sha256==args.mrt_spec_sha256
    assert selected.control_dir=='/tmp/control'
    assert selected.generator_image==args.generator_image


def test_control_wait_obeys_cancellation(tmp_path):
    runtime=SimpleNamespace(stop_signal=SimpleNamespace(is_set=lambda:True,reason='SIGTERM'),StopRequested=engine.StopRequested)
    with pytest.raises(engine.StopRequested):native.wait_for(runtime,tmp_path/'missing',1)


def test_owned_cleanup_preserves_foreign_containers(tmp_path):
    removed=[]
    client=SimpleNamespace(containers=lambda **kw:[dict(Id='own',Names=['/attempt_owned']),dict(Id='foreign',Names=['/other'])],
        networks=lambda **kw:[],inspect_container=lambda _:dict(State=dict(Running=True,OOMKilled=False)),logs=lambda *a,**kw: [] if kw.get('follow') is False else (_ for _ in ()).throw(AssertionError('Live log following would block cleanup')),
        remove_container=lambda identity,**kw:removed.append(identity))
    runtime=SimpleNamespace(dckr=client,atomic_write_json=engine.atomic_write_json)
    native.cleanup(runtime,'attempt',tmp_path)
    assert removed==['own']
