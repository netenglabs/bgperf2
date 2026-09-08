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
    result = block('block-2', results_root=results, workdir=work)
    assert result.returncode == 2
    assert 'not built yet' in result.stderr


def test_next_selects_block_zero_first_then_advances_only_past_acceptance(roots):
    results, work = roots
    run_root = os.path.join(results, '2026-timing-validation')
    block0 = os.path.join(run_root, 'block0-preflight-and-smoke')
    os.makedirs(block0)

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

    # Only now does `next` move on -- and block 1 is not built, which is what
    # proves it moved rather than re-running block 0.
    result = block('next', results_root=results, workdir=work)
    assert result.returncode == 2
    assert 'block-1' in result.stderr


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

    result = block('block-2', results_root=results, workdir=work)
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
    the marker checks that let --force past them. block-2 is not built, so this
    run measures nothing -- and deleting the acceptance of results that are
    still there would leave `status` reporting a block nobody has to redo as
    one that must be redone.'''
    results, work = roots
    run_root = os.path.join(results, '2026-timing-validation')
    block2 = os.path.join(run_root, 'block2-synthetic-rep1')
    os.makedirs(block2)
    open(os.path.join(block2, 'RAN'), 'w').close()
    open(os.path.join(block2, 'COMPLETE'), 'w').close()

    result = run([BLOCK_RUNNER, 'block-2', '--force', '--results-root', results,
                  '--workdir', work, '--allow-root-workdir'])
    assert result.returncode == 2
    assert os.path.exists(os.path.join(block2, 'COMPLETE'))
    assert os.path.exists(os.path.join(block2, 'RAN'))


def test_a_refused_force_does_not_retract_anything(roots):
    '''A forced run turned away by the workdir guard never replaced the
    results whose acceptance it would have retracted.'''
    results, _ = roots
    run_root = os.path.join(results, '2026-timing-validation')
    block2 = os.path.join(run_root, 'block2-synthetic-rep1')
    os.makedirs(block2)
    open(os.path.join(block2, 'COMPLETE'), 'w').close()

    result = run([BLOCK_RUNNER, 'block-2', '--force', '--results-root', results,
                  '--workdir', '/nonexistent-bgperf-campaign-test/work'])
    assert result.returncode != 0
    assert 'on the root filesystem' in result.stderr
    assert os.path.exists(os.path.join(block2, 'COMPLETE'))


def test_a_forced_run_does_not_resume_past_the_cells_it_is_re_measuring():
    """`batch --resume` records every completed cell, so a forced re-run that
    kept --resume would skip all of them, exit 0 having measured nothing, and
    then stamp the old artifacts with the current revision."""
    body = open(BLOCK_RUNNER).read()
    run_batch = body[body.index('run_batch() {'):body.index('EVIDENCE_FAILURES=0')]
    assert 'if [[ $FORCE -eq 1 ]]; then' in run_batch
    assert 'resume_args=()' in run_batch


def test_one_failed_evidence_check_does_not_cost_the_block_its_other_evidence():
    """Under `set -euo pipefail` a checker exiting non-zero would abort the
    script where it stands, so the second smoke's verdict would never be
    written -- half the block's record lost to the first failure."""
    body = open(BLOCK_RUNNER).read()
    assert 'EVIDENCE_FAILURES=$((EVIDENCE_FAILURES + 1))' in body
    assert 'if [[ $EVIDENCE_FAILURES -gt 0 ]]; then' in body
    # and the RAN marker is only written after that count is read
    assert body.index('if [[ $EVIDENCE_FAILURES -gt 0 ]]; then') < body.index('> "$BLOCK_DIR/RAN"')
