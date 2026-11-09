# Copyright (C) 2026 bgperf2 contributors. Apache-2.0.
"""Bounded encoded MRT peer facts, not expected BGP export or prefix identity."""
import hashlib
import ipaddress
import os
from pathlib import Path
import re
import stat
import struct
import time

SCHEMA = 'bgperf2/mrt-inventory/v1alpha1'
MAX_RECORD_BYTES = 16 * 1024**2
MAX_INPUT_BYTES = 16 * 1024**3
MAX_PEERS = 4096


class Cursor:
    def __init__(self, payload):
        self.payload, self.offset = memoryview(payload), 0

    def take(self, count):
        end = self.offset + count
        if end > len(self.payload):
            raise ValueError('Truncated MRT record body')
        value = self.payload[self.offset:end]
        self.offset = end
        return value

    def number(self, width):
        return int.from_bytes(self.take(width), 'big')

    def end(self):
        if self.offset != len(self.payload):
            raise ValueError('Trailing bytes in MRT record body')


def peer_table(payload):
    data = Cursor(payload)
    collector = str(ipaddress.IPv4Address(bytes(data.take(4))))
    view = bytes(data.take(data.number(2))).decode('utf-8')
    count = data.number(2)
    if not 0 < count <= MAX_PEERS:
        raise ValueError('Unsupported MRT peer count')
    peers = []
    for index in range(count):
        flags = data.number(1)
        if flags & ~3:
            raise ValueError('Unsupported MRT peer type flags')
        bgp_id = str(ipaddress.IPv4Address(bytes(data.take(4))))
        address = str(ipaddress.ip_address(bytes(data.take(16 if flags & 1 else 4))))
        asn = data.number(4 if flags & 2 else 2)
        peers.append(dict(index=index, bgp_id=bgp_id, address=address, asn=asn,
                          asn_bytes=4 if flags & 2 else 2,
                          ipv4_unicast_rib_entries=0, ipv6_unicast_rib_entries=0))
    data.end()
    return collector, view, peers


def rib_entries(payload, peers, subtype):
    data = Cursor(payload)
    data.number(4)  # Sequence is encoded evidence, not an ordering assumption.
    bits = data.number(1)
    if bits > (32 if subtype == 2 else 128):
        raise ValueError('Invalid MRT prefix length')
    data.take((bits + 7)//8)  # RFC 6396: unused trailing prefix bits are irrelevant.
    count = data.number(2)
    seen = set()
    for _ in range(count):
        index = data.number(2)
        if index >= len(peers) or index in seen:
            raise ValueError('Unknown or duplicate MRT peer index in RIB record')
        seen.add(index)
        data.number(4)  # Originated timestamp.
        data.take(data.number(2))  # Attributes are opaque in this inventory.
        key = 'ipv4_unicast_rib_entries' if subtype == 2 else 'ipv6_unicast_rib_entries'
        peers[index][key] += 1
    data.end()


def inventory(stream, *, expected_size, expected_sha256, timeout_seconds=1800,
              clock=time.monotonic, check=lambda: None):
    """Read/hash one complete TABLE_DUMP_V2 input with bounded record storage."""
    if type(expected_size) is not int or not 0 < expected_size <= MAX_INPUT_BYTES:
        raise ValueError('Expected MRT size must be a positive integer at most 16 GiB')
    if not isinstance(expected_sha256, str) or not re.fullmatch('[0-9a-f]{64}', expected_sha256):
        raise ValueError('Expected MRT SHA-256 must be 64 lowercase hex characters')
    if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 1800:
        raise ValueError('MRT inspection timeout must be 1–1800 seconds')
    started = clock()
    digest, consumed, records = hashlib.sha256(), 0, 0
    peers, collector, view = None, None, None
    families = {'ipv4_unicast': 0, 'ipv6_unicast': 0}

    def read(count):
        nonlocal consumed
        if clock() - started >= timeout_seconds:
            raise ValueError('MRT inspection deadline expired')
        check()
        # Regular-file reads and in-memory test streams return the requested
        # bytes or EOF. Short reads fail closed rather than silently resyncing.
        value = stream.read(count)
        if len(value) != count:
            raise ValueError('Truncated MRT input')
        consumed += count
        if consumed > expected_size:
            raise ValueError('MRT input exceeds expected size')
        digest.update(value)
        return value

    while consumed < expected_size:
        _, kind, subtype, length = struct.unpack('!IHHI', read(12))
        if not 0 < length <= MAX_RECORD_BYTES:
            raise ValueError('Unsupported MRT record length')
        if kind != 13 or subtype not in (1, 2, 4):
            raise ValueError(f'Unsupported MRT type/subtype: {kind}/{subtype}')
        payload = read(length)
        if subtype == 1:
            if records or peers is not None:
                raise ValueError('Exactly one initial MRT peer table is required')
            collector, view, peers = peer_table(payload)
        else:
            if peers is None:
                raise ValueError('MRT RIB precedes its peer table')
            rib_entries(payload, peers, subtype)
            families['ipv4_unicast' if subtype == 2 else 'ipv6_unicast'] += 1
        records += 1
    if stream.read(1):
        raise ValueError('MRT input exceeds expected size')
    if clock() - started >= timeout_seconds:
        raise ValueError('MRT inspection deadline expired')
    check()
    if digest.hexdigest() != expected_sha256:
        raise ValueError('MRT input SHA-256 mismatch')
    if peers is None or not sum(families.values()):
        raise ValueError('MRT input has no unicast RIB records')
    return dict(schema=SCHEMA, input=dict(bytes=consumed, sha256=digest.hexdigest()),
                collector_bgp_id=collector, view_name=view, peers=peers,
                record_count=records, rib_records=families,
                elapsed_seconds=clock()-started,
                limits=['RIB entry counts do not prove unique prefixes or expected exported routes.',
                        'Attributes are opaque; policy, AS paths and next hops are not validated.',
                        'Only one initial TABLE_DUMP_V2 peer table and IPv4/IPv6 unicast RIB subtypes are supported.',
                        'ADD-PATH, multicast, generic RIB and update streams are refused.'])


def inspect_file(path, **kwargs):
    path = Path(path)
    if not path.is_absolute() or path.resolve(strict=True) != path:
        raise ValueError('Canonical absolute MRT path without symlinks required')
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    before = os.fstat(descriptor)
    if not stat.S_ISREG(before.st_mode) or before.st_size != kwargs['expected_size']:
        os.close(descriptor)
        raise ValueError('Regular MRT file with the expected size required')
    with os.fdopen(descriptor, 'rb') as stream:
        value = inventory(stream, **kwargs)
        identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        if (identity(before) != identity(os.fstat(stream.fileno()))
                or identity(before) != identity(path.stat(follow_symlinks=False))):
            raise ValueError('MRT input changed during inspection')
    value['input']['path'] = str(path)
    return value
