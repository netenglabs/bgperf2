#!/usr/bin/env python3
# Copyright (C) 2026 bgperf2 contributors. Apache-2.0.
"""Prepare a real inert local Git range and verified, unexecuted maintainer handoff.

Only local Git runs. No daemon source, compiler, Docker command, registry or
network service is used. All original and generated fixture files remain local.
"""
import argparse
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import shlex
import socket
import subprocess
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import recipes
import recipe_bisection as bisection
import recipe_handoff as handoff
import recipe_preflight as preflight
import recipe_source_range as source_range
from scripts.maintainer_smoke import Commands, _forbidden
from scripts.recipe_smoke import _write


def _hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(root, *arguments):
    env = preflight._environment()
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null',
               GIT_TERMINAL_PROMPT='0', GIT_NO_LAZY_FETCH='1',
               GIT_AUTHOR_DATE='2000-01-01T00:00:00+0000',
               GIT_COMMITTER_DATE='2000-01-01T00:00:00+0000')
    result = subprocess.run(['git', '-c', 'core.hooksPath=/dev/null',
        '-c', 'commit.gpgsign=false', '-C', str(root), *arguments],
        env=env, check=True, capture_output=True, text=True, timeout=15)
    return result.stdout.strip()


def _signature(source):
    return {'head': _git(source, 'rev-parse', 'HEAD'),
            'refs': _git(source, 'for-each-ref', '--format=%(refname) %(objectname)'),
            'status': _git(source, 'status', '--porcelain', '--untracked-files=all'),
            'index_sha256': _hash(source / '.git/index'),
            'config_sha256': _hash(source / '.git/config'),
            'tracked_sha256': _hash(source / 'main.c'),
            'dirty_fix_sha256': _hash(source / 'local-fix.txt'),
            'hook_sha256': _hash(source / '.git/hooks/post-checkout')}


def _run_smoke(output, predicate):
    output = bisection.safe(output)
    if output == ROOT or ROOT in output.parents:
        raise recipes.ContractError('Choose a fresh output outside the engine checkout')
    output.mkdir(mode=0o700)
    source = output / 'maintainer-source'
    source.mkdir()
    _git(source, 'init', '-q')
    _git(source, 'config', 'user.name', 'Inert preparation fixture')
    _git(source, 'config', 'user.email', 'fixture@example.invalid')
    (source / 'configure.ac').write_text('AC_INIT([inert-preparation-fixture], [0])\n')
    (source / 'Makefile.in').write_text('all:\n\t@echo INERT-FIXTURE-NEVER-BUILT\n')
    commits = []
    for index in range(4):
        (source / 'main.c').write_text(f'/* INERT local Git fixture, revision {index}. */\n')
        _git(source, 'add', '.')
        _git(source, 'commit', '-qm', f'fixture: revision {index}')
        commits.append(_git(source, 'rev-parse', 'HEAD'))
    # These pre-existing local changes represent a maintainer's candidate fix.
    (source / 'main.c').write_text('/* INERT uncommitted candidate fix. */\n')
    (source / 'local-fix.txt').write_text('INERT untracked fix evidence; never executed.\n')
    trap = output / 'UNEXPECTED-HOOK-EXECUTION'
    hook = source / '.git/hooks/post-checkout'
    hook.write_text('#!/bin/sh\ntouch ' + shlex.quote(str(trap)) + '\n')
    hook.chmod(0o755)
    before = _signature(source)
    _write(output / 'original-before.json', before)
    commands = Commands(output / 'commands')
    recipe_file = output / 'recipe.json'
    fixture = recipes.read_document(ROOT / 'examples/recipes/synthetic-ipv4.recipe.json')
    expected = 'target_crash' if predicate == 'target_crash' else 'experiment_completed'
    commands.call(recipes, ['export', '--batch', ROOT / 'examples/recipes/synthetic-ipv4.yaml',
        '--test', fixture['selection']['test'], '--cell', fixture['selection']['cell_key'],
        '--engine-revision', _git(ROOT, 'rev-parse', 'HEAD'),
        '--target-image', 'sha256:' + '1' * 64, '--generator-image', 'sha256:' + '2' * 64,
        '--observer-image', 'sha256:' + '3' * 64,
        '--question', 'INERT local source preparation; no daemon experiment is executed.',
        '--expected-outcome', expected, '--output', recipe_file])
    prepared = output / 'prepared-range'
    manifest = commands.call(source_range, ['prepare', '--recipe', recipe_file, '--source', source,
        '--good', commits[0], '--bad', commits[-1], '--toolchain-image', 'sha256:' + 'a' * 64,
        '--runtime-image', 'sha256:' + 'b' * 64, '--predicate', predicate, '--output', prepared])
    range_verification = commands.call(source_range, ['verify', prepared / 'source-range.json'])
    candidate = output / 'candidate-build-plan.json'
    commands.call(recipes, ['target-source-plan', recipe_file, '--source', source,
        '--revision', commits[-1], '--toolchain-image', 'sha256:' + 'a' * 64,
        '--runtime-image', 'sha256:' + 'b' * 64, '--include-dirty', '--output', candidate])
    baseline = prepared / manifest['candidates'][-1]['build_plan']
    future = {name: output / ('future-' + name) for name in ('builds', 'work', 'results', 'session')}
    packet = output / 'handoff'
    handoff_manifest = commands.call(handoff, ['prepare', '--source-range', prepared / 'source-range.json',
        '--baseline-build-plan', baseline, '--candidate-build-plan', candidate,
        '--build-root', future['builds'], '--work-root', future['work'],
        '--results-root', future['results'], '--session', future['session'], '--output', packet,
        '--compare-repetitions', 2, '--compare-order', 'shuffle', '--compare-seed', 7])
    handoff_verification = commands.call(handoff, ['verify', packet / 'handoff.json'])
    after = _signature(source)
    _write(output / 'original-after.json', after)
    if before != after or trap.exists() or any(path.exists() for path in future.values()):
        raise RuntimeError('Preparation changed original fixture source, executed a hook or created runtime destinations')
    if not range_verification['valid'] or not handoff_verification['valid']:
        raise RuntimeError('Prepared workflow did not verify')
    _write(output / 'commands.json', commands.records)
    _write(output / 'verification.json', {'source_range': range_verification, 'handoff': handoff_verification})
    result = {'status': 'passed', 'fixture_source': True, 'predicate': predicate,
        'recipe_sha256': manifest['recipe_sha256'], 'prepared_revisions': len(manifest['candidates']),
        'original_source_preserved': before == after, 'hook_executed': trap.exists(),
        'runtime_destinations_created': False, 'execution': 'not_requested',
        'handoff_readiness': {key: handoff_manifest[key] for key in
            ('local_image_availability', 'host_suitability', 'execution_authorization', 'performance_policy')},
        'index': str(output / 'REPORT.md')}
    _write(output / 'smoke.json', result)
    (output / 'REPORT.md').write_text('''# Prepare one local maintainer checkout

This example used **real local Git** with inert source fixtures. No BIRD source,
compiler, Docker image, daemon worker, download or network service ran.

1. [Original source before](original-before.json) and [after](original-after.json)
   agree, including HEAD, refs, index, configuration and dirty/untracked bytes.
2. [Prepared range](prepared-range/REPORT.md) contains all four consecutive
   revisions, isolated checkouts and frozen source/bisection plans. Original
   dirty changes remain outside the clean historical checkouts.
3. [Candidate plan](candidate-build-plan.json) explicitly captures that dirty
   local fix; no source edit or build is performed by the planner.
4. [Verified handoff](handoff/RUNBOOK.md) wires the selected baseline and fix to
   future build/worker artifact paths. Commands are instructions only; none ran.
5. [Verification receipts](verification.json) and [public commands](commands.json)
   retain the evidence. Future build/work/results/session roots do not exist.

Image availability, host suitability and execution authorization remain
unassessed. Performance policy remains disabled and calibration deferred.
The source fixture is not an actual routing bug/fix, and preparation does not
establish source trust, reproducible binaries or live qualification. Prepared
checkouts and handoff paths are location-bound; retain their original layout.
''')
    return result


def run_smoke(output, *, predicate='assertions'):
    recipes._choice(predicate, ('assertions', 'target_crash'), 'predicate')
    real_popen = subprocess.Popen

    def local_git_only(arguments, *args, **kwargs):
        if (not isinstance(arguments, (list, tuple)) or not arguments or
                arguments[0] != 'git' or kwargs.get('shell')):
            return _forbidden(arguments)
        command = list(map(str, arguments))
        position = 1
        while position < len(command):
            if command[position] in ('-c', '-C'):
                position += 2
            elif command[position] in ('--no-optional-locks', '--no-replace-objects'):
                position += 1
            else:
                break
        if position >= len(command) or command[position] not in {
                'init', 'config', 'add', 'commit', 'rev-parse', 'for-each-ref',
                'status', 'diff', 'ls-files', 'cat-file', 'ls-tree', 'clone', 'worktree'}:
            return _forbidden(arguments)
        if command[position] == 'clone':
            clone = command[position:]
            if (not {'--local', '--bare', '--no-hardlinks'} <= set(clone) or '--' not in clone
                    or len(clone[clone.index('--') + 1:]) != 2
                    or not all(Path(value).is_absolute() for value in clone[clone.index('--') + 1:])):
                return _forbidden(arguments)
        if command[position] == 'worktree' and (position + 1 == len(command) or command[position + 1] not in ('add', 'list')):
            return _forbidden(arguments)
        return real_popen(arguments, *args, **kwargs)

    with ExitStack() as stack:
        stack.enter_context(patch.object(subprocess, 'Popen', local_git_only))
        for name in ('__init__', 'connect', 'connect_ex', 'sendto'):
            stack.enter_context(patch.object(socket.socket, name, _forbidden))
        stack.enter_context(patch.object(socket, 'create_connection', _forbidden))
        return _run_smoke(output, predicate)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--predicate', choices=('assertions', 'target_crash'), default='assertions')
    args = parser.parse_args(argv)
    try:
        result = run_smoke(args.output, predicate=args.predicate)
    except (OSError, ValueError, RuntimeError) as exc:
        print('Checkout workflow smoke: ' + str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
