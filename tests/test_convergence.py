'''Rules for deciding a run is done, stalled, or regressing.

A benchmark that crashes is obvious. One that quietly reports a wrong elapsed
time is not, and this is the code that decides it.
'''
import pytest

from convergence import (
    ASSURANCE_SAMPLES,
    ASSURANCE_SAMPLES_AFTER_CHECKPOINT,
    DROP_SAMPLES,
    NO_PROGRESS_DEADLINE_SECONDS,
    STUCK_SAMPLES,
    ConvergenceTracker,
)


def feed(tracker, count, elapsed_start=1, **kwargs):
    '''Push `count` identical samples, returning the last status.'''
    sample = {'recved': 1000, 'neighbors_checked': 5,
              'neighbors_received_full': 5, 'checked': False}
    sample.update(kwargs)
    status = None
    for i in range(count):
        status = tracker.update(elapsed_start + i, sample['recved'],
                                sample['neighbors_checked'],
                                sample['neighbors_received_full'],
                                sample['checked'])
    return status


def test_keeps_going_while_the_count_climbs():
    t = ConvergenceTracker()
    t.note_neighbors_checkpoint()
    for i in range(30):
        status = t.update(i + 1, recved=100 * i, neighbors_checked=5,
                          neighbors_received_full=5, checked=False)
        assert status == ConvergenceTracker.CONTINUE


def test_converges_after_the_count_holds_steady():
    t = ConvergenceTracker()
    t.note_neighbors_checkpoint()
    t.update(1, 1000, 5, 5, False)          # establish the count
    status = feed(t, ASSURANCE_SAMPLES - 1, elapsed_start=2)
    assert status == ConvergenceTracker.CONTINUE
    assert t.update(100, 1000, 5, 5, False) == ConvergenceTracker.CONVERGED


def test_checkpoint_shortens_the_assurance_window():
    t = ConvergenceTracker()
    t.note_neighbors_checkpoint()
    t.update(1, 1000, 5, 5, checked=True)
    assert t.assurance_samples == ASSURANCE_SAMPLES_AFTER_CHECKPOINT
    status = feed(t, ASSURANCE_SAMPLES_AFTER_CHECKPOINT, elapsed_start=2, checked=True)
    assert status == ConvergenceTracker.CONVERGED


def test_does_not_converge_until_neighbors_are_done():
    '''Without the neighbor checkpoint, a steady count is not enough -- more
    routes may still be on their way.
    '''
    t = ConvergenceTracker()
    t.update(1, 1000, 5, 5, False)
    assert feed(t, ASSURANCE_SAMPLES * 2, elapsed_start=2) == ConvergenceTracker.CONTINUE


def test_new_neighbor_finishing_restarts_the_clock():
    t = ConvergenceTracker()
    t.note_neighbors_checkpoint()
    t.update(1, 1000, 5, 5, False)
    feed(t, ASSURANCE_SAMPLES - 1, elapsed_start=2)
    # a sixth neighbor reports in; the steady-count streak must reset
    t.update(50, 1000, 6, 6, False)
    assert t.last_recved_count == 0
    assert feed(t, 2, elapsed_start=51, neighbors_checked=6) == ConvergenceTracker.CONTINUE


def test_fails_when_nothing_ever_arrives():
    '''The session never came up: fail at the deadline rather than waiting out
    STUCK_SAMPLES.
    '''
    t = ConvergenceTracker()
    status = t.update(NO_PROGRESS_DEADLINE_SECONDS + 1, recved=0,
                      neighbors_checked=0, neighbors_received_full=0, checked=False)
    assert status == ConvergenceTracker.FAILED
    assert 'stuck received count 0' in t.fail_msg


def test_no_progress_deadline_not_tripped_early():
    t = ConvergenceTracker()
    status = t.update(NO_PROGRESS_DEADLINE_SECONDS, 0, 0, 0, False)
    assert status == ConvergenceTracker.CONTINUE


def test_fails_when_the_count_stops_moving_for_too_long():
    t = ConvergenceTracker()
    t.update(1, 1000, 5, 5, False)
    status = feed(t, STUCK_SAMPLES, elapsed_start=2)
    assert status == ConvergenceTracker.FAILED
    assert 'stuck received count 1000' in t.fail_msg


def test_fails_on_a_sustained_significant_drop():
    t = ConvergenceTracker()
    t.update(1, 100000, 5, 5, False)
    status = None
    for i in range(DROP_SAMPLES):
        status = t.update(2 + i, 50000, 5, 5, False)   # 50% drop, well over the threshold
    assert status == ConvergenceTracker.FAILED
    assert 'dropping received count' in t.fail_msg


def test_tolerates_a_drop_too_small_to_matter():
    '''Under the 1% threshold, a wobble is not a regression.'''
    t = ConvergenceTracker()
    t.update(1, 100000, 5, 5, False)
    for i in range(DROP_SAMPLES * 2):
        status = t.update(2 + i, 99999, 5, 5, False)   # 0.001% drop
        assert status == ConvergenceTracker.CONTINUE


def test_drop_streak_resets_when_a_neighbor_drops_out():
    '''A falling finished-neighbor count explains the lost routes, so the
    regression streak restarts rather than failing the run.
    '''
    t = ConvergenceTracker()
    t.update(1, 100000, 40, 40, False)
    for i in range(DROP_SAMPLES * 2):
        # each sample has fewer finished neighbors than the one before it
        status = t.update(2 + i, 50000, 39 - i, 40, False)
        assert status == ConvergenceTracker.CONTINUE


def test_converges_when_the_count_settles_just_below_its_peak():
    '''A count that comes to rest slightly under an earlier peak is converged,
    not regressing.

    Regression used to be measured against the previous sample, so a count
    resting below the peak kept taking the regression branch and advanced
    neither the stability counter nor the stuck counter -- it could not
    converge and could not fail. Taken from a real 10-peer 1.05M-prefix MRT
    run that peaked at 973368, settled at 971957 (0.145% down, well under
    DROP_FRACTION) and hung there with the target already idle.
    '''
    t = ConvergenceTracker()
    for value in (973075, 973355, 973368, 971891):
        t.update(1, value, 10, 10, False)
    t.note_neighbors_checkpoint()

    status = None
    for i in range(ASSURANCE_SAMPLES + 5):
        status = t.update(10 + i, 971957, 10, 10, True)
        if status != ConvergenceTracker.CONTINUE:
            break
    assert status == ConvergenceTracker.CONVERGED


def test_a_big_drop_still_fails_once_the_checkpoint_is_set():
    '''A steady count far below its peak is route loss, not convergence.

    Every real run reaches the neighbor checkpoint, which shortens the
    assurance window to ASSURANCE_SAMPLES_AFTER_CHECKPOINT (5) -- fewer than
    the DROP_SAMPLES (10) the regression streak needs. Without a gate on how
    far below the peak the count is sitting, a run that lost half its routes
    and held there reported CONVERGED at sample 6, with the loss showing up
    only as a low 'received' column. None of the other drop tests set the
    checkpoint, so this path was uncovered.
    '''
    t = ConvergenceTracker()
    t.update(1, 100000, 5, 5, False)
    t.note_neighbors_checkpoint()

    status = None
    for i in range(DROP_SAMPLES * 2):
        status = t.update(2 + i, 50000, 5, 5, True)
        if status != ConvergenceTracker.CONTINUE:
            break
    assert status == ConvergenceTracker.FAILED
    assert 'dropping received count' in t.fail_msg


def test_a_recovering_count_is_not_failed():
    '''A count climbing back toward its peak is recovering, not regressing.

    A single dip -- a tester session flapping, say -- left the run only
    DROP_SAMPLES (about ten seconds) to get back within DROP_FRACTION of its
    peak, and it was failed while its count rose on every one of those samples.
    Predates the peak-based rewrite: the old comparison never updated
    last_recved inside the regression branch, so it was already an effective
    high-water mark and behaved the same way.
    '''
    t = ConvergenceTracker()
    t.update(1, 1_000_000, 5, 5, False)
    t.note_neighbors_checkpoint()
    t.update(2, 800_000, 4, 5, True)         # the flap

    recved = 800_000
    for i in range(DROP_SAMPLES * 3):
        recved += 5_000                       # climbing back
        status = t.update(3 + i, recved, 5, 5, True)
        assert status != ConvergenceTracker.FAILED, (
            'failed at {0} routes while the count was still rising'.format(recved))


def test_losing_a_peer_mid_run_still_fails():
    '''A peer that leaves and takes a fifth of the table with it is a failed
    run, not a smaller successful one.

    The dropout branch restarts the regression streak, but must not rebaseline
    the peak to the smaller table: doing so reported CONVERGED at the lower
    number as though nothing had happened, and the row looked comparable with
    runs that kept all their peers.
    '''
    t = ConvergenceTracker()
    t.update(1, 100000, 5, 5, False)
    t.note_neighbors_checkpoint()
    t.update(2, 80000, 4, 5, True)          # the sample where the peer goes

    status = None
    for i in range(DROP_SAMPLES * 3):
        status = t.update(3 + i, 80000, 4, 5, True)
        if status != ConvergenceTracker.CONTINUE:
            break
    assert status == ConvergenceTracker.FAILED


def test_sub_threshold_wobble_does_not_arm_the_drop_streak():
    '''Both halves of the regression rule must apply to the same samples.

    The streak counts only samples that are themselves past DROP_FRACTION. If
    harmless wobble armed it instead, a run could sit 0.1% under its peak for a
    while and then be failed by a single later sample past the threshold.
    '''
    t = ConvergenceTracker()
    t.update(1, 100000, 5, 5, False)
    for i in range(DROP_SAMPLES * 2):
        assert t.update(2 + i, 99999, 5, 5, False) == ConvergenceTracker.CONTINUE
    assert t.less_last_received == 0


def test_a_count_resting_below_its_peak_can_still_go_stuck():
    '''The same path must not lose the stuck check: with no neighbor
    checkpoint, a count parked under its peak has to fail rather than poll
    forever.
    '''
    t = ConvergenceTracker()
    t.update(1, 100000, 5, 5, False)
    status = None
    for i in range(STUCK_SAMPLES + 2):
        status = t.update(2 + i, 99999, 5, 5, False)   # 0.001%, under DROP_FRACTION
        if status == ConvergenceTracker.FAILED:
            break
    assert status == ConvergenceTracker.FAILED
    assert 'stuck received count' in t.fail_msg


def test_drop_streak_accumulates_when_neighbor_count_is_steady():
    '''Routes disappearing with no change in finished neighbors is unexplained,
    and after DROP_SAMPLES of it the run is failed.
    '''
    t = ConvergenceTracker()
    t.update(1, 100000, 5, 5, False)
    statuses = [t.update(2 + i, 50000, 5, 5, False) for i in range(DROP_SAMPLES)]
    assert statuses[-1] == ConvergenceTracker.FAILED
    assert ConvergenceTracker.FAILED not in statuses[:-1]
