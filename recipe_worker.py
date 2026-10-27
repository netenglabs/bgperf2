# Copyright (C) 2026 bgperf2 contributors. Apache-2.0.
"""Private bounded-worker bridge to the existing bench lifecycle.

No alternative convergence or measurement rules live here. The parent owns the
wall-clock budget, worker process group, packaging and labelled Docker cleanup.
"""
import json
import csv
import os
from pathlib import Path
import sys
import types
import threading
import tempfile

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


def scoped_adapter(adapter, image, prefix, *, role=None, work=None, capture_exit=False):
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

        def wait_established(self, *args, **kwargs):
            if work is not None and role == 'observer':
                from recipe_diagnostics import stage
                stage(work, 'session_establishment')
            return super().wait_established(*args, **kwargs)

        def stats(self, *args, **kwargs):
            if work is not None and role == 'observer':
                from recipe_diagnostics import stage
                stage(work, 'observation')
            return super().stats(*args, **kwargs)

        def get_startup_cmd(self):
            command = super().get_startup_cmd()
            if not capture_exit or role != 'target':
                return command
            # BIRD's existing -d command stays in the foreground. Capture its
            # status only after it returns, without moving measurement clocks.
            return command + ("\nbgperf_bird_exit_status=$?\n"
                              "printf '{\"exit_code\":%s}\\n' \"$bgperf_bird_exit_status\" > "
                              + self.guest_dir + "/recipe-bird-exit.json\n"
                              "exit \"$bgperf_bird_exit_status\"\n")
    return Selected


def execute(document, work, attempt, engine, *, target=None):
    resolved = document['resolved']
    from recipe_targets import effective_roles
    from recipe_diagnostics import stage
    roles = effective_roles(document, target)
    options = recipes.read_document(work / 'diagnostic-options.json') if (work / 'diagnostic-options.json').is_file() else {'mode': 'none'}
    stage(work, 'setup')
    parser = engine.create_args_parser()
    argv = ['-b', attempt, '-d', str(work), 'bench', '-t', 'bird',
            '-n', str(resolved['neighbors']), '-p', str(resolved['prefixes_per_peer']),
            '--image', roles['target']['image'], '--monitor', 'sink',
            '--results-dir', str(work / 'artifacts')]
    if resolved['target']['threads'] is not None:
        argv += ['--threads', str(resolved['target']['threads'])]
    if 'pin' in resolved:
        argv += ['--pin', resolved['pin']]
    args = parser.parse_args(argv)
    # Copy the runtime namespace; compatibility wrappers needing shared globals
    # are rebound below so every bench dependency receives this scoped object.
    runtime = types.SimpleNamespace(**vars(engine))
    runtime.TARGET_CLASSES = {'bird': scoped_adapter(engine.TARGET_CLASSES['bird'], roles['target']['image'], attempt, role='target', work=work, capture_exit=options.get('mode') == 'basic')}
    runtime.MONITOR_CLASSES = {'sink': scoped_adapter(engine.MONITOR_CLASSES['sink'], roles['observer']['image'], attempt, role='observer', work=work)}
    runtime.BIRDTester = scoped_adapter(engine.BIRDTester, roles['generator']['image'], attempt, role='generator', work=work)
    runtime.target_image = lambda *args: roles['target']['image']
    runtime.remove_target_containers = lambda: None
    runtime.remove_old_containers = lambda: None
    runtime.get_ctn_names = lambda: []
    import run_lifecycle
    finishing = {}
    def snapshot_rows(filename, header, rows):
        descriptor, temporary = tempfile.mkstemp(prefix='.' + filename, dir=work)
        try:
            with os.fdopen(descriptor, 'w', newline='') as output:
                writer = csv.writer(output)
                writer.writerow(header)
                writer.writerows(rows)
            os.replace(temporary, work / filename)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    def snapshot_samples():
        if finishing:
            columns = ['elapsed_s', 'target_cpu_percent', 'target_memory_bytes',
                       'monitor_received', 'neighbors_checked',
                       'host_idle_percent', 'host_memory_free_bytes']
            snapshot_rows('raw-samples.csv', columns, finishing['samples'])
            _write(work / 'raw-samples.metadata.json', {
                'schema': 'bgperf2/retained-samples/v1alpha1', 'columns': columns,
                'row_count': len(finishing['samples']),
                'scope': 'Retained legacy bench_stats graph series after existing assurance-window slicing; not every raw observation.',
                'missing_observations': 'Discarded assurance samples and observations before a finish callback are not reconstructed.'})
    def finish(*args, **kwargs):
        # Only retain references here. The lifecycle sets bench_stop before any
        # snapshot I/O below, preserving its existing measurement boundary.
        finishing['samples'] = args[2]
        return run_lifecycle.finish_bench(runtime, *args, **kwargs)
    runtime.finish_bench = finish
    original_events = engine.write_event_artifact
    def write_events(*args, **kwargs):
        snapshot_samples()
        _write(work / 'raw-events.json', {'events': [event.to_dict() for event in args[1]],
                                         'source': 'existing lifecycle events before final collectors'})
        return original_events(*args, **kwargs)
    runtime.write_event_artifact = write_events
    original_provenance = engine.collect_provenance
    def provenance(*args, **kwargs):
        snapshot_samples()
        return original_provenance(*args, **kwargs)
    runtime.collect_provenance = provenance
    original_output = engine.create_output_stats
    def output_stats(*args, **kwargs):
        row = original_output(*args, **kwargs)
        snapshot_rows('partial-stats.csv', [value.strip() for value in engine.stats_header().split(',')], [row])
        return row
    runtime.create_output_stats = output_stats
    original_graphs = engine.create_bench_graphs
    def graphs(*args, **kwargs):
        snapshot_samples()
        return original_graphs(*args, **kwargs)
    runtime.create_bench_graphs = graphs
    runtime.abandon_run = lambda *a, **kw: run_lifecycle.abandon_run(runtime, *a, **kw)
    if engine.dckr.networks(names=[attempt + '-br']):
        raise RuntimeError('Attempt network already exists; refusing reuse')
    engine.capture_tool_revision()
    row = run_lifecycle.bench(runtime, args)
    stage(work, 'collection', reason='Existing lifecycle returned; preserve the stats row before final diagnostics.')
    # Successful process exit alone is never an experiment completion witness.
    if not row:
        return {'status': 'inconclusive', 'reason': 'Engine returned no stats row.'}
    header = [x.strip() for x in engine.stats_header().split(',')]
    if len(row) != len(header):
        raise RuntimeError('Engine stats row does not match its declared header')
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
    monitor_stop = threading.Event()
    terminal_lock = threading.Lock()
    monitor_failures = []
    finalized = False
    watcher = None
    try:
        document = recipes.read_document(work / 'recipe.json')
        recipes.validate_recipe(document)
        from recipe_targets import effective_roles
        target = recipes.read_document(work / 'target.json') if (work / 'target.json').is_file() else None
        roles = effective_roles(document, target)
        options = recipes.read_document(work / 'diagnostic-options.json') if (work / 'diagnostic-options.json').is_file() else {'mode': 'none'}
        if options.get('mode') not in ('none', 'basic'):
            raise ValueError('Unsupported diagnostic mode')
        import docker
        host = os.environ.get('DOCKER_HOST', 'unix:///var/run/docker.sock')
        if not host.startswith('unix:///'):
            raise RuntimeError('Worker requires a local Unix Docker socket')
        client = docker.APIClient(base_url=host, version='auto', timeout=10)
        owned = OwnedDocker(client, attempt, [v['image'] for v in roles.values()])
        settings = types.ModuleType('settings')
        settings.dckr = owned
        sys.modules['settings'] = settings
        import bgperf2 as engine
        diagnostic_client = docker.APIClient(base_url=host, version='auto', timeout=2) if options['mode'] == 'basic' else None
        from recipe_diagnostics import live_sample, read_bird_exit
        live = {'samples': [], 'bird_seen': []}
        def monitor_failure(failure):
            # One terminal writer at a time. A failure observed before stopping
            # the monitor wins over a concurrent successful bench return.
            with terminal_lock:
                if finalized:
                    return
                if not monitor_failures:
                    monitor_failures.append(failure)
                monitor_stop.set()
                try:
                    _write(work / 'runtime.json', monitor_failures[0])
                except Exception:
                    # No terminal witness is preferable to a false success.
                    os._exit(1)
                os._exit(0)
        def health_watch():
            try:
                while not monitor_stop.wait(0.5):
                    failure = scan_health(owned, document['reproduction']['expected_outcome'])
                    if monitor_stop.is_set():
                        return
                    if failure is None and diagnostic_client is not None:
                        failure = live_sample(diagnostic_client, owned, live,
                                              expected=document['reproduction']['expected_outcome'],
                                              exit_reader=lambda: read_bird_exit(work, attempt + '/bird/recipe-bird-exit.json'))
                        with terminal_lock:
                            if finalized:
                                return
                            try:
                                _write(work / 'live-diagnostics.json', live)
                            except Exception as exc:
                                # Record before releasing the writer lock: main
                                # may finish before the failure handoff runs.
                                failure = {'status': 'harness_failed',
                                           'reason': f'Worker health monitor failed: {type(exc).__name__}: {exc}'}
                                monitor_failures.append(failure)
                                monitor_stop.set()
                    if failure is not None:
                        monitor_failure(failure)
                        return
            except Exception as exc:
                monitor_failure({'status': 'harness_failed',
                                 'reason': f'Worker health monitor failed: {type(exc).__name__}: {exc}'})
        watcher = threading.Thread(target=health_watch, daemon=True)
        watcher.start()
        outcome = execute(document, work, attempt, engine, target=target)
    except BaseException as exc:
        outcome = {'status': 'harness_failed', 'reason': f'{type(exc).__name__}: {exc}'}
    finally:
        with terminal_lock:
            monitor_stop.set()
            if monitor_failures:
                outcome = monitor_failures[0]
            finalized = True
            _write(work / 'runtime.json', outcome)
        if watcher is not None:
            # Do not extend the worker for a healthy in-flight SDK read. Its
            # eventual return cannot publish after finalization, and the parent
            # still stops/reaps the worker process group on its existing budget.
            watcher.join(timeout=0)
    # Pollers are daemon threads in the existing engine, but outstanding SDK
    # calls and sampler subprocesses are still terminated by the parent group.
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
