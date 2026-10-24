# Copyright (C) 2026 bgperf2 contributors.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy at http://www.apache.org/licenses/LICENSE-2.0

"""Declarative recipe/result contracts and explicit preparation/execution CLI.

The first envelope deliberately supports only synthetic IPv4 BIRD workloads,
with BIRD generators and the sink instrument. It imports no container runtime.
"""

import argparse
import copy
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys

import yaml

from batch_cells import (BatchLoader, DEFAULT_CHURN_BURSTS,
                         DEFAULT_CHURN_PREFIXES, DEFAULT_PATH_DIVERSITY,
                         DEFAULT_POLICY_RELOAD_BLOCKS, DEFAULT_RECEIVERS,
                         batch_cell_id, batch_cell_key, construct_batch_cells,
                         expand_target_versions, resolve_prefix_scope)

RECIPE_SCHEMA = 'bgperf2/recipe/v1alpha1'
RESULT_SCHEMA = 'bgperf2/result/v1alpha1'
COMPLETION_CONTRACT = 'bgperf2/existing-convergence'
RESULT_EXIT_CODES = {
    'completed': (0,), 'setup_refused': (2,), 'harness_failed': (3,),
    'experiment_failed': (4,), 'interrupted': (130, 143), 'inconclusive': (5,),
}
REPRODUCTION_OUTCOMES = ('reproduced', 'not_reproduced', 'inconclusive',
                         'not_evaluated')
EXPECTED_OUTCOMES = ('experiment_completed', 'target_crash')
ARTIFACT_KINDS = ('events', 'provenance', 'samples', 'configuration', 'log', 'other')
_HEX64 = re.compile(r'[0-9a-f]{64}\Z')
_REVISION = re.compile(r'[0-9a-f]{40}\Z')
_IMAGE = re.compile(r'(?:sha256:[0-9a-f]{64}|[a-zA-Z0-9][a-zA-Z0-9._:/-]*@sha256:[0-9a-f]{64})\Z')
_KEY = re.compile(r'[0-9a-f]{16}\Z')
_TEST_REQUIRED = ('name', 'neighbors', 'prefixes', 'filter_test', 'targets')
_TEST_OPTIONAL = ('prefix_scope', 'repetitions', 'order', 'seed', 'monitor')
_TARGET_KEYS = ('name', 'tester_type', 'version', 'image', 'label', 'threads')


class ContractError(ValueError):
    """A recipe/result refuses an invalid, unsupported or unpinned input."""


def _keys(value, required, optional=(), where='document'):
    if not isinstance(value, dict):
        raise ContractError(f'{where}: expected an object')
    missing = set(required) - value.keys()
    unknown = value.keys() - set(required) - set(optional)
    if missing:
        raise ContractError(f'{where}: missing field(s): {", ".join(sorted(missing))}')
    if unknown:
        raise ContractError(f'{where}: unsupported field(s): {", ".join(sorted(map(str, unknown)))}')
    return value


def _text(value, where):
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f'{where}: expected nonempty text')
    return value


def _integer(value, where, minimum=None):
    if isinstance(value, bool) or not isinstance(value, int) or (minimum is not None and value < minimum):
        suffix = '' if minimum is None else f' of at least {minimum}'
        raise ContractError(f'{where}: expected an integer{suffix}')
    return value


def _match(value, pattern, where, description):
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ContractError(f'{where}: expected {description}')
    return value


def _choice(value, choices, where):
    if value not in choices:
        raise ContractError(f'{where}: expected one of {", ".join(map(str, choices))}')
    return value


def _same(actual, expected, where):
    # JSON distinguishes booleans from integers, unlike Python equality.
    if canonical_json(actual) != canonical_json(expected):
        raise ContractError(f'{where}: does not match the resolved source definition')


def canonical_json(document):
    """Canonical digest text: sorted keys, ASCII JSON escapes, compact separators.

    No trailing newline is added. Whitespace within source/other strings is
    preserved; non-ASCII characters use Python JSON's ensure_ascii=True escapes.
    """
    try:
        return json.dumps(document, sort_keys=True, separators=(',', ':'),
                          ensure_ascii=True, allow_nan=False)
    except (TypeError, ValueError, RecursionError) as exc:
        raise ContractError(f'document: invalid JSON data: {exc}') from exc


def recipe_sha256(document):
    return hashlib.sha256(canonical_json(document).encode('utf-8')).hexdigest()


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ContractError(f'document: duplicate field {key!r}')
        result[key] = value
    return result


def _nonfinite(value):
    raise ContractError(f'document: non-finite number {value!r} is not supported')


def read_document(path):
    """Read strict JSON; duplicate fields and non-finite constants are errors."""
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'), object_pairs_hook=_pairs,
                          parse_constant=_nonfinite)
    except (OSError, UnicodeError, ValueError) as exc:
        raise ContractError(f'{path}: {exc}') from exc


class _RecipeBatchLoader(BatchLoader):
    """Use legacy scalar interpretation, refusing ambiguous duplicate keys."""


def _yaml_mapping(loader, node):
    loader.flatten_mapping(node)
    pairs = []
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=True)
        if not isinstance(key, str):
            raise ContractError('source: all YAML object keys must be strings')
        pairs.append((key, loader.construct_object(value_node, deep=True)))
    return _pairs(pairs)


_RecipeBatchLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
                                  _yaml_mapping)


def _source_tests(text):
    """Validate every source test before selecting or expanding any cell."""
    _text(text, 'source.text')
    try:
        document = yaml.load(text, Loader=_RecipeBatchLoader)
    except yaml.YAMLError as exc:
        raise ContractError(f'source: invalid batch YAML: {exc}') from exc
    _keys(document, ('tests',), where='source')
    if not isinstance(document['tests'], list) or not document['tests']:
        raise ContractError('source.tests: expected a nonempty list')
    names = set()
    for index, test in enumerate(document['tests']):
        where = f'source.tests[{index}]'
        _keys(test, _TEST_REQUIRED, _TEST_OPTIONAL, where)
        name = _text(test['name'], f'{where}.name')
        if name in names:
            raise ContractError(f'{where}.name: duplicate test {name!r}')
        names.add(name)
        for axis in ('neighbors', 'prefixes', 'filter_test', 'targets'):
            if not isinstance(test[axis], list) or not test[axis]:
                raise ContractError(f'{where}.{axis}: expected a nonempty list')
        for axis in ('neighbors', 'prefixes'):
            for value in test[axis]:
                _integer(value, f'{where}.{axis}', 1)
            if len(test[axis]) != len(set(test[axis])):
                raise ContractError(f'{where}.{axis}: repeated axis value')
        filters = test['filter_test']
        if any(value is not None and value != 'None' for value in filters):
            raise ContractError(f'{where}.filter_test: only unfiltered synthetic workloads are supported')
        if len({canonical_json(value) for value in filters}) != len(filters):
            raise ContractError(f'{where}.filter_test: repeated axis value')
        scope = test.get('prefix_scope')
        _choice(scope, (None, 'per-peer', 'total'), f'{where}.prefix_scope')
        _choice(test.get('monitor'), (None, 'sink'), f'{where}.monitor')
        repetitions = test.get('repetitions', 1)
        _integer(repetitions, f'{where}.repetitions', 1)
        order = test.get('order', 'matrix')
        _choice(order, ('matrix', 'shuffle'), f'{where}.order')
        seed = test.get('seed')
        if seed is not None:
            _integer(seed, f'{where}.seed')
        if order == 'shuffle' and seed is None:
            raise ContractError(f'{where}.seed: shuffle requires an explicit integer seed')
        if order == 'matrix' and seed is not None:
            raise ContractError(f'{where}.seed: a seed requires shuffle order')
        run_names = set()
        for ti, target in enumerate(test['targets']):
            tw = f'{where}.targets[{ti}]'
            _keys(target, ('name',), _TARGET_KEYS[1:], tw)
            _choice(target['name'], ('bird',), f'{tw}.name')
            _choice(target.get('tester_type'), (None, 'bird'), f'{tw}.tester_type')
            for field in ('image', 'label'):
                if target.get(field) is not None:
                    _text(target[field], f'{tw}.{field}')
            if target.get('image') is not None:
                _match(target['image'], _IMAGE, f'{tw}.image', 'an immutable image ID or repository digest')
            if target.get('version') is not None:
                if isinstance(target['version'], bool) or not isinstance(target['version'], (str, int)):
                    raise ContractError(f'{tw}.version: expected a release string or integer')
                _text(str(target['version']), f'{tw}.version')
            if target.get('threads') is not None:
                _integer(target['threads'], f'{tw}.threads', 1)
            expanded = expand_target_versions([target])[0]
            run_name = expanded.get('label') or ('bird ' + expanded['version'] if expanded.get('version') else 'bird')
            if run_name in run_names:
                raise ContractError(f'{tw}: repeated run name {run_name!r}; select unique labels')
            run_names.add(run_name)
        for neighbors in test['neighbors']:
            for prefixes in test['prefixes']:
                try:
                    resolve_prefix_scope(scope, neighbors, prefixes, 'bird')
                except ValueError as exc:
                    raise ContractError(f'{where}: {exc}') from exc
    return document['tests']


def _select(text, test_name, cell_key):
    _text(test_name, 'selection.test')
    _match(cell_key, _KEY, 'selection.cell_key', 'a 16-character legacy cell key')
    tests = _source_tests(text)
    selected_test = next((test for test in tests if test['name'] == test_name), None)
    if selected_test is None:
        raise ContractError(f'selection.test: no source test named {test_name!r}')
    targets = expand_target_versions(selected_test['targets'])
    cells = construct_batch_cells(
        selected_test, targets, repetitions=selected_test.get('repetitions', 1),
        prefix_resolver=resolve_prefix_scope, path_diversity=DEFAULT_PATH_DIVERSITY,
        receivers=DEFAULT_RECEIVERS, churn_prefixes=DEFAULT_CHURN_PREFIXES,
        churn_bursts=DEFAULT_CHURN_BURSTS,
        policy_reload_blocks=DEFAULT_POLICY_RELOAD_BLOCKS, pin=None, monitor='sink')
    matches = [cell for cell in cells if batch_cell_key(batch_cell_id(test_name, cell)) == cell_key]
    if len(matches) != 1:
        raise ContractError(f'selection.cell_key: expected exactly one source cell matching {cell_key!r}, found {len(matches)}')
    cell = matches[0]
    raw_target = selected_test['targets'][cell['ordinal'] % len(targets)]
    target = cell['target']
    resolved_target = {
        'name': 'bird', 'tester_type': target.get('tester_type') or 'bird',
        'filter_type': 'in', 'version': target.get('version'),
        'image': target.get('image'), 'label': target.get('label'),
        'threads': target.get('threads'),
    }
    resolved = {
        'neighbors': cell['neighbors'], 'prefixes_per_peer': cell['prefixes'],
        'prefix_scope': 'per-peer', 'filter': None, 'path_diversity': 1,
        'receivers': 0, 'monitor': 'sink', 'repetition': cell['repetition'],
        'ordinal': cell['ordinal'], 'target': resolved_target,
    }
    return selected_test, cell, raw_target, resolved


def _roles(roles):
    _keys(roles, ('target', 'generator', 'observer'), where='roles')
    for role, adapter in (('target', 'bird'), ('generator', 'bird'), ('observer', 'sink')):
        _keys(roles[role], ('adapter', 'image'), where=f'roles.{role}')
        _choice(roles[role]['adapter'], (adapter,), f'roles.{role}.adapter')
        _match(roles[role]['image'], _IMAGE, f'roles.{role}.image',
               'an immutable image ID (sha256:<64 hex>) or repository@sha256:<64 hex>')


def _recipe(text, test_name, cell_key, engine_revision, roles, question, expected_outcome):
    _match(engine_revision, _REVISION, 'engine.revision', 'a full 40-character lowercase Git revision')
    _roles(roles)
    _text(question, 'reproduction.question')
    _choice(expected_outcome, EXPECTED_OUTCOMES, 'reproduction.expected_outcome')
    test, cell, raw_target, resolved = _select(text, test_name, cell_key)
    if cell['target'].get('image') is not None:
        _same(roles['target']['image'], cell['target']['image'], 'roles.target.image')
    return {
        'schema': RECIPE_SCHEMA, 'engine': {'revision': engine_revision},
        'source': {'format': 'bgperf2/batch', 'text': text,
                   'sha256': hashlib.sha256(text.encode('utf-8')).hexdigest(),
                   'raw_target': copy.deepcopy(raw_target)},
        'selection': {'test': test_name, 'cell_key': cell_key},
        'legacy': {'cell_id': batch_cell_id(test_name, cell), 'cell_key': cell_key},
        'resolved': resolved, 'roles': copy.deepcopy(roles), 'inputs': [],
        'seeds': {'order': test.get('order', 'matrix'), 'seed': test.get('seed'), 'workload': None},
        'resources': {'cpus': None, 'memory_bytes': None, 'storage_bytes': None},
        'completion': {'contract': COMPLETION_CONTRACT, 'engine_revision': engine_revision},
        'reproduction': {'question': question, 'expected_outcome': expected_outcome},
    }


def export_recipe(batch_path, test_name, cell_key, *, engine_revision, roles, question,
                  expected_outcome='experiment_completed'):
    """Export exactly one explicitly selected legacy cell; never query images."""
    try:
        # Preserve the original bytes' newline spelling in the UTF-8 text hash.
        text = Path(batch_path).read_bytes().decode('utf-8')
    except (OSError, UnicodeError) as exc:
        raise ContractError(f'{batch_path}: {exc}') from exc
    return _recipe(text, test_name, cell_key, engine_revision, roles, question, expected_outcome)


def validate_recipe(document):
    """Re-resolve embedded source and verify the complete strict envelope."""
    _keys(document, ('schema', 'engine', 'source', 'selection', 'legacy', 'resolved',
                     'roles', 'inputs', 'seeds', 'resources', 'completion', 'reproduction'))
    _choice(document['schema'], (RECIPE_SCHEMA,), 'schema')
    _keys(document['engine'], ('revision',), where='engine')
    _keys(document['source'], ('format', 'text', 'sha256', 'raw_target'), where='source')
    _choice(document['source']['format'], ('bgperf2/batch',), 'source.format')
    _keys(document['selection'], ('test', 'cell_key'), where='selection')
    _keys(document['reproduction'], ('question', 'expected_outcome'), where='reproduction')
    expected = _recipe(document['source']['text'], document['selection']['test'],
                       document['selection']['cell_key'], document['engine']['revision'],
                       document['roles'], document['reproduction']['question'],
                       document['reproduction']['expected_outcome'])
    for field in expected:
        _same(document[field], expected[field], field)
    return document


def inspect_recipe(document):
    """Return an inspectable plan with explicit execution/comparability limits."""
    validate_recipe(document)
    return {
        'schema': document['schema'], 'recipe_sha256': recipe_sha256(document),
        'selection': document['selection'], 'legacy': document['legacy'],
        'engine': document['engine'], 'resolved': document['resolved'],
        'roles': document['roles'], 'inputs': document['inputs'],
        'resources': document['resources'], 'seeds': document['seeds'],
        'completion': document['completion'], 'reproduction': document['reproduction'],
        'execution': 'explicit_run_required', 'comparison': 'not_assessed',
        'identity_limit': 'Image pins are declared inputs; their existence, contents and build provenance have not been verified.',
    }


def _artifact_path(value, where):
    _text(value, where)
    path = PurePosixPath(value)
    if (path.is_absolute() or '..' in path.parts or '\\' in value
            or '\x00' in value or str(path) != value or value == '.'):
        raise ContractError(f'{where}: expected a normalized relative artifact path')
    return value


def validate_result(document):
    """Validate declared result references without reading or collecting artifacts."""
    _keys(document, ('schema', 'recipe_sha256', 'engine', 'attempt', 'status', 'exit_code',
                     'reproduction', 'comparison', 'artifacts'))
    _choice(document['schema'], (RESULT_SCHEMA,), 'schema')
    _match(document['recipe_sha256'], _HEX64, 'recipe_sha256', 'a SHA-256 digest')
    _keys(document['engine'], ('revision',), where='engine')
    _match(document['engine']['revision'], _REVISION, 'engine.revision', 'a full Git revision')
    _keys(document['attempt'], ('id',), where='attempt')
    _text(document['attempt']['id'], 'attempt.id')
    status = _choice(document['status'], tuple(RESULT_EXIT_CODES), 'status')
    code = _integer(document['exit_code'], 'exit_code')
    if code not in RESULT_EXIT_CODES[status]:
        raise ContractError(f'exit_code: does not match status {status!r}')
    reproduction = _keys(document['reproduction'], ('outcome', 'reason', 'evidence'), where='reproduction')
    outcome = _choice(reproduction['outcome'], REPRODUCTION_OUTCOMES, 'reproduction.outcome')
    _text(reproduction['reason'], 'reproduction.reason')
    if not isinstance(reproduction['evidence'], list):
        raise ContractError('reproduction.evidence: expected a list of artifact paths')
    comparison = _keys(document['comparison'], ('qualification', 'reason'), where='comparison')
    _choice(comparison['qualification'], ('not_assessed',), 'comparison.qualification')
    _text(comparison['reason'], 'comparison.reason')
    if not isinstance(document['artifacts'], list):
        raise ContractError('artifacts: expected a list')
    paths, present, kinds = set(), set(), set()
    for index, artifact in enumerate(document['artifacts']):
        where = f'artifacts[{index}]'
        _keys(artifact, ('kind', 'path', 'sha256', 'availability', 'reason'), where=where)
        kind = _choice(artifact['kind'], ARTIFACT_KINDS, f'{where}.kind')
        kinds.add(kind)
        availability = _choice(artifact['availability'], ('present', 'missing'), f'{where}.availability')
        path = artifact['path']
        if path is not None:
            _artifact_path(path, f'{where}.path')
            if path in paths:
                raise ContractError(f'{where}.path: duplicate artifact path {path!r}')
            paths.add(path)
        if availability == 'present':
            _artifact_path(path, f'{where}.path')
            _match(artifact['sha256'], _HEX64, f'{where}.sha256', 'a SHA-256 digest')
            if artifact['reason'] is not None:
                raise ContractError(f'{where}.reason: present artifacts require null')
            present.add(path)
        else:
            if artifact['sha256'] is not None:
                raise ContractError(f'{where}.sha256: missing artifacts require null')
            _text(artifact['reason'], f'{where}.reason')
    missing = set(ARTIFACT_KINDS[:-1]) - kinds
    if missing:
        raise ContractError(f'artifacts: explicitly list present or missing {", ".join(sorted(missing))}')
    for path in reproduction['evidence']:
        _artifact_path(path, 'reproduction.evidence')
        if path not in present:
            raise ContractError(f'reproduction.evidence: {path!r} does not name a present artifact')
    if outcome in ('reproduced', 'not_reproduced') and not reproduction['evidence']:
        raise ContractError('reproduction.evidence: a decided outcome requires evidence')
    if status == 'setup_refused' and outcome in ('reproduced', 'not_reproduced'):
        raise ContractError('reproduction.outcome: setup refusal cannot decide reproduction')
    return document


def _write_document(document, path=None):
    text = json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + '\n'
    if path is None:
        print(text, end='')
    else:
        # Export never overwrites an earlier recipe or arbitrary local file.
        with Path(path).open('x', encoding='utf-8', newline='\n') as stream:
            stream.write(text)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    export = commands.add_parser('export', help='export one explicitly selected batch cell')
    for flag in ('batch', 'test', 'cell', 'engine-revision', 'target-image',
                 'generator-image', 'observer-image', 'question'):
        export.add_argument('--' + flag, required=True)
    export.add_argument('--expected-outcome', choices=EXPECTED_OUTCOMES,
                        default='experiment_completed')
    export.add_argument('-o', '--output')
    for name in ('validate', 'inspect', 'result-validate', 'result-verify', 'plan', 'check',
                 'prepare', 'run', 'target-image', 'target-validate', 'target-source-plan',
                 'target-build', 'investigate', 'investigation-verify'):
        command = commands.add_parser(name)
        command.add_argument('document')
        if name in ('check', 'run'):
            command.add_argument('--workdir', required=True)
            command.add_argument('--results-dir', required=True)
            command.add_argument('--target', help='strict target override/build identity JSON')
        if name == 'run':
            command.add_argument('--timeout', type=float, default=300,
                                 help='whole-attempt runtime deadline in seconds (default: 300)')
            command.add_argument('--diagnostics', choices=('basic', 'none'), default='basic')
        if name == 'target-image':
            command.add_argument('--image', required=True)
            command.add_argument('--label')
            command.add_argument('--instrumentation', choices=('unknown', 'optimized', 'debug', 'asan', 'profiling'), default='unknown')
            command.add_argument('-o', '--output')
        if name == 'target-validate':
            command.add_argument('--recipe', help='also verify canonical recipe binding')
        if name == 'target-source-plan':
            for flag in ('source', 'revision', 'toolchain-image', 'runtime-image'):
                command.add_argument('--' + flag, required=True)
            command.add_argument('--instrumentation', choices=('unknown', 'optimized', 'debug', 'asan', 'profiling'), default='debug')
            command.add_argument('--cflags', default='-O0 -g')
            command.add_argument('--configure-flag', action='append', default=[])
            command.add_argument('--include-dirty', action='store_true')
            command.add_argument('-o', '--output')
        if name == 'target-build':
            command.add_argument('--output-dir', required=True)
            command.add_argument('--timeout', type=float, default=1200)
        if name == 'investigate':
            command.add_argument('--baseline-target', required=True)
            command.add_argument('--candidate-target', required=True)
            command.add_argument('--workdir', required=True)
            command.add_argument('--results-dir', required=True)
            command.add_argument('--timeout', type=float, default=300)
            command.add_argument('--diagnostics', choices=('basic', 'none'), default='basic')
        if name == 'prepare':
            command.add_argument('--pull', action='store_true',
                                 help='explicitly acquire missing selected repository digests after disclosure')
    report = commands.add_parser('investigation-report', help='verify and bundle an existing functional pair')
    report.add_argument('--baseline', required=True)
    report.add_argument('--candidate')
    report.add_argument('--output-dir', required=True)
    assertion_export = commands.add_parser('assertions-export', help='export explicit supported observable assertions')
    assertion_export.add_argument('document')
    assertion_export.add_argument('-o', '--output')
    assertion_export.add_argument('--capability', action='append',
        choices=('session_establishment', 'injection_completion', 'observer_route_count',
                 'experiment_completion', 'observed_role_health'),
        help='repeat to select an explicit supported subset; default exports all')
    assertion_check = commands.add_parser('assertions-check', help='evaluate assertions from a verified result package')
    assertion_check.add_argument('document')
    assertion_check.add_argument('--result', required=True)
    comparison_plan = commands.add_parser('comparison-plan', help='freeze a repeated target comparison without runtime probes')
    comparison_plan.add_argument('document')
    comparison_plan.add_argument('--baseline-target', required=True)
    comparison_plan.add_argument('--candidate-target', required=True)
    comparison_plan.add_argument('--assertions')
    comparison_plan.add_argument('--repetitions', type=int, required=True)
    comparison_plan.add_argument('--order', choices=('alternating', 'shuffle'), default='alternating')
    comparison_plan.add_argument('--seed', type=int)
    comparison_plan.add_argument('--timeout', type=float, default=300)
    comparison_plan.add_argument('--diagnostics', choices=('none', 'basic'), default='none')
    comparison_plan.add_argument('-o', '--output')
    compare = commands.add_parser('compare', help='explicitly execute a frozen serial comparison plan')
    compare.add_argument('document')
    compare.add_argument('--workdir', required=True)
    compare.add_argument('--results-dir', required=True)
    comparison_report = commands.add_parser('comparison-report', help='bundle an existing comparison ledger without runtime access')
    comparison_report.add_argument('document')
    comparison_report.add_argument('--attempts', required=True)
    comparison_report.add_argument('--output-dir', required=True)
    comparison_verify = commands.add_parser('comparison-verify', help='verify bundled comparison evidence and conclusions')
    comparison_verify.add_argument('document')
    args = parser.parse_args(argv)
    try:
        if args.command == 'export':
            roles = {role: {'adapter': adapter, 'image': getattr(args, role + '_image')}
                     for role, adapter in (('target', 'bird'), ('generator', 'bird'), ('observer', 'sink'))}
            document = export_recipe(args.batch, args.test, args.cell,
                                     engine_revision=args.engine_revision, roles=roles,
                                     question=args.question, expected_outcome=args.expected_outcome)
            _write_document(document, args.output)
        elif args.command == 'result-verify':
            from recipe_results import verify_result_package
            _write_document(verify_result_package(args.document))
        elif args.command == 'investigation-report':
            from recipe_investigation import write_investigation_report
            _write_document(write_investigation_report(baseline=args.baseline,
                candidate=args.candidate, output_dir=args.output_dir))
        elif args.command == 'investigation-verify':
            from recipe_investigation import verify_investigation_report
            _write_document(verify_investigation_report(args.document))
        elif args.command == 'comparison-verify':
            from recipe_comparison_report import verify_comparison_report
            _write_document(verify_comparison_report(args.document))
        elif args.command == 'assertions-check':
            from recipe_assertions import evaluate_assertions
            from recipe_results import verify_result_package
            verify_result_package(args.result)
            from recipe_investigation import _load
            bound = _load(Path(args.result).parent, 'recipe.json')
            result = evaluate_assertions(read_document(args.document), bound, args.result)
            _write_document(result)
            return 0 if result.get('outcome') == 'passed' else 4 if result.get('outcome') == 'failed' else 5
        else:
            document = read_document(args.document)
            if args.command == 'inspect':
                _write_document(inspect_recipe(document))
            elif args.command == 'assertions-export':
                from recipe_assertions import default_assertions
                spec = default_assertions(document)
                if args.capability:
                    if len(args.capability) != len(set(args.capability)):
                        raise ContractError('Duplicate assertion capability selection')
                    spec['assertions'] = [item for item in spec['assertions'] if item['capability'] in args.capability]
                _write_document(spec, args.output)
            elif args.command == 'comparison-plan':
                from recipe_comparison import make_comparison_plan
                _write_document(make_comparison_plan(document,
                    baseline_target=read_document(args.baseline_target),
                    candidate_target=read_document(args.candidate_target),
                    repetitions=args.repetitions, order=args.order, seed=args.seed,
                    timeout=args.timeout, diagnostics=args.diagnostics,
                    assertions=read_document(args.assertions) if args.assertions else None), args.output)
            elif args.command == 'compare':
                from recipe_comparison import run_comparison
                result = run_comparison(document, workdir=args.workdir, results_dir=args.results_dir)
                _write_document(result)
                return result['exit_code']
            elif args.command == 'comparison-report':
                from recipe_comparison_report import build_comparison_report
                _write_document(build_comparison_report(document, read_document(args.attempts), args.output_dir))
            elif args.command == 'target-image':
                from recipe_targets import supplied_target
                _write_document(supplied_target(document, args.image, label=args.label,
                    instrumentation=args.instrumentation), args.output)
            elif args.command == 'target-validate':
                from recipe_targets import validate_target
                validate_target(document, read_document(args.recipe) if args.recipe else None)
                _write_document({'valid': True, 'schema': document['schema']})
            elif args.command == 'target-source-plan':
                from recipe_targets import plan_source_build
                plan = plan_source_build(document, args.source, args.revision,
                    toolchain_image=args.toolchain_image, runtime_image=args.runtime_image,
                    instrumentation=args.instrumentation, cflags=args.cflags,
                    include_dirty=args.include_dirty, configure_flags=args.configure_flag)
                _write_document(plan, args.output)
            elif args.command == 'target-build':
                from recipe_targets import build_target
                def disclose_build(plan):
                    print(json.dumps(plan, indent=2, sort_keys=True), file=sys.stderr, flush=True)
                _write_document(build_target(document, output_dir=args.output_dir,
                    emit_disclosure=disclose_build, timeout=args.timeout))
            elif args.command == 'investigate':
                from recipe_investigation import run_investigation
                result = run_investigation(document,
                    baseline_target=read_document(args.baseline_target),
                    candidate_target=read_document(args.candidate_target),
                    workdir=args.workdir, results_dir=args.results_dir,
                    timeout=args.timeout, diagnostics=args.diagnostics)
                _write_document(result)
                return result['exit_code']
            elif args.command == 'run':
                validate_recipe(document)
                from recipe_run import run_recipe
                options = {}
                if args.target:
                    options['target'] = read_document(args.target)
                if args.diagnostics != 'basic':
                    options['diagnostics'] = args.diagnostics
                result = run_recipe(document, workdir=args.workdir,
                                    results_dir=args.results_dir, timeout=args.timeout, **options)
                _write_document(result)
                return result['exit_code']
            elif args.command in ('plan', 'check', 'prepare'):
                # Also validate in this module before importing the host layer:
                # direct script execution names this module __main__, while the
                # preflight library imports recipes and its ContractError class.
                validate_recipe(document)
                # Keep ordinary contract imports independent of host probes.
                if args.command == 'prepare':
                    from recipe_prepare import prepare_recipe

                    def disclose(report):
                        print(json.dumps(report, indent=2, sort_keys=True),
                              file=sys.stderr, flush=True)

                    report = prepare_recipe(document, pull=args.pull, emit_disclosure=disclose)
                else:
                    from recipe_preflight import check_recipe, plan_recipe
                    options = {'target': read_document(args.target)} if args.command == 'check' and args.target else {}
                    report = (plan_recipe(document) if args.command == 'plan' else
                              check_recipe(document, workdir=args.workdir,
                                           results_dir=args.results_dir, **options))
                _write_document(report)
                return 2 if report['status'] == 'refused' else 0
            elif args.command == 'result-validate':
                validate_result(document)
                _write_document({'valid': True, 'schema': RESULT_SCHEMA})
            else:
                validate_recipe(document)
                _write_document({'valid': True, 'schema': RECIPE_SCHEMA,
                                 'recipe_sha256': recipe_sha256(document)})
    except (ValueError, OSError, UnicodeError, RecursionError) as exc:
        print(f'{args.command}: {exc}', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
