"""The standalone smoke uses modeled source/build/runtime and real evidence checks."""
import ast
import json
import os
from pathlib import Path
import socket
import subprocess
from unittest.mock import patch

import pytest

import recipe_bisection as bisection
from recipe_results import verify_result_package
from scripts import bisection_smoke as smoke


@pytest.fixture(scope='module')
def simulated(tmp_path_factory):
    output = tmp_path_factory.mktemp('bisection-smoke') / 'artifacts'
    return output, smoke.run_smoke(output)


def document(summary, case):
    return bisection.load(summary['cases'][case]['report'])


@pytest.mark.parametrize('case', ['assertions', 'target-crash'])
def test_adjacent_boundary_has_cached_builds_and_fresh_confirmations(simulated, case):
    output, summary = simulated
    assert summary['simulation'] is True and summary['status'] == 'passed'
    assert set(summary['cases']) == set(smoke.CASES)
    report = document(summary, case)
    selected = summary['cases'][case]
    assert report['conclusion']['state'] == 'confirmed'
    assert report['conclusion']['last_observed_good'] == report['plan']['candidates'][3]['revision']
    assert report['conclusion']['first_observed_bad'] == report['plan']['candidates'][4]['revision']
    assert [x['index'] for x in selected['attempts']][-2:] == [3, 4]
    assert len(selected['attempts']) == 7 and len(selected['builds']) == 5
    assert len({x['source_attempt_id'] for x in selected['attempts']}) == 7
    assert [x['request']['phase'] for x in report['trials']][-2:] == ['confirm-good', 'confirm-bad']
    assert all(x['timeout'] == 120 for x in selected['attempts'])
    assert all(x['timeout'] == 60 for x in selected['builds'])
    assert report['performance'] == {'qualification': 'not_assessed', 'policy': 'disabled'}
    assert 'SIMULATED' in (output / 'SIMULATION.txt').read_text()
    assert (output / 'simulated-host.lock').is_file()
    assert 'SIMULATED' in report['plan']['recipe']['reproduction']['question']
    for record in report['trials']:
        target = record['observed']['target']
        assert target['provenance']['kind'] == 'local_source'
        assert target['provenance']['instrumentation'] == 'debug'
        assert target['provenance']['build']['reconstructible'] is False
    if case == 'target-crash':
        for record in report['trials']:
            path = Path(selected['report']).parent / record['result']
            samples = bisection.load(path.parent / 'work/live-diagnostics.json')['samples']
            assert samples[0]['bird_process_present'] is True
            if record['classification'] == 'bad':
                assert samples[-1]['bird_process_present'] is False
                assert samples[-1]['daemon_exit_code'] == 139


def test_skips_remain_inside_an_unresolved_range(simulated):
    _, summary = simulated
    report = document(summary, 'skipped')
    assert report['conclusion']['state'] == 'unresolved'
    assert report['conclusion']['possible_first_bad'] == [report['plan']['candidates'][i]['revision'] for i in (4, 5)]
    skipped = [x for x in report['trials'] if x['classification'] == 'skipped']
    assert len(skipped) == 1 and skipped[0]['request']['index'] == 4
    assert skipped[0]['result'] is None and skipped[0]['observed'] is None
    assert not any(x['index'] == 4 for x in summary['cases']['skipped']['attempts'])
    failure = Path(summary['cases']['skipped']['report']).parent / skipped[0]['failure']
    assert bisection.load(failure)['classification'] == 'skipped'


def test_ambiguous_trial_pauses_then_explicitly_continues_without_retry(simulated):
    _, summary = simulated
    case = summary['cases']['ambiguous']
    assert case['pause']['outcome']['state'] == 'paused_ambiguous'
    assert case['pause']['attempts_before_resume'] == 3 and case['pause']['explicit_resume'] is True
    paused = bisection.load(case['paused_report'])
    assert len(paused['trials']) == 3 and paused['trials'][-1]['classification'] == 'ambiguous'
    assert paused['trials'][-1]['observed']['result_status'] == 'harness_failed'
    assert [x['index'] for x in case['attempts']].count(4) == 1
    assert case['conclusion']['state'] == 'unresolved'
    assert len(case['conclusion']['possible_first_bad']) == 2


def test_unstable_confirmation_cannot_claim_a_boundary(simulated):
    _, summary = simulated
    report = document(summary, 'unstable')
    assert report['conclusion']['state'] == 'unresolved'
    assert 'confirmation failed' in report['conclusion']['reason']
    original = next(x for x in report['trials'] if x['request']['index'] == 3)
    confirmation = report['trials'][-1]
    assert original['classification'] == 'good' and confirmation['classification'] == 'bad'
    assert confirmation['request']['phase'] == 'confirm-good'
    assert original['observed']['source_attempt_id'] != confirmation['observed']['source_attempt_id']


def test_portable_packages_and_offline_rebuilds_verify(simulated):
    _, summary = simulated
    assert {'export', 'plan', 'init', 'run', 'report', 'verify'} <= set(summary['operations'])
    for case in summary['cases'].values():
        for path in (case['report'], case['report_rebuilt'], case['paused_report']):
            if path:
                assert bisection.verify_report(path)['valid'] is True
                report = bisection.load(path)
                for trial in report['trials']:
                    if trial['result']:
                        assert verify_result_package(Path(path).parent / trial['result'])['valid'] is True
        assert bisection.load(case['report']) == bisection.load(case['report_rebuilt'])
        assert all(x['arguments'][:2] == ['cat-file', 'commit'] for x in case['source_commands'])
        docker = [x for x in case['probe_commands'] if x[0] == 'docker']
        assert docker and all(x[1:5] == ['--host', 'unix:///var/run/docker.sock', 'image', 'inspect'] for x in docker)


def test_whole_walkthrough_guards_subprocess_and_network(tmp_path, monkeypatch):
    def guarded(output):
        with pytest.raises(AssertionError, match='unmodelled'):
            subprocess.Popen(['unexpected'])
        with pytest.raises(AssertionError, match='unmodelled'):
            socket.create_connection(('example.invalid', 1))
        with pytest.raises(AssertionError, match='unmodelled'):
            socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        with pytest.raises(AssertionError, match='unmodelled'):
            socket.socket.sendto(None, b'never sent', ('127.0.0.1', 1))
        return {'simulation': True}
    monkeypatch.setattr(smoke, '_run_smoke', guarded)
    assert smoke.run_smoke(tmp_path / 'guard') == {'simulation': True}


def test_standalone_module_does_not_import_tests():
    tree = ast.parse(Path(smoke.__file__).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert not (node.module or '').startswith(('test_', 'tests'))
        elif isinstance(node, ast.Import):
            assert all(not x.name.startswith(('test_', 'tests')) for x in node.names)


def test_refuses_existing_relative_checkout_and_symlink_outputs(tmp_path):
    output = tmp_path / 'existing'
    output.mkdir()
    sentinel = output / 'keep'
    sentinel.write_text('untouched')
    with pytest.raises(FileExistsError):
        smoke.run_smoke(output)
    assert list(output.iterdir()) == [sentinel] and sentinel.read_text() == 'untouched'
    with pytest.raises(ValueError, match='absolute'):
        smoke.run_smoke('relative')
    with pytest.raises(ValueError, match='outside'):
        smoke.run_smoke(smoke.ROOT / 'new-artifacts')
    alias = tmp_path / 'alias'
    alias.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match='symlinks'):
        smoke.run_smoke(alias / 'new-artifacts')


def test_main_runs_outside_checkout(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert smoke.main(['--output', str(tmp_path / 'standalone')]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary['simulation'] is True
    assert set(summary['cases']) == set(smoke.CASES)
    assert (tmp_path / 'standalone/smoke.json').is_file()


def test_smoke_host_locks_are_private_without_replacing_other_module_os(tmp_path, monkeypatch):
    import fcntl
    import recipe_run
    real_open = os.open
    original = Path('/tmp') / f'bgperf2-recipe-{os.getuid()}.lock'
    touched = []

    def trap(path, *args, **kwargs):
        if Path(path) == original:
            pytest.fail('SIMULATED smoke touched the real cooperating-host lock')
        touched.append(Path(path))
        return real_open(path, *args, **kwargs)

    class Boundary:
        def __getattr__(self, name):
            return getattr(os, name)

        open = staticmethod(trap)

    # Trap this smoke's OS boundary without changing the shared os module.
    monkeypatch.setattr(smoke, 'os', Boundary())
    first, second = (smoke.SimulatedOS(tmp_path / name) for name in ('first.lock', 'second.lock'))
    with patch.object(recipe_run, 'os', first):
        assert bisection.os is os and recipe_run.os is not os
        one = recipe_run.os.open(original, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(one, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with patch.object(recipe_run, 'os', second):
            two = recipe_run.os.open(original, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            # Two simultaneous modeled runs have independent host locks.
            fcntl.flock(two, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(two)
    finally:
        os.close(one)
    assert touched == [first.lock, second.lock]
    assert recipe_run.os is os
