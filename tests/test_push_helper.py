"""scripts/push.py against a real temporary repository and a bare remote."""
import importlib.util
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('push_under_test', ROOT / 'scripts/push.py')
push = importlib.util.module_from_spec(spec)
spec.loader.exec_module(push)


@pytest.fixture(autouse=True)
def plain_git_environment(monkeypatch):
    # The suite runs inside the commit hook, whose GIT_* variables (an
    # alternate index among them) would otherwise redirect these commands
    # onto the checkout being committed.
    for key in list(os.environ):
        if key.startswith('GIT_'):
            monkeypatch.delenv(key)
    monkeypatch.setenv('GIT_CONFIG_NOSYSTEM', '1')
    monkeypatch.setenv('GIT_CONFIG_GLOBAL', os.devnull)


def run(cwd, *args):
    return subprocess.run(['git', '-C', str(cwd), *args], check=True, text=True,
                          capture_output=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    remote = tmp_path / 'remote.git'
    work = tmp_path / 'work'
    subprocess.run(['git', 'init', '-q', '--bare', str(remote)], check=True)
    subprocess.run(['git', 'init', '-q', '-b', 'feature', str(work)], check=True)
    for key, value in (('user.name', 'test'), ('user.email', 'test@example.invalid')):
        run(work, 'config', key, value)
    (work / 'a').write_text('one\n')
    run(work, 'add', 'a')
    run(work, 'commit', '-q', '-m', 'one')
    run(work, 'remote', 'add', 'origin', str(remote))
    run(work, 'push', '-q', '-u', 'origin', 'feature')
    (work / 'a').write_text('two\n')
    run(work, 'commit', '-q', '-am', 'two')
    return work, remote


def recording_hook(tmp_path, work, status=0):
    hooks = tmp_path / 'hooks'
    hooks.mkdir()
    hook = hooks / 'pre-push'
    hook.write_text('#!/bin/sh\nn=$(ls {0} | wc -l)\n'
                    'env | sort > {0}/call-$n.env\npwd > {0}/call-$n.pwd\n'
                    'cat > {0}/call-$n.stdin\necho "$@" > {0}/call-$n.args\n'
                    'exit {1}\n'.format(tmp_path / 'calls', status))
    hook.chmod(0o755)
    (tmp_path / 'calls').mkdir()
    run(work, 'config', 'core.hooksPath', str(hooks))
    return tmp_path / 'calls'


def test_the_plan_is_what_a_push_of_the_branch_hands_its_hook(repo):
    work, remote = repo
    name, url, refspec, line = push.push_plan(work)
    assert (name, url, refspec) == ('origin', str(remote),
                                    'refs/heads/feature:refs/heads/feature')
    assert line == 'refs/heads/feature {0} refs/heads/feature {1}\n'.format(
        run(work, 'rev-parse', 'HEAD'), run(remote, 'rev-parse', 'feature'))


def test_the_remote_tip_is_asked_of_the_remote_not_the_tracking_ref(repo, tmp_path):
    work, remote = repo
    # Someone else pushed; this checkout has not fetched.
    other = tmp_path / 'other'
    subprocess.run(['git', 'clone', '-q', '-b', 'feature', str(remote), str(other)], check=True)
    run(other, '-c', 'user.name=o', '-c', 'user.email=o@example.invalid',
        'commit', '-q', '--allow-empty', '-m', 'theirs')
    run(other, 'push', '-q')
    *_, line = push.push_plan(work)
    assert line.split()[3] == run(remote, 'rev-parse', 'feature')
    assert line.split()[3] != run(work, 'rev-parse', 'origin/feature')


def test_a_branch_the_remote_lacks_gets_the_zero_id(repo):
    work, _ = repo
    run(work, 'checkout', '-q', '-b', 'fresh')
    run(work, 'config', 'branch.fresh.remote', 'origin')
    run(work, 'config', 'branch.fresh.merge', 'refs/heads/fresh')
    *_, line = push.push_plan(work)
    assert line.split()[3] == push.ZERO


def test_a_detached_head_is_refused(repo):
    work, _ = repo
    run(work, 'checkout', '-q', '--detach')
    with pytest.raises(ValueError, match='detached'):
        push.push_plan(work)


def test_a_branch_without_an_upstream_is_refused(repo):
    work, _ = repo
    run(work, 'checkout', '-q', '-b', 'loose')
    with pytest.raises(ValueError, match='no upstream'):
        push.push_plan(work)


def test_the_offline_run_hands_the_hook_exactly_what_the_push_does(repo, tmp_path):
    work, remote = repo
    calls = recording_hook(tmp_path, work)
    push.main(['--repo', str(work)])
    assert run(remote, 'rev-parse', 'feature') == run(work, 'rev-parse', 'HEAD')
    # Four files per call, so the second call is numbered 4. Environment,
    # directory, arguments and stdin are what the receipt identity is made
    # of; if any differed, the push's own hook would rerun the suite.
    for part in ('stdin', 'args', 'env', 'pwd'):
        assert (calls / ('call-0.' + part)).read_text() == \
            (calls / ('call-4.' + part)).read_text(), part


def test_a_refusing_gate_pushes_nothing(repo, tmp_path):
    work, remote = repo
    before = run(remote, 'rev-parse', 'feature')
    calls = recording_hook(tmp_path, work, status=1)
    with pytest.raises(ValueError, match='nothing was pushed'):
        push.main(['--repo', str(work)])
    assert run(remote, 'rev-parse', 'feature') == before
    assert len(list(calls.glob('*.stdin'))) == 1


def test_a_missing_hook_is_not_called_a_refusal(repo, tmp_path):
    work, remote = repo
    run(work, 'config', 'core.hooksPath', str(tmp_path / 'no-hooks'))
    before = run(remote, 'rev-parse', 'feature')
    with pytest.raises(ValueError, match='no pre-push hook is installed'):
        push.main(['--repo', str(work)])
    assert run(remote, 'rev-parse', 'feature') == before


def test_the_hook_is_found_where_core_hookspath_points(repo, tmp_path):
    work, _ = repo
    recording_hook(tmp_path, work)
    assert push.hook_path(work) == tmp_path / 'hooks' / 'pre-push'


def test_only_the_exact_upstream_ref_is_its_tip(repo):
    work, remote = repo
    # A ref whose name *ends* in refs/heads/feature, which ls-remote's tail
    # match also returns, and which sorts first.
    run(work, 'push', '-q', 'origin', 'HEAD:refs/heads/a/refs/heads/feature')
    listed = run(work, 'ls-remote', '--refs', 'origin', 'refs/heads/feature')
    assert listed.splitlines()[0].endswith('refs/heads/a/refs/heads/feature')
    *_, line = push.push_plan(work)
    assert line.split()[3] == run(remote, 'rev-parse', 'refs/heads/feature')
    assert line.split()[3] != run(work, 'rev-parse', 'HEAD')


@pytest.mark.parametrize('key', ['branch.feature.pushRemote',
                                 'remote.pushDefault'])
def test_the_push_remote_wins_as_it_does_for_git_push(repo, tmp_path, key):
    work, _ = repo
    fork = tmp_path / 'fork.git'
    subprocess.run(['git', 'init', '-q', '--bare', str(fork)], check=True)
    run(work, 'remote', 'add', 'fork', str(fork))
    run(work, 'config', key, 'fork')
    name, url, _, line = push.push_plan(work)
    assert (name, url) == ('fork', str(fork))
    assert line.split()[3] == push.ZERO


def test_gits_own_error_reaches_the_user(repo, tmp_path, capfd):
    work, _ = repo
    recording_hook(tmp_path, work)
    run(work, 'remote', 'set-url', 'origin', str(tmp_path / 'gone.git'))
    with pytest.raises(subprocess.CalledProcessError):
        push.main(['--repo', str(work)])
    assert 'gone.git' in capfd.readouterr().err


def test_check_only_never_pushes(repo, tmp_path):
    work, remote = repo
    before = run(remote, 'rev-parse', 'feature')
    recording_hook(tmp_path, work)
    push.main(['--repo', str(work), '--check-only'])
    assert run(remote, 'rev-parse', 'feature') == before
