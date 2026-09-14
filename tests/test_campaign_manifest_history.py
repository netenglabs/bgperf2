'''What a campaign manifest keeps when a block is entered more than once.

A block is entered once per *attempt*, and on a spot host reclaimed without
warning several attempts is the ordinary case. The rows measured before a
reclaim survive in the CSV and in their artifacts; the record of the machine
that measured them is in the manifest and nowhere else, so an entry replaced
outright leaves results nobody can trace back to a host -- the provenance
failure, one layer up from a build.

Docker-free like the rest of the campaign-script coverage: every test here
exercises the merge, which happens before the first container.
'''
import json
import os
import subprocess
import sys

import pytest

from conftest import REPO_ROOT

MERGER = REPO_ROOT / 'scripts' / 'campaign_merge_block_facts.py'

FIRST = {'host': {'hostname': 'ip-172-31-21-79', 'cpu_threads': 16},
         'bgperf2': {'revision': 'aaaaaaa'}, 'block_index': 2}
SECOND = {'host': {'hostname': 'ip-172-31-18-191', 'cpu_threads': 16},
          'bgperf2': {'revision': 'bbbbbbb'}, 'block_index': 2}


def merge(manifest, entry, keeps=True, results_dir=None, block_key='block2'):
    argv = [sys.executable, str(MERGER), '--manifest', str(manifest),
            '--block-key', block_key,
            '--keeps-previous-rows' if keeps else '--discards-previous-rows']
    if results_dir is not None:
        argv += ['--results-dir', str(results_dir)]
    done = subprocess.run(argv, input=json.dumps(entry), capture_output=True,
                          text=True, timeout=60, cwd=str(REPO_ROOT))
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)['blocks']


def write_manifest(tmp_path, blocks):
    path = tmp_path / 'manifest.json'
    path.write_text(json.dumps({'blocks': blocks}), encoding='utf-8')
    return path


def write_csv(directory, names):
    directory.mkdir(parents=True, exist_ok=True)
    header = 'name, target, version, peers, elapsed (s)\n'
    rows = ''.join('{0},bird,2.19.2,50,91\n'.format(n) for n in names)
    (directory / 'block.csv').write_text(header + rows, encoding='utf-8')


def test_a_resumed_block_keeps_the_host_that_measured_its_earlier_rows(tmp_path):
    """The reclaim this exists for: ten rows on one host, four on the next."""
    manifest = write_manifest(tmp_path, {'block2': dict(FIRST)})
    blocks = merge(manifest, SECOND)
    assert blocks['block2']['host']['hostname'] == 'ip-172-31-18-191'
    carried = blocks['block2']['previous_entries']
    assert [c['host']['hostname'] for c in carried] == ['ip-172-31-21-79']
    assert carried[0]['bgperf2']['revision'] == 'aaaaaaa'
    assert carried[0]['superseded_at']


def test_a_carried_entry_names_the_rows_it_accounts_for(tmp_path):
    """Which rows each host produced is the question a reader actually has,
    and the CSV cannot answer it: a row carries the date it ran and no host."""
    manifest = write_manifest(tmp_path, {'block2': dict(FIRST)})
    results = tmp_path / 'block2'
    write_csv(results / 'synthetic', ['frr_c 8.5', 'bird 2.19.2'])
    blocks = merge(manifest, SECOND, results_dir=results)
    assert blocks['block2']['previous_entries'][0]['rows_measured'] == [
        'synthetic/bird 2.19.2', 'synthetic/frr_c 8.5']


def test_a_forced_re_run_carries_nothing(tmp_path):
    """--force discards this block's previous rows a moment later, so the
    superseded entry would describe runs that no longer exist -- the same
    reason a forced run retracts the COMPLETE marker."""
    manifest = write_manifest(tmp_path, {'block2': dict(FIRST)})
    results = tmp_path / 'block2'
    write_csv(results / 'synthetic', ['frr_c 8.5'])
    blocks = merge(manifest, SECOND, keeps=False, results_dir=results)
    assert 'previous_entries' not in blocks['block2']
    assert blocks['block2']['host']['hostname'] == 'ip-172-31-18-191'


def test_an_unchanged_re_entry_supersedes_nothing(tmp_path):
    """A block resumed on the same host with the same images and revision
    superseded nothing, and a duplicate would make the count of carried
    entries read as a count of reclaims."""
    manifest = write_manifest(tmp_path, {'block2': dict(FIRST)})
    blocks = merge(manifest, dict(FIRST))
    assert 'previous_entries' not in blocks['block2']


def test_history_accumulates_across_reclaims_without_nesting(tmp_path):
    """Two reclaims give two carried entries side by side. Nested, the second
    would bury the first one level deeper on every attempt and no reader could
    say how many hosts a block had."""
    manifest = write_manifest(tmp_path, {'block2': dict(FIRST)})
    once = merge(manifest, SECOND)
    manifest = write_manifest(tmp_path, once)
    third = {'host': {'hostname': 'ip-172-31-40-2', 'cpu_threads': 16},
             'bgperf2': {'revision': 'ccccccc'}, 'block_index': 2}
    twice = merge(manifest, third)
    carried = twice['block2']['previous_entries']
    assert [c['host']['hostname'] for c in carried] == [
        'ip-172-31-21-79', 'ip-172-31-18-191']
    assert all('previous_entries' not in c for c in carried)


def test_another_blocks_facts_are_untouched(tmp_path):
    """The merge is per run ID and `blocks` is one key: Block 0's entry is an
    accepted block's, and the plan cites it."""
    manifest = write_manifest(tmp_path, {'block0': {'host': {'hostname': 'a'}},
                                         'block2': dict(FIRST)})
    blocks = merge(manifest, SECOND)
    assert blocks['block0'] == {'host': {'hostname': 'a'}}


def test_a_first_entry_writes_what_it_always_wrote(tmp_path):
    """A block entered once must produce exactly the document it produced
    before this existed, so nothing downstream reading the manifest moves."""
    blocks = merge(tmp_path / 'absent.json', SECOND)
    assert blocks == {'block2': SECOND}


def test_an_unreadable_manifest_does_not_stop_a_block(tmp_path):
    """A manifest missing one carried entry is worth more than a block that
    refused to start -- `campaign_host_facts.py`'s rule, next door."""
    manifest = tmp_path / 'manifest.json'
    manifest.write_text('{not json', encoding='utf-8')
    assert merge(manifest, SECOND) == {'block2': SECOND}


def test_the_row_scan_reads_the_name_column_by_name(tmp_path):
    """The stats row is positional for the graphs and has drifted by a column
    once already; a history keyed on index 0 would be arithmetic nobody could
    check."""
    manifest = write_manifest(tmp_path, {'block2': dict(FIRST)})
    results = tmp_path / 'block2'
    results.mkdir(parents=True)
    (results / 'block.csv').write_text(
        'date, name, target\n2026-09-10,bird 2.19.2,bird\n', encoding='utf-8')
    blocks = merge(manifest, SECOND, results_dir=results)
    assert blocks['block2']['previous_entries'][0]['rows_measured'] == [
        'bird 2.19.2']  # CSV sits at the root, so nothing to qualify with


def test_a_block_with_no_results_yet_carries_an_empty_row_list(tmp_path):
    """A block reclaimed before its first cell finished has a host to name and
    no rows to attribute; an absent directory is not an error."""
    manifest = write_manifest(tmp_path, {'block2': dict(FIRST)})
    blocks = merge(manifest, SECOND, results_dir=tmp_path / 'nothing-here')
    assert blocks['block2']['previous_entries'][0]['rows_measured'] == []


def test_a_forced_re_run_drops_inherited_history_too(tmp_path):
    """The depth-1 case is not the rule. --force `rm -rf`s the block's results
    a moment later, so an entry inherited from an *earlier* attempt describes
    runs that are about to be deleted exactly as the immediately superseded one
    does. Carried through, the manifest would keep `rows_measured` naming rows
    nothing can produce again -- the claim `retract_block_markers` retracts,
    one layer up."""
    manifest = write_manifest(tmp_path, {'block2': dict(FIRST)})
    results = tmp_path / 'block2'
    write_csv(results / 'synthetic', ['frr_c 8.5'])
    once = merge(manifest, SECOND, results_dir=results)
    assert len(once['block2']['previous_entries']) == 1
    manifest = write_manifest(tmp_path, once)
    third = {'host': {'hostname': 'ip-172-31-40-2'},
             'bgperf2': {'revision': 'ccccccc'}, 'block_index': 2}
    forced = merge(manifest, third, keeps=False, results_dir=results)
    assert 'previous_entries' not in forced['block2']


def test_an_attempt_that_measured_nothing_is_credited_with_nothing(tmp_path):
    """`capture_metadata` runs before preflight, `verify` and the MRT
    validation, so an attempt can be entered and end before a cell. Credited
    with what it found on disk it would be handed the previous attempt's rows,
    and two hosts would claim the same ten."""
    manifest = write_manifest(tmp_path, {'block2': dict(FIRST)})
    results = tmp_path / 'block2'
    write_csv(results / 'synthetic', ['bird 2.19.2', 'frr_c 8.5'])
    once = merge(manifest, SECOND, results_dir=results)
    assert len(once['block2']['previous_entries'][0]['rows_measured']) == 2
    # SECOND is entered and dies before measuring: the directory is unchanged.
    manifest = write_manifest(tmp_path, once)
    third = {'host': {'hostname': 'ip-172-31-40-2'},
             'bgperf2': {'revision': 'ccccccc'}, 'block_index': 2}
    twice = merge(manifest, third, results_dir=results)
    carried = twice['block2']['previous_entries']
    assert [c['host']['hostname'] for c in carried] == [
        'ip-172-31-21-79', 'ip-172-31-18-191']
    assert carried[0]['rows_measured'] == ['synthetic/bird 2.19.2',
                                           'synthetic/frr_c 8.5']
    assert carried[1]['rows_measured'] == []


def test_a_row_measured_after_the_supersession_belongs_to_the_new_attempt(tmp_path):
    """The delta is what the resumed attempt added, so a third attempt names
    only the rows the second one produced."""
    manifest = write_manifest(tmp_path, {'block2': dict(FIRST)})
    results = tmp_path / 'block2'
    write_csv(results / 'synthetic', ['bird 2.19.2'])
    once = merge(manifest, SECOND, results_dir=results)
    write_csv(results / 'synthetic', ['bird 2.19.2', 'frr_c 8.5'])
    manifest = write_manifest(tmp_path, once)
    third = {'host': {'hostname': 'ip-172-31-40-2'},
             'bgperf2': {'revision': 'ccccccc'}, 'block_index': 2}
    twice = merge(manifest, third, results_dir=results)
    carried = twice['block2']['previous_entries']
    assert carried[0]['rows_measured'] == ['synthetic/bird 2.19.2']
    assert carried[1]['rows_measured'] == ['synthetic/frr_c 8.5']


def test_run_names_are_qualified_by_their_sub_batch(tmp_path):
    """Block 0 runs two smokes and Block 1 renders one config into two
    out_dirs, so the same run name appears in both CSVs. Deduped bare, a
    carried entry would claim one run where two ran."""
    manifest = write_manifest(tmp_path, {'block2': dict(FIRST)})
    results = tmp_path / 'block2'
    write_csv(results / 'tail-baseline', ['mrt 2x500k'])
    write_csv(results / 'observer-tail', ['mrt 2x500k'])
    blocks = merge(manifest, SECOND, results_dir=results)
    assert blocks['block2']['previous_entries'][0]['rows_measured'] == [
        'observer-tail/mrt 2x500k', 'tail-baseline/mrt 2x500k']


def test_a_supersession_says_so_on_stderr(tmp_path):
    """The two host changes that came before this existed went unnoticed
    because nothing said anything at the moment they happened. A resumed block
    on a replacement instance must not print what a same-host resume prints."""
    manifest = write_manifest(tmp_path, {'block2': dict(FIRST)})
    argv = [sys.executable, str(MERGER), '--manifest', str(manifest),
            '--block-key', 'block2', '--keeps-previous-rows']
    done = subprocess.run(argv, input=json.dumps(SECOND), capture_output=True,
                          text=True, timeout=60, cwd=str(REPO_ROOT))
    assert done.returncode == 0, done.stderr
    assert 'ip-172-31-21-79' in done.stderr
    assert 'ip-172-31-18-191' in done.stderr
    # and stdout stays the JSON the runner captures
    assert json.loads(done.stdout)['blocks']['block2']


def test_an_unchanged_re_entry_says_nothing(tmp_path):
    manifest = write_manifest(tmp_path, {'block2': dict(FIRST)})
    argv = [sys.executable, str(MERGER), '--manifest', str(manifest),
            '--block-key', 'block2', '--keeps-previous-rows']
    done = subprocess.run(argv, input=json.dumps(FIRST), capture_output=True,
                          text=True, timeout=60, cwd=str(REPO_ROOT))
    assert done.returncode == 0
    assert done.stderr.strip() == ''


def prune(manifest, under, block_key='block2'):
    argv = [sys.executable, str(MERGER), '--manifest', str(manifest),
            '--block-key', block_key, '--prune-under', under]
    done = subprocess.run(argv, capture_output=True, text=True, timeout=60,
                          cwd=str(REPO_ROOT))
    assert done.returncode == 0, done.stderr
    return json.loads(manifest.read_text(encoding='utf-8'))['blocks']


def test_entering_a_block_never_forgets_even_under_force(tmp_path):
    """`capture_metadata` runs before preflight, `verify` and the MRT
    validation, each of which ends the block. A --force that never reached a
    container must not already have dropped the history of rows that are all
    still on disk with their markers -- that attributes them to a host which
    measured none of them, which is the loss this merge exists to prevent."""
    manifest = write_manifest(tmp_path, {'block2': dict(FIRST)})
    results = tmp_path / 'block2'
    write_csv(results / 'synthetic', ['bird 2.19.2'])
    blocks = merge(manifest, SECOND, results_dir=results)
    assert blocks['block2']['previous_entries'][0]['rows_measured'] == [
        'synthetic/bird 2.19.2']


def test_pruning_forgets_only_the_directory_that_was_deleted(tmp_path):
    """Block 1 makes four run_batch calls under one block directory, so a
    forced run deletes them one at a time. Forgetting everything on the first
    deletion would drop the host of three directories still on disk."""
    carried = dict(FIRST)
    carried['rows_measured'] = ['tail-baseline/mrt', 'observer-tail/mrt']
    manifest = write_manifest(tmp_path, {
        'block2': dict(SECOND, previous_entries=[carried])})
    blocks = prune(manifest, 'tail-baseline')
    assert blocks['block2']['previous_entries'][0]['rows_measured'] == [
        'observer-tail/mrt']


def test_pruning_the_last_rows_drops_the_entry(tmp_path):
    """An entry describing runs that no longer exist is worse than no entry."""
    carried = dict(FIRST)
    carried['rows_measured'] = ['synthetic/bird 2.19.2', 'synthetic/frr_c 8.5']
    manifest = write_manifest(tmp_path, {
        'block2': dict(SECOND, previous_entries=[carried])})
    blocks = prune(manifest, 'synthetic')
    assert 'previous_entries' not in blocks['block2']
    assert blocks['block2']['host']['hostname'] == 'ip-172-31-18-191'


def test_pruning_keeps_an_attempt_that_measured_nothing(tmp_path):
    """It is still a host that entered the block, and deleting a directory it
    never wrote to says nothing about it."""
    carried = dict(FIRST)
    carried['rows_measured'] = []
    manifest = write_manifest(tmp_path, {
        'block2': dict(SECOND, previous_entries=[carried])})
    blocks = prune(manifest, 'synthetic')
    assert blocks['block2']['previous_entries'][0]['rows_measured'] == []


def test_pruning_leaves_other_blocks_alone(tmp_path):
    carried = dict(FIRST)
    carried['rows_measured'] = ['synthetic/bird 2.19.2']
    manifest = write_manifest(tmp_path, {
        'block0': {'host': {'hostname': 'a'}},
        'block2': dict(SECOND, previous_entries=[carried])})
    blocks = prune(manifest, 'synthetic')
    assert blocks['block0'] == {'host': {'hostname': 'a'}}


def test_pruning_an_absent_manifest_is_not_an_error(tmp_path):
    argv = [sys.executable, str(MERGER), '--manifest', str(tmp_path / 'no.json'),
            '--block-key', 'block2', '--prune-under', 'synthetic']
    done = subprocess.run(argv, capture_output=True, text=True, timeout=60,
                          cwd=str(REPO_ROOT))
    assert done.returncode == 0, done.stderr


def test_a_merge_still_requires_a_keeps_flag(tmp_path):
    """--prune-under made the flags optional; a merge without one must refuse
    rather than default, since the default would be a silent policy."""
    argv = [sys.executable, str(MERGER), '--manifest', str(tmp_path / 'no.json'),
            '--block-key', 'block2']
    done = subprocess.run(argv, input=json.dumps(SECOND), capture_output=True,
                          text=True, timeout=60, cwd=str(REPO_ROOT))
    assert done.returncode != 0
    assert 'keeps-previous-rows' in done.stderr


def test_an_asymmetric_failed_reading_is_not_a_different_host(tmp_path):
    """The case the symmetric test missed. IMDS throttles or times out under
    the load of `doctor`, `images` and `verify`, so attempt 1 records the
    instance facts and attempt 2 records only a failure -- on one machine that
    never went anywhere. A carried entry means a reclaim, so calling that a
    supersession splits the block's rows across two entries that are one
    host."""
    full = {'host': {'hostname': 'h1', 'cpu_threads': 16,
                     'instance': {'id': 'i-1', 'type': 'm7a.4xlarge'}}}
    failed = {'host': {'hostname': 'h1', 'cpu_threads': 16,
                       'instance': {'type_error': 'timed out'}}}
    manifest = write_manifest(tmp_path, {'block2': full})
    assert 'previous_entries' not in merge(manifest, failed)['block2']
    # and in the other direction: the reading coming back is not a reclaim
    manifest = write_manifest(tmp_path, {'block2': failed})
    assert 'previous_entries' not in merge(manifest, full)['block2']


def test_an_empty_reading_is_not_a_different_host(tmp_path):
    """A failed `docker images` gives `{}`, which is also what a host with no
    images gives; and a failed `docker version` gives null. Neither is
    evidence that the machine changed."""
    full = {'host': {'hostname': 'h1'},
            'docker': {'server_version': '27.0', 'bgperf_images': {'a': '1'}}}
    empty = {'host': {'hostname': 'h1'},
             'docker': {'server_version': None, 'bgperf_images': {}}}
    manifest = write_manifest(tmp_path, {'block2': full})
    assert 'previous_entries' not in merge(manifest, empty)['block2']


def test_a_carried_entry_keeps_the_reasons_it_recorded(tmp_path):
    """Comparison ignores a failed reading; the *record* must not. This entry
    is the only surviving description of a host that no longer exists, so
    filing an attempt whose `tool_facts()` raised as `bgperf2: {}` loses the
    revision and the reason together."""
    first = {'host': {'hostname': 'h1'},
             'bgperf2': {'revision': 'aaa', 'error': 'git not found'}}
    manifest = write_manifest(tmp_path, {'block2': first})
    blocks = merge(manifest, {'host': {'hostname': 'h2'}})
    carried = blocks['block2']['previous_entries'][0]
    assert carried['bgperf2'] == {'revision': 'aaa', 'error': 'git not found'}


def test_a_failed_reading_is_not_a_different_host(tmp_path):
    """curl reports a timeout with the milliseconds in it, so two attempts
    that both failed to reach IMDS disagree on the text. Compared, that
    manufactures a supersession out of a same-host resume -- and a carried
    entry means a reclaim, so N re-entries would accumulate N-1 attempts that
    never happened and split `rows_measured` between them."""
    first = {'host': {'hostname': 'h1', 'cpu_threads': 16,
                      'instance': {'error': 'timed out after 2002 ms'}}}
    again = {'host': {'hostname': 'h1', 'cpu_threads': 16,
                      'instance': {'error': 'timed out after 2013 ms'}}}
    manifest = write_manifest(tmp_path, {'block2': first})
    blocks = merge(manifest, again)
    assert 'previous_entries' not in blocks['block2']


def test_a_real_fact_change_still_supersedes_through_an_error_key(tmp_path):
    """Dropping error text must not drop the facts beside it."""
    first = {'host': {'hostname': 'h1', 'instance': {'error': 'x'}}}
    again = {'host': {'hostname': 'h2', 'instance': {'error': 'y'}}}
    manifest = write_manifest(tmp_path, {'block2': first})
    blocks = merge(manifest, again)
    assert [c['host']['hostname']
            for c in blocks['block2']['previous_entries']] == ['h1']


def test_an_empty_prune_under_is_refused(tmp_path):
    """A failed command substitution in argument position is an empty string
    and `set -e` does not catch it there, so an empty value must not be read
    as 'forget every carried row' -- the one thing this module prevents."""
    carried = dict(FIRST)
    carried['rows_measured'] = ['synthetic/bird 2.19.2']
    manifest = write_manifest(tmp_path, {
        'block2': dict(SECOND, previous_entries=[carried])})
    argv = [sys.executable, str(MERGER), '--manifest', str(manifest),
            '--block-key', 'block2', '--prune-under', '']
    done = subprocess.run(argv, capture_output=True, text=True, timeout=60,
                          cwd=str(REPO_ROOT))
    assert done.returncode != 0
    # and the manifest is untouched
    blocks = json.loads(manifest.read_text(encoding='utf-8'))['blocks']
    assert blocks['block2']['previous_entries'][0]['rows_measured'] == [
        'synthetic/bird 2.19.2']


def test_forgetting_the_whole_block_has_to_be_spelled(tmp_path):
    """`.` is the deliberate form, for the block whose out_dir is the block
    directory itself."""
    carried = dict(FIRST)
    carried['rows_measured'] = ['bird 2.19.2']
    manifest = write_manifest(tmp_path, {
        'block2': dict(SECOND, previous_entries=[carried])})
    blocks = prune(manifest, '.')
    assert 'previous_entries' not in blocks['block2']


def test_the_pruned_manifest_stays_loadable_and_newline_terminated(tmp_path):
    carried = dict(FIRST)
    carried['rows_measured'] = ['synthetic/a', 'other/b']
    manifest = write_manifest(tmp_path, {
        'block2': dict(SECOND, previous_entries=[carried])})
    prune(manifest, 'synthetic')
    text = manifest.read_text(encoding='utf-8')
    assert text.endswith('\n')
    assert json.loads(text)['blocks']['block2'][
        'previous_entries'][0]['rows_measured'] == ['other/b']
