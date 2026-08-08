'''Recording which build produced a result.

A benchmark number is only reproducible if you can tell which daemon builds
made it -- and not just the target's: the testers generate the load and the
monitor is the instrument every timing is read from. These tests pin that all
three are collected, that a daemon which cannot report a version says so
loudly rather than recording a plausible-looking guess, and that the extra
columns land at the end of the stats row where they cannot shift the graphs.
'''
import json
from argparse import Namespace

import pytest

import base
import bgperf2


class FakeContainer:
    '''Stands in for a running container: version_string() is what gets read.'''
    def __init__(self, image, version):
        self.image = image
        self._version = version

    def version_string(self):
        return self._version


@pytest.fixture
def prov_args():
    return Namespace(target='frr_c', label=None, neighbor_num=10,
                     prefix_num=20000, tester_type='bird', single_table=False,
                     filter_test=None, results_dir=None)


def collect(args, testers):
    return bgperf2.collect_provenance(
        args,
        FakeContainer('bgperf/frr_c:10.7', 'FRRouting 10.7.0 (fa49f0ddc9c8)'),
        FakeContainer('bgperf/gobgp', '3.37.0'),
        testers)


class TestCollectProvenance:
    def test_records_target_monitor_and_testers(self, prov_args):
        p = collect(prov_args, [FakeContainer('bgperf/bird:2.19.2', '2.19.2')])

        assert p['target'] == {'daemon': 'frr_c', 'image': 'bgperf/frr_c:10.7',
                               'version': 'FRRouting 10.7.0 (fa49f0ddc9c8)'}
        # the monitor is the measurement instrument, so its build matters too
        assert p['monitor']['version'] == '3.37.0'
        assert p['testers'][0]['version'] == '2.19.2'

    def test_image_names_are_normalized(self, prov_args):
        '''bgperf/gobgp and bgperf/gobgp:latest are the same image.'''
        p = collect(prov_args, [])
        assert p['monitor']['image'] == 'bgperf/gobgp:latest'

    def test_one_entry_per_image_with_a_count(self, prov_args):
        '''A run can be a hundred testers off one image; exec into one, not all.'''
        testers = [FakeContainer('bgperf/bird:2.19.2', '2.19.2') for _ in range(50)]
        p = collect(prov_args, testers)

        assert len(p['testers']) == 1
        assert p['testers'][0]['count'] == 50

    def test_mixed_tester_images_are_kept_apart(self, prov_args):
        testers = ([FakeContainer('bgperf/bird:2.19.2', '2.19.2')] * 2
                   + [FakeContainer('bgperf/exabgp', '4.2')])
        p = collect(prov_args, testers)

        assert {t['image'] for t in p['testers']} == {
            'bgperf/bird:2.19.2', 'bgperf/exabgp:latest'}


class TestVersionString:
    '''version_string() must never invent a version it did not read.'''
    def _container(self, exec_result):
        c = base.Container.__new__(base.Container)

        def exec_version_cmd():
            if isinstance(exec_result, Exception):
                raise exec_result
            return exec_result
        c.exec_version_cmd = exec_version_cmd
        return c

    def test_reports_what_the_daemon_said(self):
        assert self._container(' 2.19.2\n').version_string() == '2.19.2'

    def test_missing_version_command_is_explicit(self):
        c = self._container(NotImplementedError())
        assert c.version_string().startswith(base.VERSION_UNKNOWN)

    def test_unparseable_output_is_explicit(self):
        c = self._container(base.VersionUnavailable("got 'exec'"))
        v = c.version_string()
        assert v.startswith(base.VERSION_UNKNOWN)
        assert 'exec' in v

    def test_empty_output_is_explicit(self):
        assert self._container('  \n').version_string().startswith(base.VERSION_UNKNOWN)

    def test_commas_cannot_shift_the_csv(self):
        '''Rows are ','.join()ed with no quoting, so a comma in a version would
        silently move every column after it.
        '''
        assert ',' not in self._container('BIRD, version 2').version_string()

    def test_commas_in_the_failure_text_cannot_shift_the_csv(self):
        '''The failure path is where arbitrary text actually enters -- it is a
        stringified exception, not daemon output -- so it needs the sanitizing
        more than the success path, not less. A docker socket hiccup carries
        two commas, which used to shift every later column by two.
        '''
        e = OSError("('Connection aborted.', RemoteDisconnected('closed'))")
        v = self._container(e).version_string()
        assert v.startswith(base.VERSION_UNKNOWN)
        assert ',' not in v

    def test_newlines_cannot_split_a_row(self):
        '''A multi-line banner would otherwise write one row across two lines.'''
        v = self._container('OpenBGPD 8.8\nsecond line').version_string()
        assert '\n' not in v and v == 'OpenBGPD 8.8 second line'


class TestVersionParsers:
    '''Every parser must reject text it does not recognise.

    A version command can succeed at the process level and still print
    something that is not a version -- vtysh prints 'Exiting: failed to connect
    to any daemons.' before bgpd answers, and bgperf polls before it is up.
    Parsers that took a fixed word or the first line recorded that verbatim,
    which is how the word 'exec' became a BIRD version in the published
    baseline. version_string() cannot rescue this: nothing raised.

    The good-output samples below were all captured from the real images.
    '''
    def _parse(self, monkeypatch, cls, output):
        # **kwargs: some daemons ask the base method for stderr, because their
        # banner is printed there and nowhere else.
        monkeypatch.setattr(base.Container, 'exec_version_cmd',
                            lambda self, **kw: output)
        obj = cls.__new__(cls)
        obj.name = 'test'
        return cls.exec_version_cmd(obj)

    @pytest.mark.parametrize('cls_name,good,expected', [
        ('frr.FRRoutingTarget',
         'FRRouting 10.7.0-my-manual-build (53edf60de771) on Linux(7.0.0-28-generic).\n'
         'Copyright 1996-2005 Kunihiro Ishiguro, et al.',
         'FRRouting 10.7.0-my-manual-build'),
        ('openbgp.OpenBGP', 'OpenBGPD 8.8', '8.8'),
    ])
    def test_good_output_parses(self, monkeypatch, cls_name, good, expected):
        mod, name = cls_name.split('.')
        cls = getattr(__import__(mod), name)
        assert self._parse(monkeypatch, cls, good) == expected

    @pytest.mark.parametrize('cls_name,bad', [
        # what vtysh really prints before bgpd is answering
        ('frr.FRRoutingTarget', 'Exiting: failed to connect to any daemons.'),
        ('openbgp.OpenBGP', "exec: '/usr/local/sbin/bgpctl': no such file"),
        ('openbgp.OpenBGP', ''),
    ])
    def test_unrecognized_output_raises(self, monkeypatch, cls_name, bad):
        mod, name = cls_name.split('.')
        cls = getattr(__import__(mod), name)
        with pytest.raises(base.VersionUnavailable):
            self._parse(monkeypatch, cls, bad)

    @pytest.mark.parametrize('cls_name,output,expected', [
        # The mixin targets are the ones that can pick up a sibling daemon's
        # parser, so assert against the classes bench actually instantiates.
        ('rustybgp.RustyBGPTarget', 'rustybgpd v0.2.0-16cc82756a',
         'rustybgpd v0.2.0-16cc82756a'),
        ('bird.BIRDTarget', 'BIRD version 2.19.2', '2.19.2'),
        ('gobgp.GoBGPTarget', 'gobgpd version 3.37.0', '3.37.0'),
    ])
    def test_target_classes_use_their_own_parser(self, monkeypatch, cls_name,
                                                 output, expected):
        '''RustyBGPTarget reuses GoBGP's config writer, so its MRO is
        RustyBGP -> GoBGPTarget -> GoBGP -> Container. A super() call from
        RustyBGP.exec_version_cmd lands on GoBGP's parser, which rejects
        rustybgpd's banner and records UNKNOWN for every rustybgp run. Testing
        RustyBGP on its own cannot catch that -- GoBGP is not in its MRO -- so
        this goes through the class bench really builds.
        '''
        mod, name = cls_name.split('.')
        cls = getattr(__import__(mod), name)
        assert self._parse(monkeypatch, cls, output) == expected

    def test_a_rejecting_parser_becomes_an_explicit_unknown(self, monkeypatch):
        '''The raise has to surface as UNKNOWN in the results, not a crash.'''
        import frr
        monkeypatch.setattr(base.Container, 'exec_version_cmd',
                            lambda self, **kw: 'Exiting: failed to connect to any daemons.')
        obj = frr.FRRoutingTarget.__new__(frr.FRRoutingTarget)
        obj.name = 'test'
        assert obj.version_string().startswith(base.VERSION_UNKNOWN)


class TestProvenanceColumns:
    def test_appended_at_the_end(self, bench_args, bench_stats, prov_args):
        '''create_batch_graphs() indexes the row positionally, so provenance has
        to sit after every column a graph refers to.
        '''
        header = [f.strip() for f in bgperf2.stats_header().split(',')]
        p = collect(prov_args, [FakeContainer('bgperf/bird:2.19.2', '2.19.2')])
        row = bgperf2.create_output_stats(bench_args, 'v1', bench_stats, provenance=p)

        assert header[-3:] == ['target image', 'tester version', 'monitor version']
        assert len(header) == len(row)
        named = dict(zip(header, row))
        assert named['target image'] == 'bgperf/frr_c:10.7'
        assert named['tester version'] == '2.19.2'
        assert named['monitor version'] == '3.37.0'

    def test_row_still_matches_header_without_provenance(self, bench_args, bench_stats):
        '''bench() always supplies it, but the row must not depend on that.'''
        header = [f.strip() for f in bgperf2.stats_header().split(',')]
        row = bgperf2.create_output_stats(bench_args, 'v1', bench_stats)
        assert len(header) == len(row)


class TestWriteProvenance:
    def test_writes_a_manifest_next_to_the_results(self, tmp_path, prov_args):
        prov_args.results_dir = str(tmp_path)
        p = collect(prov_args, [FakeContainer('bgperf/bird:2.19.2', '2.19.2')])

        path = bgperf2.write_provenance(prov_args, p, 'frr_c_bird_20000_10')
        doc = json.loads(open(path).read())

        assert doc['target']['image'] == 'bgperf/frr_c:10.7'
        assert doc['monitor']['version'] == '3.37.0'
        assert doc['testers'][0]['count'] == 1
        # the manifest has to say which run it describes, or it is unattachable
        assert doc['run']['peers'] == 10
        assert doc['run']['prefixes_per_peer'] == 20000
        assert doc['run']['tester_type'] == 'bird'
