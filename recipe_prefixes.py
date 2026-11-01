# Copyright (C) 2026 bgperf2 contributors. Apache-2.0.
"""Bounded, optional post-measurement IPv4 prefix evidence; no runtime imports."""
import ipaddress
import json
import os
from pathlib import Path
import socket
import time

import recipes

SCHEMA = 'bgperf2/observer-prefixes/v1alpha1'
CAPTURE_SCHEMA = 'bgperf2/observer-prefix-capture/v1alpha1'
MAX_PREFIXES = 100_000
MAX_BYTES = 4 * 1024 * 1024
CAPTURE_SECONDS = 3
SOCKET_NAME = 'prefixes.sock'


def expected_count(recipe):
    return recipe['resolved']['neighbors'] * recipe['resolved']['prefixes_per_peer']


def validate_selection(recipe, enabled):
    if type(enabled) is not bool:
        raise recipes.ContractError('observer_prefixes must be boolean')
    if enabled and expected_count(recipe) > MAX_PREFIXES:
        raise recipes.ContractError('Observer prefix capture supports at most 100000 expected prefixes')


def capture(path, recipe, *, clock=time.monotonic_ns):
    """One local request after measurement; timeout/partial evidence never attests."""
    start = clock()
    receipt = {'schema': CAPTURE_SCHEMA, 'recipe_sha256': recipes.recipe_sha256(recipe),
               'phase': 'post_measurement', 'requested_ns': start, 'completed_ns': None,
               'status': 'unavailable', 'snapshot': None, 'reason': None}
    deadline = time.monotonic() + CAPTURE_SECONDS
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(CAPTURE_SECONDS)
            # Linux is already a runner prerequisite. A directory descriptor
            # avoids sockaddr_un's short pathname limit for deep work roots
            # without chdir(), symlinks, alternate sockets or changing evidence.
            path = Path(path)
            directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                client.connect(f'/proc/self/fd/{directory}/{path.name}')
            finally:
                os.close(directory)
            chunks = bytearray()
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('Prefix snapshot deadline expired')
                client.settimeout(remaining)
                block = client.recv(min(65536, MAX_BYTES + 1 - len(chunks)))
                if not block:
                    break
                chunks.extend(block)
                if len(chunks) > MAX_BYTES:
                    raise ValueError('Prefix snapshot exceeds 4 MiB bound')
        value = json.loads(chunks, object_pairs_hook=recipes._pairs,
                           parse_constant=recipes._nonfinite)
        receipt.update(status='collected', snapshot=value)
    except (OSError, ValueError, RecursionError) as exc:
        receipt['reason'] = f'{type(exc).__name__}: {exc}'
    receipt['completed_ns'] = clock()
    return receipt


def inspect(receipt, recipe):
    """Return exact set differences only for complete, well-formed snapshots."""
    recipes._keys(receipt, ('schema', 'recipe_sha256', 'phase', 'requested_ns',
                           'completed_ns', 'status', 'snapshot', 'reason'), where='prefix capture')
    recipes._same(receipt['schema'], CAPTURE_SCHEMA, 'prefix capture schema')
    recipes._same(receipt['recipe_sha256'], recipes.recipe_sha256(recipe), 'prefix capture recipe')
    recipes._same(receipt['phase'], 'post_measurement', 'prefix capture phase')
    if receipt['status'] != 'collected' or receipt['reason'] is not None:
        raise ValueError('No complete prefix capture: ' + str(receipt['reason']))
    snap = receipt['snapshot']
    recipes._keys(snap, ('schema', 'status', 'monotonic_ns', 'connection_id', 'updates',
                        'accepted_count', 'prefixes', 'reason'), where='prefix snapshot')
    recipes._same(snap['schema'], SCHEMA, 'prefix snapshot schema')
    if snap['status'] != 'complete' or snap['reason'] is not None:
        raise ValueError('Sink prefix snapshot unavailable: ' + str(snap['reason']))
    for field, positive in (('monotonic_ns', True), ('connection_id', True),
                            ('updates', False), ('accepted_count', False)):
        value = snap[field]
        if type(value) is not int or value < int(positive):
            raise ValueError('Invalid prefix snapshot ' + field)
    start, end = receipt['requested_ns'], receipt['completed_ns']
    if (type(start) is not int or type(end) is not int or start <= 0
            or not start <= snap['monotonic_ns'] <= end
            or end - start > CAPTURE_SECONDS * 1_000_000_000):
        raise ValueError('Prefix snapshot is outside its bounded request interval')
    values = snap['prefixes']
    if (not isinstance(values, list) or len(values) > MAX_PREFIXES
            or snap['accepted_count'] != len(values) or expected_count(recipe) > MAX_PREFIXES):
        raise ValueError('Prefix snapshot count/capacity is inconsistent')
    observed = set()
    for value in values:
        if not isinstance(value, str) or len(value) > 18:
            raise ValueError('Invalid IPv4 prefix spelling')
        prefix = ipaddress.IPv4Network(value, strict=True)
        if str(prefix) != value or value in observed:
            raise ValueError('Noncanonical or duplicate IPv4 prefix')
        observed.add(value)
    origin = int(ipaddress.IPv4Address('100.0.0.0'))
    expected = {str(ipaddress.IPv4Address(origin + i)) + '/32'
                for i in range(expected_count(recipe))}
    missing, unexpected = expected - observed, observed - expected
    return {'expected_count': len(expected), 'observed_count': len(observed),
            'missing_count': len(missing), 'unexpected_count': len(unexpected),
            'missing_sample': sorted(missing)[:20], 'unexpected_sample': sorted(unexpected)[:20],
            'snapshot_monotonic_ns': snap['monotonic_ns'],
            'connection_id': snap['connection_id'], 'updates': snap['updates']}
