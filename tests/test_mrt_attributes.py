"""Encoded attribute facts, without assuming target export or best-path behavior."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from mrt_attributes import AttributeInventory, decode_attributes
from test_mrt_inventory import inspect, rib, table


def attribute(code, value):
    wide = len(value) > 255
    return bytes([0x40 | (0x10 if wide else 0), code]) + len(value).to_bytes(2 if wide else 1, 'big') + value


def segment(kind, asns):
    return bytes([kind, len(asns)]) + b''.join(a.to_bytes(4, 'big') for a in asns)


def attributes(path, communities=()):
    return (attribute(1, b'\x00') + attribute(2, path) + attribute(3, b'\xc0\x00\x02\x01')
            + attribute(8, b''.join(c.to_bytes(4, 'big') for c in communities)))


def test_inventory_counts_selected_peers_and_exact_checked_asns():
    selected = AttributeInventory([0], [1000, 1001])
    value = inspect(table()+rib(attributes=attributes(segment(2, [64512, 1000, 10010]),
        [0xffffff01, 0xffffff02, 0xffffff03, 0xffffff04])), attributes=selected)
    row = value['attribute_inventory']['peers'][0]
    assert row['entries'] == 1 and row['malformed_entries'] == 0
    assert row['checked_asn_entries'] == {'1000': 1}
    assert row['counts'] == {'no_export': 1, 'no_advertise': 1, 'no_export_subconfed': 1,
                            'nopeer': 1}
    assert row['max_as_sequence_length'] == 3
    assert 'unvalidated' in value['limits'][1]


def test_multiple_segments_sets_and_confederations_remain_encoded_facts():
    path = segment(2, [64512]*255)+segment(2, [1001])+segment(1, [1000])+segment(3, [64513])
    facts = decode_attributes(attributes(path), {1000, 1001})
    assert facts['as_sequence_length'] == 256 and facts['sequence_segments'] == 2
    assert facts['as_set'] is True and facts['confederation'] is True
    assert facts['first_asn'] == 64512 and facts['asns_present'] == [1000, 1001]


def test_malformed_selected_attributes_count_unknown_without_hiding_input_entries():
    selected = AttributeInventory([0, 1], [1000])
    value = inspect(table()+rib(attributes=b'\x40\x02\x08\x02\x02\x00'), attributes=selected)
    assert all(r['entries'] == r['malformed_entries'] == 1
               for r in value['attribute_inventory']['peers'])
    assert all(len(r['examples']) == 1 for r in value['attribute_inventory']['peers'])


def test_missing_mandatory_and_first_as_differences_are_not_export_failures():
    selected = AttributeInventory([0], [1000])
    value = inspect(table()+rib(attributes=attribute(2, segment(2, [1000]))), attributes=selected)
    counts = value['attribute_inventory']['peers'][0]['counts']
    assert counts['without_origin_attribute'] == counts['without_ipv4_next_hop_attribute'] == counts['first_as_differs_from_peer'] == 1
    assert 'export' in value['attribute_inventory']['scope']


@pytest.mark.parametrize('payload', [b'\x40', b'\x50\x02\x00', b'\x40\x02\x04x',
    attribute(1, b'\x03'), attribute(1, b'')+attribute(1, b''),
    attribute(3, b'x'), attribute(8, b'x'), attribute(2, b'\x02\x01\x00\x01'),
    attribute(2, b'\x02\x00'), attribute(2, b'\x05\x01'+b'\x00'*4)])
def test_malformed_known_attribute_encodings_refuse_classification(payload):
    with pytest.raises(ValueError): decode_attributes(payload, {1000})


@pytest.mark.parametrize('peers,asns', [([], [1000]), ([0, 0], [1000]),
    ([True], [1000]), ([4096], [1000]), ([0], []), ([0], [0]), ([0], [True]), ([0], [1000, 1000])])
def test_invalid_attribute_selection_refuses(peers, asns):
    with pytest.raises(ValueError): AttributeInventory(peers, asns)


def test_missing_peer_refuses_and_malformed_examples_are_bounded():
    with pytest.raises(ValueError, match='absent'):
        inspect(table()+rib(), attributes=AttributeInventory([2], [1000]))
    selected = AttributeInventory([0], [1000]); selected.bind([{'asn': 64512}])
    for _ in range(20): selected.observe(0, '192.0.2.0/24', b'bad')
    row = selected.result()['peers'][0]
    assert row['malformed_entries'] == 20 and len(row['examples']) == 5
    assert row['max_as_sequence_length'] is None


def test_mp_reach_without_code_three_is_only_an_encoded_presence_fact():
    selected = AttributeInventory([0], [1000])
    value = inspect(table()+rib(attributes=attribute(14, b'opaque')), attributes=selected)
    counts = value['attribute_inventory']['peers'][0]['counts']
    assert counts['without_ipv4_next_hop_attribute'] == counts['mp_reach_attribute_present'] == 1
    assert 'not a mandatory-attribute failure' in value['attribute_inventory']['scope']


@pytest.mark.parametrize('extra,code', [(['--attribute-peers', '0'], 2),
    (['--attribute-peers', 'bad', '--check-asns', '1000'], 2),
    (['--attribute-peers', '0', '--check-asns', '0'], 2),
    (['--attribute-peers', '2', '--check-asns', '1000'], 2),
    (['--attribute-peers', '0', '--check-asns', '1000'], 0)])
def test_cli_selection_and_attribute_implementation_binding(tmp_path, extra, code):
    script = Path(__file__).resolve().parents[1]/'scripts/inspect_mrt.py'
    spec = importlib.util.spec_from_file_location('mrt_attribute_cli', script)
    cli = importlib.util.module_from_spec(spec); spec.loader.exec_module(cli)
    data = table()+rib(attributes=attributes(segment(2, [64512, 1000])))
    path = tmp_path/'input'; path.write_bytes(data); output = tmp_path/'result.json'
    args = ['--input', str(path), '--expected-bytes', str(len(data)), '--expected-sha256',
            hashlib.sha256(data).hexdigest(), '--output', str(output)] + extra
    assert cli.main(args) == code
    assert output.exists() is (code == 0)
    if code == 0:
        value = json.loads(output.read_text())
        assert len(value['attribute_implementation_sha256']) == 64
        assert value['attribute_inventory']['peers'][0]['checked_asn_entries'] == {'1000': 1}



def test_exact_prefix_diagnostic_preserves_original_bytes_and_encoded_facts():
    encoded = attributes(segment(2, [64512, 1000])) + attribute(99, b'unknown')
    selected = AttributeInventory([0], [1000], ['192.0.2.0/24'])
    data = table()+rib(attributes=encoded)+rib(bits=24, prefix=b'\xc6\x12\x00', attributes=b'bad')
    value = inspect(data, attributes=selected)['attribute_inventory']
    assert value['prefixes'] == ['192.0.2.0/24']
    row = value['peers'][0]; assert row['entries'] == 1 and row['malformed_entries'] == 0
    route = row['routes'][0]
    assert route['attributes_hex'] == encoded.hex()
    assert route['attributes_sha256'] == hashlib.sha256(encoded).hexdigest()
    assert route['facts']['attribute_codes'] == [1, 2, 3, 8, 99]
    assert route['facts']['asns_present'] == [1000]


def test_diagnostic_absent_prefix_and_large_or_malformed_attributes_remain_honest():
    selected = AttributeInventory([0], [1000], ['198.18.0.0/24'])
    absent = inspect(table()+rib(), attributes=selected)['attribute_inventory']['peers'][0]
    assert absent['entries'] == 0 and absent['routes'] == []
    for encoded, reason in ((b'bad', 'Truncated'), (attribute(99, b'x'*4097), '4096')):
        selected = AttributeInventory([0], [1000], ['192.0.2.0/24'])
        row = inspect(table()+rib(attributes=encoded), attributes=selected)['attribute_inventory']['peers'][0]
        route = row['routes'][0]
        assert route['facts'] is None and reason in route['facts_unavailable_reason']
        assert route['attributes_sha256'] == hashlib.sha256(encoded).hexdigest()
        assert (route['attributes_hex'] is None) is (len(encoded) > 4096)


@pytest.mark.parametrize('prefixes', [[], ['192.0.2.1/24'], ['192.0.2.0/24']*2, ['::/0'], [True],
    [f'192.0.{i}.0/24' for i in range(9)]])
def test_diagnostic_selection_is_canonical_and_bounded(prefixes):
    with pytest.raises(ValueError): AttributeInventory([0], [1000], prefixes)


def test_diagnostic_refuses_duplicate_entries_and_peer_bound():
    with pytest.raises(ValueError): AttributeInventory(list(range(17)), [1000], ['192.0.2.0/24'])
    selected = AttributeInventory([0], [1000], ['192.0.2.0/24'])
    with pytest.raises(ValueError, match='Duplicate'):
        inspect(table()+rib()+rib(), attributes=selected)


def test_cli_prefix_diagnostic_requires_attribute_peers_and_binds_selected_prefix(tmp_path):
    script = Path(__file__).resolve().parents[1]/'scripts/inspect_mrt.py'
    spec = importlib.util.spec_from_file_location('mrt_prefix_cli', script)
    cli = importlib.util.module_from_spec(spec); spec.loader.exec_module(cli)
    data = table()+rib(attributes=attributes(segment(2, [64512])))
    path = tmp_path/'input'; path.write_bytes(data); output = tmp_path/'result.json'
    args = ['--input', str(path), '--expected-bytes', str(len(data)), '--expected-sha256',
            hashlib.sha256(data).hexdigest(), '--output', str(output), '--attribute-prefixes', '192.0.2.0/24']
    assert cli.main(args) == 2 and not output.exists()
    assert cli.main(args+['--attribute-peers','0','--check-asns','1000']) == 0
    assert json.loads(output.read_text())['attribute_inventory']['prefixes'] == ['192.0.2.0/24']



def test_prefix_diagnostic_retains_original_nlri_padding_separately_from_matching():
    selected = AttributeInventory([0], [1000], ['192.0.2.0/25'])
    value = inspect(table()+rib(bits=25, prefix=b'\xc0\x00\x02\x7f',
        attributes=attributes(segment(2, [64512]))), attributes=selected)['attribute_inventory']
    route = value['peers'][0]['routes'][0]
    assert route['prefix'] == '192.0.2.0/25'
    assert route['source_nlri'] == dict(prefix_length=25, encoded_prefix_hex='c000027f', unused_bits_zero=False)
    assert 'Absent counter keys mean zero among well-formed entries' in value['scope']
    assert 'Counters/entries cover only selected canonical source prefixes' in value['scope']
