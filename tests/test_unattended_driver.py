'''The driver that runs a worker when nobody is watching.

What is worth testing here is not the loop -- it is four lines -- but the
refusals, because every one of them is a way an unattended run looks like it is
working while it is not: a worker on master, a gate nobody was told about, a
worker claiming the gate it just raised, and an empty queue mistaken for a
crash or the reverse.

Pure: no Docker, no `claude`, no network. The driver is exercised with
`--dry-run`, which starts no worker, and with a notification channel that is a
file.
'''
import os
import re
import subprocess
import sys

import pytest

from conftest import REPO_ROOT

DRIVER = REPO_ROOT / 'scripts' / 'unattended_driver.sh'
NOTIFIER = REPO_ROOT / 'scripts' / 'notify_gate.sh'
PROMPT = REPO_ROOT / 'scripts' / 'unattended_worker_prompt.md'


def run(argv, env=None, **kwargs):
    environment = dict(os.environ)
    environment.pop('BGPERF_NOTIFY_CMD', None)
    if env:
        environment.update(env)
    return subprocess.run([str(a) for a in argv], capture_output=True,
                          text=True, env=environment, timeout=120, **kwargs)


def sink(tmp_path):
    '''A notification channel that delivers, so the message can be read back.'''
    path = tmp_path / 'notifications.log'
    return path, 'cat >> {0}'.format(path)


@pytest.fixture
def clean_checkout(tmp_path):
    """A minimal clean git repo holding the three scripts.

    The driver now refuses to start on a dirty tree -- correctly, since an
    unattended worker would review and commit whatever it found under whatever
    item it took first. That makes every test that drives it past startup
    depend on *this* checkout being clean, which during development it never
    is. So they get their own.
    """
    root = tmp_path / 'checkout'
    (root / 'scripts').mkdir(parents=True)
    for script in (DRIVER, NOTIFIER, PROMPT):
        target = root / 'scripts' / script.name
        target.write_text(script.read_text())
        target.chmod(0o755)
    # `venv/bin/python` is the interpreter the driver runs its parsers with.
    (root / 'venv' / 'bin').mkdir(parents=True)
    (root / 'venv' / 'bin' / 'python').symlink_to(sys.executable)
    for argv in (['init', '-q', '-b', 'unattended/measurement'],
                 ['add', '-A'],
                 ['-c', 'user.email=t@t', '-c', 'user.name=t',
                  'commit', '-qm', 'scripts']):
        subprocess.run(['git', '-C', str(root)] + argv, check=True,
                       capture_output=True)
    return root


def current_branch():
    return subprocess.run(['git', '-C', str(REPO_ROOT), 'rev-parse',
                           '--abbrev-ref', 'HEAD'],
                          capture_output=True, text=True).stdout.strip()


def recording_bd(tmp_path):
    """A `bd` that records the arguments it was called with and returns an
    empty queue, so the driver's own query can be asserted on."""
    path = tmp_path / 'recording-bd'
    path.write_text(
        '#!/usr/bin/env bash\n'
        'echo "$@" >> {0}/bd-args\n'
        'printf %s "[]"\n'.format(tmp_path))
    path.chmod(0o755)
    return str(path)


def stub_bd(tmp_path, ready='[]', gates='[]', status=0, fail='ready'):
    '''A `bd` that answers exactly what a test needs.

    The driver is pointed at this with BGPERF_BD_BIN. Asserting against the
    real tracker is what the first version of these tests did, and it made the
    empty-queue test pass whether or not the empty-queue path was ever taken
    -- and pass equally for a tracker that was simply absent, which is the one
    case the driver must *not* treat as empty.
    '''
    path = tmp_path / 'stub-bd'
    # Only the named subcommand fails. Failing both made the
    # tracker-cannot-be-read test pass on `open_gate_ids`' message instead of
    # `first_ready`'s -- so it still passed with the check it was written for
    # deleted, which is the vacuity this helper's own docstring warns about.
    path.write_text(
        '#!/usr/bin/env bash\n'
        'kind=""\n'
        'for a in "$@"; do\n'
        '  [[ "$a" == "ready" ]] && kind=ready\n'
        '  [[ "$a" == "list" ]] && kind=list\n'
        'done\n'
        '[[ "$kind" == {fail!r} ]] && exit {status}\n'
        'case "$kind" in\n'
        '  ready) printf %s {ready!r} ;;\n'
        '  list)  printf %s {gates!r} ;;\n'
        'esac\n'
        'exit 0\n'.format(status=status, gates=gates, ready=ready, fail=fail))
    if status == 0:
        path.write_text(
            '#!/usr/bin/env bash\n'
            'kind=""\n'
            'for a in "$@"; do\n'
            '  [[ "$a" == "ready" ]] && kind=ready\n'
            '  [[ "$a" == "list" ]] && kind=list\n'
            'done\n'
            'case "$kind" in\n'
            '  ready) printf %s {ready!r} ;;\n'
            '  list)  printf %s {gates!r} ;;\n'
            'esac\n'
            'exit 0\n'.format(ready=ready, gates=gates))
    path.chmod(0o755)
    return str(path)


class TestTheScriptsAreValid:
    def test_both_scripts_parse(self):
        for script in (DRIVER, NOTIFIER):
            result = run(['bash', '-n', script])
            assert result.returncode == 0, (script.name, result.stderr)

    def test_the_worker_prompt_exists_and_names_its_item(self):
        text = PROMPT.read_text()
        assert '{{ITEM}}' in text, 'the driver substitutes this'


class TestTheNotificationPath:
    """`A gate nobody sees is worse than stopping.`

    An unattended worker is by construction one nobody is watching, so the
    channel is not optional and "configured" is not the same as "delivers".
    """

    def test_an_unconfigured_channel_refuses_with_its_own_status(self):
        result = run([NOTIFIER, '--check'])
        # 78 is EX_CONFIG: nothing is misconfigured, there is no configuration.
        # Distinct from 1 so the driver can tell "set this up" from "your
        # channel is broken", which are different things to tell an operator.
        assert result.returncode == 78
        assert 'BGPERF_NOTIFY_CMD' in result.stderr

    def test_a_channel_that_delivers_says_where_it_came_from(self, tmp_path):
        path, command = sink(tmp_path)
        result = run([NOTIFIER, '--check'], env={'BGPERF_NOTIFY_CMD': command})
        assert result.returncode == 0
        delivered = path.read_text()
        # The hostname directly, not `'@' in delivered` -- the footer always
        # carries an `@ <timestamp>`, so that disjunct was true of every
        # message and the test would have passed with the footer deleted.
        assert os.uname().nodename in delivered
        assert 'notification check' in delivered

    def test_the_documented_channels_all_consume_stdin(self):
        """`--check` cannot tell a channel that delivers from one that exits 0
        having read nothing. `tmux display-message -p` was listed and is
        exactly that trap: it never reads stdin and prints to stdout, which the
        notifier sends to /dev/null."""
        text = NOTIFIER.read_text()
        assert 'tmux display-message -p' not in text.replace(
            '`tmux display-message -p` was listed here and is the trap', '')

    def test_a_channel_that_fails_is_not_reported_as_delivered(self, tmp_path):
        result = run([NOTIFIER, 'subject'], env={'BGPERF_NOTIFY_CMD': 'false'})
        assert result.returncode == 1
        assert 'NOT told' in result.stderr

    def test_there_is_no_fallback_that_writes_somewhere_nobody_reads(self):
        """The tempting fix is a local log file. That *is* a gate nobody sees,
        so it would satisfy the code and defeat the rule."""
        text = NOTIFIER.read_text()
        assert 'exit 78' in text
        # No default value for the channel anywhere.
        assert not re.search(r'BGPERF_NOTIFY_CMD:[-=][^}]', text)


class TestTheDriverRefusesToStartBlind:
    def test_it_will_not_run_without_a_notification_channel(self, tmp_path,
                                                            clean_checkout):
        # Not `--dry-run`: a dry run raises no gates and so deliberately needs
        # no channel. Run from a clean checkout, because the startup tree check
        # would otherwise refuse first -- on this repo's own uncommitted work.
        result = run([clean_checkout / 'scripts' / DRIVER.name, '--once'],
                     env={'BGPERF_BD_BIN': stub_bd(tmp_path)})
        assert result.returncode != 0
        assert 'gate nobody sees' in result.stderr

    def test_it_will_not_run_on_a_dirty_tree(self, tmp_path, clean_checkout):
        """An unattended worker would review and commit whatever it found
        under whatever item it took first."""
        _path, command = sink(tmp_path)
        (clean_checkout / 'stray.log').write_text('left behind\n')
        result = run([clean_checkout / 'scripts' / DRIVER.name, '--once'],
                     env={'BGPERF_NOTIFY_CMD': command,
                          'BGPERF_BD_BIN': stub_bd(tmp_path)})
        assert result.returncode != 0
        assert 'the tree is not clean' in result.stderr

    def test_a_dry_run_does_not_page_the_operator(self, tmp_path):
        """Checking does not probe the channel, it *sends* through it, so an
        operator iterating on a --dry-run invocation pages themselves once per
        attempt on the alert channel."""
        path, command = sink(tmp_path)
        run([DRIVER, '--dry-run'],
            env={'BGPERF_NOTIFY_CMD': command,
                 'BGPERF_UNATTENDED_BRANCH': current_branch(),
                 'BGPERF_BD_BIN': stub_bd(tmp_path)})
        assert not path.exists() or path.read_text() == ''

    def test_it_refuses_a_branch_that_is_not_the_unattended_one(self, tmp_path):
        """Pinned to a branch nothing is ever on, so this exercises the
        refusal wherever the suite runs. It used to `skip` whenever you were
        on the branch -- which is always, in real use -- so the one guard that
        is branch-aware was the one never tested."""
        _path, command = sink(tmp_path)
        result = run([DRIVER, '--dry-run'],
                     env={'BGPERF_NOTIFY_CMD': command,
                          'BGPERF_UNATTENDED_BRANCH': 'nonesuch/branch'})
        assert result.returncode != 0
        assert 'nonesuch/branch' in result.stderr

    def test_the_branch_is_checked_inside_the_loop_too(self):
        """A worker is perfectly capable of checking out a branch mid-run, so
        checking once before the first iteration is not enough."""
        text = DRIVER.read_text()
        body = text.split('while :; do', 1)[1]
        assert 'on_the_branch' in body


class TestTheQueue:
    def test_a_gate_is_not_offered_as_work(self):
        """Measured: an open gate is unblocked, unclaimed and high priority, so
        it sorts to the *front* of `bd ready`. Taken as work, the worker
        answers its own question and closes the gate it raised -- worse than
        guessing, because the tracker then records that somebody decided."""
        text = DRIVER.read_text()
        always = [line for line in text.splitlines()
                  if line.startswith('ALWAYS_SKIP_LABELS=')]
        assert always and 'human' in always[0]

    def test_the_operator_cannot_drop_the_gate_exclusion(self, tmp_path):
        """It is unioned in, not a default: a default is a thing an operator
        replaces, and replacing it with the two benchmark labels -- the
        plausible edit, since those are the two --help talks about -- put an
        open gate back at the front of the queue."""
        _path, command = sink(tmp_path)
        result = run([DRIVER, '--once', '--dry-run'],
                     env={'BGPERF_NOTIFY_CMD': command,
                          'BGPERF_UNATTENDED_BRANCH': current_branch(),
                          'BGPERF_UNATTENDED_SKIP_LABELS': 'plan:timing-64gb',
                          'BGPERF_BD_BIN': recording_bd(tmp_path)})
        recorded = (tmp_path / 'bd-args').read_text()
        assert '--exclude-label human' in ' '.join(recorded.split())

    def test_benchmarks_are_excluded_before_a_session_is_spent(self):
        text = DRIVER.read_text()
        skip = [line for line in text.splitlines()
                if line.startswith('SKIP_LABELS=')][0]
        assert 'plan:timing-64gb' in skip
        assert 'plan:2026-baseline' in skip

    def test_the_epics_themselves_are_never_offered(self):
        assert '--exclude-type=epic' in DRIVER.read_text()


class TestTheExitCodes:
    """`A loop that breaks only on a non-zero exit spins as fast as the model
    can decline; one that treats every non-zero exit as an empty queue sleeps
    through a crash.`"""

    def test_an_empty_queue_is_exactly_3(self, tmp_path):
        _path, command = sink(tmp_path)
        result = run([DRIVER, '--once', '--dry-run'],
                     env={'BGPERF_NOTIFY_CMD': command,
                          'BGPERF_UNATTENDED_BRANCH': current_branch(),
                          'BGPERF_BD_BIN': stub_bd(tmp_path, ready='[]')})
        assert result.returncode == 3, (result.stdout, result.stderr)
        assert 'nothing ready' in result.stdout

    def test_a_tracker_that_cannot_be_read_is_never_an_empty_queue(
            self, tmp_path, clean_checkout):
        """The mistake the whole exit-code scheme exists to avoid, and the
        first draft of the driver made it: `bd` failing produced no output,
        which read as an empty queue, and the loop slept half an hour a round
        forever -- 'sleeps through a crash', verbatim from its own header."""
        _path, command = sink(tmp_path)
        result = run([clean_checkout / 'scripts' / DRIVER.name, '--once'],
                     env={'BGPERF_NOTIFY_CMD': command,
                          'BGPERF_BD_BIN': stub_bd(tmp_path, status=7)})
        assert result.returncode == 1, (result.stdout, result.stderr)
        # `first_ready`'s message specifically -- not `open_gate_ids`', which
        # the earlier stub triggered first and which would let this pass with
        # the check under test deleted.
        assert 'the tracker could not be read (bd exited 7)' in result.stderr
        assert 'nothing ready' not in result.stdout

    def test_the_driver_computes_the_queue_rather_than_trusting_the_worker(self):
        """The plan's sketch had the worker signal an empty queue with exit 3.
        Computing it here removes the case where the model's exit code and the
        tracker disagree -- a worker that says 3 with items ready stalls the
        loop, one that exits 0 having done nothing spins it."""
        text = DRIVER.read_text()
        loop = text.split('while :; do', 1)[1]
        # The queue is read before the worker is started, in the loop.
        assert loop.index('first_ready') < loop.index('run_worker')

    def test_nothing_ready_sleeps_rather_than_exiting_when_looping(self):
        """Exiting is what makes an unattended worker need a human to restart
        it, which is the thing being removed."""
        text = DRIVER.read_text()
        loop = text.split('while :; do', 1)[1]
        # To `continue`, not to the first `fi`: the branch has a nested `if`
        # for --once, so splitting on `fi` stops inside it and the slice ends
        # before the sleep it is looking for.
        empty = loop.split('if [[ -z "$item" ]]; then', 1)[1]
        empty = empty.split('continue', 1)[0]
        assert 'sleep' in empty
        # And the sleep is what happens when the loop continues, while --once
        # gets the distinct empty-queue status instead.
        assert 'exit 3' in empty


class TestTheGateNotification:
    def test_a_new_gate_is_found_by_id_not_by_count(self):
        """Counting misses a new gate whenever an old one closes in the same
        window -- and an operator answering an earlier gate while a worker runs
        is the *expected* steady state here, so open-one close-one nets to zero
        and the new gate is never sent. That is the gate nobody sees."""
        text = DRIVER.read_text()
        assert 'comm -13' in text, 'the sets are compared, not the counts'
        assert '-gt "$gates_before"' not in text

    def test_a_failed_notification_stops_the_loop(self):
        """A warning goes to a terminal nobody is reading, which is the
        premise of the script; the loop would run on accumulating unseen
        gates."""
        text = DRIVER.read_text()
        notify = text.split('gate(s) opened, a decision is needed', 1)[1]
        # To the end of the failure branch, not to the first `fi`: the branch
        # now records the undelivered ids before dying, and the comment saying
        # why contains one.
        assert 'die "a gate was opened and the notification failed' in notify

    def test_a_gate_whose_notification_failed_is_still_owed(self):
        """On the next start `gates_before` already holds it, so the id diff
        can never report it again -- under a systemd Restart= the driver comes
        back, works the remaining items, and that gate is never mentioned by
        any means."""
        text = DRIVER.read_text()
        assert 'unattended-undelivered-gates' in text
        assert 'resend_undelivered' in text
        # Sent before the loop, and the marker cleared only on delivery.
        assert text.index('resend_undelivered()') < text.index('while :; do')

    def test_the_driver_notices_the_gate_not_the_worker(self):
        """A model that forgets to notify produces exactly the failure the rule
        is about, and produces it silently. Counting the gates before and after
        cannot be forgotten."""
        text = DRIVER.read_text()
        assert 'gates_before' in text and 'gates_after' in text
        loop = text.split('while :; do', 1)[1]
        assert loop.index('gates_before') < loop.index('run_worker')
        assert loop.index('run_worker') < loop.index('gates_after')

    def test_a_failed_notification_is_said_out_loud(self):
        text = DRIVER.read_text()
        assert 'a gate was opened and the notification failed' in text


class TestTheOperatorsMistakesAreNotReportedAsCrashes:
    def test_a_non_numeric_max_is_refused_by_name(self, tmp_path):
        _path, command = sink(tmp_path)
        result = run([DRIVER, '--max', 'abc'],
                     env={'BGPERF_NOTIFY_CMD': command})
        assert 'needs a whole number' in result.stderr

    def test_a_missing_max_value_is_refused_by_name(self, tmp_path):
        _path, command = sink(tmp_path)
        result = run([DRIVER, '--max'], env={'BGPERF_NOTIFY_CMD': command})
        assert 'needs a whole number' in result.stderr
        assert 'unbound variable' not in result.stderr


class TestTheQueueAdvances:
    def test_the_item_is_claimed_so_it_is_not_handed_back_forever(self):
        """`bd ready` excludes in_progress, so claiming is what makes the queue
        move. Without it a worker that exits 0 without closing its item leaves
        it open and unblocked, and the next round hands back the identical id,
        unattended, forever."""
        assert '--claim' in DRIVER.read_text()

    def test_a_dry_run_claims_nothing(self):
        text = DRIVER.read_text()
        loop = text.split('while :; do', 1)[1]
        assert 'first_ready peek' in loop

    def test_an_idle_night_does_not_count_against_max(self):
        """`--max N` reads as N items; ten sleeps are not ten completed
        items."""
        text = DRIVER.read_text()
        loop = text.split('while :; do', 1)[1]
        empty = loop.split('if [[ -z "$item" ]]; then', 1)[1].split('continue', 1)[0]
        assert 'worked=' not in empty

    def test_the_worker_is_bounded_by_a_timeout_that_cannot_be_ignored(self):
        """A stalled session hangs a loop nobody is watching and looks exactly
        like a long item -- and plain `timeout` sends SIGTERM then waits
        forever for a child that ignores it, which is the same hang."""
        text = DRIVER.read_text()
        assert 'timeout -k 60 "$WORKER_TIMEOUT"' in text

    def test_a_claimed_item_is_released_unless_the_worker_closed_it(self):
        """`bd ready` excludes in_progress by stored status, so an item left
        claimed never reappears -- not when its gate is answered, not when a
        human restarts the loop. It leaves the queue for good while the driver
        reports nothing ready."""
        text = DRIVER.read_text()
        assert 'release_item' in text
        loop = text.split('while :; do', 1)[1]
        # Released before either exit path below it.
        assert loop.index('release_item') < loop.index('worker exited $status')

    def test_exiting_zero_without_advancing_the_item_stops_the_loop(self):
        """Releasing alone reintroduces the spin the claim was added to
        prevent, reached from the other side.

        Tested on the item, not on a gate count: a worker that creates a gate
        and fails the `bd dep add` gates nothing, and counting gates reads that
        as explained -- the item comes back unblocked and the notification
        makes the round look normal while the loop spins."""
        text = DRIVER.read_text()
        assert 'left $item ready and unchanged' in text
        assert 'item_is_ready_again' in text
        loop = text.split('while :; do', 1)[1]
        assert 'new_gates' not in loop.split('item_is_ready_again', 1)[0][-400:]


class TestTheWorkerPrompt:
    """The prompt is the whole of the discipline for a session nobody reads."""

    def test_it_requires_review_before_commit(self):
        # Whitespace-normalised: the prompt is prose and wraps, so a literal
        # match against a sentence is a test that fails on a reflow.
        text = ' '.join(PROMPT.read_text().split())
        assert '/code-review' in text
        assert 'Review until a round comes back clean' in text

    def test_it_forbids_pushing_and_master(self):
        text = PROMPT.read_text().lower()
        assert 'never push' in text
        assert 'master' in text

    def test_it_forbids_starting_a_benchmark(self):
        text = PROMPT.read_text()
        assert 'Do not run a benchmark' in text

    def test_it_tells_the_worker_to_gate_rather_than_guess(self):
        text = PROMPT.read_text()
        assert '--labels=human' in text
        assert 'bd dep add {{ITEM}}' in text
        assert 'Do not choose' in text

    def test_it_forbids_closing_an_unfinished_item(self):
        """The next session believes a closed item, so this is the one mistake
        that is not recoverable from the tracker."""
        assert 'Do not close an item you did not finish' in PROMPT.read_text()


class TestTheClaimEndsWhenTheWorkerDoes:
    """Round five's finding, and the fourth round to find this same class.

    The release sat after the gate block, so the two `die`s in between -- the
    gate read failing, and the gate *send* failing, which the header
    explicitly plans for -- left the item claimed. `bd ready` excludes
    `in_progress` by stored status, so when the operator answered that gate the
    item never came back.
    """

    def test_the_release_precedes_everything_that_can_die_after_the_worker(self):
        text = DRIVER.read_text()
        after = text.split('run_worker "$item" || status=$?', 1)[1]
        release = after.index('release_item "$item"')
        # Every post-worker exit is after the release.
        for later in ('open_gate_ids', 'notify_gate.sh',
                      'left changes in the tree'):
            assert release < after.index(later), later


class TestRunningInTheRightPlace:
    def test_the_worker_starts_in_the_repository(self):
        """A systemd unit with no WorkingDirectory leaves cwd at `/`, and a
        worker started there resolves CLAUDE.md, the .claude hooks and its own
        pytest invocation against the wrong directory -- the whole discipline
        the prompt consists of silently not in force."""
        text = DRIVER.read_text()
        assert 'cd "$REPO_ROOT" && timeout' in text

    def test_the_prompt_names_no_checkout_literally(self):
        """Same defect as the hardcoded branch, one round later: a run from a
        second checkout told the worker to commit in a different repository
        from the one the guards watch."""
        text = PROMPT.read_text()
        assert '/data/bgperf2' not in text
        assert '{{REPO}}' in text


class TestTheGateDiffCannotFailQuietly:
    def test_comm_runs_under_a_fixed_collation_and_is_checked(self):
        """`open_gate_ids` sorts in Python codepoint order; GNU comm compares
        under LC_COLLATE. Disagreeing, comm errors -- and swallowed, that read
        as 'no new gates'."""
        text = DRIVER.read_text()
        assert 'LC_ALL=C comm' in text
        assert 'could not compare the gate sets' in text


class TestMarkersAreNotCommittable:
    """At the repo root a marker is an untracked file the driver's own
    dirty-tree guard blames the next worker for -- and a `git add -A` landing
    while it exists makes it tracked, the accident the results*.tgz rules were
    added for.

    The first version of this test asserted the *definitions* only, so it
    pinned the relative-path bug in place and never touched the write site --
    which had been left at the repo root under a different name entirely, so
    the marker was written where nothing reads it. 46 tests passed over both.
    """

    def test_the_marker_is_written_where_it_is_read(self):
        text = DRIVER.read_text()
        write = [l for l in text.splitlines()
                 if '> "$UNDELIVERED"' in l or 'unattended-undelivered' in l]
        # No write to any path other than the variable the reader uses.
        assert not [l for l in write if 'REPO_ROOT/.unattended' in l], write
        assert any('> "$UNDELIVERED"' in l for l in write)

    def test_both_markers_resolve_absolutely(self):
        """`rev-parse --git-dir` prints `.git`, relative to the repo -- and the
        driver deliberately never cd's, so under systemd both markers resolved
        to `/.git/...`, where the append fails and the guard that reads them
        sees no file and returns clean."""
        text = DRIVER.read_text()
        for marker in ('UNDELIVERED=', 'FAILED_ITEMS='):
            line = [l for l in text.splitlines() if l.startswith(marker)][0]
            assert 'rev-parse --absolute-git-dir' in line, marker

    def test_the_marker_path_is_outside_the_worktree(self, tmp_path):
        """Resolved for real against this checkout, not asserted as a
        string."""
        got = subprocess.run(
            ['git', '-C', str(REPO_ROOT), 'rev-parse', '--absolute-git-dir'],
            capture_output=True, text=True, cwd='/tmp').stdout.strip()
        assert got.startswith('/'), got
        assert '/.git' in got


class TestTheDirtyTreeGuardHasABaseline:
    def test_it_compares_against_the_tree_before_the_worker(self):
        """Absolute, any pre-existing untracked file stopped the driver on the
        *next* item naming the wrong culprit -- measured with a stub worker
        that touched nothing, blamed for this branch's own staged changes."""
        text = DRIVER.read_text()
        assert 'tree_before=' in text and 'tree_after=' in text
        loop = text.split('while :; do', 1)[1]
        assert loop.index('tree_before=') < loop.index('run_worker')

    def test_a_dirty_start_is_refused_at_startup(self):
        """The only place it can be said honestly: mid-loop the driver cannot
        tell the operator's edit from the worker's."""
        text = DRIVER.read_text()
        assert 'the tree is not clean' in text
        assert text.index('the tree is not clean') < text.index('while :; do')


class TestAPoisonedItemDoesNotLoopHot:
    def test_a_repeatedly_failing_item_stops_the_driver(self):
        """Under the systemd Restart= the header assumes, a deterministically
        failing item is claimed, fails, is released and re-offered forever with
        no notification and no record. This is the spend-limit failure recorded
        as bgperf2-cqi."""
        text = DRIVER.read_text()
        assert 'note_failed_item' in text
        assert 'refuse_a_repeatedly_failing_item' in text
        loop = text.split('while :; do', 1)[1]
        assert loop.index('refuse_a_repeatedly_failing_item') < loop.index('run_worker')

    def test_the_operator_is_told_before_the_loop_stops(self):
        text = DRIVER.read_text()
        refuse = text.split('refuse_a_repeatedly_failing_item() {', 1)[1]
        assert 'notify_gate.sh' in refuse.split('\n}', 1)[0]

    def test_the_refusal_releases_the_item_first(self):
        """It ran after the claim, so refusing left the item in_progress --
        and the item the operator was being asked to deal with was the one
        they could no longer see."""
        text = DRIVER.read_text()
        refuse = text.split('refuse_a_repeatedly_failing_item() {', 1)[1]
        body = refuse.split('\n}', 1)[0]
        # Comments out first: one of them contains the words "die messages",
        # which the split below would otherwise treat as an exit with no
        # release before it.
        body = '\n'.join(l for l in body.splitlines()
                         if not l.strip().startswith('#'))
        # Every `die` is preceded by a release, not just the first: the early
        # "already reported" exit is a `die` too, and it was added after this
        # test was written.
        for chunk in body.split('die ')[:-1]:
            assert 'release_item' in chunk, chunk[-200:]

    def test_a_failure_is_recorded_before_anything_that_can_die(self):
        """It sat at the bottom, past six exits, so a worker that failed *and*
        tripped any of them wrote no record and the restart came straight back
        onto the same item."""
        text = DRIVER.read_text()
        after = text.split('run_worker "$item" || status=$?', 1)[1]
        assert after.index('note_failed_item') < after.index('open_gate_ids')

    def test_a_completed_item_clears_its_record(self):
        """Otherwise the count is lifetime, and an item that failed once, was
        fixed, and failed once again months later is refused at two."""
        assert 'clear_failed_item' in DRIVER.read_text()


class TestTheChannelIsBounded:
    def test_the_notify_command_cannot_hang_forever(self):
        """The documented curl example carries no --max-time; against a
        black-holed host it hangs the startup check, and worse hangs the
        post-worker gate send while a worker's changes sit uncommitted."""
        assert 'timeout -k 10 "$NOTIFY_TIMEOUT"' in NOTIFIER.read_text()

    def test_a_hanging_channel_is_cut_off(self, tmp_path):
        result = run([NOTIFIER, '--check'],
                     env={'BGPERF_NOTIFY_CMD': 'sleep 30',
                          'BGPERF_NOTIFY_TIMEOUT': '2'})
        assert result.returncode != 0


class TestTheUndeliveredMarkerRoundTrip:
    """The test the plan claimed existed and did not.

    Round six's note said "it now writes a marker and asserts the round trip".
    The round trip had been verified by hand in a shell, and the tests only
    grepped the script source -- which is the same failure the note two
    paragraphs above it records: a claim that a thing is fixed is not the thing
    being fixed. Written now, and it drives the driver rather than reading it.
    """

    def a_tracker(self, tmp_path, gate_after_claim=True):
        """A `bd` whose gate list grows once an item has been claimed."""
        flag = tmp_path / 'claimed'
        path = tmp_path / 'gating-bd'
        path.write_text(
            '#!/usr/bin/env bash\n'
            'k=""\n'
            'for a in "$@"; do\n'
            '  [[ "$a" == ready ]] && k=ready\n'
            '  [[ "$a" == list ]] && k=list\n'
            '  [[ "$a" == show ]] && k=show\n'
            '  [[ "$a" == update ]] && k=update\n'
            'done\n'
            'case "$k" in\n'
            '  ready) if [[ -f {flag} ]]; then printf %s "[]"; '
            'else touch {flag}; printf %s \'[{{"id":"item-1"}}]\'; fi ;;\n'
            '  list)  if [[ -f {flag} ]]; then printf %s \'[{{"id":"g-new"}}]\'; '
            'else printf %s "[]"; fi ;;\n'
            '  show)  printf %s \'{{"status":"open"}}\' ;;\n'
            'esac\n'
            'exit 0\n'.format(flag=flag))
        path.chmod(0o755)
        return str(path)

    def a_worker(self, tmp_path):
        """A `claude` that does nothing and succeeds."""
        binder = tmp_path / 'bin'
        binder.mkdir(exist_ok=True)
        fake = binder / 'claude'
        fake.write_text('#!/usr/bin/env bash\nexit 0\n')
        fake.chmod(0o755)
        return str(binder)

    def test_a_failed_gate_send_is_recorded_and_re_sent_next_start(
            self, tmp_path, clean_checkout):
        driver = clean_checkout / 'scripts' / DRIVER.name
        git_dir = clean_checkout / '.git'
        # A channel that passes the startup check and fails the gate message.
        channel = tmp_path / 'flaky'
        channel.write_text('#!/usr/bin/env bash\n'
                           'grep -q "notification check" && exit 0\n'
                           'exit 1\n')
        channel.chmod(0o755)
        env = {'BGPERF_NOTIFY_CMD': str(channel),
               'BGPERF_BD_BIN': self.a_tracker(tmp_path),
               'PATH': self.a_worker(tmp_path) + ':' + os.environ['PATH']}

        first = run([driver, '--once'], env=env)
        assert first.returncode == 1
        assert 'notification failed' in first.stderr

        marker = git_dir / 'unattended-undelivered-gates'
        # Under .git, where the reader looks -- not the worktree, where it
        # would be untracked and trip the driver's own dirty-tree guard.
        assert marker.is_file(), sorted(p.name for p in git_dir.iterdir())
        assert 'g-new' in marker.read_text()
        assert not list(clean_checkout.glob('.unattended-*'))
        assert run(['git', '-C', str(clean_checkout), 'status',
                    '--porcelain']).stdout.strip() == ''

        # Next start, working channel: the owed gate is re-sent and cleared.
        delivered = tmp_path / 'delivered.log'
        env['BGPERF_NOTIFY_CMD'] = 'cat >> {0}'.format(delivered)
        second = run([driver, '--once'], env=env)
        assert 'never delivered' in delivered.read_text()
        assert 'g-new' in delivered.read_text()
        assert not marker.exists(), second.stderr


class TestAClosedItemIsNeverReopened:
    def test_the_release_needs_an_observed_in_progress(self):
        """`bd update --status open` on a *closed* issue reopens it, so
        releasing on "cannot tell" put finished, committed work back in the
        queue -- and the spin guard then died claiming the worker had left it
        unchanged, which was false."""
        text = DRIVER.read_text()
        after = text.split('run_worker "$item" || status=$?', 1)[1]
        branch = after.split('item_still_in_progress "$item"', 1)[1][:400]
        assert '-eq 0 ]]' in branch, branch
        assert '-ne 1 ]]' not in branch


class TestAClaimNeverOutlivesTheDriver:
    def test_a_signal_releases_the_held_item(self):
        """The header assumes a systemd Restart=, and the campaign host is a
        spot instance reclaimed without warning -- so the window between the
        claim and the release is the one most likely to be hit."""
        text = DRIVER.read_text()
        assert 'trap on_signal TERM INT' in text
        assert 'CURRENT_ITEM' in text

    def test_a_failed_claim_parse_reconciles(self):
        """`bd ready --claim` mutates state inside bd and the parse after it
        can still fail, with no way to name the item that was claimed."""
        text = DRIVER.read_text()
        loop = text.split('while :; do', 1)[1]
        claim = loop.split('first_ready claim', 1)[1][:400]
        assert 'release_stranded_items' in claim

    def test_reconciliation_asks_the_tracker_rather_than_guessing(self):
        text = DRIVER.read_text()
        body = text.split('release_stranded_items() {', 1)[1].split('\n}', 1)[0]
        assert '--status=in_progress' in body


class TestADryRunTouchesNothing:
    def test_the_poisoned_item_refusal_is_skipped(self, tmp_path,
                                                  clean_checkout):
        """It pages the operator *and* calls release_item, a tracker write --
        against a --help that promises "claim nothing, start no worker"."""
        text = DRIVER.read_text()
        loop = text.split('while :; do', 1)[1]
        refuse = loop.index('refuse_a_repeatedly_failing_item "$item"')
        guard = loop.index('if [[ $DRY_RUN -eq 0 ]]; then')
        assert guard < refuse

    def test_a_dry_run_with_a_real_item_still_pages_nobody(self, tmp_path,
                                                           clean_checkout):
        """The earlier version of this passed vacuously: its stub returned an
        empty queue, so no item ever reached the refusal."""
        path, command = sink(tmp_path)
        driver = clean_checkout / 'scripts' / DRIVER.name
        run([driver, '--dry-run'],
            env={'BGPERF_NOTIFY_CMD': command,
                 'BGPERF_BD_BIN': stub_bd(tmp_path,
                                          ready='[{"id":"item-1"}]')})
        assert not path.exists() or path.read_text() == ''


class TestTheWorkerCanDoWhatThePromptRequires:
    """`acceptEdits` auto-approves Edit and Write only.

    A Bash call outside the project allowlist still needs a permission
    decision, and in `-p` there is nobody to give one. The allowlist in
    `.claude/settings.json` carries pytest and three read-only bgperf2.py
    subcommands -- no git, no bd -- so the prompt's definition of done was
    unreachable and no item could ever be completed. Never seen, because the
    one recorded run died on the spend limit first.
    """

    def worker_tools(self):
        # To the closing paren on its own line: every entry contains a `)` of
        # its own (`Bash(git add *)`), so splitting on the first one truncated
        # the list to nothing and the assertions below were reading an empty
        # string.
        text = DRIVER.read_text()
        allowed = text.split('WORKER_ALLOWED_TOOLS=(', 1)[1].split('\n)', 1)[0]
        denied = text.split('WORKER_DENIED_TOOLS=(', 1)[1].split('\n)', 1)[0]
        return allowed, denied

    def test_everything_the_definition_of_done_needs_is_allowed(self):
        allowed, _ = self.worker_tools()
        for needed in ('git add', 'git commit', 'bd ', 'pytest', 'Edit',
                       'Write', 'Skill'):
            assert needed in allowed, needed

    def test_the_allowlist_is_passed_to_the_worker(self):
        text = DRIVER.read_text()
        assert '--allowedTools "${WORKER_ALLOWED_TOOLS[@]}"' in text
        assert '--disallowedTools "${WORKER_DENIED_TOOLS[@]}"' in text

    def test_pushing_and_docker_are_denied_not_merely_absent(self):
        """An omission is undone by anyone widening the allow list later; a
        denial is not. These two would take an unattended mistake off this
        machine, or onto the host for hours."""
        allowed, denied = self.worker_tools()
        assert 'git push' in denied
        assert 'docker' in denied
        assert 'push' not in allowed

    def test_the_prompts_own_commands_are_covered(self):
        """Whatever the prompt tells the worker to run, the driver must allow
        -- otherwise the instruction is one the worker cannot follow."""
        allowed, _ = self.worker_tools()
        prompt = PROMPT.read_text()
        # The asserted expression has to depend on the loop variable. It did
        # not: `assert 'bd ' in allowed` is loop-invariant, so the test passed
        # for any set of commands the prompt might name -- including ones the
        # allowlist does not cover.
        commands = re.findall(r'`(bd [a-z]+)', prompt)
        assert commands, 'the prompt names no bd commands; has it changed?'
        entries = [e.strip().strip('"') for e in allowed.split('\n') if e.strip()]
        for command in commands:
            covered = any(
                entry.startswith('Bash(') and
                command.startswith(entry[len('Bash('):].rstrip(')*').rstrip())
                for entry in entries)
            assert covered, '{0!r} is not covered by {1}'.format(command,
                                                                 entries)


class TestTheTrapIsAsCarefulAsTheReleaseSite:
    def test_it_does_not_reopen_a_closed_item(self):
        """CURRENT_ITEM stays set through the gate read, the gate send, the
        comm and the tree check -- all after a successful worker has closed its
        item -- so an unconditional release reopened committed work on exactly
        the signal the header calls most likely."""
        text = DRIVER.read_text()
        body = text.split('on_signal() {', 1)[1].split('\n}', 1)[0]
        assert 'item_still_in_progress' in body


class TestReconciliationIsScopedAndRunsAtStartup:
    def test_it_only_releases_this_drivers_own_claims(self):
        """Unscoped it reopened every in-progress item in the tracker,
        including one a human had claimed interactively -- which the next
        --claim would hand to an unattended worker."""
        text = DRIVER.read_text()
        body = text.split('release_stranded_items() {', 1)[1].split('\n}', 1)[0]
        assert '--assignee' in body

    def test_it_runs_at_startup_for_a_predecessor_that_was_killed(self):
        """A kill rather than a signal never runs the trap, and nothing else
        would ever release that item."""
        text = DRIVER.read_text()
        startup = text.split('while :; do', 1)[0]
        assert 'release_stranded_items' in startup


class TestEveryWayAnItemFailsIsRecorded:
    def test_exiting_zero_without_advancing_counts_as_a_failure(self):
        """The item is released and the tree is clean, so every startup guard
        passes and the restart claims the same item -- a session a cycle with
        nothing recorded. A model that declines the work is the likelier way
        here than a crash, and only crashes were counted."""
        text = DRIVER.read_text()
        spin = text.split('ready and unchanged', 1)[0][-600:]
        assert 'note_failed_item' in spin

    def test_a_poisoned_item_is_announced_once_not_once_per_restart(self):
        """Under Restart=always with RestartSec=100ms that is a page every
        tenth of a second, on the channel the gate alert uses."""
        text = DRIVER.read_text()
        assert 'FAILED_ITEMS.announced' in text
        body = text.split('refuse_a_repeatedly_failing_item() {', 1)[1]
        assert 'already reported' in body.split('\n}', 1)[0]


class TestTheDriverClaimsUnderItsOwnIdentity:
    """`bd` records an assignee as the *actor* -- git `user.name`, not
    `user.email` -- so filtering reconciliation by the email matched nothing
    and `release_stranded_items` was a permanent no-op. Measured against the
    real tracker: assignee is 'bgperf2-unattended' under BEADS_ACTOR and
    'Justin Pietsch' without it.

    And a distinct name rather than the correct one, because the human's name
    would not tell this driver's claims from that person's interactive ones --
    so startup reconciliation would reopen an item they had in flight.
    """

    def test_every_tracker_call_carries_the_actor(self):
        text = DRIVER.read_text()
        body = text.split('bd_cmd() {', 1)[1].split('}', 1)[0]
        assert 'BEADS_ACTOR=' in body

    def test_reconciliation_filters_on_that_same_actor(self):
        text = DRIVER.read_text()
        body = text.split('release_stranded_items() {', 1)[1].split('\n}', 1)[0]
        assert '--assignee "$UNATTENDED_ACTOR"' in body
        assert 'user.email' not in body

    def test_the_actor_is_not_a_git_identity(self):
        text = DRIVER.read_text()
        line = [l for l in text.splitlines()
                if l.startswith('UNATTENDED_ACTOR=')][0]
        assert 'git config' not in line


class TestTheAllowlistIsActuallyABoundary:
    def test_arbitrary_python_is_not_auto_approved(self):
        """A prefix-matched `-c` auto-approves arbitrary code, so a worker
        could reach `git push` or `docker` through a one-liner and the deny
        rules would never see the command -- the tool input is the python."""
        text = DRIVER.read_text()
        allowed = text.split('WORKER_ALLOWED_TOOLS=(', 1)[1].split('\n)', 1)[0]
        assert 'python -c' not in allowed
        assert 'python -m pytest' in allowed


class TestCouldNotTellIsAlwaysTheThirdOutcome:
    def test_any_unexpected_status_is_clamped(self):
        """The function returns the *pipeline's* status, so an orphaned
        `venv/bin/python` gives 127 -- which matched neither branch at the call
        site: no release, no reconcile, nothing printed, claim stranded."""
        text = DRIVER.read_text()
        body = text.split('item_still_in_progress() {', 1)[1].split('\n}', 1)[0]
        assert '-eq 1 ]] && return 1' in body
        assert body.rstrip().endswith('return 2')


class TestAnAnnouncementDoesNotSilenceTheNextFailure:
    def test_the_marker_is_cleared_when_the_count_drops(self):
        """An operator who clears $FAILED_ITEMS as instructed would otherwise
        leave a stale entry, and the next real failure would release and die
        having told nobody."""
        text = DRIVER.read_text()
        body = text.split('refuse_a_repeatedly_failing_item() {', 1)[1]
        body = body.split('\n}', 1)[0]
        assert 'clear_announced_item' in body
        assert body.index('clear_announced_item') < body.index('grep -q -x -F')


class TestTheAnnouncementClearActuallyRuns:
    """Round nine's fix was dead code and round ten found it.

    `[[ "$count" -lt 2 ]] && return 0` sat above the clear, so the clear was
    unreachable for every value that could reach it -- and the test grepped
    source positions rather than running the function, so 76 tests passed over
    the regression it was written against. This runs it.
    """

    def refusal(self, tmp_path, failed_lines, announced_lines):
        """Call `refuse_a_repeatedly_failing_item` in isolation."""
        git_dir = tmp_path / 'gitdir'
        git_dir.mkdir()
        (git_dir / 'unattended-failed-items').write_text(failed_lines)
        (git_dir / 'unattended-failed-items.announced').write_text(
            announced_lines)
        harness = tmp_path / 'call.sh'
        harness.write_text(
            'set -euo pipefail\n'
            'FAILED_ITEMS={d}/unattended-failed-items\n'
            'clear_announced_item() {{\n'
            '  grep -v -x -F "$1" "$FAILED_ITEMS.announced" '
            '> "$FAILED_ITEMS.announced.tmp" 2>/dev/null || true\n'
            '  mv "$FAILED_ITEMS.announced.tmp" "$FAILED_ITEMS.announced"\n'
            '}}\n'
            'release_item() {{ :; }}\n'
            'die() {{ echo "$*" >&2; exit 1; }}\n'
            '{body}\n'
            'refuse_a_repeatedly_failing_item "item-1" || true\n'.format(
                d=git_dir,
                body=DRIVER.read_text().split(
                    'refuse_a_repeatedly_failing_item() {', 1)[1]
                    .split('\n}', 1)[0]
                    .join(['refuse_a_repeatedly_failing_item() {', '\n}'])))
        run(['bash', str(harness)], env={'BGPERF_NOTIFY_CMD': 'cat >/dev/null'})
        return (git_dir / 'unattended-failed-items.announced').read_text()

    def test_a_cleared_failure_record_clears_the_announcement(self, tmp_path):
        """The operator clears $FAILED_ITEMS as instructed; the stale marker
        must not then silence the next real page."""
        left = self.refusal(tmp_path, failed_lines='',
                            announced_lines='item-1\n')
        assert 'item-1' not in left, left

    def test_an_item_still_at_the_threshold_keeps_its_announcement(self,
                                                                   tmp_path):
        left = self.refusal(tmp_path, failed_lines='item-1\nitem-1\n',
                            announced_lines='item-1\n')
        assert 'item-1' in left, left


class TestTheStartupCheckIsRateLimited:
    def test_a_second_start_inside_the_interval_does_not_page(self, tmp_path,
                                                              clean_checkout):
        """`check_notification` sends through the channel, so an unconditional
        startup send is one page per process start -- under Restart=always with
        RestartSec=100ms, about ten a second, carrying nothing about the
        failure."""
        path, command = sink(tmp_path)
        driver = clean_checkout / 'scripts' / DRIVER.name
        env = {'BGPERF_NOTIFY_CMD': command,
               'BGPERF_BD_BIN': stub_bd(tmp_path)}
        run([driver, '--once'], env=env)
        first = path.read_text().count('notification check')
        run([driver, '--once'], env=env)
        run([driver, '--once'], env=env)
        assert path.read_text().count('notification check') == first == 1

    def test_the_interval_is_overridable_and_re_checks_after_it(
            self, tmp_path, clean_checkout):
        path, command = sink(tmp_path)
        driver = clean_checkout / 'scripts' / DRIVER.name
        env = {'BGPERF_NOTIFY_CMD': command,
               'BGPERF_BD_BIN': stub_bd(tmp_path),
               'BGPERF_NOTIFY_CHECK_INTERVAL': '0'}
        run([driver, '--once'], env=env)
        run([driver, '--once'], env=env)
        assert path.read_text().count('notification check') == 2


class TestOnlyOneDriverPerCheckout:
    def test_a_second_driver_is_refused(self, tmp_path, clean_checkout):
        """`release_stranded_items` at startup reopens every in-flight claim of
        this actor, so a second driver reopens the first's item, claims it, and
        two sessions edit the same work."""
        driver = clean_checkout / 'scripts' / DRIVER.name
        _path, command = sink(tmp_path)
        lock = clean_checkout / '.git' / 'unattended.lock'
        lock.touch()
        # Hold the lock the way the driver does, then start a second one.
        holder = subprocess.Popen(
            ['flock', '-x', str(lock), 'sleep', '5'])
        try:
            result = run([driver, '--once'],
                         env={'BGPERF_NOTIFY_CMD': command,
                              'BGPERF_BD_BIN': stub_bd(tmp_path)})
            assert result.returncode != 0
            assert 'already running' in result.stderr
        finally:
            holder.kill()
            holder.wait()


class TestThePermissionRulesArePrefixMatches:
    """Bash permission rules are prefix matches, not globs.

    Every rule in this repo's own `.claude/settings.json` uses a trailing `*`
    and nothing else. The `Bash(git -C * commit *)` entries this list carried
    matched nothing, so the worker -- which CLAUDE.md and the prompt both push
    toward `git -C` -- could not commit at all: round eight's defect in a
    second form.
    """

    def entries(self, name):
        # By regex, not by line: the denied entries share a line, and a
        # line-based parser glued two rules into one string whose `*` was then
        # mid-word. The test failed on its own parsing, not on the rules.
        text = DRIVER.read_text()
        raw = text.split(name + '=(', 1)[1].split('\n)', 1)[0]
        raw = '\n'.join(l for l in raw.splitlines()
                        if not l.strip().startswith('#'))
        return re.findall(r'Bash\([^)]*\)', raw)

    def test_no_rule_has_a_wildcard_anywhere_but_the_end(self):
        for name in ('WORKER_ALLOWED_TOOLS', 'WORKER_DENIED_TOOLS'):
            found = self.entries(name)
            assert found, name
            for entry in found:
                if '*' not in entry:
                    continue
                inner = entry[entry.index('(') + 1:entry.rindex(')')]
                assert inner.index('*') == len(inner) - 1, (name, entry)

    def test_the_c_form_is_absent_rather_than_allowed(self):
        """`Bash(git -C *)` would match, and would also permit `git -C <dir>
        push`, which no prefix rule can then deny. Left out entirely, any
        `git -C` needs a decision nobody can give, so it is denied."""
        for entry in self.entries('WORKER_ALLOWED_TOOLS'):
            assert 'git -C' not in entry, entry

    def test_the_prompt_tells_the_worker_to_use_plain_git(self):
        """Its cwd is the repository root, and CLAUDE.md's rule prohibits `cd`,
        not git in a directory one is already in."""
        text = PROMPT.read_text()
        assert 'Use plain `git`' in text
        assert 'never `cd`' in text


class TestTheChannelIsCheckedEvenInsideTheRateLimitWindow:
    def test_a_missing_channel_is_refused_however_recently_it_was_probed(
            self, tmp_path, clean_checkout):
        """Skipping both halves let a hand-run --once from a shell with no
        export start, claim an item, and spend a whole worker session with no
        channel at all."""
        path, command = sink(tmp_path)
        driver = clean_checkout / 'scripts' / DRIVER.name
        # Probe once so the rate-limit window is open.
        run([driver, '--once'], env={'BGPERF_NOTIFY_CMD': command,
                                     'BGPERF_BD_BIN': stub_bd(tmp_path)})
        # Now start with no channel configured at all.
        result = run([driver, '--once'],
                     env={'BGPERF_BD_BIN': stub_bd(tmp_path)})
        assert result.returncode != 0
        assert 'gate nobody sees' in result.stderr


class TestNoExitClaimsAReleaseThatDidNotHappen:
    def test_a_failed_reconcile_says_the_claim_may_still_be_held(self):
        """The only way to reach that caller is `bd` being unhealthy, which is
        exactly when the reconcile's own read fails too -- so swallowing it
        told the operator the claim was clean while it sat in_progress."""
        text = DRIVER.read_text()
        body = text.split('release_stranded_items() {', 1)[1].split('\n}', 1)[0]
        assert '-ne 0 ]] && return 1' in body
        assert 'may still be held' in text


class TestTheWedgedPageIsNotMarkedBeforeItIsSent:
    def test_the_marker_follows_a_successful_send(self):
        text = DRIVER.read_text()
        block = text.split('the unattended driver is stopped on a dirty tree',
                           1)[1][:600]
        assert 'touch "$wedged"' in block
        assert block.index('touch "$wedged"') < block.index('else')
        assert '$UNDELIVERED' in block
