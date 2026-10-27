#!/usr/bin/env python3
"""Local Git gate. No benchmark execution and no remote Docker access."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
LOCK_NAMES = {'batch-driver.lock', '.block.lock', '.spot-boot.lock', '.bgperf-measurement.lock'}


def command(*args, capture=False, cwd=ROOT, env=None):
    return subprocess.run([str(a) for a in args], cwd=cwd, check=True,
                          text=True, capture_output=capture, env=env)


def local_docker_environment():
    env = os.environ.copy()
    env.pop('DOCKER_CONTEXT', None)
    env['DOCKER_HOST'] = os.environ.get('DOCKER_HOST', 'unix:///var/run/docker.sock')
    return env


def guard():
    # Check operator-owned descriptors, including inherited locks whose
    # original owner exited. Marker existence alone says nothing about flock.
    Path('/proc/locks').read_text()  # Linux lock visibility is required.
    for process in Path('/proc').glob('[0-9]*'):
        try:
            if process.stat().st_uid != os.getuid():
                continue
            try:
                descriptors = list((process / 'fd').iterdir())
            except PermissionError:
                continue  # protected system/user services, outside operator visibility
            for fd in descriptors:
                try:
                    try:
                        target = os.readlink(fd)
                    except PermissionError:
                        # Privileged inherited descriptors (e.g. systemd's
                        # terminal) can be unreadable even under this UID.
                        continue
                    if Path(target.removesuffix(' (deleted)')).name not in LOCK_NAMES:
                        continue
                    locks = (process / 'fdinfo' / fd.name).read_text()
                    if any(line.startswith('lock:') and 'FLOCK' in line
                           for line in locks.splitlines()):
                        raise ValueError('Active measurement: held batch lock ' + target)
                except FileNotFoundError:
                    continue
        except FileNotFoundError:
            continue
    host = os.environ.get('DOCKER_HOST', 'unix:///var/run/docker.sock')
    if not host.startswith('unix://'):
        raise ValueError('Quality gates require a local unix:// DOCKER_HOST')
    try:
        names = command('docker', '--host', host, 'ps', '--format', '{{.Names}}',
                        capture=True, env=local_docker_environment()).stdout.splitlines()
    except subprocess.CalledProcessError as exc:
        diagnostic = (exc.stderr or exc.stdout or 'Docker returned no diagnostic output.').strip()[-2000:]
        raise ValueError(
            f'Cannot inspect running containers at {host} (Docker exit {exc.returncode}): '
            f'{diagnostic}\nCheck that the local daemon is running and accessible from this execution '
            'context. Sandboxed agents must request approved host execution. '
            'The active-measurement guard remains required.') from exc
    active = [name for name in names if name.startswith('bgperf_')]
    if active:
        raise ValueError('Active measurement: running containers ' + ', '.join(active))


def git(*args):
    try:
        return command('git', '-C', ROOT, *args, capture=True).stdout
    except subprocess.CalledProcessError as exc:
        print((exc.stdout or '') + (exc.stderr or ''), file=sys.stderr, end='')
        raise


def push_ranges(stream):
    for line in stream:
        local_ref, local, remote_ref, remote = line.split()
        if set(local) == {'0'}:  # deletion sends no code
            continue
        # New refs conservatively check the whole tree (including sink/).
        base = command('git', '-C', ROOT, 'hash-object', '-t', 'tree', '/dev/null', capture=True).stdout.strip() if set(remote) == {'0'} else remote
        # Unknown remote objects must refuse, rather than silently skipping checks.
        if set(remote) != {'0'}:
            git('cat-file', '-e', remote + '^{tree}')
        yield base, local


def main():
    if len(sys.argv) < 2:
        raise ValueError('Usage: quality_gate.py pre-commit|pre-push|--guard-only')
    mode = sys.argv[1]
    if mode not in ('pre-commit', 'pre-push', '--guard-only'):
        raise ValueError('Unknown gate ' + mode)
    guard()
    if mode == '--guard-only':
        return
    ranges = list(push_ranges(sys.stdin)) if mode == 'pre-push' else []
    git('diff', '--check')
    git('diff', '--cached', '--check')
    if mode == 'pre-push' and ranges:
        head = git('rev-parse', 'HEAD').strip()
        if any(git('rev-parse', tip + '^{commit}').strip() != head
               for base, tip in ranges):
            raise ValueError('Push only the checked-out HEAD; check out other tips before pushing')
        if git('status', '--porcelain'):
            raise ValueError('Pre-push requires a clean working tree and index (including untracked files)')
    # Whitespace checks cover current edits. Historical fixture whitespace is
    # preserved; comparing a new ref to the empty tree would reject it.
    python = ROOT / 'venv/bin/python'
    command(python, '-I', ROOT / 'scripts/bootstrap.py', '--check')
    pure_env = os.environ.copy()
    pure_env.pop('BGPERF_ENGINE_ROOT', None)
    command(python, '-m', 'pytest', '-q', env=pure_env)
    if mode == 'pre-push' and (ROOT / 'bgp/scripts/batch_driver.py').is_file():
        binding = os.environ.get('BGPERF_ENGINE_ROOT', '')
        engine = Path(binding)
        if not binding or not engine.is_absolute() or not (engine / 'bgperf2.py').is_file():
            raise ValueError('Pre-push requires absolute BGPERF_ENGINE_ROOT to an engine checkout')
        engine_env = os.environ.copy()
        for key in git('rev-parse', '--local-env-vars').splitlines():
            engine_env.pop(key, None)
        if command('git', '-C', engine, 'status', '--porcelain',
                   capture=True, env=engine_env).stdout:
            raise ValueError('Bound engine must have a clean working tree and index')
        print('Engine integration revision: ' + command(
            'git', '-C', engine, 'rev-parse', 'HEAD', capture=True,
            env=engine_env).stdout.strip(), flush=True)
        command(engine / 'venv/bin/python', '-I', engine / 'scripts/bootstrap.py',
                '--check', env=engine_env)
        # The engine environment supplies engine imports. The explicit binding
        # prevents the integration tests from taking their optional skip path.
        command(engine / 'venv/bin/python', '-m', 'pytest', '-q', env=engine_env)
    if mode == 'pre-push' and (ROOT / 'sink').is_dir():
        if any(git('diff', '--name-only', base, tip, '--', 'sink/') for base, tip in ranges):
            guard()
            command(ROOT / 'scripts/sink_go_test.sh', env=local_docker_environment())


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        sys.exit('Quality gate refused: ' + str(exc))
