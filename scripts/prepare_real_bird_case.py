#!/usr/bin/env python3
# Copyright (C) 2026 bgperf2 contributors. Apache-2.0.
"""Prepare one real BIRD functional case locally; never execute the handoff.

The two upstream revisions are a neutral release transition, not a bug/fix.
Only the explicit BSD alias packaging transformation changes their source.
"""
import argparse
import copy
import json
from pathlib import Path
import shlex
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import recipes
import recipe_handoff as handoff
import recipe_source_range as ranges
from scripts import bird_alias_source

GOOD = '62d6c38c2ddfbd74119641c7da251b6b7578c7e7'
BAD = '1d201ed0360c749dfe3d3b3b079329e7148159cd'
BIRD = 'sha256:db0a8e144635b1d4b9f81f24ee78f11383c5b0cbd79f10353edcb8452e9af423'
SINK = 'sha256:311317014fc98e2cadf46941b4b23dab9dd724281dd50167a0f9187d8ac08f19'
QUESTION = ('Do the packaging-adapted BIRD pre-2.19.2 and 2.19.2 revisions each '
            'complete one peer x 100 IPv4 prefixes with exact observer count? '
            'Neutral functional validation; no bug or fix is alleged.')
CAPABILITIES = ('session_establishment', 'injection_completion',
                'observer_route_count', 'experiment_completion')
SELECTED = ('build_baseline', 'check_baseline', 'reproduce', 'verify_reproduction',
            'export_assertions', 'check_reproduction_assertions', 'build_candidate',
            'investigate', 'verify_investigation', 'rebuild_investigation')


def save(path, value):
    with Path(path).open('x') as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True) + '\n')


def execution_scope(graph, output):
    """Narrow a general handoff to this neutral functional case, not a search."""
    steps = {step['id']: copy.deepcopy(step) for step in graph['steps']}
    selected = [steps[name] for name in SELECTED]
    for step in selected:
        if step['id'] == 'export_assertions':
            for capability in CAPABILITIES:
                step['argv'] += ['--capability', capability]
    python, cli = str(ROOT / 'venv/bin/python'), str(ROOT / 'recipes.py')
    results, builds = output / 'results', output / 'builds'
    for side in ('baseline', 'candidate'):
        selected.append({'id': 'assert_' + side, 'mode': 'offline',
            'argv': [python, cli, 'assertions-check', str(builds / 'assertions.json'),
                     '--result', str(results / 'investigation' / side / 'result.json')],
            'execution': 'not_requested'})
    selected.append({'id': 'verify_rebuilt', 'mode': 'offline',
        'argv': [python, cli, 'investigation-verify',
                 str(results / 'investigation-rebuilt/investigation.json')],
        'execution': 'not_requested'})
    return {'execution': 'not_requested', 'authorization': 'pending',
        'source_builds': 2, 'workers': 3, 'build_timeout_seconds': 1200,
        'worker_timeout_seconds': 120, 'build_worker_seconds_ceiling': 2760,
        'bisection_workers': 0, 'comparison_workers': 0, 'retries': 0,
        'performance_policy': 'disabled', 'calibration': 'deferred',
        'steps': selected,
        'excluded_handoff_steps': [s['id'] for s in graph['steps'] if s['id'] not in SELECTED]}


def prepare(source, output):
    output = handoff._safe(output)
    source = handoff._safe(source)
    if handoff._overlap(output, ROOT) or handoff._overlap(output, source):
        raise recipes.ContractError('Choose a fresh case outside source and engine checkouts')
    output.mkdir(mode=0o700)
    mapping = bird_alias_source.prepare(source, GOOD, BAD, output / 'packaging')
    revision = ranges.LocalGit().run(ROOT, 'rev-parse', 'HEAD').decode().strip()
    recipe = recipes.export_recipe(ROOT / 'examples/recipes/synthetic-ipv4.yaml',
        'synthetic-ipv4', 'f94a3878b2dad49e', engine_revision=revision,
        roles={'target': {'adapter': 'bird', 'image': BIRD},
               'generator': {'adapter': 'bird', 'image': BIRD},
               'observer': {'adapter': 'sink', 'image': SINK}},
        question=QUESTION, expected_outcome='experiment_completed')
    save(output / 'recipe.json', recipe)
    manifest = ranges.prepare_range(recipe, source_root=output / 'packaging/source',
        good=mapping['revisions'][0]['derived'], bad=mapping['revisions'][1]['derived'],
        toolchain_image=BIRD, runtime_image=BIRD, output_dir=output / 'range',
        instrumentation='optimized', cflags='-O2 -g', predicate='assertions',
        max_trials=4, worker_timeout=120, build_timeout=1200)
    paths = [output / 'range' / row['build_plan'] for row in manifest['candidates']]
    handoff.prepare_handoff(output / 'range/source-range.json',
        baseline_build_plan=paths[0], candidate_build_plan=paths[1],
        build_root=output / 'builds', work_root=output / 'work',
        results_root=output / 'results', session=output / 'unused-search',
        output_dir=output / 'handoff')
    graph = recipes.read_document(output / 'handoff/commands.json')
    scope = execution_scope(graph, output)
    save(output / 'execution-scope.json', scope)
    with (output / 'CASE.md').open('x') as stream:
        stream.write(render_case(scope, recipe, revision))
    verification = verify(output)
    save(output / 'verification.json', verification)
    return verification


def render_case(scope, recipe, revision):
    lines = ['# Real BIRD neutral functional validation', '', QUESTION, '',
        'Execution approval is pending. The commands below have NOT run.', '',
        'Read the authoritative [case plan](' + str(ROOT / 'docs/plans/real-bird-maintainer-validation.md') + ').', '',
        'Engine revision: `' + revision + '`. Recipe SHA-256: `' + recipes.recipe_sha256(recipe) + '`.', '',
        '[Verification](verification.json), [packaging map](packaging/packaging.json),',
        '[source range](range/REPORT.md), [full handoff](handoff/RUNBOOK.md),',
        '[selected execution scope](execution-scope.json).', '',
        'The full handoff also contains a bisection graph. It is EXCLUDED: both endpoints are expected to pass.', '',
        'At most two 1200-second builds and three 120-second serial workers (2760 budget seconds).',
        'Prerequisite, collection and cleanup overhead are separate bounded operations; this is not a wall-clock guarantee.', '',
        'Stop after any refused/failed/inconclusive/interrupted action or rejected review. No retries.',
        'Review baseline build/reproduction before candidate build; review both returned packages and cleanup.', '',
        '## Selected commands in order', '']
    for step in scope['steps']:
        lines += ['### ' + step['id'], '', '```sh', shlex.join(step['argv']), '```', '']
    return '\n'.join(lines)


def verify(output):
    """Reconstruct the selected approval scope, never trusting edited commands."""
    output = handoff._safe(output)
    mapping = bird_alias_source.verify(output / 'packaging')
    recipes._same([row['upstream'] for row in mapping['revisions']], [GOOD, BAD],
                  'selected upstream source history')
    range_receipt = ranges.verify_preparation(output / 'range/source-range.json')
    handoff_receipt = handoff.verify_handoff(output / 'handoff/handoff.json')
    prepared = handoff._load(output / 'range/source-range.json')
    recipes._same(prepared['source_root'], str(output / 'packaging/source'), 'packaged source root')
    recipes._same([row['revision'] for row in prepared['candidates']],
                  [row['derived'] for row in mapping['revisions']], 'selected derived history')
    recipe = handoff._load(output / 'recipe.json')
    revision = ranges.LocalGit().run(ROOT, 'rev-parse', 'HEAD').decode().strip()
    expected = recipes.export_recipe(ROOT / 'examples/recipes/synthetic-ipv4.yaml',
        'synthetic-ipv4', 'f94a3878b2dad49e', engine_revision=revision,
        roles={'target': {'adapter': 'bird', 'image': BIRD},
               'generator': {'adapter': 'bird', 'image': BIRD},
               'observer': {'adapter': 'sink', 'image': SINK}},
        question=QUESTION, expected_outcome='experiment_completed')
    recipes._same(recipe, expected, 'selected case recipe and current engine revision')
    recipes._same(prepared['recipe'], recipe, 'prepared case recipe')
    manifest = handoff._load(output / 'handoff/handoff.json')
    recipes._same(manifest['input_bindings']['source_range']['path'],
                  str(output / 'range/source-range.json'), 'selected handoff source range')
    recipes._same(handoff._load(output / 'handoff/inputs/recipe.json'), recipe,
                  'selected runtime recipe')
    plan = handoff._load(output / 'range/bisection-plan.json')
    recipes._same(handoff._load(output / 'handoff/inputs/bisection-plan.json'), plan,
                  'selected handoff preparation plan')
    recipes._same(manifest['destinations'], {name: str(output / suffix) for name, suffix in
        (('build_root', 'builds'), ('work_root', 'work'), ('results_root', 'results'),
         ('session', 'unused-search'))}, 'case execution destinations')
    for side in ('baseline', 'candidate'):
        build = handoff._load(output / f'handoff/inputs/{side}-build-plan.json')
        index = 0 if side == 'baseline' else 1
        recipes._same(build, plan['candidates'][index]['build_plan'], 'selected complete build plan')
        recipes._same(manifest['input_bindings'][side + '_build_plan']['path'],
                      str(output / 'range' / prepared['candidates'][index]['build_plan']),
                      'selected build-plan path')
        recipes._same(build['source']['commit'], mapping['revisions'][index]['derived'], 'selected build source')
        for field, value in (('toolchain_image', BIRD), ('runtime_image', BIRD),
                             ('instrumentation', 'optimized'), ('cflags', '-O2 -g'),
                             ('configure_flags', []), ('network', 'none')):
            recipes._same(build[field], value, 'selected build ' + field)
    for field, value in (('max_trials', 4), ('worker_timeout', 120), ('build_timeout', 1200)):
        recipes._same(plan[field], value, 'selected preparation ' + field)
    if manifest['comparison'] is not None:
        raise recipes.ContractError('This case excludes comparison workers')
    graph = handoff._load(output / 'handoff/commands.json')
    scope = execution_scope(graph, output)
    recipes._same(handoff._load(output / 'execution-scope.json'), scope, 'selected execution scope')
    if handoff._bytes(output / 'CASE.md').decode() != render_case(scope, recipe, revision):
        raise recipes.ContractError('Selected case runbook differs')
    absent = all(not (output / name).exists() for name in ('builds', 'work', 'results', 'unused-search'))
    if not absent:
        raise recipes.ContractError('Execution destinations exist; this is no longer an unexecuted approval packet')
    return {'valid': True, 'packaging': mapping, 'source_range': range_receipt,
        'handoff': handoff_receipt, 'runtime_destinations_absent': absent,
        'engine_revision': revision, 'recipe_sha256': recipes.recipe_sha256(recipe)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source')
    parser.add_argument('--output')
    parser.add_argument('--verify', metavar='CASE_DIRECTORY')
    args = parser.parse_args()
    try:
        if args.verify:
            if args.source or args.output:
                parser.error('--verify cannot be combined with preparation arguments')
            result = verify(args.verify)
        else:
            if not args.source or not args.output:
                parser.error('preparation requires --source and --output')
            result = prepare(args.source, args.output)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, recipes.ContractError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
