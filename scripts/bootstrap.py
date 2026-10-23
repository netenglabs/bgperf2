#!/usr/bin/env python3
"""Install this checkout's hashed Python 3.14 environment and run its pure suite."""
import argparse
import json
import re
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCK = ROOT / 'requirements.lock'
PYTHON = ROOT / 'venv/bin/python'
PIN = re.compile(r'([A-Za-z0-9_.-]+)==([^\s;\\]+)')


def pins(text):
    result = {}
    for line in text.splitlines():
        clean = line.strip().rstrip('\\').rstrip()
        if (not clean or clean.startswith('#')
                or clean == '--only-binary :all:'
                or re.fullmatch(r'--hash=sha256:[a-f0-9]{64}', clean)):
            continue
        match = PIN.fullmatch(clean)
        if match:
            name = re.sub(r'[-_.]+', '-', match[1]).lower()
            result[name] = match[2]
        else:
            raise ValueError('Unsupported dependency line: ' + line)
    return result


def run(*args, capture=False):
    return subprocess.run([str(PYTHON), '-I', *args], cwd=ROOT, check=True,
                          text=True, capture_output=capture)


def verify():
    expected = pins(LOCK.read_text())
    try:
        frozen = pins(run('-m', 'pip', 'freeze', '--all', '--exclude', 'pip',
                          capture=True).stdout)
    except ValueError as exc:
        raise SystemExit(str(exc) + '. Move venv aside and bootstrap again.')
    # pip hides argparse as a stdlib backport, even with freeze --all.
    # nsenter still installs it; inspect metadata so it cannot escape the lock.
    inventory = json.loads(run('-c',
        'import importlib.metadata, json; '
        'print(json.dumps({d.metadata["Name"]: d.version '
        'for d in importlib.metadata.distributions()}))', capture=True).stdout)
    actual = pins('\n'.join(name + '==' + version
                            for name, version in inventory.items()
                            if name.lower() != 'pip'))
    expected_freeze = {key: val for key, val in expected.items()
                       if key != 'argparse' or key in frozen}
    if actual != expected or frozen != expected_freeze:
        missing = {key: val for key, val in expected.items()
                   if actual.get(key) != val}
        extra = {key: val for key, val in actual.items() if key not in expected}
        raise SystemExit('Environment differs from lock: missing/changed=' +
                         repr(missing) + ', extra=' + repr(extra) +
                         ', frozen=' + repr(frozen) +
                         '. Move venv aside and bootstrap a fresh environment.')
    run('-m', 'pip', 'check')
    print('Installed inventory and pip freeze match requirements.lock (' + str(len(expected)) +
          ' packages; pip bootstrap tooling excluded).', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true',
                        help='Only check an existing environment against the lock')
    args = parser.parse_args()
    if sys.version_info[:2] != (3, 14):
        parser.error('Use Python 3.14: python3.14 scripts/bootstrap.py')
    try:
        pins(LOCK.read_text())
    except ValueError as exc:
        parser.error(str(exc))
    environment = ROOT / 'venv'
    existing = environment.exists()
    if not existing:
        if args.check:
            parser.error('No venv; run bootstrap without --check first')
        venv.EnvBuilder(with_pip=True, symlinks=True).create(environment)
    if not (environment / 'pyvenv.cfg').is_file() or not PYTHON.is_file():
        parser.error('Incomplete venv; move it aside and bootstrap again')
    config = (environment / 'pyvenv.cfg').read_text()
    if not re.search(r'^include-system-site-packages = false$', config, re.M):
        parser.error('venv must be isolated; move it aside and bootstrap again')
    version = run('-c', 'import sys; print(sys.version_info.major, '
                  'sys.version_info.minor)', capture=True).stdout.strip()
    if version != '3 14':
        parser.error('Existing venv uses another Python; move it aside first')
    if not existing:
        run('-m', 'pip', 'install', '--require-hashes', '--only-binary=:all:',
            '-r', str(LOCK))
    verify()  # Existing environments must match before any test runs.
    if not args.check:
        run('-m', 'pytest', 'tests/', '-q')


if __name__ == '__main__':
    try:
        main()
    except subprocess.CalledProcessError as exc:
        raise SystemExit('Bootstrap command failed: ' + str(exc))
    except (OSError, ValueError, TypeError) as exc:
        raise SystemExit(str(exc) + '\nCannot prepare the environment. '
                         'Move an incomplete venv aside and bootstrap again.')
