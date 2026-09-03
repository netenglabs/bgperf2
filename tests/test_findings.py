'''Docker-free tests for the run's qualification policy.

The policy exists to answer one question -- what was this run waiting for --
and, far more often, to refuse to answer it.  These tests are mostly about the
refusals: a verdict that names the generator or the target when the evidence
does not support it is worse than no verdict, because it looks like a finding
about the daemon under test.
'''
import json

import pytest

from findings import (
    INCONCLUSIVE,
    TARGET_OR_MONITOR,
    TESTER,
    UNRESOLVED,
    derive_findings,
    describe_findings,
)
from measurements import (
    MonitorEventRecorder,
    TesterEventRecorder,
    TesterOffering,
    event_artifact,
)


def monitor(samples, interval=1.0, required_at=None):
    recorder = MonitorEventRecorder(0.0, producer='bgperf_monitor',
                                    sample_interval_s=interval)
    for at, accepted in samples:
        recorder.observe(at, accepted,
                         required_reached=required_at is not None
                         and at >= required_at)
    return recorder


def injector(producer, polls, interval=1.0):
    recorder = TesterEventRecorder(0.0, producer, sample_interval_s=interval)
    for at, fields in polls:
        fields = dict(fields)
        fields.setdefault('established', True)
        fields.setdefault('expected', 1000)
        recorder.observe(at, {'s': TesterOffering(**fields)})
    return recorder


def artifact(monitor_recorder, testers, status='converged', evidence=None):
    events = list(monitor_recorder.events)
    for recorder in testers:
        events.extend(recorder.events)
    evidence = evidence or {r.producer: {} for r in testers}
    return event_artifact(events, status, testers=evidence or None)


def rate_limited_run(required_at=11.0, last_sample=11.0):
    '''A generator handing over its table across the whole run.

    Nine seconds of measured injection with 900 of the 1000 prefixes crossing
    it, and a monitor that reaches the check-point on the same poll the
    generator finishes.
    '''
    m = monitor([(float(at), 100 * at) for at in range(1, int(last_sample) + 1)],
                required_at=required_at)
    t = injector('a', [(float(at), dict(offered=100 * (at - 1)))
                       for at in range(1, 12)])
    return artifact(m, [t])


def names(result):
    return [f['finding'] for f in result['findings']]


def test_a_generator_still_sending_at_the_end_is_the_named_limit():
    '''The one shape that earns `tester`: a measured, observed send that ran
    to the moment the monitor reached its check-point.'''
    result = derive_findings(rate_limited_run())

    assert result['limiting_component'] == TESTER
    assert 'tester_limited' in names(result)


def test_a_run_that_kept_working_after_the_load_is_not_tester_limited():
    '''The same generator, but the target went on for another half minute.'''
    m = monitor([(float(at), 40 * at) for at in range(1, 31)],
                required_at=30.0)
    t = injector('a', [(float(at), dict(offered=100 * (at - 1)))
                       for at in range(1, 12)])

    result = derive_findings(artifact(m, [t]))

    assert result['limiting_component'] == TARGET_OR_MONITOR
    assert 'tester_limited' not in names(result)
    tail = [f for f in result['findings']
            if f['finding'] == 'post_injection_tail'][0]
    assert tail['evidence']['post_injection_tail_s'] == pytest.approx(19.0)


def test_a_saturated_host_leaves_the_component_unresolved():
    '''Host-wide idle says the machine had nothing spare; it does not say
    whose work that was, and no per-role CPU measurement exists to ask.'''
    result = derive_findings(rate_limited_run(),
                             host={'min_idle_percent': 1.0})

    assert result['limiting_component'] == UNRESOLVED
    assert 'host_cpu_saturated' in names(result)
    # The evidence that would have named the tester is still published: the
    # verdict is withheld, not the measurement.
    assert 'tester_limited' in names(result)


def test_a_generator_that_never_completed_is_inconclusive():
    '''Not a guess in either direction. The workload was never fully offered,
    so no interval bounded by its completion means anything.'''
    m = monitor([(1.0, 0), (2.0, 400), (9.0, 900)], required_at=9.0)
    t = injector('a', [(1.0, dict(offered=0)), (2.0, dict(offered=400))])

    result = derive_findings(artifact(m, [t]))

    assert result['limiting_component'] == INCONCLUSIVE
    assert names(result) == ['tester_incomplete']


def test_a_run_with_no_pollable_generator_is_inconclusive():
    '''An ExaBGP or GoBGP tester reports nothing about its own sending, and a
    run without that evidence cannot be attributed at all.'''
    m = monitor([(1.0, 0), (2.0, 500), (3.0, 1000)], required_at=3.0)

    result = derive_findings(event_artifact(list(m.events), 'converged'))

    assert result['limiting_component'] == INCONCLUSIVE
    assert names(result) == ['missing_timing_evidence']


def test_a_failed_run_has_no_end_to_measure_against():
    m = monitor([(1.0, 0), (2.0, 400), (3.0, 400)])
    t = injector('a', [(1.0, dict(offered=0)),
                       (2.0, dict(offered=500)),
                       (3.0, dict(offered=1000))])

    result = derive_findings(artifact(m, [t], status='failed'))

    assert result['limiting_component'] == INCONCLUSIVE
    assert names(result) == ['missing_timing_evidence']


def test_a_queue_side_count_is_not_read_as_the_end_of_the_send():
    '''The BIRD 2.19 shape, and the reason the coverage rule exists.

    `Export updates accepted` counts a route when it is handed to the BGP
    protocol, so the table is fully "offered" before the instrument first
    looks and the completion the tail is measured from may sit anywhere inside
    the real send. The run has a large tail and it must not be charged to the
    target.
    '''
    m = monitor([(float(at), 20 * at) for at in range(1, 61)],
                required_at=60.0)
    t = injector('a', [(1.0, dict(offered=850, expected=1000)),
                       (2.0, dict(offered=1000, expected=1000))])

    result = derive_findings(artifact(m, [t]))

    assert result['limiting_component'] == UNRESOLVED
    assert 'injection_boundary_unresolved' in names(result)
    assert result['reason'].startswith('the generators offered 1000 prefixes')


def test_a_generator_that_timed_its_own_send_can_still_show_a_target_tail():
    '''An MRT injector's whole walk is over before the first poll, so its
    polled injection is unresolved -- but it says how long it took, which
    places its completion and leaves the tail readable.'''
    m = monitor([(float(at), 20 * at) for at in range(1, 61)],
                required_at=60.0)
    t = injector('a', [(1.0, dict(offered=0)),
                       (2.0, dict(offered=1000, send_complete=True,
                                  reported_send_duration_s=0.001017))])

    result = derive_findings(artifact(m, [t]))

    assert result['limiting_component'] == TARGET_OR_MONITOR
    assert 'injection_unresolved' in names(result)
    assert 'injection_boundary_unresolved' not in names(result)


def test_a_run_finished_inside_its_polls_names_nothing():
    '''Both intervals are shorter than the looks that bound them. Neither the
    generator nor the target can be shown to have held the run up.'''
    m = monitor([(1.0, 0), (2.0, 1000)], required_at=2.0)
    t = injector('a', [(1.0, dict(offered=0)),
                       (2.0, dict(offered=1000, send_complete=True,
                                  reported_send_duration_s=0.001))])

    result = derive_findings(artifact(m, [t]))

    assert result['limiting_component'] == UNRESOLVED
    assert 'no_dominant_interval' in names(result)


def test_foreign_cpu_withholds_the_component():
    '''A run sharing the machine is not comparable with one that did not, and
    a version ranking read off it would be an artifact of the neighbour.'''
    result = derive_findings(rate_limited_run(),
                             host={'max_foreign_cpu_percent': 400.0})

    assert result['limiting_component'] == UNRESOLVED
    assert 'foreign_cpu_contention' in names(result)


def test_a_quiet_machine_produces_no_host_finding():
    result = derive_findings(rate_limited_run(), host={
        'min_idle_percent': 88.0,
        'max_foreign_cpu_percent': 4.0,
        'min_free_bytes': 50 * 1024 ** 3,
        'total_memory_bytes': 64 * 1024 ** 3,
    })

    assert result['limiting_component'] == TESTER


def test_low_free_memory_withholds_the_component():
    result = derive_findings(rate_limited_run(), host={
        'min_free_bytes': 1 * 1024 ** 3,
        'total_memory_bytes': 64 * 1024 ** 3,
    })

    assert result['limiting_component'] == UNRESOLVED
    assert 'low_free_memory' in names(result)


def test_unsampled_host_evidence_asserts_nothing():
    '''A missing sample must not read as an idle host with free memory.'''
    result = derive_findings(rate_limited_run(), host={
        'min_idle_percent': None,
        'max_foreign_cpu_percent': None,
        'min_free_bytes': None,
        'total_memory_bytes': None,
    })

    assert result['limiting_component'] == TESTER


def test_blocked_writes_are_an_interaction_and_name_no_component():
    '''Which end of a blocked write was at fault is not in these numbers.'''
    m = monitor([(float(at), 100 * at) for at in range(1, 12)],
                required_at=11.0)
    t = injector('a', [(float(at), dict(offered=100 * (at - 1)))
                       for at in range(1, 12)])
    doc = artifact(m, [t], evidence={'a': {'backpressure': {
        'available': True, 'max_blocked_writes': 12, 'max_send_stalls': 3}}})

    result = derive_findings(doc)

    assert result['limiting_component'] == UNRESOLVED
    assert 'backpressure_observed' in names(result)


def test_a_queue_depth_is_not_backpressure():
    '''BIRD 3 reports `TX pending` bytes at every poll, and a session with
    something queued is what a working session looks like. Reading it as
    backpressure would withhold every BIRD 3 verdict there is.'''
    m = monitor([(float(at), 100 * at) for at in range(1, 12)],
                required_at=11.0)
    t = injector('a', [(float(at), dict(offered=100 * (at - 1)))
                       for at in range(1, 12)])
    doc = artifact(m, [t], evidence={'a': {'backpressure': {
        'available': True, 'max_tx_pending_bytes': 65536,
        'max_pending_prefixes': 400}}})

    result = derive_findings(doc)

    assert result['limiting_component'] == TESTER


def test_an_unavailable_counter_is_not_a_count_of_zero():
    m = monitor([(float(at), 100 * at) for at in range(1, 12)],
                required_at=11.0)
    t = injector('a', [(float(at), dict(offered=100 * (at - 1)))
                       for at in range(1, 12)])
    doc = artifact(m, [t], evidence={'a': {'backpressure': {
        'available': False,
        'reason': 'generator reported no blocked-write counter'}}})

    result = derive_findings(doc)

    assert 'backpressure_observed' not in names(result)


def test_every_finding_carries_its_rule_and_the_durations_it_ruled_on():
    '''The verdict is not a validity boolean: a reader has to be able to
    disagree with the policy without re-deriving the numbers.'''
    result = derive_findings(rate_limited_run(),
                             host={'min_idle_percent': 1.0})

    assert result['schema'] == 'bgperf2/measurement-findings/v1alpha1'
    assert result['policy_version'] == 'conservative/v1'
    for finding in result['findings']:
        assert finding['policy']
        assert finding['summary']
        assert finding['evidence']
        assert finding['kind'] in ('attribution', 'confounder',
                                   'qualification', 'missing_evidence')


def test_the_printed_lines_lead_with_the_verdict_and_do_not_repeat_it():
    result = derive_findings(rate_limited_run(),
                             host={'min_idle_percent': 1.0})

    lines = describe_findings(result)

    assert lines[0].startswith('limiting component: unresolved -- host idle')
    assert len(lines) == 2
    assert lines[1].startswith('finding: ')
    assert 'tester_limited' in lines[1]


def test_an_overlap_is_named_as_one_not_as_a_tail_of_zero():
    '''The strongest form of the finding: the monitor reached the check-point
    while the generators still had the rest of the table to hand over.'''
    m = monitor([(float(at), 250 * at) for at in range(1, 12)],
                required_at=4.0)
    t = injector('a', [(float(at), dict(offered=100 * (at - 1)))
                       for at in range(1, 12)])

    result = derive_findings(artifact(m, [t]))

    assert result['limiting_component'] == TESTER
    assert result['decided_by'] == 'tester_limited'
    assert result['reason'].endswith('7.0s before they finished')


def test_the_verdict_names_the_finding_that_produced_it():
    result = derive_findings(rate_limited_run(),
                             host={'min_idle_percent': 1.0})

    assert result['decided_by'] == 'host_cpu_saturated'


def test_the_run_artifact_carries_the_findings(tmp_path, bench_args):
    '''The policy is published beside the intervals it ruled on, in the same
    document, so a result can be re-read without re-running the derivation.'''
    import bgperf2

    bench_args.results_dir = str(tmp_path)
    bench_args.tester_type = 'bird'
    m = monitor([(float(at), 100 * at) for at in range(1, 12)],
                required_at=11.0)
    t = injector('a', [(float(at), dict(offered=100 * (at - 1)))
                       for at in range(1, 12)])
    events = list(m.events) + list(t.events)

    doc = bgperf2.write_event_artifact(
        bench_args, events, 'run', 'converged', testers={'a': {}},
        host=bgperf2.host_evidence({'min_idle': 90, 'max_foreign_cpu': 0,
                                    'min_free': bgperf2.UNSAMPLED_MIN_FREE}))

    written = json.loads((tmp_path / 'run.events.json').read_text())
    assert written['findings'] == doc['findings']
    assert written['findings']['limiting_component'] == TESTER


def test_an_unsampled_free_memory_sentinel_is_not_a_measurement():
    import bgperf2

    evidence = bgperf2.host_evidence({'min_free': bgperf2.UNSAMPLED_MIN_FREE,
                                      'memory': 64 * 1024 ** 3})

    assert evidence['min_free_bytes'] is None


def test_a_measured_injection_is_not_called_a_run_inside_one_poll():
    '''The traced-bgpdump2 shape: a five-second measured injection with none
    of the table inside it. Saying the run finished inside its polls would be
    false about the one interval it published.'''
    m = monitor([(float(at), 125 * at) for at in range(1, 9)],
                required_at=8.0)
    # `expected` is larger than the injector's table, which is the ordinary
    # MRT case: completion is the generator's own report, not a count.
    t = injector('a', [(1.0, dict(offered=0, expected=2000))]
                 + [(float(at), dict(offered=1000, expected=2000))
                    for at in range(2, 7)]
                 + [(7.0, dict(offered=1000, expected=2000,
                               send_complete=True,
                               reported_send_duration_s=1.4996))])

    result = derive_findings(artifact(m, [t]))

    assert 'no_dominant_interval' in names(result)
    assert result['reason'] == (
        'the generators were measured sending for 5.0s, but too little of '
        'the table crossed that interval to read it as their send')


def test_a_counter_reset_is_not_published_as_a_count():
    '''BIRD clears a protocol's route-change stats when the protocol
    restarts, so `offered_in_interval` is None rather than small -- and
    "only None of them crossed" would publish a shortfall that was an
    unreadable instrument.'''
    m = monitor([(float(at), 100 * at) for at in range(1, 13)],
                required_at=12.0)
    t = injector('a', [(1.0, dict(offered=0)),
                       (2.0, dict(offered=900)),
                       (3.0, dict(offered=400, send_complete=True))])

    result = derive_findings(artifact(m, [t]))

    assert result['decided_by'] == 'injection_boundary_unresolved'
    assert 'None' not in result['reason']
    assert result['reason'].startswith("a generator's counter reset mid-run")


def test_an_unreadable_count_at_completion_is_not_published_as_a_count():
    m = monitor([(float(at), 100 * at) for at in range(1, 13)],
                required_at=12.0)
    t = injector('a', [(1.0, dict(offered=0)),
                       (2.0, dict(offered=900)),
                       (3.0, dict(offered=None, send_complete=True))])

    result = derive_findings(artifact(m, [t]))

    assert result['decided_by'] == 'injection_boundary_unresolved'
    assert 'None' not in result['reason']


def test_the_tester_verdict_names_when_the_generators_stopped():
    '''`injection_s` is a span, not a point. A fleet that started late must
    not be described as having finished as early as its span is long.'''
    m = monitor([(float(at), 50 * at) for at in range(1, 22)],
                required_at=21.0)
    t = injector('a', [(float(at), dict(offered=0)) for at in range(1, 12)]
                 + [(float(at), dict(offered=100 * (at - 11)))
                    for at in range(12, 22)])

    result = derive_findings(artifact(m, [t]))

    assert result['limiting_component'] == TESTER
    assert '21.0s into the run' in result['reason']
    assert 'over a measured 9.0s' in result['reason']


def test_a_policy_that_raises_does_not_cost_the_run_its_evidence(
        tmp_path, bench_args, monkeypatch):
    '''The artifact preserves the evidence; the findings are an opinion about
    it. By the time the policy runs, this document is the only record that a
    converged run happened.'''
    import bgperf2

    bench_args.results_dir = str(tmp_path)
    bench_args.tester_type = 'bird'
    m = monitor([(1.0, 0), (2.0, 1000)], required_at=2.0)
    monkeypatch.setattr(bgperf2, 'derive_findings',
                        lambda *a, **kw: 1 / 0)

    doc = bgperf2.write_event_artifact(
        bench_args, list(m.events), 'run', 'converged')

    written = json.loads((tmp_path / 'run.events.json').read_text())
    assert written['events'] == doc['events']
    assert written['findings']['limiting_component'] == INCONCLUSIVE
    assert written['findings']['reason'].startswith(
        'the qualification policy failed: ZeroDivisionError')
