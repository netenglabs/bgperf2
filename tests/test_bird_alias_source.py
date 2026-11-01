"""Inert local Git fixtures validate packaging; no daemon code is executed."""
import json
import socket
import zlib

import pytest

import recipe_source_range as ranges
import recipes
from scripts import bird_alias_source as packaging
from test_source_range import git


@pytest.fixture
def source(tmp_path):
    root = tmp_path / 'inert-source'
    root.mkdir()
    git(root, 'init', '-q')
    git(root, 'config', 'user.name', 'Inert packaging fixture')
    git(root, 'config', 'user.email', 'fixture@example.invalid')
    (root / 'configure.ac').write_text('# Never executed\n')
    (root / 'Makefile.in').write_text('# Never executed\n')
    for alias, target in packaging.ALIASES.items():
        destination, original = root / alias, root / target
        destination.parent.mkdir(parents=True, exist_ok=True)
        original.parent.mkdir(parents=True, exist_ok=True)
        original.write_text('/* Inert source bytes */\n')
        destination.symlink_to('../linux/' + original.name)
    revisions = []
    for text in ('before release\n', 'release\n'):
        (root / 'VERSION').write_text(text)
        git(root, 'add', '.')
        git(root, 'commit', '-qm', 'inert release metadata')
        revisions.append(git(root, 'rev-parse', 'HEAD'))
    return root, revisions


def prepare(source, output):
    root, revisions = source
    return packaging.prepare(root, revisions[0], revisions[1], output)


def test_alias_only_adaptation_preserves_original_and_verifies_without_it(source, tmp_path, monkeypatch):
    root, revisions = source
    (root / 'untracked-note').write_text('Preserve this maintainer note\n')
    (root / 'VERSION').write_text('Preserve dirty tracked bytes\n')
    config = ranges._config_guard(ranges.LocalGit(), root)
    before = ranges._source_signature(ranges.LocalGit(), root, config)
    monkeypatch.setattr(socket.socket, '__init__', lambda *a, **k: pytest.fail('network attempted'))
    output = tmp_path / 'packaged'
    result = prepare(source, output)
    assert [row['upstream'] for row in result['revisions']] == revisions
    assert result['source_signatures']['before'] == before == result['source_signatures']['after']
    assert (root / 'untracked-note').read_text().startswith('Preserve')
    assert (root / 'VERSION').read_text().startswith('Preserve')
    assert all((root / alias).is_symlink() for alias in packaging.ALIASES)
    assert not (root / '.git/worktrees').exists()
    for alias, target in packaging.ALIASES.items():
        assert not (output / 'source' / alias).is_symlink()
        assert (output / 'source' / alias).read_bytes() == (output / 'source' / target).read_bytes()
    root.rename(tmp_path / 'moved-original')
    assert packaging.verify(output) == result


def test_changed_packaged_source_is_refused(source, tmp_path):
    output = tmp_path / 'packaged'
    prepare(source, output)
    (output / 'source/VERSION').write_text('tampered\n')
    with pytest.raises(recipes.ContractError, match='clean'):
        packaging.verify(output)


def test_hidden_index_modification_is_refused(source, tmp_path):
    output = tmp_path / 'packaged'
    prepare(source, output)
    git(output / 'source', 'update-index', '--assume-unchanged', 'VERSION')
    (output / 'source/VERSION').write_text('hidden tampering\n')
    with pytest.raises(recipes.ContractError, match='hidden'):
        packaging.verify(output)


def test_mapping_tampering_is_refused(source, tmp_path):
    output = tmp_path / 'packaged'
    prepare(source, output)
    manifest = json.loads((output / 'packaging.json').read_text())
    manifest['revisions'][0]['derived'] = manifest['revisions'][1]['derived']
    (output / 'packaging.json').write_text(json.dumps(manifest))
    with pytest.raises(recipes.ContractError, match='derived tree'):
        packaging.verify(output)


def test_copied_upstream_corruption_is_detected_without_changing_original(source, tmp_path):
    root, revisions = source
    output = tmp_path / 'packaged'
    prepare(source, output)
    oid = git(root, 'rev-parse', revisions[-1] + ':VERSION')
    original = root / '.git/objects' / oid[:2] / oid[2:]
    copied = output / 'upstream.git/objects' / oid[:2] / oid[2:]
    original_bytes = original.read_bytes()
    assert original.stat().st_ino != copied.stat().st_ino
    copied.write_bytes(zlib.compress(b'blob 8\0changed\n'))
    assert original.read_bytes() == original_bytes
    with pytest.raises(recipes.ContractError, match='object hash differs'):
        packaging.verify(output)


def test_replaced_owned_report_is_refused(source, tmp_path):
    output = tmp_path / 'packaged'
    prepare(source, output)
    (output / 'REPORT.md').write_text('Claim an upstream bug fix\n')
    with pytest.raises(recipes.ContractError, match='human report'):
        packaging.verify(output)


def test_unknown_symlink_is_refused_with_partial_evidence_retained(source, tmp_path):
    root, revisions = source
    (root / 'extra-alias').symlink_to('VERSION')
    git(root, 'add', '.')
    git(root, 'commit', '-qm', 'inert unsupported alias')
    output = tmp_path / 'packaged'
    with pytest.raises(recipes.ContractError, match='unselected symlink'):
        packaging.prepare(root, revisions[-1], git(root, 'rev-parse', 'HEAD'), output)
    assert json.loads((output / 'outcome.json').read_text())['status'] == 'failed'
    assert (output / 'upstream.git').is_dir()


def test_configured_filter_refused_before_output(source, tmp_path):
    root, _ = source
    sentinel = tmp_path / 'filter-ran'
    git(root, 'config', 'filter.trap.clean', 'touch ' + str(sentinel))
    output = tmp_path / 'packaged'
    with pytest.raises(recipes.ContractError, match='filters'):
        prepare(source, output)
    assert not output.exists() and not sentinel.exists()


def test_exact_alias_target_is_required():
    entries = {'configure.ac': ('100644', b'inert'), 'Makefile.in': ('100644', b'inert')}
    for alias, target in packaging.ALIASES.items():
        entries[alias] = ('120000', ('../../outside/' + target.rsplit('/', 1)[1]).encode())
        entries[target] = ('100644', b'inert')
    with pytest.raises(recipes.ContractError, match='alias differs'):
        packaging._adapt(entries)


def test_source_destination_overlap_refused(source):
    root, revisions = source
    with pytest.raises(recipes.ContractError, match='overlaps'):
        packaging.prepare(root, *revisions, root / 'packaged')


def raw_object(root, kind, data):
    oid = ranges._object_hash(kind, data)
    path = root / '.git/objects' / oid[:2] / oid[2:]
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(zlib.compress(kind.encode() + b' ' + str(len(data)).encode() + b'\0' + data))
    return oid


@pytest.mark.parametrize('modes', [('100644', '100644'), ('40000', '40000'), ('100644', '40000')])
def test_hash_valid_duplicate_sibling_or_file_directory_collision_refused(source, modes):
    root, _ = source
    blob = raw_object(root, 'blob', b'inert\n')
    subtree = raw_object(root, 'tree', b'100644 nested\0' + bytes.fromhex(blob))
    duplicate = b''.join(mode.encode() + b' collision\0' + bytes.fromhex(subtree if mode == '40000' else blob)
                         for mode in modes)
    ordinary = b'100644 Makefile.in\0' + bytes.fromhex(blob) + b'100644 configure.ac\0' + bytes.fromhex(blob)
    tree = raw_object(root, 'tree', ordinary + duplicate)
    commit = raw_object(root, 'commit', b'tree ' + tree.encode() + b'\n\nInert malformed-tree fixture\n')
    with pytest.raises(recipes.ContractError, match='duplicate sibling'):
        packaging._snapshot(ranges.LocalGit(), root, commit)


def test_tree_directory_and_file_entry_count_is_bounded(source, monkeypatch):
    root, revisions = source
    monkeypatch.setattr(ranges, 'MAX_CHECKOUT_FILES', 2)
    with pytest.raises(recipes.ContractError, match='entry count exceeds'):
        packaging._snapshot(ranges.LocalGit(), root, revisions[-1])
