# Copyright (C) 2026 bgperf2 contributors. Apache-2.0.
"""Private bounded-worker bridge to the existing bench lifecycle.

No alternative convergence or measurement rules live here. The parent owns the
wall-clock budget, worker process group, packaging and labelled Docker cleanup.
"""
import json
import os
from pathlib import Path
import sys
import types
import threading
import time

from recipe_run import OWNER_LABEL, _write
import recipes


class OwnedDocker:
    """Add ownership at resource creation, and refuse foreign removal."""
    def __init__(self, client, attempt, images):
        self.client, self.attempt, self.images = client, attempt, set(images)
        self.started = {}
        self.created = {}

    def __getattr__(self, name):
        if name in ('pull', 'build', 'import_image', 'tag', 'remove_image', 'prune_containers', 'prune_networks'):
            raise RuntimeError(f'Recipe worker forbids Docker {name}')
        return getattr(self.client, name)

    def create_container(self, **kwargs):
        if kwargs.get('image') not in self.images or not kwargs.get('name', '').startswith(self.attempt + '_'):
            raise RuntimeError('Recipe worker refused an unselected image or foreign container name')
        kwargs['labels'] = {OWNER_LABEL: self.attempt}
        result = self.client.create_container(**kwargs)
        self.created[result['Id']] = kwargs['name']
        return result

    def start(self, container, *args, **kwargs):
        result = self.client.start(container=container, *args, **kwargs)
        identifier = next((key for key, name in self.created.items() if key == container or name == container), None)
        if identifier is not None:
            self.started[identifier] = self.created[identifier]
        return result

    def create_network(self, name, **kwargs):
        if name != self.attempt + '-br':
            raise RuntimeError('Recipe worker refused a foreign network name')
        kwargs['labels'] = {OWNER_LABEL: self.attempt}
        return self.client.create_network(name, **kwargs)

    def remove_container(self, identifier, **kwargs):
        observed = self.client.inspect_container(identifier)
        if (observed.get('Config', {}).get('Labels') or {}).get(OWNER_LABEL) != self.attempt:
            raise RuntimeError('Recipe worker refuses to remove foreign container')
        return self.client.remove_container(observed['Id'], **kwargs)


def scoped_adapter(adapter, image, prefix):
    """Preserve adapter behavior, replacing only binary and runtime name."""
    class Selected(adapter):
        @classmethod
        def require_image(cls, *args, **kwargs):
            # Parent preflight checked exact references; creation uses only them.
            return image

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.image = image
            self.name = prefix + '_' + self.name
    return Selected


def execute(document, work, attempt, engine):
    resolved = document['resolved']
    roles = document['roles']
    parser = engine.create_args_parser()
    argv = ['-b', attempt, '-d', str(work), 'bench', '-t', 'bird',
            '-n', str(resolved['neighbors']), '-p', str(resolved['prefixes_per_peer']),
            '--image', roles['target']['image'], '--monitor', 'sink',
            '--results-dir', str(work / 'artifacts')]
    if resolved['target']['threads'] is not None:
        argv += ['--threads', str(resolved['target']['threads'])]
    args = parser.parse_args(argv)
    # Copy the runtime namespace; compatibility wrappers needing shared globals
    # are rebound below so every bench dependency receives this scoped object.
    runtime = types.SimpleNamespace(**vars(engine))
    runtime.TARGET_CLASSES = {'bird': scoped_adapter(engine.TARGET_CLASSES['bird'], roles['target']['image'], attempt)}
    runtime.MONITOR_CLASSES = {'sink': scoped_adapter(engine.MONITOR_CLASSES['sink'], roles['observer']['image'], attempt)}
    runtime.BIRDTester = scoped_adapter(engine.BIRDTester, roles['generator']['image'], attempt)
    runtime.target_image = lambda *args: roles['target']['image']
    runtime.remove_target_containers = lambda: None
    runtime.remove_old_containers = lambda: None
    runtime.get_ctn_names = lambda: []
    import run_lifecycle
    runtime.finish_bench = lambda *a, **kw: run_lifecycle.finish_bench(runtime, *a, **kw)
    runtime.abandon_run = lambda *a, **kw: run_lifecycle.abandon_run(runtime, *a, **kw)
    if engine.dckr.networks(names=[attempt + '-br']):
        raise RuntimeError('Attempt network already exists; refusing reuse')
    engine.capture_tool_revision()
    row = run_lifecycle.bench(runtime, args)
    # Successful process exit alone is never an experiment completion witness.
    if not row:
        return {'status': 'inconclusive', 'reason': 'Engine returned no stats row.'}
    header = [x.strip() for x in engine.stats_header().split(',')]
    if len(row) != len(header):
        raise RuntimeError('Engine stats row does not match its declared header')
    import csv
    with (work / 'stats.csv').open('x', newline='') as output:
        writer = csv.writer(output)
        writer.writerow(header)
        writer.writerow(row)
    failed = engine.row_failed(row)
    return {'status': 'experiment_failed' if failed else 'completed',
            'reason': 'Existing engine stats row marks experiment failed.' if failed else 'Existing engine returned a completed stats row.',
            'row': dict(zip(header, row))}


def health_outcome(name, state, expected):
    """Classify only observed stopped containers; missing state never attests."""
    if state.get('Running') is not False:
        return None
    is_target = name.endswith('_bird_target')
    is_observer = name.endswith('_monitor')
    failure = {'status': 'inconclusive' if is_observer else 'experiment_failed',
               'reason': f'Required role container {name} stopped.', 'container_state': state}
    code = state.get('ExitCode')
    if is_target and isinstance(code, int) and not isinstance(code, bool) and code != 0:
        failure['reproduction'] = {
            'outcome': 'reproduced' if expected == 'target_crash' else 'not_reproduced',
            'reason': 'Target container exited abnormally; container-level crash witness, not daemon-process diagnosis.',
            'evidence': ['work/runtime.json']}
    return failure


def scan_health(owned, expected):
    for identifier, name in list(owned.started.items()):
        try:
            state = owned.client.inspect_container(identifier)['State']
            outcome = health_outcome(name, state, expected)
            if outcome is not None:
                return outcome
        except Exception:
            # Unreadable health is not a crash witness. Outer budget remains.
            continue
    return None


def main(argv=None):
    work, attempt = (argv or sys.argv[1:])
    work = Path(work)
    outcome = {'status': 'harness_failed', 'reason': 'Worker failed before runtime initialization.'}
    try:
        document = recipes.read_document(work / 'recipe.json')
        recipes.validate_recipe(document)
        import docker
        host = os.environ.get('DOCKER_HOST', 'unix:///var/run/docker.sock')
        if not host.startswith('unix:///'):
            raise RuntimeError('Worker requires a local Unix Docker socket')
        client = docker.APIClient(base_url=host, version='auto', timeout=10)
        owned = OwnedDocker(client, attempt, [v['image'] for v in document['roles'].values()])
        settings = types.ModuleType('settings')
        settings.dckr = owned
        sys.modules['settings'] = settings
        import bgperf2 as engine
        def health_watch():
            while True:
                time.sleep(0.5)
                failure = scan_health(owned, document['reproduction']['expected_outcome'])
                if failure is not None:
                    _write(work / 'runtime.json', failure)
                    os._exit(0)
        threading.Thread(target=health_watch, daemon=True).start()
        outcome = execute(document, work, attempt, engine)
    except BaseException as exc:
        outcome = {'status': 'harness_failed', 'reason': f'{type(exc).__name__}: {exc}'}
    _write(work / 'runtime.json', outcome)
    # Pollers are daemon threads in the existing engine, but outstanding SDK
    # calls and sampler subprocesses are still terminated by the parent group.
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
