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
import time
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
    def __init__(self, *, target=None, diagnostics='none'):
        self.target, self.diagnostics = target, diagnostics

    def execute(self, document, workdir, attempt_id, timeout):
        env = preflight._environment()
        env['DOCKER_HOST'] = env.get('DOCKER_HOST', 'unix:///var/run/docker.sock')
        _write(workdir / 'recipe.json', document)
        if self.target is not None:
            _write(workdir / 'target.json', self.target)
        _write(workdir / 'diagnostic-options.json', {'mode': self.diagnostics})
        from recipe_diagnostics import stage, collect_diagnostics
        stage(workdir, 'setup')
        outcome = {'status': 'harness_failed', 'reason': 'Worker did not publish a terminal outcome.'}
        process = None
        worker_start = None
        worker_end = None
        worker_elapsed = None
        within_budget = None
        old = signal.signal(signal.SIGTERM, _stop)
        try:
            with (workdir / 'console.log').open('x') as log:
                worker_start = time.monotonic()
                process = subprocess.Popen(
                    [sys.executable, str(ROOT / 'recipe_worker.py'), str(workdir), attempt_id],
                    cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                try:
                    process.wait(timeout=timeout)
                    worker_end = time.monotonic()
                    worker_elapsed = worker_end - worker_start
                    within_budget = worker_elapsed <= timeout
                    terminal = workdir / 'runtime.json'
                    if terminal.is_file():
                        outcome = json.loads(terminal.read_text())
                    if process.returncode and outcome.get('status') == 'completed':
                        outcome = {'status': 'harness_failed', 'reason': f'Worker exited {process.returncode} after terminal evidence.'}
                except subprocess.TimeoutExpired:
                    worker_end = time.monotonic()
                    worker_elapsed = worker_end - worker_start
                    within_budget = False
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
            # Cleanup is mandatory even when a supplemental stage/collector fails.
            previous_int = signal.signal(signal.SIGINT, signal.SIG_IGN)
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            record_errors, stop_errors = [], []
            def record_stage(name, **kwargs):
                try:
                    stage(workdir, name, **kwargs)
                except Exception as exc:
                    record_errors.append(f'Stage {name} could not be recorded: {exc}')
            try:
                # This controller clock records the worker budget only, before
                # final diagnostics/cleanup. Missing or interrupted evidence
                # cannot be interpreted as successful deadline completion.
                try:
                    if worker_start is not None and worker_elapsed is None:
                        worker_end = time.monotonic()
                        worker_elapsed = worker_end - worker_start
                    _write(workdir / 'execution-budget.json', {
                        'schema': 'bgperf2/execution-budget/v1alpha1',
                        'scope': 'worker', 'timeout_seconds': timeout,
                        'started_monotonic_s': worker_start, 'ended_monotonic_s': worker_end,
                        'elapsed_seconds': worker_elapsed,
                        'completed_within_budget': within_budget})
                except Exception as exc:
                    record_errors.append(f'Worker budget could not be recorded: {exc}')
                if process is not None:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    except OSError as exc:
                        stop_errors.append(f'Worker group could not be stopped: {exc}')
                    if process.poll() is None:
                        try:
                            process.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            stop_errors.append('Worker could not be reaped after SIGKILL; inspect host before further execution.')
                record_stage('collection', reason='Worker stopped; collect owned diagnostics before removing resources.')
                try:
                    diagnostic = collect_diagnostics(workdir, attempt_id, env, mode=self.diagnostics)
                except Exception as exc:
                    from recipe_diagnostics import SCHEMA, memory_record
                    diagnostic = {'schema': SCHEMA, 'mode': self.diagnostics,
                                  'status': 'partial', 'errors': [f'{type(exc).__name__}: {exc}'],
                                  'containers': [], 'missing': ['Collector failed; available work retained.'],
                                  'memory': {'target': memory_record(reason='Collector failed before final memory observation.')}}
                    try:
                        _write(workdir / 'diagnostics.json', diagnostic)
                    except Exception as write_error:
                        record_errors.append(f'Diagnostic artifact could not be written: {write_error}')
                record_stage('cleanup')
                try:
                    errors = stop_errors + _cleanup(attempt_id, env)
                except Exception as exc:
                    errors = stop_errors + [f'Owned cleanup failed: {exc}']
                original_status = outcome['status']
                outcome['cleanup_errors'] = errors
                if errors:
                    outcome['status'] = 'harness_failed'
                    outcome['reason'] += ' Owned-resource cleanup failed; inspect cleanup_errors and retain work.'
                    outcome.pop('exit_code', None)
                supplemental_errors = diagnostic.get('errors', []) + record_errors
                if supplemental_errors:
                    outcome['experiment_status_before_collection'] = original_status
                    outcome['diagnostic_errors'] = supplemental_errors
                    outcome['status'] = 'harness_failed'
                    outcome['reason'] += ' Diagnostic collection was incomplete; available evidence retained.'
                    outcome.pop('exit_code', None)
                record_stage('terminal', status=outcome['status'], reason=outcome['reason'])
                if record_errors:
                    outcome['diagnostic_errors'] = diagnostic.get('errors', []) + record_errors
                    outcome.setdefault('experiment_status_before_collection', original_status)
                    outcome['status'] = 'harness_failed'
                    if not supplemental_errors:
                        outcome['reason'] += ' Stage recording was incomplete; inspect diagnostic_errors.'
                    outcome.pop('exit_code', None)
                _write(workdir / 'runtime.json', outcome)
            finally:
                signal.signal(signal.SIGTERM, old)
                signal.signal(signal.SIGINT, previous_int)

        return outcome


def run_recipe(document, *, workdir, results_dir, timeout=300, target=None,
               diagnostics='basic', backend=None, check=None):
    """Run one recipe after prerequisites, preserving every existing destination.

    Backend/check injection is library-only for controlled tests; the public CLI
    always uses the real prerequisite checks and bounded existing-engine worker.
    """
    recipes.validate_recipe(document)
    from recipe_targets import effective_roles, supplied_target, validate_target
    target = target if target is not None else supplied_target(document, document['roles']['target']['image'])
    validate_target(target, document)
    roles = effective_roles(document, target)
    if diagnostics not in ('basic', 'none'):
        raise recipes.ContractError('diagnostics must be basic or none')
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
        report = (check or preflight.check_recipe)(document, workdir=workdir, results_dir=results_dir, target=target)
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
        from recipe_diagnostics import host_snapshot
        _write(work / 'host.json', host_snapshot())
        _write(work / 'target.json', target)
        _write(work / 'target-selection.json', {
            'schema': 'bgperf2/target-selection/v1alpha1',
            'recipe_sha256': recipes.recipe_sha256(document), 'roles': roles,
            'diagnostics': diagnostics, 'instrumentation': target['provenance']['instrumentation']})
        attempt = 'bgperf_recipe_' + uuid.uuid4().hex
        try:
            outcome = (backend or SubprocessBackend(target=target, diagnostics=diagnostics)).execute(document, work, attempt, timeout)
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
