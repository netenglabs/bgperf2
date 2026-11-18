# Copyright (C) 2026 bgperf2 contributors. Apache-2.0.
"""Durable serial native batches. No cloud service, agent, or retry loop."""
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import time
import uuid
from types import SimpleNamespace

import native_mrt

SCHEMA = 'bgperf2/native-batch-state/v1'
ATTEMPT = re.compile(r'bgperf_bench_[0-9a-f]{32}')


class MissingOperationalReview(ValueError):
    pass


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value: raise ValueError('Duplicate native batch key: ' + key)
            value[key] = item
        return value
    path = Path(path)
    if path.is_symlink(): raise ValueError('Native batch symlink refused: ' + str(path))
    return json.loads(path.read_text(), object_pairs_hook=unique)


def canonical(path):
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('Native batch paths must not contain symlinks')
    return path.resolve()


def blueprint(engine, args, expanded, calibrate, *, validate=True):
    """Freeze existing cell identities/order; calibration is a separate original."""
    positions = []; calibrations = {}
    for test, _, cells, order, seed in expanded:
        if order == 'shuffle' and test.get('seed') is None:
            raise ValueError('Durable shuffled batches require an explicit seed')
        ordered = engine.order_batch_cells(test['name'], cells, order, seed)
        measured = []
        for cell in ordered:
            selected = engine.batch_cell_args(args, cell)
            if validate:
                if getattr(selected, 'mrt_spec', None): native_mrt.validate(selected)
                else: native_mrt.synthetic_spec(selected)
            identity = copy.deepcopy(cell); identity.pop('repetition', None); identity.pop('ordinal', None)
            group = json.dumps(dict(test=test['name'], cell=identity), sort_keys=True)
            if calibrate and group not in calibrations:
                calibration = copy.deepcopy(cell); calibration['repetition'] = None
                name = 'calibration:' + test['name']
                identifier = engine.batch_cell_id(name, calibration)
                key = engine.batch_cell_key(identifier)
                calibrations[group] = key
                positions.append(dict(key=key, id=identifier, test=test['name'], cell=calibration,
                                      kind='calibration', requires=None, order=order, seed=seed))
            identifier = engine.batch_cell_id(test['name'], cell)
            measured.append(dict(key=engine.batch_cell_key(identifier), id=identifier,
                test=test['name'], cell=cell, kind='measurement', requires=calibrations.get(group), order=order, seed=seed))
        positions.extend(measured)
    if len({p['key'] for p in positions}) != len(positions): raise ValueError('Duplicate native batch position')
    plan = dict(calibrate=calibrate, work_root=str(canonical(args.dir)), positions=positions)
    policy = getattr(args, 'operational_policy_sha256', None)
    if policy:
        if not re.fullmatch(r'[0-9a-f]{64}', policy): raise ValueError('Operational policy SHA256 required')
        plan['operational_policy_sha256'] = policy
    return plan


def inspect_saved(args):
    state = read(canonical(args.results_dir) / 'native-batch.json')
    validate_state(state, state['plan'])
    print(json.dumps(status(state), indent=2))


def list_plan(engine, args, expanded):
    plan = blueprint(engine, args, expanded, bool(getattr(args, 'calibrate', False)), validate=False)
    print(json.dumps(dict(schema='bgperf2/native-batch-plan/v1', maximum_originals=len(plan['positions']),
                         runtime_qualified=False, **plan), indent=2))


def failed_row(engine, selected, error):
    """No invented timing: a failed row retains absent statistics as None."""
    header = [h.strip() for h in engine.stats_header().split(',')]
    values = {name:'' for name in ('flags','date','target image','tester version','monitor version')}
    values.update(name=engine.run_name(selected), target=selected.target,
                  version=getattr(selected, 'version', None) or '', peers=selected.neighbor_num,
                  failed='FAILED', MSG=engine.row_message(error), filters=getattr(selected, 'filter_test', None) or '')
    values['prefixes per peer'] = selected.prefix_num
    return [values.get(h) for h in header]


def receipt_path(root, attempt, cell):
    if not ATTEMPT.fullmatch(attempt): raise ValueError('Invalid native attempt identity')
    suffix = '.mrt.json' if cell['target'].get('mrt_spec') else '.native.json'
    return root / (attempt + suffix)


def checked_receipt(engine, root, position, attempt, work_root):
    path = receipt_path(root, attempt, position['cell']); value = read(path)
    selected = engine.batch_cell_args(SimpleNamespace(results_dir=str(root)), position['cell'])
    expected_images = dict(target=selected.image, generator=selected.generator_image, observer=selected.observer_image)
    schema = 'bgperf2/native-mrt-result/v1' if position['cell']['target'].get('mrt_spec') else 'bgperf2/native-result/v1'
    if (value.get('schema') != schema or value.get('status') not in ('running','completed','failed','stopped')
            or value.get('attempt_id') != attempt or value.get('cell_id') != position['id']
            or value.get('images') != expected_images or value.get('work') != str(work_root / attempt)
            or value.get('artifacts') != str(root / attempt)):
        raise ValueError('Native receipt identity/path binding differs')
    spec = native_mrt.validate(selected) if getattr(selected, 'mrt_spec', None) else None
    expected = selected.mrt_spec_sha256 if spec else native_mrt.recipes.recipe_sha256(native_mrt.synthetic_spec(selected))
    if value.get('workload_sha256') != expected: raise ValueError('Native receipt workload differs')
    return path, value


def clean_receipt(value):
    path = Path(value['work']) / 'cleanup.json'
    cleanup = read(path)
    if (value.get('cleanup_error') or value.get('phase_error') or cleanup.get('errors') != []
            or cleanup.get('attempt_id') != value['attempt_id']):
        raise ValueError('Native cleanup is not verified; independent work is stopped')


def recover_owned(engine, root, attempt, *, destination=None):
    """Preserve inspect/logs before removing only this interrupted attempt's objects."""
    if not ATTEMPT.fullmatch(attempt): raise ValueError('Invalid recovery owner')
    owned = [c for c in engine.dckr.containers(all=True)
             if any(n.lstrip('/').startswith(attempt + '_') for n in c.get('Names', []))]
    networks = engine.dckr.networks(names=[attempt + '-br'])
    if any(n['Name'] != attempt + '-br' for n in networks): raise ValueError('Ambiguous recovery network')
    ids = {c['Id'] for c in owned}
    for network in networks:
        details = engine.dckr.inspect_network(network['Id'])
        if set(details.get('Containers', {})) - ids: raise ValueError('Shared recovery network retained')
    destination = destination or root / 'recovery' / (attempt + '-' + uuid.uuid4().hex)
    destination.mkdir(parents=True)
    for container in owned:
        cid = container['Id']
        if not re.fullmatch(r'[0-9a-f]{64}', cid): raise ValueError('Invalid recovery container identity')
        before = engine.dckr.inspect_container(cid)
        engine.atomic_write_json(str(destination / (cid + '.before.json')), before)
        if before.get('State', {}).get('Running'): engine.dckr.stop(cid, timeout=10)
        after = engine.dckr.inspect_container(cid)
        if after.get('State', {}).get('Running'): raise ValueError('Owned container did not stop; retained')
        engine.atomic_write_json(str(destination / (cid + '.json')), after)
        with (destination / (cid + '.log')).open('xb') as stream:
            size = 0
            for chunk in engine.dckr.logs(cid, stdout=True, stderr=True, stream=True, follow=False, timestamps=True):
                size += len(chunk)
                if size > 128 * 1024**2: raise ValueError('Recovery log exceeds native preservation bound; objects retained')
                stream.write(chunk)
            stream.flush(); os.fsync(stream.fileno())
    engine.atomic_write_json(str(destination / 'networks.json'), networks)
    hashes = {p.name:digest(p) for p in destination.iterdir()}
    engine.atomic_write_json(str(destination / 'preserved.json'), dict(attempt_id=attempt, files=hashes))
    if any(digest(destination / name) != sha for name, sha in hashes.items()):
        raise ValueError('Recovery preservation readback failed; objects retained')
    native_mrt.flush_outputs(destination)
    for container in owned: engine.dckr.remove_container(container['Id'], force=True)
    for network in networks:
        if engine.dckr.inspect_network(network['Id']).get('Containers'):
            raise ValueError('Recovery network became shared; retained')
        engine.dckr.remove_network(network['Id'])
    if any(any(n.lstrip('/').startswith(attempt + '_') for n in c.get('Names', []))
           for c in engine.dckr.containers(all=True)) or engine.dckr.networks(names=[attempt + '-br']):
        raise ValueError('Owned recovery objects remain')
    engine.atomic_write_json(str(destination / 'completed.json'), dict(attempt_id=attempt, status='completed'))
    return str(destination)


def operational_review(engine, root, attempt):
    """Bind host-policy review before treating native completion as qualified."""
    if not attempt.get('operational_policy_sha256') or attempt.get('operational_review_missing'): return
    saved = root / 'operations' / (attempt['id'] + '.json')
    if attempt.get('operational_review_sha256'):
        if digest(saved) != attempt['operational_review_sha256']:
            raise ValueError('Retained operational review changed')
        review = read(saved)
    else:
        control = Path(attempt['control'])
        try:
            token = read(control / 'completion-release.json')
            review = read(control / 'operational-review.json')
        except FileNotFoundError as exc:
            raise MissingOperationalReview('Operational review missing; use --recover before resume') from exc
        if token != dict(attempt_id=attempt['id'], status=review.get('status'),
                         review_sha256=digest(control / 'operational-review.json')):
            raise ValueError('Operational completion release differs')
        if (review.get('attempt_id') != attempt['id']
                or review.get('policy_sha256') != attempt['operational_policy_sha256']
                or review.get('status') not in ('passed', 'rejected')):
            raise ValueError('Operational review identity/policy differs')
        saved.parent.mkdir(exist_ok=True)
        engine.atomic_write_json(str(saved), review)
        native_mrt.flush_outputs(saved.parent)
        attempt['operational_review_sha256'] = digest(saved)
    if review['status'] != 'passed':
        attempt['unqualified_reason'] = 'operational_policy_rejected: ' + str(review.get('reason'))


def wait_operational(engine, root, attempt):
    if not attempt.get('operational_policy_sha256'): return
    path = Path(attempt['control']) / 'completion-release.json'
    try: native_mrt.wait_for(engine, path, 180)
    except ValueError:
        if not path.exists(): raise MissingOperationalReview('Operational review deadline; use --recover') from None
        raise
    operational_review(engine, root, attempt)


def terminal(engine, root, position, entry, work_root, attempt):
    path, value = checked_receipt(engine, root, position, attempt['id'], work_root)
    if value['status'] not in ('completed', 'failed') and not attempt.get('unqualified_reason'): raise ValueError('Native result is not terminal')
    if value.get('storage_flushed') is not True: raise ValueError('Native payload durability is unverified')
    clean_receipt(value)
    selected = engine.batch_cell_args(SimpleNamespace(), position['cell'])
    operational_review(engine, root, attempt)
    if attempt.get('unqualified_reason'):
        row = failed_row(engine, selected, attempt['unqualified_reason']); status = 'failed'
    elif value['status'] == 'completed':
        row = value.get('row'); identity = value.get('identity', {})
        if (not isinstance(row, list) or len(row) != len(engine.stats_header().split(',')) or engine.row_failed(row)
                or identity.get('missing_count') != 0 or identity.get('unexpected_count') != 0 or not value.get('offering')):
            raise ValueError('Completed native result lacks required witnesses')
        status = 'completed'
    else:
        row = failed_row(engine, selected, value.get('error')); status = 'failed'
    attempt.update(status=status, receipt_sha256=digest(path)); entry.update(status=status, row=row)
    return row


def qualify(engine, root, position, entry, work_root, attempt):
    try:
        return terminal(engine, root, position, entry, work_root, attempt)
    except MissingOperationalReview:
        attempt['status'] = entry['status'] = 'interrupted'
        raise
    except Exception:
        attempt['status'] = entry['status'] = 'unresolved'
        raise


def publish(engine, args, expanded, state):
    if any(c['status'] == 'unresolved' for c in state['cells'].values()):
        raise ValueError('Unresolved original prevents publishing a new accepted report')
    for position in state['plan']['positions']:
        entry = state['cells'][position['key']]
        if position['kind'] != 'measurement' or 'row' not in entry: continue
        engine.write_batch_cell_result(str(args.results_dir), position['test'], position['id'], entry['row'],
                                      order=position['order'], seed=position['seed'])
    engine.report_batch_from_cell_results(expanded, str(args.results_dir), getattr(args, 'defer_graphs', False))


def status(state):
    counts = {s:sum(c['status'] == s for c in state['cells'].values())
              for s in ('completed', 'failed', 'interrupted', 'blocked', 'unrun', 'running', 'unresolved')}
    positions = [dict(key=p['key'], configuration=p['cell']['target'].get('label') or p['cell']['target']['name'],
        kind=p['kind'], repetition=p['cell'].get('repetition'), neighbors=p['cell']['neighbors'],
        prefixes=p['cell']['prefixes'], **state['cells'][p['key']]) for p in state['plan']['positions']]
    return dict(schema=SCHEMA, status=state['status'], counts=counts, positions=positions,
                reporting=state.get('reporting', 'not_started'), error=state.get('error'), report_error=state.get('report_error'))


def validate_state(state, plan):
    if (state.get('schema') != SCHEMA or state.get('plan') != plan
            or set(state.get('cells', {})) != {p['key'] for p in plan['positions']}):
        raise ValueError('Frozen durable batch definition differs')
    states = {'completed','failed','interrupted','blocked','unrun','running','unresolved'}
    seen = set()
    for value in state['cells'].values():
        if value.get('status') not in states or not isinstance(value.get('attempts'), list):
            raise ValueError('Malformed durable batch position')
        for attempt in value['attempts']:
            if not ATTEMPT.fullmatch(attempt.get('id', '')) or attempt['id'] in seen:
                raise ValueError('Malformed or duplicated native attempt')
            seen.add(attempt['id'])
        if value['status'] in ('completed','failed','interrupted','running','unresolved') and not value['attempts']:
            raise ValueError('Attempted position has no retained original')


def run(engine, args, expanded):
    if getattr(args, 'cells', None) or getattr(args, 'no_report', False):
        raise ValueError('Durable batch owns its cells and recovery; external cell control/selection is separate')
    control = getattr(args, 'control_dir', None)
    policy = getattr(args, 'operational_policy_sha256', None)
    recovery_only = getattr(args, 'recover', False)
    if bool(control) != bool(policy) and not recovery_only:
        raise ValueError('Managed durable batches require control directory and operational policy SHA256 together')
    if control:
        control = str(canonical(control))
        if not Path(control).is_dir(): raise ValueError('Existing control directory required')
    maximum = getattr(args, 'maximum_originals', None)
    seconds = getattr(args, 'timeout_seconds', None)
    if maximum is not None and (type(maximum) is not int or maximum < 1): raise ValueError('Positive original ceiling required')
    if seconds is not None and (type(seconds) is not int or seconds < 1): raise ValueError('Positive time ceiling required')
    started = time.monotonic(); fresh = 0
    root = canonical(args.results_dir); state_path = root / 'native-batch.json'
    existing = read(state_path) if state_path.exists() else None
    if existing:
        recorded_work = existing['plan']['work_root']
        supplied = str(canonical(args.dir))
        default = str(canonical(engine.create_args_parser().get_default('dir')))
        if not getattr(args, 'batch_status', False) and supplied not in (recorded_work, default):
            raise ValueError('Recorded work root is ' + recorded_work + '; resume cannot relocate originals')
        args = copy.copy(args); args.dir = recorded_work
        recorded_policy = existing['plan'].get('operational_policy_sha256')
        if policy and policy != recorded_policy: raise ValueError('Operational policy differs')
        args.operational_policy_sha256 = recorded_policy
        if recorded_policy and not control and not recovery_only and not getattr(args, 'batch_status', False):
            raise ValueError('Managed resume requires host control')
    calibrate = bool(getattr(args, 'calibrate', False) or existing and existing['plan']['calibrate'])
    plan = blueprint(engine, args, expanded, calibrate)
    if existing: validate_state(existing, plan)
    if getattr(args, 'batch_status', False):
        if not existing: raise ValueError('No durable batch state')
        print(json.dumps(status(existing), indent=2)); return
    if existing and not (getattr(args, 'resume', False) or recovery_only): raise ValueError('Durable batch retained; use --resume or --status')
    if not existing and getattr(args, 'resume', False): raise ValueError('No durable batch to resume')
    if not existing and root.exists() and any(p.name != '.native-batch.lock' for p in root.iterdir()):
        raise ValueError('Durable batch requires fresh results; existing evidence is retained')
    if recovery_only and not existing: raise ValueError('No durable batch to recover')
    # Images and the entire finite definition qualify before the first worker.
    if not recovery_only:
        engine.check_batch_images([p['cell']['target'] for p in plan['positions']])
        engine.check_batch_monitor_images([t for t, *_ in expanded])
        engine.check_batch_pin_and_repeat([t for t, *_ in expanded])
    root.mkdir(parents=True, exist_ok=True)
    with (root / '.native-batch.lock').open('a') as lock:
        try: fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: raise ValueError('Native batch controller is already active') from None
        if state_path.exists() and not (getattr(args, 'resume', False) or recovery_only):
            raise ValueError('Durable batch appeared during admission; use --resume')
        state = read(state_path) if state_path.exists() else dict(schema=SCHEMA, plan=plan, status='prepared',
            columns=[h.strip() for h in engine.stats_header().split(',')],
            cells={p['key']:dict(status='unrun', attempts=[]) for p in plan['positions']})
        validate_state(state, plan)
        args = copy.copy(args); args.results_dir = str(root); args.dir = plan['work_root']
        def save():
            engine.atomic_write_json(str(state_path), state)
            for directory in (root, *root.parents):
                fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                try: os.fsync(fd)
                finally: os.close(fd)
        work_root = Path(plan['work_root'])
        if state.get('error'):
            state.setdefault('stops', []).append(dict(status=state['status'], error=state.pop('error')))
        engine.install_stop_handlers(); state['status'] = 'running'; save()
        try:
            for position in plan['positions']:
                entry = state['cells'][position['key']]
                if engine.stop_signal.is_set(): raise engine.StopRequested(engine.stop_signal.reason)
                if entry['status'] in ('completed', 'failed'):
                    attempt = entry['attempts'][-1]
                    path = receipt_path(root, attempt['id'], position['cell'])
                    if digest(path) != attempt['receipt_sha256']:
                        attempt['status'] = entry['status'] = 'unresolved'
                        raise ValueError('Retained native receipt changed')
                    qualify(engine, root, position, entry, work_root, attempt)
                    continue
                if entry['status'] == 'unresolved': raise ValueError('Unresolved original retained; no automatic retry')
                if position['requires'] and state['cells'][position['requires']]['status'] != 'completed':
                    if recovery_only and state['cells'][position['requires']]['status'] != 'failed': continue
                    entry.update(status='blocked', reason='calibration_not_qualified'); save(); continue
                if entry['attempts']:
                    attempt = entry['attempts'][-1]
                    path = receipt_path(root, attempt['id'], position['cell'])
                    value = checked_receipt(engine, root, position, attempt['id'], work_root)[1] if path.exists() else None
                    if value and value['status'] in ('completed', 'failed'):
                        # A valid native receipt with no host review remains unqualified.
                        # Recovery never invents an admission or repeats this original.
                        if recovery_only and attempt.get('operational_policy_sha256'):
                            try: operational_review(engine, root, attempt)
                            except MissingOperationalReview:
                                attempt['unqualified_reason'] = 'operational_review_missing_after_interruption'
                                attempt['operational_review_missing'] = True
                        qualify(engine, root, position, entry, work_root, attempt); save(); continue
                    recoveries = attempt.setdefault('recoveries', [])
                    if attempt.get('recovery') and attempt['recovery'] not in recoveries:
                        recoveries.append(attempt['recovery'])
                    destination = root / 'recovery' / (attempt['id'] + '-' + uuid.uuid4().hex)
                    recoveries.append(str(destination))
                    attempt.update(status='interrupted', recovery=str(destination))
                    entry['status'] = 'interrupted'
                    # The preservation destination is durable state before any
                    # owned resource is stopped or removed. Interrupted recovery
                    # directories therefore remain referenced on the next resume.
                    save()
                    recover_owned(engine, root, attempt['id'], destination=destination)
                    retained = [p for p in (work_root / attempt['id'], root / attempt['id']) if p.is_dir()]
                    if retained: native_mrt.flush_outputs(*retained)
                    if attempt.get('operational_policy_sha256') and (Path(attempt['control'])/'completion-release.json').exists():
                        operational_review(engine, root, attempt)
                    if attempt.get('unqualified_reason'):
                        selected = engine.batch_cell_args(args, position['cell'])
                        entry.update(status='failed', row=failed_row(engine, selected, attempt['unqualified_reason']))
                        attempt['status']='failed'
                        if path.exists(): attempt['receipt_sha256']=digest(path)
                    save()
                if recovery_only or entry['status'] == 'failed': continue
                if (maximum is not None and fresh >= maximum) or (seconds is not None and time.monotonic()-started >= seconds):
                    state['status']='paused'; state['budget_stop']='invocation_ceiling'; break
                selected = engine.batch_cell_args(args, position['cell'])
                attempt = dict(id='bgperf_bench_' + uuid.uuid4().hex, status='running', host=socket.gethostname(),
                    boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(), engine=engine.tool_revision(), started_unix=time.time())
                if policy or plan.get('operational_policy_sha256'):
                    attempt.update(operational_policy_sha256=plan['operational_policy_sha256'],
                                   control=str(canonical(control) / attempt['id']))
                entry.pop('reason', None)
                entry['attempts'].append(attempt); entry['status'] = 'running'; fresh += 1; save()
                selected.native_cell_id = position['id']; selected.native_attempt_id = attempt['id']
                selected.native_durable = True
                selected.control_dir = control
                try:
                    native_mrt.bench(engine, selected)
                except (KeyboardInterrupt, engine.StopRequested) as exc:
                    attempt['error'] = str(exc) or type(exc).__name__
                    attempt['status'] = entry['status'] = 'interrupted'
                    if attempt.get('operational_policy_sha256') and (Path(attempt['control'])/'completion-release.json').exists():
                        operational_review(engine, root, attempt)
                    save(); raise
                except Exception as exc:
                    attempt['error'] = str(exc)
                    path = receipt_path(root, attempt['id'], position['cell'])
                    if not path.exists():
                        attempt['status'] = entry['status'] = 'unresolved'; entry['error'] = str(exc); save(); raise
                    try:
                        wait_operational(engine, root, attempt)
                        qualify(engine, root, position, entry, work_root, attempt)
                    except MissingOperationalReview:
                        attempt['status'] = entry['status'] = 'interrupted'; save(); raise
                    except Exception:
                        attempt['status'] = entry['status'] = 'unresolved'; save(); raise
                else:
                    wait_operational(engine, root, attempt)
                    qualify(engine, root, position, entry, work_root, attempt)
                save()
                print(json.dumps(dict(cell=position['key'], kind=position['kind'],
                    configuration=position['cell']['target'].get('label') or position['cell']['target']['name'],
                    repetition=position['cell'].get('repetition'), status=entry['status'])), flush=True)
                if entry['status'] == 'failed' and getattr(args, 'stop_on_failure', False):
                    raise engine.StopRequested('Recorded failed batch cell; --stop-on-failure')
            if state['status'] != 'paused': state['status'] = ('recovered' if recovery_only else 'completed_with_dispositions') if any(c['status'] in ('failed', 'blocked') for c in state['cells'].values()) else ('recovered' if recovery_only else 'completed')
        except BaseException as exc:
            state.update(status='stopped', error=str(exc)); raise
        finally:
            state['reporting'] = 'running'
            save()
            # Existing reporting retains failed rows and leaves blocked/missing cells unfilled.
            try:
                publish(engine, args, expanded, state)
                state['reporting'] = 'completed'; state.pop('report_error', None); save()
            except Exception as exc:
                state.update(reporting='failed', report_error=str(exc))
                if state['status'] != 'stopped': state['status'] = 'report_failed'
                save()
                if state['status'] == 'report_failed': raise
