"""The lines behind a nonzero tester error count must outlive the work directory.

`check_timing_evidence.py` rejects a row on any nonzero tester error or timeout
count, and `bench()` rmtree's the work directory at the start of the next cell.
Until the capture existed, the count was the whole of what survived, so a
rejection could not be diagnosed and could not be re-measured toward an answer
-- a re-run wipes the logs identically. Block 4 of the 64 GB timing campaign
lost two rows that way.

These are pure: no Docker, no privileges, one tmp_path of fake logs.
"""
import ast
import json
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import base
import bgperf2
from tester import BIRDTester


def write_log(d, name, lines):
    p = os.path.join(str(d), name)
    with open(p, 'w') as f:
        f.write('\n'.join(lines) + '\n')
    return p


class TestCountsAreUnchanged:
    """The capture must not move the number it is explaining."""

    def test_bird_count_ignores_the_excluded_classes(self, tmp_path):
        write_log(tmp_path, 'a.log', [
            '<RMT> Invalid route 10.0.0.0/8 withdrawn',
            '<RMT> Bad NEXT_HOP attribute',
            '<RMT> Received: Cease',
            '<INFO> Started',
        ])
        assert BIRDTester.find_errors([str(tmp_path)]) == 1

    def test_capture_does_not_change_the_count(self, tmp_path):
        write_log(tmp_path, 'a.log', ['<RMT> Received: Cease'] * 3)
        samples = []
        assert BIRDTester.find_errors([str(tmp_path)], samples) == 3
        assert BIRDTester.find_errors([str(tmp_path)]) == 3
        assert len(samples) == 3

    def test_default_captures_nothing(self, tmp_path):
        """Every caller that predates this walks the logs exactly as it did."""
        write_log(tmp_path, 'a.log', ['<RMT> Received: Cease'])
        assert BIRDTester.find_errors([str(tmp_path)]) == 1


class TestAPartialFinalLine:
    """A log's last line can be half a line, and half a line is not evidence.

    Every one of these scans runs while the generator container is up and its
    daemon is still writing. `bird 3.3.2 (4 threads)` at 500 peers x 2000
    prefixes was rejected on `tester_health` in Block 8 of the 64 GB campaign
    for exactly one error. Its `tester-health.json` captured the line verbatim
    as `2026-09-12 01:51:01.260 <RMT> bgp1: Invalid ro`, at `10.10.0.241.log`
    line 709953 -- a copy of the commonest line in the log, cut inside `Invalid
    route` so the exclusion could no longer match it while `<RMT>` still put it
    in front of the predicate. The run had converged with exact counts.

    `test_a_truncated_exclusion_is_not_an_error` feeds that exact text.
    """

    def write_partial(self, d, name, lines, tail):
        """A log ending mid-line: no trailing newline after `tail`."""
        p = os.path.join(str(d), name)
        with open(p, 'w') as f:
            f.write(''.join(line + '\n' for line in lines))
            f.write(tail)
        return p

    def test_a_truncated_exclusion_is_not_an_error(self, tmp_path):
        """The Block 8 rejection, reproduced and then refused."""
        self.write_partial(tmp_path, '10.10.0.241.log',
                           ['<RMT> bgp1: Invalid route 10.0.0.0/8 withdrawn'] * 3,
                           '2026-09-12 01:51:01.260 <RMT> bgp1: Invalid ro')
        assert BIRDTester.find_errors([str(tmp_path)]) == 0

    def test_a_partial_line_is_not_captured_either(self, tmp_path):
        """Not counted and not sampled: `count` and `sampled` stay agreed."""
        samples = []
        self.write_partial(tmp_path, 'a.log', [], '<RMT>  bgp1: Invalid ro')
        assert BIRDTester.find_errors([str(tmp_path)], samples) == 0
        assert samples == []

    def test_complete_lines_before_it_still_count(self, tmp_path):
        """Only the partial line is withheld, not the log that carried it."""
        self.write_partial(tmp_path, 'a.log',
                           ['<RMT> Received: Cease'] * 2,
                           '<RMT>  bgp1: Invalid ro')
        assert BIRDTester.find_errors([str(tmp_path)]) == 2

    def test_the_next_log_is_still_read(self, tmp_path):
        """A partial line ends one log's scan, not the walk over the fleet."""
        a = tmp_path / 'a'
        a.mkdir()
        self.write_partial(a, '1.log', [], '<RMT>  bgp1: Invalid ro')
        write_log(a, '2.log', ['<RMT> Received: Cease'])
        assert BIRDTester.find_errors([str(a)]) == 1

    def test_the_mrt_scans_follow_the_same_rule(self, tmp_path):
        """`count_matching_lines()` feeds every MRT tester's two counts."""
        self.write_partial(tmp_path, 'bgpdump2.log',
                           ['session timeout'], 'partial error')
        assert base.count_matching_lines([str(tmp_path)], 'error') == 0
        assert base.count_matching_lines([str(tmp_path)], 'timeout') == 1


class TestWhatIsCaptured:
    def test_the_line_its_file_and_its_number_survive(self, tmp_path):
        write_log(tmp_path, '10.10.0.7.log', [
            '<INFO> Started',
            '<RMT> Received: Cease (administrative shutdown)',
        ])
        samples = []
        BIRDTester.find_errors([str(tmp_path)], samples)
        assert len(samples) == 1
        s = samples[0]
        assert s['log'] == '10.10.0.7.log'
        assert s['source'] == os.path.basename(str(tmp_path))
        assert s['line'] == 2
        assert 'Cease' in s['text']
        assert s['truncated'] is False

    def test_a_long_line_is_trimmed_and_says_so(self, tmp_path):
        long = '<RMT> Received: ' + 'x' * 5000
        write_log(tmp_path, 'a.log', [long])
        samples = []
        BIRDTester.find_errors([str(tmp_path)], samples)
        assert samples[0]['truncated'] is True
        assert len(samples[0]['text']) == base.ERROR_SAMPLE_LINE_CHARS

    def test_capture_is_capped_while_the_count_is_not(self, tmp_path):
        """A capture that kept every match could outweigh the run it describes."""
        n = base.ERROR_SAMPLE_LIMIT * 3
        for i in range(base.ERROR_SAMPLE_LIMIT):
            write_log(tmp_path, 'p{0}.log'.format(i),
                      ['<RMT> Received: Cease'] * n)
        samples = []
        total = BIRDTester.find_errors([str(tmp_path)], samples)
        assert total == n * base.ERROR_SAMPLE_LIMIT
        assert len(samples) == base.ERROR_SAMPLE_LIMIT

    def test_one_noisy_session_cannot_spend_the_whole_budget(self, tmp_path):
        """A global cap alone is spent in glob order, leaving the rest of the
        fleet unrepresented while the capture still looks complete."""
        write_log(tmp_path, 'aaa.log', ['<RMT> Received: Cease'] * 500)
        write_log(tmp_path, 'bbb.log', ['<RMT> Received: Hold timer expired'])
        samples = []
        BIRDTester.find_errors([str(tmp_path)], samples)
        assert len(samples) == base.ERROR_SAMPLE_PER_LOG + 1
        assert {s['log'] for s in samples} == {'aaa.log', 'bbb.log'}

    def test_two_testers_sharing_a_log_name_stay_distinguishable(self, tmp_path):
        """Every MRT injector writes `bgpdump2.log` in its own host dir."""
        a = tmp_path / 'tester0'
        b = tmp_path / 'tester1'
        a.mkdir()
        b.mkdir()
        write_log(a, 'bgpdump2.log', ['<RMT> Received: Cease'])
        write_log(b, 'bgpdump2.log', ['<RMT> Received: Cease'])
        samples = []
        assert BIRDTester.find_errors([str(a), str(b)], samples) == 2
        assert {s['source'] for s in samples} == {'tester0', 'tester1'}

    def test_an_unreadable_log_still_does_not_raise(self, tmp_path):
        d = tmp_path / 'sub'
        d.mkdir()
        p = write_log(d, 'a.log', ['<RMT> Received: Cease'])
        os.chmod(p, 0)
        try:
            samples = []
            BIRDTester.find_errors([str(d)], samples)
        finally:
            os.chmod(p, 0o600)


class TestEveryTesterCanBeAsked:
    """A tester type whose implementation was missed would capture nothing
    while its count stayed nonzero -- the same silent gap one level down.

    Iterated over `TESTER_CLASSES`, the table `bench()` actually builds testers
    from, rather than over `dir(module)`. `dir()` re-finds the inherited
    `base.Tester` stubs in every module, so deleting a real override still left
    the count comfortably over any threshold -- and an inherited stub satisfies
    a signature check anyway. The same reason `verify` probes through
    `TESTER_CLASSES` and never the daemon base class.
    """

    def _resolved(self, cls, meth):
        fn = None
        for klass in cls.__mro__:
            if meth in klass.__dict__:
                fn = klass.__dict__[meth]
                break
        assert fn is not None, '{0}.{1} unresolvable'.format(cls.__name__, meth)
        raw = fn.__func__ if isinstance(fn, staticmethod) else fn
        return klass, raw

    def test_every_tester_bench_can_build_accepts_samples(self):
        """Including the ones that inherit the stub: a capture that raised
        TypeError would do it after the run had already converged, which is
        how the historical no-argument signatures were found."""
        from bgperf2 import TESTER_CLASSES
        assert TESTER_CLASSES, 'no tester classes to probe'
        for name, cls in sorted(TESTER_CLASSES.items()):
            for meth in ('find_errors', 'find_timeouts'):
                _, raw = self._resolved(cls, meth)
                code = raw.__code__
                assert 'samples' in code.co_varnames[:code.co_argcount], (
                    '{0}.{1} cannot capture'.format(name, meth))

    def test_which_testers_actually_scan_is_pinned(self):
        """`base.Tester`'s stubs return 0 without reading anything, so a tester
        resolving to them reports no errors however many its logs hold. That is
        a real pre-existing gap, not something this capture introduced, so it
        is pinned rather than asserted away: a tester that stops scanning, or a
        new one that never starts, changes this set and has to say so.
        """
        import base as base_mod
        from bgperf2 import TESTER_CLASSES
        scans = set()
        for name, cls in TESTER_CLASSES.items():
            for meth in ('find_errors', 'find_timeouts'):
                owner, _ = self._resolved(cls, meth)
                if owner is not base_mod.Tester:
                    scans.add((name, meth))
        assert scans == {
            ('bird', 'find_errors'),
            ('bgpdump2', 'find_errors'),
            ('bgpdump2', 'find_timeouts'),
            ('gobgp', 'find_errors'),
            ('gobgp', 'find_timeouts'),
            ('exabgp_mrtparse', 'find_errors'),
            ('exabgp_mrtparse', 'find_timeouts'),
        }, scans


class TestTheArtifact:
    def _args(self, tmp_path):
        return types.SimpleNamespace(results_dir=str(tmp_path))

    def test_a_clean_run_writes_nothing(self, tmp_path):
        p = bgperf2.write_tester_health_artifact(
            self._args(tmp_path), 'run', 0, [], 0, [])
        assert p is None
        assert os.listdir(str(tmp_path)) == []

    def test_a_rejection_is_explained_on_disk(self, tmp_path):
        samples = [{'log': 'a.log', 'line': 3, 'text': '<RMT> Received: Cease',
                    'truncated': False}]
        p = bgperf2.write_tester_health_artifact(
            self._args(tmp_path), 'run', 1, samples, 0, [])
        assert p is not None
        doc = json.load(open(p))
        assert doc['tester_errors'] == 1
        assert doc['sampled_errors'] == 1
        # Named per-list because that is what it bounds: errors and timeouts
        # are separate walks with separate lists.
        assert doc['sample_limit_per_list'] == base.ERROR_SAMPLE_LIMIT
        # Both bounds, because the per-log one is what usually binds.
        assert doc['sample_limit_per_log'] == base.ERROR_SAMPLE_PER_LOG
        # The one artifact a previous run can deliberately leave behind, so it
        # has to say whose it is.
        assert doc['run'] == 'run'
        assert doc['date']
        assert doc['error_samples'][0]['text'] == '<RMT> Received: Cease'

    def test_a_truncated_capture_is_distinguishable(self, tmp_path):
        """`sampled` against the count is how a reader tells the two apart."""
        samples = [{'log': 'a.log', 'line': i, 'text': 'x', 'truncated': False}
                   for i in range(base.ERROR_SAMPLE_LIMIT)]
        p = bgperf2.write_tester_health_artifact(
            self._args(tmp_path), 'run', 500, samples, 0, [])
        doc = json.load(open(p))
        assert doc['tester_errors'] == 500
        assert doc['sampled_errors'] == base.ERROR_SAMPLE_LIMIT

    def test_timeouts_alone_are_enough_to_write(self, tmp_path):
        """tester_health rejects on either count, so either must be explained."""
        p = bgperf2.write_tester_health_artifact(
            self._args(tmp_path), 'run', 0, [],
            2, [{'log': 'a.log', 'line': 1, 'text': 'timeout',
                 'truncated': False}])
        assert p is not None
        assert json.load(open(p))['tester_timeouts'] == 2

    def test_a_writer_failure_never_costs_the_run(self, tmp_path):
        """By here the run has converged and its evidence is safe.

        Losing a converged run to the writer of the file that explains a
        rejection would be the failure this was written to fix. A missing
        results directory is *not* that case -- `results_path()` creates it --
        so the failure exercised here is a sample the encoder cannot take.
        """
        unserialisable = [{'log': 'a.log', 'line': 1, 'text': object(),
                           'truncated': False}]
        assert bgperf2.write_tester_health_artifact(
            self._args(tmp_path), 'run', 1, unserialisable, 0, []) is None

    def test_a_missing_results_directory_is_created(self, tmp_path):
        nested = types.SimpleNamespace(results_dir=str(tmp_path / 'a' / 'b'))
        p = bgperf2.write_tester_health_artifact(nested, 'run', 1, [], 0, [])
        assert p is not None and os.path.exists(p)


class TestAStaleFileNeverOutlivesItsRun:
    """`.events.json` and `.versions.json` are rewritten unconditionally; this
    is the only per-run artifact that can be left behind by a previous run of
    the same name, and a stale one names the run it no longer describes."""

    def test_a_clean_rerun_removes_the_previous_evidence(self, tmp_path):
        args = types.SimpleNamespace(results_dir=str(tmp_path))
        samples = [{'source': 't0', 'log': 'a.log', 'line': 1,
                    'text': '<RMT> Received: Cease', 'truncated': False}]
        p = bgperf2.write_tester_health_artifact(args, 'run', 2, samples, 0, [])
        assert os.path.exists(p)
        # Same configuration, same results dir, and this time it is clean.
        assert bgperf2.write_tester_health_artifact(
            args, 'run', 0, [], 0, []) is None
        assert not os.path.exists(p)

    def test_removing_a_file_that_is_not_there_is_not_an_error(self, tmp_path):
        args = types.SimpleNamespace(results_dir=str(tmp_path))
        assert bgperf2.write_tester_health_artifact(
            args, 'run', 0, [], 0, []) is None


    def test_a_failed_write_leaves_no_earlier_run_behind(self, tmp_path):
        """atomic_write renames over the target, so a failure would otherwise
        leave the previous run's document at this name -- and the checker would
        quote its lines for a rejection they did not cause."""
        args = types.SimpleNamespace(results_dir=str(tmp_path))
        good = [{'source': 't0', 'log': 'a.log', 'line': 1,
                 'text': 'first run', 'truncated': False}]
        p = bgperf2.write_tester_health_artifact(args, 'run', 1, good, 0, [])
        assert os.path.exists(p)
        unserialisable = [{'source': 't0', 'log': 'a.log', 'line': 1,
                           'text': object(), 'truncated': False}]
        assert bgperf2.write_tester_health_artifact(
            args, 'run', 4, unserialisable, 0, []) is None
        assert not os.path.exists(p), 'stale evidence survived a failed write'
        assert not os.path.exists(p + '.tmp')


class TestOnlyAScannedRunSupersedesAnEarlierCapture:
    """The writer also removes a previous run's document, so where it is called
    decides what an unscanned run does to evidence it did not produce.

    This invariant has been written both ways. Moving the call *out* of the
    `tester_class is not None` branch looks right -- a re-run into the same
    --results-dir must not leave a stale file -- and it is wrong. A run gets
    here with no tester class whenever it built none: `-r/--repeat`, or a
    scenario declaring no testers. Neither measured anything. `-r` is the
    sharp case, because `bench()` skips `remove_old_containers()` and the
    `shutil.rmtree(config_dir)` under it, so the reused tester containers are
    still running and still appending to the very logs nobody scanned. Its
    zeros are the defaults set before the run, so removing the file on the
    strength of them deletes a capture that still describes lines in those
    logs and publishes `tester errors: 0` over a log never read.

    A run that scanned and found nothing supersedes an earlier document; a run
    that did not scan supersedes nothing.

    Asserted against the source because `finish_bench()` cannot be driven
    without Docker, and the whole point is *where* the call sits. Same approach
    as tests/test_export_fanout.py.
    """

    def _finish_bench(self):
        src = open(os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'bgperf2.py')).read()
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.FunctionDef) and node.name == 'finish_bench':
                return node
        raise AssertionError('finish_bench not found')

    def _calls(self, node):
        return [n for n in ast.walk(node)
                if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Name)
                and n.func.id == 'write_tester_health_artifact']

    def test_the_writer_runs_only_where_the_logs_were_scanned(self):
        fn = self._finish_bench()
        calls = self._calls(fn)
        assert len(calls) == 1, 'expected exactly one call site'
        guarded = False
        for node in ast.walk(fn):
            if not isinstance(node, ast.If):
                continue
            if 'tester_class' not in ast.dump(node.test):
                continue
            if any(self._calls(stmt) for stmt in node.body):
                guarded = True
        assert guarded, (
            'write_tester_health_artifact is called outside the '
            'tester_class guard, so a --repeat run -- which scans nothing and '
            'reports zeros it never measured -- would delete the previous '
            "run's captured lines")
