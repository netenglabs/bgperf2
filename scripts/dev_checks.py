#!/usr/bin/env python3
"""Local, conservative validation receipts; standard library only, usable by consumers."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import tempfile
import time
import uuid

SCHEMA = 'bgperf2/local-check/v1'
MAX_AGE = 24 * 60 * 60


class Uncacheable(ValueError):
    """A valid check invocation whose source context cannot be safely reused."""


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def git(root, *args):
    # Hook-local Git variables must not redirect a bound checkout's commands.
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env['GIT_NO_REPLACE_OBJECTS'] = '1'
    return subprocess.check_output(['git', '-C', str(root), *args], env=env)


def file_hash(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def referent_hash(path, ancestors=frozenset()):
    """Fingerprint directory skill aliases too, rejecting recursive links."""
    info = path.stat()
    inode = (info.st_dev, info.st_ino)
    if inode in ancestors:
        raise Uncacheable('Recursive source symlink: ' + str(path))
    if path.is_symlink():
        return digest([os.readlink(path), referent_hash(path.resolve(), ancestors)])
    if stat.S_ISREG(info.st_mode):
        return digest([info.st_mode, file_hash(path)])
    if stat.S_ISDIR(info.st_mode):
        return digest([(p.name, referent_hash(p, ancestors | {inode})) for p in sorted(path.iterdir())])
    raise Uncacheable('Special source symlink referent: ' + str(path))


def normal_index(root):
    """Hook alternate indexes cannot be mistaken for the default staged tree."""
    selected_index = os.environ.get('GIT_INDEX_FILE')
    if selected_index:
        normal_index = Path(os.fsdecode(git(root, 'rev-parse', '--path-format=absolute', '--git-path', 'index')).strip())
        selected = Path(selected_index)
        if not selected.is_absolute():
            selected = Path.cwd() / selected
        if selected.resolve() != normal_index.resolve():
            raise Uncacheable('Alternate Git index: running validation without receipt reuse')


def snapshot(root):
    """Hash actual bytes, including unstaged/untracked files and hidden index edits."""
    root = Path(root).resolve()
    names = set(git(root, 'ls-files', '-z', '--cached', '--others', '--exclude-standard').split(b'\0')) - {b''}
    entries = []
    for name in sorted(names):
        path = root / os.fsdecode(name)
        try:
            mode = path.lstat().st_mode
        except FileNotFoundError:
            entries.append((os.fsdecode(name), 'missing'))
            continue
        if stat.S_ISLNK(mode):
            # Include the referent too: tracked symlinks can point outside Git.
            entries.append((os.fsdecode(name), mode, os.readlink(path), referent_hash(path)))
        elif stat.S_ISREG(mode):
            entries.append((os.fsdecode(name), mode, file_hash(path)))
        else:
            raise Uncacheable('Cannot receipt directories/submodules/special files: ' + str(path))
    return {'root': str(root), 'files': digest(entries),
            'head': git(root, 'rev-parse', '--verify', 'HEAD').decode().strip(),
            'index': digest(git(root, 'ls-files', '--stage', '-z').hex()),
            'index_flags': digest(git(root, 'ls-files', '-v', '-z').hex()),
            'status': digest(git(root, 'status', '--porcelain=v1', '-z').hex()),
            'refs': digest(git(root, 'show-ref', '--head').hex()),
            'config': digest(git(root, 'config', '--list', '--null', '--show-origin').hex())}


def python_identity(python, env):
    probe = ('import importlib.metadata as m,json,platform,sys; '
             'print(json.dumps([sys.version,sys.prefix,platform.platform(),'
             'sorted((d.metadata["Name"],d.version) for d in m.distributions())]))')
    return json.loads(subprocess.check_output([str(python), '-I', '-c', probe], env=env, text=True, timeout=30))


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def run_logged(argv, *, cwd, env, output, timeout, detect_api_errors=False, prompt=None):
    """Bound the entire process group; retain complete stdout/stderr even on failure."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    started = time.monotonic()
    next_progress = started + 30
    reason = None
    markers = ('enotfound', "can't reach api server", 'api error:', 'eai_again')
    with tempfile.TemporaryFile() as input_stream, (output / 'stdout.log').open('wb') as stdout, (output / 'stderr.log').open('wb') as stderr:
        if prompt is not None:
            input_stream.write(prompt.encode())
            input_stream.seek(0)
        process = subprocess.Popen(argv, cwd=cwd, env=env, stdout=stdout, stderr=stderr,
                                   stdin=input_stream if prompt is not None else subprocess.DEVNULL,
                                   start_new_session=True)
        try:
            while process.poll() is None:
                if time.monotonic() >= next_progress:
                    print(f'Still running ({int(time.monotonic() - started)}s); logs: {output}', flush=True)
                    next_progress = time.monotonic() + 30
                if time.monotonic() - started >= timeout:
                    reason = 'timeout'
                    break
                if detect_api_errors:
                    for name in ('stdout.log', 'stderr.log'):
                        with (output / name).open('rb') as stream:
                            stream.seek(max(0, (output / name).stat().st_size - 8192))
                            lines = stream.read().decode(errors='replace').lower().splitlines()
                            # Do not mistake a quoted error in valid JSON findings for an API failure.
                            if any(any(marker in line for marker in markers)
                                   for line in lines if not line.lstrip().startswith(('{', '[', '"'))):
                                reason = 'review backend/API failure'
                                break
                    if reason:
                        break
                time.sleep(0.05)
        finally:
            # Also terminate surviving children after their parent exits.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
    if reason:
        raise ValueError(f'{reason}; logs: {output}')
    if process.returncode:
        raise subprocess.CalledProcessError(process.returncode, argv)


def check(root, profile, argv, *, env=None, python=None, bindings=(), timeout=1200):
    root = Path(root).resolve()
    env = dict(os.environ if env is None else env)
    argv = [str(arg) for arg in argv]
    cache = root / '.dev-checks'
    cache.mkdir(mode=0o700, exist_ok=True)
    # Refuse a cache that would become part of the source fingerprint.
    if subprocess.run(['git', '-C', str(root), 'check-ignore', '-q', '.dev-checks/probe'],
                      env={k: v for k, v in env.items() if not k.startswith('GIT_')}).returncode:
        raise ValueError('Add /.dev-checks/ to this checkout\'s .gitignore before using receipts')
    def identity():
        optional_pythons = {key: python_identity(value, env) for key, value in env.items()
                            if key.startswith('BGPERF_') and key.endswith('_PYTHON') and value}
        # These shell/hook bookkeeping variables do not alter the child command's
        # behavior. A nondefault index is excluded from reuse before this point.
        stable_env = {k: v for k, v in env.items() if k not in
                      {'_', 'PWD', 'OLDPWD', 'SHLVL', 'GIT_INDEX_FILE', 'GIT_PREFIX', 'CODEX_TOOL_CALL_ID'}}
        return {'source': snapshot(root), 'bindings': [snapshot(p) for p in bindings],
                'profile': profile, 'argv': argv, 'environment_sha256': digest(stable_env),
                'python': python_identity(python, env) if python else None,
                'optional_pythons': optional_pythons,
                'runner_sha256': file_hash(Path(__file__)), 'schema': SCHEMA}
    try:
        normal_index(root)
        before = identity()
    except Uncacheable as exc:
        output = cache / 'runs' / uuid.uuid4().hex
        print(f'{exc}; running {profile} uncached; logs: {output}', flush=True)
        try:
            run_logged(argv, cwd=root, env=env, output=output, timeout=timeout)
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            atomic_json(output / 'result.json', {'schema': SCHEMA, 'status': 'failed', 'reason': str(error)})
            raise
        atomic_json(output / 'result.json', {'schema': SCHEMA, 'status': 'passed_uncached', 'reason': str(exc)})
        return None
    key = digest(before)
    receipt = cache / 'receipts' / (key + '.json')
    try:
        previous = json.loads(receipt.read_text())
        age = time.time() - previous['finished_at']
        if (previous['schema'] == SCHEMA and previous['identity'] == before
                and previous['status'] == 'passed' and 0 <= age <= MAX_AGE):
            print(f'Reusing {profile}: {receipt}', flush=True)
            return receipt
    except (OSError, ValueError, KeyError, TypeError):
        pass
    output = cache / 'runs' / uuid.uuid4().hex
    print(f'Running {profile}; logs: {output}', flush=True)
    try:
        run_logged(argv, cwd=root, env=env, output=output, timeout=timeout)
        if identity() != before:
            raise ValueError('Source/environment changed during validation; no successful receipt')
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        atomic_json(output / 'result.json', {'schema': SCHEMA, 'status': 'failed', 'reason': str(exc)})
        for name in ('stdout.log', 'stderr.log'):
            if (output / name).exists():
                print((output / name).read_text(errors='replace')[-4000:], file=sys.stderr)
        raise
    atomic_json(receipt, {'schema': SCHEMA, 'status': 'passed', 'identity': before,
                          'finished_at': time.time(), 'logs': str(output)})
    print('\n'.join((output / 'stdout.log').read_text(errors='replace').splitlines()[-3:]), flush=True)
    print(f'Passed {profile}: {receipt}', flush=True)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--profile', required=True)
    parser.add_argument('--python', type=Path)
    parser.add_argument('--binding', type=Path, action='append', default=[])
    parser.add_argument('--timeout', type=float, default=1200)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    argv = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not argv or args.timeout <= 0:
        parser.error('a command and positive timeout are required')
    check(args.repo, args.profile, argv, python=args.python, bindings=args.binding, timeout=args.timeout)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        sys.exit('Validation refused: ' + str(exc))
