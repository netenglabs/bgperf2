#!/usr/bin/env python3
# Copyright (C) 2026 bgperf2 contributors. Apache-2.0.
"""Freeze a local maintainer action handoff; never execute its commands.

Preparation verifies selected source plans using local read-only Git inspection.
Neither preparation nor verification probes Docker, tools, capacity or runtime
readiness, acquires objects/images, builds source, or starts a worker.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shlex

import recipes
import recipe_bisection as bisection
import recipe_targets as targets
from recipe_results import _regular_file

SCHEMA = 'bgperf2/maintainer-handoff/v1alpha1'
ROOT = Path(__file__).resolve().parent
MAX_JSON = 32 * 1024 * 1024
INPUTS = ('recipe.json', 'baseline-build-plan.json', 'candidate-build-plan.json', 'bisection-plan.json')
FILES = {'handoff.json', 'commands.json', 'RUNBOOK.md', *(f'inputs/{name}' for name in INPUTS)}


def _json(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _safe(value):
    path = Path(value)
    if not path.is_absolute() or '..' in path.parts:
        raise recipes.ContractError('Handoff paths must be absolute and without parent traversal')
    for part in (path, *path.parents):
        if part.is_symlink():
            raise recipes.ContractError('Handoff paths must not contain symlinks: ' + str(part))
    return path.resolve(strict=False)


def _bytes(path):
    path = _safe(path)
    with _regular_file(path.parent, path.name) as stream:
        data = stream.read(MAX_JSON + 1)
    if len(data) > MAX_JSON:
        raise recipes.ContractError('Handoff input exceeds the 32 MiB inspection bound')
    return data


def _load(path):
    return json.loads(_bytes(path).decode('utf-8'), object_pairs_hook=recipes._pairs,
                      parse_constant=recipes._nonfinite)


def _write(path, data):
    with path.open('xb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _overlap(left, right):
    return left == right or left in right.parents or right in left.parents


def _sources(source_range, baseline, candidate):
    from recipe_source_range import verify_preparation
    paths = {name: _safe(value) for name, value in
             (('source_range', source_range), ('baseline_build_plan', baseline), ('candidate_build_plan', candidate))}
    if verify_preparation(paths['source_range']).get('valid') is not True:
        raise recipes.ContractError('Source-range preparation did not verify')
    preparation = _load(paths['source_range'])
    relative = recipes._artifact_path(preparation['bisection_plan'], 'prepared bisection plan')
    paths['bisection_plan'] = _safe(paths['source_range'].parent / relative)
    data = {name: _bytes(path) for name, path in paths.items()}
    plan = bisection.validate_plan(_load(paths['bisection_plan']))
    recipe = plan['recipe']
    recipes._same(preparation['recipe'], recipe, 'prepared recipe')
    builds = {label: targets.validate_build_plan(_load(paths[label + '_build_plan']))
              for label in ('baseline', 'candidate')}
    if not any(builds['baseline'] == row['build_plan'] for row in plan['candidates']):
        raise recipes.ContractError('Select the baseline build plan explicitly from the prepared range')
    for label, build in builds.items():
        recipes._same(build['recipe'], recipe, label + ' recipe')
        _safe(build['source_root'])
        actual, _, _ = targets._snapshot(build['source_root'], build['source']['requested_revision'],
                                         build['source']['include_dirty'])
        recipes._same(actual, build['source'], label + ' current source snapshot')
    bindings = {name: {'path': str(path), 'sha256': _sha(data[name])} for name, path in paths.items()}
    return plan, builds, bindings, data['bisection_plan'], preparation


def _original_source_root(preparation):
    """Protect the original lexical checkout without opening it after export."""
    path = Path(preparation['source_root'])
    if not path.is_absolute() or '..' in path.parts:
        raise recipes.ContractError('Prepared original source root must be absolute without parent traversal')
    return Path('/' + str(path).lstrip('/'))


def _comparison(repetitions, order, seed):
    if repetitions is None:
        if order != 'alternating' or seed is not None:
            raise recipes.ContractError('Comparison options require explicit comparison repetitions')
        return None
    recipes._integer(repetitions, 'comparison repetitions', 1)
    if repetitions > 100:
        raise recipes.ContractError('Comparison repetitions exceed the supported bound of 100')
    recipes._choice(order, ('alternating', 'shuffle'), 'comparison order')
    if order == 'shuffle':
        recipes._integer(seed, 'comparison shuffle seed')
    elif seed is not None:
        raise recipes.ContractError('A comparison seed applies only to shuffle order')
    return {'repetitions': repetitions, 'order': order, 'seed': seed}


def _destinations(values, output, protected, *, fresh):
    recipes._keys(values, ('build_root', 'work_root', 'results_root', 'session'), where='destinations')
    roots = {name: _safe(value) for name, value in values.items()}
    selected = [output, *roots.values()]
    if any(_overlap(a, b) for i, a in enumerate(selected) for b in selected[i + 1:]):
        raise recipes.ContractError('Handoff, build, work, results and session roots must be distinct and nonnested')
    for path in selected:
        if any(_overlap(path, source) for source in protected):
            raise recipes.ContractError('Handoff destination overlaps selected source or input evidence: ' + str(path))
        if fresh and os.path.lexists(path):
            raise recipes.ContractError('Choose fresh handoff/build/work/results/session roots: ' + str(path))
        if not fresh and os.path.lexists(path) and not path.is_dir():
            raise recipes.ContractError('A declared destination is no longer a directory: ' + str(path))
        ancestor = path.parent
        while not os.path.lexists(ancestor):
            ancestor = ancestor.parent
        if not ancestor.is_dir():
            raise recipes.ContractError('A destination ancestor is not a directory: ' + str(ancestor))
    return {name: str(path) for name, path in roots.items()}


def _budgets(plan, comparison):
    extra = 2 * comparison['repetitions'] if comparison else 0
    return {'worker_timeout_seconds': plan['worker_timeout'], 'build_timeout_seconds': plan['build_timeout'],
            'bisection_max_trials': plan['max_trials'], 'bisection_candidate_count': len(plan['candidates']),
            'initial_source_builds': 2, 'reproduction_workers': 1, 'investigation_workers': 2,
            'comparison_workers': extra,
            'maximum_worker_invocations': 3 + extra + plan['max_trials'],
            'maximum_source_build_invocations': 2 + len(plan['candidates']),
            'scope': 'Ceilings for the listed workflow, not permission to execute or retry. Bisection uses its existing exact-plan build cache.'}


def _differences(builds):
    return [{'field': name, 'baseline': copy.deepcopy(builds['baseline'][name]),
             'candidate': copy.deepcopy(builds['candidate'][name])}
            for name in ('source_root', 'source', 'toolchain_image', 'runtime_image', 'instrumentation',
                         'cflags', 'configure_flags', 'build_recipe', 'network')
            if builds['baseline'][name] != builds['candidate'][name]]


def _graph(location, destinations, plan, builds, comparison):
    packet = Path(location)
    build, work, results, session = (Path(destinations[name]) for name in
                                    ('build_root', 'work_root', 'results_root', 'session'))
    python = str(ROOT / 'venv/bin/python')
    recipe_cli, bisect_cli = str(ROOT / 'recipes.py'), str(ROOT / 'recipe_bisection.py')
    recipe = str(packet / 'inputs/recipe.json')
    target = {label: str(build / label / 'target.json') for label in ('baseline', 'candidate')}
    timeout, build_timeout = str(plan['worker_timeout']), str(plan['build_timeout'])
    steps = []
    def add(name, argv, depends=(), *, mode='offline', condition=None):
        steps.append({'id': name, 'argv': list(map(str, argv)), 'depends_on': list(depends), 'mode': mode,
                      'condition': condition or 'Inspect this command and its actual result before any later action.',
                      'execution': 'not_requested'})
    for label in ('baseline', 'candidate'):
        add('build_' + label, [python, recipe_cli, 'target-build', packet / f'inputs/{label}-build-plan.json',
            '--output-dir', build / label, '--timeout', build_timeout], mode='explicit_build',
            condition='Requires separate source-trust/execution authorization and existing exact toolchain/runtime images. Inspect retained build outcome; do not retry an uncertain build.')
    add('check_baseline', [python, recipe_cli, 'check', recipe, '--target', target['baseline'],
        '--workdir', work / 'reproduction', '--results-dir', results / 'reproduction'], ['build_baseline'], mode='explicit_read_only_probes')
    add('reproduce', [python, recipe_cli, 'run', recipe, '--target', target['baseline'],
        '--workdir', work / 'reproduction', '--results-dir', results / 'reproduction',
        '--timeout', timeout, '--diagnostics', 'basic'], ['check_baseline'], mode='explicit_worker',
        condition='A target crash may legitimately return exit 4 with experiment_failed/reproduced. Inspect the actual frozen question, status, reproduction evidence and owned cleanup; this dependency is not automatic permission to continue.')
    add('verify_reproduction', [python, recipe_cli, 'result-verify', results / 'reproduction/result.json'], ['reproduce'])
    assertions = build / 'assertions.json'
    add('export_assertions', [python, recipe_cli, 'assertions-export', recipe, '-o', assertions], ['build_baseline'])
    add('check_reproduction_assertions', [python, recipe_cli, 'assertions-check', assertions,
        '--result', results / 'reproduction/result.json'], ['export_assertions', 'verify_reproduction'],
        condition='Inspect named observable assertions separately from reproduction. Exit 4 means failed assertions; exit 5 means inconclusive evidence. Neither is a calibrated performance verdict.')
    add('investigate', [python, recipe_cli, 'investigate', recipe, '--baseline-target', target['baseline'],
        '--candidate-target', target['candidate'], '--workdir', work / 'investigation',
        '--results-dir', results / 'investigation', '--timeout', timeout, '--diagnostics', 'basic'],
        ['build_baseline', 'build_candidate'], mode='explicit_workers',
        condition='Select this separate fresh pair explicitly; both target prerequisites are checked by investigate. Controller stops remain inconclusive; never invent a candidate attempt or retry.')
    add('verify_investigation', [python, recipe_cli, 'investigation-verify', results / 'investigation/report/investigation.json'], ['investigate'])
    add('rebuild_investigation', [python, recipe_cli, 'investigation-rebuild', results / 'investigation/report/investigation.json',
        '--output-dir', results / 'investigation-rebuilt'], ['verify_investigation'])
    if comparison:
        comparison_plan = build / 'comparison-plan.json'
        argv = [python, recipe_cli, 'comparison-plan', recipe, '--baseline-target', target['baseline'],
                '--candidate-target', target['candidate'], '--repetitions', comparison['repetitions'],
                '--order', comparison['order'], '--timeout', timeout, '--diagnostics', 'none', '-o', comparison_plan]
        if comparison['seed'] is not None:
            argv += ['--seed', comparison['seed']]
        add('plan_comparison', argv, ['build_baseline', 'build_candidate'],
            condition='Creates a descriptive plan only after actual target artifacts exist; no calibrated performance policy is enabled.')
        add('compare', [python, recipe_cli, 'compare', comparison_plan, '--workdir', work / 'comparison',
            '--results-dir', results / 'comparison'], ['plan_comparison'], mode='explicit_workers',
            condition='Opt-in descriptive attempts only. Failed or missing observations stay distinct; no dose nomination, reliable detection or quiet-host claim follows.')
        add('verify_comparison', [python, recipe_cli, 'comparison-verify', results / 'comparison/report/comparison.json'], ['compare'])
    add('init_bisection', [python, bisect_cli, 'init', packet / 'inputs/bisection-plan.json', '--session', session])
    add('status_bisection', [python, bisect_cli, 'status', session], ['init_bisection'])
    add('preview_bisection', [python, bisect_cli, 'step', session], ['init_bisection'])
    add('step_bisection', [python, bisect_cli, 'step', session, '--execute'], ['preview_bisection'], mode='explicit_build_and_worker',
        condition='One existing-engine bounded step only, within the frozen trial budget. Inspect status between steps. A pending reservation requires explicit recovery; never repeat its work automatically.')
    add('report_bisection', [python, bisect_cli, 'report', session, '--output', results / 'bisection-report'], ['init_bisection'],
        condition='Choose this fresh report output once after reviewing the intended terminal/pending state; this report command executes no trial.')
    add('verify_bisection', [python, bisect_cli, 'verify', results / 'bisection-report/bisection.json'], ['report_bisection'])
    required_images = {}
    for label, selected in builds.items():
        for role in ('toolchain_image', 'runtime_image'):
            required_images.setdefault(selected[role], []).append(label + '.' + role)
    for role in ('generator', 'observer'):
        required_images.setdefault(plan['recipe']['roles'][role]['image'], []).append(role)
    return {'schema': SCHEMA, 'execution': 'not_requested', 'steps': steps,
            'required_declared_images': [{'reference': image, 'roles': roles, 'local_availability': 'unassessed'}
                                         for image, roles in sorted(required_images.items())],
            'future_targets': {label: {'path': value, 'image': None, 'availability': 'unassessed'} for label, value in target.items()},
            'recovery_guidance': {'status_command': [python, bisect_cli, 'status', str(session)],
                'pending_record': str(session / 'pending.json'),
                'original_result_rule': 'Read the verified pending trial number; the selected original is SESSION/results/tNNNN/result.json. Do not infer no-run from a missing package.',
                'recover_result_prefix': [python, bisect_cli, 'recover', str(session), '--result'],
                'recover_abandon_prefix': [python, bisect_cli, 'recover', str(session), '--abandon-reason'],
                'arguments_required': 'Append the exact existing original result path, or an explicit reviewed abandonment reason. These prefixes are guidance, not executable steps.'}}


def _runbook(manifest, graph, recipe):
    lines = ['# Prepared local maintainer handoff', '', recipe['reproduction']['question'], '',
        'These are reviewed action descriptions, not an executable script or execution authorization.',
        'Source preparation and command bindings are verified locally. Images, host suitability, engine cleanliness, OS tools and authorization remain unassessed.',
        'Commands use future returned target.json artifacts; no target image ID or successful build is invented.', '',
        'The baseline and candidate are explicit selections. A candidate is not assumed to fix the problem.',
        'The original recipe target image is not an extra requirement once the actual target override is selected.', '',
        '## Recorded target/build differences', '',
        'These declared differences are retained, not normalized away. Different instrumentation or build environments can confound descriptive comparisons.', '',
        json.dumps(manifest['target_build_differences'], sort_keys=True), '',
        '## Frozen limits', '', json.dumps(manifest['budgets'], sort_keys=True), '',
        'The bisection plan is retained byte-for-byte, including its predicate, candidate chain and monotonicity assumption.',
        'The optional comparison remains descriptive; performance policy stays disabled and qualification not assessed.', '',
        '## Individual public commands', '']
    for step in graph['steps']:
        lines += ['### ' + step['id'], '',
                  'Requires: ' + (', '.join(step['depends_on']) if step['depends_on'] else 'reviewed frozen inputs') + '.', '',
                  step['condition'], '', '```sh', shlex.join(step['argv']), '```', '']
    recovery = graph['recovery_guidance']
    lines += ['## A stopped search', '', recovery['original_result_rule'], '',
              'Inspect status and the pending reservation before selecting recovery. Recover the original result without rebuilding or rerunning it; abandon only with an explicit reviewed reason.', '',
              'Result recovery command prefix: `' + shlex.join(recovery['recover_result_prefix']) + '`.',
              'Abandonment command prefix: `' + shlex.join(recovery['recover_abandon_prefix']) + '`.',
              recovery['arguments_required'], '',
              '## Location and evidence limits', '',
              'This handoff and prepared source worktrees are location-bound. Reprepare at a new location rather than editing frozen paths.',
              'Verification detects changed input bytes, source snapshots and command wiring. It does not authenticate the publisher or prove that any command ran.',
              'Future public build/run commands retain their own prerequisite, non-overwrite, cleanup and stop guards. Existing outputs are never execution authority or retry permission.', '']
    return '\n'.join(lines).encode()


def prepare_handoff(source_range, *, baseline_build_plan, candidate_build_plan,
                    build_root, work_root, results_root, session, output_dir,
                    compare_repetitions=None, compare_order='alternating', compare_seed=None):
    plan, builds, bindings, bisection_bytes, preparation = _sources(source_range, baseline_build_plan, candidate_build_plan)
    output = _safe(output_dir)
    comparison = _comparison(compare_repetitions, compare_order, compare_seed)
    protected = [ROOT, _original_source_root(preparation), _safe(bindings['source_range']['path']).parent,
                 *(_safe(build['source_root']) for build in builds.values()),
                 *(_safe(binding['path']) for binding in bindings.values())]
    destinations = _destinations(dict(build_root=build_root, work_root=work_root,
        results_root=results_root, session=session), output, protected, fresh=True)
    inputs = {'inputs/recipe.json': _json(plan['recipe']),
              'inputs/baseline-build-plan.json': _json(builds['baseline']),
              'inputs/candidate-build-plan.json': _json(builds['candidate']),
              'inputs/bisection-plan.json': bisection_bytes}
    manifest = {'schema': SCHEMA, 'location': str(output), 'engine_root': str(ROOT),
                'recipe_sha256': recipes.recipe_sha256(plan['recipe']), 'input_bindings': bindings,
                'inputs_sha256': {name: _sha(data) for name, data in inputs.items()},
                'destinations': destinations, 'comparison': comparison, 'budgets': _budgets(plan, comparison),
                'target_build_differences': _differences(builds),
                'execution': 'not_requested', 'local_image_availability': 'unassessed',
                'host_suitability': 'unassessed', 'execution_authorization': 'unassessed',
                'performance_policy': 'disabled', 'qualification': 'not_assessed'}
    graph = _graph(output, destinations, plan, builds, comparison)
    commands = _json(graph)
    runbook = _runbook(manifest, graph, plan['recipe'])
    manifest.update(commands_sha256=_sha(commands), runbook_sha256=_sha(runbook))
    output.mkdir(mode=0o700, parents=True)
    (output / 'inputs').mkdir(mode=0o700)
    for relative, data in inputs.items():
        _write(output / relative, data)
    _write(output / 'commands.json', commands)
    _write(output / 'RUNBOOK.md', runbook)
    _write(output / 'handoff.json', _json(manifest))
    checksums = {'schema': SCHEMA, 'files': [{'path': name, 'sha256': _sha(_bytes(output / name))} for name in sorted(FILES)]}
    _write(output / 'checksums.json', _json(checksums))
    return verify_handoff(output / 'handoff.json')


def verify_handoff(path):
    path = _safe(path)
    if path.name != 'handoff.json':
        raise recipes.ContractError('Select the bundled handoff.json')
    root = path.parent
    manifest = _load(path)
    recipes._keys(manifest, ('schema', 'location', 'engine_root', 'recipe_sha256', 'input_bindings',
        'inputs_sha256', 'destinations', 'comparison', 'budgets', 'target_build_differences', 'execution', 'local_image_availability',
        'host_suitability', 'execution_authorization', 'performance_policy', 'qualification',
        'commands_sha256', 'runbook_sha256'), where='handoff')
    if manifest['schema'] != SCHEMA or manifest['location'] != str(root) or manifest['engine_root'] != str(ROOT):
        raise recipes.ContractError('Unsupported or relocated maintainer handoff')
    for name, expected in (('execution', 'not_requested'), ('local_image_availability', 'unassessed'),
                           ('host_suitability', 'unassessed'), ('execution_authorization', 'unassessed'),
                           ('performance_policy', 'disabled'), ('qualification', 'not_assessed')):
        recipes._same(manifest[name], expected, name)
    checksum = _load(root / 'checksums.json')
    recipes._keys(checksum, ('schema', 'files'), where='handoff checksums')
    if checksum['schema'] != SCHEMA or not isinstance(checksum['files'], list):
        raise recipes.ContractError('Unsupported handoff checksums')
    listed = set()
    for entry in checksum['files']:
        recipes._keys(entry, ('path', 'sha256'), where='handoff checksum')
        relative = recipes._artifact_path(entry['path'], 'handoff checksum path')
        if relative not in FILES or relative in listed:
            raise recipes.ContractError('Unsupported or duplicate handoff checksum path')
        listed.add(relative)
        if _sha(_bytes(root / relative)) != entry['sha256']:
            raise recipes.ContractError('Handoff checksum mismatch: ' + relative)
    if listed != FILES:
        raise recipes.ContractError('Incomplete handoff checksum coverage')
    def failed_walk(exc):
        raise recipes.ContractError('Cannot inspect handoff layout: ' + str(exc))
    for directory, dirs, files in os.walk(root, followlinks=False, onerror=failed_walk):
        base = Path(directory)
        for name in dirs:
            child = _safe(base / name)
            if child != root / 'inputs':
                raise recipes.ContractError('Unsupported handoff directory')
        for name in files:
            child = _safe(base / name)
            if child.relative_to(root).as_posix() not in FILES | {'checksums.json'}:
                raise recipes.ContractError('Unlisted handoff file')
    bindings = manifest['input_bindings']
    recipes._keys(bindings, ('source_range', 'baseline_build_plan', 'candidate_build_plan', 'bisection_plan'), where='input bindings')
    for binding in bindings.values():
        recipes._keys(binding, ('path', 'sha256'), where='input binding')
        if _sha(_bytes(binding['path'])) != binding['sha256']:
            raise recipes.ContractError('Original handoff input changed: ' + binding['path'])
    plan, builds, actual_bindings, bisection_bytes, preparation = _sources(bindings['source_range']['path'],
        bindings['baseline_build_plan']['path'], bindings['candidate_build_plan']['path'])
    recipes._same(bindings, actual_bindings, 'original input bindings')
    expected_inputs = {'inputs/recipe.json': _json(plan['recipe']),
        'inputs/baseline-build-plan.json': _json(builds['baseline']),
        'inputs/candidate-build-plan.json': _json(builds['candidate']), 'inputs/bisection-plan.json': bisection_bytes}
    recipes._same(manifest['inputs_sha256'], {name: _sha(data) for name, data in expected_inputs.items()}, 'frozen inputs')
    for name, data in expected_inputs.items():
        if _bytes(root / name) != data:
            raise recipes.ContractError('Frozen handoff input differs: ' + name)
    recipes._same(manifest['recipe_sha256'], recipes.recipe_sha256(plan['recipe']), 'handoff recipe')
    comparison = manifest['comparison']
    if comparison is not None:
        recipes._keys(comparison, ('repetitions', 'order', 'seed'), where='comparison options')
        comparison = _comparison(comparison['repetitions'], comparison['order'], comparison['seed'])
    protected = [ROOT, _original_source_root(preparation), _safe(bindings['source_range']['path']).parent,
                 *(_safe(build['source_root']) for build in builds.values()),
                 *(_safe(binding['path']) for binding in bindings.values())]
    destinations = _destinations(manifest['destinations'], root, protected, fresh=False)
    recipes._same(manifest['budgets'], _budgets(plan, comparison), 'handoff budgets')
    recipes._same(manifest['target_build_differences'], _differences(builds), 'target/build differences')
    graph = _graph(root, destinations, plan, builds, comparison)
    commands, runbook = _json(graph), _runbook(manifest, graph, plan['recipe'])
    if (_bytes(root / 'commands.json') != commands or manifest['commands_sha256'] != _sha(commands) or
            _bytes(root / 'RUNBOOK.md') != runbook or manifest['runbook_sha256'] != _sha(runbook)):
        raise recipes.ContractError('Handoff commands or runbook differ from the supported derivation')
    return {'valid': True, 'schema': SCHEMA, 'handoff': str(path), 'steps': len(graph['steps']),
            'execution': 'not_requested', 'local_image_availability': 'unassessed',
            'host_suitability': 'unassessed', 'execution_authorization': 'unassessed',
            'performance_policy': 'disabled', 'qualification': 'not_assessed'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    create = commands.add_parser('prepare', help='freeze selected source plans and public action descriptions only')
    for name in ('source-range', 'baseline-build-plan', 'candidate-build-plan', 'build-root', 'work-root',
                 'results-root', 'session', 'output'):
        create.add_argument('--' + name, required=True)
    create.add_argument('--compare-repetitions', type=int)
    create.add_argument('--compare-order', choices=('alternating', 'shuffle'), default='alternating')
    create.add_argument('--compare-seed', type=int)
    verify = commands.add_parser('verify', help='verify frozen inputs, source snapshots and command derivation without execution')
    verify.add_argument('document')
    args = parser.parse_args(argv)
    try:
        if args.command == 'verify':
            result = verify_handoff(args.document)
        else:
            result = prepare_handoff(args.source_range, baseline_build_plan=args.baseline_build_plan,
                candidate_build_plan=args.candidate_build_plan, build_root=args.build_root,
                work_root=args.work_root, results_root=args.results_root, session=args.session,
                output_dir=args.output, compare_repetitions=args.compare_repetitions,
                compare_order=args.compare_order, compare_seed=args.compare_seed)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.exit(2, 'Maintainer handoff refused: ' + str(exc) + '\n')


if __name__ == '__main__':
    raise SystemExit(main())
