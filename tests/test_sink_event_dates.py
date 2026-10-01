'''The monitor's events dated to the sink's own log (measurement plan 7b).

Under `--monitor sink` the poll still decides *that* `monitor_first_prefix`,
`monitor_required_reached` and `monitor_last_change` happen; the sink's log
decides *when*, to the C line that showed the change, bounded by the line
before it. These cover the log's half (which lines date what), the conversion
and its refusals, the recorder's use of them, and the GoBGP path staying
exactly what it was.
'''

import importlib.util
import os
import time

import pytest

from conftest import REPO_ROOT

from measurements import (EventKind, MonitorEventRecorder, SinkDates,
                          monitor_metrics, sink_event_dates, unique_event)
from monitor import SinkMonitor
from sink import (SINK_CLOCK_OFFSET_LIMIT_NS, SINK_LOG_FORMAT, SinkLog,
                  SinkLogReader)

S = 10**9
HEADER = ('V 1000 {0} 0.1.0 (src 4eda4de2857a) gobgp/v4 v4.9.0 go1.25.14\n'
          'B 1001 1759300000000000000\n').format(SINK_LOG_FORMAT)


def fed(text, required=None):
    log = SinkLog(required)
    log.feed(text)
    return log


# -- the log ---------------------------------------------------------------

def test_each_event_is_its_c_line_bounded_by_the_line_before():
    log = fed(HEADER
              + 'S 2000 established inbound 1 10.10.0.2 1000 hold=90\n'
              + 'C 3000 40 1 0\n'
              + 'C 3010 90 2 0\n'
              + 'C 3020 120 3 0\n'
              + 'C 3030 150 4 0\n', required=100)
    # The first prefix arrived after the S line and by the first C line.
    assert log.first_prefix_at == (3000, 2000, 40)
    # 100 was crossed somewhere after the 90 line and by the 120 one.
    assert log.required_at == (3020, 3010, 120)
    assert log.changed_at == (3030, 3020, 150)
    section = log.sample(now_ns=3030)['sink']
    assert section['first_prefix_at'] == (3000, 2000, 40)
    assert section['required_at'] == (3020, 3010, 120)
    assert section['changed_at'] == (3030, 3020, 150)


def test_a_count_line_that_did_not_move_the_count_dates_nothing():
    # A re-announcement is an UPDATE, so it writes a C line; it is not a
    # change of the count, and the last change must stay where it was.
    log = fed(HEADER
              + 'C 3000 150 4 0\n'
              + 'H 4000 150 4 0\n'
              + 'C 5000 150 9 0\n')
    assert log.changed_at == (3000, 1001, 150)


def test_a_move_and_back_between_two_polls_is_still_a_change():
    log = fed(HEADER + 'C 3000 150 4 0\n' + 'C 3010 149 5 0\n'
              + 'C 3020 150 6 0\n')
    assert log.changed_at == (3020, 3010, 150)


def test_without_a_check_point_nothing_is_dated_to_one():
    log = fed(HEADER + 'C 3000 150 4 0\n')
    assert log.required_at is None


def test_a_check_point_of_zero_is_judged_as_the_poll_judges_it():
    # The poll calls `0 <= accepted` checked; the log must not read 0 as "no
    # check-point" and fall silent where the poll does not.
    log = fed(HEADER + 'C 3000 150 4 0\n', required=0)
    assert log.required_at == (3000, 1001, 150)


def test_a_crossing_the_session_lost_is_not_the_one_dated():
    log = fed(HEADER
              + 'C 3000 150 4 0\n'
              + 'C 3500 0 0 0\n'
              + 'S 3500 down inbound 1 EOF\n'
              + 'S 6000 established inbound 2 10.10.0.2 1000 hold=90\n'
              + 'C 7000 40 1 0\n'
              + 'C 7010 150 2 0\n', required=100)
    assert log.first_prefix_at == (7000, 6000, 40)
    assert log.required_at == (7010, 7000, 150)


def test_falling_below_the_check_point_re_arms_it():
    log = fed(HEADER + 'C 3000 150 4 0\n' + 'C 3010 90 5 0\n'
              + 'C 3020 110 6 0\n', required=100)
    assert log.required_at == (3020, 3010, 110)
    # The first prefix is still the start of the non-zero stretch.
    assert log.first_prefix_at == (3000, 1001, 150)


def test_an_inverted_pair_is_kept_as_read_for_the_recorder_to_refuse():
    # The sink stamps an UPDATE before it takes the log's lock, so a heartbeat
    # can be written between the two with a later date.
    log = fed(HEADER + 'H 3005 0 0 0\n' + 'C 3000 150 4 0\n')
    assert log.first_prefix_at == (3000, 3005, 150)


def on_the_host_clock():
    '''A header whose B line agrees with this host's clock, at ns 1001.'''
    real = time.time_ns() - time.monotonic_ns() + 1001
    return ('V 1000 {0} 0.1.0\nB 1001 {1}\n').format(SINK_LOG_FORMAT, real)


def test_a_sample_describes_the_log_as_of_its_own_stamp(tmp_path):
    path = tmp_path / 'sink.log'
    path.write_text(on_the_host_clock() + 'C 3000 40 1 0\n'
                    + 'C 3010 150 2 0\n' + 'H 4010 150 2 0\n')
    reader = SinkLogReader(str(path), required=100)
    sample = reader.sample(now_ns=3005)
    # The line written during the read, after the stamp, waits.
    assert sample['afi_safis'][0]['state']['accepted'] == 40
    assert sample['sink']['required_at'] is None
    sample = reader.sample(now_ns=4010)
    assert sample['afi_safis'][0]['state']['accepted'] == 150
    assert sample['sink']['required_at'] == (3010, 3000, 150)


def test_a_held_back_line_is_not_read_twice(tmp_path):
    path = tmp_path / 'sink.log'
    path.write_text(on_the_host_clock() + 'C 3000 40 1 0\n'
                    + 'C 3010 150 2 0\n')
    reader = SinkLogReader(str(path))
    reader.read(until_ns=3005)
    assert reader.log.accepted == 40
    reader.read(until_ns=3005)
    reader.read(until_ns=3005)
    log = reader.read()
    assert log.lines == 4
    assert log.malformed_lines == 0


def test_a_restarted_sink_dates_its_own_first_prefix_again():
    log = fed(HEADER + 'C 3000 150 4 0\n'
              + 'V 9000 {0} 0.1.0\n'.format(SINK_LOG_FORMAT)
              + 'B 9001 1759300000000000000\n'
              + 'C 9500 20 1 0\n', required=100)
    assert log.first_prefix_at == (9500, 9001, 20)
    assert log.required_at is None


def test_the_reader_keeps_its_check_point_across_a_replaced_log(tmp_path):
    path = tmp_path / 'sink.log'
    path.write_text(HEADER + 'C 3000 150 4 0\n')
    reader = SinkLogReader(str(path), required=100)
    assert reader.read().required_at == (3000, 1001, 150)
    replacement = tmp_path / 'new.log'
    replacement.write_text(HEADER + 'C 3000 120 4 0\n')
    os.replace(replacement, path)
    assert reader.read().required == 100
    assert reader.log.required_at == (3000, 1001, 120)


# -- the conversion ----------------------------------------------------------

def section(**kwargs):
    base = {'clock_offset_ns': 1500, 'first_prefix_at': (3 * S, 2 * S, 40),
            'required_at': (5 * S, 4 * S + 990_000_000, 120),
            'changed_at': (6 * S, 6 * S - 10_000_000, 150)}
    base.update(kwargs)
    return base


def test_a_gobgp_sample_has_no_dates():
    assert sink_event_dates(None, SINK_CLOCK_OFFSET_LIMIT_NS) is None
    assert sink_event_dates({}, SINK_CLOCK_OFFSET_LIMIT_NS) is None


def test_dates_are_seconds_on_the_host_clock():
    dates = sink_event_dates(section(), SINK_CLOCK_OFFSET_LIMIT_NS)
    assert dates.refused is None
    assert dates.first_prefix == (3.0, 2.0, 40)
    assert dates.required == (5.0, 4.99, 120)
    assert dates.last_change == (6.0, 5.99, 150)


def test_a_sink_with_no_clock_line_is_refused():
    dates = sink_event_dates(section(clock_offset_ns=None),
                             SINK_CLOCK_OFFSET_LIMIT_NS)
    assert dates.first_prefix is None
    assert 'no clock line' in dates.refused


def test_a_sink_on_another_clock_is_refused():
    dates = sink_event_dates(section(clock_offset_ns=-5 * S),
                             SINK_CLOCK_OFFSET_LIMIT_NS)
    assert dates.required is None
    assert '-5000.000 ms' in dates.refused


def test_the_pair_review_refuses_the_same_offset():
    # The script imports nothing from the project, so the two limits are
    # pinned together here: a pair review that passes a clock the run
    # refused to date by, or the reverse, reads one sink two ways.
    spec = importlib.util.spec_from_file_location(
        'monitor_pair_review',
        os.path.join(REPO_ROOT, 'scripts', 'monitor_pair_review.py'))
    review = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(review)
    assert review.CLOCK_OFFSET_LIMIT_NS == SINK_CLOCK_OFFSET_LIMIT_NS


# -- the recorder ------------------------------------------------------------

ORIGIN = 1.0


def recorder():
    return MonitorEventRecorder(ORIGIN, producer='bgperf_monitor',
                                sample_interval_s=1)


def test_the_events_are_the_sinks_lines_with_their_own_resolution():
    rec = recorder()
    dates = SinkDates(first_prefix=(2.31, 2.30, 40),
                      required=(4.52, 4.51, 120),
                      last_change=(4.62, 4.61, 150))
    rec.observe(3.0, 40, False, sink=SinkDates(
        first_prefix=(2.31, 2.30, 40), last_change=(2.31, 2.30, 40)))
    rec.observe(5.0, 150, True, sink=dates)
    rec.confirm_convergence(25.0)
    events = rec.events

    first = unique_event(events, EventKind.MONITOR_FIRST_PREFIX)
    assert first.monotonic_s == 2.31
    assert first.details['dated_by'] == 'sink_log'
    assert first.details['poll_resolution_s'] == pytest.approx(0.01)
    # The cadence of the poll that decided it stays, so every monitor event
    # carries the same keys.
    assert first.details['sample_interval_s'] == 1.0
    assert first.counters == {'accepted_prefixes': 40}

    required = unique_event(events, EventKind.MONITOR_REQUIRED_REACHED)
    assert required.monotonic_s == 4.52
    # The line's count, not the sample's: the sample saw 150.
    assert required.counters == {'accepted_prefixes': 120}

    last = unique_event(events, EventKind.MONITOR_LAST_CHANGE)
    assert last.monotonic_s == 4.62

    metrics = monitor_metrics(events)
    assert metrics['first_prefix_s'] == pytest.approx(1.31)
    assert metrics['first_prefix_resolution_s'] == pytest.approx(0.01)
    assert metrics['convergence_s'] == pytest.approx(3.52)
    assert metrics['convergence_resolution_s'] == pytest.approx(0.01)
    # Assurance ends on a poll's verdict, so the poll bounds it.
    assert metrics['assurance_resolution_s'] == pytest.approx(2.0)


def test_the_poll_still_decides_that_the_check_point_was_reached():
    # The log has dated the crossing, but the sample says not checked: no
    # event. The sink changes when an event is dated, never whether.
    rec = recorder()
    rec.observe(3.0, 150, False, sink=SinkDates(required=(2.5, 2.4, 120)))
    assert unique_event(rec.events, EventKind.MONITOR_REQUIRED_REACHED) is None


@pytest.mark.parametrize('line, why', [
    ((0.5, 0.4, 40), 'before the clock started'),
    ((3.5, 3.4, 40), 'after the sample that saw it'),
])
def test_a_line_outside_the_run_is_dated_by_the_poll(line, why):
    rec = recorder()
    rec.observe(3.0, 40, False, sink=SinkDates(first_prefix=line))
    first = unique_event(rec.events, EventKind.MONITOR_FIRST_PREFIX)
    assert first.monotonic_s == 3.0
    assert first.details['dated_by'] == 'poll'
    assert why in first.details['sink_dates_refused']
    assert first.details['poll_resolution_s'] == 2.0


def test_an_inverted_bound_is_refused_not_published_as_zero():
    rec = recorder()
    rec.observe(3.0, 40, False, sink=SinkDates(first_prefix=(2.5, 2.6, 40)))
    first = unique_event(rec.events, EventKind.MONITOR_FIRST_PREFIX)
    assert first.monotonic_s == 3.0
    assert first.details['dated_by'] == 'poll'
    assert 'dated later' in first.details['sink_dates_refused']


def test_equal_polls_move_the_last_change_only_on_a_dated_line():
    rec = recorder()
    rec.observe(3.0, 150, False, sink=SinkDates(
        first_prefix=(2.5, 2.4, 150), last_change=(2.5, 2.4, 150)))
    rec.observe(4.0, 150, False, sink=SinkDates(
        first_prefix=(2.5, 2.4, 150), last_change=(4.5, 4.4, 150)))
    # A line after the sample is refused, and two equal polls alone are no
    # evidence of a change: the last change stays where it was.
    last = unique_event(rec.events, EventKind.MONITOR_LAST_CHANGE)
    assert last.monotonic_s == 2.5


def test_refused_dates_fall_back_to_the_poll_and_say_why():
    rec = recorder()
    rec.observe(3.0, 40, True, sink=SinkDates(refused='the sink clock is off'))
    for kind in (EventKind.MONITOR_FIRST_PREFIX,
                 EventKind.MONITOR_REQUIRED_REACHED,
                 EventKind.MONITOR_LAST_CHANGE):
        event = unique_event(rec.events, kind)
        assert event.monotonic_s == 3.0
        assert event.details['sink_dates_refused'] == 'the sink clock is off'


def test_a_change_two_equal_polls_cannot_see_is_the_last_change():
    rec = recorder()
    rec.observe(3.0, 150, False, sink=SinkDates(
        first_prefix=(2.5, 2.4, 150), last_change=(2.5, 2.4, 150)))
    # Same count at the next poll, but the log saw it move and come back.
    rec.observe(4.0, 150, False, sink=SinkDates(
        first_prefix=(2.5, 2.4, 150), last_change=(3.7, 3.6, 150)))
    last = unique_event(rec.events, EventKind.MONITOR_LAST_CHANGE)
    assert last.monotonic_s == 3.7


def test_a_gobgp_run_is_dated_exactly_as_before():
    rec = recorder()
    rec.observe(3.0, 40, False)
    rec.observe(4.5, 150, True)
    for event in rec.events[1:]:
        assert 'dated_by' not in event.details
        assert 'sink_dates_refused' not in event.details
    required = unique_event(rec.events, EventKind.MONITOR_REQUIRED_REACHED)
    assert required.monotonic_s == 4.5
    assert required.details == {'sample_interval_s': 1.0,
                                'poll_resolution_s': 1.5}


# -- the monitor -------------------------------------------------------------

CONF = {
    'monitor': {'as': 1001, 'router-id': '10.10.0.2',
                'local-address': '10.10.0.2', 'check-points': [100]},
    'target': {'as': 1000, 'local-address': '10.10.0.1'},
}


def test_the_monitors_samples_carry_its_clock_offset(tmp_path):
    mon = SinkMonitor(str(tmp_path / 'monitor'), CONF['monitor'])
    mon.config = CONF
    assert mon.check_point() == 100
    mon.reader = SinkLogReader(os.path.join(mon.host_dir, mon.LOG_NAME),
                               required=mon.check_point())
    mono = time.monotonic_ns()
    real = time.time_ns()
    with open(os.path.join(mon.host_dir, mon.LOG_NAME), 'w') as f:
        f.write('V {0} {1} 0.1.0\nB {0} {2}\nC {0} 120 1 0\n'.format(
            mono, SINK_LOG_FORMAT, real))
    sample = mon.read_sample(time.monotonic())
    assert abs(sample['sink']['clock_offset_ns']) < SINK_CLOCK_OFFSET_LIMIT_NS
    dates = sink_event_dates(sample['sink'], SINK_CLOCK_OFFSET_LIMIT_NS)
    assert dates.refused is None
    assert dates.required[0] == mono / 1e9


def test_a_monitor_with_no_check_point_dates_none(tmp_path):
    mon = SinkMonitor(str(tmp_path / 'monitor'), CONF['monitor'])
    assert mon.check_point() is None
    mon.config = {'monitor': {}}
    assert mon.check_point() is None


def test_the_clock_offset_is_measured_once_per_sink_process(tmp_path,
                                                            monkeypatch):
    mon = SinkMonitor(str(tmp_path / 'monitor'), CONF['monitor'])
    mon.config = CONF
    mono = time.monotonic_ns()
    with open(os.path.join(mon.host_dir, mon.LOG_NAME), 'w') as f:
        f.write('V {0} {1} 0.1.0\nB {0} {2}\nC {0} 120 1 0\n'.format(
            mono, SINK_LOG_FORMAT, time.time_ns()))
    first = mon.read_sample(time.monotonic())['sink']['clock_offset_ns']
    # A realtime step mid-run moves no monotonic clock, and must not flip the
    # rest of the run to refused dating.
    real = time.time_ns
    monkeypatch.setattr(time, 'time_ns', lambda: real() + 5 * S)
    again = mon.read_sample(time.monotonic())['sink']['clock_offset_ns']
    assert again == first


def test_a_receiver_takes_no_check_point(tmp_path):
    from monitor import SinkReceiver
    rec = SinkReceiver(0, str(tmp_path / 'r0'), CONF['monitor'])
    rec.config = CONF
    assert rec.check_point() is None


def test_a_sink_clock_ahead_of_the_host_still_gives_a_count(tmp_path):
    # Its dates are refused; its count must not be. Holding back every line
    # dated after the stamp would hold back all of them, the V and B lines
    # included, and the run would wait forever for a monitor.
    path = tmp_path / 'sink.log'
    ahead = time.monotonic_ns() + 30 * S
    path.write_text('V {0} {1} 0.1.0\nB {0} {2}\nC {0} 120 1 0\n'.format(
        ahead, SINK_LOG_FORMAT, time.time_ns()))
    reader = SinkLogReader(str(path), required=100)
    sample = reader.sample(stale_after_ns=60 * S)
    assert sample['afi_safis'][0]['state']['accepted'] == 120
    assert not reader.clock_agrees()
    sample['sink']['clock_offset_ns'] = reader.clock_offset_ns()
    dates = sink_event_dates(sample['sink'], SINK_CLOCK_OFFSET_LIMIT_NS)
    assert 'ms from the host' in dates.refused


def test_an_event_is_never_dated_before_the_one_it_follows():
    # The first prefix's line is inverted and falls back to the poll; the
    # check-point's line in the same sample is fine, but earlier than that
    # poll date. It falls back too, rather than publish a first prefix after
    # the check-point.
    rec = recorder()
    rec.observe(3.0, 150, True, sink=SinkDates(
        first_prefix=(2.5, 2.6, 40), required=(2.7, 2.69, 150),
        last_change=(2.7, 2.69, 150)))
    events = rec.events
    first = unique_event(events, EventKind.MONITOR_FIRST_PREFIX)
    required = unique_event(events, EventKind.MONITOR_REQUIRED_REACHED)
    last = unique_event(events, EventKind.MONITOR_LAST_CHANGE)
    assert first.monotonic_s == 3.0
    assert required.monotonic_s == 3.0
    assert 'before monitor_first_prefix' in required.details['sink_dates_refused']
    assert last.monotonic_s == 3.0
    metrics = monitor_metrics(events)
    assert metrics['first_prefix_s'] <= metrics['convergence_s']
