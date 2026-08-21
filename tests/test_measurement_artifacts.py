'''Controller integration tests for lifecycle-event artifacts.'''

import json
import time
from argparse import Namespace

import pytest

import bgperf2
from measurements import MonitorEventRecorder


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
