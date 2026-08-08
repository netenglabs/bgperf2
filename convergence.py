# Convergence detection for a benchmark run.
#
# Deciding when a run is "done" is the subtlest logic in bgperf2. The naive
# check -- stop when received == expected -- only works for synthetic prefix
# generation. With MRT playback the total unique prefix count is unknown because
# peers' tables overlap, and with filtering enabled the accepted count is
# deliberately lower than what was sent. So instead of comparing against a
# target number, we wait for the count to go *stable*.
#
# This lives apart from bench() so the rules can be tested without Docker.

# A run is converged once the received count has been unchanged for this many
# consecutive samples (samples arrive about once a second).
ASSURANCE_SAMPLES = 20

# ...but only this many if the configured check-point was already reached, since
# we already know enough prefixes arrived.
ASSURANCE_SAMPLES_AFTER_CHECKPOINT = 5

# A count that stops moving for this long is stuck, not converging. High because
# under heavy load some stacks genuinely pause this long.
STUCK_SAMPLES = 600

# A sustained drop in the received count means the target is losing routes.
# Both conditions must hold: enough consecutive drops, and a big enough one.
DROP_SAMPLES = 10
DROP_FRACTION = 0.01

# If nothing at all has arrived by this point, fail fast instead of waiting out
# STUCK_SAMPLES -- it means the session never came up.
NO_PROGRESS_DEADLINE_SECONDS = 15


class ConvergenceTracker(object):
    '''Tracks whether a benchmark has converged, stalled, or regressed.

    Fed one sample per monitor poll via update(), which returns CONTINUE,
    CONVERGED, or FAILED. On FAILED, fail_msg explains why.
    '''

    CONTINUE = 'continue'
    CONVERGED = 'converged'
    FAILED = 'failed'

    def __init__(self):
        # True once the monitor has seen at least the configured check-point.
        self.recved_checkpoint = False
        # True once every tester neighbor has sent everything it was going to.
        self.neighbors_checkpoint = False
        self.last_recved = 0
        # Highest received count seen so far; regressions are judged against
        # this rather than the previous sample.
        self.peak_recved = 0
        # Consecutive samples with an unchanged received count.
        self.last_recved_count = 0
        self.last_neighbors_checked = 0
        # Consecutive samples where the received count went backwards.
        self.less_last_received = 0
        self.fail_msg = None

    @property
    def assurance_samples(self):
        '''How long the count must hold steady before we call it converged.'''
        if self.recved_checkpoint:
            return ASSURANCE_SAMPLES_AFTER_CHECKPOINT
        return ASSURANCE_SAMPLES

    def note_neighbors_checkpoint(self):
        '''Called when the target reports every neighbor has finished sending.'''
        self.neighbors_checkpoint = True

    def update(self, elapsed_seconds, recved, neighbors_checked,
               neighbors_received_full, checked):
        '''Fold in one monitor sample and return the resulting status.'''
        previous_recved = self.last_recved
        # Regression is measured against the high-water mark, not the previous
        # sample. Comparing against the previous sample means a count that
        # settles one step below its peak keeps comparing equal afterwards, so
        # the streak stops growing and a real slide is missed.
        if recved > self.peak_recved:
            self.peak_recved = recved
            self.less_last_received = 0

        dropped = ((self.peak_recved - recved) / self.peak_recved
                   if self.peak_recved else 0)

        # Both halves of the regression rule are evaluated on the same samples:
        # a streak counts only samples that are themselves a big enough drop.
        # Counting every sample below the peak instead would let harmless
        # sub-threshold wobble arm the streak, so a single later sample past
        # the threshold would fail the run instantly.
        if dropped > DROP_FRACTION:
            if recved > previous_recved:
                # Climbing back toward the peak is recovery, not regression.
                # Without this a run that dipped once -- a tester session
                # flapping, say -- had DROP_SAMPLES (about 10s) to get back
                # within 1% of its peak or it was failed while its count was
                # rising on every single sample. Predates the peak-based
                # rewrite: the old comparison never updated last_recved inside
                # this branch, so it was already an effective high-water mark.
                self.less_last_received = 0
            # If the number of finished neighbors also went down, a peer
            # dropped out mid-sample and the loss is explained *for now*, so
            # the streak restarts. The peak is deliberately NOT rebaselined to
            # the smaller table: a peer that leaves and takes 20% of the routes
            # with it is a failed run, and rebaselining reported it CONVERGED
            # at the lower number as though nothing had happened.
            elif neighbors_checked >= self.last_neighbors_checked:
                self.less_last_received += 1
            else:
                self.less_last_received = 0
            if self.less_last_received >= DROP_SAMPLES:
                self.fail_msg = (f"FAILED: dropping received count {recved} "
                                 f"neighbors_checked {neighbors_checked}")
                return self.FAILED
        else:
            self.less_last_received = 0

        # Stability is tracked on every sample, including ones below the peak.
        # This used to sit behind the regression branch, so a count that came
        # to rest under an earlier peak by less than DROP_FRACTION advanced
        # neither counter: it could not converge, and it could not reach
        # STUCK_SAMPLES either. A real 10-peer MRT run peaked at 973368 and
        # settled at 971957 -- 0.145% down -- and hung there indefinitely with
        # the target long since idle.
        if (self.last_neighbors_checked > 0 or neighbors_received_full > 0) \
                and recved == self.last_recved:
            self.last_recved_count += 1
        else:
            self.last_recved = recved
            self.last_recved_count = 0

        # Any change in how many neighbors have finished restarts the clock:
        # more routes are still on their way.
        if neighbors_checked != self.last_neighbors_checked:
            self.last_neighbors_checked = neighbors_checked
            self.last_recved_count = 0

        if checked:
            self.recved_checkpoint = True

        # A count parked well below its peak is not converged, however steady
        # it looks. Without this gate the checkpoint shortens the assurance
        # window to ASSURANCE_SAMPLES_AFTER_CHECKPOINT (5), which is reached
        # before the regression streak reaches DROP_SAMPLES (10) -- so a run
        # that lost half its routes and held there was reported CONVERGED, with
        # the loss visible only as a low 'received' column. Every real run sets
        # the checkpoint, so this is the ordinary path, not a corner case.
        if (self.neighbors_checkpoint
                and self.last_recved_count >= self.assurance_samples
                and dropped <= DROP_FRACTION):
            return self.CONVERGED

        if (elapsed_seconds > NO_PROGRESS_DEADLINE_SECONDS
                and not self.recved_checkpoint
                and self.last_recved_count == 0
                and recved == 0):
            # Nothing has arrived at all; trip the stuck check immediately
            # rather than waiting out STUCK_SAMPLES.
            self.last_recved_count = STUCK_SAMPLES

        if self.last_recved_count >= STUCK_SAMPLES:
            self.fail_msg = (f"FAILED: stuck received count {recved} "
                             f"neighbors_checked {neighbors_checked}")
            return self.FAILED

        return self.CONTINUE
