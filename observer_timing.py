# Copyright (C) 2026 bgperf2 contributors. Apache-2.0.
"""Offline observer count-crossing timing; never import a Docker runtime.

This supplement leaves legacy CSV and portable comparison schemas unchanged.
See docs/observer-timing.md for the measurement and its discovery-only gate.
"""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import stat

import recipes
from recipe_assertions import evaluate_assertions, validate_assertions
from recipe_results import _regular_file, verify_result_package

SCHEMA = 'bgperf2/observer-delivery-window/v1alpha1'
CAPABILITIES = {'session_establishment', 'injection_completion',
                'observer_route_count', 'experiment_completion'}
MAX_LOG_BYTES = 8 * 1024 * 1024


def crossing_window(text, total):
    """Bracket 10% and 90% crossings using actual preceding count timestamps.

    Only the initial monotone delivery through the first exact full count is
    used. Logs also contain ordinary teardown resets after collection; those
    are outside this window. Package-level witnesses qualify completion later.
    """
    if type(total) is not int or total < 10:
        raise recipes.ContractError('Expected an integer prefix count of at least ten')
    thresholds = ((total + 9) // 10, (9 * total + 9) // 10)
    brackets = [None, None]
    previous = None
    state = None
    last_ns = None
    version = boot = sessions = 0
    changes = []
    for line_number, line in enumerate(text.splitlines(keepends=True), 1):
        if not line.endswith('\n'):
            raise recipes.ContractError('Incomplete sink line before full delivery')
        parts = line.rstrip('\n').split()
        try:
            kind = parts[0]
            ns = int(parts[1])
            if not 0 <= ns <= 2**63 - 1 or (last_ns is not None and ns < last_ns):
                raise ValueError('nonmonotone or negative timestamp')
            last_ns = ns
            if kind == 'V':
                version += 1
                if version != 1 or line_number != 1 or parts[2] != '1' or len(parts) < 4:
                    raise ValueError('restart or unsupported format')
            elif version != 1:
                raise ValueError('missing format line')
            elif kind == 'B':
                boot += 1
                if boot != 1 or len(parts) != 3 or int(parts[2]) < 0:
                    raise ValueError('invalid boot clock line')
            elif kind == 'S':
                if len(parts) < 5 or parts[2] not in ('connected', 'open_sent', 'established'):
                    raise ValueError('lost/dropped session or unsupported session record')
                if parts[2] == 'established':
                    sessions += 1
                    if sessions != 1:
                        raise ValueError('multiple established sessions')
            elif kind in ('C', 'H', 'E'):
                wanted = 4 if kind == 'E' else 5
                if len(parts) != wanted:
                    raise ValueError('wrong counter field count')
                numbers = tuple(int(x) for x in parts[2:])
                if any(x < 0 for x in numbers) or numbers[0] > total:
                    raise ValueError('negative or excessive count')
                if kind == 'C':
                    if state is not None and any(a < b for a, b in zip(numbers, state)):
                        raise ValueError('count/update/EOR reset')
                    state = numbers
                elif state is None:
                    # Before any UPDATE the sink may emit its initial zero heartbeat.
                    if kind != 'H' or numbers != (0, 0, 0):
                        raise ValueError('counter restatement before a known state')
                    state = numbers
                elif numbers != (state[:2] if kind == 'E' else state):
                    raise ValueError('counter restatement disagrees with C line')
                count = numbers[0]
                if count and (boot != 1 or sessions != 1):
                    raise ValueError('delivery before clock/session establishment')
                if kind in ('C', 'H'):
                    for i, threshold in enumerate(thresholds):
                        if brackets[i] is None and count >= threshold:
                            if previous is None or previous[1] >= threshold:
                                raise ValueError('crossing lacks a preceding below-threshold count')
                            brackets[i] = {'threshold': threshold,
                                           'lower_ns': previous[0], 'upper_ns': ns,
                                           'previous_count': previous[1], 'count': count}
                    if kind == 'C' and previous is not None and count > previous[1]:
                        changes.append((ns, count))
                    previous = (ns, count)
                if count == total:
                    if any(item is None for item in brackets):
                        raise ValueError('missing threshold bracket')
                    start, end = brackets
                    lower_ns = max(0, end['lower_ns'] - start['upper_ns'])
                    upper_ns = end['upper_ns'] - start['lower_ns']
                    interior = sum(thresholds[0] < count < thresholds[1]
                                   for _, count in changes)
                    return {'start': start, 'end': end,
                            'span_seconds': (end['upper_ns'] - start['upper_ns']) / 1e9,
                            'lower_seconds': lower_ns / 1e9, 'upper_seconds': upper_ns / 1e9,
                            'bracket_width_seconds': (upper_ns - lower_ns) / 1e9,
                            'interior_increasing_records': interior,
                            'full_count_line': line_number}
            else:
                raise ValueError('refused message or unknown record')
        except (ValueError, IndexError) as exc:
            raise recipes.ContractError(f'Sink line {line_number}: {exc}') from exc
    raise recipes.ContractError('No exact full-delivery count in the retained log')


def resolution_gate(window):
    """A predeclared sampling screen, never a practical effect or regression rule."""
    reasons = []
    if window['lower_seconds'] < 1:
        reasons.append('Conservative delivery-window lower bound is below one second.')
    if window['bracket_width_seconds'] > 0.05 * window['lower_seconds']:
        reasons.append('Actual endpoint-bracket width exceeds 5% of the duration lower bound.')
    if window['interior_increasing_records'] < 10:
        reasons.append('Fewer than ten increasing count records between the thresholds.')
    return {'outcome': 'blocked' if reasons else 'passed', 'reasons': reasons,
            'definition': 'Discovery sampling screen only; no statistical power or effect-size acceptance.'}


def _read(root, relative, limit=MAX_LOG_BYTES):
    with _regular_file(root, relative) as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise recipes.ContractError(f'{relative}: exceeds offline read bound')
    return data


def review_result(result_path, assertions_path):
    """Verify a package before reading its one monitor log and instrument record."""
    path = Path(result_path)
    root = path.parent
    manifest = _read(root, path.name)
    verify_result_package(path)
    if _read(root, path.name) != manifest:
        raise recipes.ContractError('Result manifest changed during package verification')
    result = json.loads(manifest, object_pairs_hook=recipes._pairs, parse_constant=recipes._nonfinite)
    present = {item['path']: item for item in result['artifacts']
               if item['availability'] == 'present'}

    def artifact(name):
        data = _read(root, name)
        if hashlib.sha256(data).hexdigest() != present[name]['sha256']:
            raise recipes.ContractError(f'{name}: changed after package verification')
        return data

    recipe = json.loads(artifact('recipe.json'))
    spec = recipes.read_document(assertions_path)
    validate_assertions(spec, recipe)
    if (len(spec.get('assertions', [])) != 4 or
            {x.get('capability') for x in spec['assertions']} != CAPABILITIES):
        raise recipes.ContractError('Select exactly the four worker-budget assertions')
    correctness = evaluate_assertions(spec, recipe, path)
    if result['status'] != 'completed' or correctness['outcome'] != 'passed':
        raise recipes.ContractError('A completed attempt with four passed assertions is required')
    logs = [name for name in present if name.endswith('/monitor/sink.log')]
    events = [name for name in present if name.startswith('work/artifacts/')
              and name.endswith('_mon-sink.events.json')]
    if len(logs) != 1 or len(events) != 1:
        raise recipes.ContractError('Exactly one packaged monitor log and sink event artifact required')
    event_document = json.loads(artifact(events[0]))
    instrument_section = event_document.get('instrument') if isinstance(event_document, dict) else None
    instrument = instrument_section.get('sink_log') if isinstance(instrument_section, dict) else None
    if not isinstance(instrument, dict):
        raise recipes.ContractError('Missing or unreadable pre-cleanup sink instrument record')
    if (any(type(instrument.get(k)) is not int for k in
                ('processes', 'sessions_established', 'sessions_lost', 'malformed_lines',
                 'refused_messages', 'kept_messages', 'accepted')) or
            instrument.get('processes') != 1 or instrument.get('sessions_established') != 1 or
            any(instrument.get(k) != 0 for k in
                ('sessions_lost', 'malformed_lines', 'refused_messages', 'kept_messages'))):
        raise recipes.ContractError('Missing or unhealthy pre-cleanup sink instrument record')
    total = recipe['resolved']['neighbors'] * recipe['resolved']['prefixes_per_peer']
    if instrument.get('accepted') != total:
        raise recipes.ContractError('Instrument record disagrees with the expected full count')
    window = crossing_window(artifact(logs[0]).decode('utf-8'), total)
    if _read(root, path.name) != manifest:
        raise recipes.ContractError('Result manifest changed during assertion/timing inspection')
    return {'schema': SCHEMA, 'definition': 'Observer 10%-to-90% count-crossing window; not legacy elapsed time.',
            'expected_prefixes': total, 'window': window, 'resolution_gate': resolution_gate(window),
            'analysis_source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'source': {'result': str(path.absolute()), 'result_sha256': hashlib.sha256(manifest).hexdigest(),
                       'recipe_sha256': result['recipe_sha256'], 'engine': result['engine'],
                       'attempt_id': result['attempt']['id'],
                       'assertions_sha256': hashlib.sha256(recipes.canonical_json(spec).encode()).hexdigest(),
                       'artifacts': [present[logs[0]], present[events[0]]]},
            'performance': 'not_assessed', 'regression_policy': 'disabled',
            'limits': ['An observer delivery window excludes startup and both delivery tails.',
                       'Actual adjacent count timestamps bound coalesced crossings; nominal coalesce is not an error bound.',
                       'No route identities, attributes, total CPU work or source/build properties are established.']}


@contextmanager
def _output_parent(output):
    """Pin the destination directory before lengthy verification; follow no links."""
    if '..' in output.parts:
        raise recipes.ContractError('Output path must not contain parent traversal')
    fd = os.open(output.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in output.parts[1:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--result', required=True)
    parser.add_argument('--assertions', required=True)
    parser.add_argument('--output', required=True, help='new supplement file outside the original result package')
    parser.add_argument('--verify', action='store_true', help='reconstruct and check the existing output without writing')
    args = parser.parse_args(argv)
    try:
        output = Path(args.output).absolute()
        root = Path(args.result).absolute().parent
        if (any(p.is_symlink() for p in (output, *output.parents)) or
                output.resolve() == root.resolve() or root.resolve() in output.resolve().parents):
            raise recipes.ContractError('Write the supplement outside the immutable result package')
        with _output_parent(output) as directory:
            report = review_result(args.result, args.assertions)
            if args.verify:
                fd = os.open(output.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
                with os.fdopen(fd, 'rb') as stream:
                    if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                        raise recipes.ContractError('Supplement must be a regular file')
                    data = stream.read(MAX_LOG_BYTES + 1)
                if len(data) > MAX_LOG_BYTES:
                    raise recipes.ContractError('Supplement exceeds the inspection bound')
                stored = json.loads(data, object_pairs_hook=recipes._pairs, parse_constant=recipes._nonfinite)
                recipes._same(stored, report, 'observer timing supplement')
                return 0
            fd = os.open(output.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=directory)
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                stream.write(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + '\n')
        return 0 if report['resolution_gate']['outcome'] == 'passed' else 5
    except (OSError, ValueError, recipes.ContractError) as exc:
        parser.exit(2, f'Observer timing refused: {exc}\n')


if __name__ == '__main__':
    raise SystemExit(main())
