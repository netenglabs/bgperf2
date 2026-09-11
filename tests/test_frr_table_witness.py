'''FRR's own account of the table, parsed without a Docker daemon.

`bird.table_witness()` has had this coverage since it was written; FRR's
equivalent needs it for a sharper reason. The witness is withheld silently when
a field it expects is missing -- `state`, `pfxSnt`, `pfxRcd` -- and a withheld
witness does not fail anything: it surfaces as a NOTE and a *qualified* row.
So a field rename in a future FRR release would quietly remove the only size
floor and the only cross-check an MRT row has, and nothing would say so.
'''
import frr


def summary(peers):
    return {'ipv4Unicast': {'peers': peers}}


ESTABLISHED = {
    '10.10.0.2': {'state': 'Established', 'pfxSnt': 961201, 'pfxRcd': 0},
    '10.10.0.3': {'state': 'Established', 'pfxSnt': 961201, 'pfxRcd': 1049795},
    '10.10.0.4': {'state': 'Established', 'pfxSnt': 961201, 'pfxRcd': 1049785},
}


def test_the_export_count_is_read_off_the_monitors_own_session():
    '''The target's end of the very session the monitor reads. Measured
    against a real run: FRR reported 961,201 sent and the monitor reported
    961,201 accepted.'''
    w = frr.table_witness(summary(ESTABLISHED), '10.10.0.2', expected_peerings=3)
    assert w['exported_to_monitor'] == 961201


def test_the_import_sum_covers_every_peer():
    w = frr.table_witness(summary(ESTABLISHED), '10.10.0.2', expected_peerings=3)
    assert w['imported_paths'] == 1049795 + 1049785


def test_best_paths_is_withheld_deliberately_not_for_want_of_a_number():
    '''FRR reports a table size, but `ribCount` and `Total Prefixes` disagreed
    on a measured run and neither is established to mean "prefixes holding a
    selected best path". A witness that is subtly wrong excuses monitor
    declines it has no standing to excuse, and `None` is how `convergence.py`
    is told to attest to nothing.'''
    w = frr.table_witness(summary(ESTABLISHED), '10.10.0.2', expected_peerings=3)
    assert w['best_paths'] is None


def test_a_sum_missing_a_peering_is_withheld_rather_than_reported_short():
    '''A partial read looks exactly like a table that shrank, which is the one
    thing this witness exists to rule on.'''
    w = frr.table_witness(summary(ESTABLISHED), '10.10.0.2', expected_peerings=4)
    assert w['imported_paths'] is None
    assert w['peerings_measured'] == 3


def test_a_session_that_is_not_established_contributes_nothing():
    '''Measured on FRR 8.5: a peer whose session dropped keeps `pfxSnt` and
    `pfxRcd` in the document and reports them as 0, so reading them without
    checking `state` would publish a collapse as a measurement.'''
    peers = dict(ESTABLISHED)
    peers['10.10.0.3'] = {'state': 'Active', 'pfxSnt': 0, 'pfxRcd': 0}
    w = frr.table_witness(summary(peers), '10.10.0.2', expected_peerings=3)
    assert w['imported_paths'] is None
    assert w['peerings_measured'] == 2


def test_the_monitor_session_must_be_established_to_report_an_export():
    peers = {'10.10.0.2': {'state': 'Active', 'pfxSnt': 0, 'pfxRcd': 0}}
    w = frr.table_witness(summary(peers), '10.10.0.2', expected_peerings=1)
    assert w['exported_to_monitor'] is None


def test_an_unparseable_summary_attests_to_nothing():
    for document in (None, {}, {'ipv4Unicast': {}}):
        w = frr.table_witness(document, '10.10.0.2', expected_peerings=3)
        assert w['exported_to_monitor'] is None
        assert w['imported_paths'] is None


def test_a_boolean_is_not_a_count():
    peers = {'10.10.0.2': {'state': 'Established', 'pfxSnt': True, 'pfxRcd': 0}}
    w = frr.table_witness(summary(peers), '10.10.0.2', expected_peerings=1)
    assert w['exported_to_monitor'] is None


def test_neighbors_state_reads_accepted_counts_and_leaves_received_empty():
    '''FRR has no received-prefix counter; whether a neighbour finished sending
    is decided from End-of-RIB in bgpd.log instead.'''
    received, accepted = frr.neighbors_state(summary(ESTABLISHED))
    assert received == {}
    assert accepted['10.10.0.3'] == 1049795


def test_neighbors_state_tolerates_a_summary_that_could_not_be_read():
    assert frr.neighbors_state(None) == ({}, {})
