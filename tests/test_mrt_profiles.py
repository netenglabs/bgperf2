"""SIMULATED source records; no real dump, network, Docker or benchmark."""
import copy
import hashlib
import importlib.util
import io
import ipaddress
import json
from pathlib import Path
import struct

import pytest

from mrt_attributes import decode_attributes
from mrt_controls import _attribute, _segment
from mrt_inventory import inventory
import mrt_profiles as profiles
from recipe_mrt import validate_spec


def selection():
    return dict(schema=profiles.SELECTION_SCHEMA, peer_indexes=[0, 1], group_sizes=[1, 2],
                target_asn=64515, observer_asn=64516)


def record(subtype, body):
    return struct.pack('!IHHI', 1, 13, subtype, len(body))+body


def table():
    peers = b''.join(b'\x02'+b'\xc0\x00\x02\x02'*2+n.to_bytes(4, 'big') for n in (64520, 64521))
    return record(1, b'\xc0\x00\x02\x01'+b'\x00\x00\x00\x02'+peers)


def attributes(asn=64520, *, path=None, extra=b''):
    return (_attribute(1, b'\x00')+_attribute(2, path or _segment(2, [asn]))
            +_attribute(3, b'\xc0\x00\x02\x02')+extra)


def rib(index, prefix, attrs):
    network = ipaddress.IPv4Network(prefix)
    encoded = network.network_address.packed[:(network.prefixlen+7)//8]
    body = (struct.pack('!IB', 0, network.prefixlen)+encoded+b'\x00\x01'
            +struct.pack('!HIH', index, 1, len(attrs))+attrs)
    return record(2, body)


def scan(data, selected=None):
    observer = profiles.PrefixProfiles(selected or selection())
    report = inventory(io.BytesIO(data), expected_size=len(data),
                       expected_sha256=hashlib.sha256(data).hexdigest(), attributes=observer)
    return observer, report


def overlapping():
    return (table()+rib(0, '198.18.0.1/32', attributes())
        +rib(0, '198.18.0.2/32', attributes(path=_segment(2, [64520])+_segment(1, [123])))
        +rib(1, '198.18.0.1/32', attributes(64521))
        +rib(1, '198.18.0.2/32', attributes(64521))
        +rib(1, '198.18.0.0/24', attributes(64521)))


def test_profiles_are_source_unions_not_counts_or_target_observations():
    observer, report = scan(overlapping())
    assert report['attribute_inventory']['status'] == 'prepared'
    results = list(observer.workloads(dict(path='/source.mrt', bytes=1, sha256='a'*64)))
    assert [(n, p, len(w['expected_prefixes'])) for n, p, w in results] == [
        (1, profiles.PROFILES[0], 1), (1, profiles.PROFILES[1], 2),
        (2, profiles.PROFILES[0], 3), (2, profiles.PROFILES[1], 3)]
    for n, _, workload in results:
        assert len(workload['peers']) == n
        assert workload['expected_prefixes'] == sorted(set(workload['expected_prefixes']))
        validate_spec(workload, dict(neighbors=n, prefixes_per_peer=max(p['prefixes'] for p in workload['peers'])))
    assert results[-1][2]['peers'] == [dict(index=0, asn=64520, prefixes=2), dict(index=1, asn=64521, prefixes=3)]
    assert results[0][2]['expected_prefixes'] == ['198.18.0.1/32']


def test_peer_order_drives_nested_groups():
    selected = selection(); selected['peer_indexes'] = [1, 0]
    observer, _ = scan(overlapping(), selected)
    assert [p['index'] for p in next(observer.workloads({}))[2]['peers']] == [1]
    assert len(next(observer.workloads({}))[2]['expected_prefixes']) == 3


@pytest.mark.parametrize('change', [
    {'extra': 1}, {'schema': 'unknown'}, {'peer_indexes': []}, {'peer_indexes': [0, 0]},
    {'peer_indexes': [True]}, {'peer_indexes': [-1]}, {'peer_indexes': [4096]},
    {'group_sizes': [2, 1]}, {'group_sizes': [1]}, {'group_sizes': [True, 2]},
    {'target_asn': 64516}, {'target_asn': 0}, {'target_asn': True}, {'observer_asn': 2**32}])
def test_invalid_selection_refused(change):
    value = selection(); value.update(change)
    with pytest.raises(ValueError): profiles.PrefixProfiles(value)


def test_duplicate_per_peer_across_records_refused_even_with_different_path():
    data = table()+rib(0, '198.18.0.1/32', attributes())+rib(0, '198.18.0.1/32', attributes(64521))
    with pytest.raises(ValueError, match='Duplicate'): scan(data)


@pytest.mark.parametrize('attrs,reason', [
    (b'bad', 'malformed_attributes'),
    (_attribute(2, _segment(2, [64520]))+_attribute(3, b'1234'), 'missing_origin'),
    (_attribute(1, b'\x00')+_attribute(3, b'1234'), 'missing_as_path'),
    (_attribute(1, b'\x00')+_attribute(2, _segment(2, [64520])), 'missing_next_hop'),
    (attributes(64521), 'unexpected_first_as'),
    (attributes(path=_segment(2, [64520, 64515])), 'role_or_zero_asn_in_path'),
    (attributes(path=_segment(2, [64520])+_segment(1, [64516])), 'role_or_zero_asn_in_path'),
    (attributes(path=_segment(2, [64520, 0])), 'role_or_zero_asn_in_path'),
    (attributes(path=_segment(2, [64520])+_segment(3, [123])), 'confederation'),
    (attributes(extra=_attribute(14, b'opaque', 0x80)), 'mp_reach'),
    *[(attributes(extra=_attribute(8, n.to_bytes(4, 'big'), 0xc0)), 'export_scope_community')
      for n in sorted(profiles.SCOPE_COMMUNITIES)],
    (attributes(extra=_attribute(99, b'x'*4062, 0x80)), 'oversized_attributes')])
def test_unsupported_entries_refuse_whole_workload_instead_of_filtering(attrs, reason):
    observer, report = scan(table()+rib(0, '198.18.0.1/32', attrs)
                            +rib(1, '198.18.0.1/32', attributes(64521)))
    assert report['attribute_inventory']['status'] == 'refused'
    assert observer.failures[reason] == 1
    with pytest.raises(ValueError, match='Unsupported'): list(observer.workloads({}))


def test_nopeer_is_retained_and_long_path_boundary_is_not_total_length():
    source = 64520
    first255 = _segment(2, [source]*255)+_segment(2, [source]*3)
    first3 = _segment(2, [source]*3)+_segment(2, [source]*255)
    assert decode_attributes(attributes(path=first255), set())['as_sequence_length'] == 258
    assert decode_attributes(attributes(path=first3), set())['as_sequence_length'] == 258
    data = (table()+rib(0, '198.18.0.1/32', attributes(path=first255))
            +rib(0, '198.18.0.2/32', attributes(path=first3))
            +rib(1, '198.18.0.1/32', attributes(64521, extra=_attribute(8, b'\xff\xff\xff\x04', 0xc0))))
    observer, report = scan(data)
    first, second = report['attribute_inventory']['peers']
    assert first['first_sequence_length_255_entries'] == first['prepend_overflow_candidates'] == 1
    assert first['examples'] == [dict(prefix='198.18.0.1/32', first_sequence_length=255, segment_count=2)]
    assert second['counts']['nopeer'] == 1
    assert report['attribute_inventory']['status'] == 'prepared'
    assert len(list(observer.workloads({}))[-1][2]['expected_prefixes']) == 2


def test_empty_peers_absent_peer_and_role_table_asn_refused():
    observer, _ = scan(table()+rib(0, '198.18.0.1/32', attributes()))
    assert observer.result()['refusal_counts']['empty_selected_peers'] == 1
    selected = selection(); selected['peer_indexes'] = [0, 2]
    with pytest.raises(ValueError, match='absent'): scan(overlapping(), selected)
    selected = selection(); selected['target_asn'] = 64521; selected['peer_indexes'] = [0]; selected['group_sizes'] = [1]
    with pytest.raises(ValueError, match='peer table'): scan(overlapping(), selected)


def test_unique_prefix_capacity_is_bounded(monkeypatch):
    monkeypatch.setattr(profiles, 'MAX_PREFIXES', 1)
    with pytest.raises(ValueError, match='capacity'): scan(overlapping())


def load_cli():
    path = Path(__file__).resolve().parents[1]/'scripts/prepare_mrt_profiles.py'
    spec = importlib.util.spec_from_file_location('profile_cli', path)
    cli = importlib.util.module_from_spec(spec); spec.loader.exec_module(cli)
    return cli


def cli_args(tmp_path, data):
    path = tmp_path/'input.mrt'; path.write_bytes(data)
    spec = tmp_path/'selection.json'; spec.write_text(json.dumps(selection()))
    output = tmp_path/'inventory.json'
    args = ['--input', str(path), '--expected-bytes', str(len(data)), '--expected-sha256',
            hashlib.sha256(data).hexdigest(), '--profile-spec', str(spec), '--output', str(output)]
    return args, output, spec


def test_cli_publishes_hashed_private_specs_only_after_verified_source(tmp_path):
    cli = load_cli(); args, output, _ = cli_args(tmp_path, overlapping())
    assert cli.main(args) == 0
    result = json.loads(output.read_text())
    assert result['prefix_profiles']['status'] == 'prepared'
    assert output.stat().st_mode & 0o777 == 0o600
    artifacts = result['prefix_profiles']['workloads']; assert len(artifacts) == 4
    originals = {}
    for row in artifacts:
        artifact = row['artifact']; path = Path(artifact['path']); original = path.read_bytes()
        originals[path] = original
        assert path.stat().st_mode & 0o777 == 0o600
        assert len(original) == artifact['bytes']
        assert hashlib.sha256(original).hexdigest() == artifact['sha256']
    assert cli.main(args) == 2
    assert all(p.read_bytes() == v for p, v in originals.items())


@pytest.mark.parametrize('failure', ['hash', 'duplicate_selection', 'unsupported', 'destination_symlink'])
def test_cli_never_admits_partial_or_unsupported_input(tmp_path, failure):
    cli = load_cli(); data = overlapping()
    if failure == 'unsupported': data = table()+rib(0, '198.18.0.1/32', b'bad')
    args, output, spec = cli_args(tmp_path, data)
    if failure == 'hash': args[5] = '0'*64
    if failure == 'duplicate_selection': spec.write_text('{"schema":1,"schema":2}')
    if failure == 'destination_symlink': (tmp_path/'workloads').symlink_to(tmp_path)
    assert cli.main(args) == 2
    if failure == 'unsupported':
        assert json.loads(output.read_text())['prefix_profiles']['status'] == 'refused'
    else: assert not output.exists()
    assert not (tmp_path/'workloads').exists() or failure == 'destination_symlink'


def test_empty_reject_profile_is_a_recorded_refusal_before_publication(tmp_path):
    cli = load_cli()
    data = (table()+rib(0, '198.18.0.1/32', attributes(path=_segment(2, [64520])+_segment(1, [123])))
            +rib(1, '198.18.0.1/32', attributes(64521)))
    args, output, _ = cli_args(tmp_path, data)
    assert cli.main(args) == 2
    report = json.loads(output.read_text())['prefix_profiles']
    assert report['status'] == 'refused' and report['refusal_counts']['empty_reject_profile'] == 1
    assert not (tmp_path/'workloads').exists()
