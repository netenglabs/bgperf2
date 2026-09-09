'''The campaign's acceptance rules, applied to a run's published documents.

`scripts/check_timing_evidence.py` is what decides whether a block's rows may
support the 64 GB campaign's version comparisons. It is the only instrument
between "the batch exited 0" and "these fourteen rows are comparable", and the
failures it exists to catch are quiet ones: a role whose version came back
UNKNOWN, a generator that never reported completion, a row written by a build
that did not record which bgperf2 measured it.
'''
import importlib.util
import sys

import pytest

from conftest import REPO_ROOT

spec = importlib.util.spec_from_file_location(
    'check_timing_evidence', REPO_ROOT / 'scripts' / 'check_timing_evidence.py')
check = importlib.util.module_from_spec(spec)
sys.modules['check_timing_evidence'] = check
spec.loader.exec_module(check)


def artifact(**overrides):
    doc = {
        'bgperf2': {'revision': 'abc123',
                    'event_schema': 'bgperf2/measurement-events/v1alpha1',
                    'findings_schema': 'bgperf2/measurement-findings/v1alpha1',
                    'findings_policy': 'conservative/v1'},
        'status': 'converged',
        'run': {'name': 'bird 2.19.2', 'repetition': None, 'peers': 4,
                'prefixes_per_peer': 10000, 'tester_type': 'bird',
                'path_diversity': 1},
        'events': [
            {'event': 'bench_clock_started', 'monotonic_s': 0.0},
            {'event': 'tester_session_ready', 'monotonic_s': 1.0},
            {'event': 'monitor_first_prefix', 'monotonic_s': 1.5},
            {'event': 'monitor_required_reached', 'monotonic_s': 3.0},
            {'event': 'convergence_confirmed', 'monotonic_s': 8.0},
        ],
        'tester_fleet': {'testers': 1, 'testers_complete': 1,
                         'incomplete_testers': [], 'offered_prefixes': 40000},
        'findings': {'limiting_component': 'unresolved',
                     'decided_by': 'injection_boundary_unresolved',
                     'findings': []},
    }
    doc.update(overrides)
    return doc


def versions(**overrides):
    doc = {
        'target': {'daemon': 'bird', 'version': '2.19.2',
                   'image': 'bgperf/bird:2.19.2'},
        'monitor': {'daemon': 'gobgp', 'version': '4.9.0',
                    'image': 'bgperf/gobgp:latest'},
        'testers': [{'daemon': 'bird', 'version': '2.19.0', 'count': 1,
                     'image': 'bgperf/bird:latest'}],
    }
    doc.update(overrides)
    return doc


def row(**overrides):
    doc = {
        'name': 'bird 2.19.2', 'required': '39600', 'received': '40000',
        'elapsed (s)': '8', 'total time': '30.1', 'tester errors': '0',
        'tester timeouts': '0', 'failed': '', 'MSG': '',
        'max foreign cpu %': '4', 'min free mem (GB)': '55.0',
        'Mem (GB)': '61.44GB',
    }
    doc.update(overrides)
    return doc


def statuses(checks):
    return {c.name: c.status for c in checks}


def test_a_complete_run_qualifies():
    verdict, checks = check.qualify(artifact(), versions(), row())
    assert verdict == 'qualified', statuses(checks)


def test_a_run_that_cannot_name_the_build_that_measured_it_is_rejected():
    '''Every published number here came from timing code that changed under
    these daemons over the measurement plan's phases; without the revision the
    row cannot be tied to any of them.'''
    verdict, checks = check.qualify(artifact(bgperf2={}), versions(), row())
    assert verdict == 'rejected'
    assert statuses(checks)['tool_provenance'] == check.FAIL


def test_an_unknown_role_version_is_rejected_not_reported_as_a_version():
    '''`version_string()` returns a string starting UNKNOWN rather than
    guessing, and a row whose tester cannot be identified cannot be compared
    with one whose tester can -- the exabgp/gcov trap.'''
    bad = versions(testers=[{'daemon': 'exabgp', 'count': 1,
                             'version': 'UNKNOWN (no version command)',
                             'image': 'bgperf/exabgp:latest'}])
    verdict, checks = check.qualify(artifact(), bad, row())
    assert verdict == 'rejected'
    assert statuses(checks)['role_provenance'] == check.FAIL


def test_a_run_with_no_testers_recorded_is_rejected():
    verdict, checks = check.qualify(artifact(), versions(testers=[]), row())
    assert verdict == 'rejected'
    assert statuses(checks)['role_provenance'] == check.FAIL


def test_a_failed_row_is_rejected_even_when_the_artifact_looks_whole():
    verdict, checks = check.qualify(
        artifact(status='failed'), versions(),
        row(failed='FAILED', MSG='FAILED: dropping received count'))
    assert verdict == 'rejected'
    assert statuses(checks)['status'] == check.FAIL
    assert statuses(checks)['stats_row'] == check.FAIL


def test_an_artifact_with_no_row_is_rejected():
    '''A run whose CSV row is missing has no host evidence at all, and the
    campaign's contention and memory rules are applied to that row.'''
    verdict, checks = check.qualify(artifact(), versions(), None)
    assert verdict == 'rejected'
    assert statuses(checks)['stats_row'] == check.FAIL
    assert statuses(checks)['host_evidence'] == check.FAIL


def test_an_incomplete_fleet_is_rejected_and_names_the_generator():
    fleet = {'testers': 10, 'testers_complete': 9,
             'incomplete_testers': ['bgperf_bgpdump2_tester_mrt-injector7'],
             'offered_prefixes': 900000}
    verdict, checks = check.qualify(artifact(tester_fleet=fleet), versions(),
                                    row())
    assert verdict == 'rejected'
    detail = next(c.detail for c in checks if c.name == 'tester_evidence')
    assert 'mrt-injector7' in detail


def test_a_synthetic_run_that_offered_the_wrong_table_is_rejected():
    '''bgperf2 generated those prefix lists, so the count is knowable here --
    unlike an MRT injector, which replays whatever its peer's table holds.'''
    fleet = {'testers': 1, 'testers_complete': 1, 'incomplete_testers': [],
             'offered_prefixes': 39000}
    verdict, checks = check.qualify(artifact(tester_fleet=fleet), versions(),
                                    row())
    assert verdict == 'rejected'
    assert statuses(checks)['offered_count'] == check.FAIL


def test_an_mrt_runs_offered_count_is_evidence_not_a_target():
    doc = artifact()
    doc['run'] = dict(doc['run'], tester_type='bgpdump2')
    doc['tester_fleet'] = {'testers': 2, 'testers_complete': 2,
                           'incomplete_testers': [],
                           'offered_prefixes': 17777}
    verdict, checks = check.qualify(doc, versions(), row())
    assert verdict == 'qualified', statuses(checks)
    assert 'offered_count' not in statuses(checks)


def test_events_out_of_order_are_rejected():
    doc = artifact()
    doc['events'] = [
        {'event': 'bench_clock_started', 'monotonic_s': 0.0},
        {'event': 'monitor_required_reached', 'monotonic_s': 3.0},
        {'event': 'monitor_first_prefix', 'monotonic_s': 1.5},
        {'event': 'convergence_confirmed', 'monotonic_s': 8.0},
    ]
    verdict, checks = check.qualify(doc, versions(), row())
    assert verdict == 'rejected'
    assert statuses(checks)['event_order'] == check.FAIL


def test_a_missing_required_event_is_rejected():
    doc = artifact()
    doc['events'] = [e for e in doc['events']
                     if e['event'] != 'convergence_confirmed']
    verdict, checks = check.qualify(doc, versions(), row())
    assert verdict == 'rejected'
    assert statuses(checks)['event_coverage'] == check.FAIL


def test_foreign_cpu_contention_rejects_the_row():
    verdict, checks = check.qualify(artifact(), versions(),
                                    row(**{'max foreign cpu %': '180'}))
    assert verdict == 'rejected'
    assert statuses(checks)['contention'] == check.FAIL


def test_a_runs_own_contention_finding_rejects_it_even_below_the_column():
    '''The artifact's finding was decided when the run happened, with the
    competitor still named; the column alone is the weaker of the two.'''
    doc = artifact()
    doc['findings'] = dict(doc['findings'], findings=[
        {'finding': 'foreign_cpu_contention', 'kind': 'confounder'}])
    verdict, checks = check.qualify(doc, versions(),
                                    row(**{'max foreign cpu %': '20'}))
    assert verdict == 'rejected'
    assert statuses(checks)['contention'] == check.FAIL


def test_the_campaign_memory_guardrail_is_twenty_percent_not_findings_five():
    '''findings.py withholds a verdict below 5% free -- a statement about the
    timings. The campaign guardrail is 20% -- a statement about whether the
    host is safe to keep running blocks on.'''
    assert check.CAMPAIGN_FREE_MEMORY_FRACTION == 0.20
    verdict, checks = check.qualify(artifact(), versions(),
                                    row(**{'min free mem (GB)': '10.0'}))
    assert verdict == 'rejected'
    assert statuses(checks)['memory_guardrail'] == check.FAIL

    verdict, checks = check.qualify(artifact(), versions(),
                                    row(**{'min free mem (GB)': '13.0'}))
    assert verdict == 'qualified', statuses(checks)


def test_unresolved_and_inconclusive_are_answers_not_failures():
    for component in ('tester', 'target_or_monitor', 'unresolved',
                      'inconclusive'):
        doc = artifact()
        doc['findings'] = dict(doc['findings'], limiting_component=component)
        verdict, checks = check.qualify(doc, versions(), row())
        assert verdict == 'qualified', (component, statuses(checks))


def test_a_missing_findings_section_is_rejected():
    doc = artifact()
    del doc['findings']
    verdict, checks = check.qualify(doc, versions(), row())
    assert verdict == 'rejected'
    assert statuses(checks)['findings'] == check.FAIL


def test_the_row_is_found_by_the_name_the_run_recorded():
    '''run_name() already carries the repetition suffix. Appending it again
    matched no row and read as a missing row rather than as a bad key.'''
    doc = artifact()
    doc['run'] = dict(doc['run'], name='bird 2.19.2 #2', repetition=2)
    assert check.row_name_for(doc) == 'bird 2.19.2 #2'


def test_a_short_row_costs_its_own_run_and_is_named_as_such(tmp_path):
    '''--resume onto a progress file written before a column was appended is a
    supported path; indexing a short row against the current header is the
    failure summary.py calls `unreadable`.'''
    csv_path = tmp_path / 'x.csv'
    csv_path.write_text('name, required, received, failed\n'
                        'bird 2.19.2, 10\n')
    rows = check.load_rows(str(csv_path))
    assert '__short_row__' in rows['bird 2.19.2']
    verdict, checks = check.qualify(artifact(), versions(),
                                    rows['bird 2.19.2'])
    assert verdict == 'rejected'
    assert statuses(checks)['stats_row'] == check.FAIL


def test_reading_a_directory_of_runs_reports_a_shortfall(tmp_path):
    '''A block that produced fewer runs than it should have looks exactly like
    a block nobody looked for the rest of.'''
    import json
    (tmp_path / 'a.events.json').write_text(json.dumps(artifact()))
    (tmp_path / 'a.versions.json').write_text(json.dumps(versions()))
    header = ','.join(row().keys())
    values = ','.join(row().values())
    (tmp_path / 'b.csv').write_text(header + '\n' + values + '\n')

    assert check.main([str(tmp_path)]) == 0
    assert check.main([str(tmp_path), '--expect', '2']) == 1


def test_an_empty_directory_is_a_failure_not_a_clean_bill(tmp_path):
    assert check.main([str(tmp_path)]) == 1


def test_path_diversity_does_not_multiply_the_configured_table():
    """`gen_conf()` gives every neighbour `p` paths whatever the diversity;
    only the monitor's check-point is divided into groups. Multiplying here
    rejected every correct diversity row, which is Block 8's whole synthetic
    screen."""
    doc = artifact()
    doc['run'] = dict(doc['run'], path_diversity=2)
    verdict, checks = check.qualify(doc, versions(), row())
    assert verdict == 'qualified', statuses(checks)
    assert statuses(checks)['offered_count'] == check.OK


def test_an_unsampled_memory_sentinel_is_not_a_measurement():
    """`min_free` starts above every real value, and `free` raising kills that
    sampler while the run goes on -- so an untouched sentinel reaches the row
    as ~931,322 GB and clears any guardrail there is."""
    verdict, checks = check.qualify(
        artifact(), versions(), row(**{'min free mem (GB)': '931322.575'}))
    assert verdict == 'rejected'
    assert statuses(checks)['memory_guardrail'] == check.FAIL
    detail = next(c.detail for c in checks if c.name == 'memory_guardrail')
    assert 'sentinel' in detail


def calibrated(doc, expect_limiting=None, expect_mbit=None, tolerance=0.25):
    return check.qualify(doc, versions(), row(), expect_limiting, expect_mbit,
                         tolerance)


def injectors(zero_mbit=4.0, one_mbit=4.0):
    '''Two generators whose published numbers give the named wire rates.'''
    return {
        'mrt-injector0': {'octets_on_wire': int(zero_mbit * 1e6 / 8.0),
                          'reported_injection_s': 1.0},
        'mrt-injector1': {'octets_on_wire': int(one_mbit * 1e6 / 8.0),
                          'reported_injection_s': 1.0},
    }


def test_a_calibration_case_that_produced_its_component_qualifies():
    doc = artifact()
    doc['findings'] = dict(doc['findings'], limiting_component='tester',
                           decided_by='tester_limited')
    verdict, checks = calibrated(doc, expect_limiting=['tester'])
    assert verdict == 'qualified', statuses(checks)
    assert statuses(checks)['expected_limiting'] == check.OK


def test_a_calibration_case_that_produced_another_component_is_rejected():
    '''The whole point of starving one role is that the policy has to name it;
    a case that named something else calibrated nothing.'''
    doc = artifact()
    doc['findings'] = dict(doc['findings'], limiting_component='tester')
    verdict, checks = calibrated(doc, expect_limiting=['target_or_monitor'])
    assert verdict == 'rejected'
    assert statuses(checks)['expected_limiting'] == check.FAIL


def test_an_unconstrained_control_may_decline_to_name_a_component_either_way():
    '''`unresolved` and `inconclusive` are kept apart everywhere else -- one is
    a measurement that forbids attribution, the other a measurement never made
    -- and both are correct where nothing was constrained.'''
    for component in ('unresolved', 'inconclusive'):
        doc = artifact()
        doc['findings'] = dict(doc['findings'], limiting_component=component)
        verdict, checks = calibrated(
            doc, expect_limiting=['unresolved', 'inconclusive'])
        assert verdict == 'qualified', (component, statuses(checks))


def test_a_control_that_named_a_component_is_rejected():
    doc = artifact()
    doc['findings'] = dict(doc['findings'], limiting_component='tester')
    verdict, checks = calibrated(doc,
                                 expect_limiting=['unresolved',
                                                  'inconclusive'])
    assert verdict == 'rejected'


def test_an_imposed_rate_is_recovered_from_the_generators_own_numbers():
    doc = artifact(testers=injectors(4.16, 3.95))
    verdict, checks = calibrated(doc, expect_mbit=4.0)
    assert verdict == 'qualified', statuses(checks)
    assert statuses(checks)['generator_egress'] == check.OK


def test_a_constraint_that_bound_nothing_is_rejected_on_the_rate_alone():
    '''`tc` succeeding is not the traffic being shaped: it once succeeded on a
    device the BGP session did not use, and the run was logged as controlled.
    At a size where the unconstrained shape is already generator-bound, the
    verdict would have cleared it.'''
    doc = artifact(testers=injectors(69.1, 65.3))
    doc['findings'] = dict(doc['findings'], limiting_component='tester')
    verdict, checks = calibrated(doc, expect_limiting=['tester'],
                                 expect_mbit=4.0)
    assert verdict == 'rejected'
    assert statuses(checks)['expected_limiting'] == check.OK
    assert statuses(checks)['generator_egress'] == check.FAIL


def test_one_unshaped_generator_of_two_rejects_the_case_and_is_named():
    doc = artifact(testers=injectors(4.16, 65.3))
    verdict, checks = calibrated(doc, expect_mbit=4.0)
    assert verdict == 'rejected'
    detail = [c.detail for c in checks if c.name == 'generator_egress'][0]
    assert 'mrt-injector1' in detail
    assert 'mrt-injector0' not in detail.split('outside')[1]


def test_a_rate_that_cannot_be_recovered_at_all_is_rejected_not_skipped():
    '''A generator with no wire-side count leaves an imposed cap unverifiable,
    which is not the same as a cap that held.'''
    verdict, checks = calibrated(artifact(), expect_mbit=4.0)
    assert verdict == 'rejected'
    assert statuses(checks)['generator_egress'] == check.FAIL


def test_an_unconstrained_companions_rate_is_published_and_never_asserted():
    '''It is the reference the constrained run is read against, and a number
    nobody recorded cannot play that part later.'''
    doc = artifact(testers=injectors(69.1, 65.3))
    verdict, checks = calibrated(doc)
    assert verdict == 'qualified', statuses(checks)
    assert statuses(checks)['generator_egress'] == check.NOTE


def test_a_generator_that_timed_its_own_send_at_zero_resolves_no_rate():
    '''Dividing by it would raise in the middle of qualifying a block.'''
    doc = artifact(testers={'mrt-injector0': {'octets_on_wire': 1000,
                                              'reported_injection_s': 0.0}})
    verdict, checks = calibrated(doc)
    assert verdict == 'qualified', statuses(checks)
    assert 'generator_egress' not in statuses(checks)


def test_an_ordinary_run_is_unaffected_by_the_calibration_options():
    verdict, checks = check.qualify(artifact(), versions(), row())
    assert verdict == 'qualified', statuses(checks)
    assert 'expected_limiting' not in statuses(checks)
    assert 'generator_egress' not in statuses(checks)


def test_a_generator_that_published_no_rate_cannot_be_dropped_from_the_case():
    '''Both numbers are withheld rather than guessed, so a generator missing
    one is a generator this case has no evidence about. Cleared on the two
    that answered, the case would be qualified while a third ran unshaped.'''
    doc = artifact(testers=dict(injectors(4.16, 3.95),
                                **{'mrt-injector2': {'octets_on_wire': None,
                                                     'reported_injection_s':
                                                     12.0}}))
    verdict, checks = calibrated(doc, expect_mbit=4.0)
    assert verdict == 'rejected'
    detail = [c.detail for c in checks if c.name == 'generator_egress'][0]
    assert 'no recoverable rate: mrt-injector2' in detail


def test_a_case_with_no_generator_section_cannot_recover_an_imposed_rate():
    verdict, checks = calibrated(artifact(testers={}), expect_mbit=4.0)
    assert verdict == 'rejected'
    assert 'no generator section' in [c.detail for c in checks
                                      if c.name == 'generator_egress'][0]


def test_a_passing_rate_check_says_how_many_generators_it_covered():
    '''"within 4%" over one injector of ten is the reading this whole check
    exists to refuse.'''
    doc = artifact(testers=injectors(4.16, 3.95))
    _, checks = calibrated(doc, expect_mbit=4.0)
    assert 'all 2 generators' in [c.detail for c in checks
                                  if c.name == 'generator_egress'][0]
