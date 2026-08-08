'''Version selection: user-facing version -> git ref -> image tag.

The whole point of the mechanism is that `--version 10.1` reaches the right
FRR branch and the right image, so each hop is pinned here. None of it needs
Docker -- the mapping is pure.
'''
import pytest

from argparse import Namespace

from conftest import REPO_ROOT

import bgperf2

import base
from bird import BIRD
from flock import Flock
from frr_compiled import FRRoutingCompiled
from gobgp import GoBGP
from junos import Junos


class TestResolveRef:
    @pytest.mark.parametrize('version,ref', [
        ('8', 'stable/8.0'),        # bare major means its first release
        ('9', 'stable/9.0'),
        ('10', 'stable/10.0'),
        ('8.0', 'stable/8.0'),
        ('10.1', 'stable/10.1'),
        ('10.10', 'stable/10.10'),  # not 10.1 -- see test_batch_yaml_keeps_versions_as_strings
        ('10.1.1', 'frr-10.1.1'),   # point releases are tags, not branches
        ('master', 'master'),       # raw refs pass through
        ('stable/10.4', 'stable/10.4'),
        ('deadbeef', 'deadbeef'),
    ])
    def test_frr(self, version, ref):
        assert FRRoutingCompiled.resolve_ref(version) == ref

    def test_frr_default(self):
        assert FRRoutingCompiled.resolve_ref(None) == 'master'

    @pytest.mark.parametrize('version,ref', [
        ('2.19.2', 'v2.19.2'),
        ('3.3.2', 'v3.3.2'),
        ('2.18', 'v2.18'),
        ('master', 'master'),
    ])
    def test_bird(self, version, ref):
        assert BIRD.resolve_ref(version) == ref

    def test_gobgp(self):
        assert GoBGP.resolve_ref('3.37.0') == 'v3.37.0'


class TestImageTag:
    def test_no_version_is_latest(self):
        assert FRRoutingCompiled.image_tag() == 'bgperf/frr_c:latest'

    def test_version_becomes_the_tag(self):
        assert FRRoutingCompiled.image_tag('10.1') == 'bgperf/frr_c:10.1'
        assert BIRD.image_tag('2.19.2') == 'bgperf/bird:2.19.2'

    def test_slashes_are_flattened(self):
        '''Docker tags cannot contain '/', but a raw ref can.'''
        assert FRRoutingCompiled.image_tag('stable/10.4') == 'bgperf/frr_c:stable_10.4'

    def test_nos_images_are_versioned_too(self):
        '''cRPD is downloaded, but tagging it by version still works.'''
        assert Junos.image_tag('24.2') == 'crpd:24.2'
        assert Junos.image_tag() == 'crpd:latest'

    def test_fixed_release_daemon_rejects_versions(self):
        with pytest.raises(base.VersionNotSupported):
            Flock.image_tag('21.1.0')
        assert Flock.image_tag() == 'bgperf/flock:latest'


class TestNormalizeImageName:
    @pytest.mark.parametrize('name,expected', [
        ('bgperf/bird', 'bgperf/bird:latest'),
        ('bgperf/bird:2.19.2', 'bgperf/bird:2.19.2'),
        ('crpd', 'crpd:latest'),
        # a registry port is not a tag
        ('localhost:5000/bgperf/bird', 'localhost:5000/bgperf/bird:latest'),
        ('localhost:5000/bgperf/bird:10.1', 'localhost:5000/bgperf/bird:10.1'),
    ])
    def test(self, name, expected):
        assert base.normalize_image_name(name) == expected


class TestImgExists:
    '''img_exists compared only the repository half of RepoTags[0], so every
    version tag of a daemon looked present as soon as any one of them was.
    '''
    def _fake_images(self, monkeypatch, repo_tags):
        monkeypatch.setattr(base.dckr, 'images',
                            lambda: [{'RepoTags': t} for t in repo_tags])

    def test_distinguishes_tags(self, monkeypatch):
        self._fake_images(monkeypatch, [['bgperf/frr_c:latest'], ['bgperf/frr_c:10.1']])
        assert base.img_exists('bgperf/frr_c:10.1')
        assert base.img_exists('bgperf/frr_c')          # implicit :latest
        assert not base.img_exists('bgperf/frr_c:9.0')

    def test_reads_every_tag_not_just_the_first(self, monkeypatch):
        self._fake_images(monkeypatch, [['bgperf/frr_c:latest', 'bgperf/frr_c:10.3']])
        assert base.img_exists('bgperf/frr_c:10.3')

    def test_untagged_images_do_not_crash(self, monkeypatch):
        self._fake_images(monkeypatch, [None, [], ['bgperf/bird:latest']])
        assert base.img_exists('bgperf/bird')


class TestRequireImage:
    def test_message_carries_the_build_command(self, monkeypatch):
        monkeypatch.setattr(base, 'img_exists', lambda name: False)
        with pytest.raises(base.ImageNotBuilt) as e:
            FRRoutingCompiled.require_image('10.1')
        assert './bgperf2.py update frr_c --version 10.1' in str(e.value)

    def test_downloaded_images_say_to_tag_instead(self, monkeypatch):
        monkeypatch.setattr(base, 'img_exists', lambda name: False)
        with pytest.raises(base.ImageNotBuilt) as e:
            Junos.require_image('24.2')
        assert 'docker tag' in str(e.value)
        assert 'update' not in str(e.value)

    def test_returns_the_tag_when_present(self, monkeypatch):
        monkeypatch.setattr(base, 'img_exists', lambda name: True)
        assert FRRoutingCompiled.require_image('10.1') == 'bgperf/frr_c:10.1'


class TestBuildVars:
    '''Different versions need different build instructions, not just a
    different checkout.
    '''
    def test_defaults_when_nothing_matches(self):
        assert FRRoutingCompiled.build_vars('10.2')['ubuntu_version'] == '22.04'

    def test_series_override_applies(self):
        class Pinned(FRRoutingCompiled):
            VERSION_BUILD_VARS = (('8.', {'ubuntu_version': '20.04'}),)

        assert Pinned.build_vars('8.5')['ubuntu_version'] == '20.04'
        assert Pinned.build_vars('10.2')['ubuntu_version'] == '22.04'

    def test_first_match_wins(self):
        class Pinned(FRRoutingCompiled):
            VERSION_BUILD_VARS = (
                ('10.1', {'configure_extra': '--specific'}),
                ('10', {'configure_extra': '--broad'}),
            )

        assert Pinned.build_vars('10.1')['configure_extra'] == '--specific'
        assert Pinned.build_vars('10.2')['configure_extra'] == '--broad'

    def test_callable_matcher(self):
        class Pinned(FRRoutingCompiled):
            VERSION_BUILD_VARS = ((lambda v: v.startswith('9'), {'ubuntu_version': '18.04'}),)

        assert Pinned.build_vars('9.1')['ubuntu_version'] == '18.04'


class TestRenderDockerfile:
    '''Rendering must not touch Docker -- that is what makes it useful for
    checking a recipe before spending a build on it.
    '''
    def test_ref_reaches_the_checkout(self):
        assert 'git checkout stable/10.2' in FRRoutingCompiled.render_dockerfile('10.2')
        assert 'git checkout v2.19.2' in BIRD.render_dockerfile('2.19.2')

    def test_gobgp_actually_checks_out_the_ref(self):
        '''Its Dockerfile interpolated the ref into a string with no
        placeholder, so every "version" silently built master.
        '''
        assert 'git checkout v3.37.0' in GoBGP.render_dockerfile('3.37.0')

    def test_build_vars_reach_the_recipe(self):
        class Pinned(FRRoutingCompiled):
            VERSION_BUILD_VARS = (('8.', {'ubuntu_version': '20.04'}),)

        assert 'ARG UBUNTU_VERSION=20.04' in Pinned.render_dockerfile('8.0')
        assert 'ARG UBUNTU_VERSION=22.04' in Pinned.render_dockerfile('10.0')

    def test_override_file_wins(self, tmp_path, monkeypatch):
        d = tmp_path / 'dockerfiles' / 'frr_c'
        d.mkdir(parents=True)
        (d / '8.dockerfile').write_text('FROM scratch\n# hand written\n')
        monkeypatch.setattr(base, 'REPO_ROOT', tmp_path)

        # the whole 8.x series resolves to the one file
        assert '# hand written' in FRRoutingCompiled.render_dockerfile('8.0')
        assert '# hand written' in FRRoutingCompiled.render_dockerfile('8.5.1')
        assert '# hand written' not in FRRoutingCompiled.render_dockerfile('10.0')

    def test_more_specific_override_wins(self, tmp_path, monkeypatch):
        d = tmp_path / 'dockerfiles' / 'frr_c'
        d.mkdir(parents=True)
        (d / '10.dockerfile').write_text('FROM scratch\n# series\n')
        (d / '10.1.dockerfile').write_text('FROM scratch\n# exact\n')
        monkeypatch.setattr(base, 'REPO_ROOT', tmp_path)

        assert '# exact' in FRRoutingCompiled.render_dockerfile('10.1')
        assert '# series' in FRRoutingCompiled.render_dockerfile('10.2')

    def test_unversioned_build_ignores_overrides(self, tmp_path, monkeypatch):
        d = tmp_path / 'dockerfiles' / 'frr_c'
        d.mkdir(parents=True)
        (d / '10.dockerfile').write_text('FROM scratch\n# series\n')
        monkeypatch.setattr(base, 'REPO_ROOT', tmp_path)

        assert '# series' not in FRRoutingCompiled.render_dockerfile()


def test_shipped_dockerfile_overrides_are_usable():
    '''Anything under dockerfiles/ has to at least be a Dockerfile.'''
    for path in sorted((REPO_ROOT / 'dockerfiles').rglob('*.dockerfile')):
        text = path.read_text()
        assert 'FROM' in text, f'{path.name}: no FROM statement'
        assert path.parent.name in {'frr_c', 'bird', 'gobgp', 'rustybgp', 'openbgp',
                                    'exabgp', 'exabgp_mrtparse', 'bgpdump2', 'flock'}, \
            f'{path}: parent directory is not an image name'


class TestArgumentGuards:
    '''Combinations that used to build a mislabeled image or die partway.'''

    def _update_args(self, **kw):
        base_args = {'image': 'frr_c', 'version': None, 'versions': None,
                     'checkout': None, 'no_cache': False}
        base_args.update(kw)
        return Namespace(**base_args)

    def test_update_rejects_version_with_all(self):
        '''`update all --version 10.7` tried v10.7 on bird and gobgp and aborted
        on flock, after wasting real builds.
        '''
        with pytest.raises(SystemExit) as e:
            bgperf2.update(self._update_args(image='all', version='10.7'))
        assert 'single image' in str(e.value)

    def test_update_rejects_checkout_with_version(self):
        '''--checkout was silently dropped, shipping an image tagged 10.7 that
        was built from stable/10.7 rather than the requested sha.
        '''
        with pytest.raises(SystemExit) as e:
            bgperf2.update(self._update_args(version='10.7', checkout='1a2b3c4'))
        assert 'mutually exclusive' in str(e.value)

    def test_update_rejects_version_with_versions(self):
        '''--versions silently shadowed --version, so `--version 10.7
        --versions 8.5,9.1` built 8.5 and 9.1 and never mentioned 10.7.
        '''
        with pytest.raises(SystemExit) as e:
            bgperf2.update(self._update_args(version='10.7', versions='8.5,9.1'))
        assert 'redundant' in str(e.value)

    def test_prepare_rejects_versions_across_targets(self):
        '''`-t bird -t frr_c --versions 10.4` would build bgperf/bird:10.4 from
        the nonexistent ref v10.4.
        '''
        with pytest.raises(SystemExit) as e:
            bgperf2.prepare(Namespace(target=['bird', 'frr_c'], versions='10.4',
                                      force=False, no_cache=False))
        assert 'exactly one' in str(e.value)


def test_remove_target_containers_covers_every_target():
    '''Derived from TARGET_CLASSES: a target registered there but missing from
    the removal list leaves its container behind, and the next bench fails on
    the duplicate name.
    '''
    import inspect
    source = inspect.getsource(bgperf2.remove_target_containers)
    assert 'TARGET_CLASSES' in source, 'removal list must derive from TARGET_CLASSES'
    names = {c.CONTAINER_NAME for c in bgperf2.TARGET_CLASSES.values()}
    assert None not in names


class TestRenderDockerfileIsQuiet:
    '''`bgperf2.py dockerfile ... > frr.dockerfile` is the obvious use, so
    nothing may print into the rendered recipe.
    '''

    def test_no_log_line_in_rendered_output(self, capsys):
        text = FRRoutingCompiled.render_dockerfile('8.5')
        captured = capsys.readouterr()
        assert captured.out == '', 'render printed to stdout: {0!r}'.format(captured.out)
        assert 'FRRoutingCompiled:' not in text
        assert text.lstrip().startswith('ARG UBUNTU_VERSION')

    def test_build_version_still_announces(self, capsys, monkeypatch):
        '''Moving the print must not lose it -- builds take 20 minutes and
        need to say what they are doing.
        '''
        monkeypatch.setattr(FRRoutingCompiled, 'build_dockerfile',
                            classmethod(lambda cls, *a, **k: None))
        monkeypatch.setattr(base, 'img_exists', lambda name: True)
        FRRoutingCompiled.build_version('8.5')
        out = capsys.readouterr().out
        assert 'bgperf/frr_c:8.5' in out and 'stable/8.5' in out
