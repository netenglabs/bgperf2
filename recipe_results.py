# Copyright (C) 2026 bgperf2 contributors.
# Licensed under the Apache License, Version 2.0.
"""Portable local result packages; never import or contact a runtime."""

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import stat
import shutil

from recipes import (ARTIFACT_KINDS, ContractError, RESULT_EXIT_CODES, RESULT_SCHEMA,
                     canonical_json, read_document, recipe_sha256,
                     validate_recipe, validate_result, _artifact_path, _pairs, _nonfinite)


def _write(path, value):
    with path.open('x', encoding='utf-8') as stream:
        stream.write(value)


def _json(value):
    return json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n'


class _RuntimeSocket(ContractError):
    """A runtime endpoint has no portable file contents to collect."""


@contextmanager
def _regular_file(root, relative):
    """Refuse symlinks at every component, including an artifact's parents."""
    _artifact_path(relative, 'artifact path')
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        parts = Path(relative).parts
        for component in parts[:-1]:
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                            dir_fd=directory)
            os.close(directory)
            directory = child
        # A BIRD control socket can be mode 000 and cannot be opened as a file.
        # Inspect its type without following the leaf or contacting its endpoint.
        if stat.S_ISSOCK(os.stat(parts[-1], dir_fd=directory, follow_symlinks=False).st_mode):
            raise _RuntimeSocket(f'{relative}: runtime Unix-domain socket')
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                     dir_fd=directory)
        with os.fdopen(fd, 'rb') as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ContractError(f'{relative}: artifact must be a regular file')
            yield stream
    except OSError as exc:
        raise ContractError(f'{relative}: unsafe or unavailable artifact: {exc}') from exc
    finally:
        os.close(directory)


def _regular_bytes(root, relative):
    with _regular_file(root, relative) as stream:
        return stream.read()


def _digest_file(root, relative):
    digest = hashlib.sha256()
    with _regular_file(root, relative) as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _kind(relative):
    name = Path(relative).name
    if 'events' in name and name.endswith('.json'):
        return 'events'
    if name.endswith('.versions.json') or ('provenance' in name and name.endswith('.json')):
        return 'provenance'
    if name.endswith(('.csv', '.stats')):
        return 'samples'
    if name.endswith(('.yaml', '.yml', '.conf', '.cfg')):
        return 'configuration'
    if name.endswith('.log'):
        return 'log'
    return 'other'


def write_result_package(recipe, *, results_dir, workdir, attempt_id, status,
                         reason, exit_code=None, reproduction=None, artifacts=None):
    """Snapshot available work, retaining partial evidence on collection errors.

    Both roots must be private attempt directories owned by the caller. Existing
    result files are preserved and included. Runtime Unix-domain sockets are
    listed as omissions without reading or copying them. Symlinks and other
    nonregular work entries are collection errors, never dereferenced. ``artifacts``
    optionally maps relative package paths to a contract artifact kind.
    """
    validate_recipe(recipe)
    if status not in RESULT_EXIT_CODES:
        raise ContractError(f'unknown result status: {status}')
    if exit_code is None:
        exit_code = RESULT_EXIT_CODES[status][0]
    if exit_code not in RESULT_EXIT_CODES[status]:
        raise ContractError('result exit code does not match status')
    results, work = Path(results_dir), Path(workdir)
    if results.is_symlink() or work.is_symlink():
        raise ContractError('attempt roots must not be symlinks')
    if work.exists() and not work.is_dir():
        raise ContractError('attempt work root must be a directory')
    if results.resolve() == work.resolve() or results.resolve() in work.resolve().parents or work.resolve() in results.resolve().parents:
        raise ContractError('attempt work and results must be distinct and nonnested')
    overrides = artifacts or {}
    for path, kind in overrides.items():
        _artifact_path(path, 'artifact override')
        if kind not in ARTIFACT_KINDS:
            raise ContractError(f'{path}: unknown artifact kind {kind}')
    results.mkdir(parents=True, exist_ok=True)
    for reserved in ('recipe.json', 'result.json', 'SUMMARY.txt', 'collection-errors.json',
                     'collection-omissions.json', 'work'):
        if os.path.lexists(results / reserved):
            raise ContractError(f'{results / reserved}: package output already exists')
    errors, omissions = [], []
    (results / 'work').mkdir()
    if work.exists():
        for directory, dirs, files in os.walk(work, followlinks=False,
                                               onerror=lambda exc: errors.append(f'work tree traversal failed: {exc}')):
            base = Path(directory)
            for name in list(dirs):
                path = base / name
                if path.is_symlink():
                    dirs.remove(name)
                    errors.append(f'{path.relative_to(work)}: symlink directory omitted')
            for name in sorted(files):
                relative = (base / name).relative_to(work).as_posix()
                try:
                    target = results / 'work' / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with _regular_file(work, relative) as source, target.open('xb') as stream:
                        shutil.copyfileobj(source, stream, length=1024 * 1024)
                except _RuntimeSocket:
                    omissions.append({'path': 'work/' + relative, 'type': 'unix_socket',
                                      'reason': 'Runtime Unix-domain sockets are not portable evidence files; not read or copied.'})
                except (OSError, ContractError) as exc:
                    errors.append(f'{relative}: {exc}')
    else:
        errors.append('work directory unavailable; no work artifacts collected')
    _write(results / 'recipe.json', canonical_json(recipe) + '\n')
    if omissions:
        _write(results / 'collection-omissions.json', _json({'omissions': omissions}))
    if errors:
        _write(results / 'collection-errors.json', _json({'errors': errors}))
        status, exit_code = 'harness_failed', 3
        reason = f'{reason}; artifact collection incomplete (see collection-errors.json)'
    if reproduction is None:
        outcome, evidence = 'inconclusive', []
        outcome_reason = reason
        witness = results / 'work' / 'runtime.json'
        # Only a runtime completion witness may decide the completion predicate.
        if status == 'completed' and witness.is_file():
            try:
                witnessed = read_document(witness).get('status') == 'completed'
            except ContractError:
                witnessed = False
            if witnessed:
                outcome = ('reproduced' if recipe['reproduction']['expected_outcome'] == 'experiment_completed'
                           else 'not_reproduced')
                evidence = ['work/runtime.json']
        reproduction = {'outcome': outcome, 'reason': outcome_reason, 'evidence': evidence}
    if reproduction['outcome'] in ('reproduced', 'not_reproduced'):
        available = []
        for path in reproduction.get('evidence', []):
            try:
                _digest_file(results, path)
                available.append(path)
            except (OSError, ContractError):
                pass
        if len(available) != len(reproduction.get('evidence', [])) or not available:
            reproduction = {'outcome': 'inconclusive',
                            'reason': 'Required reproduction evidence could not be collected.',
                            'evidence': available}
    summary = (f"Attempt: {attempt_id}\nStatus: {status} (exit {exit_code})\n"
               f"Reason: {reason}\nReproduction: {reproduction['outcome']}\n"
               'Comparison: not_assessed\n'
               'Verify this package with: recipes.py result-verify result.json\n')
    _write(results / 'SUMMARY.txt', summary)
    references = []
    def refuse_walk_error(exc):
        raise ContractError(f'result tree traversal failed: {exc}')
    for directory, dirs, files in os.walk(results, followlinks=False, onerror=refuse_walk_error):
        base = Path(directory)
        for name in dirs:
            if (base / name).is_symlink():
                raise ContractError('symlink directory in result package')
        for name in sorted(files):
            relative = (base / name).relative_to(results).as_posix()
            digest = _digest_file(results, relative)
            references.append({'kind': overrides.get(relative, _kind(relative)),
                               'path': relative, 'sha256': digest,
                               'availability': 'present', 'reason': None})
    kinds = {item['kind'] for item in references}
    for kind in ARTIFACT_KINDS[:-1]:
        if kind not in kinds:
            references.append({'kind': kind, 'path': None, 'sha256': None,
                               'availability': 'missing',
                               'reason': f'No {kind} artifact was produced or could be collected.'})
    manifest = {'schema': RESULT_SCHEMA, 'recipe_sha256': recipe_sha256(recipe),
                'engine': recipe['engine'], 'attempt': {'id': attempt_id},
                'status': status, 'exit_code': exit_code, 'reproduction': reproduction,
                'comparison': {'qualification': 'not_assessed',
                               'reason': 'Recipe execution does not qualify performance comparisons.'},
                'artifacts': references}
    validate_result(manifest)
    _write(results / 'result.json', _json(manifest))
    return manifest


def verify_result_package(manifest_path):
    """Verify declarations, actual file bytes and the bundled recipe binding."""
    manifest_path = Path(manifest_path)
    if manifest_path.is_symlink():
        raise ContractError('manifest must not be a symlink')
    root = manifest_path.parent
    if root.is_symlink() or not root.is_dir():
        raise ContractError('package root must be a directory, not a symlink')
    try:
        document = json.loads(_regular_bytes(root, manifest_path.name).decode('utf-8'),
                              object_pairs_hook=_pairs, parse_constant=_nonfinite)
    except (UnicodeError, ValueError) as exc:
        raise ContractError(f'manifest: invalid JSON: {exc}') from exc
    validate_result(document)
    verified = 0
    listed = set()
    for artifact in document['artifacts']:
        if artifact['availability'] != 'present':
            continue
        relative = artifact['path']
        try:
            digest = _digest_file(root, relative)
        except OSError as exc:
            raise ContractError(f'{relative}: unavailable artifact: {exc}') from exc
        if digest != artifact['sha256']:
            raise ContractError(f'{relative}: SHA-256 mismatch')
        verified += 1
        listed.add(relative)
    def refuse_walk_error(exc):
        raise ContractError(f'package tree traversal failed: {exc}')
    for directory, dirs, files in os.walk(root, followlinks=False, onerror=refuse_walk_error):
        base = Path(directory)
        for name in dirs:
            if (base / name).is_symlink():
                raise ContractError('symlink directory in result package')
        for name in files:
            relative = (base / name).relative_to(root).as_posix()
            if relative == manifest_path.name:
                continue
            if relative not in listed:
                raise ContractError(f'{relative}: unlisted artifact in result package')
            with _regular_file(root, relative):
                pass
    if 'recipe.json' not in listed:
        raise ContractError('package must include a checksummed recipe.json')
    try:
        recipe = json.loads(_regular_bytes(root, 'recipe.json').decode('utf-8'),
                            object_pairs_hook=_pairs, parse_constant=_nonfinite)
    except (UnicodeError, ValueError) as exc:
        raise ContractError(f'recipe.json: invalid JSON: {exc}') from exc
    validate_recipe(recipe)
    if recipe_sha256(recipe) != document['recipe_sha256']:
        raise ContractError('recipe.json: canonical recipe SHA-256 mismatch')
    if recipe['engine'] != document['engine']:
        raise ContractError('recipe.json: engine identity differs from result')
    return {'valid': True, 'schema': RESULT_SCHEMA, 'artifacts_verified': verified,
            'recipe_sha256': document['recipe_sha256']}
