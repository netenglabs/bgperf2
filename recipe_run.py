# Copyright (C) 2026 bgperf2 contributors. Apache-2.0.
"""Explicit isolated recipe execution; importing this module never loads Docker."""
import fcntl
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import uuid

import recipes
import recipe_preflight as preflight

ROOT = Path(__file__).parent
OWNER_LABEL = 'bgperf2.recipe.attempt'


def _write(path, value):
    descriptor, temporary = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w') as output:
            output.write(json.dumps(value, indent=2, sort_keys=True) + '\n')
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _stop(signum, frame):
    raise SystemExit(128 + signum)


def _kill(process):
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        # Kernel-uninterruptible processes cannot be reaped immediately.
        # The final cleanup records that the worker remained alive.
        pass


def _cleanup(attempt_id, env):
    """Discover labelled IDs, verify ownership again, remove only those IDs."""
    host = env.get('DOCKER_HOST', 'unix:///var/run/docker.sock')
    prefix = ['docker', '--host', host]
    errors = []
    for kind, listing in (('container', ['ps', '-aq']), ('network', ['network', 'ls', '-q'])):
        try:
            identifiers = preflight.run_command(
                prefix + listing + ['--filter', f'label={OWNER_LABEL}={attempt_id}'], env=env).split()
            for identifier in identifiers:
                observed = json.loads(preflight.run_command(
                    prefix + [kind, 'inspect', identifier], env=env))[0]
                labels = (observed.get('Config', {}).get('Labels') if kind == 'container'
                          else observed.get('Labels')) or {}
                if labels.get(OWNER_LABEL) != attempt_id:
                    raise ValueError(f'{kind} {identifier} ownership changed; retained')
                command = [kind, 'rm'] + (['-f'] if kind == 'container' else []) + [identifier]
                preflight.run_command(prefix + command, env=env)
        except (preflight.ProbeError, OSError, ValueError, KeyError, TypeError, IndexError, AttributeError) as exc:
            errors.append(f'{kind}: {exc}')
    return errors


class SubprocessBackend:
    def execute(self, document, workdir, attempt_id, timeout):
        env = preflight._environment()
        env['DOCKER_HOST'] = env.get('DOCKER_HOST', 'unix:///var/run/docker.sock')
        _write(workdir / 'recipe.json', document)
        outcome = {'status': 'harness_failed', 'reason': 'Worker did not publish a terminal outcome.'}
        process = None
        old = signal.signal(signal.SIGTERM, _stop)
        try:
            with (workdir / 'console.log').open('x') as log:
                process = subprocess.Popen(
                    [sys.executable, str(ROOT / 'recipe_worker.py'), str(workdir), attempt_id],
                    cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                try:
                    process.wait(timeout=timeout)
                    terminal = workdir / 'runtime.json'
                    if terminal.is_file():
                        outcome = json.loads(terminal.read_text())
                    if process.returncode and outcome.get('status') == 'completed':
                        outcome = {'status': 'harness_failed', 'reason': f'Worker exited {process.returncode} after terminal evidence.'}
                except subprocess.TimeoutExpired:
                    _kill(process)
                    outcome = {'status': 'inconclusive', 'reason': f'Attempt exceeded its {timeout:g}s wall-clock budget; worker group stopped.'}
        except (KeyboardInterrupt, SystemExit) as exc:
            if process is not None and process.poll() is None:
                _kill(process)
            code = exc.code if isinstance(exc, SystemExit) and exc.code in (130, 143) else 130
            outcome = {'status': 'interrupted', 'exit_code': code, 'reason': f'Attempt interrupted (exit {code}); worker group stopped.'}
        except (OSError, ValueError) as exc:
            outcome = {'status': 'harness_failed', 'reason': f'Worker launch or collection failed: {exc}'}
        finally:
            # Complete bounded cleanup despite repeated stop signals. Restore
            # caller handlers after preserving the terminal outcome below.
            previous_int = signal.signal(signal.SIGINT, signal.SIG_IGN)
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            stop_errors = []
            if process is not None:
                # Reap sampler descendants even after the worker leader exits.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                if process.poll() is None:
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        stop_errors.append('Worker could not be reaped after SIGKILL; inspect host before further execution.')
            errors = stop_errors + _cleanup(attempt_id, env)
        outcome['cleanup_errors'] = errors
        if errors:
            outcome['status'] = 'harness_failed'
            outcome['reason'] += ' Owned-resource cleanup failed; inspect cleanup_errors and retain work.'
            outcome.pop('exit_code', None)
        try:
            _write(workdir / 'runtime.json', outcome)
        finally:
            signal.signal(signal.SIGTERM, old)
            signal.signal(signal.SIGINT, previous_int)
        return outcome


def run_recipe(document, *, workdir, results_dir, timeout=300, backend=None, check=None):
    """Run one recipe after prerequisites, preserving every existing destination.

    Backend/check injection is library-only for controlled tests; the public CLI
    always uses the real prerequisite checks and bounded existing-engine worker.
    """
    recipes.validate_recipe(document)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise recipes.ContractError('timeout must be a finite positive number of seconds')
    # An owner-only advisory host lock covers checks, execution and cleanup.
    lockpath = Path('/tmp') / f'bgperf2-recipe-{os.getuid()}.lock'
    descriptor = os.open(lockpath, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise recipes.ContractError('Another cooperating recipe attempt holds the host lock') from exc
        report = (check or preflight.check_recipe)(document, workdir=workdir, results_dir=results_dir)
        if report['status'] != 'checks_passed':
            # Refused destinations must never be used to publish a report.
            return {'status': 'setup_refused', 'exit_code': 2, 'reason': 'Prerequisites refused; no attempt was started.', 'prerequisites': report}
        work = Path(workdir).resolve()
        results = Path(results_dir).resolve()
        # Repeat non-overwrite and nesting guards even with injected checks.
        if not Path(workdir).is_absolute() or not Path(results_dir).is_absolute() or work == results or work in results.parents or results in work.parents:
            raise recipes.ContractError('Choose absolute, distinct, nonnested attempt destinations')
        if os.path.lexists(work) or os.path.lexists(results):
            raise recipes.ContractError('Attempt destinations must not already exist')
        work.mkdir(parents=True, exist_ok=False)
        _write(work / 'prerequisites.json', report)
        attempt = 'bgperf_recipe_' + uuid.uuid4().hex
        try:
            outcome = (backend or SubprocessBackend()).execute(document, work, attempt, timeout)
        except Exception as exc:
            outcome = {'status': 'harness_failed', 'reason': f'Runtime backend failed: {exc}'}
            _write(work / 'runtime.json', outcome)
        from recipe_results import write_result_package, verify_result_package
        manifest = write_result_package(document, results_dir=results, workdir=work, attempt_id=attempt,
                                    status=outcome['status'], reason=outcome['reason'],
                                    exit_code=outcome.get('exit_code'), reproduction=outcome.get('reproduction'))
        verification = verify_result_package(results / 'result.json')
        if not verification['valid']:
            raise recipes.ContractError('Result verification failed; preserve attempt and inspect result.json')
        return manifest
    finally:
        os.close(descriptor)
