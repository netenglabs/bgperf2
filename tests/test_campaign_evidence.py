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


def test_a_memory_column_is_converted_by_its_unit_not_stripped_of_it():
    '''`Mem (GB)` is written by `mem_human()`, which picks its unit from the
    value: GB above a gibibyte, then MB, KB and a bare B below. Stripping only
    the `GB` suffix left `total` as None on any smaller host, and the guardrail
    then failed the row for "does not carry both free and total memory" --
    diagnosing a missing column that was present and populated. A unit dropped
    rather than applied is worse than one that is not understood.'''
    assert check._row_float({'c': '61.44GB'}, 'c') == pytest.approx(61.44)
    assert check._row_float({'c': '61.44gb'}, 'c') == pytest.approx(61.44)
    assert check._row_float({'c': '512.00MB'}, 'c') == pytest.approx(0.5)
    assert check._row_float({'c': '1024.00KB'}, 'c') == pytest.approx(1.0 / 1024)
    assert check._row_float({'c': '1.00B'}, 'c') == pytest.approx(1.0 / 1024 ** 3)
    # bare numbers and absent values are unchanged
    assert check._row_float({'c': '2.5'}, 'c') == pytest.approx(2.5)
    assert check._row_float({'c': ''}, 'c') is None
    assert check._row_float({}, 'c') is None
    assert check._row_float({'c': 'not a number'}, 'c') is None


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


def test_a_monitor_that_missed_reads_rejects_the_row():
    '''The monitor is the instrument every published timing is derived from, so
    a gap in its 1-second series is a gap under `elapsed (s)`, `first_prefix_s`
    and `convergence_s` alike. Surviving the bad read is what keeps the run
    alive; it is not what makes the row comparable.'''
    art = artifact()
    art['instrument'] = {'monitor': {'failed_reads': 3,
                                     'last_error': 'MonitorReadError: rpc error'}}
    verdict, checks = check.qualify(art, versions(), row())
    assert verdict == 'rejected'
    assert statuses(checks)['instrument_reads'] == check.FAIL


def test_a_target_sampler_gap_is_a_note_not_a_rejection():
    '''It costs the neighbour checkpoint, which moves the assurance window from
    5 samples to 20 and lengthens the run -- without corrupting the timings the
    row publishes.'''
    art = artifact()
    art['instrument'] = {'target_neighbor_sampler': {
        'failed_reads': 2, 'last_error': 'TypeError: string indices'}}
    verdict, checks = check.qualify(art, versions(), row())
    assert verdict == 'qualified'
    assert statuses(checks)['instrument_reads'] == check.NOTE


def test_an_artifact_with_no_instrument_section_is_not_a_failure():
    '''Absent means "no failures recorded", and every artifact written before
    the section existed also looks like that. A checker that manufactured a
    failure from silence would reject every older run.'''
    verdict, checks = check.qualify(artifact(), versions(), row())
    assert verdict == 'qualified'
    assert statuses(checks)['instrument_reads'] == check.OK


def test_a_rejection_quotes_the_line_behind_the_count():
    '''The count alone sends a reviewer to logs that no longer exist: bench()
    rmtree's the work directory at the start of the next cell, and a re-run
    wipes them identically, so a rejected row could be neither diagnosed nor
    usefully re-measured. Block 4 of the 64 GB campaign lost two rows that way.
    '''
    health = {'error_samples': [{'source': 'tester0', 'log': 'bgpdump2.log',
                                 'line': 412,
                                 'text': '<RMT> Received: Cease'}],
              'timeout_samples': []}
    detail = check.describe_tester_health(health, 2, 0)
    assert '2 tester errors, 0 timeouts' in detail
    # The tester is named, not just the file: every MRT injector writes the
    # same `bgpdump2.log` inside its own host directory.
    assert 'tester0/bgpdump2.log:412' in detail
    assert 'Cease' in detail


def test_a_missing_capture_states_the_fact_and_not_a_cause():
    '''A missing file has at least three causes -- an older build, a writer
    that swallowed an exception, and a `-r/--repeat` run that scans nothing --
    and this text is the durable record a later session reads. Naming one of
    them would record a run whose evidence was lost as a run from an old build.
    '''
    detail = check.describe_tester_health(None, 2, 0)
    assert 'no captured lines available' in detail
    assert 'predates' not in detail


def test_a_bounded_capture_says_how_many_it_speaks_for():
    '''The count is the authority; the capture is capped, so the first line
    must not be allowed to stand for all of them.'''
    health = {'error_samples': [{'source': 't', 'log': 'a.log', 'line': i,
                                 'text': 'x'} for i in range(3)],
              'timeout_samples': []}
    assert 'first of 3 captured error line(s)' in check.describe_tester_health(
        health, 500, 0)


def test_the_quoted_line_and_its_count_come_from_the_same_list():
    '''Summing the two lists and quoting the first error renders "first of 20
    captured" for a run with one error and nineteen timeouts, which reads as
    twenty captures backing the single line shown.'''
    health = {'error_samples': [{'source': 't', 'log': 'a.log', 'line': 1,
                                 'text': 'the one error'}],
              'timeout_samples': [{'source': 't', 'log': 'a.log', 'line': i,
                                   'text': 'timeout'} for i in range(19)]}
    detail = check.describe_tester_health(health, 1, 19)
    assert 'first of 1 captured error line(s)' in detail
    assert 'the one error' in detail


def test_a_timeout_only_capture_is_quoted_as_a_timeout():
    health = {'error_samples': [],
              'timeout_samples': [{'source': 't', 'log': 'a.log', 'line': 4,
                                   'text': 'session timeout'}]}
    detail = check.describe_tester_health(health, 0, 1)
    assert 'first of 1 captured timeout line(s)' in detail
    assert 'session timeout' in detail


def test_a_clean_row_is_not_described_by_this_at_all():
    '''tester_health only reaches the describer on a nonzero count.'''
    verdict, checks = check.qualify(artifact(), versions(), row())
    assert statuses(checks)['tester_health'] == check.OK


def test_a_malformed_capture_costs_its_own_row_and_not_the_block():
    """The module degrades per run everywhere else -- load_json swallows a
    parse error and an unreadable artifact becomes one `unreadable` verdict.
    An exception here escapes main() and costs every other run its verdict."""
    for bad in ({'error_samples': 'not a list', 'timeout_samples': []},
                {'error_samples': ['not a dict'], 'timeout_samples': []},
                {'error_samples': None, 'timeout_samples': None},
                {}):
        detail = check.describe_tester_health(bad, 1, 0)
        assert '1 tester errors' in detail


def test_a_repeat_run_is_not_offered_as_a_cause():
    """It builds no tester objects, so nothing is scanned *and* nothing is
    counted: the row reports zero and this is never reached. Naming it would
    send a reviewer of a genuinely lost capture down a cause that cannot
    produce the state they are looking at."""
    assert 'repeat' not in check.describe_tester_health(None, 2, 0)
    assert 'repeat' not in (check.describe_tester_health.__doc__ or '').split(
        '(`-r/--repeat` is not a third cause')[0]


def test_a_trimmed_line_is_not_quoted_as_a_complete_one():
    '''The writer trims at 300 characters and records that it did. By review
    time this text is the evidence -- the log is gone -- so a cut line shown
    without a mark reads as the whole message.'''
    health = {'error_samples': [{'source': 't', 'log': 'a.log', 'line': 1,
                                 'text': '<RMT> Received: NOTIFICATION ' + 'x' * 270,
                                 'truncated': True}],
              'timeout_samples': []}
    assert '[trimmed]' in check.describe_tester_health(health, 1, 0)


def test_an_untrimmed_line_is_not_marked():
    health = {'error_samples': [{'source': 't', 'log': 'a.log', 'line': 1,
                                 'text': 'short', 'truncated': False}],
              'timeout_samples': []}
    assert '[trimmed]' not in check.describe_tester_health(health, 1, 0)


def test_a_blank_matched_line_says_so():
    '''Reachable: the MRT and bgpdump2 needles are bare substrings, so a blank
    line can match. A dangling "a.log:1: " reads as a formatting fault.'''
    health = {'error_samples': [{'source': 't', 'log': 'a.log', 'line': 1,
                                 'text': '   ', 'truncated': False}],
              'timeout_samples': []}
    detail = check.describe_tester_health(health, 1, 0)
    assert '(blank line)' in detail
    assert not detail.rstrip().endswith(':')


def _mrt(exported=None, received='961201', required='1039500', imported=39800):
    """An MRT run's artifact and row, optionally carrying a table witness.

    `imported` defaults to just under the fleet's offered count, because a
    daemon that publishes an export witness publishes an import one too -- both
    come off the same read, for BIRD and for FRR alike. A row below the
    check-point with neither is a row nothing can vouch for, which is its own
    test below.
    """
    doc = artifact(run={'name': 'frr_c 10.7', 'repetition': None, 'peers': 10,
                        'prefixes_per_peer': 1050000,
                        'tester_type': 'bgpdump2', 'path_diversity': 1})
    series = {}
    if exported is not None:
        series['exported_to_monitor'] = {'final': exported}
        if imported is not None:
            series['imported_paths'] = {'final': imported}
    if series:
        doc['target_table'] = {'series': series}
    return doc, row(name='frr_c 10.7', received=received, required=required)


def test_an_mrt_shortfall_against_the_check_point_is_not_route_loss():
    '''`required` is `0.99 * -p` for an MRT injector -- the per-injector cap,
    not the size of a union nobody can know in advance -- and daemons
    legitimately advertise different shares of one RIB. Measured on the same
    file: RustyBGP 1,081,178, BIRD and OpenBGPD 1,056,779, every FRR release
    ~961,000. Judged against one absolute, every FRR row is rejected and the
    rest pass, which says nothing about FRR.'''
    doc, r = _mrt(exported=961201)
    verdict, checks = check.qualify(doc, versions(), r)
    assert statuses(checks)['route_counts'] == check.OK
    assert verdict == 'qualified', statuses(checks)


def test_an_mrt_row_reports_the_share_of_its_table_it_exported():
    """Nothing else in a qualifying MRT row bounds this.

    The import floor bounds ingress (accepted paths against offered paths) and
    the consistency check bounds the link (the monitor's count against the
    target's own `pfxSnt`, two ends of one link that agree at any size). What
    neither touches is the target's own decision about what to advertise -- so a
    daemon importing a whole RIB and exporting half of it clears both, and since
    a resolved `delivery` can stand in for `monitor_required_reached`, the
    check-point no longer bounds it either.
    """
    doc, r = _mrt(exported=1056779, received='1056779')
    doc['target_table']['series']['best_paths'] = {'final': 1080985}
    verdict, checks = check.qualify(doc, versions(), r)
    share = [c for c in checks if c.name == 'export_share']
    assert len(share) == 1
    assert share[0].status == check.NOTE
    assert '97.76%' in share[0].detail
    assert verdict == 'qualified', statuses(checks)


def test_an_export_share_with_no_denominator_is_named_rather_than_omitted():
    """The daemon that most needs this bound is the one that cannot supply it.

    `frr.table_witness()` withholds `best_paths` on purpose -- `ribCount` and
    `show bgp ipv4 unicast statistics` disagreed and neither was established to
    mean "prefixes holding a selected best path" -- and every row accepted
    through the `delivery` substitution today is an `frr_c` row. An omitted
    check reads as a check that passed, so the row says out loud that nothing in
    its own artifact bounds its export share.
    """
    doc, r = _mrt(exported=961201)
    assert 'best_paths' not in doc['target_table']['series']
    verdict, checks = check.qualify(doc, versions(), r)
    share = [c for c in checks if c.name == 'export_share']
    assert len(share) == 1
    assert share[0].status == check.NOTE
    assert 'no best-path gauge' in share[0].detail
    assert verdict == 'qualified', statuses(checks)


def test_a_best_path_gauge_reporting_zero_is_broken_rather_than_absent():
    """Absent and zero are different findings, and this repo has had the zero.

    `bird.parse_protocols()` read a BIRD 3 stats table positionally, BIRD 3
    inserted two columns, and every BIRD 3 target reported its counter as 0 --
    silently, because nothing compared it with anything. A target cannot export
    prefixes it does not hold, so reporting both is a broken gauge, not a
    daemon without one; calling it absent would send the reader to FRR's
    deliberate withholding instead of to a parser. Failed rather than noted,
    unlike the absent case: this is the gauge `ConvergenceTracker`'s fourth rule
    reads to excuse a monitor decline, and a wrong witness is worse than none.
    """
    doc, r = _mrt(exported=1056779, received='1056779')
    doc['target_table']['series']['best_paths'] = {'final': 0}
    verdict, checks = check.qualify(doc, versions(), r)
    share = [c for c in checks if c.name == 'export_share']
    assert len(share) == 1
    assert share[0].status == check.FAIL
    assert 'broken rather than absent' in share[0].detail
    assert verdict == 'rejected'


def test_no_threshold_is_applied_to_the_export_share():
    """Deliberate, and recorded so it is not quietly added later. No measured
    number exists to set one to: FRR ends this workload ~11% below what it
    holds and BIRD withholds 2.24% of its own table on the same RIB, so the two
    constants this project measured -- `WITNESS_AGREEMENT_FRACTION` and
    `DROP_FRACTION`, both 1% -- are both too tight, and anything above them
    would be chosen to fit the daemons in front of it. `bgperf2-cw6`.
    """
    doc, r = _mrt(exported=540000, received='540000')
    doc['target_table']['series']['best_paths'] = {'final': 1080985}
    verdict, checks = check.qualify(doc, versions(), r)
    share = [c for c in checks if c.name == 'export_share']
    assert share[0].status == check.NOTE
    assert '49.95%' in share[0].detail
    # Stated, not rejected -- and that remaining hole is what `bgperf2-ctm`
    # stays open for.
    assert verdict == 'qualified', statuses(checks)


def test_an_mrt_row_is_rejected_when_the_two_ends_of_the_session_disagree():
    '''Completeness is not checkable for MRT playback; consistency is. The
    monitor's count and the target's own count of what it sent that very
    session are two measurements of one thing.'''
    doc, r = _mrt(exported=1010000)
    verdict, checks = check.qualify(doc, versions(), r)
    assert statuses(checks)['route_counts'] == check.FAIL
    assert verdict == 'rejected'


def test_an_mrt_row_with_no_witness_is_noted_not_passed_or_failed():
    '''The check could not be made, which is neither a pass nor a failure --
    the distinction `findings.py` keeps between unresolved and inconclusive.
    OpenBGPD and RustyBGP publish no export witness today.'''
    doc, r = _mrt(exported=None, received='1056779')
    verdict, checks = check.qualify(doc, versions(), r)
    assert statuses(checks)['route_counts'] == check.NOTE
    assert verdict == 'qualified', statuses(checks)


def test_two_zeros_are_an_absent_session_rather_than_agreement():
    '''A collapsed count agrees with itself arithmetically and attests to
    nothing: the session every published timing is read from was not carrying
    the table.'''
    doc, r = _mrt(exported=0, received='0')
    verdict, checks = check.qualify(doc, versions(), r)
    assert statuses(checks)['route_counts'] == check.FAIL
    assert verdict == 'rejected'


def test_a_synthetic_shortfall_is_still_route_loss():
    '''The MRT reasoning must not leak into the synthetic blocks, where
    bgperf2 generated the prefix lists and `required` really is `n * p`.'''
    verdict, checks = check.qualify(artifact(), versions(),
                                    row(received='39599'))
    assert statuses(checks)['route_counts'] == check.FAIL
    assert verdict == 'rejected'


def test_the_check_point_remains_a_sufficient_floor_for_an_mrt_row():
    '''Reaching `0.99 * -p` was never the problem: a daemon that exports more
    than that has demonstrably not shrunk the table. Treating it as *necessary*
    was. OpenBGPD and RustyBGP rows are judged exactly as they always were.'''
    doc, r = _mrt(exported=None, received='1056779')
    checks = [c for c in check.check_status(doc, r) if c.name == 'route_counts']
    assert any(c.status == check.OK and 'check-point' in c.detail
               for c in checks), [c.detail for c in checks]


def test_a_target_that_kept_a_tenth_of_the_rib_is_rejected():
    '''The size floor, and the reason consistency alone cannot be the whole
    check: `received` and `exported_to_monitor` are the two ends of one link
    and agree whenever the link works, so a target that imported a tenth would
    show them agreeing at a tenth. What bounds the size is the target's own
    count of what it accepted, against what the generators say they offered.'''
    doc, r = _mrt(exported=96101, received='96101')
    doc['tester_fleet'] = dict(doc['tester_fleet'], offered_prefixes=10500000)
    doc['target_table']['series']['imported_paths'] = {'final': 1049794}
    verdict, checks = check.qualify(doc, versions(), r)
    assert verdict == 'rejected'
    assert any(c.name == 'route_counts' and c.status == check.FAIL
               and 'short' in c.detail for c in checks)


def test_a_full_table_clears_the_size_floor():
    doc, r = _mrt(exported=961019, received='961019')
    doc['tester_fleet'] = dict(doc['tester_fleet'], offered_prefixes=10500000)
    doc['target_table']['series']['imported_paths'] = {'final': 10497949}
    verdict, checks = check.qualify(doc, versions(), r)
    assert verdict == 'qualified', statuses(checks)


def test_a_synthetic_exabgp_run_is_not_treated_as_mrt_playback():
    '''`SYNTHETIC_TESTER_TYPES` is ('exa', 'bird'): bgperf2 generates the
    prefix lists for both, so `required` really is `n * p` and a shortfall is
    route loss.'''
    doc = artifact(run={'name': 'bird 2.19.2', 'repetition': None, 'peers': 4,
                        'prefixes_per_peer': 10000, 'tester_type': 'exa',
                        'path_diversity': 1})
    verdict, checks = check.qualify(doc, versions(), row(received='39599'))
    assert statuses(checks)['route_counts'] == check.FAIL
    assert verdict == 'rejected'


def test_a_shortfall_with_no_gauge_at_all_is_rejected():
    """The two ends of one link agree whenever the link works, so a daemon
    publishing neither gauge and finishing below the check-point has nothing
    vouching for it. The absolute rejected that row before the MRT branch
    existed, and it still has to: "judged exactly as they always were" covers
    the shortfall case, not only rows that clear the check-point."""
    doc, r = _mrt(exported=None, received='700000')
    verdict, checks = check.qualify(doc, versions(), r)
    assert verdict == 'rejected'
    assert any(c.name == 'route_counts' and c.status == check.FAIL
               and 'no import gauge' in c.detail for c in checks)


def test_a_frozen_export_witness_is_not_published_as_route_loss():
    """The target's witness is resampled onto the monitor's polls, so a target
    sampler that stalls late in a run leaves `final` at an old value while the
    monitor climbs past it. Comparing those publishes a dead instrument as
    route loss -- and `check_instrument()` only downgrades a target-sampler
    failure to a NOTE, so nothing else would contradict it."""
    doc, r = _mrt(exported=500000, received='1056779')
    doc['target_table']['series']['exported_to_monitor']['max_witness_age_s'] = 47.0
    verdict, checks = check.qualify(doc, versions(), r)
    detail = [c for c in checks if c.name == 'route_counts']
    assert any(c.status == check.NOTE and 'without being re-read' in c.detail
               for c in detail), [c.detail for c in detail]
    assert not any(c.status == check.FAIL for c in detail)


def test_a_fresh_witness_still_catches_a_real_disagreement():
    doc, r = _mrt(exported=500000, received='1056779')
    doc['target_table']['series']['exported_to_monitor']['max_witness_age_s'] = 1.0
    verdict, checks = check.qualify(doc, versions(), r)
    assert verdict == 'rejected'
    assert any(c.name == 'route_counts' and c.status == check.FAIL
               and 'disagreement' in c.detail for c in checks)


def test_a_missing_offered_count_is_not_blamed_on_the_target():
    """`tester_fleet.offered_prefixes` is absent for an MRT injector that does
    not report its offering, and withheld entirely when one injector never
    completed. That is the generators' side of the run, not the target's."""
    doc, r = _mrt(exported=None, received='700000')
    doc['tester_fleet'] = dict(doc['tester_fleet'], offered_prefixes=None)
    verdict, checks = check.qualify(doc, versions(), r)
    assert verdict == 'rejected'
    assert any(c.name == 'route_counts' and c.status == check.FAIL
               and 'generators report no offered count' in c.detail
               for c in checks)


def test_freshness_is_the_last_readings_age_not_the_runs_worst():
    """`max_witness_age_s` is the maximum over the whole run, which answers a
    different question. One transient slow target poll -- a `vtysh` call
    blocking on a busy bgpd mid-injection, on the exact daemon and workload
    this guard was written for -- would otherwise mute the row's only
    consistency check while the final reading was perfectly fresh."""
    doc, r = _mrt(exported=961201, received='961201')
    series = doc['target_table']['series']['exported_to_monitor']
    series['max_witness_age_s'] = 47.0
    doc['target_table']['samples'] = [
        {'exported_to_monitor': 500000, 'witness_age_s': 47.0},
        {'exported_to_monitor': 961201, 'witness_age_s': 0.9},
    ]
    verdict, checks = check.qualify(doc, versions(), r)
    detail = [c for c in checks if c.name == 'route_counts']
    assert any(c.status == check.OK and 'apart' in c.detail for c in detail), \
        [c.detail for c in detail]


def test_a_withheld_import_gauge_is_not_a_missing_one():
    """`table_witness()` withholds the sum on any poll where a configured
    peering was not reporting. Blaming the target for lacking a capability it
    has sends the reader to the wrong half of the run."""
    doc, r = _mrt(exported=None, received='700000')
    doc['target_table'] = {'series': {}, 'samples': []}
    verdict, checks = check.qualify(doc, versions(), r)
    assert verdict == 'rejected'
    assert any(c.name == 'route_counts' and c.status == check.FAIL
               and 'withheld on every sample' in c.detail for c in checks)


def test_a_scenario_run_keeps_the_strict_absolute():
    '''A `-f` run records `tester_type: null` and the file states its own
    check-point, so `required` is a statement of fact there as much as for a
    synthetic run. Reading "not synthetic" as "MRT playback" let such a row
    re-advertise 70% of its table and still qualify.'''
    doc = artifact(run={'name': 'bird 2.19.2', 'repetition': None,
                        'peers': 4, 'prefixes_per_peer': 10000,
                        'tester_type': None, 'path_diversity': 1})
    verdict, checks = check.qualify(doc, versions(), row(received='28000'))
    assert statuses(checks)['route_counts'] == check.FAIL
    assert verdict == 'rejected'


def test_a_target_whose_witness_never_sampled_is_not_blamed_on_its_peers():
    """`target_table_unmeasured()` writes the section with an
    `unmeasured_reason` and no samples when a witness-reporting target's poll
    thread died. That is the target's instrument, not a peering that failed to
    report, and the correct reason is sitting in the same document."""
    doc, r = _mrt(exported=None, received='700000')
    doc['target_table'] = {'series': {}, 'samples': [],
                           'unmeasured_reason': 'no sample reached the loop'}
    verdict, checks = check.qualify(doc, versions(), r)
    assert verdict == 'rejected'
    assert any(c.name == 'route_counts' and c.status == check.FAIL
               and 'no sample reached the loop' in c.detail for c in checks)


def test_generators_offering_nothing_is_not_a_missing_offered_count():
    doc, r = _mrt(exported=None, received='700000')
    doc['tester_fleet'] = dict(doc['tester_fleet'], offered_prefixes=0)
    verdict, checks = check.qualify(doc, versions(), r)
    assert verdict == 'rejected'
    assert any(c.name == 'route_counts' and c.status == check.FAIL
               and 'offering nothing at all' in c.detail for c in checks)


def test_a_filtered_mrt_row_is_rejected_as_unvouchable_not_as_route_loss():
    """Two things are true at once and the row loses on the second.

    `imported_paths` is post-import-policy for both daemons that publish it, so
    a filtered run is *designed* to accept far less than the fleet offered and
    to sit below the check-point -- failing it for the shortfall would assert
    route loss about a policy doing its job. But that leaves nothing bounding
    the table's size, and the export cross-check compares two ends of one link
    and agrees at any size, so a row that lost 90% of the RIB for an unrelated
    reason is indistinguishable from one the policy trimmed. The refusal has to
    name the right fault: unvouchable, not short."""
    doc, r = _mrt(exported=300000, received='300000', imported=3000000)
    doc['tester_fleet'] = dict(doc['tester_fleet'], offered_prefixes=10500000)
    r = dict(r, filters='drop-half')
    verdict, checks = check.qualify(doc, versions(), r)
    detail = [c for c in checks if c.name == 'route_counts']
    assert verdict == 'rejected'
    assert any(c.status == check.FAIL and 'nothing bounds' in c.detail
               for c in detail), [c.detail for c in detail]
    assert not any('short' in c.detail for c in detail), \
        [c.detail for c in detail]


def test_an_unfiltered_mrt_run_still_gets_the_size_floor():
    doc, r = _mrt(exported=300000, received='300000', imported=3000000)
    doc['tester_fleet'] = dict(doc['tester_fleet'], offered_prefixes=10500000)
    verdict, checks = check.qualify(doc, versions(), r)
    assert verdict == 'rejected'
    assert any(c.name == 'route_counts' and c.status == check.FAIL
               and 'short' in c.detail for c in checks)


def test_a_truncated_export_series_is_not_published_as_route_loss():
    """A witness is *withheld* -- not frozen -- whenever a peering stops
    reporting: the poll keeps running and every reading it does produce is
    fresh, so the staleness guard sees nothing wrong while `final` is a
    mid-delivery value and `received` is the monitor's count at convergence."""
    doc, r = _mrt(exported=500000, received='1056779')
    doc['target_table']['series']['exported_to_monitor'].update(
        {'final_monotonic_s': 300.0, 'max_witness_age_s': 0.4})
    doc['target_table']['series']['monitor_accepted'] = {
        'final': 1056779, 'final_monotonic_s': 600.0}
    verdict, checks = check.qualify(doc, versions(), r)
    detail = [c for c in checks if c.name == 'route_counts']
    assert any(c.status == check.NOTE and 'same window' in c.detail
               for c in detail), [c.detail for c in detail]
    assert not any('disagreement' in c.detail for c in detail)


def test_a_truncated_import_series_does_not_bound_the_size():
    doc, r = _mrt(exported=None, received='700000', imported=3000000)
    doc['target_table'] = {'series': {
        'imported_paths': {'final': 3000000, 'final_monotonic_s': 100.0},
        'monitor_accepted': {'final': 700000, 'final_monotonic_s': 600.0},
    }}
    doc['tester_fleet'] = dict(doc['tester_fleet'], offered_prefixes=10500000)
    verdict, checks = check.qualify(doc, versions(), r)
    assert verdict == 'rejected'
    assert any(c.name == 'route_counts' and c.status == check.FAIL
               and 'stopped reporting' in c.detail for c in checks)
    assert not any('short' in c.detail for c in checks
                   if c.name == 'route_counts')


def test_a_frozen_import_gauge_is_not_published_as_route_loss():
    """The third time this class of fault was missed, so it is pinned here.

    A *truncated* series ends before the monitor's. A *frozen* one does not:
    the target's sampler dies, `bench()` keeps appending the carried reading to
    every monitor poll, so the series runs to the end and `final_monotonic_s`
    looks perfect while the value is minutes old. The truncation test alone
    published that as "71.43% short" -- a dead instrument reported as route
    loss, which `check_instrument()` only downgrades to a NOTE, so nothing in
    the row contradicted it.
    """
    doc, r = _mrt(exported=None, received='700000', imported=3000000)
    doc['target_table'] = {
        'series': {
            'imported_paths': {'final': 3000000, 'final_monotonic_s': 600.0},
            'monitor_accepted': {'final': 700000, 'final_monotonic_s': 600.0},
        },
        'samples': [{'imported_paths': 3000000, 'witness_age_s': 300.0}],
    }
    doc['tester_fleet'] = dict(doc['tester_fleet'], offered_prefixes=10500000)
    verdict, checks = check.qualify(doc, versions(), r)
    detail = [c for c in checks if c.name == 'route_counts']
    # The reading is still used -- discarding it rejected good rows over one
    # slow poll -- so what it says decides. Frozen at 3,000,000 of 10,500,000
    # it fails the floor either way; what the age adds is that "route loss" and
    # "the gauge stopped" cannot be told apart here, so the refusal says both.
    assert verdict == 'rejected'
    assert any(c.status == check.FAIL
               and 'either route loss or a gauge that stopped' in c.detail
               for c in detail), [c.detail for c in detail]


def test_a_filtered_row_falls_back_to_the_check_point():
    """Under a policy the floor cannot be applied at all -- `imported_paths` is
    post-policy for both daemons that publish it -- so the check-point is the
    only bound left, and it is used as the fallback, exactly as for a target
    publishing no gauge.

    The message may not claim more than that. `0.99 * -p` sits about 4% below
    the union the peers hold, so clearing it is consistent with having dropped
    several percent, and an earlier wording here said a policy "cannot make it
    insufficient" -- contradicting the finding the rest of this change set
    rests on. What it does rule out is the failure the check exists for: a
    target that lost the table is not still exporting the check-point's worth.
    """
    doc, r = _mrt(exported=1045000, received='1045000')
    r = dict(r, filters='drop-some')
    verdict, checks = check.qualify(doc, versions(), r)
    detail = [c for c in checks if c.name == 'route_counts']
    assert verdict == 'qualified', statuses(checks)
    assert any(c.status == check.OK
               and 'the only bound available' in c.detail
               for c in detail), [c.detail for c in detail]
    assert not any('cannot make insufficient' in c.detail for c in detail)


def test_a_cleared_row_names_which_half_of_the_run_lacks_the_evidence():
    """`elif cleared` is reached whenever the floor could not be applied, which
    is not the same as "this target has no gauge". `offered` is None for every
    gobgp and exabgp_mrtparse injector, so a BIRD row reporting 10,497,949
    accepted paths reached it and was told it publishes no usable import gauge
    -- a false statement about the target, sending the reader to the wrong half
    of the run, which is the fault class the rest of this module is about.
    """
    doc, r = _mrt(exported=1056779, received='1056779', imported=10497949)
    doc['tester_fleet'] = dict(doc['tester_fleet'], offered_prefixes=None)
    verdict, checks = check.qualify(doc, versions(), r)
    detail = [c for c in checks if c.name == 'route_counts']
    assert verdict == 'qualified', statuses(checks)
    assert any(c.status == check.OK and 'no offered count' in c.detail
               and '10497949' in c.detail for c in detail), \
        [c.detail for c in detail]
    assert not any('publishes no usable import gauge' in c.detail
                   for c in detail)


def test_a_gauge_withheld_on_every_sample_is_not_blamed_on_the_generators():
    """The target-side diagnoses have to come first, all three of them.

    Two were hoisted above the generator-side branches and the third was left
    below, which for exactly the generators that motivated the hoist -- gobgp
    and exabgp_mrtparse, where `offered` is None on every run -- made it
    unreachable: a target whose gauge was withheld on every sample was reported
    as "the generators report no offered count", the identical mis-attribution
    one branch over.
    """
    doc, r = _mrt(exported=None, received='700000')
    doc['target_table'] = {'series': {}, 'samples': []}
    doc['tester_fleet'] = dict(doc['tester_fleet'], offered_prefixes=None)
    verdict, checks = check.qualify(doc, versions(), r)
    detail = [c for c in checks if c.name == 'route_counts']
    assert verdict == 'rejected'
    assert any(c.status == check.FAIL and 'withheld on every sample' in c.detail
               for c in detail), [c.detail for c in detail]
    assert not any('report no offered count' in c.detail for c in detail)


def test_clearing_the_check_point_does_not_skip_the_size_floor():
    """`required` is `0.99 * -p`, and for MRT that is ~96% of the union the ten
    peers actually hold -- so a target can clear the check-point having dropped
    several percent of the table. `ConvergenceTracker`'s DROP_FRACTION does not
    catch it either: routes never delivered are not a decline from the run's
    own peak. The floor has to apply as well as the check-point, not instead."""
    doc, r = _mrt(exported=1040000, received='1040000', imported=9000000)
    doc['tester_fleet'] = dict(doc['tester_fleet'], offered_prefixes=10500000)
    verdict, checks = check.qualify(doc, versions(), r)
    assert verdict == 'rejected'
    assert any(c.name == 'route_counts' and c.status == check.FAIL
               and 'short' in c.detail for c in checks)


def test_a_daemon_with_no_import_gauge_is_still_judged_on_the_check_point():
    """OpenBGPD and RustyBGP publish no witness; clearing the check-point
    bounds the size on its own and always has."""
    doc, r = _mrt(exported=None, received='1056779')
    verdict, checks = check.qualify(doc, versions(), r)
    assert verdict == 'qualified', statuses(checks)
    assert any(c.name == 'route_counts' and c.status == check.OK
               and 'at or above' in c.detail for c in checks)


def test_a_stale_but_healthy_import_gauge_still_qualifies_the_row():
    """One slow final target poll must not cost a correct cell. For an FRR MRT
    row this floor is the only rule that can qualify it -- `received` is always
    below the check-point -- and re-measuring a 14-cell block needs `--force`,
    which discards the cells that passed. The table is flat by convergence, so
    a reading a few seconds late is still the right number; the staleness is
    reported beside the verdict rather than instead of it."""
    doc, r = _mrt(exported=958217, received='958217', imported=10497949)
    doc['target_table']['series']['imported_paths']['final_monotonic_s'] = 600.0
    doc['target_table']['series']['monitor_accepted'] = {
        'final': 958217, 'final_monotonic_s': 600.0}
    doc['target_table']['samples'] = [
        {'imported_paths': 10497949, 'exported_to_monitor': 958217,
         'witness_age_s': 6.0}]
    doc['tester_fleet'] = dict(doc['tester_fleet'], offered_prefixes=10500000)
    verdict, checks = check.qualify(doc, versions(), r)
    detail = [c for c in checks if c.name == 'route_counts']
    assert verdict == 'qualified', statuses(checks)
    assert any(c.status == check.OK and 'last read 6.0s' in c.detail
               for c in detail), [c.detail for c in detail]


def test_a_dead_target_sampler_is_not_blamed_on_the_generators():
    """`offered_prefixes` is absent for every gobgp and exabgp_mrtparse
    injector, so testing it first reported a dead target sampler as "the
    generators report no offered count" on every such run."""
    doc, r = _mrt(exported=None, received='700000', imported=None)
    doc['target_table'] = {
        'series': {
            'imported_paths': {'final': 3000000, 'final_monotonic_s': 100.0},
            'monitor_accepted': {'final': 700000, 'final_monotonic_s': 600.0},
        },
        'samples': [{'imported_paths': 3000000, 'witness_age_s': 0.4}],
    }
    doc['tester_fleet'] = dict(doc['tester_fleet'], offered_prefixes=None)
    verdict, checks = check.qualify(doc, versions(), r)
    assert verdict == 'rejected'
    assert any(c.name == 'route_counts' and c.status == check.FAIL
               and 'stopped reporting' in c.detail for c in checks)


def mrt_without_the_checkpoint_event(**delivery):
    """The real Block 5 `frr_c` shape, built on `_mrt()` so the row is
    genuinely below its check-point rather than merely missing an event.

    Everything has to hold at once or the test proves nothing: `received`
    (958,217) under `required` (1,039,500), an import gauge bounding the table
    against what the generators offered, an export gauge agreeing with the
    monitor, *and* no `monitor_required_reached`. Built the other way -- a
    cleared row with a bare `delivery` key -- the row passes
    `_mrt_route_counts()` through its "cleared the check-point" fallback, and
    the combination this substitution exists to enable is pinned by nothing.
    """
    doc, r = _mrt(exported=958217, received='958217', imported=1046000)
    doc['events'] = [e for e in doc['events']
                     if e['event'] != check.MONITOR_REQUIRED_EVENT]
    doc['tester_fleet'] = {'testers': 10, 'testers_complete': 10,
                           'incomplete_testers': [],
                           'offered_prefixes': 1050000}
    section = {'unresolved_reason': None, 'complete_s': 61.5,
               'exported_final': 958217, 'monitor_final': 958217}
    section.update(delivery)
    doc['target_table']['delivery'] = section
    return doc, r


def test_an_mrt_row_below_the_checkpoint_qualifies_on_the_derived_delivery():
    """The check-point for MRT playback is `0.99 * -p`, the per-injector cap --
    a guess, since ten peers replay one RIB's overlapping views. Every FRR
    release lands near 961,000 against a 1,039,500 check-point while BIRD and
    OpenBGPD settle on 1,056,779: three distinct totals from one file, because
    export rules differ. Rejecting such a row asked a daemon to meet a number
    nobody could have set correctly."""
    doc, r = mrt_without_the_checkpoint_event()
    # The row really is below its check-point: that is the whole premise.
    assert int(r['received']) < int(r['required'])
    verdict, checks = check.qualify(doc, versions(), r)
    assert verdict == 'qualified', statuses(checks)
    assert statuses(checks)['event_coverage'] == check.OK


def test_a_synthetic_row_below_the_checkpoint_is_still_rejected():
    """For a synthetic generator bgperf2 built the prefix lists, so the
    check-point is `n * p` -- a statement of fact. A target that misses it lost
    routes, and accepting a substitute there would excuse exactly that."""
    doc, r = mrt_without_the_checkpoint_event()
    doc['run'] = dict(doc['run'], tester_type='bird')
    verdict, checks = check.qualify(doc, versions(), r)
    assert verdict == 'rejected'
    assert statuses(checks)['event_coverage'] == check.FAIL


def test_a_scenario_run_states_its_own_checkpoint_and_is_still_rejected():
    """A `-f` run records `tester_type: null` and states its own check-point in
    the file, so `required` is a fact there too. Tested by membership in
    MRT_TESTER_TYPES rather than by not-being-synthetic, which would route this
    third state down the MRT branch."""
    doc, r = mrt_without_the_checkpoint_event()
    doc['run'] = dict(doc['run'], tester_type=None)
    verdict, checks = check.qualify(doc, versions(), r)
    assert verdict == 'rejected'
    assert statuses(checks)['event_coverage'] == check.FAIL


def test_a_withheld_delivery_is_not_a_substitute():
    """A withheld `delivery` names why, and its reasons are the cases where the
    series cannot support an answer. Reading one as a substitute would replace
    a missing measurement with an absent one."""
    doc, r = mrt_without_the_checkpoint_event(
        unresolved_reason='gauge_undated', complete_s=None)
    verdict, checks = check.qualify(doc, versions(), r)
    assert verdict == 'rejected'
    assert statuses(checks)['event_coverage'] == check.FAIL


def test_the_substitute_covers_only_the_checkpoint_event():
    """`bench_clock_started`, `monitor_first_prefix` and
    `convergence_confirmed` are recorded by every run that got that far,
    including every FRR MRT run. A missing one is a broken run, not a yardstick
    that did not fit."""
    doc, r = mrt_without_the_checkpoint_event()
    doc['events'] = [e for e in doc['events']
                     if e['event'] != 'convergence_confirmed']
    verdict, checks = check.qualify(doc, versions(), r)
    assert verdict == 'rejected'
    assert statuses(checks)['event_coverage'] == check.FAIL


def test_a_run_that_has_the_event_is_unaffected_by_the_substitute():
    """Every row that qualified before must still qualify the same way, and say
    so in the same words."""
    verdict, checks = check.qualify(artifact(), versions(), row())
    assert verdict == 'qualified'
    detail = [c.detail for c in checks if c.name == 'event_coverage']
    assert detail == ['every required event present']
