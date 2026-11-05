"""Pinned source checks account for hidden index entries and Git replacements."""
import copy
import hashlib

import pytest

import recipe_preflight as preflight
import recipe_targets as targets
from test_recipe_targets import source, recipe, git, plan


@pytest.mark.parametrize('flag', ['--assume-unchanged', '--skip-worktree'])
def test_engine_check_cannot_call_hidden_modified_source_clean(source, recipe, monkeypatch, flag):
    root, revision = source
    document = copy.deepcopy(recipe)
    document['engine']['revision'] = revision
    document['completion']['engine_revision'] = revision
    git(root, 'update-index', flag, 'main.c')
    (root / 'main.c').write_text('int main(void) { return 99; }\n')
    assert git(root, 'status', '--porcelain') == ''
    before = (root / '.git/index').read_bytes()
    monkeypatch.setattr(preflight, 'ROOT', root)
    report = {'checks': [], 'status': 'checks_passed'}
    assert preflight._engine(report, document, preflight._environment()) is False
    assert report['checks'][-1]['status'] == 'refused'
    assert 'index' in report['checks'][-1]['reason']
    assert (root / '.git/index').read_bytes() == before


def test_source_planning_uses_original_commit_objects_despite_replacement_refs(source, recipe, monkeypatch):
    root, original = source
    original_bytes = targets._git(root, 'cat-file', 'commit', original)
    (root / 'main.c').write_text('int main(void) { return 42; }\n')
    git(root, 'add', 'main.c')
    git(root, 'commit', '-qm', 'fixture: replacement tree')
    replacement = git(root, 'rev-parse', 'HEAD')
    git(root, 'replace', original, replacement)
    git(root, 'checkout', '-q', '--detach', '--force', original)
    assert git(root, 'status', '--porcelain') == ''
    observed = targets._git(root, 'cat-file', 'commit', original)
    assert observed == original_bytes
    assert hashlib.sha1(b'commit ' + str(len(observed)).encode() + b'\0' + observed).hexdigest() == original
    # The replacement work tree is an explicit dirty change relative to the
    # actual selected commit, rather than silently becoming that commit's tree.
    selected = plan(recipe, (root, original), include_dirty=True)
    assert selected['source']['dirty'] is True
    assert selected['source']['patch_sha256'] != hashlib.sha256(b'').hexdigest()
    document = copy.deepcopy(recipe)
    document['engine']['revision'] = original
    document['completion']['engine_revision'] = original
    monkeypatch.setattr(preflight, 'ROOT', root)
    report = {'checks': [], 'status': 'checks_passed'}
    assert preflight._engine(report, document, preflight._environment()) is False
    assert report['checks'][-1]['status'] == 'refused'
