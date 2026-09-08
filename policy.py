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

'''Changing import policy on a table the target already holds.

Every workload before this one asks the target to *acquire* a table -- the
initial delivery, and, since churn, a bounded block of it going away and
coming back while the rest stays. None of them asks the question an operator
asks most often: what does it cost to change policy on a router that is
already carrying a full table? That is a different mechanism from either. The
daemon re-reads its configuration, re-evaluates its import policy against
routes it already has, drops the ones the new policy rejects, and withdraws
them from every export session -- with the sessions staying up throughout.

What that costs is not derivable from a delivery measurement, and it is the
same three responsibilities BIRD 3's worker threads exist to parallelise,
reached from a third direction.

The rules live here, Docker-free and bgperf2-free like `convergence.py`,
`contention.py`, `churn.py`, `findings.py` and `summary.py`, so the whole set
is covered by a suite that needs no daemon. What the mechanism *is* on a given
daemon belongs to that daemon's module: this file knows only which peers the
new policy rejects, what the monitor should see when it has been applied, and
how to tell an applied policy from a target that stopped answering.
'''

from dataclasses import dataclass
from typing import Optional


# No reload at all: the run every command line and batch config before this
# flag carries implicitly, and the one this module renders unchanged.
DEFAULT_POLICY_RELOAD_BLOCKS = 0

# How many monitor samples the reload may make no progress at all before it is
# called stalled. Counted in samples *without progress* rather than in samples,
# for the reason `CHURN_STALL_SAMPLES` is: a large table whose rejected routes
# are still draining moves the count on nearly every poll and resets this, so
# what this bounds is silence -- a reconfigure the daemon never applied, a
# session that dropped, a target that stopped exporting. At the monitor's 1s
# cadence it is five minutes of nothing.
POLICY_RELOAD_STALL_SAMPLES = 300

# How far below the expected count the table may sit and still be read as the
# new policy having been applied, as a fraction of the converged count. The
# policy rejects exactly the blocks it names, so a count materially below what
# it leaves is routes no policy rejected -- a session that flapped, a target
# that restarted -- and the monitor reports that as a low accepted count like
# any other. Without it a post-reload sample of 0 satisfies `accepted <=
# expected` for every policy there is: the reload would be stamped complete and
# a target that had lost its sessions published as one that had applied a
# policy quickly. This is `CHURN_COLLAPSE_FRACTION`'s rule and
# `ConvergenceTracker.DROP_FRACTION`'s, on a third side of convergence; it is
# stated here rather than imported so that one workload's tolerance cannot be
# retuned by an edit aimed at another.
POLICY_RELOAD_COLLAPSE_FRACTION = 0.01


class PolicyReloadConfigurationError(ValueError):
    '''Raised for a policy reload that cannot be built or driven.'''


def _whole_number(name, value, minimum=0):
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise PolicyReloadConfigurationError(
            '{0} must be a whole number of {1} or more, got {2!r}'.format(
                name, minimum, value))
    return value


def rejected_block_indexes(groups, blocks):
    '''Which of the fleet's prefix blocks the new policy rejects.

    The **last** `blocks` of them, and the tail is the whole of the determinism
    here -- the same choice `split_churn_paths()` makes and for the same
    reason. A sampled selection would need a seed, and a seed is another
    dimension in the cell identity, the artifact stem and the manifest, which
    is what `--prefix-scope` and `--path-diversity` both refuse to become. The
    tail is rebuildable from the peer count, the diversity and the block count
    alone, so two runs of one cell reject the same peers and a reader can
    reconstruct the set from the row.

    It is stated in *blocks* rather than in peers because a block is what the
    monitor can see. Under `--path-diversity` a block is announced by several
    peers, and rejecting some of them leaves the prefix behind a surviving
    path: the target does real best-path work and the monitor's count does not
    move, so the reload could never be observed to complete. Rejecting whole
    blocks is what makes the completion count exact.
    '''
    _whole_number('groups', groups, minimum=1)
    _whole_number('blocks', blocks, minimum=1)
    if blocks >= groups:
        # Every block rejected leaves the target holding nothing, and an
        # accepted count of 0 is exactly the reading `POLICY_RELOAD_COLLAPSE_
        # FRACTION` exists to refuse -- a target that lost its sessions and one
        # that applied the policy perfectly would produce the same sample. At
        # least one surviving block is what makes the two distinguishable.
        raise PolicyReloadConfigurationError(
            'a policy rejecting {0} of {1} block(s) leaves the target holding '
            'nothing, and an empty table cannot be told from a target that '
            'lost its sessions'.format(blocks, groups))
    return tuple(range(groups - blocks, groups))


def rejected_peer_asns(neighbors, diversity, blocks):
    '''The AS numbers whose routes the new policy rejects.

    `neighbors` is every peer the generators are configured with. They are
    ordered by AS here rather than taken in the order the mapping happens to
    iterate: a scenario is YAML and the order of a mapping is not part of what
    the file means, while `gen_conf()` assigns both the address and the AS from
    the same incrementing index it keys the diversity block on. Ordering by AS
    therefore reproduces the block assignment exactly, which ordering by
    nothing does not -- and `Target.scenario_neighbors()` already sorts the
    same way.
    '''
    _whole_number('path diversity', diversity, minimum=1)
    ordered = sorted(neighbors, key=lambda n: n['as'])
    if not ordered:
        raise PolicyReloadConfigurationError(
            'a policy reload needs the peers whose routes it rejects, and this '
            'run configured none')
    if len(ordered) % diversity:
        raise PolicyReloadConfigurationError(
            'path diversity {0} does not divide {1} peer(s) into equal '
            'blocks'.format(diversity, len(ordered)))
    rejected = set(rejected_block_indexes(len(ordered) // diversity, blocks))
    return [n['as'] for i, n in enumerate(ordered) if i // diversity in rejected]


def policy_reload_counts(converged, prefix_num, blocks):
    '''What the monitor should see once the new policy has been applied.

    `expected_accepted` is exact and deliberately so. The monitor reads what
    the target re-advertises, which is one best path per distinct prefix, and a
    rejected block loses every path it had -- so the count falls by the block's
    whole `blocks * prefix_num` prefixes and by nothing else.

    It is measured down from the count this run actually converged on rather
    than from the count the fleet offered, for the reason the churn floor is:
    the monitor's check-point carries a 0.99 factor because a target does not
    always hold every prefix offered to it, and a run that converged one prefix
    short would otherwise be given a target it can never reach. What that
    cannot rescue is a target missing prefixes that fall *inside* a rejected
    block -- the count then stops above `expected_accepted` and the reload is
    reported as stalled, naming both numbers. That is the same trade
    `ChurnBurstTracker` makes: a tolerance here would have to be a number
    nobody measured, and it would let a policy that was only half applied be
    published as one that was applied.
    '''
    _whole_number('the converged prefix count', converged)
    _whole_number('prefixes per peer', prefix_num, minimum=1)
    _whole_number('blocks', blocks, minimum=1)
    rejected = blocks * prefix_num
    if rejected > converged:
        raise PolicyReloadConfigurationError(
            'a policy rejecting {0} prefix(es) cannot be observed against a '
            'converged count of {1}'.format(rejected, converged))
    return {
        'rejected_prefixes': rejected,
        'expected_accepted': converged - rejected,
    }


@dataclass(frozen=True)
class PolicyReloadStep:
    '''What one monitor sample means for the reload.

    `action` is what the caller must do *now* and `completed` names what this
    sample closed, so an event is recorded against the sample that decided it
    rather than against the next one -- the same split `ChurnStep` makes, for
    the same reason.
    '''

    action: str
    completed: Optional[str] = None
    reason: Optional[str] = None


class PolicyReloadTracker:
    '''Drive one policy reload off the monitor's own accepted count.

    Separated from `bench()`'s container plumbing exactly as
    `ConvergenceTracker` and `ChurnBurstTracker` are: the rules are the part
    that can be got wrong, and they are only testable without Docker while
    nothing here knows what a container is.

    The caller feeds one accepted-prefix count per monitor sample and performs
    whatever `update()` returns before the next one:

      RELOAD issued -> wait until the count has fallen to what the new policy
      leaves -> the reload is complete.

    Two rules carry the weight, and they are the ones churn learned:

    - **Progress, not elapsed time, bounds the wait.** A large table draining
      slowly must never be cut off, and a reconfigure that no daemon applied
      must be caught in bounded time; counting samples that made no progress
      *towards* the expected count does both.
    - **A collapsed count is not an applied policy.** A count materially below
      what the policy leaves is routes nothing rejected, and reading it as
      success would publish a target that lost its sessions as one that
      re-evaluated a table quickly.
    '''

    WAIT = 'wait'
    RELOAD = 'reload'
    DONE = 'done'
    FAILED = 'failed'

    RELOAD_PHASE = 'reload'

    def __init__(self, converged, expected_accepted,
                 stall_samples=POLICY_RELOAD_STALL_SAMPLES):
        _whole_number('the converged prefix count', converged)
        _whole_number('the expected accepted count', expected_accepted)
        _whole_number('stall_samples', stall_samples, minimum=1)
        if expected_accepted >= converged:
            # A policy that rejects nothing produces no observable transition:
            # the count is already where it will end, so the first sample would
            # complete the reload and publish the poll it happened to land on
            # as the cost of re-evaluating the table.
            raise PolicyReloadConfigurationError(
                'a policy leaving {0} of {1} accepted prefix(es) rejects '
                'none of them, so nothing the monitor sees would change'.format(
                    expected_accepted, converged))
        self.converged = converged
        self.expected_accepted = expected_accepted
        self.collapse_below = expected_accepted - max(
            1, int(converged * POLICY_RELOAD_COLLAPSE_FRACTION))
        self.stall_samples = stall_samples
        self.complete = False
        self.fail_msg = None
        self._issued = False
        self._stalled = 0
        self._best = None
        self._finished = False

    def _collapsed(self, accepted):
        '''End the reload for a count that lost more than the policy rejected.

        Named against the phase it happened in, for the reason `ChurnBurst
        Tracker._collapsed()` is: a table that had already lost routes when the
        reload was issued and one that lost them while the daemon was applying
        it send the reader to different logs.
        '''
        where = ('while the new policy was being applied' if self._issued
                 else 'before the new policy was issued')
        self._finished = True
        self.fail_msg = (
            'the policy reload was abandoned {0}: the table lost more than the '
            'policy rejects -- {1} accepted prefix(es) is below the {2} the '
            'policy leaves, so routes went away that no policy '
            'rejected'.format(where, accepted, self.expected_accepted))
        return PolicyReloadStep(self.FAILED, reason=self.fail_msg)

    def _stall(self, accepted):
        self._finished = True
        self.fail_msg = (
            'the policy reload stalled: the target held {0} accepted '
            'prefix(es) for {1} samples without moving towards the {2} the '
            'new policy leaves'.format(
                accepted, self.stall_samples, self.expected_accepted))
        return PolicyReloadStep(self.FAILED, reason=self.fail_msg)

    def update(self, accepted):
        '''Read one post-convergence monitor sample and say what to do next.'''
        if self._finished:
            raise PolicyReloadConfigurationError(
                'the policy reload has already finished')
        _whole_number('accepted prefixes', accepted)

        # Before anything else, including issuing the reload: a table that has
        # already lost routes nothing rejected is not one to change policy on,
        # and the reading would be charged to the policy.
        if accepted < self.collapse_below:
            return self._collapsed(accepted)

        if not self._issued:
            self._issued = True
            self._best = accepted
            self._stalled = 0
            return PolicyReloadStep(self.RELOAD)

        if accepted <= self.expected_accepted:
            self.complete = True
            self._finished = True
            return PolicyReloadStep(self.DONE, completed=self.RELOAD_PHASE)

        if accepted < self._best:
            self._best = accepted
            self._stalled = 0
        else:
            self._stalled += 1
            if self._stalled >= self.stall_samples:
                return self._stall(accepted)
        return PolicyReloadStep(self.WAIT)
