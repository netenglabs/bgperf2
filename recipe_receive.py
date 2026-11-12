# Copyright (C) 2026 bgperf2 contributors. Apache-2.0.
"""Opt-in small Maghemite post-worker API qualification, never transit timing."""
import hashlib
import ipaddress
import json
from pathlib import Path
import time

import recipes

SCHEMA = 'bgperf2/maghemite-receive-qualification/v1alpha1'
API_VERSION = '13.0.0'
MAX_PREFIXES = 16
MAX_BYTES = 64 * 1024
HTTP_MARKER = b'\nBGPERF_HTTP:'


def cgroup_sample(pid):
    """Whole target container, including its HTTP client; never daemon RSS."""
    from role_cpu import cgroup_dir_for_pid, parse_cpu_stat
    result = {'monotonic_ns': time.monotonic_ns(), 'usage_usec': None,
              'memory_current_bytes': None, 'memory_peak_bytes': None, 'reason': None}
    try:
        if type(pid) is not int or pid <= 0:
            raise ValueError('No live target PID')
        root = Path(cgroup_dir_for_pid(pid))
        result['usage_usec'] = parse_cpu_stat((root / 'cpu.stat').read_text())
        result['memory_current_bytes'] = int((root / 'memory.current').read_text())
        result['memory_peak_bytes'] = int((root / 'memory.peak').read_text())
        if result['usage_usec'] is None:
            raise ValueError('CPU usage unavailable')
    except (OSError, ValueError) as exc:
        result['reason'] = str(exc)
    return result


def validate_selection(recipe, enabled, diagnostics='basic'):
    if type(enabled) is not bool:
        raise recipes.ContractError('maghemite_receive must be boolean')
    if not enabled:
        return
    from recipe_mrt import selected
    resolved = recipe['resolved']
    if (selected(recipe) or recipe['roles']['target']['adapter'] != 'maghemite'
            or diagnostics != 'basic' or resolved['neighbors'] > 2
            or resolved['neighbors'] * resolved['prefixes_per_peer'] > MAX_PREFIXES):
        raise recipes.ContractError('Maghemite receive qualification requires basic diagnostics, '
                                   'synthetic IPv4, at most two peers and sixteen prefixes')


def expectation(recipe, scenario, *, loading=False):
    """Bind rendered generated source before release; never derive from target RIB."""
    if loading:
        from recipe_receive_loading import validate_selection as validate_loading
        validate_loading(recipe, True)
    else:
        validate_selection(recipe, True)
    peers = []
    union = set()
    for tester in scenario['testers']:
        for peer in tester['neighbors'].values():
            address = str(ipaddress.IPv4Address(peer['local-address']))
            prefixes = [str(ipaddress.IPv4Network(p, strict=True)) for p in peer['paths']]
            if (len(prefixes) != recipe['resolved']['prefixes_per_peer']
                    or len(set(prefixes)) != len(prefixes) or union.intersection(prefixes)):
                raise ValueError('Generated receive prefixes are not the declared disjoint sets')
            union.update(prefixes)
            peers.append({'address': address, 'asn': peer['as'], 'prefixes': sorted(prefixes)})
    if len(peers) != recipe['resolved']['neighbors'] or len({p['address'] for p in peers}) != len(peers):
        raise ValueError('Generated receive peer count/identity mismatch')
    return {'schema': SCHEMA, 'recipe_sha256': recipes.recipe_sha256(recipe),
            'target_asn': scenario['target']['as'], 'peers': peers,
            'phase': 'before_replay', 'monotonic_ns': time.monotonic_ns()}


def parse_rib(body, expected, *, max_bytes=MAX_BYTES, max_prefixes=MAX_PREFIXES):
    """Refuse partial/non-BGP snapshots; preserve union and per-peer differences."""
    if len(body) > max_bytes:
        raise ValueError('RIB body exceeds retained byte bound')
    value = json.loads(body.decode('utf-8'), object_pairs_hook=recipes._pairs,
                       parse_constant=recipes._nonfinite)
    if not isinstance(value, dict) or len(value) > max_prefixes:
        raise ValueError('Unsupported RIB object or prefix count')
    by_peer = {p['address']: set() for p in expected['peers']}
    for prefix, paths in value.items():
        if str(ipaddress.IPv4Network(prefix, strict=True)) != prefix:
            raise ValueError('Noncanonical IPv4 prefix')
        if not isinstance(paths, list) or not paths:
            raise ValueError('RIB prefix has no paths')
        seen = set()
        for path in paths:
            if not isinstance(path, dict) or not isinstance(path.get('bgp'), dict):
                raise ValueError('RIB path is not a BGP path')
            bgp = path['bgp']
            peer = bgp.get('peer')
            if not isinstance(peer, dict) or set(peer) != {'Ip'}:
                raise ValueError('Unsupported BGP peer identity')
            address = str(ipaddress.IPv4Address(peer['Ip']))
            if address not in by_peer or address in seen:
                raise ValueError('Unknown or duplicate BGP peer path')
            seen.add(address)
            for field in ('origin_as', 'id'):
                if type(bgp.get(field)) is not int or not 0 <= bgp[field] <= 2**32 - 1:
                    raise ValueError('Malformed BGP path ' + field)
            as_path = bgp.get('as_path')
            if (not isinstance(as_path, list) or not as_path
                    or any(type(a) is not int or not 1 <= a <= 2**32 - 1 for a in as_path)):
                raise ValueError('Malformed BGP AS path')
            selected = next(p for p in expected['peers'] if p['address'] == address)
            if as_path[0] != selected['asn']:
                raise ValueError('BGP first AS does not match source peer')
            ipaddress.IPv4Address(path['nexthop'])
            if path.get('shutdown') is not False or type(path.get('rib_priority')) is not int:
                raise ValueError('Unsupported BGP path state')
            by_peer[address].add(prefix)
    wanted = set().union(*(set(p['prefixes']) for p in expected['peers']))
    actual = set(value)
    peer_differences = {p['address']: {
        'missing': sorted(set(p['prefixes']) - by_peer[p['address']]),
        'unexpected': sorted(by_peer[p['address']] - set(p['prefixes']))}
        for p in expected['peers']}
    return {'prefix_count': len(actual), 'missing': sorted(wanted - actual),
            'unexpected': sorted(actual - wanted), 'peer_differences': peer_differences,
            'exact': actual == wanted and all(not d['missing'] and not d['unexpected']
                                             for d in peer_differences.values())}


def inspect_query(work, record, expected):
    from recipe_results import _regular_file
    if record['status'] != 'captured' or record.get('truncated') or record.get('exit_code') != 0:
        raise ValueError('No complete successful API capture')
    with _regular_file(Path(work), record['path']) as stream:
        data = stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES or hashlib.sha256(data).hexdigest() != record['sha256']:
        raise ValueError('API capture size/hash mismatch')
    body, marker, status = data.rpartition(HTTP_MARKER)
    if not marker or status != b'200':
        raise ValueError('API HTTP status missing or unsuccessful')
    result = {'http_status': 200, 'body_bytes': len(body),
              'body_sha256': hashlib.sha256(body).hexdigest()}
    if record['name'].startswith(('imported-', 'selected-')):
        result['identity'] = parse_rib(body, expected)
    else:
        neighbors = json.loads(body.decode('utf-8'), object_pairs_hook=recipes._pairs,
                               parse_constant=recipes._nonfinite)
        if not isinstance(neighbors, dict):
            raise ValueError('Unsupported neighbor response')
        for peer in expected['peers']:
            item = neighbors.get(peer['address'])
            if (not isinstance(item, dict) or item.get('fsm_state') != 'Established'
                    or item.get('asn') != peer['asn'] or item.get('remote_ip') != peer['address']):
                raise ValueError('Selected generator neighbor is not witnessed Established')
        result['selected_peers_established'] = len(expected['peers'])
    return result


def completion_witness(work, attempt, recipe):
    from recipe_results import _regular_file
    documents = {}
    for name in ('raw-events.json', 'runtime.json'):
        with _regular_file(Path(work), name) as stream:
            data = stream.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError('Oversized generator completion evidence')
        documents[name] = json.loads(data, object_pairs_hook=recipes._pairs)
    row = documents['runtime.json']['row']
    if any(type(row.get(k)) is not int or row[k] != 0 for k in ('tester errors', 'tester timeouts')):
        raise ValueError('Generator errors/timeouts are not witnessed zero')
    complete = [e for e in documents['raw-events.json']['events'] if e['event'] == 'tester_complete']
    if len(complete) != 1 or not complete[0]['producer'].startswith(attempt + '_bgperf_bird_tester'):
        raise ValueError('Selected synthetic BIRD completion witness unavailable')
    peers = recipe['resolved']['neighbors']
    count = peers * recipe['resolved']['prefixes_per_peer']
    wanted = {'sessions': peers, 'sessions_measured': peers,
              'configured_prefixes': count, 'expected_prefixes': count, 'offered_prefixes': count}
    counters = complete[0]['counters']
    if any(type(counters.get(k)) is not int or counters[k] != v for k, v in wanted.items()):
        raise ValueError('All selected generator sessions and offerings are not witnessed complete')
    return complete[0]


def collect(work, attempt, item, probe, errors, deadline):
    """Five bounded queries under the caller's shared owned-diagnostic budget."""
    from recipe_diagnostics import collect_native, write_json
    receipt = {'schema': SCHEMA, 'parser_version': 1, 'status': 'unmeasured',
               'api_version': API_VERSION, 'queries': [], 'errors': [],
               'scope': 'post-worker API identity qualification only; no receive or transit timing'}
    try:
        from recipe_results import _regular_file
        with _regular_file(Path(work), 'receive-expectation.json') as stream:
            data = stream.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError('Oversized receive expectation')
        expected = json.loads(data, object_pairs_hook=recipes._pairs)
        recipe = recipes.read_document(Path(work) / 'recipe.json')
        validate_selection(recipe, True)
        if (expected['schema'] != SCHEMA or expected['phase'] != 'before_replay'
                or expected['recipe_sha256'] != recipes.recipe_sha256(recipe)
                or type(expected['target_asn']) is not int
                or not 1 <= expected['target_asn'] <= 2**32 - 1):
            raise ValueError('Receive expectation binding invalid')
        receipt['expectation_sha256'] = hashlib.sha256(data).hexdigest()
        receipt['generator_completion'] = completion_witness(work, attempt, recipe)
        paths = [('neighbors', '/bgp/status/neighbors?asn=' + str(expected['target_asn']))]
        paths += [(f'{kind}-{i}', '/rib/status/' + kind + '?address_family=Ipv4&protocol=Bgp')
                  for i in (1, 2) for kind in ('imported', 'selected')]
        records = []
        for name, path in paths:
            if name == 'imported-2':
                if deadline - time.monotonic() < 1:
                    raise ValueError('No shared budget for second snapshot pair')
                time.sleep(1)
            argv = ('/usr/local/bin/bgperf-mg-http', '--fail', '--silent', '--show-error',
                    '--max-time', '2', '--max-filesize', '8388608', '-H',
                    'api-version: ' + API_VERSION, '--write-out', HTTP_MARKER.decode() + '%{http_code}',
                    'http://127.0.0.1:4676' + path)
            collect_native(work, attempt, item, probe, errors, commands=((name, argv),),
                           scope=receipt['scope'], http_receipts=True)
            record = item['native']['queries'][0]
            records.append(record)
            receipt['queries'].append(record)
            try:
                record['response'] = inspect_query(work, record, expected)
            except (OSError, ValueError, KeyError, TypeError, RecursionError) as exc:
                record['parse_error'] = str(exc)
                receipt['errors'].append(name + ': ' + str(exc))
        item['native']['queries'] = records
        if not receipt['errors']:
            for kind in ('imported', 'selected'):
                results = [q['response']['identity'] for q in records if q['name'].startswith(kind + '-')]
                receipt[kind + '_identity'] = 'passed' if len(results) == 2 and all(r['exact'] for r in results) else 'failed'
            receipt['primary_oracle'] = 'imported_identity'
            receipt['status'] = receipt['imported_identity']
    except (OSError, ValueError, KeyError, TypeError, RecursionError) as exc:
        receipt['errors'].append(str(exc))
    write_json(Path(work) / 'maghemite-receive.json', receipt)
    return receipt
