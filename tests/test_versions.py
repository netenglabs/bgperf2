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
from openbgp import OpenBGP
from rustybgp import RustyBGP


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

    @pytest.mark.parametrize('version,ref', [
        ('2026-02', '0cc685c'),   # date labels map onto the commit they name
        ('master', 'master'),     # raw refs still pass through
        ('16cc827', '16cc827'),
    ])
    def test_rustybgp(self, version, ref):
        '''RustyBGP has never cut a release, so versions are date labels.'''
        assert RustyBGP.resolve_ref(version) == ref

    def test_rustybgp_default(self):
        assert RustyBGP.resolve_ref(None) == 'master'

    @pytest.mark.parametrize('spelling', [
        '0cc685c',      # the abbreviation written in VERSION_BUILD_VARS
        '0cc685c882',   # what `rustybgpd --version` actually prints
        '0cc685',       # a shorter abbreviation than the one written here
    ])
    def test_rustybgp_sha_gets_the_same_recipe_as_its_label(self, spelling):
        '''A version is matched as typed, not as resolved, so naming a commit by
        sha has to reach its own build overrides. The abbreviation a user has in
        hand is the one the daemon printed (v0.2.0-0cc685c882), so matching the
        exact 7 characters written here would miss it and silently bundle a v4.7
        gobgp CLI with a daemon serving the v4.0 API.
        '''
        assert (RustyBGP.build_vars(spelling)['gobgp_version']
                == RustyBGP.build_vars('2026-02')['gobgp_version'])

    @pytest.mark.parametrize('spelling', ['master', '0', '16cc827', ''])
    def test_rustybgp_other_refs_keep_the_default_recipe(self, spelling):
        '''A too-short or unrelated ref must not claim the pinned commit.'''
        assert (RustyBGP.build_vars(spelling)['gobgp_version']
                == RustyBGP.BUILD_VARS['gobgp_version'])

    def test_rustybgp_builder_and_runtime_glibc_match(self):
        '''A trixie builder with a bookworm runtime builds fine and then dies at
        startup with "GLIBC_2.xx not found" -- a bench that will not come up
        rather than a build error.
        '''
        for v in (None, '2026-02'):
            build = RustyBGP.build_vars(v)
            assert build['base_image'].endswith('-bookworm')
            assert build['runtime_image'] == 'debian:bookworm'


class TestOpenBGP:
    '''OpenBGPD is repackaged, not compiled, so a version is an upstream Docker
    tag and the inherited passthrough resolve_ref() is already right.
    '''
    @pytest.mark.parametrize('version,ref', [
        ('9.2', '9.2'),
        ('8.8', '8.8'),
        ('7.3', '7.3'),   # any upstream tag works, not only the prebuilt ones
    ])
    def test_versions_are_upstream_docker_tags(self, version, ref):
        assert OpenBGP.resolve_ref(version) == ref

    def test_default_is_latest(self):
        assert OpenBGP.resolve_ref(None) == 'latest'

    def test_the_moving_tag_is_re_pulled(self):
        '''The FROM image IS the daemon under test here, so a cached copy makes
        the unversioned tag stop tracking upstream silently. A local
        openbgpd/openbgpd:latest pulled in 2025-02 kept bgperf/openbgp:latest
        at 8.8 for months after 9.2 shipped, and nothing looked wrong -- the
        run just recorded a version nobody asked for.
        '''
        assert OpenBGP.pulls_base(OpenBGP.image_tag()) is True

    @pytest.mark.parametrize('version', ['8.8', '9.2'])
    def test_pinned_versions_are_not_re_pulled(self, version):
        '''`FROM openbgpd/openbgpd:9.2` is immutable, so a pull cannot find
        anything new -- and it is fatal when the registry is unreachable even
        though the image is already local, which would break an offline
        `prepare -t openbgp` that used to work straight from cache.
        '''
        assert OpenBGP.pulls_base(OpenBGP.image_tag(version)) is False

    def test_a_bare_repo_name_still_counts_as_the_moving_tag(self):
        '''Every daemon's __init__ defaults to the bare repo name, so it is the
        easy thing to pass -- and comparing it un-normalized against
        'bgperf/openbgp:latest' would skip the re-pull silently.
        '''
        assert OpenBGP.pulls_base('bgperf/openbgp') is True

    def test_pulling_is_off_by_default(self):
        '''Compiled daemons only use their base image as a toolchain, so
        re-pulling it every build costs time and buys nothing.
        '''
        assert base.Container.PULL_BASE is False
        assert BIRD.pulls_base(BIRD.image_tag()) is False

    def test_the_upstream_entrypoint_is_neutralized(self):
        '''openbgpd/openbgpd runs `multirun bgpd ...` as its entrypoint, so
        bgpd came up on the image's own config before bgperf could act and
        start.sh then died with "cannot bind to 0.0.0.0:179: Address in use".
        The target never peered and the run hung waiting for the monitor.
        '''
        recipe = OpenBGP.render_dockerfile(version='9.2')
        assert 'ENTRYPOINT []' in recipe


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
