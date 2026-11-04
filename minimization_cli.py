# Copyright (C) 2026 bgperf2 contributors. Apache-2.0.
"""Standalone explicit CLI for bounded reproducer minimization."""
import argparse
import json
from pathlib import Path
import sys

import recipes


def parser():
    command = argparse.ArgumentParser(description=__doc__)
    commands = command.add_subparsers(dest='command', required=True)
    plan = commands.add_parser('plan', help='freeze an offline bounded search')
    plan.add_argument('recipe')
    plan.add_argument('--assertion', required=True)
    plan.add_argument('--dimension', choices=('peers', 'routes'), action='append')
    plan.add_argument('--min-peers', type=int, default=1)
    plan.add_argument('--min-routes', type=int, default=1)
    plan.add_argument('--max-trials', type=int, default=20)
    plan.add_argument('--timeout', type=float, default=120)
    plan.add_argument('-o', '--output', required=True)
    init = commands.add_parser('init', help='create owned local metadata; no worker')
    init.add_argument('plan')
    init.add_argument('--workdir', required=True)
    init.add_argument('--results-dir', required=True)
    for name in ('status', 'next', 'reserve', 'record', 'recover', 'step', 'report'):
        operation = commands.add_parser(name)
        operation.add_argument('session')
        if name == 'status':
            operation.add_argument('--text', action='store_true')
        if name == 'record':
            operation.add_argument('--result')
        if name == 'step':
            operation.add_argument('--execute', action='store_true',
                                   help='launch exactly one bounded existing recipe worker')
        if name == 'report':
            operation.add_argument('--output-dir', required=True)
    for name in ('verify', 'rebuild'):
        operation = commands.add_parser(name)
        operation.add_argument('report')
        if name == 'rebuild':
            operation.add_argument('--output-dir', required=True)
    return command


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        import recipe_minimization as core
        import recipe_minimization_session as session
        if args.command == 'plan':
            value = core.make_plan(recipes.read_document(args.recipe), assertion=args.assertion,
                dimensions=args.dimension if args.dimension is not None else ('peers', 'routes'),
                min_peers=args.min_peers, min_routes=args.min_routes,
                max_trials=args.max_trials, timeout=args.timeout)
            path = Path(args.output)
            with path.open('x') as destination:
                destination.write(json.dumps(value, indent=2, sort_keys=True) + '\n')
        elif args.command == 'init':
            value = session.init_session(recipes.read_document(args.plan), workdir=args.workdir,
                                         results_dir=args.results_dir)
        elif args.command == 'status':
            value = session.status_session(args.session)
        elif args.command == 'next':
            value = session.next_trial(args.session)
        elif args.command == 'reserve':
            value = session.reserve_trial(args.session)
        elif args.command == 'record':
            value = session.record_trial(args.session, result=args.result)
        elif args.command == 'recover':
            value = session.recover_trial(args.session)
        elif args.command == 'step':
            value = session.step_session(args.session, execute=args.execute)
        elif args.command == 'report':
            value = session.report(args.session, output_dir=args.output_dir)
        elif args.command == 'verify':
            value = session.verify_report(args.report)
        else:
            value = session.rebuild_report(args.report, output_dir=args.output_dir)
        if args.command == 'status' and args.text:
            print(f"{value.get('state')}: {value.get('conclusion')}; "
                  f"{value.get('trials_recorded')} trials recorded")
        else:
            print(json.dumps(value, indent=2, sort_keys=True))
        return 2 if args.command == 'step' and args.execute and value.get('state') == 'operational_refused' else 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(f'minimization: {exc}', file=sys.stderr)
        return 2
