# Convergence detection for a benchmark run.
#
# Deciding when a run is "done" is the subtlest logic in bgperf2. The naive
# check -- stop when received == expected -- only works for synthetic prefix
# generation. With MRT playback the total unique prefix count is unknown because
# peers' tables overlap, and with filtering enabled the accepted count is
# deliberately lower than what was sent. So instead of comparing against a
# target number, we wait for the count to go *stable*.
#
# One rule reads a second instrument. The monitor is a single BGP session's
# view of the target, so when its count falls there is nothing to check it
# against -- and a 10-injector MRT run settles 1.2%-1.6% below its own peak
# nearly every time, purely because best paths change as the last injectors
# deliver.
# `ConvergenceTracker` therefore accepts the target's own table gauge beside
# each monitor sample and uses it to tell a decline in what is *exported* from
# a decline in what is *held*. It is optional: a daemon with no gauge, or a
# poll that produced none, decides exactly what it decided before.
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

# How many monitor samples may re-use one target-side reading before it stops
# counting as evidence.
#
# The witness below can excuse a monitor decline, so a *frozen* witness would
# excuse every decline there is -- and freezing is not hypothetical:
# `Container.neighbor_stats()` has no guard around its exec, so one failed read
# ends that thread and every later monitor sample repeats its last reading
# (bgperf2-sl1). What this constant bounds is how long such a reading may keep
# a run *alive*: at most WITNESS_CARRY_SAMPLES consecutive samples, far fewer
# than DROP_SAMPLES, so a run whose target poll dies mid-decline still fails, a
# little later than it would have.
#
# It deliberately does not bound anything about the verdict. An earlier version
# argued that WITNESS_CARRY_SAMPLES samples is "fewer than convergence needs",
# which is only true when the freeze starts at or before the assurance window
# does -- a witness that froze three samples in was still inside the bound when
# the window closed, and decided CONVERGED on a stale reading. The convergence
# gate requires a reading taken on the deciding sample instead, which is a
# property of that sample rather than an arithmetic relation between two
# constants that no test could hold together.
#
# It is not tighter than that because the target read is a `docker exec` whose
# cost grows with the table, and a bound fitted to the runs measured here (the
# witness was re-read on every monitor sample but one, across 159 samples of
# four 10 x 1,050,000 runs) would quietly switch the rule off on the larger
# runs that need it most -- turning them back into the deterministic failures
# it exists to prevent.
WITNESS_CARRY_SAMPLES = ASSURANCE_SAMPLES_AFTER_CHECKPOINT

# How long a run may be kept alive by the witness alone before it is failed
# anyway.
#
# The excuse resets the drop streak, and a monitor count that declines a little
# on *every* sample also resets the stability counter, so a run whose monitor
# bleeds away steadily while the target holds its table had no terminating path
# at all: simulated at 100 prefixes a sample, it was still CONTINUE after 2000
# samples with a fifth of the table gone, where the old rule failed it at ten.
# `bench()` has no run timeout, so that is a hang, and under `batch()` it is
# the rest of the matrix.
#
# STUCK_SAMPLES rather than a bound of its own, because this is the same
# judgement that constant already makes -- a run that has not got anywhere in
# this long is not converging -- and because the alternative is a budget fitted
# to how many samples the MRT shape happens to need (7 to 11 in the eight runs
# measured, against 600 here).
WITNESS_EXCUSED_LIMIT = STUCK_SAMPLES

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
        # The target's own account of the table it holds, as a high-water mark
        # of its own: a decline is judged against the largest table the target
        # ever reported, on the same rule the monitor's count is judged by.
        self.peak_best_paths = 0
        # Consecutive samples the witness is the only thing keeping alive. A
        # run may be carried, but not indefinitely: see WITNESS_EXCUSED_LIMIT.
        self.witness_excused_streak = 0
        # When the carried reading was last taken, and how many monitor
        # samples have re-used it since. A reading that cannot be dated is not
        # evidence at all -- there is no way to show it is current, and a
        # frozen witness is the failure this whole guard exists for.
        self.last_witness_monotonic_s = None
        self.witness_carried_samples = 0
        # What the rule did, for the artifact and the progress line. Counted
        # rather than flagged: one excused sample and forty are different
        # claims about the same run.
        self.witness_excused_samples = 0
        self.max_excused_decline = 0.0
        self.max_excused_witness_decline = 0.0
        self.converged_below_monitor_peak = False

    @property
    def assurance_samples(self):
        '''How long the count must hold steady before we call it converged.'''
        if self.recved_checkpoint:
            return ASSURANCE_SAMPLES_AFTER_CHECKPOINT
        return ASSURANCE_SAMPLES

    def note_neighbors_checkpoint(self):
        '''Called when the target reports every neighbor has finished sending.'''
        self.neighbors_checkpoint = True

    def _witness_holds_table(self, table_witness, witness_monotonic_s):
        '''Whether the target itself says it still holds the table it held.

        The monitor counts what the target *re-advertises* to one session. The
        target's `best_paths` gauge counts what it *holds*: one best route per
        prefix, summed over every peering, and withheld entirely unless every
        peering the run configured reported. So a decline in the first that the
        second did not follow is a change in selection or export, not routes
        going away -- which is the one thing DROP_FRACTION exists to catch, and
        the one thing the monitor alone cannot rule on.

        Measured on eight 10 x 1,050,000 MRT runs (Phase 6 decision log,
        2026-09-08): the monitor declined 1.18% to 1.76% below its peak, while
        the target's own table was between 0.0% and 0.19% below its own on the
        samples that decline was excused on. An order of magnitude, and in most
        runs two, so the same DROP_FRACTION separates them and no constant is
        fitted to that RIB.

        The margin is not unlimited, and that is worth knowing before trusting
        it: `best_paths` is a gauge read while ten injectors are still
        delivering, so it wobbles as best paths change. One sample of one run
        sat 1.02% below its own peak and correctly did not attest. So this is
        deliberately not "best_paths is flat" -- an invariant recorded as
        monotonic gets a threshold of zero and then fails on the next run of the
        same workload -- and it is a per-sample rule: a sample where the target
        is also past the threshold advances the streak like any other.

        A genuine loss takes `best_paths` down with it and by a comparable
        amount, so it is past the same threshold and is not excused.

        Four things do not attest, each of which would otherwise let this rule
        excuse a decline nobody measured:

        - a withheld sum (`None`), which is what a peering still coming up or a
          partial CLI read produces;
        - a reading with no timestamp, which cannot be shown to be current;
        - a reading carried for WITNESS_CARRY_SAMPLES monitor samples without
          being re-read, which is what a dead target poll thread looks like;
        - a target holding nothing that never held anything, whose 0 equals its
          own peak and would otherwise read as a table intact.

        Returns (holds, declined): the verdict, and how far below its own peak
        the target's table is, or None where there was nothing to judge. The
        decline comes back so the caller can publish what it excused on rather
        than re-deriving it.
        '''
        best_paths = (table_witness or {}).get('best_paths')
        if witness_monotonic_s is None:
            # Undateable: neither fresh nor provably stale. Left out of the
            # carry counter as well, so a run that supplies no timestamps
            # cannot age its way into anything.
            return False, None
        if witness_monotonic_s != self.last_witness_monotonic_s:
            self.last_witness_monotonic_s = witness_monotonic_s
            self.witness_carried_samples = 0
        else:
            self.witness_carried_samples += 1
        if best_paths is None:
            return False, None
        if best_paths > self.peak_best_paths:
            self.peak_best_paths = best_paths
        if self.witness_carried_samples >= WITNESS_CARRY_SAMPLES:
            return False, None
        if not self.peak_best_paths:
            # Nothing held and nothing ever held: a target that has not started
            # receiving attests to nothing, and 0 == peak would otherwise read
            # as a table intact.
            return False, None
        declined = ((self.peak_best_paths - best_paths)
                    / self.peak_best_paths)
        return declined <= DROP_FRACTION, declined

    def witness_rule(self):
        '''What the table witness changed about this run's verdict, or None.

        None means the rule never decided anything -- no gauge to read, or a
        run whose monitor count never fell far enough to need one -- and such a
        run's artifact keeps exactly the shape it had before this rule existed.
        '''
        if not self.witness_excused_samples and not self.converged_below_monitor_peak:
            return None
        return {
            'policy': ('a monitor decline past DROP_FRACTION is not route loss '
                       'while the target\'s own best-path count is within '
                       'DROP_FRACTION of its peak'),
            'drop_fraction': DROP_FRACTION,
            'excused_samples': self.witness_excused_samples,
            'max_excused_monitor_decline': round(self.max_excused_decline, 6),
            'max_witness_decline_while_excusing': round(
                self.max_excused_witness_decline, 6),
            'witness_peak_best_paths': self.peak_best_paths,
            'monitor_peak': self.peak_recved,
            # Whether the run was declared converged on a sample the monitor
            # was still below its own peak on. Kept apart from the excused
            # count: excusing samples keeps a run alive, and this says the
            # final verdict rested on the witness.
            'converged_below_monitor_peak': self.converged_below_monitor_peak,
        }

    def update(self, elapsed_seconds, recved, neighbors_checked,
               neighbors_received_full, checked,
               table_witness=None, witness_monotonic_s=None):
        '''Fold in one monitor sample and return the resulting status.

        `table_witness` is the target's own reading of the table it holds, as
        `bird.table_witness()` returns it, and `witness_monotonic_s` is when
        that reading was taken. Both default to absent, and a run that supplies
        neither is decided exactly as it was before this witness existed.
        '''
        previous_recved = self.last_recved
        # Read first, and on every sample: the carry counter this rule depends
        # on advances per monitor sample, so a witness consulted only inside
        # the drop branch would look eternally fresh the moment it was needed.
        witness_holds, witness_declined = self._witness_holds_table(
            table_witness, witness_monotonic_s)
        # Regression is measured against the high-water mark, not the previous
        # sample. Comparing against the previous sample means a count that
        # settles one step below its peak keeps comparing equal afterwards, so
        # the streak stops growing and a real slide is missed.
        if recved > self.peak_recved:
            self.peak_recved = recved
            self.less_last_received = 0

        dropped = ((self.peak_recved - recved) / self.peak_recved
                   if self.peak_recved else 0)

        # Whether the witness is the only reason this sample did not advance
        # the drop streak; see WITNESS_EXCUSED_LIMIT below.
        excused = False

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
            elif witness_holds and recved > 0:
                excused = True
                # The target says it still holds the table, so what fell is
                # what it exports, not what it has. Placed after the recovery
                # branch so the counters below describe samples this rule
                # actually saved -- a sample that was climbing anyway needed no
                # saving, and counting it would overstate what the rule did.
                #
                # `recved > 0` because a count of zero is not a decline in what
                # the target exports; it is the absence of the session every
                # published timing is read from, and the target-side witness
                # cannot see that session at all. Observed: a batch pass whose
                # target container was removed mid-run went to 0 in one sample
                # while the target poll thread died with it, so the last
                # reading -- a full table -- was carried and excused a "100%
                # export change" for three samples before the carry bound cut
                # it off. The run failed either way, but for three samples it
                # failed later and the printed line asserted something untrue.
                # Same rule as churn's "a collapsed count is not a withdrawal",
                # reached from the other side of convergence.
                #
                # Deliberately not narrowed to samples at or above the
                # check-point, the way the convergence gate below is: the
                # declines that fail these runs settle above it, but the
                # mid-run collapses are entirely below it -- one recorded run
                # fell 22% below its peak while the target's table was still
                # climbing -- and refusing to excuse those leaves the hole this
                # rule exists to close. The cost is that a monitor which stops
                # seeing the run altogether is no longer failed by the drop
                # streak in DROP_SAMPLES; it is failed as stuck instead, which
                # is the same verdict STUCK_SAMPLES later.
                self.less_last_received = 0
                self.witness_excused_samples += 1
                self.max_excused_decline = max(self.max_excused_decline,
                                               dropped)
                self.max_excused_witness_decline = max(
                    self.max_excused_witness_decline, witness_declined)
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

        # A run the witness is carrying is still a run that is not converging,
        # and it has to end. The streak counts only consecutive samples, so a
        # decline that is excused, recovers, and settles -- the shape every MRT
        # run here has -- never approaches the limit.
        if excused:
            self.witness_excused_streak += 1
        else:
            self.witness_excused_streak = 0

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
        # The witness reaches this gate as well as the streak above, and it
        # has to: excusing the samples only keeps such a run alive, and with
        # the gate unchanged a settled MRT table 1.5% below its own transient
        # peak would poll on until STUCK_SAMPLES and fail anyway -- the same
        # verdict by a slower route, which is what the old rule already did to
        # a run that settled 0.145% down.
        #
        # `checked` is required with it, and only here. It is this sample's own
        # answer to "is the monitor at or above the check-point", so it says
        # the instrument is still seeing the run -- which the witness cannot,
        # since a target holding its whole table is exactly what a broken
        # monitor session also looks like from the target's side. Without it
        # this gate would report CONVERGED for a run whose monitor sat at zero
        # while the target held everything: the very case the gate was added
        # for, reached from the other side. It costs the excuse in runs whose
        # monitor never reaches the check-point at all -- a filtered run, say
        # -- and those are decided exactly as they were before.
        #
        # So is a reading taken on *this* sample. WITNESS_CARRY_SAMPLES bounds
        # how long a carried reading may keep a run alive, and that is not the
        # same permission as deciding its verdict: a witness that froze partway
        # through the assurance window is still inside the carry bound when the
        # window closes, so without this the CONVERGED verdict could rest on a
        # reading several polls stale -- taken, in the case the bound exists
        # for, from a poll thread that had already died. A carried reading
        # costs at most a poll here: the count is flat by then, so the next
        # sample carrying a fresh read converges. Measured, the witness is
        # re-read on all but one monitor sample in 159.
        if (self.neighbors_checkpoint
                and self.last_recved_count >= self.assurance_samples
                and (dropped <= DROP_FRACTION
                     or (witness_holds and checked
                         and self.witness_carried_samples == 0))):
            if dropped > DROP_FRACTION:
                self.converged_below_monitor_peak = True
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

        # Below the stuck check, so a run that is merely slow is still
        # described by the message that fits it. The message names the witness
        # because the two point somewhere different: a stuck count says the
        # target stopped, this says the target holds its table and the session
        # the run is measured through has been losing it for ten minutes.
        if self.witness_excused_streak >= WITNESS_EXCUSED_LIMIT:
            self.fail_msg = (
                f"FAILED: monitor count {recved} has been declining below its "
                f"peak {self.peak_recved} for "
                f"{self.witness_excused_streak} samples while the target "
                f"reported holding {self.peak_best_paths} prefixes")
            return self.FAILED

        return self.CONTINUE
