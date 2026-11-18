"""Source-bound injector patch and reported identity; no image build or Docker."""
from pathlib import Path
import subprocess

import pytest

from bgpdump2 import Bgpdump2, Bgpdump2Tester
from bgpdump2_patch import OLD, NEW, PATCH, SUFFIX, patched_ref, patch_command
from base import Container, VersionUnavailable

REVISION = 'a0191842fedf001abbda6364ab5c70d3f1c0788d'


@pytest.mark.parametrize('value', ['master'+SUFFIX, 'a019184'+SUFFIX, 'A'*40+SUFFIX,
                                  'a'*40+';echo x'+SUFFIX])
def test_patch_profile_requires_exact_commit(value):
    with pytest.raises(ValueError, match='full lowercase'):
        Bgpdump2.resolve_ref(value)


def test_profile_resolves_source_without_changing_ordinary_refs():
    assert patched_ref(REVISION+SUFFIX) == REVISION
    assert Bgpdump2.resolve_ref(REVISION+SUFFIX) == REVISION
    assert Bgpdump2.resolve_ref(REVISION) == REVISION
    assert Bgpdump2.resolve_ref(None) == 'master'
    assert Bgpdump2.resolve_ref('some-upstream-branch') == 'some-upstream-branch'


@pytest.mark.parametrize('text', ['unrecognized source\n', OLD+'\n'+OLD+'\n', NEW+'\n'])
def test_source_drift_refuses_before_mutation(tmp_path, text):
    source = tmp_path/'src/bgpdump_data.c'
    source.parent.mkdir()
    source.write_text(text)
    value = subprocess.run(['sh', '-c', patch_command()], cwd=tmp_path, capture_output=True)
    assert value.returncode != 0
    assert source.read_text() == text


def test_patch_preserves_unrelated_source_and_refuses_reapplication(tmp_path):
    source = tmp_path/'src/bgpdump_data.c'
    source.parent.mkdir()
    other = '  bgp_path_node = ptree_search(different_arguments);\n'
    before = '/* upstream attribution and other source stay intact */\n'+OLD+'\n'+other
    source.write_text(before)
    subprocess.run(['sh', '-c', patch_command()], cwd=tmp_path, check=True)
    assert source.read_text() == before.replace(OLD, NEW)
    assert subprocess.run(['sh', '-c', patch_command()], cwd=tmp_path).returncode != 0


def test_rendered_profile_is_explicit_and_default_recipe_stays_unpatched():
    ordinary = Bgpdump2.render_dockerfile(REVISION)
    corrected = Bgpdump2.render_dockerfile(REVISION+SUFFIX)
    assert 'ptree_search_exact' not in ordinary
    assert 'bgperf-bgpdump2-patch' not in ordinary
    assert 'git checkout '+REVISION in corrected
    assert patch_command() in corrected and PATCH in corrected
    assert corrected.index(patch_command()) < corrected.index('autoreconf -fi')
    assert Bgpdump2.render_dockerfile(REVISION) == ordinary
    with pytest.raises(ValueError, match='checkout must match'):
        Bgpdump2.build_image(version=REVISION+SUFFIX, checkout='b'*40)


@pytest.mark.parametrize('marker', ['unknown', PATCH+'\nbgperf-patch: '+PATCH, ''])
def test_unknown_or_ambiguous_marker_never_attests_patched_version(tmp_path, monkeypatch, marker):
    monkeypatch.setattr(Container, 'exec_version_cmd', lambda self:
        'Version: 2.0.14\ncommit: a019184\nbgperf-patch: '+marker+'\n')
    with pytest.raises(VersionUnavailable, match='patch marker'):
        Bgpdump2Tester('one', str(tmp_path), {}).exec_version_cmd()


def test_queried_version_distinguishes_patched_injector(tmp_path, monkeypatch):
    monkeypatch.setattr(Container, 'exec_version_cmd', lambda self:
        'Version: 2.0.14\ncommit: a019184\nbgperf-patch: '+PATCH+'\n')
    instance = Bgpdump2Tester('one', str(tmp_path), {})
    assert instance.exec_version_cmd() == '2.0.14 (a019184) [pa-exact-v1]'
    assert 'cat /root/bgperf-bgpdump2-patch' in instance.get_version_cmd()[2]


@pytest.mark.parametrize('banner', ['Version: 2.0.14\ncommit: a019184\n',
    'Version: 2.0.14\ncommit: bbbbbbb\nbgperf-patch: pa-exact-v1\n',
    'Version: 2.0.14\ncommit:\nbgperf-patch: pa-exact-v1\n'])
def test_profile_tag_requires_patch_marker_and_matching_source(tmp_path, monkeypatch, banner):
    monkeypatch.setattr(Container, 'exec_version_cmd', lambda self: banner)
    instance = Bgpdump2Tester('one', str(tmp_path), {}, image=Bgpdump2.image_tag(REVISION+SUFFIX))
    with pytest.raises(VersionUnavailable):
        instance.exec_version_cmd()


def test_profile_tag_never_defaults_to_unversioned_image():
    with pytest.raises(ValueError, match='explicit versioned image tag'):
        Bgpdump2.build_image(version=REVISION+SUFFIX)
