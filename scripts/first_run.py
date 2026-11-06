#!/usr/bin/env python3
# Copyright (C) 2026 bgperf2 contributors. Apache-2.0.
"""Run the first SIMULATED FRR investigation; no daemon or measurement executes."""
import argparse
from importlib import metadata
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def check_environment():
    if sys.version_info[:2] != (3, 14):
        raise ValueError('Python 3.14 is required. Start with: '
                         'python3.14 scripts/bootstrap.py; then use venv/bin/python.')
    from scripts.bootstrap import pins
    issues = []
    for name, expected in pins((ROOT / 'requirements.lock').read_text()).items():
        try:
            actual = metadata.version(name)
        except metadata.PackageNotFoundError:
            actual = 'not installed'
        if actual != expected:
            issues.append(f'{name}: need {expected}, found {actual}')
    if issues:
        raise ValueError('Required package versions are not ready:\n  ' + '\n  '.join(issues)
                         + '\nCreate the locked environment with python3.14 scripts/bootstrap.py '
                         'and run this command with venv/bin/python. For an existing environment '
                         'that differs from the lock, follow docs/python-environment.md.')


def output_path(value):
    from recipe_bisection import safe
    output = safe(value)
    if output == ROOT or ROOT in output.parents:
        raise ValueError('Choose an absolute output directory outside the engine checkout.')
    if os.path.lexists(output):
        raise ValueError(f'Output already exists and is preserved: {output}. Choose a new directory.')
    if not output.parent.is_dir():
        raise ValueError(f'Output parent must already exist: {output.parent}. '
                         'Create that parent or choose a directory under your home directory.')
    return output


def describe_result(output, summary):
    pair = json.loads((output / 'return/pair/investigation.json').read_text())
    attempts = pair['correctness']['attempts']
    baseline = {row['name']: row['status'] for row in attempts['baseline']['assertions']}
    verification = json.loads((output / 'verification.json').read_text())
    if (summary.get('status') != 'passed' or summary.get('simulation') is not True
            or baseline.get('observer.count') != 'passed'
            or baseline.get('observer.prefixes') != 'failed'
            or attempts['candidate']['outcome'] != 'passed'
            or not summary['minimization']['confirmed']
            or summary['conclusion']['state'] != 'confirmed'
            or not verification or not all(row.get('valid') is True for row in verification.values())):
        raise RuntimeError('The example did not produce its expected verified simulated result.')
    best = summary['minimization']['best']
    peer_label = 'peer' if best['peers'] == 1 else 'peers'
    return [
        'SIMULATED workflow completed; no real FRR source, compiler, daemon or network ran.',
        'Baseline: route count passed; prefix identity failed as intended.',
        'Rollback candidate: correctness assertions passed.',
        f'Smaller reproducer: {best["peers"]} {peer_label}, {best["routes"]} prefixes per peer; confirmed.',
        'Modeled source boundary: confirmed with fresh simulated observations.',
        f'Verified portable report packages: {len(verification)}.',
        f'Open: {output / "REPORT.md"}',
        f'For your own inputs: {ROOT / "docs/first-run.md"} (Prepare your own investigation).',
        'Performance and host qualification remain unassessed.',
    ]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True,
                        help='new absolute directory outside the checkout, with an existing parent')
    args = parser.parse_args(argv)
    output = None
    try:
        check_environment()
        output = output_path(args.output)
        from scripts.frr_source_smoke import run_smoke
        print('Running the SIMULATED FRR maintainer example...', flush=True)
        # A user's optional live converter must not become part of this example.
        # The walkthrough selects its own scratch store and restores that binding.
        with patch.dict(os.environ):
            os.environ.pop('BGPERF_PARQUET_PYTHON', None)
            summary = run_smoke(output)
        for line in describe_result(output, summary):
            print(line)
    except (OSError, ValueError, RuntimeError) as exc:
        print('First run: ' + str(exc), file=sys.stderr)
        if output is not None and output.exists():
            print(f'Available output is preserved at {output}; inspect it before choosing a new directory.',
                  file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
