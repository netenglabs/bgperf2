"""Prerequisite snapshots must never become an implicit execution path."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

import recipes
import recipe_preflight as preflight


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def document():
    return json.loads((ROOT / 'examples/recipes/synthetic-ipv4.recipe.json').read_text())


def no_probe(*args, **kwargs):
    raise AssertionError('unexpected prerequisite probe')


def test_nested_storage_binding_refused_before_runtime_probes(document, tmp_path, monkeypatch):
    monkeypatch.setenv('BGPERF_ARTIFACT_STORE', str(tmp_path / 'work/store'))
    monkeypatch.setattr(preflight, 'runtime_prerequisites', no_probe)
    report = preflight.check_recipe(document, workdir=tmp_path / 'work', results_dir=tmp_path / 'results')
    assert report['status'] == 'refused'
    assert 'nonnested' in report['checks'][-1]['reason']
    assert not list(tmp_path.iterdir())


def test_store_location_refuses_ram_and_does_not_create_directories(tmp_path, monkeypatch):
    monkeypatch.setenv('BGPERF_ARTIFACT_STORE', str(tmp_path / 'new-store'))
    monkeypatch.setattr(preflight, 'filesystem_type', lambda *a: 'tmpfs')
    monkeypatch.setattr(preflight, 'is_memory_backed', lambda *a: True)
    report = {'checks': [], 'status': 'checks_passed'}
    preflight._store_destination(report, 'unused')
    assert report['checks'][0]['status'] == 'refused'
    assert not list(tmp_path.iterdir())


def checks(report):
    assert report['schema'] == 'bgperf2/prerequisites/v1alpha1'
    assert report['execution'] == 'not_requested'
    assert report['comparison'] == 'not_assessed'
    assert report['status'] in {'checks_passed', 'refused'}
    assert len({item['name'] for item in report['checks']}) == len(report['checks'])
    for item in report['checks']:
        assert item['status'] in {'pass', 'refused', 'unknown'}
        assert {'name', 'status', 'reason', 'details'} <= item.keys()
    return {item['name']: item for item in report['checks']}


def test_plan_validates_without_probes_or_input_mutation(document, monkeypatch):
    before = copy.deepcopy(document)
    monkeypatch.setattr(preflight, 'run_command', no_probe)
    monkeypatch.setattr(preflight.shutil, 'which', no_probe)
    report = preflight.plan_recipe(document)
    entries = checks(report)
    assert report['mode'] == 'plan'
    assert report['recipe_sha256'] == recipes.recipe_sha256(document)
    assert document == before
    assert entries['resources']['status'] == 'unknown'
    assert entries['capabilities']['status'] == 'unknown'


@pytest.mark.parametrize('operation', ['plan', 'check'])
def test_invalid_contract_is_refused_before_probes(document, monkeypatch, tmp_path, operation):
    document['roles']['target']['image'] = 'bgperf/bird:latest'
    monkeypatch.setattr(preflight, 'run_command', no_probe)
    monkeypatch.setattr(preflight.shutil, 'which', no_probe)
    with pytest.raises(ValueError):
        if operation == 'plan':
            preflight.plan_recipe(document)
        else:
            preflight.check_recipe(document, workdir=tmp_path / 'work',
                                   results_dir=tmp_path / 'results')


def test_offline_commands_have_no_runtime_import_or_subprocess_path(tmp_path):
    script = '''
import importlib.abc, os, pathlib, runpy, socket, subprocess, sys
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
sys.path.insert(0, sys.argv.pop(1))
runpy.run_module('recipes', run_name='__main__')
'''
    fixture = ROOT / 'examples/recipes/synthetic-ipv4.recipe.json'
    for command in ['inspect', 'validate', 'plan']:
        result = subprocess.run([sys.executable, '-c', script, str(ROOT), command,
                                 str(fixture)], cwd=tmp_path, capture_output=True, text=True,
                                env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
        assert result.returncode == 0, result.stderr
        output = json.loads(result.stdout)
        if command == 'plan':
            checks(output)


def test_probe_subprocess_is_bounded_read_only_and_timeout_is_a_refusal(monkeypatch):
    calls = []
    killed = []
    class HungProcess:
        pid = 123456
        def __init__(self, argv, **kwargs):
            calls.append((argv, kwargs))
            self.waits = []
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def communicate(self, timeout=None):
            self.waits.append(timeout)
            if timeout is not None:
                assert 0 < timeout <= 60
                raise subprocess.TimeoutExpired(calls[0][0], timeout)
            return '', ''
    monkeypatch.setattr(preflight.subprocess, 'Popen', HungProcess)
    monkeypatch.setattr(preflight.os, 'killpg', lambda *args: killed.append(args))
    with pytest.raises(preflight.ProbeError):
        preflight.run_command(['docker', 'version'])
    assert len(calls) == 1
    argv, options = calls[0]
    assert argv == ['docker', 'version']
    assert options.get('shell', False) is False
    assert options['start_new_session'] is True
    assert killed == [(123456, preflight.signal.SIGKILL)]


@pytest.mark.parametrize('command', ['plan', 'check'])
def test_invalid_contract_cli_refuses_without_traceback(document, tmp_path, command):
    document['roles']['target']['image'] = 'bgperf/bird:latest'
    path = tmp_path / 'invalid.json'
    path.write_text(json.dumps(document))
    args = [sys.executable, str(ROOT / 'recipes.py'), command, str(path)]
    if command == 'check':
        args += ['--workdir', str(tmp_path / 'work'),
                 '--results-dir', str(tmp_path / 'results')]
    result = subprocess.run(args, cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 2
    assert 'immutable image' in result.stderr
    assert 'Traceback' not in result.stderr
    assert not result.stdout


@pytest.mark.parametrize('endpoint', ['tcp://remote.example:2375', 'ssh://operator@remote'])
def test_remote_endpoint_refused_before_docker_or_bootstrap(document, monkeypatch,
                                                           tmp_path, endpoint):
    monkeypatch.setenv('DOCKER_HOST', endpoint)
    calls = []
    def fake(argv, *, env=None):
        calls.append(list(map(str, argv)))
        assert 'docker' not in Path(str(argv[0])).name
        assert not any('bootstrap.py' in str(arg) for arg in argv)
        if 'rev-parse' in argv:
            return document['engine']['revision'] + '\n'
        if 'ls-files' in argv:
            return 'H SIMULATED-engine.py\0'
        if 'status' in argv:
            return ''
        raise preflight.ProbeError('unsupported fake probe')
    monkeypatch.setattr(preflight, 'run_command', fake)
    report = preflight.check_recipe(document, workdir=tmp_path / 'work',
                                   results_dir=tmp_path / 'results')
    entries = checks(report)
    assert report['status'] == 'refused'
    assert entries['docker_endpoint']['status'] == 'refused'
    assert not (tmp_path / 'work').exists()
    assert not (tmp_path / 'results').exists()


@pytest.fixture
def local_probes(document, monkeypatch):
    """Only these exact read operations are allowed, never a live command."""
    monkeypatch.setenv('DOCKER_HOST', 'unix:///var/run/docker.sock')
    monkeypatch.setenv('DOCKER_CONTEXT', 'remote-context')
    monkeypatch.setenv('DOCKER_CONFIG', '/untrusted/config')
    monkeypatch.setenv('GIT_DIR', '/untrusted/git')
    monkeypatch.setattr(preflight.platform, 'system', lambda: 'Linux')
    monkeypatch.setattr(preflight.sys, 'version_info', (3, 14, 0))
    monkeypatch.setattr(preflight.shutil, 'which', lambda tool: '/usr/bin/' + tool)
    state = {'calls': [], 'image_error': None, 'bootstrap_error': None, 'dirty': ''}
    def fake(argv, *, env=None):
        argv = list(map(str, argv))
        state['calls'].append(argv)
        assert env['GIT_OPTIONAL_LOCKS'] == '0'
        assert not {'DOCKER_CONTEXT', 'DOCKER_CONFIG', 'GIT_DIR'} & env.keys()
        git = ['git', '-c', 'core.fsmonitor=false', '-c', 'core.untrackedCache=false',
               '-C', str(preflight.ROOT)]
        if argv == [*git, 'rev-parse', '--verify', 'HEAD^{commit}']:
            return document['engine']['revision'] + '\n'
        if argv == [*git, 'ls-files', '-v', '-z']:
            return 'H SIMULATED-engine.py\0'
        if argv == [*git, 'status', '--porcelain',
                    '--untracked-files=all', '--ignore-submodules=none']:
            return state['dirty']
        if argv == [str(preflight.ROOT / 'venv/bin/python'), '-I',
                    str(preflight.ROOT / 'scripts/bootstrap.py'), '--check']:
            if state['bootstrap_error']:
                raise preflight.ProbeError(state['bootstrap_error'])
            return 'Existing locked environment verified'
        if argv[:5] == ['docker', '--host', 'unix:///var/run/docker.sock', 'image', 'inspect']:
            requested = argv[5]
            assert len(argv) == 6
            assert requested in {role['image'] for role in document['roles'].values()}
            if state['image_error'] == 'missing':
                raise preflight.ProbeError('No such image')
            if state['image_error'] == 'bad-json':
                return '{'
            image_id = requested if requested.startswith('sha256:') else 'sha256:' + 'a' * 64
            if state['image_error'] == 'mismatch':
                image_id = 'sha256:' + 'f' * 64
            return json.dumps([{'Id': image_id, 'RepoDigests': [requested],
                                'Size': 12345, 'Os': 'linux', 'Architecture': 'amd64'}])
        raise AssertionError('unexpected command: ' + repr(argv))
    monkeypatch.setattr(preflight, 'run_command', fake)
    # A deterministic disk mount snapshot; no actual mount or filesystem mutation.
    monkeypatch.setattr(preflight, 'filesystem_type', lambda path, mounts: 'ext4')
    monkeypatch.setattr(preflight, 'is_memory_backed', lambda path, mounts: False)
    return state


@pytest.fixture
def pinned_document(document, tmp_path, monkeypatch):
    import bgperf2
    from test_recipes import source, export
    monkeypatch.setattr(bgperf2, 'host_cpus', lambda: frozenset(range(4)))
    path, test = source(tmp_path, pin='target=0,monitor=1,testers=2-3')
    return export(path, test, engine_revision=document['engine']['revision'], roles=document['roles'])


def test_pinned_plan_is_declared_without_online_cpu_probe(pinned_document, monkeypatch):
    monkeypatch.setattr(preflight, '_online_cpus', no_probe)
    monkeypatch.setattr(preflight, 'run_command', no_probe)
    entry = checks(preflight.plan_recipe(pinned_document))['cpu_pinning']
    assert entry['status'] == 'unknown'
    assert entry['details']['requested'] == pinned_document['resolved']['pin']


def test_pinned_check_uses_online_cpus_not_controller_affinity(
        pinned_document, local_probes, tmp_path, monkeypatch):
    monkeypatch.setattr(preflight, '_online_cpus', lambda: frozenset(range(4)))
    monkeypatch.setattr(preflight.os, 'cpu_count', lambda: 4)
    monkeypatch.setattr(preflight.os, 'sched_getaffinity', lambda pid: {3})
    report = preflight.check_recipe(pinned_document, workdir=tmp_path / 'work', results_dir=tmp_path / 'results')
    assert report['status'] == 'checks_passed'
    assert checks(report)['cpu_pinning']['details']['online_cpus'] == [0, 1, 2, 3]
    assert not (tmp_path / 'work').exists()


@pytest.mark.parametrize('online', [frozenset(range(3)), None])
def test_missing_or_unreadable_online_cpus_refuse_pinned_execution(
        pinned_document, local_probes, tmp_path, monkeypatch, online):
    def observed():
        if online is None:
            raise OSError('CPU sysfs unavailable')
        return online
    monkeypatch.setattr(preflight, '_online_cpus', observed)
    report = preflight.check_recipe(pinned_document, workdir=tmp_path / 'work', results_dir=tmp_path / 'results')
    assert report['status'] == 'refused'
    assert checks(report)['cpu_pinning']['status'] == 'refused'
    assert not (tmp_path / 'work').exists()
    assert not (tmp_path / 'results').exists()


def test_observed_checks_inspect_only_selected_pins_without_creating_outputs(
        document, local_probes, tmp_path, monkeypatch):
    monkeypatch.setattr(preflight, '_online_cpus', no_probe)
    before = copy.deepcopy(document)
    marker = tmp_path / 'evidence'
    marker.write_bytes(b'earlier evidence\x00')
    report = preflight.check_recipe(document, workdir=tmp_path / 'work',
                                   results_dir=tmp_path / 'results')
    entries = checks(report)
    assert report['status'] == 'checks_passed'
    assert entries['resources']['status'] == 'unknown'
    assert entries['host_contention']['status'] == 'unknown'
    inspected = [argv[-1] for argv in local_probes['calls'] if argv[0] == 'docker']
    assert sorted(inspected) == sorted(role['image'] for role in document['roles'].values())
    for role, declaration in document['roles'].items():
        item = entries['image.' + role]
        assert item['status'] == 'pass'
        assert item['details']['image_id'] == declaration['image']
        assert item['details']['local_size_bytes'] == 12345
    assert set(tmp_path.iterdir()) == {marker}
    assert marker.read_bytes() == b'earlier evidence\x00'
    assert document == before


@pytest.mark.parametrize('failure', ['missing', 'mismatch', 'bad-json'])
def test_image_inspection_failures_never_acquire_or_substitute(
        document, local_probes, tmp_path, failure):
    local_probes['image_error'] = failure
    report = preflight.check_recipe(document, workdir=tmp_path / 'work',
                                   results_dir=tmp_path / 'results')
    entries = checks(report)
    assert report['status'] == 'refused'
    assert all(entries['image.' + role]['status'] == 'refused' for role in document['roles'])


@pytest.mark.parametrize('failure', ['active measurement lock', 'probe timed out'])
def test_bootstrap_guard_or_probe_failure_blocks_all_images(
        document, local_probes, tmp_path, failure):
    local_probes['bootstrap_error'] = failure
    report = preflight.check_recipe(document, workdir=tmp_path / 'work',
                                   results_dir=tmp_path / 'results')
    entries = checks(report)
    assert entries['bootstrap']['status'] == 'refused'
    assert failure in entries['bootstrap']['reason']
    assert not any(argv[0] == 'docker' for argv in local_probes['calls'])
    assert all(entries['image.' + role]['status'] == 'unknown' for role in document['roles'])


@pytest.mark.parametrize('kind', ['existing', 'nested', 'symlink', 'dangling-ancestor',
                                  'ancestor-file', 'ram'])
def test_destination_refusals_preserve_existing_evidence(
        document, local_probes, monkeypatch, tmp_path, kind):
    evidence = tmp_path / 'evidence'
    evidence.write_text('preserve me')
    work, results = tmp_path / 'work', tmp_path / 'results'
    if kind == 'existing':
        work = evidence
    elif kind == 'nested':
        results = work / 'results'
    elif kind == 'symlink':
        (tmp_path / 'alias').symlink_to(preflight.ROOT, target_is_directory=True)
        work = tmp_path / 'alias' / 'new-attempt'
    elif kind == 'dangling-ancestor':
        (tmp_path / 'alias').symlink_to(tmp_path / 'nonexistent', target_is_directory=True)
        work = tmp_path / 'alias' / 'new-attempt'
    elif kind == 'ancestor-file':
        work = evidence / 'new-attempt'
    elif kind == 'ram':
        monkeypatch.setattr(preflight, 'is_memory_backed', lambda path, mounts: True)
    before = set(tmp_path.iterdir())
    report = preflight.check_recipe(document, workdir=work, results_dir=results)
    entries = checks(report)
    assert report['status'] == 'refused'
    assert any(item['status'] == 'refused' for name, item in entries.items()
               if name.startswith('destinations.'))
    assert evidence.read_text() == 'preserve me'
    assert set(tmp_path.iterdir()) == before


def test_cli_emits_json_report_and_refusal_exit(document, local_probes, tmp_path, capsys):
    local_probes['bootstrap_error'] = 'active measurement lock'
    path = tmp_path / 'recipe.json'
    path.write_text(json.dumps(document))
    assert recipes.main(['check', str(path), '--workdir', str(tmp_path / 'work'),
                         '--results-dir', str(tmp_path / 'results')]) == 2
    output = capsys.readouterr()
    assert not output.err
    assert checks(json.loads(output.out))['bootstrap']['status'] == 'refused'


def test_repository_digest_cannot_be_satisfied_by_tag_or_wrong_digest(
        document, local_probes, monkeypatch, tmp_path):
    requested = 'registry.example/bird@sha256:' + 'a' * 64
    document['roles']['target']['image'] = requested
    original = preflight.run_command
    def wrong_digest(argv, *, env=None):
        if list(map(str, argv))[-1] == requested:
            return json.dumps([{'Id': 'sha256:' + 'b' * 64,
                                'RepoTags': ['registry.example/bird:latest'],
                                'RepoDigests': ['registry.example/bird@sha256:' + 'c' * 64],
                                'Size': 1, 'Os': 'linux', 'Architecture': 'amd64'}])
        return original(argv, env=env)
    monkeypatch.setattr(preflight, 'run_command', wrong_digest)
    entries = checks(preflight.check_recipe(document, workdir=tmp_path / 'work',
                                            results_dir=tmp_path / 'results'))
    assert entries['image.target']['status'] == 'refused'
    assert 'digest' in entries['image.target']['reason'].lower()


def test_repository_digest_reports_actual_image_identity_and_metadata(
        document, local_probes, tmp_path):
    requested = 'registry.example/bird@sha256:' + 'd' * 64
    document['roles']['target']['image'] = requested
    entries = checks(preflight.check_recipe(document, workdir=tmp_path / 'work',
                                            results_dir=tmp_path / 'results'))
    item = entries['image.target']
    assert item['status'] == 'pass'
    assert item['details']['requested'] == requested
    assert item['details']['image_id'] == 'sha256:' + 'a' * 64
    assert item['details']['repo_digests'] == [requested]
    assert item['details']['platform'] == {'os': 'linux', 'architecture': 'amd64',
                                         'variant': None}
    assert item['details']['local_size_bytes'] == 12345
    assert item['details']['download_bytes'] is None


def test_ram_mount_with_spaces_is_not_misread_as_disk(
        document, local_probes, monkeypatch, tmp_path):
    parent = tmp_path / 'space in path'
    parent.mkdir()
    # These are real pure shared helpers, with the same octal spelling as /proc/mounts.
    import contention
    monkeypatch.setattr(preflight, 'filesystem_type', contention.filesystem_type)
    monkeypatch.setattr(preflight, 'is_memory_backed', contention.is_memory_backed)
    mounts = 'rootfs / ext4 rw 0 0\nnone ' + str(parent).replace(' ', r'\040') + ' tmpfs rw 0 0\n'
    original_read = Path.read_text
    def read(path, *args, **kwargs):
        if str(path) == '/proc/mounts':
            return mounts
        return original_read(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'read_text', read)
    entries = checks(preflight.check_recipe(document, workdir=parent / 'work',
                                            results_dir=tmp_path / 'results'))
    assert entries['destinations.workdir']['status'] == 'refused'
    assert 'RAM' in entries['destinations.workdir']['reason']
    assert not (parent / 'work').exists()
