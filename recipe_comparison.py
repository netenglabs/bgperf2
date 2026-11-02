# Copyright (C) 2026 bgperf2 contributors. Apache-2.0.
"""Explicit serial repeated comparisons; planning is offline and never authorizes a run."""
import copy
import hashlib
import math
import os
from pathlib import Path

import recipes

PLAN_SCHEMA = 'bgperf2/comparison-plan/v1alpha1'
MAX_REPETITIONS = 100  # An implementation bound, never a statistical recommendation.
ROLES = ('baseline', 'candidate')


def comparison_sequence(repetitions, order, seed):
    """Repeat the whole pair; deterministic digest ordering mirrors batch ordering.

    Alternating blocks counterbalance AB/BA. Shuffle uses a stable SHA-256 key,
    rather than interpreter-specific PRNG draws, as the existing batch does.
    Role/round identity stays independent of execution position.
    """
    sequence = []
    for pair in range(1, repetitions + 1):
        block = list(ROLES)
        if order == 'alternating' and pair % 2 == 0:
            block.reverse()
        elif order == 'shuffle':
            block.sort(key=lambda role: hashlib.sha256(
                f'{seed}:{pair}:{role}'.encode('ascii')).hexdigest())
        for role in block:
            sequence.append({'index': len(sequence), 'pair': pair, 'role': role,
                             'id': f'r{pair:03d}-{role}'})
    return sequence


def validate_comparison_plan(plan):
    recipes._keys(plan, ('schema', 'recipe', 'targets', 'repetitions', 'order', 'seed',
                         'diagnostics', 'timeout', 'assertions', 'sequence'), where='comparison plan')
    recipes._choice(plan['schema'], (PLAN_SCHEMA,), 'comparison plan.schema')
    recipes.validate_recipe(plan['recipe'])
    recipes._keys(plan['targets'], ROLES, where='comparison plan.targets')
    from recipe_targets import validate_target
    for role in ROLES:
        validate_target(plan['targets'][role], plan['recipe'])
    repetitions = recipes._integer(plan['repetitions'], 'repetitions', 1)
    if repetitions > MAX_REPETITIONS:
        raise recipes.ContractError(f'repetitions exceeds implementation bound {MAX_REPETITIONS}')
    recipes._choice(plan['order'], ('alternating', 'shuffle'), 'order')
    if plan['order'] == 'shuffle':
        recipes._integer(plan['seed'], 'shuffle seed')
    elif plan['seed'] is not None:
        raise recipes.ContractError('seed applies only to shuffle order')
    recipes._choice(plan['diagnostics'], ('none', 'basic'), 'diagnostics')
    timeout = plan['timeout']
    try:
        valid_timeout = (not isinstance(timeout, bool) and isinstance(timeout, (int, float))
                         and math.isfinite(timeout) and timeout > 0)
    except OverflowError:
        valid_timeout = False
    if not valid_timeout:
        raise recipes.ContractError('timeout must be finite and positive')
    from recipe_assertions import validate_assertions
    validate_assertions(plan['assertions'], plan['recipe'])
    recipes._same(plan['sequence'], comparison_sequence(repetitions, plan['order'], plan['seed']), 'sequence')
    return plan


def make_comparison_plan(recipe, *, baseline_target, candidate_target, repetitions,
                         order='alternating', seed=None, timeout=300, diagnostics='none',
                         assertions=None):
    """Freeze every requested attempt and its controls without runtime probes."""
    # Validate counts before constructing a potentially unbounded sequence.
    recipes._integer(repetitions, 'repetitions', 1)
    if repetitions > MAX_REPETITIONS:
        raise recipes.ContractError(f'repetitions exceeds implementation bound {MAX_REPETITIONS}')
    recipes._choice(order, ('alternating', 'shuffle'), 'order')
    if order == 'shuffle':
        recipes._integer(seed, 'shuffle seed')
    elif seed is not None:
        raise recipes.ContractError('seed applies only to shuffle order')
    from recipe_assertions import default_assertions
    plan = {'schema': PLAN_SCHEMA, 'recipe': copy.deepcopy(recipe),
            'targets': {'baseline': copy.deepcopy(baseline_target), 'candidate': copy.deepcopy(candidate_target)},
            'repetitions': repetitions, 'order': order, 'seed': seed,
            'timeout': timeout, 'diagnostics': diagnostics,
            'assertions': copy.deepcopy(assertions) if assertions is not None else default_assertions(recipe),
            'sequence': comparison_sequence(repetitions, order, seed)}
    validate_comparison_plan(plan)
    return plan


def _destinations(workdir, results_dir):
    from recipe_investigation import _new_roots
    return _new_roots(workdir, results_dir)


def _write(path, document):
    recipes._write_document(document, path)


def run_comparison(plan, *, workdir, results_dir, run=None, check=None):
    """Execute exactly the frozen sequence serially, stopping on first noncompletion.

    Every attempt goes through the existing guarded, bounded run path. No retry,
    resume, image acquisition, build or calibrated performance policy is provided.
    Injection is library-only for deterministic tests and maintained simulations.
    """
    validate_comparison_plan(plan)
    from artifact_store import validate_destinations, StorageError
    try:
        validate_destinations(workdir, results_dir)
    except StorageError as exc:
        raise recipes.ContractError(str(exc)) from exc
    work, results = _destinations(workdir, results_dir)
    from recipe_preflight import check_recipe
    precheck = check or check_recipe
    checks = []
    for role in ROLES:
        entry = next(item for item in plan['sequence'] if item['role'] == role)
        checks.append(precheck(plan['recipe'], workdir=work / entry['id'],
                               results_dir=results / entry['id'], target=plan['targets'][role]))
    if any(item.get('status') != 'checks_passed' for item in checks):
        return {'schema': PLAN_SCHEMA, 'status': 'setup_refused', 'exit_code': 2,
                'reason': 'Both targets must pass prerequisites before any comparison attempt.',
                'prerequisites': checks}
    work.mkdir(parents=True, mode=0o700)
    results.mkdir(parents=True, mode=0o700)
    _write(results / 'comparison-plan.json', plan)
    attempts = [{**entry, 'result': None, 'status': 'not_run',
                 'reason': 'This planned attempt has not run.'} for entry in plan['sequence']]
    _write(results / 'attempts.json', attempts)
    from recipe_run import run_recipe
    from recipe_results import verify_result_package
    from recipe_investigation import _read_attempt
    execute = run or run_recipe
    stop_exit = 0
    observed_attempt_ids = set()
    for index, entry in enumerate(plan['sequence']):
        attempt = attempts[index]
        try:
            result = execute(plan['recipe'], workdir=work / entry['id'], results_dir=results / entry['id'],
                             timeout=plan['timeout'], diagnostics=plan['diagnostics'],
                             target=plan['targets'][entry['role']])
            recipes._choice(result.get('status'), tuple(recipes.RESULT_EXIT_CODES), 'attempt status')
            code = result.get('exit_code', recipes.RESULT_EXIT_CODES[result['status']][0])
            if type(code) is not int or code not in recipes.RESULT_EXIT_CODES[result['status']]:
                raise recipes.ContractError('Runtime status and exit code disagree')
            attempt['status'] = result['status']
            attempt['reason'] = result.get('reason') or result.get('reproduction', {}).get('reason') or 'Recorded attempt.'
            path = results / entry['id'] / 'result.json'
            if os.path.lexists(path):
                verify_result_package(path)
                observed, bound, recorded = _read_attempt(path, entry['role'], None)
                recipes._same(bound, plan['recipe'], 'attempt recipe')
                recipes._same(observed['target'], plan['targets'][entry['role']], 'attempt target')
                recipes._same(recorded['status'], result['status'], 'attempt terminal status')
                original_id = recorded['attempt']['id']
                if original_id in observed_attempt_ids:
                    raise recipes.ContractError('A runtime attempt identity cannot supply multiple repetitions')
                observed_attempt_ids.add(original_id)
                attempt['result'] = str(path)
            elif result['status'] in ('completed', 'experiment_failed'):
                raise recipes.ContractError('Runtime returned an experiment outcome without a verified package')
            if result['status'] != 'completed':
                stop_exit = code
                break
        except (Exception, KeyboardInterrupt, SystemExit) as exc:
            interrupted = isinstance(exc, (KeyboardInterrupt, SystemExit))
            stop_exit = (exc.code if isinstance(exc, SystemExit) and exc.code in (130, 143)
                         else 130 if interrupted else 3)
            attempt.update(status='interrupted' if interrupted else 'harness_failed',
                           reason=f'{type(exc).__name__}: {exc}; original work and any partial package retained.')
            break
        finally:
            # Replace only our newly created ledger; original attempt packages stay immutable.
            temporary = results / 'attempts.pending.json'
            _write(temporary, attempts)
            os.replace(temporary, results / 'attempts.json')
    for attempt in attempts:
        if attempt['status'] == 'not_run' and stop_exit:
            attempt['reason'] = 'Earlier attempt did not complete; comparison stopped without retry.'
    temporary = results / 'attempts.pending.json'
    _write(temporary, attempts)
    os.replace(temporary, results / 'attempts.json')
    from recipe_comparison_report import build_comparison_report
    report = build_comparison_report(plan, attempts, results / 'report')
    return {'schema': PLAN_SCHEMA, 'status': 'recorded', 'exit_code': stop_exit,
            'report': str(results / 'report/comparison.json'),
            'performance': report.get('performance', {'qualification': 'not_assessed'})}
