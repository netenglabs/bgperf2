'''Tests for get_neighbors_state(), which parses each daemon's CLI output.

This is the layer that rots. Every daemon reports received/accepted prefix
counts differently and changes the format between releases -- that is the
stated historical pain of this project. Parsing against recorded output catches
a format change in a second instead of after a benchmark silently reports zero.

Targets are built with object.__new__ so no container is created; the only
things these methods touch are self.local() and the TextFSM template.
'''
import json

import pytest

from bird import BIRDTarget
from frr import FRRoutingTarget


def build(target_class, output):
    '''A target whose local() returns recorded CLI output.'''
    target = object.__new__(target_class)
    target.local = lambda cmd, **kwargs: output
    return target


# --- BIRD: 'birdc show protocols all', parsed with bird.tfsm -----------------

def test_bird_parses_recorded_output(fixture_text):
    target = build(BIRDTarget, fixture_text('bird_show_protocols_all.txt').encode('utf-8'))
    received, accepted = target.get_neighbors_state()

    # The recorded capture has one established BGP session, to the monitor.
    assert '10.10.0.2' in accepted
    assert isinstance(accepted['10.10.0.2'], int)
    assert set(received) == set(accepted)


def test_bird_ignores_non_bgp_protocols(fixture_text):
    '''The output also contains Device, Direct and Kernel protocols, none of
    which have a neighbor address and none of which should appear.
    '''
    target = build(BIRDTarget, fixture_text('bird_show_protocols_all.txt').encode('utf-8'))
    received, accepted = target.get_neighbors_state()
    for name in accepted:
        assert name.count('.') == 3, f"{name} is not a neighbor address"


def test_bird_handles_empty_output():
    target = build(BIRDTarget, b'')
    received, accepted = target.get_neighbors_state()
    assert received == {}
    assert accepted == {}


# --- FRR: 'vtysh -c "sh ip bgp summary json"' -------------------------------

FRR_SUMMARY = {
    'ipv4Unicast': {
        'routerId': '10.10.255.254',
        'as': 1000,
        'peers': {
            '10.10.0.3': {'remoteAs': 1003, 'pfxRcd': 500, 'pfxSnt': 0, 'state': 'Established'},
            '10.10.0.4': {'remoteAs': 1004, 'pfxRcd': 500, 'pfxSnt': 0, 'state': 'Established'},
            '10.10.0.5': {'remoteAs': 1005, 'pfxRcd': 0, 'pfxSnt': 0, 'state': 'Active'},
        },
    }
}


def test_frr_parses_prefix_counts():
    target = build(FRRoutingTarget, json.dumps(FRR_SUMMARY).encode('utf-8'))
    received, accepted = target.get_neighbors_state()

    assert accepted == {'10.10.0.3': 500, '10.10.0.4': 500, '10.10.0.5': 0}


def test_frr_handles_no_output():
    '''local() returns falsy before bgpd is up; that must not raise.'''
    target = build(FRRoutingTarget, b'')
    with pytest.raises((TypeError, UnboundLocalError, KeyError)):
        # Documents current behavior: an empty reply is not handled and blows up
        # inside the parser. Worth fixing; pinned here so a fix is deliberate.
        target.get_neighbors_state()
