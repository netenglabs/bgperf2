'''The target's own account of the table it holds, beside the monitor's count.

`bgperf2-dcs`: an MRT run's monitor count overshoots by ~1.5% while a minority
of injectors have finished, then settles as the rest complete, and
`ConvergenceTracker` reads that settled decline as route loss.  The monitor is
one BGP session's view of the target and it is the only instrument any
published timing comes from, so nothing checks it.  These cover the second
witness -- BIRD's own `Routes:` gauge -- and the artifact section that records
it, plus the account `ConvergenceTracker` publishes here of what the rule it
feeds actually did.  The rule itself is pinned in `test_convergence.py`: this
module covers the measurement and the document, not the verdict.
'''
import pytest

from base import Target
from bgperf2 import target_table_unmeasured
from convergence import ConvergenceTracker
from bird import BIRDTarget, neighbors_state, table_witness
from measurements import (
    EventKind,
    EventPhase,
    LifecycleEvent,
    event_artifact,
    target_table_section,
)


# A target's own `show protocols all`: two generators sending, one monitor
# session that receives everything and announces nothing.  Both generators
# announce prefix blocks that overlap, so `imported` (every path held) is
# larger than `preferred` (one best path per distinct prefix) -- which is the
# whole reason both are published.
TARGET_PROTOCOLS = '''BIRD 3.3.2 ready.
Name       Proto      Table      State  Since         Info
device1    Device     ---        up     20:55:21.029

bgp1       BGP        ---        up     20:55:23.892  Established
  BGP state:          Established
    Neighbor address: 10.10.0.3
    Neighbor AS:      1003
  Channel ipv4
    State:          UP
    Table:          master4
    Routes:         100 imported, 0 filtered, 0 exported, 60 preferred
    Route change stats:     received   rejected   filtered    ignored   RX limit      limit   accepted
      Import updates:            100          0          0          0          0          0        100
      Import withdraws:            0          0        ---          0        ---        ---          0

bgp2       BGP        ---        up     20:55:23.951  Established
  BGP state:          Established
    Neighbor address: 10.10.0.4
    Neighbor AS:      1004
  Channel ipv4
    State:          UP
    Table:          master4
    Routes:         90 imported, 0 filtered, 0 exported, 40 preferred
    Route change stats:     received   rejected   filtered    ignored   RX limit      limit   accepted
      Import updates:             90          0          0          0          0          0         90
      Import withdraws:            0          0        ---          0        ---        ---          0

monitor    BGP        ---        up     20:55:23.999  Established
  BGP state:          Established
    Neighbor address: 10.10.0.2
    Neighbor AS:      1001
  Channel ipv4
    State:          UP
    Table:          master4
    Routes:         0 imported, 0 filtered, 100 exported, 0 preferred
    Route change stats:     received   rejected   filtered    ignored   RX limit      limit   accepted
      Import updates:              0          0          0          0          0          0          0
      Import withdraws:            0          0        ---          0        ---        ---          0
'''

# The same target with one session still coming up: BIRD prints no `Routes:`
# line at all for a DOWN channel.
TARGET_PROTOCOLS_ONE_SESSION_DOWN = TARGET_PROTOCOLS.replace(
    '''    State:          UP
    Table:          master4
    Routes:         90 imported, 0 filtered, 0 exported, 40 preferred
''',
    '''    State:          DOWN
    Table:          master4
''')


# --- the gauge -------------------------------------------------------------

def test_best_paths_is_the_distinct_prefix_count():
    '''One best route per prefix, which is what the monitor's count tracks.'''
    witness = table_witness(TARGET_PROTOCOLS, expected_peerings=3)
    assert witness['best_paths'] == 100
    assert witness['imported_paths'] == 190


def test_the_monitor_session_is_read_at_the_target_end():
    witness = table_witness(TARGET_PROTOCOLS, monitor_address='10.10.0.2',
                            expected_peerings=3)
    assert witness['exported_to_monitor'] == 100


def test_no_monitor_address_leaves_the_export_unread():
    '''Absent, not zero: a session nobody looked for held nothing that we know.'''
    assert table_witness(TARGET_PROTOCOLS,
                         expected_peerings=3)['exported_to_monitor'] is None


def test_a_session_that_has_not_connected_withholds_the_sums():
    '''The guard has to count configured sessions, not visible protocols.

    `BIRDTarget.DYNAMIC_NEIGHBORS` is True, so BIRD spawns a `dynbgp` protocol
    per *connected* peer and takes it away again when the session drops.
    Comparing measured against the protocols on show is therefore vacuous: the
    denominator shrinks with the numerator, and a tester that flaps mid-run
    publishes a `best_paths` decline of exactly the shape real route loss has
    -- on the one series the convergence rule will be written against.
    '''
    # Three peerings are up; the run configured ten.
    witness = table_witness(TARGET_PROTOCOLS, monitor_address='10.10.0.2',
                            expected_peerings=10)
    assert witness['peerings'] == 3
    assert witness['peerings_expected'] == 10
    assert witness['peerings_measured'] == 3
    assert witness['best_paths'] is None
    assert witness['imported_paths'] is None


def test_an_unstated_expectation_withholds_rather_than_weakens():
    '''A guard that quietly falls back is worse than one that refuses.'''
    witness = table_witness(TARGET_PROTOCOLS)
    assert witness['peerings_expected'] is None
    assert witness['best_paths'] is None


def test_an_unmeasured_peering_withholds_the_sums():
    '''A partial read looks exactly like a table that shrank, so refuse it.

    tester_offering()'s rule, and the reason it matters more here: this witness
    exists to be compared against a *declining* monitor count.
    '''
    witness = table_witness(TARGET_PROTOCOLS_ONE_SESSION_DOWN,
                            monitor_address='10.10.0.2', expected_peerings=3)
    assert witness['peerings'] == 3
    assert witness['peerings_measured'] == 2
    assert witness['best_paths'] is None
    assert witness['imported_paths'] is None
    # The session that was readable still is: the monitor is the one being
    # compared against, and dropping it with the sums would hide the comparison
    # for exactly the polls where a generator is still coming up.
    assert witness['exported_to_monitor'] == 100


def test_a_neighbor_range_listener_is_not_a_peering(fixture_text):
    '''`everything BGP ... Neighbor range: 10.0.0.0/8` is a listener.

    It sits Passive for the whole run and holds nothing, so counting it would
    make every dynamic-neighbour target withhold both sums forever.
    '''
    text = fixture_text('bird3_show_protocols_all.txt')
    # Three `dynbgp*` sessions plus the `everything` listener, which must not
    # be counted: including it would withhold every dynamic-neighbour sum
    # forever.
    witness = table_witness(text, expected_peerings=3)
    assert witness['peerings'] == 3
    assert witness['peerings_measured'] == 3
    assert witness['best_paths'] is not None


def test_a_gauge_is_not_a_counter():
    '''The counters already on the queue only rise, so they witness no loss.

    `Import updates accepted` is cumulative; `Routes: ... imported` is the
    table as it stands.  This target has received 190 updates and holds 190
    paths, and it is the second number that can fall.
    '''
    _, accepted = neighbors_state(TARGET_PROTOCOLS)
    assert sum(accepted.values()) == 190
    assert table_witness(TARGET_PROTOCOLS,
                         expected_peerings=3)['imported_paths'] == 190


# --- one CLI read serves both ----------------------------------------------

class _OneReadTarget(BIRDTarget):
    def __init__(self, text):
        self._text = text
        self.reads = 0
        self.scenario_global_conf = {
            'testers': [{'neighbors': {
                '10.10.0.3': {'check-points': 100},
                '10.10.0.4': {'check-points': 90}}}],
            'monitor': {'local-address': '10.10.0.2/16'},
        }

    def show_protocols(self):
        self.reads += 1
        return self._text


def test_one_sample_is_one_exec():
    '''Two reads would be two execs a second, and two different instants.'''
    target = _OneReadTarget(TARGET_PROTOCOLS)
    received_full, checked, witness = target.sample_target_state()
    assert target.reads == 1
    assert checked == {'10.10.0.3': True, '10.10.0.4': True}
    assert received_full == {'10.10.0.3': True, '10.10.0.4': True}
    assert witness['best_paths'] == 100
    assert witness['exported_to_monitor'] == 100
    # Two generator peers and the monitor, from the scenario -- not from what
    # BIRD happens to be showing.
    assert witness['peerings_expected'] == 3


def test_the_monitor_address_loses_its_prefix_length():
    '''Scenario addresses carry one; BIRD prints the bare address.'''
    target = _OneReadTarget(TARGET_PROTOCOLS)
    assert target.monitor_neighbor_address() == '10.10.0.2'


def test_a_target_with_no_monitor_has_no_address():
    target = _OneReadTarget(TARGET_PROTOCOLS)
    target.scenario_global_conf = {'testers': []}
    assert target.monitor_neighbor_address() is None


def test_a_daemon_with_no_gauge_reports_none_rather_than_zero():
    '''Absence has to stay distinguishable from a target holding nothing.'''
    assert Target.get_table_witness(object.__new__(Target)) is None


# --- the artifact section --------------------------------------------------

# The shape bgperf2-dcs is about, one order of magnitude down: the count
# overshoots while generators are still finishing, then settles.
OVERSHOOT_SAMPLES = [
    {'monotonic_s': 1.0, 'witness_age_s': 0.1, 'monitor_accepted': 900,
     'best_paths': 900, 'imported_paths': 1800, 'exported_to_monitor': 900},
    {'monotonic_s': 2.0, 'witness_age_s': 0.1, 'monitor_accepted': 1000,
     'best_paths': 1000, 'imported_paths': 4000, 'exported_to_monitor': 1000},
    {'monotonic_s': 3.0, 'witness_age_s': 0.2, 'monitor_accepted': 985,
     'best_paths': 985, 'imported_paths': 6000, 'exported_to_monitor': 985},
]


def test_the_section_keeps_every_sample():
    '''A number whose inputs are gone is not auditable -- summary.py's rule.'''
    section = target_table_section(OVERSHOOT_SAMPLES)
    assert section['samples'] == OVERSHOOT_SAMPLES


def test_decline_is_measured_from_the_peak():
    '''The comparison ConvergenceTracker makes, and the one that fails runs.'''
    series = target_table_section(OVERSHOOT_SAMPLES)['series']
    assert series['monitor_accepted']['peak'] == 1000
    assert series['monitor_accepted']['final'] == 985
    assert series['monitor_accepted']['decline_from_peak'] == 0.015
    # Paths held only rose while the prefix count fell -- which is the pair the
    # next change set has to reason about.
    assert series['imported_paths']['decline_from_peak'] == 0.0


def test_a_series_nobody_could_read_is_absent():
    samples = [dict(s, exported_to_monitor=None) for s in OVERSHOOT_SAMPLES]
    series = target_table_section(samples)['series']
    assert 'exported_to_monitor' not in series
    assert series['best_paths']['observations'] == 3


def test_one_unreadable_poll_does_not_end_the_series():
    '''It leaves that sample None; the rest are still observations.'''
    samples = list(OVERSHOOT_SAMPLES)
    samples[1] = dict(samples[1], best_paths=None)
    series = target_table_section(samples)['series']
    assert series['best_paths']['observations'] == 2
    assert series['best_paths']['peak'] == 985


def _converged_events():
    return [
        LifecycleEvent(kind=EventKind.BENCH_CLOCK_STARTED, monotonic_s=0.0,
                       phase=EventPhase.SETUP, producer='controller'),
        LifecycleEvent(kind=EventKind.MONITOR_FIRST_PREFIX, monotonic_s=1.0,
                       phase=EventPhase.CONVERGENCE, producer='monitor'),
    ]


def test_a_run_with_no_witness_keeps_the_document_it_always_had():
    assert 'target_table' not in event_artifact(_converged_events(),
                                                'converged')
    assert 'target_table' not in event_artifact(_converged_events(),
                                                'converged', target_table=[])


def test_a_run_with_a_witness_publishes_it():
    artifact = event_artifact(_converged_events(), 'converged',
                              target_table=OVERSHOOT_SAMPLES)
    assert artifact['target_table']['series']['best_paths']['final'] == 985
    assert len(artifact['target_table']['samples']) == 3


def test_each_series_says_when_it_was_last_read():
    """Two windows compared as one is the failure this guards.

    The target's sums are withheld on any poll where a session was not
    reporting, so a peer dropping near the end truncates the target series
    while `monitor_accepted` -- which is never withheld -- runs on. A
    `decline_from_peak` read across those two windows compares different runs.
    """
    samples = list(OVERSHOOT_SAMPLES)
    samples[2] = dict(samples[2], best_paths=None, imported_paths=None,
                      exported_to_monitor=None)
    series = target_table_section(samples)['series']
    assert series['monitor_accepted']['final_monotonic_s'] == 3.0
    assert series['best_paths']['final_monotonic_s'] == 2.0


def test_a_frozen_witness_is_visible_as_age():
    """A dead target poll thread otherwise reads as a perfectly stable table.

    `Container.neighbor_stats()` has no guard around its exec, so one transient
    failure ends the thread; every later monitor sample then repeats the last
    reading, and `decline_from_peak` becomes 0.0 for a target nobody asked.
    """
    samples = [dict(s) for s in OVERSHOOT_SAMPLES]
    for i, sample in enumerate(samples[1:], start=1):
        sample.update(best_paths=900, imported_paths=1800,
                      exported_to_monitor=900, witness_age_s=float(i) * 30)
    series = target_table_section(samples)['series']
    assert series['best_paths']['decline_from_peak'] == 0.0
    assert series['best_paths']['max_witness_age_s'] == 60.0
    # The monitor reads its own count on the poll it is recorded with, so
    # staleness is not a property it can have.
    assert series['monitor_accepted']['max_witness_age_s'] is None


def test_a_target_that_could_answer_and_did_not_says_so():
    """Otherwise it produces the artifact of a daemon with no gauge at all."""
    reason = target_table_unmeasured(_OneReadTarget(TARGET_PROTOCOLS), [])
    assert reason
    artifact = event_artifact(_converged_events(), 'converged',
                              target_table=[],
                              target_table_unmeasured_reason=reason)
    assert artifact['target_table']['unmeasured_reason'] == reason
    assert artifact['target_table']['series'] == {}


def test_a_daemon_with_no_gauge_gets_no_reason_and_no_section():
    """The document every non-BIRD run has always written, unchanged."""
    assert target_table_unmeasured(object.__new__(Target), []) is None


def test_a_target_that_answered_needs_no_reason():
    assert target_table_unmeasured(_OneReadTarget(TARGET_PROTOCOLS),
                                   OVERSHOOT_SAMPLES) is None


# --- the rule the witness feeds -------------------------------------------

def test_a_run_the_rule_never_touched_publishes_no_rule():
    '''Absent rather than a rule that did not fire, so it stays legible that
    this is not a filter every run passes through.'''
    artifact = event_artifact(_converged_events(), 'converged',
                              target_table=OVERSHOOT_SAMPLES)
    assert 'witness_rule' not in artifact['target_table']


def test_the_rule_that_decided_a_run_is_published_beside_its_evidence():
    tracker = ConvergenceTracker()
    tracker.note_neighbors_checkpoint()
    for i, sample in enumerate(OVERSHOOT_SAMPLES):
        tracker.update(i, sample['monitor_accepted'], 2, 2, True,
                       table_witness={'best_paths': 1000},
                       witness_monotonic_s=float(i))
    rule = tracker.witness_rule()
    assert rule['excused_samples'] == 1
    artifact = event_artifact(_converged_events(), 'converged',
                              target_table=OVERSHOOT_SAMPLES,
                              target_table_witness_rule=rule)
    section = artifact['target_table']
    assert section['witness_rule'] == rule
    # The rule's own account sits beside the series it was applied to, so a
    # reader can check one against the other.
    assert section['series']['monitor_accepted']['decline_from_peak'] == 0.015
