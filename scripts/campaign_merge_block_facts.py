#!/usr/bin/env python3
'''Merge one block's facts into a campaign manifest, keeping what it supersedes.

The manifest records host, Docker, image and revision facts under each block's
own key, because images are rebuilt and hosts are replaced between blocks and
one shared record would describe whichever block wrote last. That key is
written every time a block is *entered*, and a block is entered more than once
whenever it is resumed -- which, on a spot host that is reclaimed without
warning, is the ordinary case rather than the exception.

Replacing the entry outright is what this exists to stop. Block 2 of the 64 GB
timing campaign measured ten of its fourteen rows on `ip-172-31-21-79`, lost
the host to a reclaim, and resumed on `ip-172-31-18-191`; the ten rows survived
in the CSV and in their artifacts, and the only record of the machine that
produced them was overwritten by the resume. The rows were still there and
nothing could say where they came from, which is the same failure as a result
nobody can trace back to a build.

So a superseded entry moves into `previous_entries` on the new one, exactly as
a superseded order moves to `previous_seeds` in a batch progress file, and
under the same two conditions:

- **Only when rows it describes still exist.** An entry describing runs that no
  longer exist is worse than no entry -- it is the `COMPLETE` marker a
  `--force` retracts, one layer down.

  That is why the *entry* merge always keeps, and forgetting is a separate
  call (`--prune-under`) made from the one place that actually deletes results.
  Deciding it where a block is entered is too early and loses in the wrong
  direction: `capture_metadata` runs before preflight, `verify` and the MRT
  validation, each of which can end the block, so a `--force` that never
  reached a container would already have dropped the history of fourteen rows
  still sitting on disk with their markers -- attributing them to a host that
  measured none of them. `retract_forced_markers` avoids the same asymmetry by
  running after the gates that can still turn the run away.
- **Only when it differs.** A block re-entered on the same host with the same
  images and revision supersedes nothing, and carrying a duplicate would make
  the count of entries read as a count of reclaims.

Each carried entry also records `rows_measured`: the run names that attempt
added, which is the question a reader actually has. Knowing that two hosts
touched a block is not it -- the CSV cannot say which rows each one produced,
because a row carries the date it ran and no host.

It is a *delta*, not a snapshot of the directory, and the difference decides
whether the field can be read at face value. `capture_metadata` runs before
preflight, `verify` and the MRT validation, every one of which can end the
block, so an attempt can be entered and measure nothing; credited with what it
found on disk it would be handed the previous attempt's rows, and a third
attempt would report the same ten names under two hosts. The names already
attributed to earlier carried entries are therefore subtracted, and an attempt
that measured nothing records an empty list -- which is the true answer, and
distinguishes an attempt that ran nothing from one that ran rows.

Names are qualified by the sub-directory that holds the CSV, because a block
may run several batches under one directory: Block 0 runs two smokes and
Block 1 renders one config into two out_dirs, so bare run names collide across
sub-batches and a `set` of them would claim one run where two exist.

Reads the new block entry as JSON on stdin; prints `{"blocks": {...}}` on
stdout for the manifest writer to merge. Never raises on a fact it cannot
collect: a manifest missing one carried row list is worth more than a block
that refused to start.
'''
import argparse
import csv
import datetime
import io
import json
import os
import sys
import tempfile


CARRY_KEY = 'previous_entries'


def rows_present(results_dir):
    '''Run names in every batch CSV under `results_dir`, sorted and deduped.

    The `name` column is the run name `bench_output_prefix()` builds each
    artifact from, so this is the join between a carried entry and the files
    it accounts for. Read by column name rather than by position: the stats
    row is positional for the graphs and has drifted by a column once already.

    Each name is qualified by the directory holding its CSV, relative to
    `results_dir`. A block is not always one batch -- Block 0 runs two smokes
    and Block 1 renders one config into two out_dirs whose CSVs carry the same
    run names -- so unqualified names collide across sub-batches and the join
    this exists for would silently claim one run where two ran.
    '''
    if not results_dir or not os.path.isdir(results_dir):
        return []
    names = set()
    for root, _dirs, files in os.walk(results_dir):
        for leaf in files:
            if not leaf.endswith('.csv'):
                continue
            where = os.path.relpath(root, results_dir)
            try:
                with io.open(os.path.join(root, leaf), encoding='utf-8') as handle:
                    reader = csv.reader(handle)
                    header = next(reader, None)
                    if not header:
                        continue
                    stripped = [column.strip() for column in header]
                    if 'name' not in stripped:
                        continue
                    index = stripped.index('name')
                    for row in reader:
                        if len(row) > index and row[index].strip():
                            name = row[index].strip()
                            names.add(name if where == os.curdir
                                      else '{0}/{1}'.format(where, name))
            except (OSError, ValueError, csv.Error):
                continue
    return sorted(names)


def _informative(value):
    '''False for a reading that says nothing: absent, null, or empty.'''
    return value is not None and value != {} and value != []


def contradicts(previous, current, path=()):
    '''True when two entries disagree about a fact **both** of them recorded.

    Supersession is not "the documents differ". It is "this is a different
    machine or a different build", and the thing that reliably makes two
    entries differ without that being true is a *failed reading*. Every fact
    here comes from a tool that can fail independently -- IMDS throttles or
    times out under the load of `doctor`, `images` and `verify`; `docker
    version` can time out; `tool_facts()` can raise -- so one attempt records
    `instance: {id, type, availability_zone}` and the next records
    `instance: {error: ...}`, on one machine that never went anywhere.

    Equality on the whole document calls that a reclaim. A carried entry
    *means* a reclaim by this module's own rule, so the block's rows would then
    be split across two entries that are one host -- the inverse of the claim
    the file exists to make. An error is likewise excluded by name: its text is
    written by whatever failed, and curl times out with the milliseconds in the
    message, so two failures disagree on the millisecond.

    So only leaves present and informative on **both** sides are compared. A
    fact one attempt could not read is not evidence about the machine, in
    either direction. Anything that really is a new host moves `hostname`,
    which no failure empties.
    '''
    if isinstance(previous, dict) and isinstance(current, dict):
        for key in set(previous) & set(current):
            if key == CARRY_KEY or key == 'error' or key.endswith('_error'):
                continue
            before, after = previous[key], current[key]
            if not (_informative(before) and _informative(after)):
                continue
            if contradicts(before, after, path + (key,)):
                return True
        return False
    if isinstance(previous, list) and isinstance(current, list):
        if len(previous) != len(current):
            return True
        return any(contradicts(a, b, path) for a, b in zip(previous, current))
    return previous != current


def merge(existing, block_key, new_entry, keeps_previous_rows, results_dir,
          announce=None):
    merged = dict(existing or {})
    previous = merged.get(block_key)
    entry = dict(new_entry)
    carried = []
    if isinstance(previous, dict) and keeps_previous_rows:
        # Inherited history is kept only on the path that keeps the rows it
        # describes. Carrying it under --force would leave the manifest naming
        # runs that `run_batch` is about to `rm -rf` -- the same claim
        # `retract_forced_markers` exists to retract one layer up, and it
        # survives a depth-1 test because the first forced re-run of a block
        # has nothing inherited to keep.
        carried = list(previous.get(CARRY_KEY) or [])
        # Stored whole, compared narrowly. `contradicts()` ignores a fact one
        # side could not read; the *record* must keep it, because this entry is
        # the only surviving description of a host that no longer exists.
        # Storing the comparison's view instead dropped every `error` key from
        # it -- an attempt whose `tool_facts()` raised was filed as
        # `"bgperf2": {}`, losing the revision and the reason together, and a
        # failed `docker images` became indistinguishable from a host that had
        # none. "Missing" and "missing because X" must not look the same.
        superseded = {k: v for k, v in previous.items() if k != CARRY_KEY}
        if contradicts(previous, entry):
            already = set()
            for older in carried:
                already.update(older.get('rows_measured') or [])
            superseded['superseded_at'] = datetime.datetime.now(
                datetime.timezone.utc).replace(microsecond=0).isoformat()
            superseded['rows_measured'] = [
                row for row in rows_present(results_dir) if row not in already]
            carried.append(superseded)
            if announce is not None:
                announce(superseded)
    if carried:
        entry[CARRY_KEY] = carried
    merged[block_key] = entry
    return merged


def describe_supersession(superseded, entry):
    '''One line for the operator, because the silence is the thing.'''
    was = (superseded.get('host') or {}).get('hostname') or 'an unnamed host'
    now = (entry.get('host') or {}).get('hostname') or 'an unnamed host'
    rows = superseded.get('rows_measured') or []
    if was == now:
        what = 'this block was last entered under different facts on {0}'.format(was)
    else:
        what = 'this block was last entered on {0}, and is now on {1}'.format(was, now)
    return 'manifest: {0}; keeping that attempt and the {1} row(s) it measured'.format(
        what, len(rows))


def prune(existing, block_key, under):
    '''Forget carried rows under `under`, and any entry left describing none.

    Called when a `--force` run has just deleted one output directory, so the
    manifest stops naming rows at the moment they stop existing rather than at
    the moment a block was entered. Scoped to the directory actually removed
    because a block is not always one batch: Block 1 makes four `run_batch`
    calls, and dropping every carried entry on the first deletion would forget
    the hosts of three directories still on disk.
    '''
    if not under:
        # An empty value would mean "forget every carried row", which is the
        # one thing this module exists to prevent, and it is what a caller
        # supplies by accident -- a failed command substitution in argument
        # position is an empty string and `set -e` does not catch it there.
        # Forgetting the whole block is spelled `.` and has to be meant.
        raise ValueError('--prune-under needs a path; pass "." to forget the '
                         'whole block deliberately')
    merged = dict(existing or {})
    entry = merged.get(block_key)
    if not isinstance(entry, dict):
        return merged
    kept = []
    prefix = None if under == os.curdir else '{0}/'.format(under.strip('/'))
    for older in entry.get(CARRY_KEY) or []:
        rows = older.get('rows_measured')
        if rows is None:
            kept.append(older)
            continue
        if prefix is None:
            remaining = []
        else:
            remaining = [row for row in rows if not row.startswith(prefix)]
        if remaining or not rows:
            # An entry that named nothing to begin with described an attempt
            # that measured nothing; it is still a host that entered the block
            # and there is nothing about it to invalidate.
            older = dict(older)
            older['rows_measured'] = remaining
            kept.append(older)
    entry = dict(entry)
    if kept:
        entry[CARRY_KEY] = kept
    else:
        entry.pop(CARRY_KEY, None)
    merged[block_key] = entry
    return merged


def load_blocks(path):
    if not os.path.exists(path):
        return {}
    try:
        with io.open(path, encoding='utf-8') as handle:
            return json.load(handle).get('blocks') or {}
    except (OSError, ValueError):
        return {}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--manifest', required=True,
                        help='existing manifest, may be absent or unreadable')
    parser.add_argument('--block-key', required=True)
    parser.add_argument('--results-dir', default=None,
                        help="the block's results, read for the run names a "
                             'superseded entry accounts for')
    parser.add_argument('--prune-under', default=None,
                        help='forget carried rows under this path (relative to '
                             "the block's results) and rewrite the manifest in "
                             'place; for use where a --force run deletes them')
    keeps = parser.add_mutually_exclusive_group()
    keeps.add_argument('--keeps-previous-rows', dest='keeps',
                       action='store_true', default=None)
    keeps.add_argument('--discards-previous-rows', dest='keeps',
                       action='store_false')
    args = parser.parse_args(argv)

    if args.prune_under is not None:
        # Rewrites in place rather than printing, because it is called after
        # the manifest for this attempt has already been written -- there is
        # no `campaign_write_manifest` downstream to hand it to.
        blocks = load_blocks(args.manifest)
        pruned = prune(blocks, args.block_key, args.prune_under)
        if pruned != blocks and os.path.exists(args.manifest):
            with io.open(args.manifest, encoding='utf-8') as handle:
                document = json.load(handle)
            document['blocks'] = pruned
            handle_fd, tmp = tempfile.mkstemp(
                dir=os.path.dirname(os.path.abspath(args.manifest)),
                suffix='.tmp')
            with os.fdopen(handle_fd, 'w', encoding='utf-8') as out:
                json.dump(document, out, indent=2, sort_keys=True)
                out.write('\n')
                # flush and fsync before the rename, exactly as
                # `campaign_write_manifest` does and for the same reason: the
                # host is reclaimed without warning, and a rename that reaches
                # the directory before the data reaches the disk leaves a
                # zero-length manifest -- every block's facts gone, not only
                # the rows this call meant to forget.
                out.flush()
                os.fsync(out.fileno())
            os.replace(tmp, args.manifest)
        return 0

    if args.keeps is None:
        parser.error('one of --keeps-previous-rows / --discards-previous-rows '
                     'is required unless --prune-under is given')

    new_entry = json.loads(sys.stdin.read())
    existing = load_blocks(args.manifest)
    merged = merge(existing, args.block_key, new_entry, args.keeps,
                   args.results_dir,
                   # stderr, never stdout: stdout is the merged JSON the
                   # runner captures. A within-block host change is a finding
                   # by the plan's own rule, and the two that came before it
                   # went unnoticed precisely because nothing said anything at
                   # the moment they happened.
                   announce=lambda s: print(describe_supersession(s, new_entry),
                                            file=sys.stderr))
    print(json.dumps({'blocks': merged}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
