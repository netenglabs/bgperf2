# Copyright (C) 2026 bgperf2 contributors. Apache-2.0.
"""Bounded recipe reduction and evidence classification; no runtime imports."""
import copy
import hashlib
import json
import math
from pathlib import Path

import recipes

SCHEMA = 'bgperf2/minimization-plan/v1alpha1'
STRATEGY = 'greedy-coordinate/v1'
PROJECTION = 'single-cell-per-peer/v1'
DIMENSIONS = ('peers', 'routes')
MAX_TRIALS = 256
MAX_TIMEOUT = 3600


def shape(recipe):
    return dict(peers=recipe['resolved']['neighbors'], routes=recipe['resolved']['prefixes_per_peer'])


def _finite(value, *, positive=False):
    try:
        return (not isinstance(value, bool) and isinstance(value, (int, float))
                and math.isfinite(value) and (value > 0 if positive else value >= 0))
    except OverflowError:
        return False


def selected_assertions(recipe, name):
    from recipe_assertions import default_assertions
    spec = default_assertions(recipe, include_prefixes=name == 'observer.prefixes')
    spec['assertions'] = [item for item in spec['assertions'] if item['name'] == name]
    if len(spec['assertions']) != 1:
        raise recipes.ContractError('Select one supported named assertion; performance predicates are unavailable')
    return spec


def validate_plan(plan):
    recipes._keys(plan, ('schema', 'recipe', 'assertion', 'dimensions', 'minimum',
                         'max_trials', 'timeout', 'strategy', 'projection'), where='minimization plan')
    recipes._same(plan['schema'], SCHEMA, 'minimization schema')
    recipes._same(plan['strategy'], STRATEGY, 'minimization strategy')
    recipes._same(plan['projection'], PROJECTION, 'minimization projection')
    recipes._integer(plan['max_trials'], 'max_trials', 3)
    if plan['max_trials'] > MAX_TRIALS:
        raise recipes.ContractError('max_trials exceeds 256, including baseline and confirmation')
    if not _finite(plan['timeout'], positive=True) or plan['timeout'] > MAX_TIMEOUT:
        raise recipes.ContractError('timeout must be finite and positive, at most 3600 seconds')
    dims = plan['dimensions']
    if (not isinstance(dims, list) or not dims or len(dims) > 2
            or any(not isinstance(item, str) or item not in DIMENSIONS for item in dims)
            or len(set(dims)) != len(dims)):
        raise recipes.ContractError('dimensions must select unique peers and/or routes in search order')
    recipes._keys(plan['minimum'], DIMENSIONS, where='minimum')
    for dim in DIMENSIONS:
        recipes._integer(plan['minimum'][dim], 'minimum.' + dim, 1)
    recipes.validate_recipe(plan['recipe'])
    original = shape(plan['recipe'])
    if any(plan['minimum'][dim] > original[dim] for dim in DIMENSIONS):
        raise recipes.ContractError('minimum must not exceed the original dimension')
    recipes._text(plan['assertion'], 'assertion')
    selected_assertions(plan['recipe'], plan['assertion'])
    from recipe_prefixes import validate_selection
    validate_selection(plan['recipe'], plan['assertion'] == 'observer.prefixes')
    return plan


def make_plan(recipe, *, assertion, dimensions=('peers', 'routes'), min_peers=1,
              min_routes=1, max_trials=20, timeout=120):
    if not isinstance(dimensions, (list, tuple)) or len(dimensions) > 2:
        raise recipes.ContractError('dimensions must be a bounded list of peers and/or routes')
    plan = dict(schema=SCHEMA, recipe=copy.deepcopy(recipe), assertion=assertion,
                dimensions=list(dimensions), minimum=dict(peers=min_peers, routes=min_routes),
                max_trials=max_trials, timeout=timeout, strategy=STRATEGY, projection=PROJECTION)
    validate_plan(plan)
    return plan


def candidate_recipe(original, peers, routes):
    """Project only the selected cell; retain the untouched original separately.

    A reduction changes source/selection/legacy and ordinal/repetition/seed
    metadata explicitly. Immutable roles and resolved controls other than the
    two dimensions and projection metadata retain their exact meanings.
    """
    recipes._integer(peers, 'candidate peers', 1)
    recipes._integer(routes, 'candidate routes', 1)
    recipes.validate_recipe(original)
    before = shape(original)
    if peers > before['peers'] or routes > before['routes']:
        raise recipes.ContractError('A minimization candidate cannot increase either dimension')
    if dict(peers=peers, routes=routes) == before:
        return copy.deepcopy(original)
    tests = recipes._source_tests(original['source']['text'])
    selected = next(item for item in tests if item['name'] == original['selection']['test'])
    test = dict(name=selected['name'], neighbors=[peers], prefixes=[routes],
                prefix_scope='per-peer', filter_test=[None], monitor='sink',
                targets=[copy.deepcopy(original['source']['raw_target'])])
    if 'pin' in selected:
        test['pin'] = selected['pin']
    # JSON is a supported YAML subset and provides deterministic source bytes.
    text = json.dumps({'tests': [test]}, sort_keys=True, indent=2, allow_nan=False) + '\n'
    from batch_cells import construct_batch_cells, expand_target_versions, batch_cell_id, batch_cell_key
    cell = construct_batch_cells(test, expand_target_versions(test['targets']),
        repetitions=1, prefix_resolver=recipes.resolve_prefix_scope,
        path_diversity=recipes.DEFAULT_PATH_DIVERSITY, receivers=recipes.DEFAULT_RECEIVERS,
        churn_prefixes=recipes.DEFAULT_CHURN_PREFIXES, churn_bursts=recipes.DEFAULT_CHURN_BURSTS,
        policy_reload_blocks=recipes.DEFAULT_POLICY_RELOAD_BLOCKS,
        pin=recipes._recipe_pin(test['pin']) if 'pin' in test else None, monitor='sink')[0]
    key = batch_cell_key(batch_cell_id(test['name'], cell))
    result = recipes._recipe(text, test['name'], key, original['engine']['revision'],
                             original['roles'], original['reproduction']['question'],
                             original['reproduction']['expected_outcome'])
    recipes.validate_recipe(result)
    fixed = {key: value for key, value in original['resolved'].items()
             if key not in ('neighbors', 'prefixes_per_peer', 'ordinal', 'repetition')}
    actual = {key: value for key, value in result['resolved'].items()
              if key not in ('neighbors', 'prefixes_per_peer', 'ordinal', 'repetition')}
    recipes._same(actual, fixed, 'candidate fixed resolved controls')
    for field in ('roles', 'engine', 'resources', 'inputs', 'completion', 'reproduction'):
        recipes._same(result[field], original[field], 'candidate.' + field)
    recipes._same(result['source']['raw_target'], original['source']['raw_target'], 'candidate raw target')
    return result


def classify_result(plan, candidate, result_path):
    """Recheck one original package; only the selected observed failure retains."""
    validate_plan(plan)
    dims = shape(candidate)
    recipes._same(candidate, candidate_recipe(plan['recipe'], **dims), 'candidate recipe')
    from recipe_assertions import evaluate_assertions, _load as load_artifact
    from recipe_investigation import _load
    from recipe_results import _regular_bytes, verify_result_package
    from recipe_targets import supplied_target
    path = Path(result_path)
    before = _regular_bytes(path.parent, path.name)
    verify_result_package(path)
    manifest = _load(path.parent, path.name)
    recipes._same(_load(path.parent, 'recipe.json'), candidate, 'result recipe')
    spec = selected_assertions(candidate, plan['assertion'])
    row = evaluate_assertions(spec, candidate, path)['assertions'][0]
    references = {item['path']: item for item in manifest['artifacts'] if item['availability'] == 'present'}
    values = {}
    reasons = []
    observed_images = {role: None for role in candidate['roles']}
    for name in ('target', 'runtime', 'execution-budget', 'prerequisites'):
        value, reason = load_artifact(path.parent, 'work/' + name + '.json', references)
        values[name] = value
        if value is None:
            reasons.append(reason)
    if values['target'] is not None:
        recipes._same(values['target'], supplied_target(candidate, candidate['roles']['target']['image']),
                      'minimization requires the recipe supplied-image target; overrides are unsupported')
    runtime, budget, prereq = values['runtime'], values['execution-budget'], values['prerequisites']
    if runtime is not None and (type(runtime.get('cleanup_errors')) is not list or runtime['cleanup_errors']):
        reasons.append('Owned cleanup is not explicitly complete.')
    if manifest['status'] not in ('completed', 'experiment_failed'):
        reasons.append('Operational refusal, interruption or uncertainty cannot preserve the predicate.')
    if budget is not None:
        start, end, elapsed = (budget.get(key) for key in ('started_monotonic_s', 'ended_monotonic_s', 'elapsed_seconds'))
        if (budget.get('schema') != 'bgperf2/execution-budget/v1alpha1' or budget.get('scope') != 'worker'
                or not _finite(budget.get('timeout_seconds'), positive=True)
                or budget['timeout_seconds'] != plan['timeout']
                or budget.get('completed_within_budget') is not True
                or not _finite(start, positive=True) or not _finite(end, positive=True)
                or not _finite(elapsed) or end < start or elapsed > plan['timeout']
                or not math.isclose(end-start, elapsed, rel_tol=1e-6, abs_tol=1e-6)):
            reasons.append('The selected finite worker budget and clock anchors are not satisfied.')
    if prereq is not None:
        checks = prereq.get('checks', [])
        for role, identity in candidate['roles'].items():
            matches = [item for item in checks if isinstance(item, dict) and item.get('name') == 'image.' + role] if isinstance(checks, list) else []
            if len(matches) != 1 or matches[0].get('status') != 'pass':
                reasons.append('The observed ' + role + ' identity is unavailable.')
                continue
            details = matches[0].get('details')
            if not isinstance(details, dict) or details.get('requested') != identity['image']:
                raise recipes.ContractError('Observed role request differs from frozen candidate')
            image = details.get('image_id')
            if image is None:
                reasons.append('The observed ' + role + ' image ID is unavailable.')
                continue
            recipes._match(image, recipes._IMAGE, 'observed image', 'an immutable image ID')
            if not image.startswith('sha256:'):
                raise recipes.ContractError('Observed image ID must be a full sha256 image ID')
            if identity['image'].startswith('sha256:'):
                recipes._same(image, identity['image'], 'observed ' + role + ' image')
            elif identity['image'] not in (details.get('repo_digests') or []):
                raise recipes.ContractError('Observed repository digest differs from frozen candidate')
            observed_images[role] = image
    if row['status'] == 'unmeasured':
        reasons.append('Selected assertion is unmeasured: ' + row['reason'])
    classification = 'inconclusive' if reasons else 'preserved' if row['status'] == 'failed' else 'not_preserved'
    if _regular_bytes(path.parent, path.name) != before:
        raise recipes.ContractError('Result manifest changed during minimization classification')
    return dict(classification=classification, attempt_id=manifest['attempt']['id'],
                recipe_sha256=recipes.recipe_sha256(candidate), result_sha256=hashlib.sha256(before).hexdigest(),
                observed_images=observed_images, assertion=row, reason=' '.join(reasons) if reasons else
                'The selected assertion failed.' if classification == 'preserved' else 'The selected assertion passed.')


def summarize(plan, trials):
    """Replay bounded observations without assuming monotonicity or a minimum."""
    validate_plan(plan)
    if not isinstance(trials, list) or len(trials) > plan['max_trials']:
        raise recipes.ContractError('Invalid or oversized trial journal')
    original = shape(plan['recipe'])
    best = dict(original)
    visited, identities = set(), set()
    terminal = None
    confirmed = False
    baseline = False
    baseline_images = None

    def request(index):
        if terminal is not None:
            return None
        if not baseline:
            point, phase = original, 'baseline'
        else:
            point, phase = best, 'confirmation'
            if index < plan['max_trials']:
                for dim in plan['dimensions']:
                    value, floor = best[dim], plan['minimum'][dim]
                    for target in dict.fromkeys((floor, (value + floor)//2, value-1)):
                        if not floor <= target < value:
                            continue
                        proposal = dict(best, **{dim: target})
                        candidate = candidate_recipe(plan['recipe'], **proposal)
                        if recipes.recipe_sha256(candidate) not in visited:
                            point, phase = proposal, 'search'
                            break
                    if phase == 'search':
                        break
        recipe = candidate_recipe(plan['recipe'], **point)
        return dict(index=index, phase=phase, **point, recipe_sha256=recipes.recipe_sha256(recipe))

    for index, trial in enumerate(trials, 1):
        recipes._keys(trial, ('request', 'assessment'), where='trial')
        expected = request(index)
        if expected is None:
            raise recipes.ContractError('A terminal minimization cannot record another trial')
        recipes._same(trial['request'], expected, 'trial request')
        assessment = trial['assessment']
        recipes._keys(assessment, ('classification', 'attempt_id', 'recipe_sha256', 'result_sha256',
                                   'observed_images', 'assertion', 'reason'), where='assessment')
        kind = recipes._choice(assessment['classification'], ('preserved', 'not_preserved', 'inconclusive'), 'classification')
        recipes._text(assessment['attempt_id'], 'original attempt ID')
        if assessment['attempt_id'] in identities:
            raise recipes.ContractError('Every trial and confirmation requires a distinct original attempt ID')
        identities.add(assessment['attempt_id'])
        recipes._same(assessment['recipe_sha256'], expected['recipe_sha256'], 'assessment recipe')
        recipes._match(assessment['result_sha256'], recipes._HEX64, 'result_sha256', 'a SHA-256 digest')
        recipes._text(assessment['reason'], 'assessment reason')
        images = assessment['observed_images']
        recipes._keys(images, ('target', 'generator', 'observer'), where='observed images')
        for role, image in images.items():
            if image is None:
                if kind != 'inconclusive':
                    raise recipes.ContractError('Decisive trials require every observed image identity')
            elif not isinstance(image, str) or not image.startswith('sha256:') or not recipes._HEX64.fullmatch(image[7:]):
                raise recipes.ContractError('Observed image identity must be a full sha256 image ID')
            elif baseline_images is not None:
                recipes._same(image, baseline_images[role], 'observed ' + role + ' changed from baseline')
        if index == 1:
            baseline_images = copy.deepcopy(images)
        row = assessment['assertion']
        if not isinstance(row, dict) or row.get('name') != plan['assertion']:
            raise recipes.ContractError('The selected assertion cannot change between trials')
        definition = selected_assertions(candidate_recipe(plan['recipe'], expected['peers'], expected['routes']),
                                         plan['assertion'])['assertions'][0]
        recipes._keys(row, (*definition, 'status', 'observed', 'evidence', 'reason'), where='assertion outcome')
        recipes._same({name: row[name] for name in definition}, definition, 'selected assertion definition')
        if not isinstance(row['evidence'], list):
            raise recipes.ContractError('Assertion evidence must remain a list')
        recipes._text(row['reason'], 'assertion outcome reason')
        recipes._choice(row.get('status'), ('failed', 'passed', 'unmeasured'), 'selected assertion status')
        if kind in ('preserved', 'not_preserved'):
            recipes._same(row['status'], 'failed' if kind == 'preserved' else 'passed', 'selected assertion outcome')
        visited.add(expected['recipe_sha256'])
        phase = expected['phase']
        if phase == 'baseline':
            if kind == 'preserved':
                baseline = True
            else:
                terminal = 'original_not_reproduced' if kind == 'not_preserved' else 'baseline_inconclusive'
        elif phase == 'search':
            if kind == 'preserved':
                best = {dim: expected[dim] for dim in DIMENSIONS}
            elif kind == 'inconclusive':
                terminal = 'search_inconclusive'
        elif kind == 'preserved':
            terminal, confirmed = 'complete', True
        else:
            terminal = 'confirmation_not_preserved' if kind == 'not_preserved' else 'confirmation_inconclusive'
    next_item = request(len(trials)+1)
    smaller = best != original and baseline
    conclusion = ('confirmed_smaller' if smaller else 'no_reduction') if confirmed else terminal or 'unconfirmed'
    return dict(state=terminal or 'ready', conclusion=conclusion, best=best, confirmed=confirmed,
                next=next_item, trials_recorded=len(trials), smaller_observed=smaller,
                search_budget_exhausted=bool(baseline and len(trials) >= plan['max_trials']-1),
                limitation='Greedy declared proposals only; no monotonicity, global-minimum, bug-cause or performance claim.')


if __name__ == '__main__':
    from minimization_cli import main
    raise SystemExit(main())
