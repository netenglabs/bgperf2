# Copyright (C) 2026 bgperf2 contributors.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy at http://www.apache.org/licenses/LICENSE-2.0

"""Offline recipe plans and explicitly requested, read-only prerequisite snapshots.

These reports qualify only the implemented checks. They never authorize execution,
acquire an image, or decide performance comparison suitability.
"""

import copy
import json
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import subprocess
import sys

import recipes

# Importing this module is also part of the offline plan path. Canonicalize
# destinations only in check; even resolving __file__ would consult the host.
ROOT = Path(__file__).parent
PREREQUISITES_SCHEMA = 'bgperf2/prerequisites/v1alpha1'
PROBE_TIMEOUT_SECONDS = 15


class ProbeError(ValueError):
    """A bounded read-only prerequisite probe could not be completed."""


def run_command(argv, *, env=None):
    """Return stdout from one bounded command; reap its whole group on timeout."""
    try:
        with subprocess.Popen([str(arg) for arg in argv], cwd=ROOT, env=env,
                              shell=False, start_new_session=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True) as process:
            try:
                stdout, stderr = process.communicate(timeout=PROBE_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired as exc:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.communicate()
                raise ProbeError(f'{argv[0]} timed out after {PROBE_TIMEOUT_SECONDS}s; '
                                 'its probe process group was stopped') from exc
            if process.returncode:
                message = (stderr or stdout).strip()[-2000:]
                raise ProbeError(f'{argv[0]} exited {process.returncode}: {message}')
            return stdout
    except (OSError, UnicodeError) as exc:
        raise ProbeError(f'Cannot run {argv[0]}: {exc}') from exc


def _add(report, name, status, reason, **details):
    report['checks'].append({'name': name, 'status': status, 'reason': reason,
                             'details': details})
    if status == 'refused':
        report['status'] = 'refused'


def _report(document, mode):
    # This must precede ALL filesystem, environment, runtime and subprocess probes.
    recipes.validate_recipe(document)
    report = {'schema': PREREQUISITES_SCHEMA, 'mode': mode,
              'recipe_sha256': recipes.recipe_sha256(document),
              'status': 'checks_passed', 'execution': 'not_implemented',
              'comparison': 'not_assessed', 'checks': [],
              'acquisition': 'none',
              'scope': 'Only implemented checks are reported; this is not a ready-to-run qualification.'}
    for key in ('selection', 'engine', 'roles', 'resources', 'inputs'):
        report[key] = copy.deepcopy(document[key])
    _add(report, 'recipe', 'pass', 'The strict recipe contract is valid.')
    _add(report, 'resources', 'unknown',
         'Recipe CPU, memory and storage requirements are unknown; no capacity threshold can be assessed.',
         requirements=copy.deepcopy(document['resources']))
    _add(report, 'downloads', 'unknown',
         'Download sizes and availability are unknown; no acquisition is performed.',
         download_bytes=None)
    _add(report, 'capabilities', 'unknown',
         'Container network capabilities and full hardware qualification are not assessed.')
    _add(report, 'host_contention', 'unknown',
         'CPU contention is not sampled; the bootstrap guard only checks for active measurement locks and containers.')
    return report


def plan_recipe(document):
    """Describe exact declared inputs without consulting the host or acquiring data."""
    report = _report(document, 'plan')
    for role, declaration in document['roles'].items():
        _add(report, 'image.' + role, 'unknown',
             'Declared immutable reference; local availability, contents and build provenance are unverified.',
             requested=declaration['image'], image_id=None, platform=None,
             local_size_bytes=None, download_bytes=None)
    _add(report, 'runtime', 'unknown', 'Host prerequisites are not probed by plan.')
    _add(report, 'destinations', 'unknown', 'No work or results destination is selected or created by plan.')
    return report


def _environment():
    # Git hooks can export GIT_INDEX_FILE/GIT_DIR and arbitrary config overrides.
    # Remove the entire namespace before asking about this explicit checkout.
    env = {key: value for key, value in os.environ.items()
           if not key.startswith('GIT_') and key not in (
               'DOCKER_CONTEXT', 'DOCKER_CONFIG', 'DOCKER_TLS',
               'DOCKER_TLS_VERIFY', 'DOCKER_CERT_PATH')}
    env['GIT_OPTIONAL_LOCKS'] = '0'  # status must never refresh the index.
    return env


def _engine(report, document, env):
    try:
        # status must not invoke an optional, locally configured fsmonitor hook.
        git = ['git', '-c', 'core.fsmonitor=false', '-c', 'core.untrackedCache=false',
               '-C', str(ROOT)]
        revision = run_command([*git, 'rev-parse', '--verify', 'HEAD^{commit}'], env=env).strip()
        if not re.fullmatch(r'[0-9a-f]{40}', revision):
            raise ProbeError('Git returned an invalid full HEAD revision')
        dirty = run_command([*git, 'status', '--porcelain',
                             '--untracked-files=all', '--ignore-submodules=none'], env=env)
        if revision != document['engine']['revision']:
            raise ProbeError('Check out the exact recipe engine revision before checking prerequisites '
                             f'(requested {document["engine"]["revision"]}, actual {revision})')
        if dirty.strip():
            raise ProbeError('Engine checkout has tracked, staged or untracked changes; use a clean checkout')
        _add(report, 'engine', 'pass', 'The engine checkout is clean at the requested revision.', revision=revision)
        return True
    except (ProbeError, OSError, ValueError, TypeError) as exc:
        _add(report, 'engine', 'refused', str(exc))
        return False


def _image(report, role, requested, host, env):
    try:
        text = run_command(['docker', '--host', host, 'image', 'inspect', requested], env=env)
        images = json.loads(text, object_pairs_hook=recipes._pairs,
                            parse_constant=recipes._nonfinite)
        if not isinstance(images, list) or len(images) != 1 or not isinstance(images[0], dict):
            raise ProbeError('docker image inspect must return exactly one image object')
        image = images[0]
        image_id = image.get('Id')
        if not isinstance(image_id, str) or not re.fullmatch(r'sha256:[0-9a-f]{64}', image_id):
            raise ProbeError('docker image inspect returned a missing or malformed image ID')
        digests = image.get('RepoDigests')
        if digests is not None and (not isinstance(digests, list) or
                                   not all(isinstance(value, str) for value in digests)):
            raise ProbeError('docker image inspect returned malformed RepoDigests')
        if requested.startswith('sha256:'):
            if image_id != requested:
                raise ProbeError('Local image ID differs from the requested immutable image ID')
        else:
            if not isinstance(digests, list) or requested not in digests:
                raise ProbeError('Requested repository digest is absent from the local image RepoDigests')
        size, operating_system, architecture = image.get('Size'), image.get('Os'), image.get('Architecture')
        if (isinstance(size, bool) or not isinstance(size, int) or size < 0 or
                not isinstance(operating_system, str) or not operating_system or
                not isinstance(architecture, str) or not architecture):
            raise ProbeError('docker image inspect returned malformed size or platform metadata')
        variant = image.get('Variant')
        if variant is not None and not isinstance(variant, str):
            raise ProbeError('docker image inspect returned malformed platform variant')
        _add(report, 'image.' + role, 'pass',
             'The exact immutable reference is present locally. Build/source provenance is not established.',
             requested=requested, image_id=image_id,
             repo_digests=digests,
             platform={'os': operating_system, 'architecture': architecture, 'variant': variant},
             local_size_bytes=size, download_bytes=None)
    except (ProbeError, OSError, ValueError, TypeError) as exc:
        _add(report, 'image.' + role, 'refused',
             f'{exc}. Supply the selected immutable image locally through a separately authorized preparation path.',
             requested=requested)


def _capacity(report):
    try:
        count = os.cpu_count()
        affinity = sorted(os.sched_getaffinity(0))
        memory = Path('/proc/meminfo').read_text()
        match = re.search(r'^MemAvailable:\s+(\d+) kB$', memory, re.M)
        if not match or not isinstance(count, int) or count < 1 or not affinity:
            raise ProbeError('CPU or MemAvailable snapshot is unavailable')
        _add(report, 'host_capacity', 'pass',
             'Read-only capacity snapshot; unknown recipe requirements prevent capacity qualification.',
             cpu_count=count, affinity=affinity, memory_available_bytes=int(match[1]) * 1024)
    except (OSError, ValueError, AttributeError) as exc:
        _add(report, 'host_capacity', 'unknown', f'Capacity snapshot unavailable: {exc}')


def _mount_key(path):
    # /proc/mounts uses octal escapes; match that spelling through the shared helpers.
    return str(path).replace('\\', r'\134').replace(' ', r'\040').replace('\t', r'\011').replace('\n', r'\012')


def filesystem_type(path, mounts_text):
    # contention initializes Linux clock metadata on import: keep it off plan's
    # import path while reusing the established filesystem interpretation.
    from contention import filesystem_type as implementation
    return implementation(path, mounts_text)


def is_memory_backed(path, mounts_text):
    from contention import is_memory_backed as implementation
    return implementation(path, mounts_text)


def _destination(report, name, value, mounts):
    try:
        path = Path(value)
        if not path.is_absolute():
            raise ProbeError('Specify an absolute new destination')
        if os.path.lexists(path):
            raise ProbeError('Destination already exists (including a dangling symlink); choose a new path')
        # Resolve would hide a dangling ancestor alias by replacing it with its
        # missing target. The caller's requested path must also be traversable.
        requested_ancestor = path.parent
        while not os.path.lexists(requested_ancestor):
            parent = requested_ancestor.parent
            if parent == requested_ancestor:
                raise ProbeError('Cannot find an existing destination ancestor')
            requested_ancestor = parent
        if not requested_ancestor.is_dir():
            raise ProbeError('Nearest existing requested ancestor is not a directory (possibly a dangling symlink)')
        canonical = path.resolve(strict=False)
        if os.path.lexists(canonical):
            raise ProbeError('Canonical destination already exists; choose a new path')
        engine = ROOT.resolve()
        if canonical == engine or engine in canonical.parents:
            raise ProbeError('Choose a destination outside the engine checkout')
        ancestor = canonical.parent
        while not os.path.lexists(ancestor):
            parent = ancestor.parent
            if parent == ancestor:
                raise ProbeError('Cannot find an existing destination ancestor')
            ancestor = parent
        if not ancestor.is_dir():
            raise ProbeError('Nearest existing ancestor is not a directory')
        if not os.access(ancestor, os.W_OK | os.X_OK):
            raise ProbeError('Nearest existing directory must be writable and searchable')
        fs_type = filesystem_type(_mount_key(ancestor), mounts)
        if fs_type is None:
            raise ProbeError('Cannot identify destination filesystem from /proc/mounts')
        if is_memory_backed(_mount_key(ancestor), mounts):
            raise ProbeError('Destination uses a RAM-backed filesystem; select disk-backed storage')
        stats = os.statvfs(ancestor)
        _add(report, 'destinations.' + name, 'pass',
             'New disk-backed destination; access and free space are advisory snapshots, with no creation or capacity threshold.',
             requested=str(path), canonical=str(canonical), existing_ancestor=str(ancestor),
             filesystem_type=fs_type, available_bytes=stats.f_bavail * stats.f_frsize)
        return canonical
    except (ProbeError, OSError, ValueError, TypeError, RuntimeError) as exc:
        _add(report, 'destinations.' + name, 'refused', str(exc), requested=str(value))
        return None


def check_recipe(document, *, workdir, results_dir):
    """Take explicit bounded snapshots, without acquiring or creating anything."""
    report = _report(document, 'check')
    env = _environment()
    host = env.get('DOCKER_HOST', 'unix:///var/run/docker.sock')
    local = (host.startswith('unix:///') and len(host) > len('unix:///') and
             '\x00' not in host and '?' not in host and '#' not in host)
    if local:
        _add(report, 'docker_endpoint', 'pass', 'Only the explicit local Unix Docker endpoint is used.', host=host)
        env['DOCKER_HOST'] = host
    else:
        _add(report, 'docker_endpoint', 'refused',
             'Set DOCKER_HOST to a local absolute unix:/// socket; remote Docker endpoints are refused before Docker or bootstrap probes.', host=host)
    runtime = platform.system() == 'Linux' and sys.version_info[:2] == (3, 14)
    _add(report, 'runtime', 'pass' if runtime else 'refused',
         'Linux and Python 3.14 are required; use the locked engine environment.',
         operating_system=platform.system(), python=list(sys.version_info[:3]))
    missing = [tool for tool in ('docker', 'mpstat', 'free') if shutil.which(tool) is None]
    _add(report, 'tools', 'refused' if missing else 'pass',
         ('Install the missing OS tools manually: ' + ', '.join(missing)) if missing else
         'Docker, mpstat and free executables are available.', missing=missing)
    engine_ok = _engine(report, document, env)
    bootstrap_ok = False
    python = ROOT / 'venv/bin/python'
    if local and runtime and not missing and engine_ok:
        try:
            if not python.is_file():
                raise ProbeError('No existing engine venv; run the documented hashed bootstrap separately')
            output = run_command([str(python), '-I', str(ROOT / 'scripts/bootstrap.py'), '--check'], env=env)
            _add(report, 'bootstrap', 'pass',
                 'Existing hashed environment and active-measurement guard passed; this is not CPU-idleness qualification.',
                 output=output.strip()[-4000:])
            bootstrap_ok = True
        except (ProbeError, OSError, ValueError, TypeError) as exc:
            _add(report, 'bootstrap', 'refused', f'{exc}. Follow docs/python-environment.md; no installation was attempted.')
    else:
        _add(report, 'bootstrap', 'unknown', 'Not probed because an earlier runtime, tool, engine or local-endpoint prerequisite was refused.')
    for role, declaration in document['roles'].items():
        if bootstrap_ok:
            _image(report, role, declaration['image'], host, env)
        else:
            _add(report, 'image.' + role, 'unknown',
                 'Not probed: the existing environment and active-measurement guard must pass first.',
                 requested=declaration['image'])
    _capacity(report)
    try:
        mounts = Path('/proc/mounts').read_text()
    except OSError as exc:
        _add(report, 'destinations', 'refused', f'Cannot read filesystem mounts: {exc}')
    else:
        work = _destination(report, 'workdir', workdir, mounts)
        results = _destination(report, 'results_dir', results_dir, mounts)
        if work is not None and results is not None:
            overlap = work == results or work in results.parents or results in work.parents
            _add(report, 'destinations.isolation', 'refused' if overlap else 'pass',
                 'Choose distinct, nonnested work and results destinations.' if overlap else
                 'Canonical work and results destinations are distinct and nonnested.')
    return report
