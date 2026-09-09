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


def block(*args, results_root, workdir=None):
    argv = [BLOCK_RUNNER, *args, '--results-root', results_root]
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


def unbuilt_block():
    """The lowest block with no branch: the one a guard test may safely run.

    Every test that drives the runner all the way to its `case` uses this, so
    landing a new block moves them along instead of pointing them at a real
    matrix.
    """
    built = set(_built_blocks())
    for index, key in enumerate(_block_keys()):
        if index not in built:
            return index, key
    raise AssertionError(
        'every block is built, so no guard test can reach the refusal branch '
        'without running a benchmark; give these tests another way in')


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
    assert len(lines) == 12
    assert lines[0].split()[1] == 'block0-preflight-and-smoke'
    assert lines[1].split()[1] == 'block1-generator-calibration'
    assert lines[5].split()[1] == 'block5-mrt-rep1'
    assert lines[11].split()[1] == 'block11-final-report'


def test_status_reports_every_block_before_anything_has_run(roots):
    results, _ = roots
    result = block('status', results_root=results)
    assert result.returncode == 0, result.stderr
    assert result.stdout.count('not-started') == 12


def test_an_unknown_block_is_refused_by_name(roots):
    results, work = roots
    result = block('block-99', results_root=results, workdir=work)
    assert result.returncode != 0
    assert 'no such block' in result.stderr


def test_a_block_that_is_not_built_yet_says_so_rather_than_inventing_one(roots):
    '''A block that ran the wrong matrix produces rows that look exactly like
    the right ones.'''
    results, work = roots
    index, _ = unbuilt_block()
    result = block('block-%d' % index, results_root=results, workdir=work)
    assert result.returncode == 2
    assert 'not built yet' in result.stderr


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


def test_a_recorded_workdir_wins_over_the_one_invoked_with(roots):
    '''The campaign contract's rule: the recorded manifest wins and the
    discrepancy is a finding to report, not a path to silently switch.'''
    import json
    results, work = roots
    metadata = os.path.join(results, '2026-timing-validation', 'metadata')
    os.makedirs(metadata)
    with open(os.path.join(metadata, 'manifest.json'), 'w') as f:
        json.dump({'workdir': '/data/somewhere-else'}, f)

    index, _ = unbuilt_block()
    result = block('block-%d' % index, results_root=results, workdir=work)
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


def test_a_force_that_replaced_nothing_retracts_nothing(roots):
    '''The retraction belongs where results start being replaced, not beside
    the marker checks that let --force past them. An unbuilt block measures
    nothing -- and deleting the acceptance of results that are still there
    would leave `status` reporting a block nobody has to redo as one that must
    be redone.'''
    results, work = roots
    run_root = os.path.join(results, '2026-timing-validation')
    index, key = unbuilt_block()
    target = os.path.join(run_root, key)
    os.makedirs(target)
    open(os.path.join(target, 'RAN'), 'w').close()
    open(os.path.join(target, 'COMPLETE'), 'w').close()

    result = run([BLOCK_RUNNER, 'block-%d' % index, '--force',
                  '--results-root', results,
                  '--workdir', work, '--allow-root-workdir'])
    assert result.returncode == 2
    assert os.path.exists(os.path.join(target, 'COMPLETE'))
    assert os.path.exists(os.path.join(target, 'RAN'))


def test_a_refused_force_does_not_retract_anything(roots):
    '''A forced run turned away by the workdir guard never replaced the
    results whose acceptance it would have retracted.'''
    results, _ = roots
    run_root = os.path.join(results, '2026-timing-validation')
    index, key = unbuilt_block()
    target = os.path.join(run_root, key)
    os.makedirs(target)
    open(os.path.join(target, 'COMPLETE'), 'w').close()

    result = run([BLOCK_RUNNER, 'block-%d' % index, '--force',
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
