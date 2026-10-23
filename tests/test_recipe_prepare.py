"""Selected image acquisition never becomes an implicit runtime or build path."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

import recipes
import recipe_preflight as runtime
import recipe_prepare as preparation


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def document():
    result = json.loads((ROOT / 'examples/recipes/synthetic-ipv4.recipe.json').read_text())
    for index, role in enumerate(result['roles'], 1):
        result['roles'][role]['image'] = f'registry.example/{role}@sha256:' + str(index) * 64
    return result


def items(report):
    assert report['schema'] == 'bgperf2/preparation/v1alpha1'
    assert report['execution'] == 'not_implemented'
    assert report['comparison'] == 'not_assessed'
    assert report['status'] in {'planned', 'prepared', 'refused'}
    refs = [item['requested'] for item in report['items']]
    assert len(refs) == len(set(refs))
    for item in report['items']:
        assert item['action'] in {'keep', 'pull', 'unavailable'}
        assert item['state'] in {'available', 'missing', 'acquired', 'failed', 'skipped'}
        assert item['download_bytes'] is None
        assert item['incremental_size_bytes'] is None
    return {item['requested']: item for item in report['items']}


@pytest.fixture
def host(document, monkeypatch):
    """An exact command allowlist; any accidental real operation fails the test."""
    monkeypatch.setenv('DOCKER_HOST', 'unix:///var/run/docker.sock')
    monkeypatch.setenv('DOCKER_CONTEXT', 'remote-context')
    monkeypatch.setenv('DOCKER_CONFIG', '/untrusted/config')
    monkeypatch.setenv('GIT_DIR', '/untrusted/git')
    monkeypatch.setattr(runtime.platform, 'system', lambda: 'Linux')
    monkeypatch.setattr(runtime.sys, 'version_info', (3, 14, 0))
    monkeypatch.setattr(runtime.shutil, 'which', lambda tool: '/usr/bin/' + tool)
    original_is_file = Path.is_file
    monkeypatch.setattr(Path, 'is_file', lambda path: True if path == runtime.ROOT / 'venv/bin/python'
                        else original_is_file(path))
    state = {'calls': [], 'events': [], 'missing': set(), 'acquired': [],
             'inspect_errors': {}, 'pull_errors': {}, 'wrong_after_pull': set(),
             'guard_failure': None, 'guards': 0, 'dirty': '', 'missing_stdout': ''}

    def fake(argv, *, env=None, timeout=15):
        argv = list(map(str, argv))
        state['calls'].append((argv, timeout))
        assert env['GIT_OPTIONAL_LOCKS'] == '0'
        assert not {'DOCKER_CONTEXT', 'DOCKER_CONFIG', 'GIT_DIR'} & env.keys()
        git = ['git', '-c', 'core.fsmonitor=false', '-c', 'core.untrackedCache=false',
               '-C', str(runtime.ROOT)]
        if argv == [*git, 'rev-parse', '--verify', 'HEAD^{commit}']:
            assert timeout == 15
            return document['engine']['revision'] + '\n'
        if argv == [*git, 'status', '--porcelain', '--untracked-files=all',
                    '--ignore-submodules=none']:
            assert timeout == 15
            return state['dirty']
        bootstrap = [str(runtime.ROOT / 'venv/bin/python'), '-I',
                     str(runtime.ROOT / 'scripts/bootstrap.py'), '--check']
        guard = [str(runtime.ROOT / 'venv/bin/python'), '-I',
                 str(runtime.ROOT / 'scripts/quality_gate.py'), '--guard-only']
        if argv in (bootstrap, guard):
            assert timeout == 15
            state['guards'] += 1
            state['events'].append(('guard', state['guards']))
            if state['guards'] == state['guard_failure']:
                raise runtime.ProbeError('active measurement lock')
            return 'Existing locked environment verified'
        docker = ['docker', '--host', 'unix:///var/run/docker.sock', 'image']
        selected = {role['image'] for role in document['roles'].values()}
        if len(argv) == 6 and argv[:5] == [*docker, 'inspect']:
            assert timeout == 15
            ref = argv[-1]
            assert ref in selected
            state['events'].append(('inspect', ref))
            if ref in state['inspect_errors']:
                response = state['inspect_errors'][ref]
                if isinstance(response, Exception):
                    raise response
                return response
            if ref in state['missing'] and ref not in state['acquired']:
                raise runtime.CommandError(argv, 1, state['missing_stdout'],
                    'Error response from daemon: No such image: ' + ref + '\n')
            digest = 'registry.example/wrong@sha256:' + 'f' * 64
            observed = digest if ref in state['wrong_after_pull'] and ref in state['acquired'] else ref
            image_id = ref if ref.startswith('sha256:') else 'sha256:' + 'a' * 64
            return json.dumps([{'Id': image_id, 'RepoDigests': [observed],
                                'Size': 123, 'Os': 'linux', 'Architecture': 'amd64'}])
        if len(argv) == 6 and argv[:5] == [*docker, 'pull']:
            assert timeout == preparation.PULL_TIMEOUT_SECONDS
            assert timeout > 15
            ref = argv[-1]
            assert ref in selected and '@sha256:' in ref
            state['events'].append(('pull', ref))
            if ref in state['pull_errors']:
                raise runtime.ProbeError(state['pull_errors'][ref])
            state['acquired'].append(ref)
            return 'pulled selected digest'
        raise AssertionError('unexpected command: ' + repr(argv))

    monkeypatch.setattr(runtime, 'run_command', fake)
    return state


def disclose(host):
    def emit(report):
        host['events'].append(('disclosure', copy.deepcopy(report)))
    return emit


def pulls(host):
    return [event[1] for event in host['events'] if event[0] == 'pull']


def test_default_is_a_local_plan_without_acquisition(document, host):
    before = copy.deepcopy(document)
    host['missing'] = {role['image'] for role in document['roles'].values()}
    report = preparation.prepare_recipe(document)
    assert report['status'] == 'planned'
    assert all(item['state'] == 'missing' and item['action'] == 'pull'
               for item in items(report).values())
    assert not pulls(host)
    assert document == before


@pytest.mark.parametrize('missing_stdout', ['', '[]\n'])
def test_typed_exact_docker_absence_can_be_acquired(document, host, missing_stdout):
    ref = document['roles']['target']['image']
    host['missing'] = {ref}
    host['missing_stdout'] = missing_stdout
    report = preparation.prepare_recipe(document, pull=True, emit_disclosure=disclose(host))
    assert report['status'] == 'prepared'
    assert items(report)[ref]['state'] == 'acquired'
    assert pulls(host) == [ref]


def test_explicit_pull_deduplicates_roles_and_discloses_before_mutation(document, host):
    ref = document['roles']['target']['image']
    document['roles']['generator']['image'] = ref
    host['missing'] = {ref}
    report = preparation.prepare_recipe(document, pull=True, emit_disclosure=disclose(host))
    entries = items(report)
    assert report['status'] == 'prepared'
    assert len(entries) == 2
    assert set(entries[ref]['roles']) == {'target', 'generator'}
    assert entries[ref]['state'] == 'acquired'
    observer = document['roles']['observer']['image']
    assert entries[observer]['state'] == 'available'
    assert entries[observer]['action'] == 'keep'
    assert pulls(host) == [ref]
    kinds = [event[0] for event in host['events']]
    assert kinds.count('disclosure') == 1
    first_pull = kinds.index('pull')
    disclosure = kinds.index('disclosure')
    assert disclosure < first_pull
    assert kinds[disclosure + 1:first_pull] == ['guard']
    assert {event[1] for event in host['events'][:disclosure] if event[0] == 'inspect'} == set(entries)
    assert host['events'][first_pull + 1] == ('inspect', ref)
    disclosed = host['events'][disclosure][1]
    assert items(disclosed)[ref]['state'] == 'missing'


def test_already_local_image_ids_are_reused(document, host):
    document['roles']['target']['image'] = 'sha256:' + 'b' * 64
    report = preparation.prepare_recipe(document, pull=True)
    assert report['status'] == 'prepared'
    assert all(item['state'] == 'available' for item in items(report).values())
    assert not pulls(host)


def test_missing_bare_id_blocks_all_digest_pulls(document, host):
    ref = 'sha256:' + 'b' * 64
    document['roles']['observer']['image'] = ref
    host['missing'] = {role['image'] for role in document['roles'].values()}
    report = preparation.prepare_recipe(document, pull=True, emit_disclosure=disclose(host))
    assert report['status'] == 'refused'
    assert items(report)[ref]['action'] == 'unavailable'
    assert not pulls(host)


@pytest.mark.parametrize('response', ['{', '[]', '[{}]',
    '[{"Id":"sha256:' + 'a' * 64 + '","RepoDigests":[]}]',
    'permission', 'timeout', 'untyped-missing', 'wrong-ref-missing',
    'wrong-exit', 'nonempty-missing-stdout'])
def test_inspection_errors_are_never_classified_as_missing(document, host, response):
    refs = [role['image'] for role in document['roles'].values()]
    ref = refs[-1]
    argv = ['docker', '--host', 'unix:///var/run/docker.sock', 'image', 'inspect', ref]
    if response == 'permission':
        response = runtime.CommandError(argv, 1, '', 'permission denied')
    elif response == 'timeout':
        response = runtime.ProbeError('docker timed out')
    elif response == 'untyped-missing':
        response = runtime.ProbeError('No such image: ' + ref)
    elif response == 'wrong-ref-missing':
        response = runtime.CommandError(argv, 1, '', 'Error: No such image: unrelated')
    elif response == 'wrong-exit':
        response = runtime.CommandError(argv, 125, '', 'Error: No such image: ' + ref)
    elif response == 'nonempty-missing-stdout':
        response = runtime.CommandError(argv, 1, '{"error":"unavailable"}',
                                        'Error: No such image: ' + ref)
    host['missing'] = set(refs[:-1])
    host['inspect_errors'][ref] = response
    report = preparation.prepare_recipe(document, pull=True, emit_disclosure=disclose(host))
    assert report['status'] == 'refused'
    assert not pulls(host)


def test_missing_disclosure_callback_blocks_mutation(document, host):
    host['missing'] = {role['image'] for role in document['roles'].values()}
    report = preparation.prepare_recipe(document, pull=True)
    assert report['status'] == 'refused'
    assert not pulls(host)


def test_failed_disclosure_blocks_mutation(document, host):
    host['missing'] = {role['image'] for role in document['roles'].values()}
    def broken_disclosure(report):
        raise OSError('disclosure stream closed')
    report = preparation.prepare_recipe(document, pull=True, emit_disclosure=broken_disclosure)
    assert report['status'] == 'refused'
    assert not pulls(host)


@pytest.mark.parametrize('failure', ['remote', 'dirty'])
def test_runtime_prerequisite_failure_blocks_images(document, host, monkeypatch, failure):
    if failure == 'remote':
        monkeypatch.setenv('DOCKER_HOST', 'tcp://remote.example:2375')
    else:
        host['dirty'] = ' M recipes.py\n'
    report = preparation.prepare_recipe(document, pull=True, emit_disclosure=disclose(host))
    assert report['status'] == 'refused'
    assert not any(event[0] in {'inspect', 'pull'} for event in host['events'])


@pytest.mark.parametrize('guard_failure', [1, 2])
def test_initial_or_post_disclosure_guard_refusal_blocks_pull(document, host, guard_failure):
    host['missing'] = {role['image'] for role in document['roles'].values()}
    host['guard_failure'] = guard_failure
    report = preparation.prepare_recipe(document, pull=True, emit_disclosure=disclose(host))
    assert report['status'] == 'refused'
    assert not pulls(host)
    if guard_failure == 1:
        assert not any(event[0] == 'inspect' for event in host['events'])
    else:
        assert any(event[0] == 'disclosure' for event in host['events'])


def test_post_pull_wrong_digest_stops_remaining_acquisition(document, host):
    refs = [role['image'] for role in document['roles'].values()]
    host['missing'] = set(refs)
    host['wrong_after_pull'] = {refs[0]}
    report = preparation.prepare_recipe(document, pull=True, emit_disclosure=disclose(host))
    assert report['status'] == 'refused'
    assert pulls(host) == refs[:1]
    entries = items(report)
    assert entries[refs[0]]['state'] == 'failed'
    assert all(entries[ref]['state'] == 'skipped' for ref in refs[1:])


def test_partial_failure_keeps_first_image_and_skips_third(document, host):
    refs = [role['image'] for role in document['roles'].values()]
    host['missing'] = set(refs)
    host['pull_errors'][refs[1]] = 'registry unavailable'
    report = preparation.prepare_recipe(document, pull=True, emit_disclosure=disclose(host))
    assert report['status'] == 'refused'
    assert pulls(host) == refs[:2]
    assert host['acquired'] == refs[:1]
    entries = items(report)
    assert [entries[ref]['state'] for ref in refs] == ['acquired', 'failed', 'skipped']
    assert entries[refs[0]]['image_id'] == 'sha256:' + 'a' * 64


def test_later_guard_failure_keeps_acquired_image_and_stops_pending_pulls(document, host):
    refs = [role['image'] for role in document['roles'].values()]
    host['missing'] = set(refs)
    host['guard_failure'] = 3
    report = preparation.prepare_recipe(document, pull=True, emit_disclosure=disclose(host))
    assert report['status'] == 'refused'
    assert host['acquired'] == pulls(host) == refs[:1]
    entries = items(report)
    assert [entries[ref]['state'] for ref in refs] == ['acquired', 'skipped', 'skipped']


def test_cli_separates_flushed_disclosure_from_json_result(document, host, tmp_path, monkeypatch, capsys):
    path = tmp_path / 'recipe.json'
    path.write_text(json.dumps(document))
    host['missing'] = {role['image'] for role in document['roles'].values()}
    original_flush = sys.stderr.flush
    flushed = []
    def flush():
        flushed.append(True)
        return original_flush()
    monkeypatch.setattr(sys.stderr, 'flush', flush)
    original_runner = runtime.run_command
    def runner(argv, **kwargs):
        if 'pull' in argv:
            assert flushed
        return original_runner(argv, **kwargs)
    monkeypatch.setattr(runtime, 'run_command', runner)
    assert recipes.main(['prepare', str(path), '--pull']) == 0
    output = capsys.readouterr()
    assert json.loads(output.out)['status'] == 'prepared'
    assert 'bgperf2/preparation/v1alpha1' in output.err
    assert 'pull' in output.err


def test_cli_refusal_is_json_with_exit_two(document, host, tmp_path, capsys):
    path = tmp_path / 'recipe.json'
    path.write_text(json.dumps(document))
    host['guard_failure'] = 1
    assert recipes.main(['prepare', str(path)]) == 2
    output = capsys.readouterr()
    assert json.loads(output.out)['status'] == 'refused'


def test_invalid_direct_script_refuses_before_probing(document, tmp_path):
    document['roles']['target']['image'] = 'bgperf/bird:latest'
    path = tmp_path / 'invalid.json'
    path.write_text(json.dumps(document))
    result = subprocess.run([sys.executable, str(ROOT / 'recipes.py'), 'prepare',
                             str(path), '--pull'], cwd=tmp_path, capture_output=True, text=True,
                            env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
    assert result.returncode == 2
    assert not result.stdout
    assert 'immutable image' in result.stderr
    assert 'Traceback' not in result.stderr


def test_importing_preparation_preserves_offline_runtime_isolation(tmp_path):
    script = '''
import importlib.abc, os, pathlib, socket, subprocess, sys
class BlockRuntime(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'docker', 'settings', 'bgperf2', 'base'}:
            raise AssertionError('runtime import forbidden: ' + fullname)
sys.meta_path.insert(0, BlockRuntime())
def forbidden(*args, **kwargs):
    raise AssertionError('runtime operation forbidden')
subprocess.run = forbidden
subprocess.Popen = forbidden
socket.socket.connect = forbidden
socket.create_connection = forbidden
os.sysconf = forbidden
pathlib.Path.resolve = forbidden
sys.path.insert(0, sys.argv[1])
import recipe_prepare, recipe_preflight, recipes
import json
with open(sys.argv[2]) as source:
    document = json.load(source)
assert recipe_preflight.plan_recipe(document)['mode'] == 'plan'
assert recipes.inspect_recipe(document)['schema'] == document['schema']
'''
    result = subprocess.run([sys.executable, '-c', script, str(ROOT),
                             str(ROOT / 'examples/recipes/synthetic-ipv4.recipe.json')],
                            cwd=tmp_path, capture_output=True, text=True,
                            env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
    assert result.returncode == 0, result.stderr


def test_interrupted_bounded_pull_reaps_only_its_client_process_group(monkeypatch):
    calls, killed, waits = [], [], []
    class InterruptedProcess:
        pid = 123456
        def __init__(self, argv, **kwargs):
            calls.append((argv, kwargs))
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def communicate(self, timeout=None):
            waits.append(timeout)
            if len(waits) == 1:
                raise KeyboardInterrupt
            return '', ''
    monkeypatch.setattr(runtime.subprocess, 'Popen', InterruptedProcess)
    monkeypatch.setattr(runtime.os, 'killpg', lambda *args: killed.append(args))
    argv = ['docker', '--host', 'unix:///var/run/docker.sock', 'image', 'pull',
            'registry.example/bird@sha256:' + 'a' * 64]
    with pytest.raises(KeyboardInterrupt):
        runtime.run_command(argv, timeout=preparation.PULL_TIMEOUT_SECONDS)
    assert len(calls) == 1
    assert calls[0][0] == argv
    assert calls[0][1]['start_new_session'] is True
    assert calls[0][1].get('shell', False) is False
    assert waits == [preparation.PULL_TIMEOUT_SECONDS, None]
    assert killed == [(123456, runtime.signal.SIGKILL)]


def test_sigterm_stops_owned_client_reaps_and_restores_handler(monkeypatch):
    installed, killed, waits = [], [], []
    handlers = {runtime.signal.SIGTERM: runtime.signal.SIG_DFL}
    def set_handler(signum, handler):
        previous = handlers[signum]
        handlers[signum] = handler
        installed.append((signum, handler))
        return previous
    class TerminatedProcess:
        pid = 123457
        def __init__(self, argv, **kwargs):
            assert kwargs['start_new_session'] is True
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def communicate(self, timeout=None):
            waits.append(timeout)
            if len(waits) == 1:
                handler = handlers[runtime.signal.SIGTERM]
                assert callable(handler)
                handler(runtime.signal.SIGTERM, None)
                raise AssertionError('SIGTERM handler must propagate termination')
            return '', ''
    monkeypatch.setattr(runtime.subprocess, 'Popen', TerminatedProcess)
    monkeypatch.setattr(runtime.os, 'killpg', lambda *args: killed.append(args))
    monkeypatch.setattr(runtime.signal, 'getsignal', lambda signum: handlers[signum])
    monkeypatch.setattr(runtime.signal, 'signal', set_handler)
    with pytest.raises(SystemExit) as interrupted:
        runtime.run_command(['docker', 'image', 'pull', 'selected'],
                            timeout=preparation.PULL_TIMEOUT_SECONDS)
    assert interrupted.value.code == 143
    assert waits == [preparation.PULL_TIMEOUT_SECONDS, None]
    assert killed == [(123457, runtime.signal.SIGKILL)]
    assert handlers[runtime.signal.SIGTERM] == runtime.signal.SIG_DFL
    assert len(installed) == 2
    assert callable(installed[0][1])
    assert installed[1] == (runtime.signal.SIGTERM, runtime.signal.SIG_DFL)
