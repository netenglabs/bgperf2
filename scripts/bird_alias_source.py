# Copyright (C) 2026 bgperf2 contributors. Apache-2.0.
"""Explicit packaging-only BIRD history adaptation; never execute source code.

The maintained source builder still refuses symlinks. This separate preparation
materializes exactly BIRD's two known BSD aliases from verified in-tree blobs,
retains the upstream objects, and records new, explicitly derived commit IDs.
"""
import argparse
import base64
from pathlib import Path
import os
import shutil
import stat
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import recipes
import recipe_bisection as records
import recipe_source_range as ranges
import recipe_targets as targets

SCHEMA = 'bgperf2/bird-alias-packaging/v1'
ALIASES = {'sysdep/bsd-netlink/netlink.Y': 'sysdep/linux/netlink.Y',
           'sysdep/bsd-netlink/netlink.c': 'sysdep/linux/netlink.c'}


def _object(git, root, kind, oid, limit=targets.SOURCE_LIMIT):
    data = git.run(root, 'cat-file', kind, oid, output_limit=limit)
    if ranges._object_hash(kind, data) != oid:
        raise recipes.ContractError('Packaging raw Git object hash differs')
    return data


def _snapshot(git, root, revision):
    """Authenticate raw trees before interpreting filenames or alias contents."""
    raw = _object(git, root, 'commit', revision, 65536)
    records.commit_parents(base64.b64encode(raw).decode(), revision)
    tree = raw.splitlines()[0][5:].decode('ascii')
    entries, pending, total, metadata = {}, [(tree, '', 0)], 0, 0
    selected_paths = set()
    while pending:
        oid, prefix, depth = pending.pop()
        if depth > 256:
            raise recipes.ContractError('Packaging tree nesting exceeds bound')
        data = _object(git, root, 'tree', oid, ranges.MAX_GIT_OUTPUT)
        metadata += len(data)
        if metadata > ranges.MAX_GIT_OUTPUT:
            raise recipes.ContractError('Packaging tree metadata exceeds bound')
        position = 0
        sibling_names = set()
        while position < len(data):
            space, end = data.find(b' ', position), data.find(b'\0', position)
            if space < position or end < space or end + 21 > len(data):
                raise recipes.ContractError('Packaging tree entry is malformed')
            mode, name = data[position:space], data[space + 1:end].decode('utf-8')
            oid = data[end + 1:end + 21].hex()
            position = end + 21
            if not name or '/' in name or name in ('.', '..') or name.lower() == '.git':
                raise recipes.ContractError('Packaging tree path is unsafe')
            if name in sibling_names:
                raise recipes.ContractError('Packaging raw tree contains duplicate sibling names')
            sibling_names.add(name)
            path = prefix + name
            recipes._artifact_path(path, 'packaging source path')
            if path in selected_paths:
                raise recipes.ContractError('Packaging raw tree contains a repeated path')
            selected_paths.add(path)
            if len(selected_paths) > ranges.MAX_CHECKOUT_FILES:
                raise recipes.ContractError('Packaging tree entry count exceeds bound')
            if mode == b'40000':
                pending.append((oid, path + '/', depth + 1))
            else:
                if mode not in (b'100644', b'100755', b'120000'):
                    raise recipes.ContractError('Packaging refuses submodules and special entries')
                if mode == b'120000' and path not in ALIASES:
                    raise recipes.ContractError('Packaging refuses an unselected symlink: ' + path)
                blob = _object(git, root, 'blob', oid)
                total += len(blob)
                entries[path] = (mode.decode(), blob)
                if len(entries) > 20_000 or total > targets.SOURCE_LIMIT:
                    raise recipes.ContractError('Packaging source exceeds snapshot resource bound')
    if not {'configure.ac', 'Makefile.in'} <= entries.keys():
        raise recipes.ContractError('Packaging requires BIRD configure.ac and Makefile.in')
    return entries


def _adapt(entries):
    entries = dict(entries)
    for alias, target in ALIASES.items():
        if entries.get(alias) != ('120000', ('../linux/' + Path(target).name).encode()):
            raise recipes.ContractError('Selected BIRD alias differs: ' + alias)
        if target not in entries or entries[target][0] not in ('100644', '100755'):
            raise recipes.ContractError('Selected BIRD alias target must be an in-tree regular file')
        entries[alias] = ('100644', entries[target][1])
    return entries


def _report(manifest):
    rows = '\n'.join(f"| `{row['upstream']}` | `{row['derived']}` |" for row in manifest['revisions'])
    return ('# Explicit BIRD alias packaging\n\n'
        'This is real BIRD source with a local packaging adaptation, not an upstream bug/fix. '
        'Only the two selected BSD symlink aliases become regular files with byte-identical '
        'Linux target content. Every other path, file mode and byte is preserved. '
        'Original attribution and license files remain in each tree.\n\n'
        '| Upstream commit | Derived packaging commit |\n| --- | --- |\n' + rows + '\n\n'
        'The derived history has two new local commits. Its first commit is a root snapshot, '
        'so these are not original upstream commit identities. The independent upstream.git '
        'object copy preserves the selected original history; packaging.json records the mapping '
        'and unchanged original-checkout signatures. Source hashes do not authenticate publishers. '
        'No configure code, compiler, image probe, download or worker was executed. '
        'Performance policy remains disabled and calibration deferred.\n')


def prepare(source, good, bad, output):
    source, output = records.safe(source), records.safe(output)
    if not source.is_dir() or not (source / '.git').is_dir():
        raise recipes.ContractError('Packaging requires a full standalone source checkout')
    if os.path.lexists(output) or not output.parent.is_dir():
        raise recipes.ContractError('Packaging needs a fresh destination with an existing parent')
    for protected in (source, ranges.ENGINE_ROOT):
        if protected == output or protected in output.parents or output in protected.parents:
            raise recipes.ContractError('Packaging destination overlaps a source checkout')
    git = ranges.LocalGit()
    budget = ranges._metadata_guard(source / '.git')
    config = ranges._config_guard(git, source)
    if git.run(source, 'for-each-ref', '--format=%(refname)', 'refs/replace').strip():
        raise recipes.ContractError('Packaging refuses replacement refs')
    if Path(git.run(source, 'rev-parse', '--show-toplevel').decode().strip()) != source:
        raise recipes.ContractError('Packaging source must be the checkout root')
    hidden = git.run(source, 'ls-files', '-v', '-z').split(b'\0')
    if any(row and not row.startswith(b'H ') for row in hidden):
        raise recipes.ContractError('Packaging refuses hidden index flags')
    before = ranges._source_signature(git, source, config)
    revisions, _ = ranges._chain(git, source, good, bad)
    if len(revisions) != 2:
        raise recipes.ContractError('Packaging selects exactly two adjacent first-parent revisions')
    if shutil.disk_usage(output.parent).free < budget['bytes'] + 2 * targets.SOURCE_LIMIT + ranges.MAX_METADATA_BYTES:
        raise recipes.ContractError('Insufficient observed free disk for bounded packaging')
    output.mkdir(mode=0o700)
    records.write(output / 'outcome-started.json', {'status': 'preparing', 'execution': 'not_requested'})
    try:
        for name in ('hooks', 'template', 'source'):
            (output / name).mkdir(mode=0o700)
        original_git = git
        git = ranges.LocalGit(output / 'hooks')
        git.calls = original_git.calls
        upstream, derived = output / 'upstream.git', output / 'source'
        git.run(output, 'clone', '--bare', '--local', '--no-hardlinks', '--no-tags',
                '--template=' + str(output / 'template'), '--', source, upstream)
        ranges._metadata_guard(upstream)
        git.run(derived, 'init', '--quiet', '--template=' + str(output / 'template'))
        mapping, previous_paths = [], set()
        for revision in revisions:
            entries = _adapt(_snapshot(git, upstream, revision))
            # This deliberately narrow adapter refuses deletion transitions rather
            # than removing any source/evidence file from its owned checkout.
            if previous_paths - entries.keys():
                raise recipes.ContractError('Selected packaging transition contains deleted paths')
            for relative, (mode, data) in entries.items():
                path = derived / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
                path.chmod(0o755 if mode == '100755' else 0o644)
            git.run(derived, 'add', '--all', '--force', '--', '.')
            git.run(derived, '-c', 'user.name=BIRD local packaging',
                    '-c', 'user.email=packaging@example.invalid', '-c', 'commit.gpgsign=false',
                    'commit', '--quiet', '--allow-empty', '-m',
                    'build: materialize BIRD aliases for upstream ' + revision)
            mapping.append({'upstream': revision, 'derived': git.run(derived, 'rev-parse', 'HEAD').decode().strip()})
            previous_paths = set(entries)
        after = ranges._source_signature(original_git, source, ranges._config_guard(original_git, source))
        recipes._same(before, after, 'packaging original checkout signatures')
        manifest = {'schema': SCHEMA, 'output': str(output), 'original_source': str(source),
                    'revisions': mapping, 'aliases': ALIASES,
                    'source_signatures': {'before': before, 'after': after},
                    'execution': 'not_requested'}
        records.write(output / 'packaging.json', manifest)
        (output / 'REPORT.md').write_text(_report(manifest))
        records.write(output / 'git-commands.json', git.calls)
        verify(output)
        records.write(output / 'outcome.json', {'status': 'prepared', 'execution': 'not_requested'})
        return manifest
    except BaseException as exc:
        if not os.path.lexists(output / 'outcome.json'):
            records.write(output / 'outcome.json', {'status': 'failed', 'reason': str(exc),
                          'execution': 'not_requested', 'recovery': 'Retain partial output; select a fresh destination.'})
        raise


def verify(output):
    output = records.safe(output)
    manifest = records.load(output / 'packaging.json')
    recipes._keys(manifest, ('schema', 'output', 'original_source', 'revisions', 'aliases',
                            'source_signatures', 'execution'))
    if manifest['schema'] != SCHEMA or manifest['output'] != str(output) or manifest['aliases'] != ALIASES or manifest['execution'] != 'not_requested':
        raise recipes.ContractError('Packaging contract or location differs')
    recipes._keys(manifest['source_signatures'], ('before', 'after'))
    for signature in manifest['source_signatures'].values():
        ranges._signature_schema(signature)
    recipes._same(manifest['source_signatures']['before'], manifest['source_signatures']['after'], 'packaging original signatures')
    rows = manifest['revisions']
    if not isinstance(rows, list) or len(rows) != 2:
        raise recipes.ContractError('Packaging requires two mapped revisions')
    git = ranges.LocalGit(output / 'hooks')
    upstream, derived = output / 'upstream.git', output / 'source'
    for root in (upstream, derived / '.git'):
        ranges._metadata_guard(root)
        ranges._owned_config_guard(root)
    for root in (upstream, derived):
        ranges._config_guard(git, root)
        if git.run(root, 'for-each-ref', '--format=%(refname)', 'refs/replace').strip():
            raise recipes.ContractError('Packaging refuses replacement refs')
    for row in rows:
        recipes._keys(row, ('upstream', 'derived'))
        for oid in row.values():
            recipes._match(oid, recipes._REVISION, 'packaging revision', 'a full Git commit')
        expected = _adapt(_snapshot(git, upstream, row['upstream']))
        actual = _snapshot(git, derived, row['derived'])
        if expected != actual:
            raise recipes.ContractError('Packaging derived tree differs from the alias-only adaptation')
    for root, field in ((upstream, 'upstream'), (derived, 'derived')):
        chain, _ = ranges._chain(git, root, rows[0][field], rows[1][field])
        recipes._same(chain, [row[field] for row in rows], 'packaging consecutive history')
    if git.run(derived, 'rev-parse', 'HEAD').decode().strip() != rows[-1]['derived'] or git.run(derived, 'status', '--porcelain=v1', '--untracked-files=all').strip():
        raise recipes.ContractError('Packaging derived checkout must remain clean at the selected HEAD')
    # Validate current working bytes too; status alone can hide index flags.
    if any(row and not row.startswith(b'H ') for row in git.run(derived, 'ls-files', '-v', '-z').split(b'\0')):
        raise recipes.ContractError('Packaging refuses hidden derived index flags')
    from recipe_results import _regular_file
    for relative, (mode, data) in actual.items():
        with _regular_file(derived, relative) as stream:
            observed = os.fstat(stream.fileno())
            content = stream.read(len(data) + 1)
        if content != data or bool(observed.st_mode & 0o111) != (mode == '100755') or not stat.S_ISREG(observed.st_mode):
            raise recipes.ContractError('Packaging working bytes or mode differ from the derived tree')
    if ranges._bytes(output / 'REPORT.md').decode() != _report(manifest):
        raise recipes.ContractError('Packaging human report differs')
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    create = sub.add_parser('prepare')
    for name in ('source', 'good', 'bad', 'output'):
        create.add_argument('--' + name, required=True)
    check = sub.add_parser('verify')
    check.add_argument('output')
    args = parser.parse_args(argv)
    try:
        if args.command == 'prepare':
            result = prepare(args.source, args.good, args.bad, args.output)
        else:
            result = verify(args.output)
        print(recipes.canonical_json(result))
        return 0
    except (recipes.ContractError, OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
