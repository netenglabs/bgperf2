# Copyright (C) 2026 bgperf2 contributors.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy at http://www.apache.org/licenses/LICENSE-2.0

"""Plan or explicitly acquire only a validated recipe's selected immutable images."""

import copy
import json

import recipe_preflight as runtime
import recipes

PREPARATION_SCHEMA = 'bgperf2/preparation/v1alpha1'
PULL_TIMEOUT_SECONDS = 600


def _missing_image(error, requested, host):
    """Recognize only Docker's exact, completed missing-image inspect response."""
    if (not isinstance(error, runtime.CommandError) or error.returncode != 1 or
            error.argv != ('docker', '--host', host, 'image', 'inspect', requested) or
            error.stderr.strip() not in (
                f'Error response from daemon: No such image: {requested}',
                f'Error: No such image: {requested}')):
        return False
    if not error.stdout.strip():
        return True
    try:
        return json.loads(error.stdout, object_pairs_hook=recipes._pairs,
                          parse_constant=recipes._nonfinite) == []
    except (ValueError, TypeError, RecursionError):
        return False


def _report(document, pull):
    # Validate every source test before filesystem, environment or runtime probes.
    recipes.validate_recipe(document)
    report = {
        'schema': PREPARATION_SCHEMA, 'mode': 'prepare',
        'recipe_sha256': recipes.recipe_sha256(document),
        'status': 'planned', 'execution': 'not_implemented',
        'comparison': 'not_assessed', 'pull_requested': pull,
        'acquisition': 'none', 'cache_changes': 'none', 'partial': False,
        'checks': [], 'items': [],
        'scope': 'Selected image availability only; no experiment or host qualification is established.',
        'disclosure': {
            'references': [], 'download_bytes': None, 'incremental_size_bytes': None,
            'size_reason': 'Local image logical sizes do not determine compressed downloads or incremental cache storage.',
            'effects': 'Explicit pulls contact selected registries and may add shared Docker cache data. No builds, tagging, containers, work/results directories or result artifacts are created.',
            'retention': 'Acquired or partial cache data is retained. Failure, interruption or timeout does not guarantee download cancellation or rollback; no images are deleted or retagged.',
            'provenance': 'Immutable image identity does not establish source/build reconstruction or daemon binary identity; these remain unknown.'}}
    for key in ('selection', 'engine', 'roles', 'resources', 'inputs'):
        report[key] = copy.deepcopy(document[key])
    runtime._add(report, 'recipe', 'pass', 'The strict recipe contract is valid.')
    runtime._add(report, 'resources', 'unknown',
                 'CPU, memory and storage requirements remain unknown; no capacity threshold is assessed.',
                 requirements=copy.deepcopy(document['resources']))
    runtime._add(report, 'provenance', 'unknown', report['disclosure']['provenance'])
    # A shared pin is inspected and acquired once, while retaining every role.
    items = {}
    for role, declaration in document['roles'].items():
        requested = declaration['image']
        if requested not in items:
            items[requested] = {
                'requested': requested, 'roles': [], 'action': 'unavailable',
                'state': 'skipped', 'image_id': None, 'repo_digests': None,
                'platform': None, 'local_size_bytes': None,
                'download_bytes': None, 'incremental_size_bytes': None,
                'reason': 'Not probed: runtime prerequisites must pass first.'}
        items[requested]['roles'].append(role)
    report['items'] = list(items.values())
    return report


def _skip_pending(items, reason):
    for item in items:
        if item['action'] == 'pull' and item['state'] == 'missing':
            item['state'] = 'skipped'
            item['reason'] = reason


def prepare_recipe(document, *, pull=False, emit_disclosure=None):
    """Observe selected pins, or pull missing repository digests with disclosure.

    Library callers must supply a disclosure callback for an actual acquisition.
    It receives a copy of the complete pre-mutation report and must return only
    after making the disclosure visible. The CLI flushes this JSON to stderr.
    """
    report = _report(document, pull)
    env, host, bootstrap_ok = runtime.runtime_prerequisites(report, document)
    if not bootstrap_ok:
        return report
    for index, item in enumerate(report['items']):
        requested = item['requested']
        try:
            item.update(runtime.inspect_image(requested, host, env))
        except (runtime.ProbeError, OSError, ValueError, TypeError, RecursionError) as exc:
            if _missing_image(exc, requested, host):
                item['state'] = 'missing'
                if requested.startswith('sha256:'):
                    item['reason'] = 'A missing bare image ID cannot be fetched. Supply that exact image locally; no build, tag or registry fallback is permitted.'
                    status = 'refused'
                else:
                    item['action'] = 'pull'
                    item['reason'] = 'The exact repository digest is missing locally; acquisition requires explicit --pull.'
                    status = 'unknown'
            else:
                item['state'] = 'failed'
                item['reason'] = f'Image inspection refused: {exc}'
                status = 'refused'
        else:
            item['action'], item['state'] = 'keep', 'available'
            item['reason'] = 'The exact immutable reference is present locally and will be reused.'
            status = 'pass'
        runtime._add(report, f'image.{index}', status, item['reason'],
                     requested=requested, roles=copy.deepcopy(item['roles']))
    pending = [item for item in report['items'] if item['action'] == 'pull']
    report['disclosure']['references'] = [item['requested'] for item in pending]
    if report['status'] == 'refused':
        _skip_pending(pending, 'Acquisition skipped because a selected image or runtime prerequisite was refused.')
        return report
    if not pull:
        return report
    if not pending:
        report['status'] = 'prepared'
        return report
    try:
        if not callable(emit_disclosure):
            raise ValueError('A disclosure callback is required before image acquisition')
        emit_disclosure(copy.deepcopy(report))
    except Exception as exc:
        runtime._add(report, 'disclosure', 'refused', f'Cannot disclose acquisition before mutation: {exc}')
        _skip_pending(pending, 'Acquisition skipped because disclosure was unavailable.')
        return report
    runtime._add(report, 'disclosure', 'pass', 'The complete acquisition plan was disclosed before mutation.')
    for index, item in enumerate(pending):
        try:
            # Reuse the existing active-lock/container guard immediately before
            # each mutation; never grant a stale initial observation for all pulls.
            runtime.run_command([str(runtime.ROOT / 'venv/bin/python'), '-I',
                                 str(runtime.ROOT / 'scripts/quality_gate.py'),
                                 '--guard-only'], env=env)
        except (runtime.ProbeError, OSError, ValueError, TypeError) as exc:
            runtime._add(report, f'acquisition_guard.{index}', 'refused', str(exc))
            _skip_pending(pending, 'Acquisition skipped because the active-measurement guard was refused.')
            break
        runtime._add(report, f'acquisition_guard.{index}', 'pass',
                     'The existing active-measurement guard passed immediately before this pull.')
        report['acquisition'] = 'selected_repository_digests'
        report['cache_changes'] = 'possible'
        try:
            runtime.run_command(['docker', '--host', host, 'image', 'pull', item['requested']],
                                env=env, timeout=PULL_TIMEOUT_SECONDS)
            # Pull success is not identity proof; inspect the same exact pin.
            item.update(runtime.inspect_image(item['requested'], host, env))
        except (runtime.ProbeError, OSError, ValueError, TypeError, RecursionError) as exc:
            item['state'] = 'failed'
            item['reason'] = f'Acquisition or identity verification failed: {exc}. Unverified partial cache changes may remain.'
            runtime._add(report, f'acquisition.{index}', 'refused', item['reason'],
                         requested=item['requested'])
            _skip_pending(pending, 'Acquisition skipped after an earlier pull or identity verification failed.')
            break
        item['state'] = 'acquired'
        item['reason'] = 'The selected digest was pulled and its exact immutable identity was verified locally.'
        report['cache_changes'] = 'observed'
        runtime._add(report, f'acquisition.{index}', 'pass', item['reason'],
                     requested=item['requested'])
    if report['status'] != 'refused':
        report['status'] = 'prepared'
    report['partial'] = report['status'] == 'refused' and report['acquisition'] != 'none'
    return report
