# Copyright (C) 2026 bgperf2 contributors. Apache-2.0.
"""Selected encoded attribute facts; deliberately no BGP policy or path selection."""
from collections import Counter


def decode_attributes(payload, check_asns):
    data = memoryview(payload)
    offset, values = 0, {}
    while offset < len(data):
        if len(data)-offset < 3:
            raise ValueError('Truncated attribute header')
        flags, code = data[offset], data[offset+1]
        width = 2 if flags & 16 else 1
        if len(data)-offset < 2+width:
            raise ValueError('Truncated extended attribute header')
        size = int.from_bytes(data[offset+2:offset+2+width], 'big')
        offset += 2+width
        if offset+size > len(data) or code in values:
            raise ValueError('Truncated or duplicate attribute')
        values[code] = data[offset:offset+size]
        offset += size
    facts = {'attribute_codes': sorted(values), 'asns_present': [], 'first_asn': None,
             'as_set': False, 'confederation': False, 'sequence_segments': 0,
             'as_sequence_length': 0, 'communities': [],
             'segment_count': 0, 'first_sequence_length': None}
    if 1 in values and (len(values[1]) != 1 or values[1][0] > 2):
        raise ValueError('Invalid ORIGIN')
    if 3 in values and len(values[3]) != 4:
        raise ValueError('Invalid IPv4 NEXT_HOP length')
    if 2 in values:
        path = values[2]; offset = 0; present = set()
        while offset < len(path):
            if len(path)-offset < 2:
                raise ValueError('Truncated AS_PATH segment')
            kind, count = path[offset], path[offset+1]; offset += 2
            if kind not in (1, 2, 3, 4) or count == 0 or offset+4*count > len(path):
                raise ValueError('Invalid four-byte AS_PATH segment')
            numbers = [int.from_bytes(path[i:i+4], 'big') for i in range(offset, offset+4*count, 4)]
            facts['segment_count'] += 1
            if offset == 2 and kind == 2:
                facts['first_asn'] = numbers[0]
                facts['first_sequence_length'] = count
            if kind == 1: facts['as_set'] = True
            if kind in (3, 4): facts['confederation'] = True
            if kind == 2:
                facts['sequence_segments'] += 1
                facts['as_sequence_length'] += count
            present.update(check_asns.intersection(numbers))
            offset += 4*count
        facts['asns_present'] = sorted(present)
    if 8 in values:
        communities = values[8]
        if len(communities) % 4: raise ValueError('Invalid standard community length')
        facts['communities'] = [int.from_bytes(communities[i:i+4], 'big')
                                for i in range(0, len(communities), 4)]
    return facts


class AttributeInventory:
    def __init__(self, peer_indexes, check_asns):
        if (not peer_indexes or len(peer_indexes) > 4096 or len(set(peer_indexes)) != len(peer_indexes)
                or any(type(p) is not int or not 0 <= p < 4096 for p in peer_indexes)):
            raise ValueError('Unique selected peer indexes from 0 to 4095 required')
        if (not check_asns or len(check_asns) > 64 or len(set(check_asns)) != len(check_asns)
                or any(type(a) is not int or not 1 <= a < 2**32 for a in check_asns)):
            raise ValueError('Unique checked ASNs from 1 to 4294967295 required')
        self.indexes, self.asns = list(peer_indexes), set(check_asns)
        self.rows = {p: dict(peer_index=p, entries=0, malformed_entries=0, counts=Counter(),
                            checked_asn_entries=Counter(), max_as_sequence_length=None,
                            examples=[]) for p in peer_indexes}
        self.peers = None

    def bind(self, peers):
        if any(p >= len(peers) for p in self.indexes):
            raise ValueError('Selected attribute peer index is absent')
        self.peers = peers

    def observe(self, index, prefix, attributes):
        if index not in self.rows: return
        row = self.rows[index]; row['entries'] += 1
        try:
            facts = decode_attributes(attributes, self.asns)
        except ValueError as exc:
            row['malformed_entries'] += 1
            if len(row['examples']) < 5: row['examples'].append(dict(prefix=prefix, error=str(exc)))
            return
        counts = row['counts']
        for code, label in ((0xffffff01, 'no_export'), (0xffffff02, 'no_advertise'),
                            (0xffffff03, 'no_export_subconfed'), (0xffffff04, 'nopeer')):
            if code in facts['communities']: counts[label] += 1
        for code, label in ((1, 'without_origin_attribute'), (2, 'without_as_path_attribute'),
                            (3, 'without_ipv4_next_hop_attribute')):
            if code not in facts['attribute_codes']: counts[label] += 1
        if 14 in facts['attribute_codes']: counts['mp_reach_attribute_present'] += 1
        if facts['first_asn'] != self.peers[index]['asn']: counts['first_as_differs_from_peer'] += 1
        if facts['as_set']: counts['as_set'] += 1
        if facts['confederation']: counts['confederation'] += 1
        if facts['sequence_segments'] > 1: counts['multiple_as_sequence_segments'] += 1
        if 2 in facts['attribute_codes']:
            row['max_as_sequence_length'] = max(row['max_as_sequence_length'] or 0, facts['as_sequence_length'])
        for asn in facts['asns_present']: row['checked_asn_entries'][str(asn)] += 1

    def result(self):
        return dict(peer_indexes=self.indexes, checked_asns=sorted(self.asns),
                    peers=[self.rows[p] for p in self.indexes],
                    scope='Encoded IPv4 RIB attribute facts only; no best-path, export, unique-prefix or expected-route inference. Absent counter keys mean zero among well-formed entries. The separate maximum covers well-formed AS_PATH entries and stays null if none were classified; lack of code 3 is not a mandatory-attribute failure because MP_REACH may carry the next hop.')
