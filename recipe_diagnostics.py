# Copyright (C) 2026 bgperf2 contributors. Apache-2.0.
"""Bounded, owned-attempt diagnostics; no Docker client is initialized on import."""
import json
import os
import re
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import time

import recipes
import recipe_preflight as preflight

SCHEMA = 'bgperf2/diagnostics/v1alpha1'
MAX_BYTES = 64 * 1024
MAX_CONTAINERS = 128
COLLECTION_SECONDS = 20
LIVE_SAMPLE_LIMIT = 128


def host_snapshot():
    """Read minimal host identity before execution, without Docker or subprocesses."""
    result = {'schema': 'bgperf2/host/v1alpha1', 'hostname': None, 'operating_system': None,
              'kernel_release': None, 'kernel_version': None, 'architecture': None,
              'python_version': list(sys.version_info[:3]),
              'python_implementation': sys.implementation.name,
              'cpu_count': None, 'cpu_affinity': None, 'cpu_model': None,
              'boot_id': None, 'unavailable': {},
              'scope': 'Read-only identity/capacity observations; not host qualification or performance comparability.'}
    try:
        identity = os.uname()
        result.update(hostname=identity.nodename, operating_system=identity.sysname,
                      kernel_release=identity.release, kernel_version=identity.version,
                      architecture=identity.machine)
    except (OSError, AttributeError) as exc:
        result['unavailable']['uname'] = f'{type(exc).__name__}: {exc}'
    try:
        result['cpu_count'] = os.cpu_count()
        if result['cpu_count'] is None:
            result['unavailable']['cpu_count'] = 'Logical CPU count unavailable.'
    except OSError as exc:
        result['unavailable']['cpu_count'] = str(exc)
    try:
        result['cpu_affinity'] = sorted(os.sched_getaffinity(0))
    except (OSError, AttributeError) as exc:
        result['unavailable']['cpu_affinity'] = f'{type(exc).__name__}: {exc}'
    try:
        with Path('/proc/cpuinfo').open() as source:
            text = source.read(64 * 1024)
        for line in text.splitlines():
            if ':' in line and line.split(':', 1)[0].strip() in ('model name', 'Hardware'):
                result['cpu_model'] = line.split(':', 1)[1].strip() or None
                break
        if result['cpu_model'] is None:
            result['unavailable']['cpu_model'] = 'No CPU model in the first 64 KiB of /proc/cpuinfo.'
    except OSError as exc:
        result['unavailable']['cpu_model'] = str(exc)
    try:
        with Path('/proc/sys/kernel/random/boot_id').open() as source:
            value = source.read(128).strip()
        if not re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', value):
            raise ValueError('Malformed boot ID; persistent machine identifiers are not consulted.')
        result['boot_id'] = value
    except (OSError, ValueError) as exc:
        result['unavailable']['boot_id'] = str(exc)
    return result


def write_json(path, document):
    # Local import keeps this standalone helper independent of controller imports.
    from recipe_run import _write
    _write(Path(path), document)


def stage(work, name, *, status='entered', reason=None):
    """Record lifecycle control stages separately from benchmark timestamps."""
    path = Path(work) / 'stages.json'
    try:
        document = recipes.read_document(path)
    except recipes.ContractError:
        document = {'schema': 'bgperf2/stages/v1alpha1', 'events': [],
                    'clock': 'controller monotonic seconds; not benchmark measurement boundaries',
                    'deadline': 'Worker stages share the selected worker timeout; parent diagnostics and cleanup use separate bounded probes.'}
    events = document['events']
    events.append({'stage': name, 'status': status, 'monotonic_s': time.monotonic(),
                   'reason': reason})
    document['current_stage'] = name
    write_json(path, document)


def role_for_name(name):
    if name.endswith('_bird_target'):
        return 'target'
    if name.endswith('_monitor'):
        return 'observer'
    return 'generator'


def bounded_probe(argv, *, env, timeout=3, max_bytes=MAX_BYTES):
    """Stop a read-only CLI client on deadline/output limit, retaining bounded bytes."""
    deadline = time.monotonic() + timeout
    output = bytearray()
    truncated = False
    process = subprocess.Popen(list(map(str, argv)), env=env, shell=False,
                               start_new_session=True, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT)
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise preflight.ProbeError('Diagnostic command deadline expired')
                for key, _ in selector.select(remaining):
                    block = os.read(key.fileobj.fileno(), 4096)
                    if not block:
                        selector.unregister(key.fileobj)
                        continue
                    space = max_bytes - len(output)
                    output.extend(block[:max(0, space)])
                    if len(block) > space:
                        truncated = True
                        break
                if truncated:
                    break
        if truncated:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        process.wait(timeout=max(0.01, deadline - time.monotonic()))
        if process.returncode and not truncated:
            raise preflight.ProbeError(f'Diagnostic command exited {process.returncode}: '
                                       + output.decode('utf-8', errors='replace')[-1000:])
        return {'text': output.decode('utf-8', errors='replace'),
                'truncated': truncated, 'captured_bytes': len(output)}
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            if process.poll() is None:
                process.wait(timeout=3)
        finally:
            process.stdout.close()


def read_memory(pid):
    """Read the container's actual cgroup v2; never invent a path from its ID."""
    from role_cpu import cgroup_dir_for_pid
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        raise ValueError('No live container PID for cgroup memory observation')
    root = Path(cgroup_dir_for_pid(pid))
    def number(name):
        text = (root / name).read_text().strip()
        value = int(text)
        if value < 0:
            raise ValueError('Negative cgroup memory value')
        return value
    result = {'ending_bytes': number('memory.current'), 'peak_bytes': None,
              'anon_bytes': None, 'file_backed_bytes': None}
    try:
        result['peak_bytes'] = number('memory.peak')
    except (OSError, ValueError):
        pass
    try:
        values = dict(line.split() for line in (root / 'memory.stat').read_text().splitlines())
        for key, field in (('anon', 'anon_bytes'), ('file', 'file_backed_bytes')):
            if key in values and int(values[key]) >= 0:
                result[field] = int(values[key])
    except (OSError, ValueError):
        pass
    return result


def memory_record(values=None, *, reason=None, sampled_peak_bytes=None):
    values = values or {}
    return {'units': 'bytes', 'accounting': 'whole container cgroup v2 memory, including file-backed/cache costs',
            'peak_bytes': values.get('peak_bytes'), 'ending_bytes': values.get('ending_bytes'),
            'peak_definition': 'kernel memory.peak over container lifetime, including setup; unavailable stays null',
            'ending_definition': 'memory.current at the final pre-cleanup collection observation',
            'sampled_peak_bytes': sampled_peak_bytes,
            'sampled_peak_definition': 'maximum observed live memory usage; unsampled extremes are unknown',
            'anon_bytes': values.get('anon_bytes'), 'file_backed_bytes': values.get('file_backed_bytes'),
            'daemon_process_rss_bytes': None,
            'daemon_process_reason': 'Per-daemon RSS is not measured; container memory is not process RSS.',
            'reason': reason}


def read_bird_exit(work, relative):
    """Read only the fixed, bounded regular-file BIRD exit witness."""
    from recipe_results import _regular_file
    try:
        with _regular_file(Path(work), relative) as source:
            data = source.read(4097)
        if len(data) > 4096:
            return None
        value = json.loads(data, object_pairs_hook=recipes._pairs)
        recipes._keys(value, ('exit_code',), where='BIRD exit witness')
        code = value['exit_code']
        return code if isinstance(code, int) and not isinstance(code, bool) and 0 <= code <= 255 else None
    except (OSError, ValueError):
        return None


def live_sample(client, owned, previous, *, expected, exit_reader=None):
    """One optional diagnostic pass; an absent process attests only after presence."""
    samples = previous.setdefault('samples', [])
    seen = previous.setdefault('bird_seen', [])
    failure = None
    for identifier, name in list(owned.started.items())[:MAX_CONTAINERS]:
        sample = {'container_id': identifier, 'name': name, 'role': role_for_name(name),
                  'monotonic_s': time.monotonic(), 'memory_bytes': None,
                  'bird_process_present': None, 'errors': []}
        try:
            stats = client.stats(identifier, stream=False)
            usage = stats.get('memory_stats', {}).get('usage')
            if isinstance(usage, int) and not isinstance(usage, bool) and usage >= 0:
                sample['memory_bytes'] = usage
                peaks = previous.setdefault('sampled_peak_bytes', {})
                peaks[sample['role']] = max(usage, peaks.get(sample['role'], 0))
        except Exception as exc:
            sample['errors'].append('memory: ' + type(exc).__name__)
        if sample['role'] == 'target':
            try:
                processes = client.top(identifier, ps_args='-eo pid,comm')
                titles, rows = processes.get('Titles', []), processes.get('Processes', [])
                index = next(i for i, title in enumerate(titles) if title.upper() in ('COMMAND', 'CMD', 'COMM'))
                present = any(len(row) > index and row[index].rsplit('/', 1)[-1] == 'bird' for row in rows)
                sample['bird_process_present'] = present
                if present and identifier not in seen:
                    seen.append(identifier)
                elif not present:
                    code = exit_reader() if exit_reader is not None else None
                    sample['daemon_exit_code'] = code
                    witnessed = isinstance(code, int) and not isinstance(code, bool) and 0 <= code <= 255
                    if identifier not in seen and not witnessed:
                        samples.append(sample)
                        continue
                    decided = witnessed and identifier in seen
                    failure = {'status': 'experiment_failed',
                               'reason': ('Previously observed BIRD daemon disappeared while its container remained available.' if identifier in seen else
                                          'BIRD startup command ended before a running daemon was observed; inspect its exit status and log.'),
                               'reproduction': {'outcome': ('reproduced' if expected == 'target_crash' and code != 0 else 'not_reproduced') if decided else 'inconclusive',
                                                'reason': ('BIRD exit status was captured by the fixed startup wrapper; no core or signal attribution.' if decided else
                                                           'BIRD disappeared, but no exit status attests abnormal termination.'),
                                                'evidence': ['work/live-diagnostics.json']}}
            except Exception as exc:
                sample['errors'].append('bird_process: ' + type(exc).__name__)
        samples.append(sample)
    if len(samples) > LIVE_SAMPLE_LIMIT:
        removed = len(samples) - LIVE_SAMPLE_LIMIT
        previous['dropped_samples'] = previous.get('dropped_samples', 0) + removed
        del samples[:removed]
    previous['schema'] = SCHEMA
    previous['instrumentation'] = 'optional Docker stats and fixed BIRD process-list probes; observation overhead is uncalibrated'
    return failure


def collect_diagnostics(work, attempt, env, *, mode='basic', command=None, memory_reader=None):
    """Collect before owned cleanup. Exclude environment, mounts, journals and cores."""
    work = Path(work)
    command = command or bounded_probe
    memory_reader = memory_reader or read_memory
    report = {'schema': SCHEMA, 'mode': mode, 'status': 'collected', 'containers': [],
              'errors': [], 'missing': [], 'memory': {'target': memory_record(reason='No target memory observation.')},
              'instrumentation': 'diagnostic probes have uncalibrated overhead; performance comparison not assessed',
              'capabilities': {'container_state': True, 'bounded_container_logs': True,
                               'cgroup_v2_memory': 'if readable',
                               'bird_process_presence': 'absence attests only after observed presence',
                               'bird_daemon_exit': 'fixed startup wrapper records status after BIRD exits',
                               'daemon_process_rss': False, 'privileged_cores': False},
              'privileged_artifacts': {'cores': 'not_requested', 'kernel_journal': 'not_requested'}}
    if mode == 'none':
        report.update(status='disabled', missing=['Optional runtime diagnostics were explicitly disabled.'])
        write_json(work / 'diagnostics.json', report)
        return report
    deadline = time.monotonic() + COLLECTION_SECONDS
    prefix = ['docker', '--host', env.get('DOCKER_HOST', 'unix:///var/run/docker.sock')]
    def probe(args):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise preflight.ProbeError('Overall diagnostic collection budget expired')
        result = command(prefix + args, env=env, timeout=min(3, remaining), max_bytes=MAX_BYTES)
        if result.get('truncated') and 'logs' not in args:
            raise preflight.ProbeError('Structured diagnostic output exceeded its byte budget')
        return result
    try:
        listed = probe(['ps', '-aq', '--no-trunc', '--filter', f'label=bgperf2.recipe.attempt={attempt}'])
        identifiers = listed['text'].split()
        if len(identifiers) > MAX_CONTAINERS:
            report['errors'].append('Owned-container count exceeded diagnostic limit; extra entries uncollected.')
        for identifier in identifiers[:MAX_CONTAINERS]:
            try:
                if not re.fullmatch(r'[0-9a-f]{64}', identifier):
                    raise ValueError('Malformed full container ID; no path or command constructed')
                inspected = json.loads(probe(['container', 'inspect', identifier])['text'])[0]
                labels = inspected.get('Config', {}).get('Labels') or {}
                if labels.get('bgperf2.recipe.attempt') != attempt or inspected.get('Id') != identifier:
                    raise ValueError('Diagnostic ownership/ID recheck failed; foreign resource retained')
                name = inspected.get('Name', '').lstrip('/')
                state = inspected.get('State', {})
                filtered = {key: state.get(key) for key in ('Status', 'Running', 'ExitCode', 'OOMKilled', 'Error', 'StartedAt', 'FinishedAt')}
                item = {'id': identifier, 'name': name, 'role': role_for_name(name),
                        'image_id': inspected.get('Image'), 'state': filtered,
                        'memory': memory_record(reason='Container cgroup unavailable.'), 'log': None}
                try:
                    item['memory'] = memory_record(memory_reader(state.get('Pid')))
                except (OSError, ValueError) as exc:
                    item['memory']['reason'] = str(exc)
                try:
                    log = probe(['logs', '--tail', '200', '--timestamps', identifier])
                    relative = 'diagnostic-logs/' + identifier + '.log'
                    path = work / relative
                    path.parent.mkdir(exist_ok=True)
                    path.write_text(log['text'])
                    item['log'] = {'path': relative, 'truncated': log['truncated'],
                                   'captured_bytes': log['captured_bytes'], 'requested_tail_lines': 200}
                except (OSError, ValueError, preflight.ProbeError) as exc:
                    report['errors'].append(f'{identifier}: log collection failed: {exc}')
                report['containers'].append(item)
            except (OSError, ValueError, IndexError, KeyError, TypeError, preflight.ProbeError) as exc:
                report['errors'].append(f'{identifier}: {exc}')
    except (OSError, ValueError, preflight.ProbeError) as exc:
        report['errors'].append(str(exc))
    if not report['containers']:
        report['missing'].append('No owned containers were available before cleanup; runtime may not have reached creation.')
    for item in report['containers']:
        if item['role'] == 'target':
            report['memory']['target'] = item['memory']
    live_path = work / 'live-diagnostics.json'
    if live_path.is_file():
        try:
            live = recipes.read_document(live_path)
            peaks = [sample['memory_bytes'] for sample in live.get('samples', [])
                     if sample.get('role') == 'target' and isinstance(sample.get('memory_bytes'), int)]
            peak = live.get('sampled_peak_bytes', {}).get('target')
            if isinstance(peak, int) and not isinstance(peak, bool) and peak >= 0:
                report['memory']['target']['sampled_peak_bytes'] = peak
            elif peaks:
                report['memory']['target']['sampled_peak_bytes'] = max(peaks)
            report['live_samples_retained'] = len(live.get('samples', []))
            report['live_samples_dropped'] = live.get('dropped_samples', 0)
        except (recipes.ContractError, ValueError, TypeError) as exc:
            report['errors'].append('Live diagnostic artifact unreadable: ' + str(exc))
    if report['errors']:
        report['status'] = 'partial'
    write_json(work / 'diagnostics.json', report)
    return report
