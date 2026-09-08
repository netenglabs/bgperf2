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
    WITNESS_CARRY_SAMPLES,
    WITNESS_EXCUSED_LIMIT,
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


# --- the target's own table as a second witness ---------------------------
#
# The monitor is one BGP session's view of the target, so when its count falls
# there is nothing to check it against. These pin the rule that reads the
# target's own gauge beside it: a decline in what the target *exports* is not
# a decline in what it *holds*.

def feed_witness(tracker, count, recved, best_paths, first_at=1.0,
                 neighbors_checked=10, checked=True, frozen_at=None):
    '''Push `count` samples carrying a witness, returning the last status.

    `frozen_at` pins every reading to one timestamp, which is what a target
    poll thread that died looks like from the monitor loop.
    '''
    status = None
    for i in range(count):
        at = frozen_at if frozen_at is not None else first_at + i
        status = tracker.update(int(first_at) + i, recved, neighbors_checked,
                                neighbors_checked, checked,
                                table_witness={'best_paths': best_paths},
                                witness_monotonic_s=at)
    return status


def test_a_settled_decline_the_target_did_not_follow_is_not_a_loss():
    '''The Phase 6 MRT shape: the monitor settles 1.5% below its own peak while
    the target's table is at its peak and stays there. What fell is what the
    target exports, not what it holds, so this converges rather than failing on
    the drop streak.'''
    t = ConvergenceTracker()
    t.note_neighbors_checkpoint()
    feed_witness(t, 1, 1000000, 1020000)
    status = feed_witness(t, ASSURANCE_SAMPLES_AFTER_CHECKPOINT + 1,
                          985000, 1020000, first_at=2.0)
    assert status == ConvergenceTracker.CONVERGED
    rule = t.witness_rule()
    assert rule['converged_below_monitor_peak'] is True
    assert rule['excused_samples'] >= 1
    assert round(rule['max_excused_monitor_decline'], 3) == 0.015
    assert rule['max_witness_decline_while_excusing'] == 0.0


def test_a_decline_the_target_followed_still_fails():
    '''A genuine loss takes the target's own count down with it, by a
    comparable amount, so it is past the same threshold and is not excused.'''
    t = ConvergenceTracker()
    t.note_neighbors_checkpoint()
    feed_witness(t, 1, 1000000, 1020000)
    status = feed_witness(t, DROP_SAMPLES, 985000, 1004000, first_at=2.0)
    assert status == ConvergenceTracker.FAILED
    assert t.witness_rule() is None


def test_a_withheld_witness_decides_nothing():
    '''best_paths is None whenever a peering did not report, which is what a
    session still coming up or a partial CLI read produces. A withheld sum is
    not evidence that the table is intact.'''
    t = ConvergenceTracker()
    t.note_neighbors_checkpoint()
    feed_witness(t, 1, 1000000, 1020000)
    status = feed_witness(t, DROP_SAMPLES, 985000, None, first_at=2.0)
    assert status == ConvergenceTracker.FAILED


def test_an_undated_witness_decides_nothing():
    '''A reading with no timestamp cannot be shown to be current, and a
    reading that cannot be shown to be current is exactly what a dead poll
    thread supplies.'''
    t = ConvergenceTracker()
    t.note_neighbors_checkpoint()
    t.update(1, 1000000, 10, 10, True,
             table_witness={'best_paths': 1020000}, witness_monotonic_s=None)
    status = None
    for i in range(DROP_SAMPLES):
        status = t.update(2 + i, 985000, 10, 10, True,
                          table_witness={'best_paths': 1020000},
                          witness_monotonic_s=None)
    assert status == ConvergenceTracker.FAILED


def test_a_frozen_witness_cannot_carry_a_run():
    '''One reading may not decide a verdict by itself. A target poll that dies
    as the count falls leaves the monitor loop repeating its last reading
    forever; the run still fails, later than it would have.'''
    t = ConvergenceTracker()
    t.note_neighbors_checkpoint()
    feed_witness(t, 1, 1000000, 1020000)
    status = feed_witness(t, DROP_SAMPLES + WITNESS_CARRY_SAMPLES + 2,
                          985000, 1020000, first_at=2.0, frozen_at=2.0)
    assert status == ConvergenceTracker.FAILED


def test_the_witness_is_judged_against_its_own_peak():
    '''The target's gauge gets the high-water treatment the monitor's count
    gets: a table that grew and then shrank has lost routes, however steady it
    looks afterwards.'''
    t = ConvergenceTracker()
    t.note_neighbors_checkpoint()
    feed_witness(t, 1, 1000000, 1020000)
    status = feed_witness(t, DROP_SAMPLES, 985000, 1000000, first_at=2.0)
    assert status == ConvergenceTracker.FAILED


def test_a_target_that_holds_nothing_attests_to_nothing():
    '''A gauge of 0 with no peak behind it is a target that has not started
    receiving, not a table that survived intact.'''
    t = ConvergenceTracker()
    holds, declined = t._witness_holds_table({'best_paths': 0}, 1.0)
    assert holds is False
    assert declined is None


def test_the_witness_rule_is_absent_when_it_changed_nothing():
    '''A run whose count never fell far enough to need the witness writes the
    document it always wrote.'''
    t = ConvergenceTracker()
    t.note_neighbors_checkpoint()
    status = feed_witness(t, ASSURANCE_SAMPLES_AFTER_CHECKPOINT + 1,
                          1000000, 1020000)
    assert status == ConvergenceTracker.CONVERGED
    assert t.witness_rule() is None


def test_a_run_with_no_witness_is_decided_exactly_as_before():
    '''Every daemon but BIRD reports no gauge at all, and those runs must keep
    the verdicts they had.'''
    t = ConvergenceTracker()
    t.note_neighbors_checkpoint()
    t.update(1, 1000000, 10, 10, True)
    status = None
    for i in range(DROP_SAMPLES):
        status = t.update(2 + i, 985000, 10, 10, True)
    assert status == ConvergenceTracker.FAILED
    assert t.witness_rule() is None


def test_the_witness_cannot_converge_a_run_the_monitor_stopped_seeing():
    '''A monitor session that lost most of the table while the target kept it
    looks, from the target's side, exactly like the export change this rule
    excuses. The sample's own check-point flag is what separates them, so a
    count parked far below the check-point is not converged however intact the
    target is. Deliberately not a count of zero: that is refused a step
    earlier, and testing this gate through it would test the other guard.'''
    t = ConvergenceTracker()
    t.note_neighbors_checkpoint()
    feed_witness(t, 1, 1000000, 1020000, checked=True)
    status = feed_witness(t, ASSURANCE_SAMPLES + 5, 500000, 1020000,
                          first_at=2.0, checked=False)
    assert status != ConvergenceTracker.CONVERGED

    # The control: the same samples with the monitor at or above the
    # check-point are exactly what the rule is for, and do converge.
    t = ConvergenceTracker()
    t.note_neighbors_checkpoint()
    feed_witness(t, 1, 1000000, 1020000, checked=True)
    assert feed_witness(t, ASSURANCE_SAMPLES_AFTER_CHECKPOINT + 1, 500000,
                        1020000, first_at=2.0, checked=True) \
        == ConvergenceTracker.CONVERGED


def test_a_monitor_count_of_zero_is_not_an_export_change():
    '''Zero is not a decline in what the target exports -- it is the absence of
    the session the run is measured through, which the target-side witness
    cannot see. Observed for real: a pass whose target container went away
    mid-run carried its last reading and excused a "100% export change".'''
    t = ConvergenceTracker()
    t.note_neighbors_checkpoint()
    feed_witness(t, 1, 1000000, 1020000)
    # `checked` goes with it: the monitor's flag is its own answer to "am I at
    # or above the check-point", so a sample of 0 is never a checked one.
    status = feed_witness(t, DROP_SAMPLES, 0, 1020000, first_at=2.0,
                          checked=False)
    assert status == ConvergenceTracker.FAILED
    assert t.witness_rule() is None


def test_a_continuously_declining_monitor_still_fails():
    '''The witness may carry a run; it may not carry it forever.

    A count that declines a little on every sample resets the drop streak
    through the excuse *and* the stability counter through changing, so before
    WITNESS_EXCUSED_LIMIT such a run had no terminating path at all -- and
    bench() has no run timeout, so under batch() it is the rest of the matrix.
    '''
    t = ConvergenceTracker()
    t.note_neighbors_checkpoint()
    feed_witness(t, 1, 1000000, 1020000)
    # Past DROP_FRACTION and then bleeding away a little on every sample.
    recved = 985000
    status = None
    for i in range(WITNESS_EXCUSED_LIMIT + 5):
        recved -= 100
        status = t.update(2 + i, recved, 10, 10, False,
                          table_witness={'best_paths': 1020000},
                          witness_monotonic_s=2.0 + i)
        if status != ConvergenceTracker.CONTINUE:
            break
    assert status == ConvergenceTracker.FAILED
    # Named for what it is: the target held its table and the session the run
    # is measured through kept losing it. A stuck count means the opposite.
    assert 'declining' in t.fail_msg and '1020000' in t.fail_msg


def test_an_excused_decline_that_settles_never_approaches_the_limit():
    '''The MRT shape: excused while it settles, then flat and converged. The
    limit counts consecutive samples for exactly this reason.'''
    t = ConvergenceTracker()
    t.note_neighbors_checkpoint()
    feed_witness(t, 1, 1000000, 1020000)
    status = feed_witness(t, ASSURANCE_SAMPLES_AFTER_CHECKPOINT + 1,
                          985000, 1020000, first_at=2.0)
    assert status == ConvergenceTracker.CONVERGED
    assert t.witness_excused_streak < WITNESS_EXCUSED_LIMIT


def test_a_verdict_needs_a_reading_taken_on_the_sample_that_decides_it():
    '''A witness that freezes partway through the assurance window is still
    inside the carry bound when the window closes, so the bound alone does not
    keep a stale reading out of the verdict -- and a dead target poll is
    exactly what freezes it.'''
    t = ConvergenceTracker()
    t.note_neighbors_checkpoint()
    feed_witness(t, 1, 1000000, 1020000)
    # Three flat samples with the witness being re-read...
    feed_witness(t, 3, 985000, 1020000, first_at=2.0)
    # ...then the target poll dies and the same reading is carried.
    status = feed_witness(t, ASSURANCE_SAMPLES_AFTER_CHECKPOINT, 985000,
                          1020000, first_at=5.0, frozen_at=5.0)
    assert status != ConvergenceTracker.CONVERGED
    # One fresh read is enough: the count is already flat, so nothing else is
    # waiting on it.
    assert t.update(20, 985000, 10, 10, True,
                    table_witness={'best_paths': 1020000},
                    witness_monotonic_s=99.0) == ConvergenceTracker.CONVERGED
