"""SIMULATED binary inputs; no network, Docker or measured MRT file."""
import hashlib
import importlib.util
import io
import ipaddress
import json
import os
from pathlib import Path
import struct

import pytest

import mrt_inventory as mrt


def record(subtype, payload, kind=13):
    return struct.pack('!IHHI', 123, kind, subtype, len(payload)) + payload


def peer(flags, address, asn):
    return (bytes([flags]) + ipaddress.IPv4Address('192.0.2.1').packed
            + ipaddress.ip_address(address).packed + asn.to_bytes(4 if flags & 2 else 2, 'big'))


def table():
    return record(1, ipaddress.IPv4Address('192.0.2.9').packed + struct.pack('!H', 3)
                  + b'lab' + struct.pack('!H', 2)
                  + peer(0, '192.0.2.2', 64512) + peer(3, '2001:db8::1', 4200000001))


def rib(subtype=2, indexes=(0, 1), *, bits=24, prefix=b'\xc0\x00\x02', attributes=b'opaque'):
    entries = b''.join(struct.pack('!HIH', index, 120, len(attributes)) + attributes for index in indexes)
    return record(subtype, struct.pack('!IB', 0, bits) + prefix + struct.pack('!H', len(indexes)) + entries)


def inspect(data, **kwargs):
    return mrt.inventory(io.BytesIO(data), expected_size=len(data),
                         expected_sha256=hashlib.sha256(data).hexdigest(), **kwargs)


def test_mixed_families_and_peer_identity_counts_are_not_export_expectations():
    value = inspect(table() + rib() + rib(4, (1,), bits=32, prefix=b'\x20\x01\x0d\xb8'))
    assert value['collector_bgp_id'] == '192.0.2.9' and value['view_name'] == 'lab'
    assert value['record_count'] == 3
    first, second = value['peers']
    assert (first['index'], first['address'], first['asn'], first['asn_bytes']) == (0, '192.0.2.2', 64512, 2)
    assert (second['address'], second['asn'], second['asn_bytes']) == ('2001:db8::1', 4200000001, 4)
    assert first['ipv4_unicast_rib_entries'] == second['ipv4_unicast_rib_entries'] == 1
    assert first['ipv6_unicast_rib_entries'] == 0 and second['ipv6_unicast_rib_entries'] == 1
    assert 'Attributes are opaque' in value['limits'][1]


@pytest.mark.parametrize('data', [table()[:-1], table()+rib()[:-1],
    table()+rib()+b'partial', rib(), table()+table()+rib(), table(),
    table()+rib(indexes=(2,)), table()+rib(indexes=(0, 0)),
    table()+rib(bits=33, prefix=b'\x00'*5), table()+rib()+record(8, b'x'),
    record(1, b'x', kind=12), table()+record(2, b'bad'),
    table()+rib(attributes=b'')+record(4, b'x')])
def test_incomplete_or_unsupported_inventory_fails_without_partial_success(data):
    with pytest.raises(ValueError): inspect(data)


def test_unused_nlri_padding_bits_are_irrelevant_not_a_false_validation_failure():
    value = inspect(table()+rib(bits=25, prefix=b'\xc0\x00\x02\x7f'))
    assert value['peers'][0]['ipv4_unicast_rib_entries'] == 1


def test_record_bound_refuses_before_body_read():
    data = struct.pack('!IHHI', 0, 13, 1, mrt.MAX_RECORD_BYTES+1)
    with pytest.raises(ValueError, match='record length'): inspect(data)


def test_unknown_peer_flags_and_peer_count_bound_are_refused(monkeypatch):
    data = table()
    # First peer flag follows header, collector ID, view length/name and peer count.
    bad = bytearray(data); bad[23] = 4
    with pytest.raises(ValueError, match='flags'): inspect(bytes(bad)+rib())
    monkeypatch.setattr(mrt, 'MAX_PEERS', 1)
    with pytest.raises(ValueError, match='peer count'): inspect(data+rib())


def test_opaque_attribute_length_is_still_structurally_bounded():
    data = table()+rib()
    with pytest.raises(ValueError, match='Trailing bytes'):
        inspect(table()+record(2, rib()[12:]+b'extra'))
    broken = bytearray(rib()); broken[28:30] = struct.pack('!H', 65535)
    with pytest.raises(ValueError): inspect(table()+bytes(broken))


def test_identity_and_deadline_are_enforced():
    data = table()+rib()
    with pytest.raises(ValueError, match='SHA-256 mismatch'):
        mrt.inventory(io.BytesIO(data), expected_size=len(data), expected_sha256='0'*64)
    ticks = iter((0, 2))
    with pytest.raises(ValueError, match='deadline'):
        inspect(data, timeout_seconds=1, clock=lambda: next(ticks))
    with pytest.raises(ValueError, match='exceeds expected size'):
        mrt.inventory(io.BytesIO(data+b'x'), expected_size=len(data), expected_sha256='0'*64)


def test_file_path_and_changes_are_checked(tmp_path):
    data = table()+rib(); path = tmp_path/'input.mrt'; path.write_bytes(data)
    kwargs = dict(expected_size=len(data), expected_sha256=hashlib.sha256(data).hexdigest())
    assert mrt.inspect_file(path, **kwargs)['input']['path'] == str(path)
    link = tmp_path/'link'; link.symlink_to(path)
    with pytest.raises(ValueError, match='Canonical'): mrt.inspect_file(link, **kwargs)
    with pytest.raises(ValueError, match='Regular'): mrt.inspect_file(tmp_path, **kwargs)
    def change():
        previous = path.stat()
        os.utime(path, ns=(previous.st_atime_ns, previous.st_mtime_ns + 2_000_000_000))
    with pytest.raises(ValueError, match='changed'): mrt.inspect_file(path, check=change, **kwargs)


def test_cli_creates_fresh_output_only_after_verified_input(tmp_path, capsys, monkeypatch):
    script = Path(__file__).resolve().parents[1]/'scripts/inspect_mrt.py'
    spec = importlib.util.spec_from_file_location('inspect_mrt_cli', script)
    cli = importlib.util.module_from_spec(spec); spec.loader.exec_module(cli)
    data = table()+rib(); path = tmp_path/'input.mrt'; path.write_bytes(data)
    output = tmp_path/'inventory.json'
    args = ['--input', str(path), '--expected-bytes', str(len(data)), '--expected-sha256',
            hashlib.sha256(data).hexdigest(), '--output', str(output)]
    assert cli.main(args) == 0
    original = output.read_bytes()
    assert json.loads(original)['schema'] == mrt.SCHEMA
    assert output.stat().st_mode & 0o777 == 0o600
    assert cli.main(args) == 2 and output.read_bytes() == original
    output.unlink(); args[5] = '0'*64
    assert cli.main(args) == 2 and not output.exists()
    args[5] = hashlib.sha256(data).hexdigest()
    def failed_write(value, stream, **kwargs):
        stream.write('partial output retained for inspection')
        raise OSError('SIMULATED output failure')
    monkeypatch.setattr(cli.json, 'dump', failed_write)
    assert cli.main(args) == 2
    assert output.read_text() == 'partial output retained for inspection'
    assert cli.main(args) == 2  # Failed output must not be silently replaced.
