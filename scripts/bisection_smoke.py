#!/usr/bin/env python3
# Copyright (C) 2026 bgperf2 contributors. Apache-2.0.
"""Exercise deterministic bisection with SIMULATED source, builds and workers.

No real Git command, build, subprocess, network or daemon is permitted. The
maintained public CLI still plans, records, packages and verifies local evidence.
These fixtures establish no BIRD bug, binary identity or performance conclusion.
"""
import argparse
from contextlib import ExitStack, redirect_stdout
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import recipes
import recipe_bisection as bisection
import recipe_targets as targets
from scripts.comparison_smoke import ComparisonRuntime
from scripts.investigation_smoke import _command as recipe_command
from scripts.recipe_smoke import SimulatedHost, _write

CASES = ('assertions', 'target-crash', 'skipped', 'ambiguous', 'unstable')
TOOLCHAIN = 'sha256:' + 'a' * 64
RUNTIME = 'sha256:' + 'b' * 64


def _forbidden(*args, **kwargs):
    raise AssertionError('Bisection smoke forbids unmodelled subprocess and network operations')


def _command(arguments, *, expected=0):
    stream = io.StringIO()
    with redirect_stdout(stream):
        code = bisection.main(list(map(str, arguments)))
    if code != expected:
        raise RuntimeError(f'Simulated bisection {arguments[0]} exited {code}; expected {expected}')
    return json.loads(stream.getvalue())


class SimulatedOS:
    """Redirect only the modeled recipe controller's host lock to this output.

    Other modules retain the actual os module, including bisection's session
    locking. Independent walkthroughs never contend with real recipe attempts.
    """
    def __init__(self, lock):
        self.lock = lock
        self.original_lock = Path('/tmp') / f'bgperf2-recipe-{os.getuid()}.lock'

    def __getattr__(self, name):
        return getattr(os, name)

    def open(self, path, flags, mode=0o777, *, dir_fd=None):
        selected = self.lock if os.fsdecode(path) == str(self.original_lock) else path
        return os.open(selected, flags, mode, dir_fd=dir_fd)


class SimulatedChain:
    """Hash-valid commit proofs for an inert nine-revision first-parent chain."""
    def __init__(self, root, recipe):
        self.builds, self.objects, self.calls = [], {}, []
        previous = None
        for index in range(9):
            raw = (f'tree {"0" * 40}\n' + (f'parent {previous}\n' if previous else '') +
                   f'author SIMULATED <fixture@example.invalid> {index} +0000\n'
                   f'committer SIMULATED <fixture@example.invalid> {index} +0000\n\n'
                   f'SIMULATED inert revision {index}\n').encode()
            revision = hashlib.sha1(b'commit ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
            source = {'requested_revision': revision, 'commit': revision, 'checkout_head': revision,
                      'dirty': False, 'include_dirty': False, 'patch_sha256': hashlib.sha256(b'').hexdigest(),
                      'untracked': [], 'snapshot_sha256': hashlib.sha256(f'SIMULATED {index}'.encode()).hexdigest()}
            source_root = root / f'source-{index}'
            self.objects[(str(source_root), revision)] = raw
            self.builds.append({'schema': targets.BUILD_SCHEMA, 'recipe': copy.deepcopy(recipe),
                'recipe_sha256': recipes.recipe_sha256(recipe), 'source_root': str(source_root),
                'source': source, 'toolchain_image': TOOLCHAIN, 'runtime_image': RUNTIME,
                'instrumentation': 'debug', 'cflags': '-O0 -g', 'configure_flags': [],
                'build_recipe': 'bird-local/v1', 'network': 'none',
                'requirements': ['SIMULATED inert source; no toolchain is invoked.'],
                'limits': ['SIMULATED source/build declarations, not authentic execution.']})
            previous = revision

    def git(self, root, *arguments):
        args = tuple(map(str, arguments))
        self.calls.append({'root': str(root), 'arguments': list(args)})
        if len(args) == 3 and args[:2] == ('cat-file', 'commit'):
            raw = self.objects.get((str(root), args[2]))
            if raw is not None:
                return raw
        raise AssertionError('Bisection smoke refused an unmodelled source command')


class BisectionHost(SimulatedHost):
    def __init__(self, document):
        super().__init__(document)
        self.images = set()

    def command(self, argv, *, env=None, timeout=15):
        args = list(map(str, argv))
        if (len(args) == 6 and args[:5] == ['docker', '--host', 'unix:///var/run/docker.sock',
                                         'image', 'inspect'] and args[-1] in self.images):
            self.calls.append(args)
            return json.dumps([{'Id': args[-1], 'RepoDigests': [], 'Size': 123,
                                'Os': 'linux', 'Architecture': 'amd64'}])
        return super().command(args, env=env, timeout=timeout)


class SimulatedBisection:
    """Fake local-source builds and actual-shaped bounded worker witnesses."""
    def __init__(self, scenario, chain, host):
        self.scenario, self.chain, self.host = scenario, chain, host
        self.builds, self.attempts = [], []
        self.indices = {build['source']['commit']: i for i, build in enumerate(chain.builds)}
        self.runtime = ComparisonRuntime('known-difference')

    def build(self, document, *, output_dir, emit_disclosure, timeout):
        index = self.indices[document['source']['commit']]
        self.builds.append({'index': index, 'timeout': timeout, 'simulation': True})
        output_dir.mkdir(parents=True)
        emit_disclosure({'simulation': True, 'revision': document['source']['commit']})
        log = b'SIMULATED local source build; no compiler or image builder invoked.\n'
        (output_dir / 'build.log').write_bytes(log)
        if self.scenario == 'skipped' and index == 4:
            _write(output_dir / 'build-result.json', {'status': 'failed', 'simulation': True})
            raise recipes.ContractError('SIMULATED unbuildable revision')
        image = 'sha256:' + bisection.digest(document)
        built = {'recipe': document['build_recipe'], 'toolchain_image': TOOLCHAIN,
                 'runtime_image': RUNTIME, 'toolchain_image_id': TOOLCHAIN, 'runtime_image_id': RUNTIME,
                 'compiler_flags': document['cflags'], 'linker_flags': document['cflags'],
                 'configure_flags': document['configure_flags'],
                 'dockerfile_sha256': hashlib.sha256(targets._dockerfile(TOOLCHAIN, RUNTIME, document).encode()).hexdigest(),
                 'source_snapshot_sha256': document['source']['snapshot_sha256'],
                 'build_log_sha256': hashlib.sha256(log).hexdigest(), 'image_id': image,
                 'binary_sha256': None, 'reconstructible': False}
        target = {'schema': targets.TARGET_SCHEMA, 'recipe_sha256': document['recipe_sha256'],
                  'adapter': 'bird', 'image': image, 'label': 'SIMULATED revision ' + str(index),
                  'provenance': {'kind': 'local_source', 'source': document['source'], 'build': built,
                                 'instrumentation': document['instrumentation'], 'limits': document['limits']}}
        targets.validate_target(target, document['recipe'])
        _write(output_dir / 'target.json', target)
        self.host.images.add(image)
        return target

    def execute(self, document, workdir, attempt_id, timeout):
        target = recipes.read_document(workdir / 'target.json')
        index = self.indices[target['provenance']['source']['commit']]
        repeated = any(x['index'] == index for x in self.attempts)
        bad = index >= 4
        if self.scenario == 'unstable' and repeated:
            bad = not bad
        ambiguous = self.scenario == 'ambiguous' and index == 4
        outcome = self.runtime.execute(document, workdir, attempt_id, timeout)
        status = 'harness_failed' if ambiguous else 'experiment_failed' if bad else 'completed'
        outcome.update(status=status, reason='SIMULATED ' + status + '; no daemon or benchmark ran.')
        (workdir / 'runtime.json').write_text(json.dumps(outcome))
        events = recipes.read_document(workdir / 'raw-events.json')
        if bad:
            events['events'][-1]['counters']['accepted_prefixes'] -= 1
        (workdir / 'raw-events.json').write_text(json.dumps(events))
        budget = recipes.read_document(workdir / 'execution-budget.json')
        budget.update(started_monotonic_s=1, ended_monotonic_s=1 + budget['elapsed_seconds'])
        (workdir / 'execution-budget.json').write_text(json.dumps(budget))
        samples = [{'role': 'target', 'container_id': 'SIMULATED-target', 'monotonic_s': 2,
                    'bird_process_present': True, 'errors': []}]
        if bad:
            samples.append({'role': 'target', 'container_id': 'SIMULATED-target', 'monotonic_s': 11,
                            'bird_process_present': False, 'daemon_exit_code': 139, 'errors': []})
        _write(workdir / 'live-diagnostics.json', {'simulation': True, 'samples': samples})
        self.attempts.append({'index': index, 'source_attempt_id': attempt_id, 'status': status,
                              'timeout': timeout, 'simulation': True})
        return outcome


def _run_smoke(output):
    import recipe_run
    output = bisection.safe(output)
    if output == ROOT or ROOT in output.parents:
        raise ValueError('Choose an output directory outside the engine checkout')
    output.mkdir(mode=0o700)
    (output / 'SIMULATION.txt').write_text(
        'All source revisions, builds, images, predicates and worker observations are SIMULATED.\n'
        'No real Git command, build, Docker, network, daemon or benchmark ran.\n'
        'No actual bug, fix, hardware qualification or performance conclusion is represented.\n')
    fixture = recipes.read_document(ROOT / 'examples/recipes/synthetic-ipv4.recipe.json')
    cases = {}
    for scenario in CASES:
        case = output / scenario
        case.mkdir(mode=0o700)
        predicate = 'target_crash' if scenario == 'target-crash' else 'assertions'
        recipe_path = case / 'recipe.json'
        recipe_command(['export', '--batch', ROOT / 'examples/recipes/synthetic-ipv4.yaml',
            '--test', fixture['selection']['test'], '--cell', fixture['selection']['cell_key'],
            '--engine-revision', fixture['engine']['revision'], '--target-image', 'sha256:' + '1' * 64,
            '--generator-image', 'sha256:' + '2' * 64, '--observer-image', 'sha256:' + '3' * 64,
            '--question', 'SIMULATED deterministic ' + scenario + '; no real source or runtime.',
            '--expected-outcome', 'target_crash' if predicate == 'target_crash' else 'experiment_completed',
            '--output', recipe_path])
        recipe = recipes.read_document(recipe_path)
        chain = SimulatedChain(case, recipe)
        host = BisectionHost(recipe)
        runtime = SimulatedBisection(scenario, chain, host)
        plan_path = case / 'plan.json'
        arguments = ['plan', '--recipe', recipe_path, '--predicate', predicate, '--max-trials', 32,
                     '--worker-timeout', 120, '--build-timeout', 60, '--output', plan_path]
        for index, build in enumerate(chain.builds):
            path = case / f'build-plan-{index}.json'
            _write(path, build)
            arguments += ['--build-plan', path]
        session = case / 'session'
        with ExitStack() as stack:
            host.patch(stack)
            stack.enter_context(patch.object(recipe_run, 'os', SimulatedOS(output / 'simulated-host.lock')))
            stack.enter_context(patch.object(targets, '_git', chain.git))
            stack.enter_context(patch.object(targets, 'build_target', runtime.build))
            stack.enter_context(patch.object(recipe_run, 'SubprocessBackend', lambda **kwargs: runtime))
            _command(arguments)
            _command(['init', plan_path, '--session', session])
            preview = _command(['run', session])
            if preview['phase'] != 'endpoint-good' or runtime.builds or runtime.attempts:
                raise RuntimeError('Planning without --execute started simulated runtime work')
            conclusion = _command(['run', session, '--execute'], expected=0 if scenario in ('assertions', 'target-crash') else 5)
            paused_report, pause = None, None
            if scenario == 'ambiguous':
                if conclusion['state'] != 'paused_ambiguous':
                    raise RuntimeError('Ambiguous trial did not pause')
                pause = {'outcome': conclusion, 'attempts_before_resume': len(runtime.attempts),
                         'explicit_resume': True}
                _command(['report', session, '--output', case / 'paused-report'])
                paused_report = str(case / 'paused-report/bisection.json')
                _command(['verify', paused_report])
                conclusion = _command(['run', session, '--execute'], expected=5)
            for destination in (case / 'report', case / 'report-rebuilt'):
                _command(['report', session, '--output', destination])
                _command(['verify', destination / 'bisection.json'])
        expected = 'confirmed' if scenario in ('assertions', 'target-crash') else 'unresolved'
        if conclusion['state'] != expected:
            raise RuntimeError(f'{scenario}: expected {expected}, observed {conclusion}')
        primary = recipes.read_document(case / 'report/bisection.json')
        if primary != recipes.read_document(case / 'report-rebuilt/bisection.json'):
            raise RuntimeError('Offline report reconstruction changed the conclusion or witnesses')
        if primary['performance'] != {'qualification': 'not_assessed', 'policy': 'disabled'}:
            raise RuntimeError('A simulated bisection enabled performance policy')
        cases[scenario] = {'predicate': predicate, 'conclusion': conclusion,
                          'report': str(case / 'report/bisection.json'),
                          'report_rebuilt': str(case / 'report-rebuilt/bisection.json'),
                          'paused_report': paused_report, 'pause': pause, 'builds': runtime.builds,
                          'attempts': runtime.attempts, 'probe_commands': host.calls,
                          'source_commands': chain.calls}
    summary = {'simulation': True, 'status': 'passed', 'cases': cases,
               'operations': ['export', 'plan', 'init', 'run', 'report', 'verify'],
               'scope': 'Controlled local fixtures only; no real source, build, daemon or performance verdict.'}
    _write(output / 'smoke.json', summary)
    return summary


def run_smoke(output):
    """Guard the entire walkthrough, including setup and report-only rebuilds."""
    with ExitStack() as stack:
        stack.enter_context(patch.object(subprocess, 'Popen', _forbidden))
        for name in ('__init__', 'connect', 'connect_ex', 'sendto'):
            stack.enter_context(patch.object(socket.socket, name, _forbidden))
        stack.enter_context(patch.object(socket, 'create_connection', _forbidden))
        return _run_smoke(output)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, help='new absolute directory outside the checkout')
    args = parser.parse_args(argv)
    try:
        summary = run_smoke(args.output)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f'bisection smoke: {exc}', file=sys.stderr)
        return 2
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
