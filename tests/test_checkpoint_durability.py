"""A checkpoint that a hard termination can lose is not a checkpoint.

`results/` is gitignored and lives only on the `/data` EBS volume, so every
campaign row exists in exactly one place. These cover the writers, which is
what the exit criterion of the unattended plan's step 7 names: the progress
file and a completed cell's versions manifest survive a simulated power-off,
and no stray `*.tmp` is left beside a durable document.

Pure: no Docker, no EC2. `fsync` durability itself cannot be tested without
cutting power, so what is tested is that the calls are made and that the
document is never observed half-written.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bgperf2


class TestAtomicWrite:
    def test_a_reader_never_sees_a_half_written_document(self, tmp_path):
        path = str(tmp_path / 'doc.json')
        with open(path, 'w') as f:
            f.write('{"old": true}')

        def write(f):
            f.write('{"new": ')
            # What a reader sees at this instant is the whole point.
            assert json.load(open(path)) == {'old': True}
            f.write('true}')

        bgperf2.atomic_write(path, write)
        assert json.load(open(path)) == {'new': True}

    def test_the_temp_file_does_not_outlive_the_write(self, tmp_path):
        path = str(tmp_path / 'doc.json')
        bgperf2.atomic_write(path, lambda f: f.write('{}'))
        assert os.listdir(str(tmp_path)) == ['doc.json']

    def test_a_failed_write_leaves_the_old_document_and_no_temp(self, tmp_path):
        path = str(tmp_path / 'doc.json')
        with open(path, 'w') as f:
            f.write('{"old": true}')

        def write(f):
            f.write('{"partial": ')
            raise RuntimeError('killed mid-dump')

        with pytest.raises(RuntimeError):
            bgperf2.atomic_write(path, write)
        assert json.load(open(path)) == {'old': True}
        assert os.listdir(str(tmp_path)) == ['doc.json']

    def test_the_directory_entry_is_fsynced_not_just_the_data(self, tmp_path,
                                                              monkeypatch):
        """`os.replace()` orders the rename; it does not make it durable.

        Without this the directory entry can still point at the old file after
        a hard termination -- which is the difference between a checkpoint and
        a document that was probably written.
        """
        synced = []
        real_fsync = os.fsync

        def record(fd):
            try:
                synced.append(os.fstat(fd).st_mode)
            except OSError:
                pass
            return real_fsync(fd)

        monkeypatch.setattr(os, 'fsync', record)
        bgperf2.atomic_write(str(tmp_path / 'doc.json'), lambda f: f.write('{}'))
        import stat
        assert any(stat.S_ISDIR(mode) for mode in synced), (
            'the containing directory was never fsynced')

    def test_an_unsyncable_directory_does_not_cost_the_run(self, tmp_path,
                                                          monkeypatch):
        """A directory fsync is not portable -- it raises on Windows and some
        filesystems refuse it. A checkpoint that *raised* where it used to
        succeed would lose the run it exists to protect.

        Only the directory sync is refused here. The data `fsync` inside
        `atomic_write()` is not guarded, was not guarded before this, and
        should not be: a file whose contents could not be flushed is a
        checkpoint that does not exist, and that is worth failing over.
        """
        real_fsync = os.fsync

        def refuse_directories(fd):
            import stat
            if stat.S_ISDIR(os.fstat(fd).st_mode):
                raise OSError('not supported')
            return real_fsync(fd)

        monkeypatch.setattr(os, 'fsync', refuse_directories)
        bgperf2.atomic_write(str(tmp_path / 'doc.json'), lambda f: f.write('{}'))
        assert json.load(open(str(tmp_path / 'doc.json'))) == {}

    def test_an_unopenable_directory_does_not_cost_the_run(self, tmp_path,
                                                           monkeypatch):
        def refuse(path, flags):
            raise OSError('cannot open')

        monkeypatch.setattr(os, 'open', refuse)
        bgperf2.fsync_directory(str(tmp_path))


class TestSweepingAnInterruptedCheckpoint:
    """SIGKILL never reaches `atomic_write()`'s `finally`."""

    def test_a_stray_temp_is_removed_and_named(self, tmp_path):
        open(str(tmp_path / 'bench.progress.json'), 'w').write('{}')
        open(str(tmp_path / 'bench.progress.json.tmp'), 'w').write('{"half')
        swept = bgperf2.sweep_stale_temp_files(str(tmp_path))
        assert swept == ['bench.progress.json.tmp']
        assert os.listdir(str(tmp_path)) == ['bench.progress.json']

    def test_a_clean_directory_reports_nothing(self, tmp_path):
        open(str(tmp_path / 'bench.progress.json'), 'w').write('{}')
        assert bgperf2.sweep_stale_temp_files(str(tmp_path)) == []

    def test_durable_documents_are_never_touched(self, tmp_path):
        for name in ('a.csv', 'b.json', 'c.png', 'd.tmp.json'):
            open(str(tmp_path / name), 'w').write('x')
        bgperf2.sweep_stale_temp_files(str(tmp_path))
        assert sorted(os.listdir(str(tmp_path))) == [
            'a.csv', 'b.json', 'c.png', 'd.tmp.json']

    def test_a_missing_directory_is_not_an_error(self, tmp_path):
        assert bgperf2.sweep_stale_temp_files(
            str(tmp_path / 'nope')) == []


class TestProvenanceIsWrittenAtomically:
    """The worse of the two holes: a plain `json.dump` truncates.

    A half-written `versions.json` beside a completed cell is a row whose
    target version cannot be established -- and `--resume` will then skip that
    cell, because its result is already in the progress file.
    """

    def test_write_provenance_goes_through_atomic_write(self):
        import ast
        import inspect
        tree = ast.parse(inspect.getsource(bgperf2.write_provenance).strip())
        calls = {node.func.id for node in ast.walk(tree)
                 if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Name)}
        assert 'atomic_write' in calls
        # Not a comment match: `open()` must not be called at all, which is
        # what makes the write old-or-new rather than truncatable.
        assert 'open' not in calls


class TestAStopUnwindsTheWholeBatch:
    """A stop at a cell boundary ends the batch, not just one test's loop.

    Breaking out of the cell loop alone let `batch()` finish that test, walk on
    to the next one in the config, and return -- so the process exited 0, which
    is exactly what the 143 exists to distinguish from a host that was taken
    away. The campaign runner reads that 0 as success and stamps RAN over a
    truncated matrix. The second test below is the sharper half: the per-test
    preamble unlinks a test's progress and summary documents when the batch is
    not resuming, so a stop that walked on would discard the previous results
    of tests it never ran.
    """

    def _config(self, tmp_path):
        config = tmp_path / 'batch.yaml'
        config.write_text(
            'tests:\n'
            '  -\n'
            '     name: first\n'
            '     neighbors: [1]\n'
            '     prefixes: [1]\n'
            '     filter_test: [None]\n'
            '     targets:\n'
            '       -\n'
            '         name: bird\n'
            '  -\n'
            '     name: second\n'
            '     neighbors: [1]\n'
            '     prefixes: [1]\n'
            '     filter_test: [None]\n'
            '     targets:\n'
            '       -\n'
            '         name: bird\n')
        return config

    def _args(self, tmp_path, config):
        import argparse
        return argparse.Namespace(
            batch_config=str(config), results_dir=str(tmp_path / 'results'),
            resume=False, dir=str(tmp_path / 'work'), bench_name='bgperf')

    def test_it_raises_rather_than_running_on(self, tmp_path, monkeypatch):
        called = []
        monkeypatch.setattr(bgperf2, 'check_batch_images', lambda targets: None)
        monkeypatch.setattr(bgperf2, 'start_interruption_watch', lambda: None)
        monkeypatch.setattr(bgperf2, 'install_stop_handlers', lambda: None)
        monkeypatch.setattr(bgperf2, 'bench', lambda a: called.append(a))

        results = tmp_path / 'results'
        results.mkdir(parents=True)
        # The second test's documents, from a run that finished earlier.
        survivor = results / 'second.progress.json'
        survivor.write_text('{"schema_version": 1, "cells": {"x": []}}')
        summary = results / 'second.summary.json'
        summary.write_text('{"test": "second"}')

        monkeypatch.setattr(bgperf2, 'stop_signal', bgperf2.StopSignal())
        bgperf2.stop_signal.request('SIGTERM')

        with pytest.raises(bgperf2.StopRequested) as raised:
            bgperf2.batch(self._args(tmp_path, self._config(tmp_path)))

        assert raised.value.reason == 'SIGTERM'
        # No cell was begun, which is the point of stopping at the boundary.
        assert called == []
        # And the test that never ran still has the results it had.
        assert json.loads(survivor.read_text())['cells'] == {'x': []}
        assert summary.exists()
