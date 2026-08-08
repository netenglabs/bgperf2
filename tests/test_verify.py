'''Checks behind `bgperf2 verify`.

`verify` starts a container per built image and asks the daemon about itself.
The container half needs Docker and so cannot be tested here; the two pieces of
judgement it depends on are pure, and both are pinned below because both got
this wrong on the first attempt.
'''
import re

import pytest

import bgperf2


class TestVersionMatches:
    '''Does a reported version look like it came from the tag it is filed under?

    This is what catches an image built from the wrong ref, or a repackaged one
    whose upstream tag moved underneath it.
    '''
    @pytest.mark.parametrize('reported,version,ref', [
        # the label appears verbatim in the banner
        ('FRRouting 10.7.0-my-manual-build', '10.7', 'stable/10.7'),
        ('2.19.2', '2.19.2', 'v2.19.2'),
        ('9.2', '9.2', '9.2'),
        # ...and where it does not, the resolved ref does. RustyBGP files
        # builds under a date label but reports the commit.
        ('rustybgpd v0.2.0-0cc685c882', '2026-02', '0cc685c'),
    ])
    def test_a_matching_build_is_accepted(self, reported, version, ref):
        assert bgperf2.version_matches(reported, version, ref) is True

    @pytest.mark.parametrize('reported,version,ref', [
        # the case this exists for: a repackaged image whose base moved, so the
        # tag says one release and the daemon reports another
        ('8.8', '9.2', '9.2'),
        ('FRRouting 10.0.1-my-manual-build', '10.7', 'stable/10.7'),
        ('2.17.1', '2.19.2', 'v2.19.2'),
    ])
    def test_a_mismatched_build_is_rejected(self, reported, version, ref):
        assert bgperf2.version_matches(reported, version, ref) is False

    @pytest.mark.parametrize('reported,version,ref', [
        ('BIRD version 3.13', '3.1', 'v3.1'),
        ('FRRouting 10.10.0', '10.1', 'stable/10.1'),
    ])
    def test_a_longer_version_is_not_a_match(self, reported, version, ref):
        '''A bare substring test makes '3.1' match '3.13', so an image tagged
        3.1 but built from v3.13 would verify clean -- the 10.1-vs-10.10
        confusion BatchLoader exists to prevent, in the one check meant to
        catch a wrong-ref build.
        '''
        assert bgperf2.version_matches(reported, version, ref) is False

    def test_a_more_specific_release_still_matches(self):
        '''FRR's 10.7 branch legitimately reports 10.7.0, so a following '.'
        has to stay acceptable even though a following digit does not.
        '''
        assert bgperf2.version_matches('FRRouting 10.7.0', '10.7', 'stable/10.7') is True


class TestExpectVersionInBanner:
    '''resolve_ref() passes unrecognized values through as raw refs, so a
    branch or sha is a supported --version. Their banners cannot be expected to
    contain the label, and demanding it fails a perfectly good image.
    '''
    def test_a_release_number_is_checked(self):
        assert bgperf2.expect_version_in_banner(bgperf2.BUILDABLE_IMAGES['gobgp'], '3.37.0')

    def test_a_branch_name_is_not_checked(self):
        '''`update gobgp --version master` builds bgperf/gobgp:master, whose
        banner says 3.38.0 and never the word 'master'.
        '''
        assert not bgperf2.expect_version_in_banner(
            bgperf2.BUILDABLE_IMAGES['gobgp'], 'master')

    def test_a_bare_sha_is_not_checked(self):
        assert not bgperf2.expect_version_in_banner(
            bgperf2.BUILDABLE_IMAGES['rustybgp'], '0cc685c')

    def test_a_declared_label_is_checked_even_when_not_numeric(self):
        '''rustybgp files builds under a date, which resolves to a commit the
        banner does carry -- so it is worth checking.
        '''
        assert bgperf2.expect_version_in_banner(
            bgperf2.BUILDABLE_IMAGES['rustybgp'], '2026-02')


class TestGcovPattern:
    '''The signature of a gcov-instrumented binary.

    Both halves were checked against a purpose-built pair inside an image --
    `gcc -fprofile-arcs -ftest-coverage` scores 2, the same source without it
    scores 0 -- because a detector that never fires is worse than no detector.
    '''
    def matches(self, text):
        return re.search(bgperf2.GCOV_PATTERN, text) is not None

    @pytest.mark.parametrize('sample', [
        '__gcov_init',
        '__gcov_merge_add',
        '/root/frr/bgpd/bgp_route.gcda',        # a real path from the FRR log
        '/root/frr/bgpd/bgpd.gcda\x00nextsym',  # as it sits in the binary
    ])
    def test_instrumentation_is_detected(self, sample):
        assert self.matches(sample)

    @pytest.mark.parametrize('sample', [
        # Go's runtime, which a bare '\.gcda' matched -- it reported every
        # gobgp image as gcov-instrumented.
        'runtime.gcdata',
        'time.(*stackObjectRecord).gcdata runtime.scan',
        'runtime.esymtab runtime.gcdata runtime.egcd',
        'bgp_route.c',
        '',
    ])
    def test_clean_binaries_are_not_flagged(self, sample):
        assert not self.matches(sample)


class TestProbeUsesTheClassBenchUses:
    def test_target_classes_are_preferred_over_daemon_bases(self):
        '''rustybgp's version parser was wrong only through RustyBGPTarget's
        MRO and correct when the daemon base was asked directly, so probing the
        base class would have missed it entirely.
        '''
        for name in ('rustybgp', 'bird', 'gobgp', 'openbgp', 'frr_c'):
            assert name in bgperf2.TARGET_CLASSES

    def test_frr_declares_that_its_version_needs_a_daemon(self):
        '''vtysh reaches bgpd over a socket, so a bare container reports
        "Exiting: failed to connect to any daemons." -- which would read as a
        broken image rather than an unprobeable one.
        '''
        assert bgperf2.TARGET_CLASSES['frr_c'].VERSION_NEEDS_DAEMON is True

    @pytest.mark.parametrize('name', ['rustybgp', 'bird', 'gobgp', 'openbgp', 'frr_c'])
    def test_daemons_declare_the_binary_under_test(self, name):
        assert bgperf2.TARGET_CLASSES[name].DAEMON_BINARY

    @pytest.mark.parametrize('name', ['exabgp', 'exabgp_mrtparse', 'bgpdump2'])
    def test_tester_only_images_are_probed_as_testers(self, name):
        '''These have no TARGET_CLASSES entry, so without TESTER_CLASSES they
        would be probed through the daemon base class -- the same blind spot
        that hid the rustybgp bug, since bench builds ExaBGPTester(Tester,
        ExaBGP), not ExaBGP.
        '''
        cls = bgperf2.TESTER_CLASSES[name]
        assert cls is not bgperf2.BUILDABLE_IMAGES[name]
        assert issubclass(cls, bgperf2.BUILDABLE_IMAGES[name])

    def test_images_that_are_both_roles_are_probed_as_both(self):
        '''bird and gobgp run as target and as load generator, and the two have
        different MROs.
        '''
        for name in ('bird', 'gobgp'):
            assert bgperf2.TARGET_CLASSES[name] is not bgperf2.TESTER_CLASSES[name]
