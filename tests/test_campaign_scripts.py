'''The campaign runners' guards, which decide where a multi-hour block writes.

These scripts had no coverage at all, and they are now what drives a twelve
block campaign: the workdir guard is the only thing between a full-table MRT
block and the 29 GB root filesystem, and the two-marker rule is the only thing
between a session that died before its review and one that reviewed.

Every test here is Docker-free: each exercises a refusal or a listing that
happens before the first container. That is a property of the scripts, not of
the tests -- a Docker call ahead of an argument guard is the failure
`test_image_resolves_before_containers_are_torn_down` exists for, one level up.
'''
import os
import re
import subprocess

import pytest

from conftest import REPO_ROOT

BLOCK_RUNNER = REPO_ROOT / 'scripts' / 'run_timing_validation_block.sh'
SUITE_RUNNER = REPO_ROOT / 'scripts' / 'run_2026_suite.sh'
COMMON = REPO_ROOT / 'scripts' / 'lib' / 'campaign_common.sh'


def run(args, **kwargs):
    return subprocess.run([str(a) for a in args], cwd=str(REPO_ROOT),
                          capture_output=True, text=True, timeout=120,
                          **kwargs)


def block(*args, results_root, workdir=None, runner=None):
    argv = [runner or BLOCK_RUNNER, *args, '--results-root', results_root]
    if workdir is not None:
        argv += ['--workdir', workdir, '--allow-root-workdir']
    return run(argv)


def _block_keys():
    listed = BLOCK_RUNNER.read_text().split('BLOCK_KEYS=(', 1)[1].split(')', 1)[0]
    return [line.strip() for line in listed.split() if line.strip()]


def _built_blocks():
    """Which block numbers the runner has a `case` branch for.

    Discovered rather than written down, because a guard test that names an
    unbuilt block by number becomes a *benchmark launcher* the moment that
    block is built. That is not hypothetical: when block 1 landed, this
    suite -- whose whole point is that it needs no Docker -- spent two minutes
    running a real MRT calibration into a temp directory, and would have gone
    on doing it on every developer's machine.
    """
    cases = BLOCK_RUNNER.read_text().split('case "$BLOCK_INDEX" in', 1)[1]
    return sorted(int(n) for n in re.findall(r'^  (\d+)\)\s*$', cases, re.M))


def _held_blocks():
    """Which blocks the runner refuses to run without an explicit override.

    Discovered from the script for the reason `_built_blocks` is: a test that
    named block 5 would silently stop testing anything the day block 5 is
    released, and would be testing the wrong block the day another is held.
    """
    table = BLOCK_RUNNER.read_text().split('declare -A BLOCK_HELD=(', 1)
    if len(table) < 2:
        return set()
    return set(int(n) for n in re.findall(r'^\s*\[(\d+)\]=', table[1].split('\n)', 1)[0], re.M))


@pytest.fixture
def unbuilt(tmp_path):
    """A copy of the runner with its last block unbuilt, and that block's number.

    Every test that drives the runner all the way to its `case` needs a block
    that will not really run even if the guard it is testing regresses. For
    most of this campaign the unbuilt blocks supplied one for free; they no
    longer can, because Block 12 is the last block there is and the campaign
    has now built all of them, at which point the old helper asserted and took
    seven tests with it.

    So the block is made rather than found, the way `held_runner` already
    makes one: remove the highest `case` branch from a copy. The index is
    still discovered from the script and never written down, so it moves on
    its own as blocks land -- which is the property that matters, and the
    reason this is not simply a literal. A literal here becomes a *benchmark
    launcher* the day that block is built: these tests hand the runner
    `--workdir` and `--allow-root-workdir`, so a 14-cell full-table MRT batch
    would start inside the Docker-free suite before the `returncode == 2`
    assertion ever ran.

    The copy has to sit in `scripts/`: the runner resolves `SCRIPT_DIR` from
    `BASH_SOURCE` and sources `lib/campaign_common.sh` relative to it. Unique
    per process, because under pytest-xdist a fixed name means two workers
    write and unlink the same path and one can execute a half-written file.
    """
    index = _built_blocks()[-1]
    key = _block_keys()[index]
    source = BLOCK_RUNNER
    target = source.parent / '.test_unbuilt_runner_{0}.sh'.format(os.getpid())
    text = source.read_text()
    branch = re.compile(r'^  %d\)\n.*?^    ;;\n' % index, re.M | re.S)
    text, removed = branch.subn('', text, count=1)
    assert removed == 1, 'could not unbuild block %d in the copy' % index
    target.write_text(text)
    target.chmod(source.stat().st_mode)
    try:
        yield str(target), index, key
    finally:
        target.unlink(missing_ok=True)


@pytest.fixture
def roots(tmp_path):
    results = tmp_path / 'results'
    work = tmp_path / 'work'
    results.mkdir()
    work.mkdir()
    return str(results), str(work)


def test_every_script_is_syntactically_valid():
    for script in (BLOCK_RUNNER, SUITE_RUNNER, COMMON,
                   REPO_ROOT / 'scripts' / 'preflight_2026_suite.sh',
                   REPO_ROOT / 'scripts' / 'prepare_mrt.sh',
                   REPO_ROOT / 'scripts' / 'calibration_case.sh'):
        result = run(['bash', '-n', script])
        assert result.returncode == 0, (script.name, result.stderr)


def test_the_block_order_is_the_plans_order():
    '''The key is a directory name under the run root: reordering or renaming
    one orphans whatever an earlier block already wrote there.'''
    result = run([BLOCK_RUNNER, 'list'])
    assert result.returncode == 0, result.stderr
    lines = [l for l in result.stdout.splitlines() if l.strip()]
    assert len(lines) == 13
    assert lines[0].split()[1] == 'block0-preflight-and-smoke'
    assert lines[1].split()[1] == 'block1-generator-calibration'
    assert lines[5].split()[1] == 'block5-mrt-rep1'
    assert lines[11].split()[1] == 'block11-peers-expansion'
    assert lines[12].split()[1] == 'block12-final-report'


def test_status_reports_every_block_before_anything_has_run(roots):
    """Every block accounts for itself before the first one runs.

    Counted as "has a pre-run state" rather than as twelve `not-started`,
    because a block can also be *held* -- built, reviewed, and waiting on a
    decision about what its results would mean. Hardcoding the one word made
    this test fail the moment a block was held, which is a state it has no
    opinion about.
    """
    results, _ = roots
    result = block('status', results_root=results)
    assert result.returncode == 0, result.stderr
    states = [line.split()[-1] for line in result.stdout.splitlines()
              if line.startswith('block-')]
    assert len(states) == len(_block_keys())
    # The exact partition, not just the vocabulary. Asserting only that every
    # state is one of the two words would pass a `block_state` whose held
    # lookup had degraded to something true of every block -- reporting the
    # whole campaign as held, which is the one reading that stops `next` dead.
    held = _held_blocks()
    expected = ['held' if i in held else 'not-started'
                for i in range(len(states))]
    assert states == expected, states


@pytest.fixture
def held_runner(tmp_path):
    """A copy of the runner with one block held, beside the real one.

    The mechanism is only exercised while some block is actually held, and
    blocks are held rarely and released as soon as the question that held them
    is settled -- Block 5 was held and released the same day. Tests that
    skipped whenever `BLOCK_HELD` was empty therefore covered it for a few
    hours and never again, which is no coverage at all for infrastructure the
    next held block depends on. Patching a copy tests the real guard against a
    real invocation.

    The copy has to sit in `scripts/`: the runner resolves `SCRIPT_DIR` from
    `BASH_SOURCE` and sources `lib/campaign_common.sh` relative to it.
    """
    # Unique per process: under pytest-xdist a fixed name means two workers
    # write and unlink the same path, so one can execute a half-written file.
    # A stray copy after a hard kill is also this test's mess to leave, and a
    # pid-tagged one is at least identifiable.
    source = BLOCK_RUNNER
    target = source.parent / '.test_held_runner_{0}.sh'.format(os.getpid())
    text = source.read_text()
    assert 'declare -A BLOCK_HELD=(' in text, 'the held-block table is gone'
    # Two blocks that cannot run, made by removing the two highest `case`
    # branches from the copy: these tests need one block that will not really
    # run even if the guard they are testing regresses, and one of them needs
    # *two* -- a held one and an unheld one.
    #
    # The campaign's own unbuilt blocks used to supply them for free. They
    # cannot any more, because Block 12 is the last block there is and all of
    # them are now built -- which is why the `unbuilt` fixture below makes its
    # block the same way. Unbuilding in a copy keeps both fixtures independent
    # of how much of the campaign has been written.
    #
    # The hazard neither of them softens: a literal number here becomes a
    # *benchmark launcher* the day that block is built. These tests hand the
    # runner `--workdir` and `--allow-root-workdir`, so a guard that regressed
    # would put a 14-cell full-table MRT batch inside the Docker-free suite
    # before the `returncode == 2` assertion ever ran. So the indices are
    # discovered from the script, never written down, and they move on their
    # own as blocks land.
    index, second = sorted(_built_blocks()[-2:], reverse=True)
    for number in (index, second):
        branch = re.compile(r'^  %d\)\n.*?^    ;;\n' % number, re.M | re.S)
        text, removed = branch.subn('', text, count=1)
        assert removed == 1, 'could not unbuild block %d in the copy' % number
    text = text.replace(
        'declare -A BLOCK_HELD=(',
        'declare -A BLOCK_HELD=(\n  [%d]="a reason the operator has to read"'
        % index,
        1)
    target.write_text(text)
    target.chmod(source.stat().st_mode)
    try:
        yield target, index, second
    finally:
        target.unlink(missing_ok=True)


def held_block(runner, *args, results_root, workdir=None):
    argv = [runner, *args, '--results-root', results_root]
    if workdir is not None:
        argv += ['--workdir', workdir, '--allow-root-workdir']
    return run(argv)


def test_a_held_block_is_refused_and_says_what_decision_it_is_waiting_on(
        held_runner, roots):
    """A held block is built and reviewed; what it lacks is a decision.

    It must not be reachable by `next`, because the campaign contract tells an
    unattended session to run the next block -- and the whole point of holding
    one is that its rows are already known not to mean what they appear to.
    """
    runner, index, unbuilt = held_runner
    results, work = roots
    result = held_block(runner, 'block-%d' % index, results_root=results,
                        workdir=work)
    assert result.returncode == 2, result.stdout
    assert 'built but held' in result.stderr
    # The refusal has to name the decision, not just refuse: an operator who
    # cannot see why will pass the override.
    assert 'a reason the operator has to read' in result.stderr
    assert '--run-held-block' in result.stderr
    assert not os.path.exists(os.path.join(
        results, '2026-timing-validation', _block_keys()[index]))


def test_next_does_not_select_a_held_block(held_runner, roots):
    runner, index, unbuilt = held_runner
    results, work = roots
    root = os.path.join(results, '2026-timing-validation')
    for key in _block_keys()[:index]:
        directory = os.path.join(root, key)
        os.makedirs(directory, exist_ok=True)
        with open(os.path.join(directory, 'COMPLETE'), 'w') as handle:
            handle.write('accepted\n')
    result = held_block(runner, 'next', results_root=results,
                        workdir=work)
    assert result.returncode == 2, result.stdout
    assert 'built but held' in result.stderr


def test_the_held_override_is_refused_by_an_action_that_runs_nothing(
        held_runner, roots):
    """`accept` is the slip that matters: a held block's refusal is about what
    its rows would mean, which is the judgement `accept` records."""
    runner, index, unbuilt = held_runner
    results, _ = roots
    for action in (['accept', str(index), '--note', 'why'], ['status'],
                   ['list']):
        result = held_block(runner, *action, '--run-held-block',
                            results_root=results)
        assert result.returncode == 1, (action, result.stdout)
        assert '--run-held-block applies to running a block' in result.stderr


def test_a_held_block_is_reported_as_held_rather_than_not_started(
        held_runner, roots):
    runner, index, unbuilt = held_runner
    results, _ = roots
    result = held_block(runner, 'status', results_root=results)
    assert result.returncode == 0, result.stderr
    line = [l for l in result.stdout.splitlines()
            if l.startswith('block-%d ' % index)]
    assert line and line[0].split()[-1] == 'held', result.stdout


def test_an_unknown_block_is_refused_by_name(roots):
    results, work = roots
    result = block('block-99', results_root=results, workdir=work)
    assert result.returncode != 0
    assert 'no such block' in result.stderr


def test_a_block_that_is_not_built_yet_says_so_rather_than_inventing_one(
        roots, unbuilt):
    '''A block that ran the wrong matrix produces rows that look exactly like
    the right ones.'''
    results, work = roots
    runner, index, _ = unbuilt
    result = block('block-%d' % index, results_root=results, workdir=work,
                   runner=runner)
    assert result.returncode == 2
    assert 'not built yet' in result.stderr


def test_an_unbuilt_blocks_refusal_leaves_no_directory_behind(roots, unbuilt):
    """`status` must not report a block nobody can run as interrupted work.

    The block directory is created for every invocation, well before the
    `case` that finds out whether this block has a procedure. Left behind,
    `block_state()` reads a bare directory as `started` -- which is the one
    state an unbuilt block is not, and it reads to the next session as work
    somebody stopped half way through. Removed only while empty, so nothing
    that holds results is ever touched by that path.
    """
    results, work = roots
    runner, index, key = unbuilt
    result = block('block-%d' % index, results_root=results, workdir=work,
                   runner=runner)
    assert result.returncode == 2
    assert not os.path.exists(
        os.path.join(results, '2026-timing-validation', key)), (
            'the refusal left a directory, so `status` now calls it started')
    listed = block('status', results_root=results, workdir=work)
    line = [row for row in listed.stdout.splitlines() if key in row]
    assert line and 'not-started' in line[0], listed.stdout


def test_a_block_that_measures_nothing_is_not_told_to_re_measure(roots):
    """The failure guidance has to be true of the block that produced it.

    A review block writes no `evidence/`, has no rows to exclude and has no
    progress file for a plain re-run to resume past -- so the shared failure
    message sent the operator to read a directory that is never created and to
    re-measure a block that measures nothing, while the real cause was printed
    far above it.

    Safe in a suite that needs no Docker because this is the one block that
    starts no container: it reads documents that earlier blocks published, and
    against a scratch results root it finds none of them and says so.
    """
    results, work = roots
    index = [n for n, key in enumerate(_block_keys())
             if 'variance-review' in key][0]
    result = block('block-%d' % index, results_root=results, workdir=work)
    assert result.returncode == 1
    assert 'This block measures nothing' in result.stderr
    assert 'evidence/' not in result.stderr, (
        'sent to read a directory this block never creates')
    assert 'resumes past every cell' not in result.stderr, (
        'a block with no progress file cannot resume past a cell')
    assert 'no selection document' in result.stdout, (
        'the real cause must still be reported')


def _review_block():
    """The block that measures nothing, discovered rather than named.

    Same reason the `unbuilt` fixture discovers its block: a test that hardcoded an
    index would be testing the wrong block the day the list changes.
    """
    keys = _block_keys()
    index = [n for n, key in enumerate(keys) if 'variance-review' in key][0]
    return index, keys[index]


def _a_block_that_ran_and_failed(results, key):
    run_root = os.path.join(results, '2026-timing-validation')
    os.makedirs(os.path.join(run_root, key), exist_ok=True)
    with open(os.path.join(run_root, key, 'RAN'), 'w') as marker:
        marker.write('block: %s\nevidence: 1 check(s) failed\n' % key)
    return run_root


def test_accept_does_not_send_a_review_block_to_a_checker_that_never_ran(roots):
    """A block with no rows has nothing to exclude and nothing to re-measure.

    `accept` refuses it either way -- there is no evidence to record a durable
    exclusion against -- but the refusal used to name a `$dir/evidence/`
    directory that is never created and tell the operator to "re-measure" a
    block that measures nothing.
    """
    results, _ = roots
    index, key = _review_block()
    _a_block_that_ran_and_failed(results, key)
    result = run([BLOCK_RUNNER, 'accept', str(index), '--note', 'x',
                  '--results-root', results])
    assert result.returncode == 1
    assert 'measures nothing' in result.stderr
    assert '/evidence/' not in result.stderr


def test_next_points_a_failed_review_block_at_its_review(roots):
    """The fourth path that has to know a block produces no rows.

    Every other block is marked complete first, from the runner's own key
    list, so the only candidate is the review block and `next` cannot reach a
    benchmark: it finds that block awaiting review and prints.
    """
    results, work = roots
    index, key = _review_block()
    run_root = _a_block_that_ran_and_failed(results, key)
    for other in _block_keys():
        if other == key:
            continue
        os.makedirs(os.path.join(run_root, other), exist_ok=True)
        with open(os.path.join(run_root, other, 'COMPLETE'), 'w') as marker:
            marker.write('accepted: fixture\n')
    result = block('next', results_root=results, workdir=work)
    assert result.returncode == 1
    assert 'Read its review under' in result.stderr
    assert 'discards no observation' in result.stderr
    assert 'with-exclusions' not in result.stderr


def test_next_selects_block_zero_first_then_advances_only_past_acceptance(roots):
    results, work = roots
    run_root = os.path.join(results, '2026-timing-validation')
    block0 = os.path.join(run_root, 'block0-preflight-and-smoke')
    block1 = os.path.join(run_root, 'block1-generator-calibration')
    os.makedirs(block0)
    os.makedirs(block1)

    # RAN alone is not acceptance: the review is what completes a block, and a
    # session that died between the batch and the review must not look like
    # one that reviewed it.
    open(os.path.join(block0, 'RAN'), 'w').close()
    result = block('next', results_root=results, workdir=work)
    assert result.returncode == 1
    assert 'waiting to be reviewed' in result.stderr

    result = block('accept', '0', '--note', 'reviewed', results_root=results)
    assert result.returncode == 0, result.stderr
    assert os.path.exists(os.path.join(block0, 'COMPLETE'))

    # Only now does `next` move on. It is stopped at block 1 by block 1's own
    # RAN marker rather than by block 1 being unbuilt: `next` runs whatever it
    # selects, so a test that proved advancement by letting it reach an
    # unbuilt block would start a real benchmark the day that block landed --
    # which is exactly what happened when this one did.
    open(os.path.join(block1, 'RAN'), 'w').close()
    result = block('next', results_root=results, workdir=work)
    assert result.returncode == 1
    assert 'block-1' in result.stderr
    assert 'waiting to be reviewed' in result.stderr


def test_accepting_a_block_that_never_ran_is_refused(roots):
    '''It would write the marker `next` advances past, and the campaign would
    skip the work believing it done.'''
    results, _ = roots
    result = block('accept', '0', results_root=results)
    assert result.returncode != 0
    assert 'has not run yet' in result.stderr


def test_a_ran_block_is_not_silently_rerun(roots):
    results, work = roots
    run_root = os.path.join(results, '2026-timing-validation')
    block0 = os.path.join(run_root, 'block0-preflight-and-smoke')
    os.makedirs(block0)
    open(os.path.join(block0, 'RAN'), 'w').close()
    result = block('block-0', results_root=results, workdir=work)
    assert result.returncode != 0
    assert 'waiting for review' in result.stderr


def test_the_acceptance_marker_records_who_accepted_what_and_when(roots):
    results, _ = roots
    run_root = os.path.join(results, '2026-timing-validation')
    block0 = os.path.join(run_root, 'block0-preflight-and-smoke')
    os.makedirs(block0)
    open(os.path.join(block0, 'RAN'), 'w').close()
    block('accept', '0', '--note', 'both smokes qualified',
          results_root=results)
    marker = open(os.path.join(block0, 'COMPLETE')).read()
    assert 'accepted_utc:' in marker
    assert 'revision:' in marker
    assert 'note: both smokes qualified' in marker


@pytest.mark.parametrize('runner', [BLOCK_RUNNER, SUITE_RUNNER])
def test_a_work_directory_on_the_root_filesystem_is_refused(runner, tmp_path):
    '''A --workdir naming the root filesystem is the same hazard as a
    defaulted one, and the more likely of the two now that every contract
    prints an explicit --workdir.

    The path is deliberately one that does not exist: the guard walks up to
    the nearest existing ancestor, which is `/` itself here whatever this
    host's mount layout is. Naming a real directory like /var/tmp would make
    this test pass or fail on how the machine was partitioned.'''
    results = tmp_path / 'results'
    results.mkdir()
    argv = [runner, 'block-0' if runner is BLOCK_RUNNER else 'smoke',
            '--results-root', str(results),
            '--workdir', '/nonexistent-bgperf-campaign-test/work']
    result = run(argv)
    assert result.returncode != 0
    assert 'on the root filesystem' in result.stderr


@pytest.mark.parametrize('runner', [BLOCK_RUNNER, SUITE_RUNNER])
def test_an_invalid_run_id_is_refused(runner, roots):
    results, work = roots
    result = run([runner, 'block-0' if runner is BLOCK_RUNNER else 'smoke',
                  '--run-id', '../escape', '--results-root', results,
                  '--workdir', work, '--allow-root-workdir'])
    assert result.returncode != 0
    assert 'invalid run ID' in result.stderr


def test_a_recorded_workdir_wins_over_the_one_invoked_with(roots, unbuilt):
    '''The campaign contract's rule: the recorded manifest wins and the
    discrepancy is a finding to report, not a path to silently switch.'''
    import json
    results, work = roots
    metadata = os.path.join(results, '2026-timing-validation', 'metadata')
    os.makedirs(metadata)
    with open(os.path.join(metadata, 'manifest.json'), 'w') as f:
        json.dump({'workdir': '/data/somewhere-else'}, f)

    runner, index, _ = unbuilt
    result = block('block-%d' % index, results_root=results, workdir=work,
                   runner=runner)
    assert result.returncode != 0
    assert 'recorded under workdir' in result.stderr


def test_the_manifest_writer_refuses_to_let_a_caller_redefine_its_spine(roots):
    '''MANIFEST_EXTRA_JSON carrying its own "workdir" would silently undo the
    refusal above.'''
    results, work = roots
    manifest = os.path.join(results, 'manifest.json')
    script = (
        'source scripts/lib/campaign_common.sh\n'
        'MANIFEST_EXTRA_JSON=\'{"workdir": "/elsewhere"}\' '
        'campaign_write_manifest venv/bin/python "%s" rid "%s" "%s" "%s"\n'
        % (manifest, results, work, results))
    result = run(['bash', '-c', script])
    assert result.returncode != 0
    assert 'may not redefine manifest keys' in result.stderr
    assert not os.path.exists(manifest)


def test_the_manifest_records_the_facts_a_block_was_run_with(roots):
    results, work = roots
    manifest = os.path.join(results, 'manifest.json')
    script = (
        'source scripts/lib/campaign_common.sh\n'
        'SUITE_TEXT=block0 MANIFEST_EXTRA_JSON=\'{"blocks": {"block0": {}}}\' '
        'campaign_write_manifest venv/bin/python "%s" rid "%s" "%s" "%s"\n'
        % (manifest, results, work, results))
    result = run(['bash', '-c', script])
    assert result.returncode == 0, result.stderr
    import json
    doc = json.load(open(manifest))
    assert doc['workdir'] == work
    assert doc['suites'] == ['block0']
    assert doc['blocks'] == {'block0': {}}


def test_a_second_block_can_record_its_facts_under_one_run_id(roots):
    '''The block runner records its facts under "blocks", pre-merging what
    earlier blocks recorded. Reserving keys against the merged manifest instead
    of against this library's own spine refused every invocation after the
    first -- aborting the second block of a run ID before its preflight.'''
    import json
    results, work = roots
    manifest = os.path.join(results, 'manifest.json')
    script = (
        'source scripts/lib/campaign_common.sh\n'
        'MANIFEST_EXTRA_JSON=\'{"blocks": {"block0": {"host": {}}}}\' '
        'campaign_write_manifest venv/bin/python "%(m)s" rid "%(r)s" "%(w)s" "%(r)s"\n'
        'MANIFEST_EXTRA_JSON=\'{"blocks": {"block0": {"host": {}}, "block1": {}}}\' '
        'campaign_write_manifest venv/bin/python "%(m)s" rid "%(r)s" "%(w)s" "%(r)s"\n'
        % {'m': manifest, 'r': results, 'w': work})
    result = run(['bash', '-c', script])
    assert result.returncode == 0, result.stderr
    doc = json.load(open(manifest))
    assert sorted(doc['blocks']) == ['block0', 'block1']


def test_a_zero_padded_block_number_is_read_in_base_ten(roots):
    '''`(( 010 ))` is octal in bash: `accept 010` accepted block 8.'''
    results, _ = roots
    run_root = os.path.join(results, '2026-timing-validation')
    block8 = os.path.join(run_root, 'block8-bird-architecture-screen')
    block0 = os.path.join(run_root, 'block0-preflight-and-smoke')
    os.makedirs(block8)
    os.makedirs(block0)
    open(os.path.join(block0, 'RAN'), 'w').close()

    result = block('accept', '010', results_root=results)
    assert result.returncode != 0
    assert not os.path.exists(os.path.join(block8, 'COMPLETE'))

    result = block('accept', '00', results_root=results)
    assert result.returncode == 0, result.stderr
    assert os.path.exists(os.path.join(block0, 'COMPLETE'))


def test_a_force_that_replaced_nothing_retracts_nothing(roots, unbuilt):
    '''The retraction belongs where results start being replaced, not beside
    the marker checks that let --force past them. An unbuilt block measures
    nothing -- and deleting the acceptance of results that are still there
    would leave `status` reporting a block nobody has to redo as one that must
    be redone.'''
    results, work = roots
    run_root = os.path.join(results, '2026-timing-validation')
    runner, index, key = unbuilt
    target = os.path.join(run_root, key)
    os.makedirs(target)
    open(os.path.join(target, 'RAN'), 'w').close()
    open(os.path.join(target, 'COMPLETE'), 'w').close()

    result = run([runner, 'block-%d' % index, '--force',
                  '--results-root', results,
                  '--workdir', work, '--allow-root-workdir'])
    assert result.returncode == 2
    assert os.path.exists(os.path.join(target, 'COMPLETE'))
    assert os.path.exists(os.path.join(target, 'RAN'))


def test_a_refused_force_does_not_retract_anything(roots, unbuilt):
    '''A forced run turned away by the workdir guard never replaced the
    results whose acceptance it would have retracted.'''
    results, _ = roots
    run_root = os.path.join(results, '2026-timing-validation')
    runner, index, key = unbuilt
    target = os.path.join(run_root, key)
    os.makedirs(target)
    open(os.path.join(target, 'COMPLETE'), 'w').close()

    result = run([runner, 'block-%d' % index, '--force',
                  '--results-root', results,
                  '--workdir', '/nonexistent-bgperf-campaign-test/work'])
    assert result.returncode != 0
    assert 'on the root filesystem' in result.stderr
    assert os.path.exists(os.path.join(target, 'COMPLETE'))


def _run_batch_body():
    body = open(BLOCK_RUNNER).read()
    return body[body.index('run_batch() {'):body.index('EVIDENCE_FAILURES=0')]


def test_a_forced_run_does_not_resume_past_the_cells_it_is_re_measuring():
    """`batch --resume` records every completed cell, so a forced re-run that
    kept --resume would skip all of them, exit 0 having measured nothing, and
    then stamp the old artifacts with the current revision."""
    assert 'FORCE -eq 1' in _run_batch_body()
    assert 'resume_args=()' in _run_batch_body()


def test_a_constrained_case_is_never_resumed():
    """The progress file says a cell completed and says nothing about whether
    the constraint bound -- the guard that decides that runs in the watcher,
    which cannot observe a cell it did not launch. Resuming one accepts a case
    as controlled on a marker that is silent about control."""
    assert 'FORCE -eq 1 || $# -gt 0' in _run_batch_body()


def test_a_failed_case_puts_its_own_log_on_the_terminal():
    """Everything a constrained run has to say goes to a redirected log, so
    failing on the bare exit status would abort the block with nothing
    printed -- including the one message the design turns on, that a container
    of this run went unconstrained."""
    body = _run_batch_body()
    assert '|| status=$?' in body
    assert 'tail -20 "$LOG_DIR/$key.stderr.log" >&2' in body
    # and the case log is kept on the failing path, which is the path whose
    # record matters most
    assert body.index('cp "$LOG_DIR/$key.stderr.log" "$out_dir/case.log"') \
        < body.index('return "$status"')


def test_one_failed_evidence_check_does_not_cost_the_block_its_other_evidence():
    """Under `set -euo pipefail` a checker exiting non-zero would abort the
    script where it stands, so the second smoke's verdict would never be
    written -- half the block's record lost to the first failure."""
    body = open(BLOCK_RUNNER).read()
    assert 'EVIDENCE_FAILURES=$((EVIDENCE_FAILURES + 1))' in body
    assert 'if [[ $EVIDENCE_FAILURES -gt 0 ]]; then' in body


def test_ran_marker_records_that_the_work_ran_whatever_the_verdict():
    """RAN says the block's mechanical work finished, and carries the evidence
    verdict beside it rather than being withheld by it.

    Written only on the passing path, a single rejected row made the block
    unrecoverable in two ways at once: `accept` refuses a block with no RAN, and
    `next` -- seeing a directory but no marker -- re-selected the block and ran
    it with `--resume`, which skips every cell the progress file already holds,
    failed ones included. The block re-ran, measured nothing, exited 0 and
    failed the identical check.

    This asserts the ordering the old test meant to: the marker is written
    before the branch that exits non-zero, not after it. Anchored on the failure
    *message* rather than on `if [[ $EVIDENCE_FAILURES -gt 0 ]]`, which now also
    appears inside the marker's own heredoc -- the old assertion matched that
    copy and passed vacuously through exactly this change."""
    body = open(BLOCK_RUNNER).read()
    ran_written = body.index('> "$BLOCK_DIR/RAN"')
    failure_branch = body.index('did not meet its exit criterion')
    assert ran_written < failure_branch
    # and it says which of the two happened, either way
    assert 'echo "evidence: $EVIDENCE_FAILURES check(s) failed"' in body
    assert 'echo "evidence: all checks qualified"' in body


def test_a_rejected_row_may_only_be_accepted_as_an_explicit_exclusion():
    """The plan's exit criterion is "14 reviewed rows *or* explicit durable
    exclusions with evidence", and the second half has to be written down or it
    is not durable. A block whose evidence rejected a row is accepted only with
    --with-exclusions and a note, and the marker names the rows."""
    body = open(BLOCK_RUNNER).read()
    assert '--with-exclusions) WITH_EXCLUSIONS=1' in body
    assert 'accepted_with_exclusions:' in body
    # a reason is required: an exclusion with none is a row dropped
    assert 'if [[ -z "$NOTE" ]]; then' in body
    # and the flag is refused on a clean block rather than quietly ignored
    assert 'has no rejected rows; --with-exclusions does not apply' in body


def test_rejected_rows_and_runs_that_never_happened_are_named_apart():
    """The campaign keeps a result to investigate apart from unfinished work at
    every level of aggregation, and this is the level an operator acts on.

    A count of failed `check_evidence` *calls* cannot do it: Blocks 2-7 make one
    call covering 14 runs, so that count is 1 whether one row was rejected or
    fourteen -- and `check_timing_evidence.py` also exits non-zero on a
    shortfall, so a block that produced 9 artifacts for 14 configurations
    reached `accept` under identical wording. Only a rejected row may be
    excluded; a missing run leaves the block unfinished."""
    body = open(BLOCK_RUNNER).read()
    assert 'block_exclusion_report() {' in body
    assert 'print("excluded_row: " + line)' in body
    assert 'print("missing_runs: " + line)' in body
    # the helper is defined above the dispatch that calls it, or `accept` would
    # die on "command not found"
    assert body.index('block_exclusion_report() {') < body.index(
        'if [[ "$ACTION" == "accept" ]]; then')


def test_metadata_files_with_no_manifest_equivalent_are_keyed_per_block():
    """`METADATA_DIR` is shared by every block of a run. A file whose content is
    also merged into `manifest.json` under `blocks.<key>` may be overwritten;
    one whose content exists nowhere else may not, or a later block destroys an
    accepted block's evidence.

    `campaign_host_facts.py` records memory and swap *totals* and nothing about
    disk, so free memory, used swap and free space have no manifest equivalent
    -- and comparing swap across blocks is what the 64 GB Safety Contract's
    "stop the active block after ... swap growth" is read from."""
    body = open(BLOCK_RUNNER).read()
    for stem in ('preflight', 'verify', 'mrt-validation', 'free-h', 'df-h'):
        assert '"$METADATA_DIR/{0}.txt"'.format(stem) not in body, stem
        assert '"$METADATA_DIR/{0}-$BLOCK_KEY.txt"'.format(stem) in body, stem


def test_a_forced_run_discards_the_artifacts_it_is_replacing():
    """`--force` drops `--resume`, which makes `batch()` unlink the progress
    file, but nothing removed the previous run's `.events.json`. A forced re-run
    under an edited matrix left one artifact per dropped target beside the new
    ones, and `check_evidence` -- which counts the artifacts it finds -- reported
    a permanent shortfall against a block that measured exactly what it was
    asked to."""
    body = _run_batch_body()
    assert 'if [[ $FORCE -eq 1 && -d "$out_dir" ]]; then' in body
    assert 'rm -rf "${out_dir:?}"' in body


def _ran_block(results_root, key, evidence=None, failed=True):
    """A block on disk that has run, with the verdicts a checker would leave."""
    import json
    import os
    directory = os.path.join(results_root, 'tvtest', key)
    os.makedirs(os.path.join(directory, 'evidence'), exist_ok=True)
    line = ('evidence: 1 check(s) failed' if failed
            else 'evidence: all checks qualified')
    with open(os.path.join(directory, 'RAN'), 'w') as f:
        f.write('block: {0}\n{1}\n'.format(key, line))
    if evidence is not None:
        with open(os.path.join(directory, 'evidence', 'synthetic.json'),
                  'w') as f:
            json.dump(evidence, f)
    return directory


REJECTED_ROW = {'expected_runs': 14, 'shortfall': None,
                'runs': [{'run': 'openbgp 8.8', 'verdict': 'rejected'},
                         {'run': 'bird 2.19.2', 'verdict': 'qualified'}]}
SHORTFALL = {'expected_runs': 14, 'shortfall': '9 runs found, 14 expected',
             'runs': [{'run': 'bird 2.19.2', 'verdict': 'qualified'}]}


def test_a_run_that_never_happened_cannot_be_accepted_as_an_exclusion(tmp_path):
    """The gate is on the parsed verdicts, not on the wording of a message.

    Reporting a rejected row and a missing run apart is not the same as
    *treating* them apart, and the first version got exactly that wrong:
    `--with-exclusions` proceeded on any non-zero failure count, so a block
    whose only fault was "9 runs found, 14 expected" was stamped COMPLETE and
    `next` advanced past five configurations nobody measured."""
    root = str(tmp_path)
    directory = _ran_block(root, 'block2-synthetic-rep1', SHORTFALL)
    result = block('accept', '2', '--run-id', 'tvtest', '--with-exclusions',
                   '--note', 'why', results_root=root)
    assert result.returncode == 1, result.stdout
    assert 'unfinished' in result.stderr
    assert not os.path.exists(os.path.join(directory, 'COMPLETE'))


def test_a_shortfall_beside_a_rejected_row_is_still_unfinished(tmp_path):
    """Unfinished wins over excludable. A block missing a configuration is not
    made acceptable by also having a row worth excluding."""
    both = {'expected_runs': 14, 'shortfall': '13 runs found, 14 expected',
            'runs': [{'run': 'frr_c 9.1', 'verdict': 'rejected'}]}
    root = str(tmp_path)
    directory = _ran_block(root, 'block2-synthetic-rep1', both)
    result = block('accept', '2', '--run-id', 'tvtest', '--with-exclusions',
                   '--note', 'why', results_root=root)
    assert result.returncode == 1, result.stdout
    assert not os.path.exists(os.path.join(directory, 'COMPLETE'))


def test_failing_checks_with_no_readable_verdict_cannot_be_excluded(tmp_path):
    """"Explicit durable exclusions *with evidence*" cannot be satisfied by a
    record with none. A checker that died leaves failing checks and no verdict,
    and accepting there writes an exclusion naming an evidence path that holds
    nothing."""
    root = str(tmp_path)
    directory = _ran_block(root, 'block2-synthetic-rep1', None)
    result = block('accept', '2', '--run-id', 'tvtest', '--with-exclusions',
                   '--note', 'why', results_root=root)
    assert result.returncode == 1, result.stdout
    assert 'no readable verdicts' in result.stderr
    assert not os.path.exists(os.path.join(directory, 'COMPLETE'))


def test_a_rejected_row_is_accepted_and_the_marker_names_it(tmp_path):
    """The path the campaign actually needs: every configuration produced a row,
    one of them did not qualify, and it is recorded as an exclusion by name."""
    root = str(tmp_path)
    directory = _ran_block(root, 'block2-synthetic-rep1', REJECTED_ROW)
    result = block('accept', '2', '--run-id', 'tvtest', '--with-exclusions',
                   '--note', 'openbgp 8.8 hit the guardrail', results_root=root)
    assert result.returncode == 0, result.stderr
    marker = open(os.path.join(directory, 'COMPLETE')).read()
    assert 'accepted_with_exclusions: 1 rejected row(s), 0 shortfall(s)' in marker
    assert 'excluded_row: synthetic: openbgp 8.8 (rejected)' in marker
    assert 'note: openbgp 8.8 hit the guardrail' in marker


def test_a_rejected_row_needs_the_flag_and_a_reason(tmp_path):
    root = str(tmp_path)
    directory = _ran_block(root, 'block2-synthetic-rep1', REJECTED_ROW)
    bare = block('accept', '2', '--run-id', 'tvtest', results_root=root)
    assert bare.returncode == 1
    assert 'openbgp 8.8' in bare.stderr
    assert not os.path.exists(os.path.join(directory, 'COMPLETE'))

    unreasoned = block('accept', '2', '--run-id', 'tvtest',
                       '--with-exclusions', results_root=root)
    assert unreasoned.returncode == 1
    assert 'requires --note' in unreasoned.stderr
    assert not os.path.exists(os.path.join(directory, 'COMPLETE'))


def test_accept_only_flags_are_refused_rather_than_ignored_elsewhere(tmp_path):
    """The `next` refusal prints an `accept N --with-exclusions --note` line to
    copy, so leaving the action as `next` is the natural slip -- and ignoring
    the flags there launches a multi-hour benchmark instead of refusing."""
    root = str(tmp_path)
    for action in ('next', 'block-2'):
        result = block(action, '--run-id', 'tvtest', '--with-exclusions',
                       '--note', 'oops', results_root=root)
        assert result.returncode == 1, (action, result.stdout)
        assert 'applies to `accept`' in result.stderr, action
        # and nothing was started
        assert not os.path.exists(os.path.join(root, 'tvtest',
                                               'block2-synthetic-rep1'))


def test_an_unreadable_verdict_is_not_an_excludable_row(tmp_path):
    """`unreadable` means the checker could not parse that run's artifact at
    all, so its checks are empty and nothing was judged. That is a row with no
    evidence, not a row that failed a rule -- and "explicit durable exclusions
    *with evidence*" cannot be satisfied by one."""
    root = str(tmp_path)
    unreadable = {'expected_runs': 14, 'shortfall': None,
                  'runs': [{'run': 'bird 2.19.2', 'verdict': 'unreadable'},
                           {'run': 'frr_c 8.5', 'verdict': 'qualified'}]}
    directory = _ran_block(root, 'block2-synthetic-rep1', unreadable)
    result = block('accept', '2', '--run-id', 'tvtest', '--with-exclusions',
                   '--note', 'why', results_root=root)
    assert result.returncode == 1, result.stdout
    assert 'unfinished' in result.stderr
    assert 'evidence unreadable' in result.stderr
    assert not os.path.exists(os.path.join(directory, 'COMPLETE'))


def test_the_held_override_accepts_every_spelling_of_a_block(held_runner,
                                                             roots):
    """`parse_block_number()` takes `5`, `block5` and `block-5`, and `accept`
    takes its number bare -- so the bare form is the natural thing to type
    here. A guard that whitelisted `next` and `block-*` refused it with
    "applies to running a block, not to `5`", which is false.

    Safe to exercise because the held block is the lowest *unbuilt* one: past
    the override it reaches the "not built yet" branch and exits, rather than
    starting a benchmark.
    """
    runner, index, unbuilt = held_runner
    results, work = roots
    for spelling in (str(index), 'block%d' % index, 'block-%d' % index):
        result = held_block(runner, spelling, '--run-held-block',
                            results_root=results, workdir=work)
        assert 'applies to running a block' not in result.stderr, spelling
        assert 'not built yet' in result.stderr, (spelling, result.stderr)


def test_the_held_override_is_refused_on_a_block_that_is_not_held(held_runner,
                                                                  roots):
    """Same rule as the action guard: a flag that quietly does nothing is read
    next time as one that did something. The slip that matters is a mistyped
    block number while overriding a held one, which would otherwise start a
    full unmarked run of a different block.

    The block chosen must be one that could not run even if the guard failed --
    an *unbuilt* one, which exits 2 at the "not built yet" branch. Reaching for
    `index - 1` here launched the real held block 5, because the patched copy
    carries the repository's own BLOCK_HELD entries as well as the injected
    one. The refusal is checked by its message, not merely by a non-zero exit,
    so that shortcut cannot be taken again.

    Those entries are excluded through `_held_blocks()` rather than by picking
    an unbuilt block and trusting the two sets not to overlap. They only do not
    overlap today because the one held block happens to be built; a block that
    was held before its configs were written would land first in `candidates`,
    take the override path, and exit 2 at "not built yet" -- failing this
    assertion for a reason that has nothing to do with what it tests.
    """
    runner, index, unbuilt = held_runner
    results, work = roots
    # The copy's second unrunnable block, not the repository's. Block 11 is
    # the last block of the campaign, so from Block 10 onward there are not two
    # unbuilt indices to be had -- the fixture unbuilds two in its copy and
    # hands both back, and they are discovered from the script rather than
    # named here for the same reason the `unbuilt` fixture discovers its: a literal
    # would become a benchmark launcher the day the arrangement changed.
    held = _held_blocks()
    assert unbuilt not in held and unbuilt != index, (
        'the unbuilt candidate must be neither held nor the held block')
    other = unbuilt
    result = held_block(runner, 'block-%d' % other, '--run-held-block',
                        results_root=results, workdir=work)
    assert result.returncode == 1, result.stdout
    assert 'is not held, so --run-held-block overrides nothing' in result.stderr
    assert not os.path.exists(os.path.join(
        results, '2026-timing-validation', _block_keys()[other]))


def _reclaimed_block(results_root, key, evidence=SHORTFALL):
    """A block the host was taken away from mid-run.

    The marker carries the stop *and* the shortfall it explains, because that
    is what the runner writes: a block stopped at a cell boundary always has
    configurations that produced no row.
    """
    import os
    directory = _ran_block(results_root, key, evidence)
    path = os.path.join(directory, 'RAN')
    body = open(path).read()
    with open(path, 'w') as f:
        f.write(body.replace(
            'evidence: ',
            'stopped: host reclaimed -- EC2 spot interruption notice: '
            'terminate at 2026-09-14T05:40:43Z\nevidence: '))
    return directory


def test_a_reclaimed_block_is_reported_as_interrupted_not_awaiting_review(
        tmp_path):
    """`awaiting-review` would be a lie about what the block is waiting for:
    there is nothing to review yet, only cells still to measure."""
    root = str(tmp_path)
    _reclaimed_block(root, 'block2-synthetic-rep1')
    result = block('status', '--run-id', 'tvtest', results_root=root)
    assert result.returncode == 0, result.stderr
    line = [l for l in result.stdout.splitlines() if 'block2' in l][0]
    assert line.endswith('interrupted'), line


def test_a_reclaimed_block_is_pointed_at_the_resume_not_at_a_re_measure(
        tmp_path):
    """The whole cost of the old behaviour: `unfinished` sends an operator to
    --force, which discards every cell the boundary stop preserved."""
    root = str(tmp_path)
    # Block 0, because `next` selects the first block with no COMPLETE and a
    # `next` that reached an earlier one would *run* it -- this suite needs no
    # Docker, and a test that launches a smoke benchmark is the failure
    # the `unbuilt` fixture exists for.
    _reclaimed_block(root, 'block0-preflight-and-smoke')
    result = block('next', '--run-id', 'tvtest', results_root=root,
                   workdir=str(tmp_path / 'work'))
    assert result.returncode != 0
    assert '--resume-after-stop' in result.stderr
    assert '--force' not in result.stderr.split('--resume-after-stop')[0]


def test_a_reclaimed_block_cannot_be_accepted(tmp_path):
    """It is unfinished work however it stopped: accepting it would stamp
    COMPLETE over configurations nobody measured."""
    root = str(tmp_path)
    directory = _reclaimed_block(root, 'block2-synthetic-rep1')
    result = block('accept', '2', '--run-id', 'tvtest', '--with-exclusions',
                   '--note', 'the host went away', results_root=root)
    assert result.returncode != 0
    assert 'host reclaim' in result.stderr
    assert '--resume-after-stop' in result.stderr
    import os
    assert not os.path.exists(os.path.join(directory, 'COMPLETE'))


def test_a_resume_is_refused_for_a_block_that_was_not_reclaimed(tmp_path):
    """The marker is the authority, never the operator's recollection. A resume
    over an ordinary failure would skip every cell in the progress file, the
    failed ones included, and stamp those rows with a fresh revision."""
    root = str(tmp_path)
    _ran_block(root, 'block2-synthetic-rep1', SHORTFALL)
    result = block('block-2', '--run-id', 'tvtest', '--resume-after-stop',
                   results_root=root)
    assert result.returncode != 0
    assert 'did not stop at a cell boundary' in result.stderr


def test_a_resume_of_a_block_that_never_ran_is_refused(roots, unbuilt):
    """There is no interrupted run to continue, and the plain form is what
    starts one."""
    results, work = roots
    runner, index, _ = unbuilt
    result = block('block-%d' % index, '--resume-after-stop',
                   results_root=results, workdir=work, runner=runner)
    assert result.returncode != 0
    assert 'nothing to continue' in result.stderr


def test_force_and_resume_are_refused_together(roots, unbuilt):
    """One discards this block's measured cells and the other keeps them.
    Whichever won silently, the operator would learn which by reading the
    results afterwards -- and one of the two answers destroys them."""
    results, work = roots
    runner, index, _ = unbuilt
    result = block('block-%d' % index, '--force', '--resume-after-stop',
                   results_root=results, workdir=work, runner=runner)
    assert result.returncode != 0
    assert 'opposites' in result.stderr


def test_the_resume_flag_is_refused_by_an_action_that_runs_nothing(tmp_path):
    """A flag that quietly does nothing is read next time as one that did
    something -- and `accept` is the slip that matters, because the refusal an
    interrupted block gets prints the resume command to copy."""
    root = str(tmp_path)
    _reclaimed_block(root, 'block2-synthetic-rep1')
    result = block('accept', '2', '--run-id', 'tvtest',
                   '--resume-after-stop', results_root=root)
    assert result.returncode != 0
    assert 'applies to running a block' in result.stderr


def test_a_resume_retracts_nothing_and_a_force_retracts_the_claims():
    """A resume deletes neither marker nor verdict; only --force does.

    Every non-143 exit aborts the block under `set -e` before a new marker is
    written. Deleted up front, a resume that then failed for an ordinary reason
    would leave no record of the stop at all -- the next resume refused for a
    block whose marker records none, and only --force left, discarding exactly
    the cells the recovery path was built to keep. Deleting the verdicts costs
    the detail printed under that standing stop line, on every later
    invocation. Deleting results would make the flag a slower --force outright.
    """
    body = BLOCK_RUNNER.read_text()
    retract = body.split('retract_block_markers() {', 1)[1].split('\n}', 1)[0]
    deletes = retract.split('if [[ $FORCE -eq 1 ]]; then', 1)[1]
    assert 'rm -f "$BLOCK_DIR/COMPLETE" "$BLOCK_DIR/RAN"' in deletes
    assert 'rm -rf "$BLOCK_DIR/evidence"' in deletes
    assert 'RESUME_STOP' not in retract, (
        'a resume must retract nothing: it has no marker of its own yet')
    assert 'progress' not in retract
    force_only = body.split('if [[ $FORCE -eq 1 && -d "$out_dir" ]]; then', 1)
    assert len(force_only) == 2, 'the results delete is no longer force-only'


def test_the_force_branch_reports_its_own_failures():
    """`set -e` no longer runs inside `run_batch`: every call site collects its
    status now. The delete and the manifest prune were relying on the shell to
    abort the block, and a prune that failed silently leaves the state its own
    guard exists to prevent -- results gone, manifest still naming them."""
    body = BLOCK_RUNNER.read_text()
    fn = body.split('run_batch() {', 1)[1].split('\n}\n', 1)[0]
    branch = fn.split('if [[ $FORCE -eq 1 && -d "$out_dir" ]]; then', 1)[1]
    branch = branch.split('mkdir -p "$out_dir"', 1)[0]
    assert branch.count('exit 1') >= 3, branch
    assert 'rm -rf "${out_dir:?}" || {' in branch
    assert '--prune-under "$prune_under" || {' in branch


def test_a_stop_is_recorded_with_the_reason_the_run_gave():
    """bgperf2 asks for the same orderly stop on any SIGTERM, so `stopped:
    SIGTERM` reaches this path as readily as a spot interruption notice.
    Writing "host reclaimed" over it would put a fabricated account of the
    machine into the campaign's durable record."""
    body = BLOCK_RUNNER.read_text()
    assert 'echo "stopped: $STOP_REASON"' in body
    assert 'stopped: host reclaimed' not in body, (
        'the marker line may not assert a cause the run did not report')


def test_a_held_block_is_told_the_resume_that_would_work():
    """`guard_held_block` runs after the resume gate, so the bare form is
    refused for a held block. `next` used to avoid this for free -- a block
    with a RAN never reached that guard."""
    body = BLOCK_RUNNER.read_text()
    fn = body.split('resume_command() {', 1)[1].split('\n}', 1)[0]
    assert 'BLOCK_HELD[$index]' in fn
    assert '--run-held-block' in fn
    # Every printed resume command goes through the helper. `block-N` is the
    # placeholder in the flag-misuse message, which is about the flag rather
    # than about any block, and is the one exception.
    printed = [l for l in body.splitlines()
               if '--resume-after-stop' in l
               and 'run_timing_validation_block.sh' in l
               and 'block-N' not in l]
    assert not printed, printed


def test_a_pass_that_never_started_is_not_reported_as_one_that_failed():
    """After a stop, every later `run_batch` returns without starting. Saying
    "the remaining passes still run" of those is the opposite of what happened,
    and counting each skip turned the failure count into a number that tracked
    where in the matrix the stop landed."""
    body = BLOCK_RUNNER.read_text()
    loops = [seg for seg in body.split('|| batch_status=$?')[1:]
             if seg.lstrip().startswith('if [[ $batch_status -ne 0 ]]; then')]
    # Every such loop, however many blocks have one -- a count written down
    # here is a number that has to be edited each time a block lands, and the
    # edit that silences it is indistinguishable from the one that hides a
    # loop which stopped following the rule. Two is the floor: blocks 8 and 10
    # both have one and neither is going away.
    assert len(loops) >= 2, len(loops)
    for seg in loops:
        head = seg.split('\n    check_evidence', 1)[0]
        assert 'if [[ $STOPPED -eq 1 ]]; then' in head
        counted = head.split('if [[ $STOPPED -eq 1 ]]; then', 1)[1]
        # The skip branch ends at the first `elif` or `else` at that
        # indentation, not at the first `else` anywhere: a block that tells
        # its *last* pass apart from the rest has an `elif` between them, and
        # splitting on `else` put that branch inside the skip and read its
        # counting as the skip's.
        boundary = re.search(r'^      (?:elif |else$)', counted, re.M)
        assert boundary, counted
        skip, failed = counted[:boundary.start()], counted[boundary.start():]
        assert 'EVIDENCE_FAILURES' not in skip, skip
        assert 'EVIDENCE_FAILURES' in failed
        # And every branch that is not the skip counts, so a pass that failed
        # is never lost because it happened to be the last one.
        for branch in re.split(r'^      (?:elif .*|else)$', failed,
                               flags=re.M)[1:]:
            assert 'EVIDENCE_FAILURES' in branch, branch


def test_a_reclaim_does_not_start_the_passes_after_it():
    """A pass launched into a host with two minutes left reads the same notice
    seconds later and stops having measured nothing -- burning its turn. That
    is what Block 10's reload-rep3 did on 2026-09-14."""
    body = BLOCK_RUNNER.read_text()
    guard = body.split('run_batch() {', 1)[1].split('\n}', 1)[0]
    assert 'if [[ $STOPPED -eq 1 ]]; then' in guard
    assert 'return 143' in guard


def _logical_lines(body):
    """The script's lines with backslash continuations joined.

    A guard on a `run_batch` call sits at the end of the *command*, which may
    be several source lines; scanning source lines reports the first of them
    as unguarded and the real defect -- a guard dropped from the last one --
    as fine.
    """
    joined, buffer = [], ''
    for line in body.splitlines():
        buffer += line
        if buffer.rstrip().endswith('\\'):
            buffer = buffer.rstrip()[:-1]
            continue
        joined.append(buffer)
        buffer = ''
    if buffer:
        joined.append(buffer)
    return joined


def test_a_reclaim_is_never_left_without_a_marker():
    """Aborting the block on the stop would leave no RAN at all: `block_state`
    reads `started`, `next` re-selects the block, and the plain re-run resumes
    past every cell in the progress file including the failed ones.

    So every `run_batch` call has to absorb the stop -- either through
    `tolerate_stop` or by collecting the status itself, which the two pass
    loops do."""
    body = BLOCK_RUNNER.read_text()
    assert 'tolerate_stop() {' in body
    calls = [l for l in _logical_lines(body)
             if l.strip().startswith('run_batch "')]
    assert len(calls) >= 8, calls
    unguarded = [l for l in calls
                 if 'tolerate_stop' not in l and 'batch_status=$?' not in l]
    assert not unguarded, unguarded


def test_the_stop_is_read_from_the_run_and_not_from_its_exit_status():
    """143 is neither necessary nor sufficient.

    A constrained calibration case never reaches it -- `calibration_case.sh`
    exits 1 when it saw no container of the constrained role, which is what a
    stop at the first cell boundary leaves it -- and any other SIGTERM reaches
    it with no checkpoint behind it, where recording a reclaim would unlock a
    resume that skips every cell in the progress file."""
    body = BLOCK_RUNNER.read_text()
    fn = body.split('run_batch() {', 1)[1].split('\n}', 1)[0]
    # STOPPED=1, not RECLAIMED=1 -- the flag was renamed and this split
    # silently became a no-op, leaving `detect` the whole tail of
    # `run_batch` rather than the detection block it claims to isolate.
    assert 'RECLAIMED=1' not in body, 'stale flag name'
    detect = fn.split('STOPPED=1', 1)[0].rsplit('local stop_reason', 1)[-1]
    assert 's/^stopped: //p' in detect
    assert '-n "$stop_reason"' in detect
    assert 'status -eq 143' not in detect, (
        'a reclaim is proved by the run saying it stopped, not by a status')
    assert 'the host was taken away (exit 143)' not in fn, (
        'a fabricated reason writes `stopped: host reclaimed` for a run that '
        'never checkpointed')


def test_a_reclaimed_block_is_never_read_as_clean(tmp_path):
    """`block_state` reads the stop line alone. If the classifier can answer
    `clean` for the same marker, `next` prints the interrupted headline with
    `accept` beside it and `accept` stamps COMPLETE over cells that never ran.
    """
    root = str(tmp_path)
    directory = _reclaimed_block(root, 'block2-synthetic-rep1')
    marker = os.path.join(directory, 'RAN')
    body = open(marker).read().replace('evidence: 1 check(s) failed',
                                       'evidence: all checks qualified')
    open(marker, 'w').write(body)
    result = block('accept', '2', '--run-id', 'tvtest', results_root=root)
    assert result.returncode != 0, result.stdout
    assert '--resume-after-stop' in result.stderr
    assert not os.path.exists(os.path.join(directory, 'COMPLETE'))


def _stop_log(results_root, index, reason, suffix='reload-rep3'):
    """A run log carrying the `stopped:` line bgperf2 prints at the checkpoint.

    The name matters: `record-stop` globs on the block *index*, because Block
    1's log keys do not begin with its block key.
    """
    import os
    logs = os.path.join(results_root, 'tvtest', 'metadata', 'logs')
    os.makedirs(logs, exist_ok=True)
    path = os.path.join(logs, 'block{0}-{1}.stdout.log'.format(index, suffix))
    with open(path, 'w') as f:
        f.write('some output\nstopped: {0}\n'.format(reason))
    return path


def test_record_stop_writes_the_stop_its_run_logged_and_its_marker_did_not(
        tmp_path):
    """The migration for a marker written before the runner recorded the stop.
    Block 10 is the block the whole reclaim path was built for and the one
    block it could not reach, because its RAN predates the fix."""
    root = str(tmp_path)
    directory = _ran_block(root, 'block2-synthetic-rep1', SHORTFALL)
    reason = 'EC2 spot interruption notice: terminate at 2026-09-14T05:40:43Z'
    _stop_log(root, 2, reason)
    result = block('record-stop', '2', '--run-id', 'tvtest', results_root=root)
    assert result.returncode == 0, result.stderr
    import os
    body = open(os.path.join(directory, 'RAN')).read()
    assert 'stopped: {0}\n'.format(reason) in body, body
    # Marked as backfilled, and naming the log, so a later reader can see that
    # a human asserted this and check it against the attempt.
    assert 'stopped_backfilled: ' in body
    assert 'block2-reload-rep3.stdout.log' in body


def test_record_stop_makes_the_block_resumable_and_stops_pointing_at_force(
        tmp_path):
    """The point of it: the block flips to `interrupted`, so the resume is no
    longer refused and `next` stops sending the operator to --force."""
    root = str(tmp_path)
    _ran_block(root, 'block0-preflight-and-smoke', SHORTFALL)
    _stop_log(root, 0, 'SIGTERM', suffix='smoke-mrt')
    assert block('record-stop', '0', '--run-id', 'tvtest',
                 results_root=root).returncode == 0
    state = block('status', '--run-id', 'tvtest', results_root=root)
    line = [l for l in state.stdout.splitlines() if 'block0' in l][0]
    assert line.endswith('interrupted'), line
    result = block('next', '--run-id', 'tvtest', results_root=root,
                   workdir=str(tmp_path / 'work'))
    assert result.returncode != 0
    assert '--resume-after-stop' in result.stderr


def test_record_stop_is_refused_when_no_log_records_a_stop(tmp_path):
    """The evidence is what unlocks the resume, never the operator's
    recollection. Without this refusal the command is a way to assert a stop
    that did not happen -- and the resume it unlocks skips the failed cells."""
    root = str(tmp_path)
    directory = _ran_block(root, 'block2-synthetic-rep1', SHORTFALL)
    result = block('record-stop', '2', '--run-id', 'tvtest', results_root=root)
    assert result.returncode != 0
    assert '--force' in result.stderr
    import os
    assert 'stopped: ' not in open(os.path.join(directory, 'RAN')).read()


def test_record_stop_copies_the_reason_verbatim_and_invents_none(tmp_path):
    """The same rule the runner follows: any SIGTERM reaches this path, so
    writing a cause over what the run said would put a fabricated account of
    the machine into the campaign's durable record."""
    root = str(tmp_path)
    directory = _ran_block(root, 'block2-synthetic-rep1', SHORTFALL)
    _stop_log(root, 2, 'SIGTERM')
    assert block('record-stop', '2', '--run-id', 'tvtest',
                 results_root=root).returncode == 0
    import os
    body = open(os.path.join(directory, 'RAN')).read()
    assert 'stopped: SIGTERM\n' in body
    assert 'reclaim' not in body.lower(), body


def test_record_stop_is_refused_for_a_marker_that_already_records_a_stop(
        tmp_path):
    """Which is every marker the fixed runner writes, so the command applies to
    pre-fix markers only and has nothing left to do once they are gone. It also
    keeps a second invocation from stacking a duplicate line."""
    root = str(tmp_path)
    directory = _reclaimed_block(root, 'block2-synthetic-rep1')
    _stop_log(root, 2, 'SIGTERM')
    result = block('record-stop', '2', '--run-id', 'tvtest', results_root=root)
    assert result.returncode != 0
    assert '--resume-after-stop' in result.stderr
    import os
    body = open(os.path.join(directory, 'RAN')).read()
    assert body.count('stopped: ') == 1, body


def test_record_stop_does_not_rewrite_an_accepted_blocks_marker(tmp_path):
    """An accepted block is a reviewed one, and its RAN is part of what was
    reviewed. Editing it here would change the record behind the acceptance."""
    root = str(tmp_path)
    directory = _ran_block(root, 'block2-synthetic-rep1', SHORTFALL)
    _stop_log(root, 2, 'SIGTERM')
    import os
    open(os.path.join(directory, 'COMPLETE'), 'w').close()
    result = block('record-stop', '2', '--run-id', 'tvtest', results_root=root)
    assert result.returncode != 0
    assert 'stopped: ' not in open(os.path.join(directory, 'RAN')).read()


def test_record_stop_is_refused_for_a_block_that_never_ran(tmp_path):
    """No RAN is not an interrupted run; it is a block still to start, and a
    marker conjured here would be one `next` advances past."""
    root = str(tmp_path)
    _stop_log(root, 2, 'SIGTERM')
    result = block('record-stop', '2', '--run-id', 'tvtest', results_root=root)
    assert result.returncode != 0
    import os
    assert not os.path.exists(os.path.join(
        root, 'tvtest', 'block2-synthetic-rep1', 'RAN'))


def test_record_stop_reads_only_its_own_blocks_logs(tmp_path):
    """`block1-*` must not match `block10-...`. It does not, because the glob
    requires the literal `-` that `block10` spells `0` -- but the two blocks
    are one keystroke apart and a stop copied across them would unlock a resume
    on a block that never stopped."""
    root = str(tmp_path)
    directory = _ran_block(root, 'block1-generator-calibration', SHORTFALL)
    _stop_log(root, 10, 'a stop belonging to another block',
              suffix='selected-repetitions-reload-rep3')
    result = block('record-stop', '1', '--run-id', 'tvtest', results_root=root)
    assert result.returncode != 0, result.stdout
    import os
    assert 'stopped: ' not in open(os.path.join(directory, 'RAN')).read()


def test_a_stop_is_absorbed_without_being_counted_as_a_failed_check():
    """The pass loops' rule, which has to be `tolerate_stop`'s too: they are
    the two halves of one marker field. While they disagreed, `evidence: N
    check(s) failed` moved with *where* in the matrix the reclaim landed --
    Block 0 stopped in `smoke-synth` recorded 4 against 2 for a stop one batch
    later, for the same event. The shortfall each unmeasured batch reports is
    what records it, and that names the runs."""
    body = BLOCK_RUNNER.read_text()
    fn = body.split('tolerate_stop() {', 1)[1].split('\n}', 1)[0]
    assert 'EVIDENCE_FAILURES=' not in fn, fn


def test_an_interrupted_block_never_reaches_the_success_epilogue():
    """`EVIDENCE_FAILURES` is not a proxy for the stop: neither the pass loops
    nor `tolerate_stop` count a skip, so a notice arriving after the last cell
    of the last pass completed leaves the count at 0 -- and the epilogue would
    write `evidence: all checks qualified` beside `stopped:`, exit 0, and print
    `accept N`. That is the one piece of advice this path exists to withhold,
    and an unattended driver reads the exit status."""
    body = BLOCK_RUNNER.read_text()
    epilogue = body.index('block-$BLOCK_INDEX ran. It is NOT complete')
    guard = body.rindex('if [[ $STOPPED -eq 1 ]]; then', 0, epilogue)
    assert 'exit 1' in body[guard:epilogue], (
        'the stop guard before the success epilogue must end the block')
    assert 'resume_command' in body[guard:epilogue], (
        'and point at the resume, like every other reader of the stop')


def test_the_backfill_provenance_survives_the_resume_it_unlocks():
    """`record-stop` writes `stopped_backfilled:` so a later reader can see a
    human asserted the stop. RAN is rewritten whole by the very resume that
    line unlocks, and nothing else carries it -- so without this the provenance
    survives exactly until it has been used."""
    body = BLOCK_RUNNER.read_text()
    assert 'BACKFILLED_STOP="$(grep -m1 ' in body
    assert 'echo "$BACKFILLED_STOP"' in body
    # Not under --force: a forced block discards the results the assertion is
    # about, so the assertion goes with them.
    capture = body.split('BACKFILLED_STOP=""', 1)[1].split('\nfi', 1)[0]
    assert 'FORCE -eq 0' in capture, capture


def test_the_interrupted_advice_names_force_for_a_pass_that_really_failed():
    """A block that had a pass fail for its own reasons *and* was then stopped
    classifies `interrupted`, because the stop is read first. But `--resume`
    skips every cell in the progress file including the failed ones, so the
    resume returns the identical failure and the only repair is `--force`,
    which is refused beside the resume and was named on neither path."""
    body = BLOCK_RUNNER.read_text()
    for marker in ('Its measured cells are checkpointed and are not lost.',
                   'ones that never ran are outstanding.'):
        advice = body.split(marker, 1)[1][:400]
        assert '--force' in advice, marker


def _blocks_that_measure_nothing():
    """The indices the runner says produce no rows at all."""
    table = BLOCK_RUNNER.read_text().split(
        'declare -A BLOCK_MEASURES_NOTHING=(', 1)
    assert len(table) == 2, 'the measures-nothing table is gone'
    return set(int(n) for n in re.findall(
        r'^\s*\[(\d+)\]=', table[1].split('\n)', 1)[0], re.M))


def test_the_blocks_that_measure_nothing_are_the_review_and_the_report():
    """The table is keyed by index and the claim is about a block.

    Inserting a block below an entry moves that entry onto a different block,
    silently and in the accepting direction: when the peer-sweep expansion
    became block 11, the report's `[11]` would have sat on a block that runs
    six benchmarks and told `next` it produced no rows -- the three messages
    the table feeds are all failure paths, so nobody would see it until one
    fired. Nothing else pins these to the blocks they are about; the indices
    were hand-shifted, which is exactly the edit this catches.
    """
    keys = _block_keys()
    named = sorted(keys[index] for index in _blocks_that_measure_nothing())
    assert named == ['block12-final-report', 'block9-variance-review'], named


def test_a_failed_review_does_not_destroy_the_one_already_on_disk():
    """`rm -rf "$out_dir"` came before the regeneration, and the regeneration
    refuses whenever a later block has been built and not yet accepted --
    which is the ordinary state of the campaign, since a pass is declared as
    soon as its block is built. So a `block-9 --force` deleted an accepted
    block's published review and could not rebuild it, and the expansion
    document cites that review by path as its own evidence.
    """
    body = BLOCK_RUNNER.read_text()
    procedure = body.split('run_variance_review() {', 1)[1].split('\n}', 1)[0]
    # Comments out: this one explains the defect by quoting the line that
    # caused it, and a test that reads prose as code fails on the paragraph
    # describing the fix.
    procedure = '\n'.join(line for line in procedure.splitlines()
                          if not line.strip().startswith('#'))
    staged = procedure.split('--out "$staging"', 1)
    assert len(staged) == 2, 'the review no longer regenerates into staging'
    assert 'rm -rf "$out_dir"' not in staged[0], staged[0]
    # And the move into place happens only after the non-zero path returned.
    assert procedure.index('return') < procedure.index('mv "$staging"')
