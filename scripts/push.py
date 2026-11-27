#!/usr/bin/env python3
"""Run the pre-push gate offline first, then push the current branch.

`git push` opens its connection to the remote before it runs the pre-push hook,
and the hook runs the whole Python suite, minutes in which that connection sits
idle. A remote that closes idle connections ends the push after the checks have
passed. This runs the same hook through `git hook run` first, which gives it the
same environment, arguments and stdin as a real push and opens no connection,
so the checks finish before anything connects. The hook inside the real push
then finds the receipt they left (scripts/dev_checks.py) and only repeats the
quick guards. Nothing is weakened: the suite runs in full either way, and the
push still runs its own hook, which still refuses.

It pushes only the checked-out branch to its configured upstream, the one shape
the gate accepts (`Push only the checked-out HEAD`). Standard library only.
"""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
ZERO = '0' * 40


def git(root, *args, capture=True):
    # Only stdout is captured: Git's own stderr ("Permission denied
    # (publickey)", a rejected push) must reach the user, not be folded into
    # an exit status.
    result = subprocess.run(['git', '-C', str(root), *args], check=True, text=True,
                            stdout=subprocess.PIPE if capture else None)
    return result.stdout.strip() if capture else None


def config(root, key):
    '''A config value, or None where it is unset.'''
    result = subprocess.run(['git', '-C', str(root), 'config', '--get', key],
                            text=True, stdout=subprocess.PIPE)
    return result.stdout.strip() if result.returncode == 0 else None


def hook_path(root):
    '''The pre-push hook a push would run, or None when none is installed.

    `rev-parse --git-path` honours `core.hooksPath`, which is where this
    checkout's hooks live (`.githooks`).
    '''
    path = Path(git(root, 'rev-parse', '--git-path', 'hooks/pre-push'))
    if not path.is_absolute():
        path = Path(root) / path
    return path if path.is_file() and os.access(path, os.X_OK) else None


def push_plan(root):
    """What `git push <remote> refs/heads/<branch>:<merge>` would hand its hook.

    Returns `(remote, url, refspec, stdin_line)`. The remote's current tip is
    asked of the remote itself (`ls-remote`) rather than read from the
    remote-tracking ref, which can be stale; that is the value a push gives
    its hook. A branch the remote does not have gets the zero id, as in a push.
    """
    branch = subprocess.run(['git', '-C', str(root), 'symbolic-ref', '-q', '--short', 'HEAD'],
                            text=True, capture_output=True)
    if branch.returncode:
        raise ValueError('HEAD is detached; check out the branch to push')
    branch = branch.stdout.strip()
    merge = config(root, 'branch.{0}.merge'.format(branch))
    # The remote `git push` itself would pick: a triangular setup pushes
    # somewhere other than where it fetches from.
    remote = (config(root, 'branch.{0}.pushRemote'.format(branch))
              or config(root, 'remote.pushDefault')
              or config(root, 'branch.{0}.remote'.format(branch)))
    if not remote or not merge:
        raise ValueError('Branch {0} has no upstream; push it once with '
                         '`git push -u <remote> {0}`'.format(branch))
    if remote == '.':
        raise ValueError('Branch {0} tracks a local branch; there is nothing to push to'.format(branch))
    url = git(root, 'remote', 'get-url', '--push', remote)
    local = git(root, 'rev-parse', '--verify', 'HEAD^{commit}')
    # `ls-remote` matches its pattern against the tail of every ref, so
    # `refs/heads/x/refs/heads/main` would match `refs/heads/main` too.
    exact = [line.split()[0] for line in
             git(root, 'ls-remote', '--refs', remote, merge).splitlines()
             if line.split()[1:] == [merge]]
    remote_tip = exact[0] if exact else ZERO
    stdin_line = 'refs/heads/{0} {1} {2} {3}\n'.format(branch, local, merge, remote_tip)
    return remote, url, 'refs/heads/{0}:{1}'.format(branch, merge), stdin_line


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--repo', type=Path, default=ROOT)
    parser.add_argument('--check-only', action='store_true',
                        help='run the pre-push gate and stop without pushing')
    args = parser.parse_args(argv)
    if hook_path(args.repo) is None:
        # Not a refusal: no gate would run at all, here or in a plain push.
        raise ValueError('no pre-push hook is installed; run '
                         '`git config core.hooksPath .githooks` first')
    remote, url, refspec, stdin_line = push_plan(args.repo)
    print('Pre-push gate for {0} -> {1} ({2}), before connecting'.format(
        refspec, remote, stdin_line.split()[3][:12]), flush=True)
    with tempfile.NamedTemporaryFile('w', suffix='.pre-push') as refs:
        refs.write(stdin_line)
        refs.flush()
        hook = subprocess.run(['git', '-C', str(args.repo), 'hook', 'run',
                               '--to-stdin=' + refs.name, 'pre-push', '--', remote, url])
    if hook.returncode:
        raise ValueError('the pre-push gate refused; nothing was pushed')
    if args.check_only:
        return
    git(args.repo, 'push', remote, refspec, capture=False)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        sys.exit('push refused: ' + str(exc))
