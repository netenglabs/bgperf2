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
import findings
import measurements


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
        # Captured from bgperf/bgpdump2:latest. The commit is not decoration:
        # bgpdump2 has reported 2.0.14 for every master build this project has
        # made, so the version on its own cannot tell two images apart.
        ('bgpdump2.Bgpdump2Tester', 'Version: 2.0.14\ncommit: a019184\n',
         '2.0.14 (a019184)'),
    ])
    def test_good_output_parses(self, monkeypatch, cls_name, good, expected):
        mod, name = cls_name.split('.')
        cls = getattr(__import__(mod), name)
        assert self._parse(monkeypatch, cls, good) == expected

    # Every daemon that parses a banner, not a sample of them: the raise path
    # is code that only ever runs when something is already wrong, so a typo in
    # it survives indefinitely. Leaving bird out of this list is what let a
    # NameError sit in its raise, turning the diagnostic into
    # "UNKNOWN (name 'version' is not defined)" -- version_string()'s bare
    # `except Exception` catches it, so nothing crashes and nothing says what
    # the daemon actually printed.
    @pytest.mark.parametrize('cls_name,bad', [
        # what vtysh really prints before bgpd is answering
        ('frr.FRRoutingTarget', 'Exiting: failed to connect to any daemons.'),
        ('bird.BIRDTarget', "exec: 'bird': executable file not found in $PATH"),
        ('bird.BIRDTarget', ''),
        ('gobgp.GoBGPTarget', 'exec failed'),
        ('rustybgp.RustyBGPTarget', 'exec failed'),
        ('openbgp.OpenBGP', "exec: '/usr/local/sbin/bgpctl': no such file"),
        ('openbgp.OpenBGP', ''),
        # The version command is two commands in one shell, so a missing binary
        # still produces the second half's output. A parser reading the first
        # line, or accepting whatever it got, would record 'commit:' as a
        # bgpdump2 version.
        ('bgpdump2.Bgpdump2Tester',
         "sh: 1: /usr/local/sbin/bgpdump2: not found\ncommit: a019184"),
        ('bgpdump2.Bgpdump2Tester', 'commit:'),
        ('bgpdump2.Bgpdump2Tester', ''),
    ])
    def test_unrecognized_output_raises(self, monkeypatch, cls_name, bad):
        mod, name = cls_name.split('.')
        cls = getattr(__import__(mod), name)
        with pytest.raises(base.VersionUnavailable):
            self._parse(monkeypatch, cls, bad)

    # The fragment is a distinctive TAIL of each message on purpose. Matching
    # the first token ('exec', 'Exiting') would pass just as happily for a
    # parser that truncated the daemon's output to its first word, which is
    # the opposite of what this is asserting.
    @pytest.mark.parametrize('cls_name,bad,fragment', [
        ('frr.FRRoutingTarget', 'Exiting: failed to connect to any daemons.',
         'any daemons'),
        ('bird.BIRDTarget', "exec: 'bird': executable file not found in $PATH",
         'not found in $PATH'),
        ('gobgp.GoBGPTarget', 'gobgpd: command not found', 'command not found'),
        ('rustybgp.RustyBGPTarget', 'no such file or directory',
         'such file or directory'),
        ('openbgp.OpenBGP', "exec: '/usr/local/sbin/bgpctl': no such file",
         '/usr/local/sbin/bgpctl'),
        ('bgpdump2.Bgpdump2Tester',
         "sh: 1: /usr/local/sbin/bgpdump2: not found", 'bgpdump2: not found'),
    ])
    def test_the_rejected_output_survives_into_the_message(self, monkeypatch,
                                                           cls_name, bad,
                                                           fragment):
        '''The point of raising is to say what the daemon really printed, so
        assert that text reaches the recorded string rather than only that
        something was raised -- a broken raise still raises.
        '''
        mod, name = cls_name.split('.')
        cls = getattr(__import__(mod), name)
        obj = cls.__new__(cls)
        obj.name = 'test'
        monkeypatch.setattr(base.Container, 'exec_version_cmd',
                            lambda self, **kw: bad)

        recorded = obj.version_string()
        assert recorded.startswith(base.VERSION_UNKNOWN)
        assert fragment in recorded

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

    @pytest.mark.parametrize('commit,expected', [
        ('a019184', '2.0.14 (a019184)'),
        ('0123456789abcdef0123456789abcdef01234567',
         '2.0.14 (0123456789abcdef0123456789abcdef01234567)'),
    ])
    def test_the_bgpdump2_build_is_named_beside_its_version(self, monkeypatch,
                                                            commit, expected):
        '''bgpdump2 is built from master and its banner never moves, so the
        commit is the only thing that separates two images. Recording the
        version alone would repeat the gcov trap one layer up: a cached image
        carrying an older build, with nothing in the results to show it.
        '''
        import bgpdump2
        assert self._parse(monkeypatch, bgpdump2.Bgpdump2Tester,
                           'Version: 2.0.14\ncommit: {0}\n'.format(commit)) \
            == expected

    def test_a_bgpdump2_image_with_no_clone_says_so(self, monkeypatch):
        '''The commit is read from the clone the image still carries, so an
        image built without one -- or with it pruned -- has to report a version
        it cannot pin rather than one that looks pinned.
        '''
        import bgpdump2
        parsed = self._parse(monkeypatch, bgpdump2.Bgpdump2Tester,
                             'Version: 2.0.14\ncommit:\n')
        assert parsed == '2.0.14 (commit unknown)'

    def test_bgpdump2_is_parsed_through_the_class_bench_builds(self):
        '''Bgpdump2Tester's MRO is Tester -> Bgpdump2 -> MRTTester ->
        Container, and only the middle one defines a version parser. This is
        the shape that hid the rustybgp bug, where the parser was correct on
        the base class and wrong through the class bench instantiates.
        '''
        import bgpdump2
        assert bgpdump2.Bgpdump2Tester.exec_version_cmd \
            is bgpdump2.Bgpdump2.exec_version_cmd

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


class FakeGit:
    '''Stands in for the git commands `tool_revision()` runs.

    Injected rather than run for real, because a test that reads the tree it
    happens to run in passes or fails on whether someone has edited a file.
    '''
    class Result:
        def __init__(self, returncode=0, stdout='', stderr=''):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def __init__(self, head, status=None):
        self.head = head
        self.status = status if status is not None else self.Result()

    def __call__(self, *argv):
        return self.head if argv[0] == 'rev-parse' else self.status


class TestToolRevision:
    '''Which bgperf2 produced a result, recorded the way a daemon version is.

    The daemon versions say what was benchmarked and nothing about the code
    that timed it, and the timing code is what the measurement plan changed
    under those daemons. The rule is the one `version_string()` already
    follows: report what was read, or say why it could not be -- never a value
    that looks right and is not.
    '''
    def test_a_clean_tree_is_the_bare_revision(self):
        git = FakeGit(FakeGit.Result(stdout='abc123\n'))
        assert bgperf2.tool_revision(git) == 'abc123'

    def test_an_edited_tree_says_so(self):
        # The nearest commit does not contain the code that ran, and a row
        # traced to it is worse than one that says it cannot be traced.
        git = FakeGit(FakeGit.Result(stdout='abc123\n'),
                      FakeGit.Result(stdout=' M bgperf2.py\n'))
        assert bgperf2.tool_revision(git) == 'abc123-dirty'

    def test_no_git_is_reported_not_guessed(self):
        git = FakeGit(FakeGit.Result(returncode=128,
                                     stderr='not a git repository'))
        revision = bgperf2.tool_revision(git)
        assert revision.startswith('UNKNOWN')
        assert 'not a git repository' in revision

    def test_an_empty_answer_is_not_a_revision(self):
        git = FakeGit(FakeGit.Result(stdout='\n'))
        assert bgperf2.tool_revision(git).startswith('UNKNOWN')

    def test_an_unreadable_worktree_never_reports_a_clean_tree(self):
        # The commit is known and its cleanliness is not. Publishing the bare
        # sha would assert clean on the strength of a check that failed.
        git = FakeGit(FakeGit.Result(stdout='abc123\n'),
                      FakeGit.Result(returncode=1, stderr='index locked'))
        revision = bgperf2.tool_revision(git)
        assert revision != 'abc123'
        assert 'abc123' in revision and 'index locked' in revision

    def test_a_raising_git_costs_the_revision_not_the_run(self):
        def boom(*argv):
            raise OSError('no git binary')

        revision = bgperf2.tool_revision(boom)
        assert revision.startswith('UNKNOWN')
        assert 'no git binary' in revision

    def test_the_block_names_the_schemas_the_run_wrote(self):
        block = bgperf2.tool_provenance()
        assert block['event_schema'] == measurements.EVENT_ARTIFACT_SCHEMA
        assert block['findings_schema'] == findings.FINDINGS_SCHEMA
        assert block['findings_policy'] == findings.POLICY_VERSION
        assert block['revision']

    def test_the_manifest_records_which_bgperf2_measured_the_run(
            self, tmp_path, prov_args):
        prov_args.results_dir = str(tmp_path)
        p = collect(prov_args, [FakeContainer('bgperf/bird:2.19.2', '2.19.2')])

        path = bgperf2.write_provenance(prov_args, p, 'frr_c_bird_20000_10')
        doc = json.loads(open(path).read())

        assert doc['bgperf2']['findings_policy'] == findings.POLICY_VERSION
        assert doc['bgperf2']['revision']

    def test_the_event_artifact_records_it_too(self, tmp_path):
        '''Both documents, on the rule both `run` blocks already follow: the
        events artifact is what findings.py reads and what a summary groups
        by, so a reader holding only that one must still be able to say which
        build wrote it.
        '''
        args = Namespace(target='bird', label=None, version=None,
                         tester_type='bird', prefix_num=100, neighbor_num=10,
                         filter_test=None, path_diversity=1, receivers=0,
                         churn_prefixes=0, churn_bursts=0, repetition=None,
                         policy_reload_blocks=0, file=None,
                         results_dir=str(tmp_path))
        doc = bgperf2.write_event_artifact(args, [], 'stem', 'converged')
        assert doc['bgperf2']['revision']
        assert doc['bgperf2']['event_schema'] == doc['schema']
        assert doc['bgperf2']['findings_policy'] == \
            doc['findings']['policy_version']

    def test_a_raising_status_keeps_the_revision(self):
        '''The commit is already known by then. A `git status` that times out
        on a loaded host must not report the run as having no traceable build
        -- at startup that would stamp every cell of a matrix with UNKNOWN.
        '''
        class Raises(FakeGit):
            def __call__(self, *argv):
                if argv[0] == 'rev-parse':
                    return self.head
                raise TimeoutError('timed out')

        revision = bgperf2.tool_revision(Raises(FakeGit.Result(
            stdout='abc123\n')))
        assert not revision.startswith('UNKNOWN')
        assert 'abc123' in revision and 'timed out' in revision

    def test_an_untracked_file_is_not_an_edit_to_the_code(self):
        '''`bd` rewrites .beads/issues.jsonl on any issue activity and it is
        neither tracked nor ignored here, so counting untracked files would
        mark nearly every run dirty and empty the flag of its meaning.
        '''
        seen = []

        class Recording(FakeGit):
            def __call__(self, *argv):
                seen.append(argv)
                return super().__call__(*argv)

        Recording(FakeGit.Result(stdout='abc123\n'))('rev-parse', 'HEAD')
        bgperf2.tool_revision(Recording(FakeGit.Result(stdout='abc123\n')))
        assert any('--untracked-files=no' in a for a in seen)
