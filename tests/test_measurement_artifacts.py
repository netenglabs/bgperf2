'''Controller integration tests for lifecycle-event artifacts.'''

import json
import time
from argparse import Namespace

import pytest

import bgperf2
from measurements import (EventKind, EventPhase, LifecycleEvent,
                          MonitorEventRecorder, TesterEventRecorder,
                          TesterOffering)


class FakeComponent:
    stop_monitoring = False


def test_legacy_queue_message_gets_a_boundary_monotonic_timestamp():
    assert bgperf2.monitor_sample_monotonic_s(
        {'time': 'legacy'}, fallback_clock=lambda: 12.5) == 12.5
    assert bgperf2.monitor_sample_monotonic_s(
        {'monotonic_s': 8.25}, fallback_clock=lambda: 99) == 8.25


def test_failed_finalization_persists_events_before_later_collection(
        tmp_path, monkeypatch):
    '''A failed fake run leaves evidence even if later collection also fails.'''
    args = Namespace(
        target='frr_c',
        label=None,
        neighbor_num=10,
        prefix_num=20000,
        tester_type='bird',
        results_dir=str(tmp_path),
    )
    recorder = MonitorEventRecorder(100, producer='bgperf_monitor')
    recorder.observe(116, accepted_prefixes=0)

    def fail_collection(*args, **kwargs):
        raise RuntimeError('fake provenance failure')

    monkeypatch.setattr(bgperf2, 'collect_provenance', fail_collection)

    with pytest.raises(RuntimeError, match='fake provenance failure'):
        bgperf2.finish_bench(
            args,
            {},
            [],
            time.time(),
            FakeComponent(),
            FakeComponent(),
            fail=True,
            lifecycle_events=recorder.events,
        )

    path = tmp_path / 'frr_c_bird_20000_10.events.json'
    artifact = json.loads(path.read_text())
    assert artifact['schema'] == 'bgperf2/measurement-events/v1alpha1'
    assert artifact['status'] == 'failed'
    assert artifact['measurements']['first_prefix_s'] is None
    assert [observed['event'] for observed in artifact['events']] == [
        'bench_clock_started']


def tester_recorder(producer='bgperf_bird_tester_1', origin_s=100.0):
    recorder = TesterEventRecorder(origin_s, producer, sample_interval_s=1.0)
    recorder.observe(origin_s + 1, {'p1': TesterOffering(
        established=True, expected=100, offered=40)})
    recorder.observe(origin_s + 3, {'p1': TesterOffering(
        established=True, expected=100, offered=100)})
    return recorder


def test_a_rejected_tester_sample_retires_its_recorder_not_the_run():
    '''A poll that the recorder cannot accept is a wiring fault. Raising out
    of the queue loop would throw away a run that is otherwise producing a
    result, so the recorder is dropped and the reason kept.'''
    recorder = tester_recorder()
    recorders = {'bgperf_bird_tester_1': recorder}
    errors = {}

    backwards = {'who': 'bgperf_bird_tester_1', 'monotonic_s': 101.0,
                 'tester_offering': {'p1': TesterOffering(
                     established=True, expected=100, offered=100)}}
    assert bgperf2.observe_tester_sample(backwards, recorders, errors) is False
    assert 'not monotonic' in errors['bgperf_bird_tester_1']

    # Still retired on the next well-formed sample: the recorder's own
    # bookkeeping is no longer trustworthy once it rejected one.
    later = dict(backwards, monotonic_s=110.0)
    assert bgperf2.observe_tester_sample(later, recorders, errors) is False


def test_a_sample_from_an_unpolled_producer_is_ignored():
    assert bgperf2.observe_tester_sample(
        {'who': 'bgperf_exabgp_tester_1', 'monotonic_s': 1.0,
         'tester_offering': {}}, {}, {}) is False


def test_tester_evidence_reaches_the_artifact(tmp_path, monkeypatch):
    args = Namespace(target='bird', label=None, neighbor_num=1,
                     prefix_num=100, tester_type='bird',
                     results_dir=str(tmp_path))
    monitor = MonitorEventRecorder(100.0, producer='bgperf_monitor')
    monitor.observe(102.0, accepted_prefixes=100, required_reached=True)
    monitor.confirm_convergence(105.0)
    tester = tester_recorder()
    monkeypatch.setattr(bgperf2, 'collect_provenance',
                        lambda *a, **k: (_ for _ in ()).throw(
                            RuntimeError('fake provenance failure')))

    with pytest.raises(RuntimeError, match='fake provenance failure'):
        bgperf2.finish_bench(
            args, {}, [], time.time(), FakeComponent(), FakeComponent(),
            lifecycle_events=monitor.events,
            tester_lifecycles={'bgperf_bird_tester_1': tester},
            tester_observation_errors={},
        )

    artifact = json.loads(
        (tmp_path / 'bird_bird_100_1.events.json').read_text())
    measured = artifact['testers']['bgperf_bird_tester_1']
    # Injection is the generator's own first-update-to-completion interval,
    # measured at the tester rather than inferred from the monitor.
    assert measured['injection_s'] == 2.0
    assert measured['offered_prefixes'] == 100
    assert measured['tester_startup_s'] == 1.0
    # BIRD 2.19 exposes no blocked-write counter, and that is recorded as
    # unavailable rather than as zero.
    assert measured['backpressure'] == {
        'available': False,
        'reason': 'generator reported no blocked-write counter'}
    assert 'observation_error' not in measured
    # The tester's events are merged into the one ordered stream, not kept in
    # a second timeline the reader has to align by hand.
    assert [e['event'] for e in artifact['events']] == [
        'bench_clock_started', 'tester_session_ready', 'tester_first_update',
        'monitor_first_prefix', 'monitor_required_reached',
        'monitor_last_change', 'tester_last_update', 'tester_complete',
        'convergence_confirmed']


def test_a_failed_observation_is_named_in_the_artifact(tmp_path, monkeypatch):
    args = Namespace(target='bird', label=None, neighbor_num=1,
                     prefix_num=100, tester_type='bird',
                     results_dir=str(tmp_path))
    monitor = MonitorEventRecorder(100.0, producer='bgperf_monitor')
    monkeypatch.setattr(bgperf2, 'collect_provenance',
                        lambda *a, **k: (_ for _ in ()).throw(
                            RuntimeError('fake provenance failure')))

    with pytest.raises(RuntimeError, match='fake provenance failure'):
        bgperf2.finish_bench(
            args, {}, [], time.time(), FakeComponent(), FakeComponent(),
            fail=True, lifecycle_events=monitor.events,
            tester_lifecycles={'bgperf_bird_tester_1': tester_recorder()},
            tester_observation_errors={
                'bgperf_bird_tester_1': 'tester sessions changed between polls'},
        )

    artifact = json.loads(
        (tmp_path / 'bird_bird_100_1.events.json').read_text())
    measured = artifact['testers']['bgperf_bird_tester_1']
    assert measured['observation_error'] == 'tester sessions changed between polls'
    # The events recorded before the fault are still published: partial
    # evidence with a stated reason beats a silently absent generator.
    assert measured['offered_prefixes'] == 100


def test_a_run_with_no_polled_generator_reports_no_tester_section(tmp_path,
                                                                  monkeypatch):
    args = Namespace(target='bird', label=None, neighbor_num=1,
                     prefix_num=100, tester_type='exabgp',
                     results_dir=str(tmp_path))
    monitor = MonitorEventRecorder(100.0, producer='bgperf_monitor')
    monkeypatch.setattr(bgperf2, 'collect_provenance',
                        lambda *a, **k: (_ for _ in ()).throw(
                            RuntimeError('fake provenance failure')))

    with pytest.raises(RuntimeError, match='fake provenance failure'):
        bgperf2.finish_bench(
            args, {}, [], time.time(), FakeComponent(), FakeComponent(),
            fail=True, lifecycle_events=monitor.events)

    artifact = json.loads(
        (tmp_path / 'bird_exabgp_100_1.events.json').read_text())
    assert 'testers' not in artifact


def test_a_poll_that_could_not_be_read_is_counted_not_swallowed():
    '''A silently dropped read leaves a null injection interval that reads
    exactly like a generator which was polled fine and never finished.'''
    failures = {}
    info = {'who': 'bgperf_bird_tester_1', 'monotonic_s': 3.0,
            'tester_offering_error': "RuntimeError('container is not running')"}

    bgperf2.note_tester_read_failure(info, failures)
    bgperf2.note_tester_read_failure(info, failures)

    assert failures['bgperf_bird_tester_1'] == {
        'polls': 2,
        'first_reason': "RuntimeError('container is not running')"}


def test_a_failed_read_does_not_retire_a_working_recorder():
    '''A read can fail while the container is still coming up and succeed for
    the rest of the run. Retiring the generator over that would throw away the
    evidence the poll exists to collect.'''
    recorder = tester_recorder()
    recorders = {'bgperf_bird_tester_1': recorder}
    errors, failures = {}, {}

    bgperf2.note_tester_read_failure(
        {'who': 'bgperf_bird_tester_1', 'monotonic_s': 3.0,
         'tester_offering_error': 'boom'}, failures)
    later = {'who': 'bgperf_bird_tester_1', 'monotonic_s': 110.0,
             'tester_offering': {'p1': TesterOffering(
                 established=True, expected=100, offered=100)}}

    assert bgperf2.observe_tester_sample(later, recorders, errors) is True
    events, evidence = bgperf2.tester_lifecycle_summary(recorders, errors, failures)
    assert evidence['bgperf_bird_tester_1']['read_failures']['polls'] == 1
    assert 'observation_error' not in evidence['bgperf_bird_tester_1']


def test_a_counter_reset_is_not_reported_as_a_sub_poll_injection(capsys):
    '''Both cases give a null rate, and they are opposites: one is an injection
    too fast to resolve, the other a long injection whose content is unknown.'''
    events = [
        LifecycleEvent(EventKind.BENCH_CLOCK_STARTED, 0.0, 'controller',
                       EventPhase.SETUP),
        LifecycleEvent(EventKind.TESTER_FIRST_UPDATE, 1.0, 'tester',
                       EventPhase.INJECTION,
                       counters={'offered_prefixes': 900}),
        LifecycleEvent(EventKind.TESTER_COMPLETE, 43.0, 'tester',
                       EventPhase.INJECTION,
                       counters={'offered_prefixes': 100}),
    ]

    bgperf2.print_tester_metrics(events, ['tester'])

    printed = capsys.readouterr().out
    assert 'counter was reset' in printed
    assert 'shorter than one poll' not in printed
    assert '42.0s' in printed
