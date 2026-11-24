# Copyright (C) 2026 bgperf2 contributors. Apache-2.0.
"""Exact-input MRT binding for native bench/batch; no portable recipe workers.

The existing lifecycle supplies every timing and resource statistic. Input and
final-set checks bracket that lifecycle and never extend its measurement clock.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time
import types
import uuid

import recipe_mrt as mrt
import recipe_prefixes as prefixes
import recipes
import run_lifecycle


_CACHE = {}


def flush_outputs(*roots):
    """Make native payloads durable before publishing a completed receipt.

    Runtime sockets and symlinks carry no flushable file contents. Never open
    them or follow a link into the shared input cache.
    """
    directories = set()
    for root in roots:
        root = Path(root)
        if root.is_symlink(): raise ValueError('Native output root is a symlink')
        for path in [root, *root.rglob('*')]:
            mode = path.lstat().st_mode
            if stat.S_ISREG(mode):
                fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                try:
                    if not stat.S_ISREG(os.fstat(fd).st_mode): raise ValueError('Native output type changed')
                    os.fsync(fd)
                finally: os.close(fd)
            elif stat.S_ISDIR(mode): directories.add(path)
        directories.update(root.parents)
    for path in sorted(directories, key=lambda p:len(p.parts), reverse=True):
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try: os.fsync(fd)
        finally: os.close(fd)


def workload(path, digest, neighbors, per_peer):
    path = Path(path)
    if not path.is_absolute() or path.is_symlink() or path.stat().st_size > 128*1024**2:
        raise ValueError('Canonical absolute MRT workload file required (at most 128 MiB)')
    data = path.read_bytes()
    if not re.fullmatch(r'[0-9a-f]{64}', digest or '') or hashlib.sha256(data).hexdigest() != digest:
        raise ValueError('MRT workload SHA-256 differs')
    key = (digest, neighbors, per_peer)
    if key not in _CACHE:
        def unique(pairs):
            value = {}
            for key, item in pairs:
                if key in value:
                    raise ValueError('Duplicate MRT workload key: '+key)
                value[key] = item
            return value
        spec = json.loads(data, object_pairs_hook=unique)
        mrt.validate_spec(spec, dict(neighbors=neighbors, prefixes_per_peer=per_peer))
        _CACHE[key] = spec
    return _CACHE[key]


def validate(args):
    if (args.file or args.repeat or args.tester_type != 'bgpdump2' or args.monitor != 'sink'
            or getattr(args, 'receivers', 0) or getattr(args, 'churn_prefixes', 0)
            or getattr(args, 'policy_reload_blocks', 0) or args.filter_test):
        raise ValueError('Exact MRT requires generated fresh bgpdump2/sink transit without extra workloads')
    for image in (args.image, args.generator_image, args.observer_image):
        if not re.fullmatch(r'sha256:[0-9a-f]{64}', image or ''):
            raise ValueError('Exact MRT requires three immutable image IDs')
    return workload(args.mrt_spec, args.mrt_spec_sha256, args.neighbor_num, args.prefix_num)


def selected_adapter(base, image, attempt, *, observer=False):
    class Selected(base):
        @classmethod
        def require_image(cls, *a, **kw):
            return image

        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self.image = image
            self.name = attempt + '_' + self.name
            if observer:
                os.chmod(self.host_dir, 0o700)
                self.prefix_snapshot_socket = self.guest_dir + '/' + prefixes.SOCKET_NAME
                self.prefix_snapshot_max_prefixes = prefixes.MAX_PREFIXES
    return Selected


def wait_for(runtime, path, seconds):
    deadline = time.monotonic() + seconds
    while not path.exists():
        if runtime.stop_signal.is_set():
            raise runtime.StopRequested(runtime.stop_signal.reason)
        if time.monotonic() >= deadline:
            raise ValueError('Native cell control deadline: ' + str(path))
        time.sleep(.1)
    if path.is_symlink() or path.stat().st_size > 1024:
        raise ValueError('Invalid native cell control receipt')


def offering(events, spec, attempt):
    completed = [e for e in events if e['event'] == 'tester_complete']
    result = []
    for ordinal, peer in enumerate(spec['peers']):
        matches = [e for e in completed if e['producer'].startswith(attempt+'_')
                   and e['producer'].endswith('_mrt-injector'+str(ordinal))]
        if len(matches) != 1:
            raise ValueError('Missing or duplicate attempt-bound offering witness')
        counters = matches[0]['counters']
        if (any(counters.get(k) != peer['prefixes'] for k in
                ('configured_prefixes','expected_prefixes','offered_prefixes'))
                or counters.get('sessions') != 1 or counters.get('sessions_measured') != 1):
            raise ValueError('Incomplete MRT producer offering')
        result.append(dict(peer=peer, producer=matches[0]['producer'], counters=counters))
    if len(completed) != len(result):
        raise ValueError('Foreign MRT completion witness')
    return result


def cleanup(engine, attempt, work, expected_count=None):
    errors = []
    containers = engine.dckr.containers(all=True)
    owned = [c for c in containers if any(n.lstrip('/').startswith(attempt+'_') for n in c.get('Names', []))]
    if expected_count is not None and len(owned) != expected_count:
        errors.append('Native owned container coverage differs')
    for container in containers:
        if any(n.lstrip('/').startswith(attempt+'_') for n in container.get('Names', [])):
            try:
                details=engine.dckr.inspect_container(container['Id'])
                engine.atomic_write_json(str(work/('container-'+container['Id'][:12]+'.json')),details)
                if details.get('State',{}).get('OOMKilled') or not details.get('State',{}).get('Running'):
                    errors.append('Native container did not remain running: '+container['Id'])
                with (work/('container-'+container['Id'][:12]+'.log')).open('xb') as output:
                    size=0
                    for chunk in engine.dckr.logs(container['Id'],stdout=True,stderr=True,stream=True,follow=False,timestamps=True):
                        size+=len(chunk)
                        if size>128*1024**2:
                            raise ValueError('Native container log exceeds 128 MiB preservation bound')
                        output.write(chunk)
                engine.dckr.remove_container(container['Id'], force=True)
            except Exception as exc:
                errors.append(str(exc))
                try:
                    engine.dckr.remove_container(container['Id'], force=True)
                except Exception as cleanup_error:
                    errors.append(str(cleanup_error))
    for network in engine.dckr.networks(names=[attempt+'-br']):
        try:
            if network['Name'] != attempt+'-br':
                raise ValueError('Native network identity differs')
            engine.dckr.remove_network(network['Id'])
        except Exception as exc:
            errors.append(str(exc))
    engine.atomic_write_json(str(work/'cleanup.json'), dict(errors=errors, attempt_id=attempt))
    if errors:
        raise ValueError('Native owned cleanup failed: '+str(errors))


def synthetic_spec(args):
    """Bounded generated BIRD/sink transit, with the existing /32 expectation."""
    if (getattr(args,'file',None) or getattr(args,'repeat',False) or args.tester_type!='bird'
            or args.monitor!='sink' or getattr(args,'filter_test',None)
            or getattr(args,'receivers',0) or getattr(args,'churn_prefixes',0)
            or getattr(args,'policy_reload_blocks',0) or getattr(args,'path_diversity',1) not in (None,1)
            or getattr(args,'mrt_file',None) or getattr(args,'mrt_injector',None)
            or getattr(args,'single_table',False) or getattr(args,'prefix_scope',None) not in (None,'per-peer')
            or getattr(args,'churn_bursts',None) not in (None,1)
            or getattr(args,'prefix_length',None) not in (None,32)
            or getattr(args,'tester_attributes',False)):
        raise ValueError('Controlled synthetic cells require generated fresh BIRD/sink plain transit')
    for image in (args.image,args.generator_image,args.observer_image):
        if not re.fullmatch(r'sha256:[0-9a-f]{64}',image or ''):
            raise ValueError('Controlled synthetic cells require three immutable image IDs')
    if (type(args.neighbor_num) is not int or type(args.prefix_num) is not int
            or min(args.neighbor_num,args.prefix_num)<1 or args.neighbor_num*args.prefix_num>prefixes.MAX_PREFIXES):
        raise ValueError('Controlled synthetic prefix count exceeds capture capacity')
    return dict(schema='bgperf2/native-synthetic-workload/v1',resolved=dict(
        neighbors=args.neighbor_num,prefixes_per_peer=args.prefix_num))


def synthetic_offering(events,document,attempt,generators):
    completed=[e for e in events if e['event']=='tester_complete']
    if len(completed)!=generators or len({e['producer'] for e in completed})!=generators:
        raise ValueError('Incomplete synthetic generator fleet')
    sessions=expected=0
    for event in completed:
        c=event['counters']
        if (not event['producer'].startswith(attempt+'_') or type(c.get('sessions')) is not int
                or c['sessions']<1 or c.get('sessions_measured')!=c['sessions']
                or type(c.get('expected_prefixes')) is not int or c['expected_prefixes']<1
                or c.get('offered_prefixes',-1)<c['expected_prefixes']):
            raise ValueError('Incomplete attempt-bound synthetic offering')
        sessions+=c['sessions'];expected+=c['expected_prefixes']
    if sessions!=document['resolved']['neighbors'] or expected!=prefixes.expected_count(document):
        raise ValueError('Synthetic source offering differs from declared topology')
    return [dict(producer=e['producer'],counters=e['counters']) for e in completed]


def bench(engine, selected):
    args = copy.copy(selected)
    is_mrt=bool(getattr(args,'mrt_spec',None))
    spec = validate(args) if is_mrt else None
    synthetic = None if is_mrt else synthetic_spec(args)
    for image in (args.image,args.generator_image,args.observer_image):
        if not engine.img_exists(image):
            raise ValueError('Native MRT image unavailable: '+image)
    attempt = getattr(args, 'native_attempt_id', None) or 'bgperf_bench_' + uuid.uuid4().hex
    if not re.fullmatch(r'bgperf_bench_[0-9a-f]{32}', attempt):
        raise ValueError('Invalid native attempt identity')
    args.bench_name = attempt
    if is_mrt:args.mrt_file = spec['input']['path']
    work = Path(args.dir)/attempt
    work.mkdir(parents=True,exist_ok=False)
    receipt_path = Path(args.results_dir)/(attempt+('.mrt.json' if is_mrt else '.native.json'))
    receipt_path.parent.mkdir(parents=True,exist_ok=True)
    args.results_dir = str(receipt_path.parent/attempt)
    Path(args.results_dir).mkdir(exist_ok=False)
    document = dict(schema=mrt.SCHEMA,mrt=spec) if is_mrt else synthetic
    receipt = dict(schema='bgperf2/native-mrt-result/v1' if is_mrt else 'bgperf2/native-result/v1',attempt_id=attempt,
        status='running',work=str(work),artifacts=args.results_dir,workload_path=getattr(args,'mrt_spec',None),
        workload_sha256=args.mrt_spec_sha256 if is_mrt else recipes.recipe_sha256(document),engine=engine.tool_revision(),
        images=dict(target=args.image,generator=args.generator_image,observer=args.observer_image),
        label=engine.run_name(args),expected_prefixes=prefixes.expected_count(document),
        row=None,error=None)
    if getattr(args,'native_cell_id',None):receipt['cell_id']=args.native_cell_id
    if not is_mrt:receipt['workload']=document
    engine.atomic_write_json(str(receipt_path),receipt)
    from native_phases import Journal
    receipt['phases']=str(Path(args.results_dir)/'phases.jsonl')
    journal=Journal(Path(receipt['phases']),attempt)
    receipt['defer_graphs']=bool(getattr(args,'defer_graphs',False))
    runtime = types.SimpleNamespace(**vars(engine))
    runtime.native_phase=journal.note
    runtime.TARGET_CLASSES = dict(engine.TARGET_CLASSES)
    runtime.TARGET_CLASSES[args.target] = selected_adapter(engine.TARGET_CLASSES[args.target],args.image,attempt)
    runtime.MONITOR_CLASSES = dict(engine.MONITOR_CLASSES)
    runtime.MONITOR_CLASSES['sink'] = selected_adapter(engine.MONITOR_CLASSES['sink'],args.observer_image,attempt,observer=True)
    if is_mrt:
        from bgpdump2 import Bgpdump2Tester
        fixed = mrt.adapter(selected_adapter(Bgpdump2Tester,args.generator_image,attempt),document)
        runtime.scenario_mrt_tester_class = lambda tester: fixed
        runtime.gen_conf = lambda options: mrt.generated_scenario(engine,options,document)
        import yaml
        runtime.render_scenario = yaml.safe_load
        runtime.Template = lambda text: types.SimpleNamespace(render=lambda: text)
    else:
        runtime.BIRDTester=selected_adapter(engine.BIRDTester,args.generator_image,attempt)
        def scenario(conf):
            if sum(len(t['neighbors']) for t in conf['testers'])!=args.neighbor_num:
                raise ValueError('Synthetic configured topology differs')
            receipt['generator_containers']=len(conf['testers'])
        runtime.native_scenario=scenario
    runtime.remove_target_containers = lambda: None
    runtime.remove_old_containers = lambda: None
    runtime.get_ctn_names = lambda: []
    runtime.target_image = lambda *a: args.image
    runtime.finish_bench = lambda *a,**kw: run_lifecycle.finish_bench(runtime,*a,**kw)
    runtime.abandon_run = lambda *a,**kw: run_lifecycle.abandon_run(runtime,*a,**kw)
    control = None
    if getattr(args,'control_dir',None):
        root=Path(args.control_dir)
        if not root.is_absolute() or not root.is_dir() or root.is_symlink():
            raise ValueError('Existing absolute native cell-control directory required')
        control=root/attempt;control.mkdir(exist_ok=False)
        engine.atomic_write_json(str(root/'current.json'),dict(attempt_id=attempt,path=str(control),phase='admission'))
        runtime.install_stop_handlers()
    try:
        if control:
            journal.note('admission_wait')
            wait_for(runtime,control/'admission-release.json',1800)
            if recipes.read_document(control/'admission-release.json') != dict(attempt_id=attempt):
                raise ValueError('Native admission release identity differs')
        journal.note('admitted')
        if is_mrt:
            receipt['input_before']=mrt.verify_input(document)
            journal.note('input_before_verified')
        if control:
            def before_replay():
                journal.note('pre_replay_ready')
                request=dict(schema='bgperf2/pre-replay/v1alpha1',attempt_id=attempt)
                engine.atomic_write_json(str(control/'pre-replay-ready.json'),request)
                wait_for(runtime,control/'pre-replay-release.json',125)
                if recipes.read_document(control/'pre-replay-release.json')!=request:
                    raise ValueError('Native replay release identity differs')
                journal.note('replay_released')
            runtime.before_replay=before_replay
        journal.note('setup_started')
        row=run_lifecycle.bench(runtime,args)
        receipt['row']=row
        journal.note('prefix_capture_started')
        capture=prefixes.capture(work/'monitor'/prefixes.SOCKET_NAME,document)
        engine.atomic_write_json(str(work/'observer-prefixes.json'),capture)
        identity=prefixes.inspect(capture,document)
        receipt['identity']=identity
        event_path=Path(args.results_dir)/(engine.bench_output_prefix(args)+'.events.json')
        events=recipes.read_document(event_path)
        receipt['offering']=(offering(events['events'],spec,attempt) if is_mrt else
            synthetic_offering(events['events'],document,attempt,receipt['generator_containers']))
        journal.note('prefix_capture_finished')
        if is_mrt:
            receipt['input_after']=mrt.verify_input(document)
            journal.note('input_after_verified')
        if (engine.row_failed(row) or identity['missing_count'] or identity['unexpected_count']
                or row[6]!=prefixes.expected_count(document) or row[20] or row[21]):
            raise ValueError('Native MRT completion/identity/generator health failed')
        receipt['status']='completed'
        return row
    except BaseException as exc:
        receipt.update(status='stopped' if isinstance(exc,(engine.StopRequested,KeyboardInterrupt)) else 'failed',error=str(exc))
        raise
    finally:
        runtime.controller_stop.set()
        try:
            try:journal.note('cleanup_started')
            except OSError as exc:receipt['phase_error']=str(exc)
            cleanup(engine,attempt,work,expected_count=(len(spec['peers']) if is_mrt else receipt.get('generator_containers',0))+2 if receipt['row'] is not None else None)
        except BaseException as exc:
            receipt.update(status='failed',cleanup_error=str(exc))
            if receipt['error'] is None:receipt['error']='Cleanup: '+str(exc)
            raise
        finally:
            if getattr(args,'native_durable',False):
                try:
                    flush_outputs(work,Path(args.results_dir))
                    receipt['storage_flushed']=True
                except (OSError,ValueError) as exc:
                    receipt.update(status='failed',storage_error=str(exc))
                    if receipt['error'] is None:receipt['error']='Native payload storage failed: '+str(exc)
            try:journal.note('terminal',status=receipt['status'])
            except OSError as exc:receipt['phase_error']=str(exc)
            if receipt.get('phase_error'):
                receipt.update(status='failed',error='Operational phase journal failed: '+receipt['phase_error'])
            engine.atomic_write_json(str(receipt_path),receipt)
            if control:
                engine.atomic_write_json(str(control/'done.json'),dict(attempt_id=attempt,status=receipt['status']))
            if receipt.get('phase_error'):raise ValueError(receipt['error'])
            if receipt.get('storage_error'):raise ValueError('Native payload storage failed: '+receipt['storage_error'])
