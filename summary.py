'''Summary statistics over the passes of a repeated batch matrix.

Phase 5 of the measurement plan asks for a median, a min and a max, a
dispersion and a coefficient of variation over the repetitions of one matrix
cell -- and asks for them *without hiding individual runs*, which is the whole
constraint.  One number per cell is what a reader wants, and it is also the
thing that makes three passes indistinguishable from one, so every statistic
here is published beside the observations it was computed from and the passes
those came from.

Kept free of Docker and of bgperf2 imports, like contention.py,
convergence.py and findings.py, so the arithmetic and the withholding rules
are testable without a daemon.

Its input is the stats rows the batch has already written to its CSV, read by
**column name**.  That row is positional for create_batch_graphs() and has
drifted by one column once already; a summary that averaged whichever column
happened to sit at index 12 would be arithmetic nobody could check.
'''

import math
import statistics


SUMMARY_SCHEMA = 'bgperf2/batch-summary/v1alpha1'

# Columns of the stats row that describe what was *measured*, so a
# distribution over the passes of one cell means something.  `required` is
# configuration and is carried as identity below; `date`, `cores` and
# `Mem (GB)` describe the machine, and `flags` and `MSG` are not numbers.
METRIC_COLUMNS = (
    'received',
    'monitor (s)',
    'elapsed (s)',
    'prefix received (s)',
    # Legacy, and named for what it is elsewhere: elapsed minus the first
    # monitor-visible prefix.  Summarised under its historical name, because
    # renaming it here would be the silent redefinition the plan forbids.
    'testers (s)',
    'total time',
    'max cpu %',
    'max mem (GB)',
    'min idle%',
    'min free mem (GB)',
    'tester errors',
    'tester timeouts',
    'max foreign cpu %',
)

# Read from the rows rather than from the cell, and checked for agreement
# across the passes: two passes of "one cell" that ran against different
# images are not two observations of the same thing, and that is the gcov trap
# -- a freshly built version beside a cached one -- reached one layer up.  A
# disagreement is surfaced, never averaged over.
PROVENANCE_COLUMNS = ('target image', 'tester version', 'monitor version')

# Configuration the target reported back, kept beside the metrics so a median
# `received` can be read against what the run required.
ROW_IDENTITY_COLUMNS = ('required',)

# What a run writes into a column it never sampled. Passed in by the caller
# rather than known here, because the sentinel is a property of the controller
# and this module is deliberately free of bgperf2 imports --
# `bgperf2.unsampled_row_values()` derives it from the one constant.
FAILED_COLUMN = 'failed'
FAILED_VALUE = 'FAILED'
MESSAGE_COLUMN = 'MSG'

# What the passes of a cell can be.  A pass that failed and a pass that has
# not run are both absent from the statistics and are counted apart, because
# one of them is a result and the other is unfinished work.
OBSERVED = 'observed'
FAILED = 'failed'
NOT_RUN = 'not run'
# A row that cannot be read against this header at all. It is kept apart from
# `failed` because it is not a result about the daemon: `--resume` onto a
# progress file written before a column was appended is a supported path, and
# such a row is one field short. One of them must cost that pass and not the
# whole document.
UNREADABLE = 'unreadable'

# Why a statistic is absent.  Nothing here is published as a zero: a
# coefficient of variation of 0 over one observation would say the measurement
# is perfectly repeatable on the strength of never having been repeated.
NO_OBSERVATION = 'no observation: every pass of this cell failed or has not run'
NON_NUMERIC = 'a pass reported a non-numeric value in this column'
NEEDS_TWO = 'a dispersion needs at least two observations'
UNSAMPLED = ('a pass reported the never-sampled sentinel in this column, so '
             'that pass never measured it')
MEAN_NOT_POSITIVE = 'the mean is not positive, so a relative dispersion has no meaning'

_STATISTICS = ('mean', 'median', 'min', 'max', 'stdev', 'cv_percent')

# Derived statistics are rounded; observations are not.  Six places keeps a
# small dispersion visible -- a 0.4 MB spread in `max mem (GB)` reads as
# 0.000391, not as 0.0 -- while keeping 1.4142135623730951 out of a document
# meant to be read.
_PLACES = 6

# What the printed line reports.  The rest is in the artifact: two metrics is
# a glance at repeatability, thirteen is a table nobody reads at the end of a
# batch that has run for hours.
PRINTED_METRICS = ('elapsed (s)', 'total time')


# --- the variance rule ------------------------------------------------------
#
# Phase 5 asks that a test go from three passes to five "only under a named
# variance rule".  The naming is the point: without one, the decision to rerun
# is taken by whoever looks at the CSV and does not like it, which selects for
# reruns of the results somebody found surprising and quietly turns a
# benchmark into a search for the answer they expected.
#
# The rule is comparative rather than a threshold on a coefficient of
# variation, because there is no CV that means the same thing twice here.  A
# 2% spread is nothing on a cell whose targets are 40% apart and fatal on one
# where they are 0.1% apart -- FRR 8.5, 9.1 and 10.0 finished a 95s MRT run
# within 0.11s of each other, which is 0.12%.  So a cell earns more passes when
# its own spread covers the difference it is being asked to resolve, and not
# otherwise:
#
#     two cells are separated when their medians differ by more than the
#     sum of their standard deviations
#
# Deliberately weaker than a significance test.  It is a scheduling rule with
# n=3, where a t-test would be arithmetic dressing up three numbers, and it is
# conservative in the direction that costs machine time rather than the one
# that publishes a ranking the passes do not support.
VARIANCE_RULE = ('two cells are separated when their medians differ by more '
                 'than the sum of their standard deviations, floored at the '
                 'resolution of the metric')

# The resolution of each metric the rule can decide on, in that metric's own
# units, and 0 for one that is not quantised.
#
# `elapsed (s)` reaches the row as `stats['elapsed'].seconds` -- whole seconds
# -- and that is not a formatting choice that could be widened.  Two things
# quantise it and the coarser wins: the `timedelta.seconds` truncation, which
# is 1s whatever else changes, and the monitor's poll interval, which is 1s
# today and is a real knob (`bgperf2.MONITOR_POLL_INTERVAL_S`, passed into the
# sampling loop).  So the quantum is `max(1.0, MONITOR_POLL_INTERVAL_S)`, and
# `test_stats_contract.py` pins it that way rather than to the interval alone:
# pinning to the interval would go red if somebody polled twice a second and
# invite the fix of setting this to 0.5, which understates the truncation --
# two cells one whole second apart would clear a 0.5 floor and be published
# `separated` on a rounding boundary, silently.  That is the defect this floor
# exists to prevent, reintroduced through its own test.
#
# It matters twice, in opposite directions, and the rule is wrong in both
# without it:
#
#   * Passes of one cell land in the same one-second bucket often, which gives
#     `stdev` exactly 0.0.  A combined deviation of zero is satisfied by *any*
#     gap, so the batch publishes `separated` on a difference of one rounding
#     boundary -- and publishes it in silence, since the rule prints nothing
#     about the results it supports.  A ranking asserted from quantisation
#     noise, with nothing to argue with, is the worst thing this module can do.
#   * The pairs the rule was written for are inside the quantum.  FRR 8.5, 9.1
#     and 10.0 finished a 95s MRT run 0.11s apart; at this resolution they are
#     the same measurement, and the honest verdict is that this instrument
#     cannot tell them apart at this workload -- `expand`, and then
#     `unseparated at the expansion limit`, which is exactly what those three
#     are.
#
# So the combined deviation is floored here: two cells one quantum apart are
# not separated, whatever their passes agreed on.  Same rule as
# `MONITOR_POLL_INTERVAL_S` flooring the published `poll_resolution_s`, and the
# same reason -- a span nothing crossed is not a measurement of zero.
#
# `total time` is a float to two places and is *not* the way out of this: it
# times the whole run, container startup included, so it is finer and less
# relevant, and its own dispersion is partly Docker's.
METRIC_RESOLUTION = {'elapsed (s)': 1.0}

# What the rule is applied to.  The end-to-end number every graph in
# create_batch_graphs() is keyed on, and the one a version comparison is read
# from; a rule that ranged over all thirteen metrics would recommend expansion
# for every batch, since `min idle%` and `max cpu %` are noisy by nature and
# nobody ranks a daemon by them.
DECISION_METRIC = 'elapsed (s)'

# Five, from the plan, and a ceiling rather than a step: a cell that is still
# unseparated at five is not asking for a sixth pass.  It is saying those two
# targets are not distinguishable at this workload, which is a result -- and
# expanding without a limit is how a batch that cannot decide something spends
# a weekend failing to.
#
# It is a floor under the recommendation, never a cap on it.  A test that
# already declares more passes than this must not be told to rerun at five:
# following that advice would *reduce* the configured passes and throw away
# observations, and the cell that prompted it is the one whose spread matters
# most.  See `apply_variance_rule()`, which takes the declared count.
EXPANSION_PASSES = 5

SEPARATED = 'separated'
EXPAND = 'expand'
UNSEPARATED_AT_LIMIT = 'unseparated at the expansion limit'
UNDECIDED = 'undecided'

# Why the rule could not be applied.  Each is a different thing to do about it,
# which is why they are not one word: nothing to compare against is a property
# of the test as written, while a missing dispersion is a property of what came
# back from the passes.
NOTHING_TO_COMPARE = ('no other cell shares this cell\'s axes, so there is no '
                      'difference for its spread to cover')
# Distinct from the above, and it was published as it until review: a rival
# whose every pass failed has no median, so it drops out of the comparison
# entirely and the survivor claimed to have no rivals at all.  That is false
# about the test, and it is the wrong half of the distinction this module keeps
# -- nothing to compare against is a property of the matrix as written, while
# rivals that produced nothing is a property of what came back from the run,
# and only the second is something to go and fix.
# It names them, one by one, with why each has nothing.  A single verdict over
# a mixed group cannot be stated in one clause without losing the distinction
# it is drawing: an `any(... NOT_RUN ...)` over the group reported a rival that
# ran and failed every pass as a batch still in progress, as soon as one *other*
# rival was unstarted -- and the failed one is the only thing there an operator
# can go and fix.
RIVALS_WITHOUT_OBSERVATIONS = ('no other cell sharing this cell\'s axes has an '
                               'observation of {0}: {1}')
# One rival with no observation, where others were measurable. Less known than
# a rival with a median and no dispersion, not more -- so if that one withholds
# `separated`, this one has to as well, or the rule is stricter about the case
# it knows more about.  There is no gap to report with it: no median to take
# one from.
UNOBSERVED_RIVAL = ('{0} shares this cell\'s axes and has no observation of '
                    '{1} ({2}), so the group this cell would be ranked in is '
                    'not fully measured')
# The second half is quoted from the metric's own `withheld` entry rather than
# restated here.  There are four ways to arrive without a dispersion -- every
# pass failed, only one produced an observation, one reported the never-sampled
# sentinel, one reported something non-numeric -- and they are already told
# apart, in one place, by `summarize_metric()`.  A parallel set of strings here
# would answer the same question differently: a cell whose every pass failed
# read as "this cell has no dispersion", which is what one observation looks
# like too, and the difference between them is the whole reason the refusals
# are kept apart.
NO_DISPERSION = 'this cell has no dispersion for {0}: {1}'
NEIGHBOUR_NO_DISPERSION = ('no cell sharing this cell\'s axes has a dispersion '
                           'for {0} (the nearest is {1}), so no pair can be '
                           'separated or found unseparated')
# Clearing every rival that can be judged is not the same as clearing the
# group.  A rival with a median and no dispersion cannot be separated from or
# found unseparated -- but it is still drawn in the same bars, so a cell
# published `separated` while an unjudgeable rival sits *nearer* than the one
# that decided it makes exactly the claim the reader will take from the
# picture and cannot support.  This is the nearest-rival defect one path over:
# there it was the rival that decided the verdict, here it is the rival that
# was skipped.  It withholds only the `separated` verdict -- an unseparated one
# is already the conservative answer, and degrading those is how a single
# mostly-failed cell mutes its whole group.
NEARER_RIVAL_UNJUDGED = ('this cell clears every rival that has a dispersion '
                         'for {0}, but {1} is nearer still ({2} away) and has '
                         'none, so this cell cannot be called distinguishable '
                         'from the cells drawn beside it')

# A cell can reach the expansion ceiling without ever having been run that many
# times, because a failed pass produces no observation.  Rerunning at the same
# count would repeat the failure; the shortfall is the thing to look at.
SHORTFALL = ('{0} of {1} passes produced an observation, so the shortfall is a '
             'failed or unrun pass rather than a missing repetition')
# The same thing about the rival instead.  A cell that has spent all its passes
# can still be unseparated only because the *other* cell has not, and the
# recommendation then reduces to the count the test already ran -- advice that
# is a no-op, printed with nothing to say why.  Worse, the rival's own
# shortfall is filed under whichever pair *its* verdict binds to, which need
# not be this one, so following the no-op advice is exactly the "fix the pass,
# rerun at the count you already had, come back unseparated again" failure the
# shortfall was added to prevent -- reached through the rival rather than
# through the cell.
# Phrased to start with a word rather than with the rival's name: the printed
# line capitalises its first character, and a run name is what names an
# artifact, a CSV row and a bar, so `Bird 2.19.2` is a label the operator
# cannot search for. `SHORTFALL` above starts with a digit, which is why the
# same idiom is harmless there.
RIVAL_SHORTFALL = ('the pair is short because {0} produced {1} of {2} passes, '
                   'so what it needs is that cell\'s failed or unrun passes '
                   'rather than another repetition of this one')


def _unobserved_because(cell, metric):
    '''Why a rival has no observation: still to come, already failed, or both.

    The same distinction `summarize_cell()` keeps at the pass level, and it
    decides whether the reader has something to go and fix or a batch that is
    merely in progress. It is counted rather than tested for, because
    `NOT_RUN in states` let one unstarted pass describe a rival whose other
    two had failed as a batch still in progress -- which is the distinction
    being thrown away in the act of drawing it.
    '''
    states = [entry.get('state') for entry in (cell.get('passes') or [])]
    counted = [(sum(1 for state in states if state == name), label)
               for name, label in ((FAILED, 'failed'), (NOT_RUN, 'not run'),
                                   (UNREADABLE, 'unreadable'))]
    present = [(count, label) for count, label in counted if count]
    if any(state == OBSERVED for state in states):
        # Some pass did produce a row, so what is missing is the *metric*, not
        # the passes, and the metric's own reason leads. Deciding this on
        # "were any passes not observed" instead described a cell with two
        # observations and one non-numeric value as `1 failed` -- printed two
        # lines under its own `2 of 3 passes observed`, pointing the operator
        # at the failed pass rather than at the unreadable value.
        reason = _dispersion_withheld(cell, metric, 'median')
        if present:
            reason += '; of {0} passes, {1}'.format(
                len(states),
                ', '.join('{0} {1}'.format(c, l) for c, l in present))
        return reason
    if not present:
        # Every pass ran and the column is still empty, so the reason is the
        # metric's, not the passes'. Asserting a pass state here contradicted
        # `observations: 3` and three `observed` entries two keys away in the
        # same document; the cell's own refusal already quotes `withheld`, and
        # this is the same question one rival over.
        return _dispersion_withheld(cell, metric, 'median')
    if len(present) == 1:
        count, label = present[0]
        if count == len(states):
            return ('has not run yet' if label == 'not run'
                    else 'every pass {0}'.format(label))
    return 'of {0} passes, {1}'.format(
        len(states), ', '.join('{0} {1}'.format(c, l) for c, l in present))


def _comparison_key(cell):
    """The cells one graph draws side by side, which is what gets compared.

    Peers, prefixes and filter -- every axis of the matrix except the target
    itself, which is the thing being told apart. `create_graph()` groups its
    bars exactly this way, so the rule answers a question somebody is actually
    going to ask of the picture.
    """
    identity = cell.get('identity') or {}
    return (identity.get('peers'), identity.get('prefixes'),
            identity.get('filter'))


def _decision_statistics(cell, metric):
    stats = (cell.get('metrics') or {}).get(metric) or {}
    return stats.get('median'), stats.get('stdev')


def _dispersion_withheld(cell, metric, statistic='stdev'):
    """Why this cell has no such statistic, in the words the metric used."""
    stats = (cell.get('metrics') or {}).get(metric) or {}
    return ((stats.get('withheld') or {}).get(statistic)
            or 'no {0} was published'.format(statistic))


def apply_variance_rule(cells, metric=DECISION_METRIC,
                        expansion_passes=EXPANSION_PASSES, repetitions=1):
    """Say, per cell, whether its passes separate it from the cells beside it.

    Mutates each cell to carry a `variance` section, and returns the cells, in
    the shape findings.py publishes a verdict: the rule that was applied and
    the numbers it was applied to, beside the verdict, because a verdict
    nobody can argue with is a boolean with extra words.

    **Every rival is tested, not just the nearest one.**  The nearest cell by
    median is the obvious candidate and it is the wrong one: separating a cell
    from its closest neighbour separates it from the rest of the group only if
    every rival has the same dispersion.  With bird at 40 +/- 0.01, frr at 41
    +/- 0.01 and gobgp at 45 +/- 10, bird clears its nearest rival by a mile
    and is not separated from gobgp at all -- and `create_graph()` draws all
    three side by side, so a reader takes `separated` to mean "distinguishable
    from the others here".  The verdict is therefore decided by the *binding*
    rival: the one with the smallest margin between the gap and the combined
    deviation, which is the closest call in the group and the one a reader
    would challenge first.

    `repetitions` is what the test declared, and the recommendation never goes
    below it: telling a `repetitions: 7` test to rerun at five would reduce its
    passes and discard observations.
    """
    ceiling = max(expansion_passes, repetitions or 1)
    resolution = METRIC_RESOLUTION.get(metric, 0.0)
    by_axes = {}
    for cell in cells:
        by_axes.setdefault(_comparison_key(cell), []).append(cell)

    for cell in cells:
        median, stdev = _decision_statistics(cell, metric)
        observed = cell.get('observations') or 0
        expected_passes = cell.get('passes_expected') or 0
        # `observations`, not `passes_observed`: the value comes straight from
        # `cell['observations']`, and a near-anagram of the sibling
        # `cell['observed_passes']` -- which is a *list* of repetition numbers
        # -- sitting nested inside the same document is a trap for anything
        # reading it, this module included.
        verdict = {'metric': metric, 'policy': VARIANCE_RULE,
                   'observations': observed}
        others = [other for other in by_axes[_comparison_key(cell)]
                  if other is not cell]
        # Two filters, not one. A rival with no median cannot be compared at
        # all; a rival with a median but no dispersion can still be shown to
        # the reader as a gap, which is why the two are kept apart.
        comparable = [other for other in others
                      if _decision_statistics(other, metric)[0] is not None]
        measurable = [other for other in comparable
                      if _decision_statistics(other, metric)[1] is not None]
        # Every rival the rule could not judge, named whatever the verdict
        # turns out to be -- including the refusal below, which otherwise
        # named only the nearest one inside its reason string and left the
        # others unmentioned anywhere. A reader comparing two cells of one
        # group has to be able to see that the rule looked at fewer rivals
        # than the graph draws: `rivals_considered: 1` cannot otherwise be
        # told from "one of two".
        #
        # Drawn from `others`, not `comparable`: a rival that produced no
        # observation at all has no median, so filtering on that dropped it
        # out of the naming as well as out of the comparison, and it went
        # unmentioned anywhere in the verdict.
        unjudged = [other for other in others
                    if _decision_statistics(other, metric)[1] is None]
        # The subset with no observation whatsoever, which is less known than a
        # rival with a median and no dispersion rather than more. Withholding
        # `separated` for the second while publishing it beside the first would
        # be incoherent, so both withhold -- this one without a gap to report,
        # since there is no median to take one from.
        unobserved = [other for other in others
                      if _decision_statistics(other, metric)[0] is None]

        # Hoisted above every branch, so no verdict can be the one that names
        # none of its rivals. `rivals_considered: 1` cannot otherwise be told
        # from "one of two", and the branch that reports rivals without
        # observations named nothing at all.
        verdict['rivals_considered'] = len(measurable)
        if unjudged:
            verdict['rivals_unjudged'] = [other['description']
                                          for other in unjudged]

        def gap_to(other):
            return abs(_decision_statistics(other, metric)[0] - median)

        def combined_deviation(other):
            '''The spread the gap has to clear, never below the quantum.

            Passes that agree exactly agree to within one bucket, not to
            within nothing; see `METRIC_RESOLUTION`.
            '''
            return max(stdev + _decision_statistics(other, metric)[1],
                       resolution)

        def margin_to(other):
            return gap_to(other) - combined_deviation(other)

        def evidence_for(other, chosen_by):
            '''The pair the verdict was decided on, and how that rival was
            picked.

            These keys were `nearest_*` and only one of the two branches
            picks the nearest rival. The other picks the *binding* one -- the
            smallest margin, which in the group bird 40, frr 41, gobgp 45 is
            gobgp, the cell furthest away. A reader of `<test>.summary.json`
            taking `nearest_cell` literally would conclude the rule had
            compared a different pair than it did, and this document exists to
            be argued with.
            '''
            rival_median, rival_stdev = _decision_statistics(other, metric)
            found = {
                'median': median,
                'stdev': stdev,
                'rival_cell': other['cell'],
                'rival_description': other['description'],
                'rival_median': rival_median,
                'rival_stdev': rival_stdev,
                'rival_chosen_by': chosen_by,
                'gap': _round(gap_to(other)),
            }
            if rival_stdev is not None:
                # Both published: the floor is part of the verdict, so a
                # reader who adds the two deviations and gets something
                # smaller has to be able to see why.
                found['combined_stdev'] = _round(combined_deviation(other))
                found['metric_resolution'] = resolution
                found['margin'] = _round(margin_to(other))
            return found

        if median is None or stdev is None:
            verdict['verdict'] = UNDECIDED
            verdict['reason'] = NO_DISPERSION.format(
                metric, _dispersion_withheld(cell, metric))
        elif not others:
            verdict['verdict'] = UNDECIDED
            verdict['reason'] = NOTHING_TO_COMPARE
        elif not comparable:
            verdict['verdict'] = UNDECIDED
            # Each rival separately: a rival that has not run yet is not a
            # rival that produced nothing, and the summary is written before
            # the first cell and rewritten after every one, so for most of a
            # batch these are simply unstarted. An interrupted batch leaves
            # exactly that document behind, since the surviving file is the
            # last checkpoint.
            verdict['reason'] = RIVALS_WITHOUT_OBSERVATIONS.format(
                metric, '; '.join(
                    '{0} ({1})'.format(other['description'],
                                       _unobserved_because(other, metric))
                    for other in others))
            # This refusal names rivals, so it is one the reader has to see --
            # a group whose rival failed every pass otherwise printed nothing,
            # and silence is what an endorsed ranking looks like. It carries no
            # `evidence`, having no rival median to take a gap from, so
            # `withheld_by` is what makes it printable and gives the line a
            # pair to be de-duplicated on.
            verdict['withheld_by'] = others[0]['cell']
        elif not measurable:
            # Only when *no* rival has a dispersion. Picking the nearest first
            # and then noticing it had none let one degraded cell -- two of
            # three passes failed -- sit between two cells that were plainly
            # unseparated and mute the verdict for both, with nothing printed
            # to say the rule had been silenced.
            nearest = min(comparable, key=gap_to)
            verdict['evidence'] = evidence_for(nearest, 'gap')
            verdict['verdict'] = UNDECIDED
            verdict['reason'] = NEIGHBOUR_NO_DISPERSION.format(
                metric, nearest['description'])
        else:
            binding = min(measurable, key=margin_to)
            verdict['evidence'] = evidence_for(binding, 'margin')
            # Only a rival *nearer* than the one that decided it. A further
            # unjudgeable rival does not contradict the claim, and withholding
            # on any unjudgeable rival at all would mute a whole group for one
            # cell whose passes failed -- which is the thing the `measurable`
            # preference above exists to prevent.
            # `<=`, not `<`: a rival sitting exactly as close as the one
            # that decided the verdict contradicts "distinguishable from the
            # cells drawn beside it" just as completely as a closer one, and
            # an equal gap is the likeliest shape of all here, since the
            # decision metric is quantised.
            nearer = [other for other in unjudged
                      if _decision_statistics(other, metric)[0] is not None
                      and gap_to(other) <= gap_to(binding)]
            if verdict['evidence']['margin'] > 0 and nearer:
                closest = min(nearer, key=gap_to)
                verdict['verdict'] = UNDECIDED
                verdict['reason'] = NEARER_RIVAL_UNJUDGED.format(
                    metric, closest['description'], _round(gap_to(closest)))
                # The relation this verdict reports is against *this* cell,
                # not against the binding rival in `evidence`. The printed
                # lines are de-duplicated per pair, so without saying which
                # cell withheld the verdict, two cells demoted by two
                # different unjudged rivals collapse onto one pair key and one
                # of the two refusals is never printed.
                verdict['withheld_by'] = closest['cell']
            elif verdict['evidence']['margin'] > 0 and unobserved:
                blocking = unobserved[0]
                verdict['verdict'] = UNDECIDED
                verdict['reason'] = UNOBSERVED_RIVAL.format(
                    blocking['description'], metric,
                    _unobserved_because(blocking, metric))
                verdict['withheld_by'] = blocking['cell']
            elif verdict['evidence']['margin'] > 0:
                verdict['verdict'] = SEPARATED
            elif (observed < ceiling
                  or (binding.get('observations') or 0) < ceiling):
                # The rival's observations as well as this cell's. The claim
                # `unseparated at the expansion limit` makes -- "more passes
                # will not decide it" -- is about the *pair*, and a rival that
                # produced two of its five passes has not spent the passes that
                # claim assumes. Decided from this cell alone, a fully observed
                # cell published that verdict beside a rival whose dispersion
                # could not support it.
                verdict['verdict'] = EXPAND
                # Three separate reasons a pair can be short, and a cell can
                # carry more than one of them. They are told apart by what the
                # operator would do about each, and a recommendation is only
                # emitted where following it would change something.
                #
                # A failed pass produces no observation, so a cell can fall
                # short without the test ever having asked for fewer passes.
                if observed < expected_passes:
                    verdict['shortfall'] = SHORTFALL.format(
                        observed, expected_passes)
                # Only where the test asked for fewer passes than the ceiling.
                # Keyed on observations alone, a cell that had already run
                # `ceiling` passes and lost some of them was told to rerun at
                # the count it had just run -- the same no-op advice the
                # `rival_shortfall` branch was added to avoid, reached through
                # the cell's own shortfall instead of the rival's.
                if observed < ceiling and expected_passes < ceiling:
                    verdict['passes_recommended'] = ceiling
                # And if neither, this cell has spent every pass it was given
                # and what the pair is short of belongs to the rival.
                if 'shortfall' not in verdict and 'passes_recommended' not in verdict:
                    verdict['rival_shortfall'] = RIVAL_SHORTFALL.format(
                        binding['description'],
                        binding.get('observations') or 0,
                        binding.get('passes_expected') or 0)
            else:
                verdict['verdict'] = UNSEPARATED_AT_LIMIT
        cell['variance'] = verdict
    return cells


def _is_number(value):
    # A nan or an inf is not an observation.
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def _publishable(value):
    '''A value that survives `json.dump` into a document a strict parser reads.

    `json.dump` writes a nan or an inf as a bare word that jq and most
    non-Python parsers reject, so one is published as its own repr: the fact
    that a pass reported it is kept, and it is already not a number, so every
    statistic over that column is withheld anyway.
    '''
    if isinstance(value, float) and not math.isfinite(value):
        return repr(value)
    return value


def _round(value):
    return round(float(value), _PLACES)


def summarize_metric(values, unsampled=None):
    '''One column's distribution over the observed passes of one cell.

    `min` and `max` are observations and are copied through unrounded: a
    summary must not report an extreme no run produced.  Everything else is
    derived, so it is rounded, and `mean` is published because the coefficient
    of variation is otherwise a number a reader cannot check.

    `unsampled` is the value this column carries when the run never measured
    it.  One of those withholds the whole column for the cell rather than
    being dropped from it, for the same reason a non-numeric value does: a
    minimum that starts above every real value reaches the row as a machine
    with a petabyte free, and a cell where one pass of three lost its sampler
    would otherwise publish a coefficient of variation of 173% on a 64 GB box.
    '''
    raw = list(values)
    sentinel = [_is_number(v) and unsampled is not None and v == unsampled
                for v in raw]
    published = [None if seen else _publishable(v)
                 for v, seen in zip(raw, sentinel)]
    summary = {'values': published, 'n': len(published)}
    summary.update({name: None for name in _STATISTICS})
    withheld = {}
    if not raw:
        withheld = {name: NO_OBSERVATION for name in _STATISTICS}
    elif any(sentinel):
        withheld = {name: UNSAMPLED for name in _STATISTICS}
    elif not all(_is_number(v) for v in raw):
        # Dropping the offending pass instead would change n without saying
        # so, which is the one thing a dispersion cannot survive.
        withheld = {name: NON_NUMERIC for name in _STATISTICS}
    else:
        values = raw
        mean = statistics.fmean(values)
        summary['min'] = min(values)
        summary['max'] = max(values)
        summary['mean'] = _round(mean)
        summary['median'] = _round(statistics.median(values))
        if len(values) < 2:
            withheld['stdev'] = NEEDS_TWO
            withheld['cv_percent'] = NEEDS_TWO
        else:
            # Sample standard deviation, n-1: three passes are a sample of what
            # the machine does, and the population formula understates the
            # spread of one -- to exactly 0 at n=1.
            stdev = statistics.stdev(values)
            summary['stdev'] = _round(stdev)
            if mean > 0:
                summary['cv_percent'] = _round(100.0 * stdev / mean)
            else:
                withheld['cv_percent'] = MEAN_NOT_POSITIVE
    if withheld:
        summary['withheld'] = withheld
    return summary


def _agreement(rows, index, column):
    '''One value if every observed pass reported the same one, else all of them.

    Returns (value, disagreement) so the caller can both publish the field and
    say out loud that the passes did not agree about it.
    '''
    distinct = []
    for row in rows:
        value = row[index[column]]
        if value not in distinct:
            distinct.append(value)
    if not distinct:
        return None, None
    if len(distinct) == 1:
        return distinct[0], None
    return distinct, distinct


def summarize_cell(header, group, unavailable=None):
    '''One matrix cell: what was asked of it, which passes answered, and the
    distribution of those answers.

    The cell supplies the identity, because it is known whether or not any
    pass produced a row -- a cell whose every pass failed still has to say
    which cell it was.  The rows supply what came back.

    A row that is not this header's width costs its own pass and nothing else.
    `--resume` onto a progress file written before a column was appended is a
    supported path -- `BATCH_PROGRESS_SCHEMA_VERSION` deliberately did not move
    for `max foreign cpu %` -- and one short row indexed against this header
    raises `IndexError`, which the caller catches into *no summary at all* for
    the whole test, naming neither the cell nor the pass.  A row that is the
    right width but the wrong layout cannot be caught here at all, which is why
    `stats_header()` is the contract and `test_stats_contract.py` enforces it.
    '''
    index = {name: position for position, name in enumerate(header)}
    unavailable = unavailable or {}
    passes = []
    observed = []
    for entry in group['passes']:
        row = entry.get('row')
        described = {'repetition': entry.get('repetition')}
        if row is None:
            described['state'] = NOT_RUN
        elif len(row) != len(header):
            described['state'] = UNREADABLE
            described['message'] = (
                'row has {0} field(s), this header has {1}'.format(
                    len(row), len(header)))
        elif row[index[FAILED_COLUMN]] == FAILED_VALUE:
            described['state'] = FAILED
            described['message'] = row[index[MESSAGE_COLUMN]]
        else:
            described['state'] = OBSERVED
            observed.append(entry)
        passes.append(described)

    rows = [entry['row'] for entry in observed]
    identity = dict(group.get('identity') or {})
    inconsistent = {}
    for column in ROW_IDENTITY_COLUMNS:
        identity[column], disagreement = _agreement(rows, index, column)
        if disagreement:
            inconsistent[column] = disagreement
    provenance = {}
    for column in PROVENANCE_COLUMNS:
        provenance[column], disagreement = _agreement(rows, index, column)
        if disagreement:
            inconsistent[column] = disagreement

    summary = {
        'cell': group['ordinal'],
        'name': group['name'],
        # The run name is the target; two cells of one target differ only in
        # their axes, so a printed line naming only the target names both.
        'description': group.get('description') or group['name'],
        'identity': identity,
        'provenance': provenance,
        'passes_expected': len(group['passes']),
        'observations': len(observed),
        # In the same order as every metric's `values`, so a reader can say
        # which pass produced which number without a second lookup.
        'observed_passes': [entry.get('repetition') for entry in observed],
        'passes': passes,
        'metrics': {
            column: summarize_metric([row[index[column]] for row in rows],
                                     unsampled=unavailable.get(column))
            for column in METRIC_COLUMNS},
    }
    if inconsistent:
        summary['inconsistent'] = inconsistent
    return summary


def summarize_batch(test_name, header, groups, repetitions=1, unavailable=None):
    '''The whole test, one entry per matrix cell, in the order given.

    Matrix order, for the same reason the CSV is written in it: a shuffled
    execution order is a property of the run, not of the report.

    `unavailable` maps a column to the value a run writes into it when it
    never sampled it; see `summarize_metric()`.
    '''
    missing = [column for column in
               METRIC_COLUMNS + PROVENANCE_COLUMNS + ROW_IDENTITY_COLUMNS
               + (FAILED_COLUMN, MESSAGE_COLUMN)
               if column not in header]
    if missing:
        raise ValueError(
            'the stats header does not carry {0}; summary.py reads the row by '
            'column name and cannot guess'.format(', '.join(missing)))
    cells = [summarize_cell(header, group, unavailable=unavailable)
             for group in groups]
    document = {
        'schema': SUMMARY_SCHEMA,
        'test': test_name,
        'repetitions': repetitions,
        'cells': cells,
    }
    # A policy that raises costs the verdict, not the evidence -- the same rule
    # `write_event_artifact()` applies to `derive_findings()`, and for the same
    # reason: by the time the rule runs, these statistics are the only record
    # of what the passes measured, and `publish_batch_summary()` catches at the
    # outer level, so anything raised here loses the whole document at the end
    # of a multi-hour batch. The rule is a *derived* opinion about numbers that
    # are already computed and correct.
    #
    # After every cell exists, because the rule reads a cell against its
    # rivals and a cell cannot be judged before they are all summarised.
    # `repetitions` goes in so the recommendation cannot come back lower than
    # what the test already asked for.
    try:
        apply_variance_rule(cells, repetitions=repetitions)
        document['variance_rule'] = VARIANCE_RULE
    except Exception as failure:      # noqa: BLE001 - see above
        # Partial verdicts are dropped rather than published. The rule reads
        # each cell against its group, so a run that stopped part way leaves
        # some cells of one group judged and others not, and nothing in the
        # document says which -- a ranking that cannot be argued with is the
        # failure this module exists to avoid.
        for cell in cells:
            cell.pop('variance', None)
        document['variance_failure'] = (
            'the variance rule raised {0}: {1}'.format(
                type(failure).__name__, failure))
    return document


def _describe_metric(metric):
    reported = '{0} median {1}'.format(metric['name'], metric['median'])
    reported = '{0} ({1}-{2})'.format(reported, metric['min'], metric['max'])
    if metric['cv_percent'] is None:
        return '{0}, CV unavailable'.format(reported)
    return '{0}, CV {1:.2f}%'.format(reported, metric['cv_percent'])


# The verdicts that get a printed line. `separated` is not one of them -- the
# rule is silent about the results it supports -- but a refusal is: silence
# would otherwise mean both "the rule endorsed this ranking" and "the rule
# could not judge it", which are the two things a reader most needs told apart.
# That is the same complaint the `not measurable` branch above was fixed for:
# there the verdict was corrected and the printing was not.
PRINTED_VERDICTS = (EXPAND, UNSEPARATED_AT_LIMIT, UNDECIDED)

# How much a verdict asks of the operator, for choosing which half of a
# mutual pair gets the one printed line. A shortfall is something to go and
# investigate, `expand` is something to do, "more passes will not decide it"
# is something to accept, and a refusal names work that has to happen before
# the question can be asked at all -- so they rank in that order.
_VARIANCE_RANK = {UNDECIDED: 1, UNSEPARATED_AT_LIMIT: 2, EXPAND: 3}


def _variance_rank(cell):
    if cell is None:
        return 0
    variance = cell['variance']
    return (_VARIANCE_RANK.get(variance['verdict'], 0)
            + (1 if variance.get('shortfall') else 0))


def _variance_pair(cell):
    """The two cells one printed line is about.

    Usually the cell and its binding rival, and they are usually mutual, which
    is what the de-duplication is for. A withheld separation is the exception:
    the relation it reports is against the unjudgeable cell that blocked it,
    not against the rival in `evidence` that the rule got as far as measuring.
    Keying those on the binding rival collapsed two cells demoted by two
    different unjudged rivals onto one pair, and matrix position then decided
    which of the two refusals was printed at all -- which is the defect the
    ranking above exists to prevent, reached one path over.
    """
    variance = cell['variance']
    if 'withheld_by' in variance:
        partner = variance['withheld_by']
    else:
        partner = variance['evidence']['rival_cell']
    return frozenset((cell['cell'], partner))


def _sentence(text):
    '''A clause as a sentence, without rewriting a name it may start with.'''
    return text[0].upper() + text[1:] if text[:1].islower() else text


def _describe_variance(cell):
    """One line about a cell whose passes did not settle it against its rival."""
    variance = cell['variance']
    if variance['verdict'] == UNDECIDED:
        # `evidence` is deliberately not read here. A refusal reached because
        # no rival has a dispersion carries no combined deviation, so the
        # comparison sentence below cannot be built for it -- and reading the
        # key up front, before the branch, made that a `KeyError` at the end of
        # a batch that had already run for hours.
        #
        # It is not phrased as a pair either: the rival in `evidence` is the
        # one the rule got as far as measuring, which for a withheld
        # separation is not the cell that withheld it. The reason names that
        # one.
        return '  variance rule: no verdict for {0}: {1}.'.format(
            cell['description'], variance['reason'])
    evidence = variance['evidence']
    where = ('{0} is not separated from {1} on {2}: medians {3} and {4} differ '
             'by {5}, inside a combined deviation of {6}'.format(
                 cell['description'], evidence['rival_description'],
                 variance['metric'], evidence['median'],
                 evidence['rival_median'], evidence['gap'],
                 evidence['combined_stdev']))
    if variance['verdict'] == EXPAND:
        # Both facts, never one instead of the other. A failed pass and a
        # rerun count are separate things to do about the same cell, and the
        # shortfall used to replace the count: with `repetitions: 3` and one
        # failed pass, the only line printed said to investigate the failure,
        # the pair de-duplication suppressed the rival's line that carried the
        # count, and the obvious next move -- fix the pass, rerun at three --
        # comes back unseparated again.
        # Whichever of the three the verdict carries, in the order an
        # operator would act on them, and never a recommendation that is the
        # count the test already ran.
        advice = []
        if 'passes_recommended' in variance:
            advice.append('Rerun this test with repetitions: {0}'.format(
                variance['passes_recommended']))
        for key in ('shortfall', 'rival_shortfall'):
            if variance.get(key):
                advice.append(_sentence(variance[key]))
        return '  variance rule: {0}. {1}.'.format(where, '. '.join(advice))
    return ('  variance rule: {0}, over {1} passes. More passes will not '
            'decide it: these two are not distinguishable at this '
            'workload.'.format(where, variance['observations']))


def describe_batch_summary(document, path=None):
    '''The lines a batch prints about its own repeatability.

    Nothing for a single-pass test: every dispersion in it is withheld, and a
    block of "CV unavailable" says only that the test asked for one pass.  A
    disagreement between passes is printed whenever there is one, because that
    is the finding, not the statistic beside it.
    '''
    lines = []
    cells = document.get('cells') or []
    repetitions = document.get('repetitions') or 1
    if repetitions > 1:
        heading = 'repeatability over {0} passes'.format(repetitions)
        lines.append('{0} ({1}):'.format(heading, path) if path else heading + ':')
        # Under the heading, and inside this gate. Said out loud rather than
        # left to the artifact, because the rule prints nothing about the
        # results it supports, so a batch whose rule raised looks exactly like
        # one whose every cell was separated. But only where a verdict could
        # have been printed at all: a single-pass test's every dispersion is
        # withheld, so no cell of one can carry a printable verdict, and
        # emitting this outside the gate put a lone indented line into the
        # output of a `repetitions: 1` batch with no heading naming the test
        # or the summary path -- and every checked-in benchmark config is
        # single-pass.
        if document.get('variance_failure'):
            lines.append('  variance rule: no verdicts -- {0}'.format(
                document['variance_failure']))
        for cell in cells:
            described = ['{0}: {1} of {2} passes observed'.format(
                cell['description'], cell['observations'],
                cell['passes_expected'])]
            for column in PRINTED_METRICS:
                metric = cell['metrics'].get(column) or {}
                if metric.get('median') is None:
                    continue
                described.append(_describe_metric(dict(metric, name=column)))
            lines.append('  ' + '; '.join(described))
            for entry in cell['passes']:
                if entry['state'] == OBSERVED:
                    continue
                lines.append('    pass {0}: {1}{2}'.format(
                    entry['repetition'], entry['state'],
                    ' ({0})'.format(entry['message']) if entry.get('message') else ''))
    # Only the cells the rule reached a verdict about, and only the verdicts
    # that ask for something. A cell that is separated needs no line: the whole
    # point of the rule is that it is silent about the results it supports.
    # One line per unseparated *pair*, not per cell. The verdict is per cell
    # and the binding rival is usually mutual, so a two-target group otherwise
    # states the same relation twice with identical numbers -- and a matrix of
    # 4 peers x 3 prefixes x 2 filters x 3 targets ends a multi-hour batch with
    # 72 lines that are 36 facts.
    #
    # Which of the pair's two verdicts gets that line is decided by what it
    # asks the operator to do, not by which cell has the lower ordinal. The two
    # sides need not agree: with `repetitions: 5` a cell whose passes all
    # succeeded is `unseparated at the expansion limit` -- "more passes will
    # not decide it" -- while the rival that lost two of them is `expand`
    # carrying a shortfall, which is a failed pass to go and look at. Taking
    # the first seen meant matrix position chose between those two pieces of
    # advice, and printed the one that says to do nothing.
    chosen, order = {}, []
    for cell in cells:
        variance = cell.get('variance') or {}
        # A refusal that names no rival -- this cell has no dispersion at all,
        # or nothing shares its axes -- is not printed: it has no pair, and its
        # cause is already there as the cell's own failed passes. Every other
        # refusal is, which is the documented contract, so the test is for
        # something that identifies a rival rather than for `evidence`
        # specifically: the branch reporting rivals without observations names
        # them and has no evidence to give.
        if (variance.get('verdict') not in PRINTED_VERDICTS
                or not ('evidence' in variance or 'withheld_by' in variance)):
            continue
        pair = _variance_pair(cell)
        if pair not in chosen:
            order.append(pair)
        if _variance_rank(cell) > _variance_rank(chosen.get(pair)):
            chosen[pair] = cell
    for pair in order:
        lines.append(_describe_variance(chosen[pair]))
    for cell in cells:
        for column, values in sorted((cell.get('inconsistent') or {}).items()):
            lines.append(
                '  warning: {0} passes disagree on {1}: {2}. These are not '
                'repeated observations of one thing.'.format(
                    cell['description'], column,
                    ', '.join(repr(v) for v in values)))
    return lines
