"""Real scratch Git, fake validators/backends: no Docker, network or model calls."""
import importlib.util
import json
import os
import shlex
from pathlib import Path
import subprocess
import sys
import time

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


checks, reviewer = load('dev_checks'), load('local_review')


@pytest.fixture(autouse=True)
def isolate_hook_git_environment(monkeypatch):
    # A real pre-commit supplies GIT_INDEX_FILE pointing at the caller's index.
    # Scratch repositories and nested git clone must never inherit that binding.
    for key in list(os.environ):
        if key.startswith('GIT_'):
            monkeypatch.delenv(key)


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / 'repo'
    root.mkdir()
    def git(*args):
        env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
        return subprocess.check_output(['git', '-C', str(root), *args], env=env)
    git('init', '-q')
    git('config', 'user.name', 'Test')
    git('config', 'user.email', 'test@example.invalid')
    git('config', 'core.hooksPath', '/dev/null')
    (root / '.gitignore').write_text('/.dev-checks/\n')
    (root / 'source.py').write_text('original\n')
    git('add', '.')
    git('commit', '-qm', 'test: initial')
    return root, git


def validator(root, code=None):
    return [sys.executable, '-c', code or
            "from pathlib import Path; p=Path('.dev-checks/count'); p.write_text(str(int(p.read_text())+1) if p.exists() else '1'); print('validated')"]


def test_reuses_only_identical_success_and_keeps_logs(repo):
    root, _ = repo
    args = validator(root)
    first = checks.check(root, 'pure', args, python=sys.executable)
    assert checks.check(root, 'pure', args, python=sys.executable) == first
    assert (root / '.dev-checks/count').read_text() == '1'
    receipt = json.loads(first.read_text())
    assert 'validated' in (Path(receipt['logs']) / 'stdout.log').read_text()
    assert 'environment_sha256' in receipt['identity']


@pytest.mark.parametrize('change', ['tracked', 'untracked', 'hidden', 'index', 'head', 'env', 'profile', 'binding', 'expired', 'corrupt'])
def test_receipt_invalidation(repo, tmp_path, change):
    root, git = repo
    env = os.environ.copy()
    binding = root  # Explicit bound sources participate independently.
    args = validator(root)
    path = checks.check(root, 'pure', args, env=env, bindings=[binding])
    profile = 'pure'
    if change in ('tracked', 'hidden', 'binding'):
        if change == 'hidden':
            git('update-index', '--assume-unchanged', 'source.py')
        (root / 'source.py').write_text('changed')
    elif change == 'untracked':
        (root / 'new.py').write_text('new')
    elif change == 'index':
        git('update-index', '--chmod=+x', 'source.py')
    elif change == 'head':
        git('commit', '--allow-empty', '-qm', 'test: metadata')
    elif change == 'env':
        env['VALIDATOR_OPTION'] = 'changed'
    elif change == 'profile':
        profile = 'integration'
    elif change == 'expired':
        value = json.loads(path.read_text()); value['finished_at'] = 0
        path.write_text(json.dumps(value))
    elif change == 'corrupt':
        path.write_text('not-json')
    checks.check(root, profile, args, env=env, bindings=[binding])
    assert (root / '.dev-checks/count').read_text() == '2'


def test_failed_and_mutating_checks_never_publish_success(repo):
    root, _ = repo
    with pytest.raises(subprocess.CalledProcessError):
        checks.check(root, 'bad', validator(root, 'raise SystemExit(1)'))
    with pytest.raises(ValueError, match='changed during'):
        checks.check(root, 'mutating', validator(root, "from pathlib import Path; Path('source.py').write_text('mutated')"))
    assert not list((root / '.dev-checks/receipts').glob('*.json'))
    assert len(list((root / '.dev-checks/runs').glob('*/result.json'))) == 2


def test_python_inventory_change_invalidates(repo, monkeypatch):
    root, _ = repo
    monkeypatch.setattr(checks, 'python_identity', lambda *a: ['version-a'])
    checks.check(root, 'pure', validator(root), python=sys.executable)
    monkeypatch.setattr(checks, 'python_identity', lambda *a: ['version-b'])
    checks.check(root, 'pure', validator(root), python=sys.executable)
    assert (root / '.dev-checks/count').read_text() == '2'


def backend(value):
    return [sys.executable, '-c', 'import sys; sys.stdin.read(); print(' + repr(json.dumps(value)) + ')']


def stage(repo):
    root, git = repo
    (root / 'source.py').write_text('candidate\n')
    git('add', 'source.py')


def finding(severity='blocker'):
    return dict(id='R1', severity=severity, path='source.py', line=1, reason='supported failing input')


def test_broad_then_focused_review(repo, tmp_path):
    root, _ = repo
    stage(repo)
    one = tmp_path / 'one'
    result = reviewer.review(root, one, backend=backend(dict(findings=[finding()], resolved_ids=[])))
    assert result['status'] == 'blocked'
    (root / 'source.py').write_text('fixed\n'); repo[1]('add', 'source.py')
    two = tmp_path / 'two'
    result = reviewer.review(root, two, previous=one / 'review.json',
                             backend=backend(dict(findings=[], resolved_ids=['R1'])))
    assert result['status'] == 'ready'
    assert 'FOCUSED verification only' in (two / 'prompt.txt').read_text()
    assert 'fixed' in (two / 'staged.diff').read_text()


@pytest.mark.parametrize('response', [dict(findings=[], resolved_ids=['unknown']),
    dict(findings=[finding(), finding()], resolved_ids=[]), dict(findings='none', resolved_ids=[]),
    dict(findings=[], resolved_ids=[], extra=True), []])
def test_invalid_review_never_ready(repo, tmp_path, response):
    stage(repo)
    result = reviewer.review(repo[0], tmp_path / 'review', backend=backend(response))
    assert result['status'] == 'not_ready'
    assert (tmp_path / 'review/backend/stdout.log').exists()


def test_followup_is_nonblocking(repo, tmp_path):
    stage(repo)
    result = reviewer.review(repo[0], tmp_path / 'review',
                             backend=backend(dict(findings=[finding('followup')], resolved_ids=[])))
    assert result['status'] == 'ready' and result['findings']


def test_api_failure_exit_zero_and_timeout(repo, tmp_path):
    stage(repo)
    for name, code in [('api', "print('API Error: ENOTFOUND', flush=True); import time; time.sleep(5)"),
                       ('timeout', 'import time; time.sleep(5)')]:
        start = time.monotonic()
        result = reviewer.review(repo[0], tmp_path / name,
                                 backend=[sys.executable, '-c', code], timeout=.2)
        assert result['status'] == 'not_ready' and time.monotonic() - start < 3
        assert ('API failure' in result['reason'] if name == 'api' else 'timeout' in result['reason'])


def test_focused_review_cannot_drop_blocker(repo, tmp_path):
    stage(repo)
    one = tmp_path / 'one'
    reviewer.review(repo[0], one, backend=backend(dict(findings=[finding()], resolved_ids=[])))
    result = reviewer.review(repo[0], tmp_path / 'two', previous=one / 'review.json',
                             backend=backend(dict(findings=[], resolved_ids=[])))
    assert result['status'] == 'not_ready' and 'omitted' in result['reason']


@pytest.mark.parametrize('excerpt', [
    '    except FileNotFoundError:',
    "markers = ('enotfound', 'eai_again')",
    "print('API Error: ENOTFOUND')",
])
def test_reviewer_reading_source_is_not_an_api_failure(repo, tmp_path, excerpt):
    stage(repo)
    code = ('import sys,time; print(' + repr(excerpt) + ', file=sys.stderr, flush=True); '
            'time.sleep(.15); print(\'{"findings":[],"resolved_ids":[]}\')')
    result = reviewer.review(repo[0], tmp_path / 'review', backend=[sys.executable, '-c', code])
    assert result['status'] == 'ready'


def test_unstaged_changes_refuse_before_backend(repo, tmp_path):
    stage(repo)
    (repo[0] / 'source.py').write_text('unstaged')
    with pytest.raises(ValueError, match='Stage the complete'):
        reviewer.review(repo[0], tmp_path / 'review', backend=['does-not-exist'])


def test_review_verify_rejects_changed_source(repo, tmp_path, monkeypatch):
    stage(repo)
    output = tmp_path / 'review'
    reviewer.review(repo[0], output, backend=backend(dict(findings=[], resolved_ids=[])))
    monkeypatch.setattr(sys, 'argv', ['review', '--repo', str(repo[0]), '--verify', str(output / 'review.json')])
    assert reviewer.main() == 0
    (repo[0] / 'source.py').write_text('changed again')
    with pytest.raises(ValueError, match='not ready'):
        reviewer.main()


def test_review_backend_mutation_never_ready(repo, tmp_path):
    stage(repo)
    result = reviewer.review(repo[0], tmp_path / 'review', backend=[sys.executable, '-c',
        "from pathlib import Path; Path('source.py').write_text('mutated'); print('{\"findings\":[],\"resolved_ids\":[]}')"])
    assert result['status'] == 'not_ready' and 'Source changed' in result['reason']


def test_bound_checkout_changes_invalidate_independently(repo, tmp_path):
    root, _ = repo
    # A second clean Git checkout is an explicit source dependency.
    bound = tmp_path / 'bound'
    subprocess.run(['git', '-C', str(root), 'clone', '-q', str(root), str(bound)], check=True)
    checks.check(root, 'integration', validator(root), bindings=[bound])
    (bound / 'source.py').write_text('bound change')
    checks.check(root, 'integration', validator(root), bindings=[bound])
    assert (root / '.dev-checks/count').read_text() == '2'


def test_alternate_index_runs_uncached_without_refusal(repo, tmp_path, monkeypatch):
    monkeypatch.setenv('GIT_INDEX_FILE', str(tmp_path / 'alternate-index'))
    assert checks.check(repo[0], 'pure', validator(repo[0])) is None
    assert checks.check(repo[0], 'pure', validator(repo[0])) is None
    assert (repo[0] / '.dev-checks/count').read_text() == '2'
    assert not list((repo[0] / '.dev-checks/receipts').glob('*.json'))


def test_review_refuses_hidden_source_flags(repo, tmp_path):
    stage(repo)
    repo[1]('update-index', '--assume-unchanged', 'source.py')
    with pytest.raises(ValueError, match='Clear assume-unchanged'):
        reviewer.review(repo[0], tmp_path / 'review', backend=['does-not-exist'])


def test_shell_bookkeeping_does_not_invalidate_receipts(repo, monkeypatch):
    root, git = repo
    checks.check(root, 'pure', validator(root))
    monkeypatch.setenv('_', 'different-shell-command')
    monkeypatch.setenv('SHLVL', '99')
    monkeypatch.setenv('CODEX_TOOL_CALL_ID', 'new-invocation')
    monkeypatch.setenv('GIT_INDEX_FILE', str(root / '.git/index'))
    checks.check(root, 'pure', validator(root))
    assert (root / '.dev-checks/count').read_text() == '1'


def test_directory_symlink_referents_participate(repo, tmp_path):
    root, git = repo
    target = tmp_path / 'skill'
    target.mkdir(); (target / 'SKILL.md').write_text('original')
    (root / 'skill').symlink_to(target, target_is_directory=True)
    git('add', 'skill')
    checks.check(root, 'pure', validator(root))
    (target / 'SKILL.md').write_text('changed')
    checks.check(root, 'pure', validator(root))
    assert (root / '.dev-checks/count').read_text() == '2'


def test_valid_review_can_quote_api_error(repo, tmp_path):
    stage(repo)
    item = finding('followup'); item['reason'] = 'Handle API Error: ENOTFOUND diagnostics'
    code = 'import sys,time; sys.stdin.read(); print(' + repr(json.dumps(dict(findings=[item], resolved_ids=[]))) + ', flush=True); time.sleep(.15)'
    result = reviewer.review(repo[0], tmp_path / 'review', backend=[sys.executable, '-c', code])
    assert result['status'] == 'ready'


def test_real_git_commit_a_uses_uncached_validation(repo, tmp_path):
    root, git = repo
    hooks = tmp_path / 'hooks'; hooks.mkdir()
    argv = [sys.executable, '-I', str(ROOT / 'scripts/dev_checks.py'), '--repo', str(root),
            '--profile', 'commit', '--python', sys.executable, '--', sys.executable, '-c', 'pass']
    hook = hooks / 'pre-commit'
    hook.write_text('#!/bin/sh\nexec ' + shlex.join(argv) + '\n')
    hook.chmod(0o755)
    git('config', 'core.hooksPath', str(hooks))
    (root / 'source.py').write_text('commit via temporary index')
    git('commit', '-aqm', 'test: automatic staging')
    results = [json.loads(p.read_text()) for p in (root / '.dev-checks/runs').glob('*/result.json')]
    assert any(result['status'] == 'passed_uncached' for result in results)


def test_focused_review_can_resolve_followups_alongside_blockers(repo, tmp_path):
    stage(repo)
    followup = finding('followup'); followup['id'] = 'R2'
    one = tmp_path / 'one'
    reviewer.review(repo[0], one, backend=backend(dict(findings=[finding(), followup], resolved_ids=[])))
    result = reviewer.review(repo[0], tmp_path / 'two', previous=one / 'review.json',
                             backend=backend(dict(findings=[], resolved_ids=['R1', 'R2'])))
    assert result['status'] == 'ready'


def test_nested_suite_preserves_callers_index_binding(tmp_path):
    caller_index = tmp_path / 'caller-index'
    caller_index.write_bytes(b'caller index must remain untouched')
    env = os.environ.copy()
    env['GIT_INDEX_FILE'] = str(caller_index)
    result = subprocess.run([sys.executable, '-m', 'pytest', '-q',
                             str(Path(__file__)) + '::test_bound_checkout_changes_invalidate_independently'],
                            cwd=ROOT, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert caller_index.read_bytes() == b'caller index must remain untouched'


def test_public_snapshot_cli_is_readable_by_offline_consumers(repo):
    root, git = repo
    before = git('rev-parse', 'HEAD')
    output = subprocess.check_output([sys.executable, '-I', str(ROOT / 'scripts/dev_checks.py'),
                                      '--repo', str(root), '--snapshot'], text=True)
    document = json.loads(output)
    assert document['schema'] == 'bgperf2/local-source/v1'
    assert document['snapshot'] == checks.snapshot(root)
    assert git('rev-parse', 'HEAD') == before and git('status', '--porcelain') == b''
