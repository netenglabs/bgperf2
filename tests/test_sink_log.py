'''The host-side reader of the sink's log (measurement plan Phase 7a).

The writer's half -- coalescing, heartbeats, flushing a pending count before
an immediate one -- is covered by the Go tests in `sink/log_test.go`. These
cover the reader: that it takes the count the log states, stops at the last
complete line, refuses a log it cannot read as a count instead of reporting a
number from it, and says when the sink has stopped.
'''

import os

import pytest

from sink import (SINK_LOG_FORMAT, SinkLog, SinkLogError, SinkLogReader)

S = 10**9
HEADER = ('V 1000 {0} 0.1.0 (src 4eda4de2857a) gobgp/v4 v4.9.0 go1.25.14\n'
          'B 1001 1759300000000000000\n').format(SINK_LOG_FORMAT)


def fed(text):
    log = SinkLog()
    log.feed(text)
    return log


def accepted(sample):
    return sample['afi_safis'][0]['state']['accepted']


def test_the_count_is_the_last_count_line():
    log = fed(HEADER
              + 'S 2000 established inbound 1 10.10.0.2 1000 hold=90\n'
              + 'C 3000 100 4 0\n'
              + 'C 4000 250 9 0\n'
              + 'E 4000 250 9\n'
              + 'H 5000 250 9 0\n')
    sample = log.sample(now_ns=5000)
    assert accepted(sample) == 250
    assert sample['state']['session_state'] == 'established'
    assert sample['sink']['count_ns'] == 4000
    assert sample['sink']['eor_ns'] == 4000
    assert sample['sink']['updates'] == 9
    assert log.version == '0.1.0 (src 4eda4de2857a) gobgp/v4 v4.9.0 go1.25.14'


def test_zero_is_present_not_omitted():
    # GoBGP omitted `accepted` until it held something; the sink always says.
    assert accepted(fed(HEADER).sample(now_ns=1001)) == 0


def test_a_session_drop_is_a_zero_and_not_established():
    log = fed(HEADER
              + 'S 2000 established outbound 1 10.10.0.2 1000 hold=90\n'
              + 'C 3000 500 3 1\n'
              + 'C 3500 0 0 0\n'
              + 'S 3500 down outbound 1 EOF\n')
    sample = log.sample(now_ns=4000)
    assert accepted(sample) == 0
    assert sample['state']['session_state'] == 'idle'


def test_a_lost_collision_does_not_end_the_held_session():
    log = fed(HEADER
              + 'S 2000 established inbound 1 10.10.0.2 1000 hold=90\n'
              + 'S 2100 connected outbound 2 10.10.0.2:179\n'
              + 'S 2200 down outbound 2 connection collision\n'
              # The same direction as the held session, and still not it: a
              # target retrying before its old session's hold timer expired.
              + 'S 2250 connected inbound 3 10.10.0.2:40000\n'
              + 'S 2260 down inbound 3 connection collision\n')
    assert log.sample(now_ns=2260)['state']['session_state'] == 'established'
    log.feed_line('S 2300 dropped inbound 1 collision')
    assert log.sample(now_ns=2300)['state']['session_state'] == 'idle'


def test_a_session_line_without_its_connection_is_malformed():
    log = fed(HEADER + 'S 2000 established inbound\n')
    with pytest.raises(SinkLogError, match='without a connection'):
        log.sample(now_ns=2000)


def test_a_restarted_sink_starts_from_nothing():
    log = fed(HEADER + 'S 2000 established inbound 1 x\nC 3000 700 5 1\n'
              + HEADER.replace('1000', '9000').replace('1001 ', '9001 '))
    sample = log.sample(now_ns=9001)
    assert accepted(sample) == 0
    assert sample['state']['session_state'] == 'idle'
    assert sample['sink']['processes'] == 2
    # The old process's last line to the new one's first is time the
    # instrument was not running, and it is kept.
    assert sample['sink']['max_line_gap_ns'] == 6000


def test_heartbeat_gaps_are_kept_even_when_the_sink_recovered():
    log = fed(HEADER + 'H {0} 0 0 0\nH {1} 0 0 0\n'.format(1001 + S, 1001 + 6 * S))
    # Fresh at this sample, so nothing refuses it -- but the gap is published.
    sample = log.sample(now_ns=1001 + 6 * S)
    assert sample['sink']['max_line_gap_ns'] == 5 * S


def test_a_log_that_stops_growing_is_a_stopped_sink():
    log = fed(HEADER + 'C 2000 10 1 0\n')
    assert accepted(log.sample(now_ns=2000 + 3 * S)) == 10
    with pytest.raises(SinkLogError, match='stopped'):
        log.sample(now_ns=2001 + 3 * S)


def test_nothing_written_yet_is_not_a_zero():
    with pytest.raises(SinkLogError, match='not written'):
        SinkLog().sample(now_ns=0)


@pytest.mark.parametrize('line, why', [
    ('C 3000 10 1', 'fields'),
    ('C 3000 ten 1 0', 'non-integer'),
    ('X 3000 1', 'unknown line kind'),
    ('C 3k 10 1 0', 'timestamp'),
    ('H 3000 11 1 0', 'heartbeat disagrees'),
    ('E 3000 11 1', 'End-of-RIB disagrees'),
    ('garbage', 'not a sink log line'),
])
def test_a_malformed_line_refuses_the_count(line, why):
    log = fed(HEADER + 'C 2000 10 1 0\n' + line + '\n')
    with pytest.raises(SinkLogError, match=why):
        log.sample(now_ns=3000)


def test_another_format_is_refused():
    with pytest.raises(SinkLogError, match='log format is not'):
        fed('V 1000 2 0.2.0\nC 2000 10 1 0\n').sample(now_ns=2000)


def test_a_count_before_the_format_line_is_refused():
    with pytest.raises(SinkLogError, match='before the format line'):
        fed('C 2000 10 1 0\n').sample(now_ns=2000)


def test_refused_messages_are_counted_not_fatal():
    log = fed(HEADER + 'M 2000 malformed attribute\nC 2100 1 1 0\n')
    sample = log.sample(now_ns=2100)
    assert sample['sink']['refused_messages'] == 1
    assert log.last_refused == 'malformed attribute'


def test_clock_offset_is_the_difference_of_the_two_offsets():
    log = fed(HEADER)
    sink_offset = 1759300000000000000 - 1001
    assert log.clock_offset_ns(1759300000000000000 + 5, 1001 + 5) == 0
    assert log.clock_offset_ns(sink_offset + 7 + 2 * S, 2 * S) == -7
    assert SinkLog().clock_offset_ns(1, 1) is None


def write(path, text, mode='a'):
    with open(path, mode) as f:
        f.write(text)


def test_reader_stops_at_the_last_complete_line(tmp_path):
    path = tmp_path / 'sink.log'
    write(path, HEADER + 'C 2000 10 1 0\nC 3000 2')
    reader = SinkLogReader(str(path))
    assert accepted(reader.sample(now_ns=3000)) == 10
    # The half line is completed, not lost and not read as `2`.
    write(path, '50 2 0\n')
    assert accepted(reader.sample(now_ns=3000)) == 250


def test_reader_reads_only_what_was_appended(tmp_path):
    path = tmp_path / 'sink.log'
    write(path, HEADER + 'C 2000 10 1 0\n')
    reader = SinkLogReader(str(path))
    reader.read()
    lines = reader.log.lines
    reader.read()
    assert reader.log.lines == lines
    write(path, 'C 2500 20 2 0\n')
    reader.read()
    assert reader.log.lines == lines + 1


def test_reader_starts_over_on_a_replaced_log(tmp_path):
    path = tmp_path / 'sink.log'
    write(path, HEADER + 'C 2000 10 1 0\n')
    reader = SinkLogReader(str(path))
    assert accepted(reader.sample(now_ns=2000)) == 10
    # A replacement longer than the saved offset: only the inode tells. It is
    # written beside the old one and renamed over it, so the two exist at once
    # and cannot share an inode -- an unlink-then-create may be handed the
    # freed one back, and that case is the one stat() cannot see.
    write(tmp_path / 'new.log', HEADER + 'C 2000 77 1 0\n' + 'H 2001 77 1 0\n' * 4)
    os.replace(tmp_path / 'new.log', path)
    assert accepted(reader.sample(now_ns=2001)) == 77
    write(path, HEADER, mode='w')
    assert accepted(reader.sample(now_ns=1001)) == 0


def test_reader_bounds_one_read_and_resumes(tmp_path, monkeypatch):
    monkeypatch.setattr(SinkLogReader, 'READ_BLOCK', 64)
    monkeypatch.setattr(SinkLogReader, 'READ_MAX', 128)
    path = tmp_path / 'sink.log'
    write(path, HEADER + ''.join('C {0} {1} {1} 0\n'.format(2000 + i, i)
                                 for i in range(1, 41)))
    reader = SinkLogReader(str(path))
    first = accepted(reader.read().sample(now_ns=2040))
    assert 0 < first < 40
    while reader.log.lines < 42:
        reader.read()
    assert accepted(reader.sample(now_ns=2040)) == 40


def test_reader_skips_a_block_with_no_line_end(tmp_path, monkeypatch):
    monkeypatch.setattr(SinkLogReader, 'READ_BLOCK', 64)
    path = tmp_path / 'sink.log'
    write(path, HEADER + 'M 1500 ' + 'x' * 200 + '\nC 2000 5 1 0\n')
    reader = SinkLogReader(str(path))
    for _ in range(10):
        reader.read()
    # Skipped, not re-read forever -- and not trusted either.
    assert reader.log.lines >= 2
    with pytest.raises(SinkLogError, match='no line end'):
        reader.sample(now_ns=2000)


def test_a_same_inode_replacement_is_caught_by_its_own_contents(tmp_path):
    # The case neither stat() check can see: the log rewritten in place,
    # same inode, longer than the saved offset. The reader resumes mid-file
    # and misses the new count
    # line -- and the heartbeat that restates it refuses the sample rather
    # than letting the old count stand.
    path = tmp_path / 'sink.log'
    write(path, HEADER + 'C 2000 10 1 0\n')
    reader = SinkLogReader(str(path))
    reader.read()
    write(path, HEADER + 'C 2000 77 1 0\n' + 'H 2001 77 1 0\n' * 4, mode='w')
    with pytest.raises(SinkLogError, match='heartbeat disagrees'):
        reader.sample(now_ns=2001)


def test_an_unreadable_log_raises(tmp_path):
    with pytest.raises(OSError):
        SinkLogReader(str(tmp_path / 'missing.log')).read()


def test_read_all_reads_past_one_bounded_read(tmp_path, monkeypatch):
    '''Found in review: the end-of-run evidence used a single bounded read
    and described only the log's first READ_MAX bytes.'''
    monkeypatch.setattr(SinkLogReader, 'READ_MAX', 128)
    monkeypatch.setattr(SinkLogReader, 'READ_BLOCK', 128)
    path = tmp_path / 'sink.log'
    lines = ''.join('C {0} {1} {1} 0\n'.format(2000 + i, i) for i in range(1, 40))
    path.write_text(HEADER + lines)
    assert SinkLogReader(str(path)).read().accepted < 39
    assert SinkLogReader(str(path)).read_all().accepted == 39


def test_a_restart_does_not_erase_a_lost_session():
    log = fed(HEADER
              + 'S 2000 established inbound 1 x\n'
              + 'S 2001 down inbound 1 eof\n'
              + 'V 3000 {0} restarted\n'.format(SINK_LOG_FORMAT))
    assert log.processes == 2
    assert log.sessions_lost == 1


def test_session_counts_share_one_scope_across_a_restart():
    '''Found in review: established reset on a restart while lost did not, so
    a session that came back read as the only session, lost.'''
    log = fed(HEADER
              + 'S 2000 established inbound 1 x\n'
              + 'M 2001 bad update\n'
              + 'V 3000 {0} restarted\n'.format(SINK_LOG_FORMAT)
              + 'S 3001 established outbound 1 x\n')
    assert log.sessions_established == 2
    # held when its process ended
    assert log.sessions_lost == 1
    assert log.refused_messages == 1
    assert log.session is not None
