# Copyright (C) 2026 bgperf2 contributors. Apache-2.0.
"""Bounded source-only IPv4 unions under explicit, conservative export profiles."""
from collections import Counter

from mrt_attributes import decode_attributes

SELECTION_SCHEMA = 'bgperf2/mrt-profile-selection/v1alpha1'
PROFILE_SCHEMA = 'bgperf2/mrt-prefix-profiles/v1alpha1'
PROFILES = ('as-set-reject-v1', 'as-set-forward-v1')
MAX_PREFIXES = 5_000_000
MAX_ATTRIBUTE_BYTES = 4061  # 4096 minus header/lengths/NLRI and 7-byte prepend margin.
SCOPE_COMMUNITIES = {0xffffff01, 0xffffff02, 0xffffff03}


def validate_selection(value):
    if (not isinstance(value, dict) or set(value) != {
            'schema', 'peer_indexes', 'group_sizes', 'target_asn', 'observer_asn'}
            or value.get('schema') != SELECTION_SCHEMA):
        raise ValueError('Unsupported MRT profile selection')
    indexes, groups = value['peer_indexes'], value['group_sizes']
    if (not isinstance(indexes, list) or not 1 <= len(indexes) <= 128
            or any(type(p) is not int or not 0 <= p < 4096 for p in indexes)
            or len(set(indexes)) != len(indexes)):
        raise ValueError('Unique ordered peer indexes from 0 to 4095 required (at most 128)')
    if (not isinstance(groups, list) or not 1 <= len(groups) <= 3
            or any(type(n) is not int or not 1 <= n <= len(indexes) for n in groups)
            or groups != sorted(set(groups)) or groups[-1] != len(indexes)):
        raise ValueError('One to three increasing nested group sizes ending at selected peer count required')
    roles = [value['target_asn'], value['observer_asn']]
    if any(type(n) is not int or not 1 <= n < 2**32 for n in roles) or roles[0] == roles[1]:
        raise ValueError('Distinct nonzero four-byte role ASNs required')
    return value


class PrefixProfiles:
    """Observe selected source entries; no best-path simulator or target output.

    The prefix universe maps canonical strings to seen-peer masks. Profile/group
    masks share those strings, bounding storage independently of entry count.
    Refusal counters do not make unsupported paths silently disappear: ANY such
    counter prevents publishing every workload specification.
    """
    def __init__(self, selection):
        self.selection = validate_selection(selection)
        self.indexes = list(selection['peer_indexes'])
        self.ordinals = {index: ordinal for ordinal, index in enumerate(self.indexes)}
        self.rows = {p: dict(index=p, entries=0, counts=Counter(),
                            first_sequence_length_255_entries=0,
                            prepend_overflow_candidates=0, examples=[]) for p in self.indexes}
        self.seen, self.reject = {}, {}
        self.failures = Counter()
        self.peers = None

    def bind(self, peers):
        if any(p >= len(peers) for p in self.indexes):
            raise ValueError('Selected MRT profile peer is absent')
        roles = {self.selection['target_asn'], self.selection['observer_asn']}
        # Check every peer table ASN, not only the selected sources.
        if any(p['asn'] in roles for p in peers):
            raise ValueError('Role ASN occurs in the MRT peer table')
        if any(not 1 <= peers[p]['asn'] < 2**32 for p in self.indexes):
            raise ValueError('Selected source ASN must be nonzero and fit four bytes')
        self.peers = peers

    def observe(self, index, prefix, attributes):
        if index not in self.rows:
            return
        row = self.rows[index]; row['entries'] += 1
        mask = 1 << self.ordinals[index]
        previous = self.seen.get(prefix, 0)
        if previous & mask:
            raise ValueError('Duplicate IPv4 prefix for one selected source peer')
        if not previous and len(self.seen) >= MAX_PREFIXES:
            raise ValueError('MRT profile unique-prefix capacity exceeded')
        self.seen[prefix] = previous | mask
        if row['entries'] > MAX_PREFIXES:
            raise ValueError('MRT profile per-peer capacity exceeded')
        reasons = []
        if len(attributes) > MAX_ATTRIBUTE_BYTES:
            reasons.append('oversized_attributes')
        try:
            facts = decode_attributes(attributes, {0, self.selection['target_asn'],
                                                  self.selection['observer_asn']})
        except ValueError as exc:
            self.failures['malformed_attributes'] += 1
            row['counts']['malformed_attributes'] += 1
            if len(row['examples']) < 5:
                row['examples'].append(dict(prefix=prefix, error=str(exc)))
            return
        for code, label in ((1, 'missing_origin'), (2, 'missing_as_path'), (3, 'missing_next_hop')):
            if code not in facts['attribute_codes']: reasons.append(label)
        if facts['first_asn'] != self.peers[index]['asn']: reasons.append('unexpected_first_as')
        if facts['asns_present']: reasons.append('role_or_zero_asn_in_path')
        if facts['confederation']: reasons.append('confederation')
        if SCOPE_COMMUNITIES.intersection(facts['communities']): reasons.append('export_scope_community')
        if 14 in facts['attribute_codes']: reasons.append('mp_reach')
        if facts['first_sequence_length'] == 255:
            row['first_sequence_length_255_entries'] += 1
            if facts['segment_count'] != 255:
                row['prepend_overflow_candidates'] += 1
                if len(row['examples']) < 5:
                    row['examples'].append(dict(prefix=prefix, first_sequence_length=255,
                                                segment_count=facts['segment_count']))
        if facts['as_set']: row['counts']['as_set'] += 1
        if 0xffffff04 in facts['communities']: row['counts']['nopeer'] += 1
        for reason in reasons:
            self.failures[reason] += 1
            row['counts'][reason] += 1
        if not reasons and not facts['as_set']:
            self.reject[prefix] = self.reject.get(prefix, 0) | mask

    def result(self):
        empty = [p for p in self.indexes if not self.rows[p]['entries']]
        if empty: self.failures['empty_selected_peers'] = len(empty)
        for count in self.selection['group_sizes']:
            mask = (1 << count)-1
            if not any(seen & mask for seen in self.reject.values()):
                self.failures['empty_reject_profile'] = 1
        return dict(schema=PROFILE_SCHEMA, selection=self.selection,
                    status='refused' if self.failures else 'prepared',
                    refusal_counts=dict(self.failures),
                    peers=[dict(self.rows[p], asn=self.peers[p]['asn']) for p in self.indexes],
                    unique_source_prefixes=len(self.seen),
                    scope='Source-derived IPv4 prefix unions under declared profiles; not a BGP best-path or attribute fidelity proof.')

    def workloads(self, source):
        from recipe_mrt import SPEC_SCHEMA
        if self.result()['status'] != 'prepared':
            raise ValueError('Unsupported source facts prevent MRT workload publication')
        for count in self.selection['group_sizes']:
            peers = [dict(index=p, asn=self.peers[p]['asn'], prefixes=self.rows[p]['entries'])
                     for p in self.indexes[:count]]
            mask = (1 << count)-1
            for profile in PROFILES:
                prefixes = self.reject if profile == PROFILES[0] else self.seen
                expected = sorted(p for p, seen in prefixes.items() if seen & mask)
                if not expected:
                    raise ValueError('Empty MRT profile cannot attest convergence')
                yield count, profile, dict(schema=SPEC_SCHEMA, input=source, peers=peers,
                    target_asn=self.selection['target_asn'], observer_asn=self.selection['observer_asn'],
                    expected_prefixes=expected,
                    expectation_description=(profile + ': unique canonical IPv4 union from selected original source peers; '
                        'reject profile removes AS_SET paths before union. No malformed/ambiguous source paths, '
                        'role-AS/AS0 loops, confederations, export-scope communities or MP_REACH accepted. '
                        'NOPEER is retained for this downstream transit workload. Expected set derived before target output.'))
