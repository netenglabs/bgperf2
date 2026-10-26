# Copyright (C) 2026 bgperf2 contributors. Apache-2.0.
"""Bounded deterministic BIRD regression searches; performance predicates refused.

Planning, next, record, report and verification are offline. Only step/run with
--execute may build trusted local source and run an existing bounded recipe.
"""
import argparse
import base64
from contextlib import contextmanager
import copy
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import uuid

import recipes
from recipe_assertions import default_assertions, evaluate_assertions
from recipe_investigation import _copy_package, _read_attempt
from recipe_results import _regular_file, verify_result_package
from recipe_targets import validate_build_plan, validate_target

PLAN_SCHEMA = 'bgperf2/bisection-plan/v1alpha1'
REPORT_SCHEMA = 'bgperf2/bisection-report/v1alpha1'
MAX_CANDIDATES = 256
MAX_TRIALS = 1024
MAX_JSON = 32 * 1024 * 1024
ROOT = Path(__file__).parent
POLICY = {'qualification': 'not_assessed', 'policy': 'disabled'}


def digest(value):
    return hashlib.sha256(recipes.canonical_json(value).encode()).hexdigest()


def load(path):
    path = safe(path)
    with _regular_file(path.parent, path.name) as stream:
        data = stream.read(MAX_JSON + 1)
    if len(data) > MAX_JSON:
        raise recipes.ContractError('Bisection JSON exceeds the 32 MiB limit')
    try:
        return json.loads(data, object_pairs_hook=recipes._pairs, parse_constant=recipes._nonfinite)
    except (ValueError, UnicodeError) as exc:
        raise recipes.ContractError(f'Invalid bisection JSON: {exc}') from exc


def write(path, document):
    with safe(path).open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + '\n')


def safe(path):
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts or any(p.is_symlink() for p in (path, *path.parents)):
        raise recipes.ContractError('Use absolute paths without symlinks or parent traversal')
    return path


def finite(value, field):
    try:
        valid = type(value) in (int, float) and math.isfinite(value) and value > 0
    except OverflowError:
        valid = False
    if not valid:
        raise recipes.ContractError(f'{field}: expected a finite positive number')


def commit_parents(encoded, revision):
    if not isinstance(encoded, str) or len(encoded) > 90000:
        raise recipes.ContractError('Commit object must be bounded base64 text')
    try:
        data = base64.b64decode(encoded, validate=True)
        if len(data) > 65536 or hashlib.sha1(b'commit ' + str(len(data)).encode() + b'\0' + data).hexdigest() != revision:
            raise ValueError('Git commit object hash differs from revision')
        header, _ = data.split(b'\n\n', 1)
        lines = header.splitlines()
        if not lines or not lines[0].startswith(b'tree '):
            raise ValueError('Missing commit tree header')
        parents = [line[7:].decode('ascii') for line in lines if line.startswith(b'parent ')]
        for parent in parents:
            recipes._match(parent, recipes._REVISION, 'parent', 'a full Git commit')
        return parents
    except (ValueError, UnicodeError) as exc:
        raise recipes.ContractError(f'Invalid commit proof: {exc}') from exc


def build_controls(plan):
    return {key: plan[key] for key in ('toolchain_image', 'runtime_image', 'instrumentation',
                                      'cflags', 'configure_flags', 'build_recipe', 'network')}


def validate_plan(plan):
    recipes._keys(plan, ('schema', 'recipe', 'predicate', 'candidates', 'max_trials',
                        'worker_timeout', 'build_timeout', 'diagnostics', 'assumption'))
    recipes._choice(plan['schema'], (PLAN_SCHEMA,), 'schema')
    recipes.validate_recipe(plan['recipe'])
    recipes._choice(plan['predicate'], ('target_crash', 'assertions'), 'predicate')
    if plan['predicate'] == 'target_crash' and plan['recipe']['reproduction']['expected_outcome'] != 'target_crash':
        raise recipes.ContractError('Crash search requires a target_crash reproduction question')
    if plan['predicate'] == 'assertions' and plan['recipe']['reproduction']['expected_outcome'] != 'experiment_completed':
        raise recipes.ContractError('Assertion search requires an experiment_completed reproduction question')
    if plan['assumption'] != 'one monotone good-to-bad transition on the selected first-parent chain':
        raise recipes.ContractError('The deterministic monotonicity assumption must remain explicit')
    recipes._integer(plan['max_trials'], 'max_trials', 4)
    if plan['max_trials'] > MAX_TRIALS:
        raise recipes.ContractError('max_trials exceeds 1024')
    finite(plan['worker_timeout'], 'worker_timeout')
    finite(plan['build_timeout'], 'build_timeout')
    recipes._choice(plan['diagnostics'], ('basic',), 'diagnostics')
    candidates = plan['candidates']
    if not isinstance(candidates, list) or not 2 <= len(candidates) <= MAX_CANDIDATES:
        raise recipes.ContractError('Select 2..256 consecutive first-parent revisions')
    seen, controls = set(), None
    for index, candidate in enumerate(candidates):
        recipes._keys(candidate, ('revision', 'commit_object', 'build_plan'), where='candidate')
        revision, build = candidate['revision'], candidate['build_plan']
        recipes._match(revision, recipes._REVISION, 'revision', 'a full Git commit')
        if revision in seen:
            raise recipes.ContractError('Candidate revisions must be unique')
        parents = commit_parents(candidate['commit_object'], revision)
        if index and (not parents or parents[0] != candidates[index - 1]['revision']):
            raise recipes.ContractError('Candidates must be a complete consecutive first-parent chain')
        seen.add(revision)
        validate_build_plan(build)
        recipes._same(build['recipe'], plan['recipe'], 'candidate recipe')
        if build['source']['commit'] != revision or build['source']['dirty'] or build['source']['include_dirty']:
            raise recipes.ContractError('Bisection requires clean source plans at each exact revision')
        if controls is None:
            controls = build_controls(build)
        recipes._same(build_controls(build), controls, 'fixed build controls')
    if len(json.dumps(plan, indent=2, sort_keys=True, allow_nan=False).encode()) + 1 > MAX_JSON:
        raise recipes.ContractError('Bisection plan exceeds the 32 MiB inspection bound')
    return plan


def make_plan(recipe, build_plans, commit_objects, *, predicate, max_trials,
              worker_timeout=120, build_timeout=1200):
    candidates = [{'revision': build['source']['commit'], 'build_plan': copy.deepcopy(build),
                   'commit_object': base64.b64encode(raw).decode('ascii')}
                  for build, raw in zip(build_plans, commit_objects, strict=True)]
    return validate_plan({'schema': PLAN_SCHEMA, 'recipe': copy.deepcopy(recipe), 'predicate': predicate,
                         'candidates': candidates, 'max_trials': max_trials, 'worker_timeout': worker_timeout,
                         'build_timeout': build_timeout, 'diagnostics': 'basic',
                         'assumption': 'one monotone good-to-bad transition on the selected first-parent chain'})


def validate_selected_target(plan, index, target):
    build = plan['candidates'][index]['build_plan']
    validate_target(target, plan['recipe'])
    provenance = target['provenance']
    if provenance['kind'] != 'local_source':
        raise recipes.ContractError('A supplied image cannot establish a source-revision boundary')
    recipes._same(provenance['source'], build['source'], 'built source identity')
    recipes._same(provenance['instrumentation'], build['instrumentation'], 'instrumentation')
    fields = {'recipe': 'build_recipe', 'toolchain_image': 'toolchain_image',
              'runtime_image': 'runtime_image', 'compiler_flags': 'cflags',
              'linker_flags': 'cflags', 'configure_flags': 'configure_flags'}
    for actual, expected in fields.items():
        recipes._same(provenance['build'][actual], build[expected], 'built ' + actual)
    for name in ('toolchain_image', 'runtime_image'):
        if build[name].startswith('sha256:'):
            recipes._same(provenance['build'][name + '_id'], build[name], 'observed ' + name)
    from recipe_targets import _dockerfile
    built = provenance['build']
    expected = _dockerfile(built['toolchain_image_id'], built['runtime_image_id'], build)
    recipes._same(built['dockerfile_sha256'], hashlib.sha256(expected.encode()).hexdigest(), 'fixed Dockerfile')
    return target


def classification(plan, index, result_path):
    """Decide only from verified named witnesses; harness/missing evidence is ambiguous."""
    result_path = safe(result_path)
    with _regular_file(result_path.parent, result_path.name) as stream:
        pinned = stream.read(MAX_JSON + 1)
    if len(pinned) > MAX_JSON:
        raise recipes.ContractError('Result manifest exceeds inspection bound')
    evidence, recipe, result = _read_attempt(result_path, 'trial', None)
    if evidence['result_sha256'] != hashlib.sha256(pinned).hexdigest():
        raise recipes.ContractError('Result manifest changed during identity verification')
    recipes._same(recipe, plan['recipe'], 'trial recipe')
    target = validate_selected_target(plan, index, evidence['target'])
    root = Path(result_path).parent
    references = {item['path']: item for item in result['artifacts'] if item['availability'] == 'present'}

    def artifact(name):
        if name not in references:
            return None
        with _regular_file(root, name) as stream:
            data = stream.read(MAX_JSON + 1)
        if len(data) > MAX_JSON or hashlib.sha256(data).hexdigest() != references[name]['sha256']:
            raise recipes.ContractError('Artifact changed or exceeds inspection bound: ' + name)
        return json.loads(data, object_pairs_hook=recipes._pairs, parse_constant=recipes._nonfinite)

    spec = default_assertions(recipe)
    spec['assertions'] = spec['assertions'][:4]
    assertions = evaluate_assertions(spec, recipe, result_path)
    budget = assertions['worker_deadline']
    answer = 'ambiguous'
    reason = 'No decisive supported predicate witness within the selected worker budget.'
    if budget['satisfied'] is True and budget['timeout_seconds'] == plan['worker_timeout']:
        if plan['predicate'] == 'assertions' and result['status'] in ('completed', 'experiment_failed'):
            if assertions['outcome'] == 'passed':
                answer, reason = 'good', 'All four supported bounded assertions pass.'
            elif assertions['outcome'] == 'failed':
                answer, reason = 'bad', 'At least one supported bounded assertion has a decisive failed witness.'
        elif plan['predicate'] == 'target_crash':
            live = artifact('work/live-diagnostics.json')
            samples = live.get('samples') if isinstance(live, dict) else None
            budget_record = artifact('work/execution-budget.json')
            start = budget_record.get('started_monotonic_s') if isinstance(budget_record, dict) else None
            end = budget_record.get('ended_monotonic_s') if isinstance(budget_record, dict) else None
            try:
                anchored = (type(start) in (int, float) and type(end) in (int, float)
                            and math.isfinite(start) and math.isfinite(end) and 0 <= start <= end
                            and math.isclose(end - start, budget_record['elapsed_seconds'], rel_tol=1e-12, abs_tol=1e-9))
            except (OverflowError, KeyError):
                anchored = False
            seen, identifiers, crash, exit_seen, presence_only, valid = set(), set(), False, False, True, True
            previous = None
            if (isinstance(samples, list) and samples and anchored
                    and type(live.get('dropped_samples', 0)) is int and live.get('dropped_samples', 0) == 0):
                for sample in samples:
                    if not isinstance(sample, dict):
                        valid = False
                        break
                    if sample.get('role') != 'target':
                        continue
                    timestamp = sample.get('monotonic_s')
                    try:
                        clock_valid = (type(timestamp) in (int, float) and math.isfinite(timestamp)
                                       and start <= timestamp <= end
                                       and (previous is None or timestamp > previous))
                    except (OverflowError, TypeError, KeyError):
                        clock_valid = False
                    identifier = sample.get('container_id')
                    if (not clock_valid or sample.get('errors') != [] or not isinstance(identifier, str)
                            or not identifier or type(sample.get('bird_process_present')) is not bool):
                        valid = False
                        break
                    previous = timestamp
                    identifiers.add(identifier)
                    if sample.get('bird_process_present') is False:
                        presence_only = False
                    if sample.get('bird_process_present') is True:
                        seen.add(identifier)
                    code = sample.get('daemon_exit_code')
                    if code is not None:
                        exit_seen = True
                    if (identifier in seen and sample.get('bird_process_present') is False and
                            type(code) is int and 1 <= code <= 255):
                        crash = True
            else:
                valid = False
            if valid and crash and len(identifiers) == 1 and result['status'] == 'experiment_failed':
                answer, reason = 'bad', 'Previously observed BIRD process has a captured nonzero exit in its owned container.'
            elif (valid and presence_only and len(identifiers) == 1 and len(seen) == 1 and not exit_seen
                  and result['status'] == 'completed' and assertions['outcome'] == 'passed'):
                answer, reason = 'good', 'Completed correct recipe with target presence and no captured nonzero target exit.'
    # The same result bytes must underlie the identity, assertions and final answer.
    verify_result_package(result_path)
    with _regular_file(root, result_path.name) as stream:
        final_manifest = stream.read(MAX_JSON + 1)
    if final_manifest != pinned:
        raise recipes.ContractError('Result manifest changed during predicate evaluation')
    return {'classification': answer, 'reason': reason, 'target': target,
            'source_attempt_id': result['attempt']['id'], 'result_status': result['status'],
            'assertions': assertions, 'result_sha256': evidence['result_sha256']}


def request(plan, records):
    """Reconstruct next action; skipped/ambiguous points never move good/bad bounds."""
    size = len(plan['candidates'])
    initial = {r['request']['index']: r['classification'] for r in records
               if r['request']['phase'] in ('endpoint-good', 'endpoint-bad', 'search')}
    if 0 not in initial:
        selected = (0, 'endpoint-good')
    elif initial[0] != 'good':
        return {'state': 'unresolved', 'reason': 'Selected good endpoint was not witnessed good.'}
    elif size - 1 not in initial:
        selected = (size - 1, 'endpoint-bad')
    elif initial[size - 1] != 'bad':
        return {'state': 'unresolved', 'reason': 'Selected bad endpoint was not witnessed bad.'}
    else:
        good = max(i for i, outcome in initial.items() if outcome == 'good')
        bad = min(i for i, outcome in initial.items() if outcome == 'bad')
        if good >= bad:
            return {'state': 'unresolved', 'reason': 'Observed predicate is nonmonotone.'}
        available = [i for i in range(good + 1, bad) if i not in initial]
        if available:
            selected = (min(available, key=lambda i: (abs(2 * i - good - bad), i)), 'search')
        else:
            confirmations = {r['request']['phase']: r for r in records if r['request']['phase'].startswith('confirm-')}
            for phase, expected, index in [('confirm-good', 'good', good), ('confirm-bad', 'bad', bad)]:
                if phase not in confirmations:
                    selected = (index, phase)
                    break
                if confirmations[phase]['classification'] != expected:
                    return {'state': 'unresolved', 'reason': 'Fresh boundary confirmation failed or remained ambiguous.'}
            else:
                return {'state': 'confirmed' if bad == good + 1 else 'unresolved',
                        'reason': ('Adjacent first-parent boundary independently rerun on both sides.' if bad == good + 1 else
                                   'Skipped/ambiguous revisions remain inside the confirmed observed bracket.'),
                        'last_observed_good': plan['candidates'][good]['revision'],
                        'first_observed_bad': plan['candidates'][bad]['revision'],
                        'possible_first_bad': [c['revision'] for c in plan['candidates'][good + 1:bad + 1]]}
    if len(records) >= plan['max_trials']:
        return {'state': 'budget_exhausted', 'reason': 'Fixed trial budget exhausted; no automatic extension.'}
    index, phase = selected
    return {'state': 'trial_required', 'index': index, 'phase': phase,
            'revision': plan['candidates'][index]['revision'], 'trial': len(records) + 1}


@contextmanager
def locked(session):
    session = safe(session)
    if not session.is_dir():
        raise recipes.ContractError('Bisection session does not exist')
    for name in ('trials', 'evidence', 'failures', 'cache', 'work', 'results'):
        safe(session / name)
    descriptor = os.open(safe(session / 'session.lock'), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'a+') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise recipes.ContractError('Bisection session is already active') from exc
        yield session


def initialize(plan, session):
    validate_plan(plan)
    path = safe(session)
    forbidden = [ROOT.resolve(), *(Path(c['build_plan']['source_root']).resolve() for c in plan['candidates'])]
    if any(path == p or p in path.parents for p in forbidden) or os.path.lexists(path):
        raise recipes.ContractError('Choose a new session outside engine and all source checkouts')
    path.mkdir(mode=0o700, parents=True)
    for name in ('trials', 'evidence', 'failures', 'cache', 'work', 'results'):
        (path / name).mkdir(mode=0o700)
    write(path / 'plan.json', plan)
    write(path / 'identity.json', {'plan_sha256': digest(plan)})
    return {'session': str(path), 'next': request(plan, [])}


def history(session):
    plan = validate_plan(load(session / 'plan.json'))
    recipes._same(load(session / 'identity.json'), {'plan_sha256': digest(plan)}, 'session identity')
    records, ids = [], set()
    files = sorted((session / 'trials').iterdir())
    for number, path in enumerate(files, 1):
        if path.name != f't{number:04d}.json' or not path.is_file() or path.is_symlink():
            raise recipes.ContractError('Journal must contain contiguous immutable trial records')
        record = load(path)
        recipes._keys(record, ('request', 'classification', 'reason', 'result', 'failure', 'observed'))
        recipes._text(record['reason'], 'trial reason')
        expected = request(plan, records)
        recipes._same(record['request'], expected, 'recorded trial request')
        if record['result'] is not None:
            recipes._same(record['result'], f'evidence/t{number:04d}/result.json', 'trial package path')
            observed = classification(plan, expected['index'], session / record['result'])
            recipes._same(record['observed'], observed, 'reconstructed predicate evidence')
            recipes._same(record['classification'], observed['classification'], 'predicate outcome')
            recipes._same(record['reason'], observed['reason'], 'predicate reason')
            if record['failure'] is not None or observed['source_attempt_id'] in ids:
                raise recipes.ContractError('Duplicate original trial or conflicting failure reference')
            ids.add(observed['source_attempt_id'])
        else:
            if record['classification'] not in ('skipped', 'ambiguous') or record['observed'] is not None:
                raise recipes.ContractError('Unavailable evidence cannot establish good/bad')
            recipes._same(record['failure'], f'failures/t{number:04d}.json', 'trial failure path')
            failure = load(session / record['failure'])
            recipes._same(failure, {'classification': record['classification'], 'reason': record['reason']}, 'failure record')
        records.append(record)
    return plan, records


def pending_request(path, plan, records):
    pending = path / 'pending.json'
    if not pending.exists():
        return None
    value = load(pending)
    if records and value == records[-1]['request']:
        # Append succeeded but process stopped before clearing its reservation.
        # Reconcile bookkeeping only; never repeat that measured trial.
        pending.unlink()
        return None
    recipes._same(value, request(plan, records), 'pending request')
    return value


def next_trial(session):
    with locked(session) as path:
        plan, records = history(path)
        pending = pending_request(path, plan, records)
        if pending is not None:
            return {'state': 'recovery_required', 'pending': pending,
                    'reason': 'An earlier process reserved a trial; recover its evidence or explicitly abandon it. No automatic retry.'}
        return request(plan, records)


def append_result(path, plan, records, selected, result_path):
    observed = classification(plan, selected['index'], result_path)
    if observed['source_attempt_id'] in {r['observed']['source_attempt_id'] for r in records if r['observed']}:
        raise recipes.ContractError('Confirmation/search trials require distinct original result IDs')
    relative = f'evidence/t{selected["trial"]:04d}/result.json'
    source = Path(result_path)
    destination = path / Path(relative).parent
    if destination.exists():
        safe(destination)
        try:
            copied = classification(plan, selected['index'], destination / 'result.json')
        except (OSError, ValueError, TypeError, recipes.ContractError):
            # An interrupted copy is evidence too. Preserve it before the
            # operator-requested recovery copies the verified original anew.
            destination.rename(path / 'failures' / f't{selected["trial"]:04d}-partial-{uuid.uuid4().hex}')
        else:
            recipes._same(copied, observed, 'existing preserved trial package')
    if not destination.exists():
        _copy_package(source, load(source), destination)
    copied = classification(plan, selected['index'], destination / 'result.json')
    recipes._same(copied, observed, 'preserved trial package')
    record = {'request': selected, 'classification': observed['classification'], 'reason': observed['reason'],
              'result': relative, 'failure': None, 'observed': observed}
    write(path / f'trials/t{selected["trial"]:04d}.json', record)
    (path / 'pending.json').unlink()
    return record


def append_failure(path, selected, classification_value, reason):
    recipes._text(reason, 'failure reason')
    if classification_value not in ('skipped', 'ambiguous'):
        raise recipes.ContractError('A missing experiment can only be skipped or ambiguous')
    relative = f'failures/t{selected["trial"]:04d}.json'
    failure = {'classification': classification_value, 'reason': reason}
    if (path / relative).exists():
        recipes._same(load(path / relative), failure, 'existing immutable failure')
    else:
        write(path / relative, failure)
    record = {'request': selected, 'classification': classification_value, 'reason': reason,
              'result': None, 'failure': relative, 'observed': None}
    write(path / f'trials/t{selected["trial"]:04d}.json', record)
    (path / 'pending.json').unlink()
    return record


def record_result(session, result_path):
    with locked(session) as path:
        plan, records = history(path)
        selected = request(plan, records)
        if selected['state'] != 'trial_required':
            raise recipes.ContractError('No trial is currently required')
        if pending_request(path, plan, records) is None:
            write(path / 'pending.json', selected)
        return append_result(path, plan, records, selected, safe(result_path))


def recover(session, *, result_path=None, reason=None):
    with locked(session) as path:
        plan, records = history(path)
        if pending_request(path, plan, records) is None:
            return {'state': 'reservation_reconciled', 'next': request(plan, records)}
        selected = request(plan, records)
        recipes._same(load(path / 'pending.json'), selected, 'pending recovery request')
        if result_path is not None:
            return append_result(path, plan, records, selected, safe(result_path))
        failure = path / f'failures/t{selected["trial"]:04d}.json'
        if failure.exists():
            original = load(failure)
            recipes._keys(original, ('classification', 'reason'))
            return append_failure(path, selected, original['classification'], original['reason'])
        return append_failure(path, selected, 'ambiguous', reason)


def step(session, *, build=None, run=None):
    """One bounded explicit build/run. Injectable fake backends are library-only."""
    with locked(session) as path:
        plan, records = history(path)
        if pending_request(path, plan, records) is not None:
            raise recipes.ContractError('Pending trial requires explicit recovery, never automatic retry')
        selected = request(plan, records)
        if selected['state'] != 'trial_required':
            return selected
        write(path / 'pending.json', selected)
        candidate = plan['candidates'][selected['index']]
        key = digest(candidate['build_plan'])
        cache = path / 'cache' / key
        safe(cache)
        from recipe_targets import build_target
        from recipe_run import run_recipe
        try:
            if not cache.exists():
                cache.mkdir(mode=0o700)
                write(cache / 'identity.json', {'build_plan_sha256': key})
                target = (build or build_target)(candidate['build_plan'], output_dir=cache / 'build',
                    timeout=plan['build_timeout'], emit_disclosure=lambda value: write(cache / 'disclosure.json', value))
                validate_selected_target(plan, selected['index'], target)
                write(cache / 'target.json', target)
            else:
                recipes._same(load(cache / 'identity.json'), {'build_plan_sha256': key}, 'build cache identity')
                target = validate_selected_target(plan, selected['index'], load(cache / 'target.json'))
        except Exception as exc:
            failure = cache / 'build/build-result.json'
            kind = 'skipped' if failure.is_file() and load(failure).get('status') == 'failed' else 'ambiguous'
            return append_failure(path, selected, kind, f'Build not completed: {type(exc).__name__}: {exc}; original cache/work retained.')
        name = f't{selected["trial"]:04d}'
        try:
            result = (run or run_recipe)(plan['recipe'], target=target, workdir=path / 'work' / name,
                results_dir=path / 'results' / name, timeout=plan['worker_timeout'], diagnostics=plan['diagnostics'])
            result_path = path / 'results' / name / 'result.json'
            if result_path.is_file():
                return append_result(path, plan, records, selected, result_path)
            return append_failure(path, selected, 'ambiguous', f'No verified package; runtime outcome: {result.get("status")}')
        except Exception as exc:
            # Leave the reservation intact: a worker may have run, so never repeat it automatically.
            raise recipes.ContractError(f'Trial stopped with original work preserved; explicit recover required: {exc}') from exc


def run_search(session, **backends):
    while True:
        state = next_trial(session)
        if state['state'] != 'trial_required':
            return state
        result = step(session, **backends)
        if result.get('classification') == 'ambiguous':
            return {'state': 'paused_ambiguous', 'reason': result['reason'], 'next': next_trial(session)}


def render(report):
    lines = ['# Deterministic regression localization', '',
             'Question: ' + report['plan']['recipe']['reproduction']['question'], '',
             'Predicate: ' + report['plan']['predicate'] + '.', '',
             'Conclusion: **' + report['conclusion']['state'] + '**. ' +
             report['conclusion'].get('reason', 'The next selected trial has not run.'), '',
             'Performance: not_assessed. Regression policy: disabled.', '',
             '| Trial | Revision | Phase | Predicate | Experiment |', '| --- | --- | --- | --- | --- |']
    for record in report['trials']:
        item = record['request']
        lines.append(f'| {item["trial"]} | `{item["revision"]}` | {item["phase"]} | {record["classification"]} | ' +
                     ((record['observed'] or {}).get('result_status') or 'no measured experiment') + ' |')
    lines += ['', 'A confirmation is a fresh original trial; build caching never reuses a measurement.', '',
              'Skipped, unbuildable and ambiguous revisions are never good. Missing work is never a successful trial.', '',
              'This boundary is conditional on the declared single-transition assumption and this fixed recipe. '
              'It proves no general bug fix, unobserved monotonicity or performance regression. '
              'Source/build declarations and local checksums do not authenticate execution or establish reproducible binaries.', '']
    return '\n'.join(lines)


def report(session, output):
    with locked(session) as path:
        plan, records = history(path)
        conclusion = request(plan, records)
        pending = pending_request(path, plan, records)
        if pending is not None:
            conclusion = {'state': 'recovery_required', 'reason': 'An unfinished reserved trial remains; no retry is implied.'}
        destination = safe(output)
        if destination.exists() or destination == path or path in destination.parents or destination in path.parents:
            raise recipes.ContractError('Choose a new nonnested report destination')
        destination.mkdir(mode=0o700, parents=True)
        for name in ('plan.json', 'identity.json'):
            shutil.copyfile(path / name, destination / name)
        if pending is not None:
            write(destination / 'pending.json', pending)
        for name in ('trials', 'evidence', 'failures'):
            source = path / name
            (destination / name).mkdir(mode=0o700)
            for item in sorted(source.rglob('*')):
                relative = item.relative_to(path)
                if item.is_symlink():
                    raise recipes.ContractError('Session evidence contains a symlink')
                if item.is_dir():
                    (destination / relative).mkdir(mode=0o700, exist_ok=True)
                else:
                    with _regular_file(path, relative.as_posix()) as incoming, (destination / relative).open('xb') as outgoing:
                        shutil.copyfileobj(incoming, outgoing)
        document = {'schema': REPORT_SCHEMA, 'plan': plan, 'trials': records,
                    'conclusion': conclusion, 'performance': POLICY}
        write(destination / 'bisection.json', document)
        (destination / 'REPORT.md').write_text(render(document))
        inventory = [{'path': p.relative_to(destination).as_posix(),
                      'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
                     for p in sorted(destination.rglob('*')) if p.is_file()]
        write(destination / 'checksums.json', {'files': inventory})
        return verify_report(destination / 'bisection.json')


def verify_report(report_path):
    path = safe(report_path)
    root = path.parent
    manifest = load(root / 'checksums.json')
    recipes._keys(manifest, ('files',))
    listed = set()
    for item in manifest['files']:
        recipes._keys(item, ('path', 'sha256'))
        recipes._artifact_path(item['path'], 'report artifact')
        if item['path'] in listed or item['path'] == 'checksums.json':
            raise recipes.ContractError('Duplicate or self-referencing report artifact')
        listed.add(item['path'])
        with _regular_file(root, item['path']) as stream:
            observed = hashlib.sha256(stream.read()).hexdigest()
        recipes._same(observed, item['sha256'], 'report artifact hash')
    actual = set()
    for p in root.rglob('*'):
        if p.is_symlink():
            raise recipes.ContractError('Report contains a symlink')
        if p.is_file() and p != root / 'checksums.json':
            actual.add(p.relative_to(root).as_posix())
        elif not p.is_dir() and p != root / 'checksums.json':
            raise recipes.ContractError('Report contains a nonregular artifact')
    if listed != actual:
        raise recipes.ContractError('Report inventory differs from actual files')
    plan, records = history(root)
    document = load(path)
    recipes._keys(document, ('schema', 'plan', 'trials', 'conclusion', 'performance'))
    recipes._same(document['schema'], REPORT_SCHEMA, 'report schema')
    recipes._same(document['plan'], plan, 'report plan')
    recipes._same(document['trials'], records, 'reconstructed trials')
    # A pending reservation is represented only as recovery_required, not a false boundary.
    expected = request(plan, records)
    if (root / 'pending.json').exists():
        recipes._same(load(root / 'pending.json'), expected, 'report pending reservation')
        expected = {'state': 'recovery_required', 'reason': 'An unfinished reserved trial remains; no retry is implied.'}
    recipes._same(document['conclusion'], expected, 'reconstructed conclusion')
    recipes._same(document['performance'], POLICY, 'performance policy')
    recipes._same((root / 'REPORT.md').read_text(), render(document), 'human report')
    return {'valid': True, 'schema': REPORT_SCHEMA, 'files_verified': len(listed),
            'conclusion': document['conclusion']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    create = commands.add_parser('plan')
    create.add_argument('--recipe', required=True)
    create.add_argument('--build-plan', action='append', required=True, help='ordered clean per-revision source build plans')
    create.add_argument('--predicate', choices=('target_crash', 'assertions'), required=True)
    create.add_argument('--max-trials', type=int, required=True)
    create.add_argument('--worker-timeout', type=float, default=120)
    create.add_argument('--build-timeout', type=float, default=1200)
    create.add_argument('--output', required=True)
    start = commands.add_parser('init')
    start.add_argument('plan'); start.add_argument('--session', required=True)
    for name in ('next', 'step', 'run', 'record', 'recover', 'report'):
        command = commands.add_parser(name); command.add_argument('session')
        if name in ('step', 'run'):
            command.add_argument('--execute', action='store_true', help='explicitly authorize the selected local build and bounded recipe run')
        if name == 'record': command.add_argument('--result', required=True)
        if name == 'recover':
            selection = command.add_mutually_exclusive_group(required=True)
            selection.add_argument('--result'); selection.add_argument('--abandon-reason')
        if name == 'report': command.add_argument('--output', required=True)
    verify = commands.add_parser('verify'); verify.add_argument('report')
    args = parser.parse_args(argv)
    try:
        if args.command == 'plan':
            from recipe_targets import _git
            if not 2 <= len(args.build_plan) <= MAX_CANDIDATES:
                raise recipes.ContractError('Select 2..256 consecutive first-parent revisions')
            builds = [load(safe(p)) for p in args.build_plan]
            for build in builds: validate_build_plan(build)
            raw = [_git(Path(build['source_root']), 'cat-file', 'commit', build['source']['commit']) for build in builds]
            result = make_plan(load(safe(args.recipe)), builds, raw, predicate=args.predicate,
                               max_trials=args.max_trials, worker_timeout=args.worker_timeout, build_timeout=args.build_timeout)
            write(safe(args.output), result)
        elif args.command == 'init': result = initialize(load(safe(args.plan)), args.session)
        elif args.command == 'next': result = next_trial(args.session)
        elif args.command in ('step', 'run'):
            result = (step(args.session) if args.command == 'step' else run_search(args.session)) if args.execute else next_trial(args.session)
        elif args.command == 'record': result = record_result(args.session, args.result)
        elif args.command == 'recover': result = recover(args.session, result_path=args.result, reason=args.abandon_reason)
        elif args.command == 'report': result = report(args.session, args.output)
        else: result = verify_report(args.report)
        print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
        if args.command == 'run' and args.execute and result.get('state') != 'confirmed':
            return 5
        return 0
    except (OSError, ValueError, TypeError, recipes.ContractError) as exc:
        parser.exit(2, f'Bisection refused: {exc}\n')


if __name__ == '__main__':
    raise SystemExit(main())
