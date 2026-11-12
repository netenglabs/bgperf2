# Copyright (C) 2026 bgperf2 contributors. Apache-2.0.
"""Separate, bounded synthetic Maghemite receive-loading observation.

No observer convergence row or assertion success is produced by this contract.
"""
import hashlib
import json
import os
from pathlib import Path
from queue import Empty
import time

import recipes
import recipe_receive as receive

SCHEMA = 'bgperf2/maghemite-receive-loading/v1alpha1'
MAX_PREFIXES = 4096
MAX_BYTES = 2 * 1024 * 1024
LOADING_SECONDS = 120
MAX_SNAPSHOTS = 8
SNAPSHOT_GAP_SECONDS = 1


def validate_selection(recipe, enabled, diagnostics='basic'):
    if type(enabled) is not bool:
        raise recipes.ContractError('maghemite_loading must be boolean')
    if not enabled:
        return
    from recipe_mrt import selected
    resolved = recipe['resolved']
    if (selected(recipe) or recipe['roles']['target']['adapter'] != 'maghemite'
            or diagnostics != 'basic' or not 1 <= resolved['neighbors'] <= 2
            or not 1 <= resolved['neighbors'] * resolved['prefixes_per_peer'] <= MAX_PREFIXES
            or resolved.get('filter') not in (None, 'None')):
        raise recipes.ContractError('Receive loading requires basic diagnostics, unfiltered synthetic '
                                   'Maghemite, at most two peers and 4096 total prefixes')


def generator_witness(recorders, errors, expected):
    """Complete source-bound fleet only; missing/retired recorders cannot attest."""
    if errors or not recorders or not all(r.complete for r in recorders.values()):
        raise ValueError('Generator fleet completion unavailable')
    events = [e.to_dict() for r in recorders.values() for e in r.events]
    complete = [e for e in events if e['event'] == 'tester_complete']
    # Synthetic recipe currently has one BIRD container driving every peer.
    wanted = {'sessions': len(expected['peers']), 'sessions_measured': len(expected['peers']),
              'configured_prefixes': sum(len(p['prefixes']) for p in expected['peers']),
              'expected_prefixes': sum(len(p['prefixes']) for p in expected['peers']),
              'offered_prefixes': sum(len(p['prefixes']) for p in expected['peers'])}
    if (len(recorders) != 1 or len(complete) != 1
            or any(type(complete[0]['counters'].get(k)) is not int
                   or complete[0]['counters'][k] != v for k, v in wanted.items())):
        raise ValueError('Source-bound generator session/offering totals disagree')
    return events, complete[0]


def observe(expected, release, completion, query, *, deadline, clock=time.monotonic,
            sleep=time.sleep):
    """Retain every read; two consecutive exact imported reads qualify readiness.

    Query errors are terminal/unmeasured; inexact reads are retained, bounded
    observations rather than replacement originals. Selected RIB is secondary.
    """
    receipt = {'schema': SCHEMA, 'status': 'unmeasured', 'primary_oracle': 'imported',
               'release': release, 'generator_completion': completion, 'queries': [],
               'errors': [], 'timing': None, 'first_prefix_visibility': None,
               'limits': {'loading_seconds': LOADING_SECONDS, 'max_snapshots': MAX_SNAPSHOTS,
                          'max_response_bytes': MAX_BYTES, 'minimum_snapshot_gap_s': SNAPSHOT_GAP_SECONDS},
               'scope': 'Observed API table readiness, including polling and serialization; '
                        'no transit convergence or continuous/atomic RIB claim.'}
    exact = []
    try:
        if not release['monotonic_s'] <= completion['monotonic_s'] <= clock() <= deadline:
            raise ValueError('Completion/release clock ordering invalid or deadline exceeded')
        neighbors = query('neighbors', '/bgp/status/neighbors?asn=' + str(expected['target_asn']))
        receipt['queries'].append(neighbors)
        data = json.loads(neighbors['body'], object_pairs_hook=recipes._pairs, parse_constant=recipes._nonfinite)
        if not isinstance(data, dict):
            raise ValueError('Unsupported neighbor response')
        for p in expected['peers']:
            entry = data.get(p['address'], {})
            if (entry.get('fsm_state') != 'Established' or entry.get('asn') != p['asn']
                    or entry.get('remote_ip') != p['address']):
                raise ValueError('Selected peer not witnessed Established')
        for i in range(MAX_SNAPSHOTS):
            if i:
                if clock() + SNAPSHOT_GAP_SECONDS >= deadline:
                    raise ValueError('No budget for next imported snapshot')
                sleep(SNAPSHOT_GAP_SECONDS)
            if clock() >= deadline:
                raise ValueError('Loading deadline exceeded')
            record = query(f'imported-{i + 1}', '/rib/status/imported?address_family=Ipv4&protocol=Bgp')
            receipt['queries'].append(record)
            record['identity'] = receive.parse_rib(record['body'], expected,
                                                  max_bytes=MAX_BYTES, max_prefixes=MAX_PREFIXES)
            if record['completed_monotonic_s'] > deadline:
                raise ValueError('Snapshot completed beyond loading deadline')
            if record['identity']['exact']:
                exact.append(record)
            else:
                exact.clear()
            if len(exact) == 2:
                receipt['status'] = 'passed'
                receipt['timing'] = {
                    'release_to_generator_completion_s': completion['monotonic_s'] - release['monotonic_s'],
                    'release_to_first_exact_snapshot_s': exact[0]['completed_monotonic_s'] - release['monotonic_s'],
                    'release_to_confirmation_s': exact[1]['completed_monotonic_s'] - release['monotonic_s'],
                    'generator_resolution': completion.get('details', {}),
                    'snapshot_intervals': [{k: q[k] for k in ('started_monotonic_s', 'completed_monotonic_s')}
                                           for q in exact]}
                break
        if receipt['status'] != 'passed':
            receipt['status'] = 'failed'
    except (OSError, ValueError, KeyError, TypeError, RecursionError) as exc:
        receipt['errors'].append(str(exc))
        receipt['status'], receipt['timing'] = 'unmeasured', None
    # Raw bytes live in separate hashed artifacts, never duplicate huge bodies.
    for record in receipt['queries']:
        record.pop('body', None)
    return receipt


def execute_loading(work, attempt, document, runtime, *, target, testers, queue,
                    recorders, errors, release):
    """Reuse owned setup/samplers and bounded CLI collection, before cleanup."""
    from recipe_diagnostics import bounded_probe, collect_native, write_json
    validate_selection(document, True)
    work = Path(work)
    expected = recipes.read_document(work / 'receive-expectation.json')
    deadline = release['monotonic_s'] + LOADING_SECONDS
    receipt = {'schema': SCHEMA, 'status': 'unmeasured', 'release': release,
               'errors': [], 'timing': None}
    try:
        if (expected['recipe_sha256'] != recipes.recipe_sha256(document)
                or expected['phase'] != 'before_replay'):
            raise ValueError('Receive source binding invalid')
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ValueError('Generator completion deadline exceeded')
            try:
                info = queue.get(timeout=min(remaining, 0.5))
            except Empty:
                continue
            if 'tester_offering' in info:
                runtime.observe_tester_sample(info, recorders, errors)
                write_json(work / 'receive-generator-events.json', {
                    'events': [e.to_dict() for r in recorders.values() for e in r.events],
                    'observation_errors': dict(errors)})
            if errors:
                raise ValueError('Generator recorder rejected observation: ' + str(errors))
            if runtime.tester_offering_complete(recorders, errors) is True:
                break
        events, completion = generator_witness(recorders, errors, expected)
        write_json(work / 'receive-generator-events.json', {'events': events})
        log_dirs = [t.host_dir for t in testers]
        health = {'errors': runtime.BIRDTester.find_errors(log_dirs),
                  'timeouts': runtime.BIRDTester.find_timeouts(log_dirs)}
        write_json(work / 'receive-generator-health.json', health)
        if health != {'errors': 0, 'timeouts': 0}:
            raise ValueError('Generator errors/timeouts not zero')
        inspection = runtime.dckr.inspect_container(target.name)
        item = {'id': inspection['Id'], 'name': target.name, 'image_id': inspection['Image']}
        capture_errors, records = [], []
        def probe(argv, raw=False):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ValueError('Receive collection deadline exceeded')
            return bounded_probe(['docker', '--host', os.environ.get('DOCKER_HOST', 'unix:///var/run/docker.sock'), *argv],
                                 env=os.environ.copy(), timeout=min(3, remaining),
                                 max_bytes=MAX_BYTES, allow_nonzero=raw)
        def query(name, path):
            argv = ('/usr/local/bin/bgperf-mg-http', '--fail', '--silent', '--show-error',
                    '--max-time', '2', '--max-filesize', '8388608', '-H',
                    'api-version: ' + receive.API_VERSION, '--write-out',
                    receive.HTTP_MARKER.decode() + '%{http_code}', 'http://127.0.0.1:4676' + path)
            collect_native(work, attempt, item, probe, capture_errors, commands=((name, argv),),
                           scope='receive-loading observation', http_receipts=True)
            record = item['native']['queries'][0]
            records.append(record)
            if record['status'] != 'captured' or record.get('truncated') or record.get('exit_code') != 0:
                raise ValueError('Receive HTTP request unavailable: ' + name)
            from recipe_results import _regular_file
            with _regular_file(work, record['path']) as stream:
                data = stream.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES or hashlib.sha256(data).hexdigest() != record['sha256']:
                raise ValueError('Receive HTTP capture size/hash mismatch')
            body, marker, status = data.rpartition(receive.HTTP_MARKER)
            if not marker or status != b'200':
                raise ValueError('Receive HTTP status unavailable or unsuccessful')
            return {'name': name, 'path': record['path'], 'body': body,
                    'started_monotonic_s': record['request_started_ns'] / 1e9,
                    'completed_monotonic_s': record['request_completed_ns'] / 1e9}
        receipt = observe(expected, release, completion, query, deadline=deadline)
        receipt.update(api_version=receive.API_VERSION, captures=records, capture_errors=capture_errors,
                       expectation_sha256=hashlib.sha256((work / 'receive-expectation.json').read_bytes()).hexdigest())
    except (OSError, ValueError, KeyError, TypeError, RecursionError) as exc:
        receipt['errors'].append(str(exc))
    finally:
        write_json(work / 'maghemite-loading.json', receipt)
