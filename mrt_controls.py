# Copyright (C) 2026 bgperf2 contributors. Apache-2.0.
"""Deterministic small protocol fixtures, with predeclared IPv4 export expectations."""
import hashlib
import ipaddress
import struct

from recipe_mrt import SPEC_SCHEMA

CASES = ('plain', 'export-scope', 'as-loops', 'as-set', 'long-paths')


def _attribute(code, payload, flags=0x40):
    return (bytes((flags | (16 if len(payload) > 255 else 0), code))
            + len(payload).to_bytes(2 if len(payload) > 255 else 1, 'big') + payload)


def _segment(kind, numbers):
    return bytes((kind, len(numbers))) + b''.join(n.to_bytes(4, 'big') for n in numbers)


def control(case, input_path, *, target_asn, observer_asn, source_asn):
    """Return bytes and a bound spec, never consulting any measured output.

    AS_SET rejection follows RFC 9774's default behavior. A mismatch is an
    observed protocol outcome, not permission to tune a target or the oracle.
    """
    if case not in CASES:
        raise ValueError('Unknown MRT protocol control')
    numbers = (target_asn, observer_asn, source_asn)
    if (any(type(n) is not int or not 1 <= n < 2**32 for n in numbers)
            or len(set(numbers)) != 3):
        raise ValueError('Three distinct nonzero four-byte role/source ASNs required')
    routes = [(None, (), True)]
    if case == 'plain':
        routes += [(None, (), True), (None, (), True)]
    elif case == 'export-scope':
        routes += [(None, (c,), False) for c in (0xffffff01, 0xffffff02, 0xffffff03)]
    elif case == 'as-loops':
        routes += [([_segment(2, [source_asn, n])], (), False)
                   for n in (target_asn, observer_asn)]
    elif case == 'as-set':
        routes += [([_segment(2, [source_asn]), _segment(1, [source_asn])], (), False)]
    elif case == 'long-paths':
        for length in (254, 255, 256, 257, 258, 260):
            path = [source_asn] * length
            routes.append(([_segment(2, path[i:i+255]) for i in range(0, length, 255)], (), True))
    def record(subtype, body):
        return struct.pack('!IHHI', 1, 13, subtype, len(body)) + body
    # RFC 6396: IPv4 address, four-byte ASN, and AS_PATH always four-byte.
    peer = (b'\xc0\x00\x02\x01' + b'\x00\x00' + b'\x00\x01' + b'\x02'
            + b'\xc0\x00\x02\x02' * 2 + source_asn.to_bytes(4, 'big'))
    data = bytearray(record(1, peer))
    expected = []
    for ordinal, (path, communities, accepted) in enumerate(routes):
        address = ipaddress.IPv4Address(int(ipaddress.IPv4Address('198.18.0.1')) + ordinal)
        attributes = (_attribute(1, b'\x00')
                      + _attribute(2, b''.join(path or [_segment(2, [source_asn])]))
                      + _attribute(3, b'\xc0\x00\x02\x02'))
        if communities:
            attributes += _attribute(8, b''.join(n.to_bytes(4, 'big') for n in communities), 0xc0)
        body = (ordinal.to_bytes(4, 'big') + b'\x20' + address.packed + b'\x00\x01'
                + b'\x00\x00' + (1).to_bytes(4, 'big')
                + len(attributes).to_bytes(2, 'big') + attributes)
        data.extend(record(2, body))
        if accepted:
            expected.append(str(address) + '/32')
    data = bytes(data)
    return data, dict(schema=SPEC_SCHEMA,
        input=dict(path=str(input_path), bytes=len(data), sha256=hashlib.sha256(data).hexdigest()),
        peers=[dict(index=0, asn=source_asn, prefixes=len(routes))],
        target_asn=target_asn, observer_asn=observer_asn,
        expected_prefixes=sorted(expected), expectation_description=(
            'Predeclared ' + case + ' control: ordinary routes transit; export-scope communities, '
            'role-AS loops and AS_SET (RFC 9774 default) do not. Long paths use legal '
            'AS_SEQUENCE segments of at most 255 ASNs. No attribute capture or timing claim.'))
