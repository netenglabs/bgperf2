# Copyright (C) 2026 bgperf2 contributors. Apache-2.0.
"""Explicit, offline assertions over verified synthetic recipe evidence.

These predicates do not change the engine's convergence decision. An exact
observer count proves count agreement only, never route or attribute identity.
"""
import hashlib
import json
import math
from pathlib import Path

import recipes
from measurements import EventKind, EventPhase, LifecycleEvent
from recipe_results import _regular_file, verify_result_package

SCHEMA = 'bgperf2/assertions/v1alpha1'
OUTCOME_SCHEMA = 'bgperf2/assertion-outcome/v1alpha1'
MAX_JSON_BYTES = 8 * 1024 * 1024


def _definitions(recipe):
    resolved = recipe['resolved']
    sessions = resolved['neighbors']
    total = sessions * resolved['prefixes_per_peer']
    return [
        ('sessions.ready', 'session_establishment', sessions, 'recorded_worker_budget'),
        ('injection.complete', 'injection_completion', sessions, 'recorded_worker_budget'),
        ('observer.count', 'observer_route_count', total, 'recorded_worker_budget'),
        ('experiment.complete', 'experiment_completion', 'completed', 'recorded_worker_budget'),
        ('roles.healthy', 'observed_role_health', ['generator', 'observer', 'target'], 'pre_cleanup_snapshot'),
    ]


def default_assertions(recipe):
    """Export expectations separately, bound to the unchanged recipe v1 digest."""
    recipes.validate_recipe(recipe)
    return {'schema': SCHEMA, 'recipe_sha256': recipes.recipe_sha256(recipe),
            'assertions': [{'name': name, 'capability': capability, 'expected': expected,
                            'deadline': {'kind': deadline}}
                           for name, capability, expected, deadline in _definitions(recipe)]}


def validate_assertions(spec, recipe):
    """Refuse unknown predicates, altered expectations and unsupported deadlines."""
    recipes.validate_recipe(recipe)
    recipes._keys(spec, ('schema', 'recipe_sha256', 'assertions'), where='assertions')
    recipes._choice(spec['schema'], (SCHEMA,), 'assertions.schema')
    recipes._same(spec['recipe_sha256'], recipes.recipe_sha256(recipe), 'assertions.recipe_sha256')
    items = spec['assertions']
    if not isinstance(items, list) or not items:
        raise recipes.ContractError('assertions: expected a nonempty assertion list')
    supported = {item['capability']: item for item in default_assertions(recipe)['assertions']}
    seen = set()
    for item in items:
        recipes._keys(item, ('name', 'capability', 'expected', 'deadline'), where='assertion')
        capability = item['capability']
        if not isinstance(capability, str) or capability not in supported:
            raise recipes.ContractError('assertion: unsupported capability; route/attribute, timeout, policy and recovery oracles are not available')
        if capability in seen:
            raise recipes.ContractError('assertion: duplicate capability')
        seen.add(capability)
        recipes._same(item, supported[capability], 'assertion')
    return spec


def _load(root, relative, references):
    """Read only listed bytes, rechecking the digest after package verification."""
    if relative not in references:
        return None, f'{relative} was not collected.'
    try:
        with _regular_file(root, relative) as source:
            data = source.read(MAX_JSON_BYTES + 1)
        if len(data) > MAX_JSON_BYTES:
            return None, f'{relative} exceeds the 8 MiB JSON inspection bound; raw evidence retained.'
        if hashlib.sha256(data).hexdigest() != references[relative]['sha256']:
            raise recipes.ContractError(f'{relative}: evidence changed after verification')
        value = json.loads(data.decode('utf-8'), object_pairs_hook=recipes._pairs,
                           parse_constant=recipes._nonfinite)
        if not isinstance(value, dict):
            raise ValueError('expected an object')
        return value, None
    except (UnicodeError, ValueError, RecursionError) as exc:
        # Unsafe paths and post-verification mutations are contract errors,
        # whereas malformed but checksummed JSON is retained as unmeasured.
        if isinstance(exc, recipes.ContractError) and 'changed after verification' in str(exc):
            raise
        return None, f'{relative}: JSON inspection failed: {exc}'


def _finite(value, positive=False):
    try:
        return (not isinstance(value, bool) and isinstance(value, (int, float))
                and math.isfinite(value) and (value > 0 if positive else value >= 0))
    except OverflowError:
        return False


def _events(document):
    if not isinstance(document.get('events'), list):
        raise ValueError('events must be a list')
    events, seen = [], set()
    for value in document['events']:
        recipes._keys(value, ('event', 'monotonic_s', 'producer', 'phase', 'counters', 'details'), where='event')
        event = LifecycleEvent(EventKind(value['event']), value['monotonic_s'],
                               value['producer'], EventPhase(value['phase']),
                               value['counters'], value['details'])
        if any(count < 0 for count in event.counters.values()):
            raise ValueError('negative event counter')
        key = (event.kind, event.producer)
        if key in seen:
            raise ValueError('duplicate event/producer witness')
        seen.add(key)
        events.append(event)
    origins = [event for event in events if event.kind == EventKind.BENCH_CLOCK_STARTED
               and event.producer == 'controller']
    if len(origins) != 1 or any(event.monotonic_s < origins[0].monotonic_s for event in events):
        raise ValueError('missing or inconsistent bench clock origin')
    for producer in {event.producer for event in events}:
        sequence = [next((event.monotonic_s for event in events
                          if event.producer == producer and event.kind == kind), None)
                    for kind in (EventKind.TESTER_SESSION_READY, EventKind.TESTER_FIRST_UPDATE,
                                 EventKind.TESTER_COMPLETE)]
        recorded = [value for value in sequence if value is not None]
        if recorded != sorted(recorded):
            raise ValueError('inverted generator event order')
        if sequence[2] is not None and sequence[1] is None:
            raise ValueError('generator completion lacks a first-update witness')
    return events


def evaluate_assertions(spec, recipe, result_path):
    """Evaluate named witnesses; absence stays null and never becomes a zero.

    Health is a final pre-cleanup container snapshot, collected outside the
    worker budget. It does not attest continuous or daemon-process health.
    Other positive witnesses require a recorded, satisfied finite worker budget.
    """
    validate_assertions(spec, recipe)
    result_path = Path(result_path)
    with _regular_file(result_path.parent, result_path.name) as source:
        manifest_bytes = source.read(MAX_JSON_BYTES + 1)
    if len(manifest_bytes) > MAX_JSON_BYTES:
        raise recipes.ContractError('Result manifest exceeds the 8 MiB assertion inspection bound')
    verification = verify_result_package(result_path)
    if verification['recipe_sha256'] != recipes.recipe_sha256(recipe):
        raise recipes.ContractError('assertion result package belongs to another recipe')
    # Do not reread new manifest references after verifying a different snapshot.
    with _regular_file(result_path.parent, result_path.name) as source:
        if source.read(MAX_JSON_BYTES + 1) != manifest_bytes:
            raise recipes.ContractError('Result manifest changed during assertion verification')
    manifest = json.loads(manifest_bytes, object_pairs_hook=recipes._pairs, parse_constant=recipes._nonfinite)
    references = {item['path']: item for item in manifest['artifacts'] if item['availability'] == 'present'}
    root = result_path.parent
    budget, budget_reason = _load(root, 'work/execution-budget.json', references)
    if budget is not None and (budget.get('schema') != 'bgperf2/execution-budget/v1alpha1'
            or budget.get('scope') != 'worker' or not _finite(budget.get('timeout_seconds'), True)
            or not _finite(budget.get('elapsed_seconds'))
            or type(budget.get('completed_within_budget')) is not bool):
        budget, budget_reason = None, 'Finite observed worker budget/completion evidence is unavailable or malformed.'
    budget_satisfied = (budget is not None and budget['completed_within_budget'] is True
                        and budget['elapsed_seconds'] <= budget['timeout_seconds'])
    if not budget_satisfied and budget_reason is None:
        budget_reason = 'Worker budget was not satisfied; event timing is not bounded by a completed worker.'
    raw_path = 'work/raw-events.json'
    if raw_path not in references:
        candidates = [path for path, item in references.items()
                      if item['kind'] == 'events' and path.endswith('.events.json')]
        raw_path = candidates[0] if len(candidates) == 1 else raw_path
    raw, event_reason = _load(root, raw_path, references)
    events = None
    if raw is not None:
        try:
            events = _events(raw)
            if budget is not None:
                origin = next(event.monotonic_s for event in events
                              if event.kind == EventKind.BENCH_CLOCK_STARTED and event.producer == 'controller')
                if any(event.monotonic_s - origin > budget['elapsed_seconds'] for event in events):
                    # The bench origin is inside the worker lifetime. Even
                    # before its exact start is recorded, an event span longer
                    # than that lifetime cannot support a bounded witness.
                    events = None
                    event_reason = 'Event clock span exceeds recorded worker elapsed time; raw evidence retained.'
        except (ValueError, TypeError, KeyError, AttributeError, OverflowError) as exc:
            event_reason = f'Raw events retained; witness inspection failed: {exc}'
    runtime, runtime_reason = _load(root, 'work/runtime.json', references)
    diagnostic, diagnostic_reason = _load(root, 'work/diagnostics.json', references)

    def witnesses(*paths):
        return [{'path': path, 'sha256': references[path]['sha256']}
                for path in paths if path in references]

    answers = []
    for assertion in spec['assertions']:
        capability = assertion['capability']
        answer = dict(assertion, status='unmeasured', observed=None, evidence=[],
                      reason='No supported witness was recorded.')
        if capability in ('session_establishment', 'injection_completion'):
            kind = (EventKind.TESTER_SESSION_READY if capability == 'session_establishment'
                    else EventKind.TESTER_COMPLETE)
            matches = [event for event in events or () if event.kind == kind]
            answer['evidence'] = witnesses(raw_path)
            if matches and all(isinstance(event.counters.get('sessions'), int)
                               and event.counters['sessions'] > 0 for event in matches):
                observed = sum(event.counters['sessions'] for event in matches)
                answer.update(observed=observed, status=('passed' if observed == assertion['expected']
                              else 'failed' if observed > assertion['expected'] else 'unmeasured'),
                              reason='Configured generator session total observed in lifecycle events.')
                if observed < assertion['expected']:
                    answer['reason'] = 'Only part of the configured generator session total has a recorded witness.'
            else:
                answer['reason'] = event_reason or 'Not every configured generator session has a recorded witness.'
        elif capability == 'observer_route_count':
            matches = [event for event in events or () if event.kind == EventKind.CONVERGENCE_CONFIRMED]
            answer['evidence'] = witnesses(raw_path)
            if len(matches) == 1 and 'accepted_prefixes' in matches[0].counters:
                observed = matches[0].counters['accepted_prefixes']
                answer.update(observed=observed, status='passed' if observed == assertion['expected'] else 'failed',
                              reason='Exact observer count at convergence confirmation; route identities and attributes are unmeasured.')
            else:
                answer['reason'] = event_reason or 'No unique final convergence count witness was recorded.'
        elif capability == 'experiment_completion':
            answer['evidence'] = witnesses('work/runtime.json')
            status = runtime.get('experiment_status_before_collection', runtime.get('status')) if runtime else None
            if status in ('completed', 'experiment_failed'):
                answer.update(observed=status, status='passed' if status == 'completed' else 'failed',
                              reason='Existing engine runtime outcome; separate from exact route-count agreement.')
            else:
                answer['reason'] = runtime_reason or 'No decisive existing engine completion outcome was recorded.'
        else:
            answer['evidence'] = witnesses('work/diagnostics.json')
            containers = diagnostic.get('containers') if diagnostic else None
            if isinstance(containers, list) and containers and all(isinstance(item, dict)
                    and isinstance(item.get('role'), str) for item in containers):
                roles = {item.get('role') for item in containers}
                states = [item.get('state') for item in containers]
                failed = any(isinstance(state, dict) and (state.get('Running') is False
                             or state.get('OOMKilled') is True or (isinstance(state.get('Error'), str)
                             and bool(state['Error']))) for state in states)
                # This supported BIRD recipe creates exactly one container per
                # role; its generator hosts every configured session.
                complete = (len(containers) == len(assertion['expected'])
                            and roles == set(assertion['expected']) and all(isinstance(state, dict)
                            and state.get('Running') is True and state.get('OOMKilled') is False
                            and state.get('Error') == '' for state in states))
                if failed or complete:
                    answer.update(observed=[{'role': item.get('role'), 'state': item.get('state')} for item in containers],
                                  status='failed' if failed else 'passed',
                                  reason='Owned container states at final pre-cleanup collection; continuous and daemon-process health are unmeasured.')
            if answer['status'] == 'unmeasured':
                answer['reason'] = diagnostic_reason or 'Complete final container health snapshots were not recorded.'
        if assertion['deadline']['kind'] == 'recorded_worker_budget':
            answer['evidence'] += witnesses('work/execution-budget.json')
            if answer['status'] == 'passed' and not budget_satisfied:
                answer.update(status='unmeasured', reason=budget_reason)
        answers.append(answer)
    statuses = {item['status'] for item in answers}
    outcome = 'failed' if 'failed' in statuses else 'inconclusive' if 'unmeasured' in statuses else 'passed'
    return {'schema': OUTCOME_SCHEMA, 'recipe_sha256': recipes.recipe_sha256(recipe),
            'outcome': outcome, 'assertions': answers,
            'worker_deadline': {'timeout_seconds': budget.get('timeout_seconds') if budget else None,
                                'elapsed_seconds': budget.get('elapsed_seconds') if budget else None,
                                'satisfied': budget_satisfied if budget else None, 'reason': budget_reason},
            'limits': ['Count agreement does not establish route or attribute correctness.',
                       'Container health snapshots do not establish continuous daemon health.',
                       'BIRD tester timeouts, policy, recovery, IPv6 and new actions are unsupported.']}
