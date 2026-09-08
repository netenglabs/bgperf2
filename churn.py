# Copyright (C) 2026 bgperf2 contributors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

'''Bounded withdrawal/reannouncement bursts, as a pure state machine.

Every run bgperf2 has made measures one thing: a table arriving at a daemon
that has never seen it. A router spends almost none of its life doing that. It
spends it holding a table while parts of it move -- a peer withdraws a block,
re-announces it a moment later, and the target has to remove those routes from
its own table, re-run best-path selection for every prefix that had a competing
path, and withdraw and re-advertise on every export session. That is the work
BIRD 3's worker threads exist to parallelise and nothing here has been able to
ask for it.

A burst is deliberately *bounded* and *counted*: a fixed block of each peer's
prefixes goes away and comes back, so the operation count is known before the
run starts rather than inferred from what the monitor happened to see.

Docker-free and bgperf2-free, like `convergence.py`, `contention.py`,
`findings.py` and `summary.py`, so the whole rule set is covered by a test
suite that needs no daemon.
'''

from dataclasses import dataclass
from typing import Optional


# No churn at all: the workload every run before this flag existed ran, and the
# value every existing command line and batch config carries implicitly.
DEFAULT_CHURN_PREFIXES = 0

# One withdraw/reannounce cycle. A burst count is only meaningful alongside a
# churn block, so this is the count a run that asked for churn gets by default
# rather than a workload on its own.
DEFAULT_CHURN_BURSTS = 1

# How many monitor samples a burst phase may make no progress at all before it
# is called stalled. Counted in samples *without progress*, not in samples, so
# a large table that is still draining is never cut off -- a 5,000,000-route
# reannouncement moves the count on nearly every poll and resets this. What it
# bounds is the case where nothing is coming: a `disable` that never reached
# the generator, a session that dropped, a target that stopped exporting. At
# the monitor's 1s cadence this is five minutes of complete silence.
CHURN_STALL_SAMPLES = 300

# How far below the expected floor a count may sit and still be read as the
# churn block going away, as a fraction of the converged count. The peers
# withdraw exactly the block and nothing else, so a count materially below the
# floor is routes nobody withdrew -- a session that flapped, a target that
# restarted -- and the monitor reports that as a low accepted count like any
# other. Without this, a post-convergence sample of 0 satisfies `accepted <=
# floor` for every block there is: the withdrawal would be stamped complete,
# the re-announcement issued against a table that never lost the block, and
# the session re-learning the whole table published as `reannounce_s`, with
# nothing in the artifact marking either as suspect. `ConvergenceTracker`
# guards the same shape during delivery with `DROP_FRACTION`; this is that
# rule on the other side of convergence. It is a fraction so it scales with
# the table, floored at one prefix so a small run is not held to exactness the
# monitor's own sampling cannot promise.
CHURN_COLLAPSE_FRACTION = 0.01


class ChurnConfigurationError(ValueError):
    '''Raised for a churn workload that cannot be built or driven.'''


def split_churn_paths(paths, churn_prefixes):
    '''Split one peer's prefixes into the block it holds and the block it churns.

    The churn block is the **tail** of the peer's own list, and that choice is
    the whole of the determinism here: a sampled block would need a seed, and a
    seed is a fourth dimension in the cell identity, the artifact stem and the
    manifest -- exactly what `--prefix-scope` and `--path-diversity` both
    refuse to become. The tail is reproducible from the per-peer prefix count
    and the churn count alone, so two runs of one cell withdraw the same
    prefixes and a reader can rebuild the set from the row.

    Taking the tail also keeps the block *shared* under `--path-diversity`:
    peers in one group are handed the same list, so they churn the same
    prefixes and the target loses the prefix rather than falling back to a
    surviving path. That is the withdrawal a best-path selection has to react
    to, and it is why the monitor-visible count is `groups * churn`, not
    `peers * churn`.
    '''
    if churn_prefixes is None:
        churn_prefixes = DEFAULT_CHURN_PREFIXES
    if not isinstance(churn_prefixes, int) or isinstance(churn_prefixes, bool) \
            or churn_prefixes < 0:
        raise ChurnConfigurationError(
            'churn prefixes must be a whole number of 0 or more, got '
            '{0!r}'.format(churn_prefixes))
    paths = list(paths)
    if churn_prefixes > len(paths):
        raise ChurnConfigurationError(
            'churn block of {0} is larger than the {1} prefix(es) this peer '
            'announces'.format(churn_prefixes, len(paths)))
    if not churn_prefixes:
        # The default renders what it always rendered: the caller writes one
        # static protocol holding every path, exactly as it did before churn
        # existed, so an existing run's generator config is byte-identical.
        return paths, []
    split = len(paths) - churn_prefixes
    return paths[:split], paths[split:]


def churn_operation_counts(neighbor_num, churn_prefixes, groups):
    '''The two operation counts one burst performs, stated before the run.

    They differ by exactly the path diversity and both are needed:

    - `offered_withdrawals` is what the *fleet* does -- one withdrawal per peer
      per churned prefix. It is the size of the workload.
    - `distinct_withdrawals` is what the *monitor* can see, because the monitor
      reads what the target re-advertises and that is one best path per prefix.
      It is the number the burst's completion is decided on.

    Reporting only the first would describe a burst the instrument cannot
    confirm; reporting only the second would understate a diversity-5 fleet's
    work by a factor of five.
    '''
    for name, value in (('peers', neighbor_num), ('groups', groups)):
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ChurnConfigurationError(
                '{0} must be a whole number of 1 or more, got {1!r}'.format(
                    name, value))
    if not isinstance(churn_prefixes, int) or isinstance(churn_prefixes, bool) \
            or churn_prefixes < 0:
        raise ChurnConfigurationError(
            'churn prefixes must be a whole number of 0 or more, got '
            '{0!r}'.format(churn_prefixes))
    if groups > neighbor_num:
        raise ChurnConfigurationError(
            'a fleet of {0} peers cannot announce {1} distinct blocks'.format(
                neighbor_num, groups))
    return {
        'offered_withdrawals': neighbor_num * churn_prefixes,
        'distinct_withdrawals': groups * churn_prefixes,
    }


@dataclass(frozen=True)
class ChurnStep:
    '''What one monitor sample means for the burst sequence.

    `action` is what the caller must issue *now*; `completed` names the thing
    this sample closed, so an event is recorded against the sample that decided
    it rather than against the next one. They are separate fields because a
    sample can do both -- the last burst's reannouncement completing is also
    the end of the sequence.
    '''

    action: str
    burst: int
    completed: Optional[str] = None
    reason: Optional[str] = None


class ChurnBurstTracker:
    '''Drive N withdraw/reannounce bursts off the monitor's accepted count.

    Separated from `bench()`'s container plumbing for the reason
    `ConvergenceTracker` is: the rules are what can be got wrong, and they are
    only testable without Docker if nothing here knows what a container is.

    The caller feeds one accepted-prefix count per monitor sample and performs
    whatever `update()` returns before the next one. A burst is:

      WITHDRAW issued -> wait until the count has fallen by the whole distinct
      block -> REANNOUNCE issued -> wait until it is back at the count the run
      converged on -> the burst is complete.

    Three rules here are load-bearing:

    - **The withdrawal and the reannouncement are separate intervals.** A burst
      timed end to end cannot say whether a daemon is slow to drop routes or
      slow to re-select and re-export, and those are different code paths --
      the second is the one BIRD 3 parallelises. Collapsing them would publish
      one number that is the sum of two mechanisms.
    - **A burst closes on a sample, and the next one opens on the sample
      after.** Issuing the next withdrawal on the same sample that saw the
      table restored would put the two bursts back to back with the target
      still draining its export queues, so burst 2 would be measured against a
      baseline it had not actually reached. One poll of settling is cheap and
      it makes every interval start from an observed state.
    - **Progress, not elapsed time, bounds a phase.** `CHURN_STALL_SAMPLES`
      counts samples in which the count did not move *towards* the target at
      all, so a large table that is draining slowly is never cut off and a
      burst that was never issued is caught in bounded time.
    '''

    WAIT = 'wait'
    WITHDRAW = 'withdraw'
    REANNOUNCE = 'reannounce'
    DONE = 'done'
    FAILED = 'failed'

    WITHDRAW_PHASE = 'withdraw'
    REANNOUNCE_PHASE = 'reannounce'

    def __init__(self, bursts, baseline, distinct_withdrawals,
                 stall_samples=CHURN_STALL_SAMPLES):
        if not isinstance(bursts, int) or isinstance(bursts, bool) or bursts < 1:
            raise ChurnConfigurationError(
                'churn bursts must be a whole number of 1 or more, got '
                '{0!r}'.format(bursts))
        if not isinstance(distinct_withdrawals, int) \
                or isinstance(distinct_withdrawals, bool) \
                or distinct_withdrawals < 1:
            raise ChurnConfigurationError(
                'a burst must withdraw at least one distinct prefix, got '
                '{0!r}'.format(distinct_withdrawals))
        if not isinstance(baseline, int) or isinstance(baseline, bool) \
                or baseline < 0:
            raise ChurnConfigurationError(
                'the converged prefix count must be a whole number of 0 or '
                'more, got {0!r}'.format(baseline))
        if distinct_withdrawals > baseline:
            # The monitor cannot see a count fall below zero, so this burst
            # could never be observed to complete -- it would stall and be
            # reported as a stuck target. Refused here rather than at the
            # command line as well, because the baseline is only known once
            # the run has converged: a filtered or lossy run can reach this
            # with a churn block the flag guards accepted.
            raise ChurnConfigurationError(
                'a burst withdrawing {0} distinct prefix(es) cannot be '
                'observed against a converged count of {1}'.format(
                    distinct_withdrawals, baseline))
        if not isinstance(stall_samples, int) or isinstance(stall_samples, bool) \
                or stall_samples < 1:
            raise ChurnConfigurationError(
                'stall_samples must be a whole number of 1 or more, got '
                '{0!r}'.format(stall_samples))
        self.bursts = bursts
        self.baseline = baseline
        self.distinct_withdrawals = distinct_withdrawals
        self.floor = baseline - distinct_withdrawals
        # Below this the table lost more than the burst withdrew, whichever
        # phase it happens in: the two cases are the same fault and take the
        # same message.
        self.collapse_below = self.floor - max(
            1, int(baseline * CHURN_COLLAPSE_FRACTION))
        self.stall_samples = stall_samples
        self.burst = 0
        self.completed_bursts = 0
        self.phase = None
        self.fail_msg = None
        self._stalled = 0
        self._best = None
        self._finished = False

    def _begin_phase(self, phase, accepted):
        self.phase = phase
        self._stalled = 0
        self._best = accepted

    def _note_progress(self, accepted):
        '''Advance or charge the stall counter for one sample of a phase.'''
        if self.phase == self.WITHDRAW_PHASE:
            improved = accepted < self._best
        else:
            improved = accepted > self._best
        if improved:
            self._best = accepted
            self._stalled = 0
            return True
        self._stalled += 1
        return False

    def _stall(self, accepted, target):
        '''End the sequence, naming the phase, the count and what it wanted.

        The message goes into the run's own MSG column, so it has to say which
        of the two phases stopped moving: a withdrawal that never landed means
        the generator did not act on it, while a reannouncement that never
        landed means the target did not put the block back -- and those send
        the reader to different logs.
        '''
        phase = ('withdrawal' if self.phase == self.WITHDRAW_PHASE
                 else 'reannouncement')
        self.phase = None
        self._finished = True
        self.fail_msg = (
            'churn burst {0}/{1} stalled: the {2} held at {3} accepted '
            'prefix(es) for {4} samples without moving towards {5}'.format(
                self.burst, self.bursts, phase, accepted, self.stall_samples,
                target))
        return ChurnStep(self.FAILED, self.burst, reason=self.fail_msg)

    def _collapsed(self, accepted):
        '''End the sequence for a count that lost more than the burst did.

        Reported rather than waited out, and reported in *both* phases: during
        the withdrawal it would otherwise be read as the block going away, and
        during the re-announcement it would be waited on until the stall bound
        and then blamed on a slow target.
        '''
        # Names the phase for the reason `_stall()` does -- a withdrawal that
        # lost routes and a re-announcement that lost them send the reader to
        # different logs -- and distinguishes the two states `phase is None`
        # covers, since a collapse before the first burst is the flap this rule
        # exists for and 'between bursts' would misdescribe when it happened.
        if self.phase == self.WITHDRAW_PHASE:
            where = 'churn burst {0}/{1} during the withdrawal'.format(
                self.burst, self.bursts)
        elif self.phase == self.REANNOUNCE_PHASE:
            where = 'churn burst {0}/{1} during the re-announcement'.format(
                self.burst, self.bursts)
        elif self.burst:
            where = 'between churn bursts after {0}/{1}'.format(
                self.burst, self.bursts)
        else:
            where = 'before the first churn burst'
        self.phase = None
        self._finished = True
        self.fail_msg = (
            '{0}: the table lost more than the burst withdrew -- {1} accepted '
            'prefix(es) is below the {2} a burst withdraws down to, so routes '
            'went away that no peer withdrew'.format(
                where, accepted, self.floor))
        return ChurnStep(self.FAILED, self.burst, reason=self.fail_msg)

    def update(self, accepted):
        '''Read one post-convergence monitor sample and say what to do next.'''
        if self._finished:
            raise ChurnConfigurationError(
                'the churn sequence has already finished')
        if not isinstance(accepted, int) or isinstance(accepted, bool) \
                or accepted < 0:
            raise ChurnConfigurationError(
                'accepted prefixes must be a whole number of 0 or more, got '
                '{0!r}'.format(accepted))

        # Before anything else, including opening the next burst: a table
        # that has lost routes nobody withdrew is not one to start a burst
        # against, and between bursts there is no phase to catch it below.
        if accepted < self.collapse_below:
            return self._collapsed(accepted)

        if self.phase is None:
            if self.completed_bursts >= self.bursts:
                self._finished = True
                return ChurnStep(self.DONE, self.burst)
            self.burst += 1
            self._begin_phase(self.WITHDRAW_PHASE, accepted)
            return ChurnStep(self.WITHDRAW, self.burst)

        if self.phase == self.WITHDRAW_PHASE:
            if accepted <= self.floor:
                self._begin_phase(self.REANNOUNCE_PHASE, accepted)
                return ChurnStep(self.REANNOUNCE, self.burst,
                                 completed=self.WITHDRAW_PHASE)
            if not self._note_progress(accepted) \
                    and self._stalled >= self.stall_samples:
                return self._stall(accepted, self.floor)
            return ChurnStep(self.WAIT, self.burst)

        if accepted >= self.baseline:
            self.completed_bursts += 1
            self.phase = None
            if self.completed_bursts >= self.bursts:
                self._finished = True
                return ChurnStep(self.DONE, self.burst,
                                 completed=self.REANNOUNCE_PHASE)
            return ChurnStep(self.WAIT, self.burst,
                             completed=self.REANNOUNCE_PHASE)
        if not self._note_progress(accepted) \
                and self._stalled >= self.stall_samples:
            return self._stall(accepted, self.baseline)
        return ChurnStep(self.WAIT, self.burst)
