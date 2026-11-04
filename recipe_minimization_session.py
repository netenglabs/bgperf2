# Copyright (C) 2026 bgperf2 contributors. Apache-2.0.
"""Owned, single-step minimization sessions and independently verified reports.

All operations except an explicitly executed step are offline. Reservations are
durable evidence: an uncertain worker is recovered from its original package,
never retried or silently abandoned.
"""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import uuid

import recipes
import recipe_minimization as core
from recipe_assertions import default_assertions
from recipe_results import _regular_file, verify_result_package
from recipe_targets import supplied_target

SCHEMA = 'bgperf2/minimization-session/v1alpha1'
REPORT_SCHEMA = 'bgperf2/minimization-report/v1alpha1'
MAX_JSON = 32 * 1024 * 1024
ROOT = Path(__file__).resolve().parent


def _safe(path):
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts or any(p.is_symlink() for p in (path, *path.parents)):
        raise recipes.ContractError('Use absolute paths without symlinks or parent traversal')
    return path


def _bytes(path):
    path = _safe(path)
    with _regular_file(path.parent, path.name) as source:
        data = source.read(MAX_JSON + 1)
    if len(data) > MAX_JSON:
        raise recipes.ContractError('Minimization control file exceeds 32 MiB')
    return data


def _load(path):
    try:
        return json.loads(_bytes(path), object_pairs_hook=recipes._pairs, parse_constant=recipes._nonfinite)
    except (ValueError, UnicodeError) as exc:
        raise recipes.ContractError(f'Invalid minimization JSON: {exc}') from exc


def _write(path, document):
    path = _safe(path)
    with path.open('x', encoding='utf-8') as output:
        output.write(json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + '\n')
        output.flush()
        os.fsync(output.fileno())


def _publish(root, relative, document):
    """Publish complete immutable bytes without overwriting prior evidence."""
    staging = _safe(root / 'unpublished')
    staging.mkdir(mode=0o700, exist_ok=True)
    temporary = staging / uuid.uuid4().hex
    _write(temporary, document)
    destination = _safe(root / relative)
    os.link(temporary, destination, follow_symlinks=False)
    _sync_directory(destination.parent)
    temporary.unlink()


def _sync_directory(path):
    descriptor = os.open(_safe(path), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _clear_pending(root):
    (root / 'pending.json').unlink()
    _sync_directory(root)


def _digest(document):
    return hashlib.sha256(recipes.canonical_json(document).encode()).hexdigest()


def _separate(paths):
    paths = [_safe(p) for p in paths]
    for i, path in enumerate(paths):
        for other in paths[i + 1:]:
            if path == other or path in other.parents or other in path.parents:
                raise recipes.ContractError('Destinations must be distinct and nonnested')
    for path in paths:
        if path == ROOT or ROOT in path.parents or path in ROOT.parents:
            raise recipes.ContractError('Destinations must be outside the engine checkout')
    return paths


def _config(root, *, plan=None):
    config = _load(root / 'session.json')
    recipes._keys(config, ('schema', 'workdir', 'results_dir', 'plan_sha256'), where='session configuration')
    recipes._same(config['schema'], SCHEMA, 'session schema')
    for field in ('workdir', 'results_dir'):
        recipes._text(config[field], 'session.' + field)
    recipes._match(config['plan_sha256'], recipes._HEX64, 'session.plan_sha256', 'a SHA-256 digest')
    _separate((config['workdir'], config['results_dir']))
    if plan is not None:
        recipes._same(config['plan_sha256'], _digest(plan), 'frozen plan')
    return config


@contextmanager
def _locked(root, *, mutating=True):
    root = _safe(root)
    descriptor = os.open(_safe(root / 'session.lock'), (os.O_RDWR if mutating else os.O_RDONLY) | os.O_NOFOLLOW)
    with os.fdopen(descriptor, 'r+' if mutating else 'r') as lock:
        try:
            fcntl.flock(lock, (fcntl.LOCK_EX if mutating else fcntl.LOCK_SH) | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise recipes.ContractError('Minimization session is already active') from exc
        if mutating:
            recipes._same(_config(root)['results_dir'], str(root),
                          'Mutation requires the original session root; relocated copies are read-only')
        yield root


def init_session(plan, *, workdir, results_dir):
    """Freeze an offline plan into fresh owned work and result directories."""
    core.validate_plan(plan)
    work, root = _separate((workdir, results_dir))
    if any(os.path.lexists(path) for path in (work, root)):
        raise recipes.ContractError('Choose fresh minimization destinations')
    work.mkdir(parents=True, mode=0o700)
    root.mkdir(parents=True, mode=0o700)
    for name in ('trials', 'evidence', 'proposals', 'attempts', 'failures', 'unpublished', 'snapshots'):
        (root / name).mkdir(mode=0o700)
    (root / 'session.lock').touch(mode=0o600, exist_ok=False)
    _write(root / 'plan.json', plan)
    config = {'schema': SCHEMA, 'workdir': str(work), 'results_dir': str(root), 'plan_sha256': _digest(plan)}
    _write(root / 'session.json', config)
    return {'session': str(root), **status_session(root)}


def _proposal(plan, request):
    candidate = core.candidate_recipe(plan['recipe'], request['peers'], request['routes'])
    assertions = default_assertions(candidate, include_prefixes=plan['assertion'] == 'observer.prefixes')
    assertions['assertions'] = [a for a in assertions['assertions'] if a['name'] == plan['assertion']]
    target = supplied_target(candidate, candidate['roles']['target']['image'])
    return {'recipe': candidate, 'assertions': assertions, 'target': target}


def _trial_name(request):
    return f't{request["index"]:04d}'


def _paths(root, config, request):
    name = _trial_name(request)
    proposal = root / 'proposals' / name
    return {'workdir': str(Path(config['workdir']) / name),
            'results_dir': str(root / 'attempts' / name),
            'result': str(root / 'attempts' / name / 'result.json'),
            'recipe': str(proposal / 'recipe.json'), 'assertions': str(proposal / 'assertions.json'),
            'target': str(proposal / 'target.json')}


def _history(root):
    root = _safe(root)
    plan = core.validate_plan(_load(root / 'plan.json'))
    config = _config(root, plan=plan)
    records = []
    for i, path in enumerate(sorted(_safe(root / 'trials').iterdir()), 1):
        if path.name != f't{i:04d}.json' or i > plan['max_trials']:
            raise recipes.ContractError('Trial journal must be bounded and contiguous')
        record = _load(path)
        recipes._keys(record, ('request', 'assessment'))
        expected = core.summarize(plan, records)['next']
        recipes._same(record['request'], expected, 'trial request chain')
        candidate = _proposal(plan, expected)['recipe']
        observed = core.classify_result(plan, candidate, root / 'evidence' / f't{i:04d}' / 'result.json')
        recipes._same(record['assessment'], observed, 'reconstructed trial evidence')
        records.append(record)
    summary = core.summarize(plan, records)
    pending = None
    already = False
    if os.path.lexists(root / 'pending.json'):
        pending = _load(root / 'pending.json')
        recipes._keys(pending, ('index', 'phase', 'peers', 'routes', 'recipe_sha256'), where='pending request')
        already = bool(records and pending == records[-1]['request'])
        recipes._same(pending, records[-1]['request'] if already else summary['next'], 'pending request')
    # Reconstruct the frozen launch controls for every recorded/reserved trial.
    requests = [r['request'] for r in records]
    if pending is not None and not already:
        requests.append(pending)
    names = { _trial_name(r) for r in requests }
    proposals = _safe(root / 'proposals')
    for path in proposals.iterdir():
        if path.name not in names:
            raise recipes.ContractError('Unaccounted proposal requires manual inspection; no successor')
    for request in requests:
        proposal = _proposal(plan, request)
        directory = proposals / _trial_name(request)
        incomplete = pending == request and not already
        if not os.path.lexists(directory) and incomplete:
            continue  # Reservation remains charged after interrupted preparation.
        present = sorted(p.name for p in _safe(directory).iterdir())
        expected_files = ['assertions.json', 'recipe.json', 'target.json']
        if (not incomplete and present != expected_files) or any(n not in expected_files for n in present):
            raise recipes.ContractError('Unexpected frozen proposal inventory')
        for key, value in proposal.items():
            if key + '.json' not in present and incomplete:
                continue
            recipes._same(_load(directory / (key + '.json')), value, 'frozen candidate control')
    return plan, config, records, summary, pending, already


def _controller_stop(root, pending):
    if not os.path.lexists(root / 'controller-stop.json'):
        return None
    stop = _load(root / 'controller-stop.json')
    recipes._keys(stop, ('request', 'kind', 'reason', 'prerequisites'))
    if pending is None:
        raise recipes.ContractError('Controller stop requires its charged reservation')
    recipes._same(stop['request'], pending, 'controller stop request')
    if os.path.lexists(root / 'trials' / (_trial_name(pending) + '.json')):
        raise recipes.ContractError('A known pre-launch refusal cannot also have a recorded original')
    recipes._choice(stop['kind'], ('setup_refused', 'host_busy'), 'pre-execution refusal')
    recipes._text(stop['reason'], 'controller stop reason')
    if stop['kind'] == 'host_busy':
        recipes._same(stop['prerequisites'], None, 'host busy has no prerequisite report')
    elif not isinstance(stop['prerequisites'], dict) or stop['prerequisites'].get('status') == 'checks_passed':
        raise recipes.ContractError('Setup refusal requires its returned prerequisite report')
    return stop


def _status(plan, records, summary, pending, already, stop=None):
    reserved = int(pending is not None and not already)
    return {**summary, 'state': 'operational_refused' if stop else 'recovery_required' if pending is not None else summary['state'],
            'conclusion': 'operational_refused' if stop else summary['conclusion'],
            'controller_stop': stop,
            'recovery_instruction': ('No attempt started. This session is closed and its reservation remains charged. '
                                     'Resolve the recorded prerequisite or host-lock refusal and initialize a fresh session.' if stop else
                                     'Recover only the existing original pending package. If it cannot be recovered, retain this session '
                                     'and all partial evidence and initialize a fresh session; never retry its reserved trial.' if pending else None),
            'pending': pending, 'pending_already_recorded': already,
            'trials_reserved': reserved, 'trials_remaining': plan['max_trials'] - len(records) - reserved,
            'max_trials': plan['max_trials'], 'assertion': plan['assertion'],
            'next': None if pending is not None else summary['next'],
            'scope': 'Bounded greedy search; no global minimum or performance claim.',
            'performance': {'policy': 'disabled', 'qualification': 'not_assessed'}}


def _status_session(root):
    plan, _, records, summary, pending, already = _history(_safe(root))
    return _status(plan, records, summary, pending, already, _controller_stop(root, pending))


def status_session(root):
    """Inspect a consistent verified snapshot without changing any bytes."""
    with _locked(root, mutating=False) as root:
        return _status_session(root)


def _next_trial(root):
    root = _safe(root)
    plan, config, records, summary, pending, already = _history(root)
    status = _status(plan, records, summary, pending, already, _controller_stop(root, pending))
    request = status['next']
    if request is None:
        return status
    paths = _paths(root, config, request)
    argv = ['recipes.py', 'run', paths['recipe'], '--target', paths['target'],
            '--workdir', paths['workdir'], '--results-dir', paths['results_dir'],
            '--diagnostics', 'basic', '--timeout', str(plan['timeout'])]
    if plan['assertion'] == 'observer.prefixes':
        argv.append('--observer-prefixes')
    return {**status, **_proposal(plan, request), 'paths': paths, 'argv': argv}


def next_trial(root):
    """Return one consistent read-only proposal; refuse concurrent mutation."""
    with _locked(root, mutating=False) as root:
        return _next_trial(root)


def _reserve(root):
    proposal = _next_trial(root)
    request = proposal['next']
    if proposal['pending'] is not None:
        raise recipes.ContractError('Pending trial requires explicit recovery; never retry it')
    if request is None:
        raise recipes.ContractError('Minimization is terminal; no trial may be reserved')
    paths = proposal['paths']
    for path in (paths['workdir'], paths['results_dir']):
        if os.path.lexists(_safe(path)):
            raise recipes.ContractError('Trial destinations already exist; retain evidence and inspect')
    # Reserve before creating launch inputs or invoking any worker. Partial
    # preparation remains a charged uncertain attempt after any exception.
    _publish(root, 'pending.json', request)
    directory = _safe(Path(paths['recipe']).parent)
    directory.mkdir(mode=0o700)
    for key in ('recipe', 'assertions', 'target'):
        _publish(root, Path(paths[key]).relative_to(root).as_posix(), proposal[key])
    return proposal


def reserve_trial(root):
    with _locked(root) as root:
        return _reserve(root)


def _record(root, result=None):
    plan, config, records, _, pending, already = _history(root)
    if _controller_stop(root, pending) is not None:
        raise recipes.ContractError('Known pre-execution refusal closed this session; initialize a fresh session')
    if pending is None:
        raise recipes.ContractError('No pending trial to record')
    expected = Path(_paths(root, config, pending)['result'])
    if result is not None and _safe(result) != expected:
        raise recipes.ContractError('Only the exact pending result path may be recorded')
    if already:
        # Journal publication succeeded. Reverify the original result as well as
        # its retained snapshot before clearing only this bookkeeping marker.
        candidate = _proposal(plan, pending)['recipe']
        recipes._same(core.classify_result(plan, candidate, expected), records[-1]['assessment'], 'original recovery evidence')
        _clear_pending(root)
        return _status_session(root)
    candidate = _proposal(plan, pending)['recipe']
    assessment = core.classify_result(plan, candidate, expected)
    record = {'request': pending, 'assessment': assessment}
    core.summarize(plan, records + [record])  # includes duplicate original-ID refusal
    # A separately collected valid original may return after interrupted
    # proposal publication. Complete only its deterministic missing controls,
    # after evidence/identity validation and without launching another worker.
    proposal = _proposal(plan, pending)
    proposal_directory = _safe(root / 'proposals' / _trial_name(pending))
    proposal_directory.mkdir(mode=0o700, exist_ok=True)
    for key in ('recipe', 'assertions', 'target'):
        relative = proposal_directory.relative_to(root) / (key + '.json')
        if not os.path.lexists(root / relative):
            _publish(root, relative.as_posix(), proposal[key])
    destination = root / 'evidence' / _trial_name(pending)
    snapshots = _safe(root / 'snapshots')
    snapshots.mkdir(mode=0o700, exist_ok=True)
    if os.path.lexists(destination):
        try:
            recipes._same(core.classify_result(plan, candidate, destination / 'result.json'), assessment, 'existing record snapshot')
        except (recipes.ContractError, OSError):
            # Preserve prior partial bytes without letting them block recovery
            # from the independently reverified original package.
            os.rename(destination, snapshots / (_trial_name(pending) + '-retained-' + uuid.uuid4().hex))
    if not os.path.lexists(destination):
        from recipe_investigation import _copy_package
        staging = snapshots / (_trial_name(pending) + '-copy-' + uuid.uuid4().hex)
        _copy_package(expected, _load(expected), staging)
        recipes._same(core.classify_result(plan, candidate, staging / 'result.json'), assessment, 'staged trial evidence')
        os.rename(staging, destination)
        _sync_directory(destination.parent)
    recipes._same(core.classify_result(plan, candidate, destination / 'result.json'), assessment, 'copied trial evidence')
    _publish(root, 'trials/' + _trial_name(pending) + '.json', record)
    _clear_pending(root)
    return _status_session(root)


def record_trial(root, *, result=None):
    with _locked(root) as root:
        return _record(root, result)


def recover_trial(root, *, result=None):
    """Record only the existing verified pending package; never launch work."""
    return record_trial(root, result=result)


def step_session(root, *, execute=False, run=None):
    if type(execute) is not bool:
        raise recipes.ContractError('execute must be an explicit boolean')
    if not execute:
        return next_trial(root)
    with _locked(root) as root:
        proposal = _reserve(root)
        plan = _load(root / 'plan.json')
        from recipe_run import RecipeNotStarted
        if run is None:
            from recipe_run import run_recipe
            run = run_recipe
        try:
            outcome = run(proposal['recipe'], workdir=Path(proposal['paths']['workdir']),
                results_dir=Path(proposal['paths']['results_dir']), timeout=plan['timeout'],
                target=proposal['target'], diagnostics='basic',
                observer_prefixes=plan['assertion'] == 'observer.prefixes')
            if isinstance(outcome, dict) and outcome.get('status') == 'setup_refused':
                recipes._same(outcome.get('exit_code'), 2, 'known setup refusal exit')
                recipes._text(outcome.get('reason'), 'known setup refusal reason')
                if not isinstance(outcome.get('prerequisites'), dict) or outcome['prerequisites'].get('status') == 'checks_passed':
                    raise recipes.ContractError('Known setup refusal requires its refused prerequisite report')
                _publish(root, 'controller-stop.json', {'request': proposal['next'], 'kind': 'setup_refused',
                         'reason': outcome.get('reason', 'Prerequisites refused before an attempt started.'),
                         'prerequisites': outcome.get('prerequisites')})
                return _status_session(root)
            return _record(root)
        except RecipeNotStarted as exc:
            recipes._text(str(exc), 'known host lock refusal reason')
            _publish(root, 'controller-stop.json', {'request': proposal['next'], 'kind': 'host_busy',
                     'reason': str(exc), 'prerequisites': None})
            return _status_session(root)
        except BaseException as exc:
            # Keep the reservation even if the worker published a valid result;
            # explicit recovery is required after any uncertain controller exit.
            _publish(root, 'failures/' + _trial_name(proposal['next']) + '-' + uuid.uuid4().hex + '.json',
                     {'request': proposal['next'], 'exception': type(exc).__name__, 'reason': str(exc)[:8192]})
            raise


def _render(status, pending_evidence=None):
    pending_text = ''
    if pending_evidence is not None:
        pending_text = ('A verified pending package is bundled. It remains unrecorded and cannot establish confirmation.'
                        if pending_evidence['availability'] == 'present' else pending_evidence['reason']) + '\n\n'
    return ('# Bounded reproducer minimization\n\n'
            f'State: {status["state"]}\n\nConclusion: {status["conclusion"]}\n\n'
            f'Selected assertion: {status["assertion"]}\n\n'
            f'Best observed shape: {status["best"]}\n\n'
            f'Fresh confirmation: {status["confirmed"]}\n\n'
            f'Recorded trials: {status["trials_recorded"]}; reserved: {status["trials_reserved"]}; '
            f'budget: {status["max_trials"]}.\n\n'
            + (status['recovery_instruction'] or 'No pending trial requires recovery.') + '\n\n'
            + pending_text +
            'This is a bounded greedy search. Passing points do not establish monotonicity. '
            'No global minimum or performance claim is made; performance policy is disabled.\n')


def _inventory(root):
    files = []
    for directory, dirs, names in os.walk(root, followlinks=False):
        for name in dirs + names:
            _safe(Path(directory) / name)
        for name in names:
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            with _regular_file(root, relative) as source:
                digest = hashlib.file_digest(source, 'sha256').hexdigest()
            files.append({'path': relative, 'sha256': digest})
    return sorted(files, key=lambda item: item['path'])


def _copy_control(source, output):
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('xb') as target:
        target.write(_bytes(source))


PENDING_UNAVAILABLE = ('No verified candidate-bound pending result is bundled. Partial original work and '
                       'results remain at their selected session paths and are not bundled.')


def _pending_evidence(plan, pending, already, path, *, stop=None):
    if pending is None or already:
        return None
    if stop is not None:
        return {'availability': 'unavailable',
                'reason': 'Known pre-execution refusal: no worker attempt started and no result package is expected.'}
    try:
        candidate = _proposal(plan, pending)['recipe']
        verify_result_package(path)
        assessment = core.classify_result(plan, candidate, path)
    except (recipes.ContractError, OSError, ValueError):
        return {'availability': 'unavailable', 'reason': PENDING_UNAVAILABLE}
    return {'availability': 'present', 'package': 'pending/result.json', 'assessment': assessment}


def _portable_package(source, destination):
    """Copy only verified manifest-listed artifacts, materializing stored bytes."""
    document = _load(source)
    verify_result_package(source)
    destination.mkdir(mode=0o700)
    names = ['result.json'] + [a['path'] for a in document['artifacts'] if a['availability'] == 'present']
    import shutil
    for name in names:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with _regular_file(source.parent, name) as reader, target.open('xb') as writer:
            shutil.copyfileobj(reader, writer, length=1024 * 1024)
    verify_result_package(destination / 'result.json')


def _build_report(root, *, output_dir, pending_source=None):
    root, output = _separate((root, output_dir))
    plan, config, records, _, pending, already = _history(root)
    status = _status_session(root)
    if os.path.lexists(output):
        raise recipes.ContractError('Choose a fresh report destination')
    work = _safe(config['workdir'])
    if output == work or output in work.parents or work in output.parents:
        raise recipes.ContractError('Report must be outside session work')
    pending_path = Path(_paths(root, config, pending)['result']) if pending is not None else None
    if pending_source is not None:
        pending_path = _safe(pending_source)
    pending_evidence = _pending_evidence(plan, pending, already, pending_path, stop=status['controller_stop'])
    output.mkdir(parents=True, mode=0o700)
    bundle = output / 'session'
    bundle.mkdir(mode=0o700)
    for name in ('trials', 'evidence', 'proposals', 'failures', 'unpublished'):
        (bundle / name).mkdir(mode=0o700)
    for name in ('plan.json', 'session.json', 'session.lock'):
        _copy_control(root / name, bundle / name)
    if pending is not None:
        _copy_control(root / 'pending.json', bundle / 'pending.json')
    if status['controller_stop'] is not None:
        _copy_control(root / 'controller-stop.json', bundle / 'controller-stop.json')
    for name in ('trials', 'proposals', 'failures', 'unpublished'):
        for item in _inventory(root / name):
            _copy_control(root / name / item['path'], bundle / name / item['path'])
    for record in records:
        name = _trial_name(record['request'])
        _portable_package(root / 'evidence' / name / 'result.json', bundle / 'evidence' / name)
    if pending_evidence is not None and pending_evidence['availability'] == 'present':
        _portable_package(pending_path, output / 'pending')
    document = {'schema': REPORT_SCHEMA, 'status': status, 'trials': records, 'pending_evidence': pending_evidence}
    _write(output / 'minimization.json', document)
    (output / 'REPORT.md').write_text(_render(status, pending_evidence), encoding='utf-8')
    _write(output / 'checksums.json', {'schema': REPORT_SCHEMA, 'files': _inventory(output)})
    verify_report(output / 'minimization.json')
    return document


def report(root, *, output_dir):
    """Freeze control bytes and independently portable copies of every package."""
    with _locked(root, mutating=False) as root:
        return _build_report(root, output_dir=output_dir)


def verify_report(path):
    """Reconstruct every claim from bundled bytes without runtime or old paths."""
    path = _safe(path)
    if path.is_dir():
        path = path / 'minimization.json'
    root = path.parent
    recipes._same(path.name, 'minimization.json', 'report filename')
    checksums = _load(root / 'checksums.json')
    recipes._keys(checksums, ('schema', 'files'))
    recipes._same(checksums['schema'], REPORT_SCHEMA, 'checksum schema')
    actual = [item for item in _inventory(root) if item['path'] != 'checksums.json']
    recipes._same(checksums['files'], actual, 'report file checksums and inventory')
    document = _load(path)
    recipes._keys(document, ('schema', 'status', 'trials', 'pending_evidence'))
    recipes._same(document['schema'], REPORT_SCHEMA, 'report schema')
    plan, _, records, summary, pending, already = _history(root / 'session')
    expected = _status(plan, records, summary, pending, already, _controller_stop(root / 'session', pending))
    recipes._same(document['status'], expected, 'reconstructed minimization status')
    recipes._same(document['trials'], records, 'reconstructed minimization trials')
    evidence = _pending_evidence(plan, pending, already, root / 'pending/result.json', stop=expected['controller_stop'])
    if evidence is not None and evidence['availability'] == 'unavailable' and os.path.lexists(root / 'pending'):
        raise recipes.ContractError('Bundled pending evidence is invalid; retain its original package')
    recipes._same(document['pending_evidence'], evidence, 'reconstructed pending package evidence')
    recipes._same(_bytes(root / 'REPORT.md').decode(), _render(expected, evidence), 'reconstructed report prose')
    return {'valid': True, 'schema': REPORT_SCHEMA, 'files_verified': len(actual), 'status': expected}


def rebuild_report(path, *, output_dir):
    path = _safe(path)
    if path.is_dir():
        path = path / 'minimization.json'
    _separate((path.parent, output_dir))
    verify_report(path)
    pending = path.parent / 'pending/result.json'
    return _build_report(path.parent / 'session', output_dir=output_dir,
                         pending_source=pending if os.path.lexists(pending) else None)
