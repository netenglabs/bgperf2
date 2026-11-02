#!/usr/bin/env python3
"""Freeze a staged local diff, run one bounded review, retain structured findings."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

_spec = importlib.util.spec_from_file_location('review_dev_checks', Path(__file__).with_name('dev_checks.py'))
_checks = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_checks)
atomic_json, file_hash, git = _checks.atomic_json, _checks.file_hash, _checks.git
run_logged, snapshot = _checks.run_logged, _checks.snapshot

SCHEMA = 'bgperf2/local-review/v1'


def findings(value):
    if not isinstance(value, list):
        raise ValueError('findings must be a list')
    ids = set()
    for item in value:
        if (not isinstance(item, dict) or set(item) != {'id', 'severity', 'path', 'line', 'reason'}
                or not all(isinstance(item[k], str) and item[k].strip()
                           for k in ('id', 'severity', 'path', 'reason'))
                or item['id'] in ids or item['severity'] not in ('blocker', 'followup')
                or type(item['line']) is not int or item['line'] < 1):
            raise ValueError('Malformed or duplicate review finding')
        ids.add(item['id'])
    return value


def review(root, output, *, backend=None, timeout=300, previous=None):
    root, output = Path(root).resolve(), Path(output).resolve()
    _checks.normal_index(root)
    if output.exists():
        raise ValueError('Review output already exists; use a new output directory')
    # Logs must be ignored or external, so they cannot change the frozen source.
    if output.is_relative_to(root):
        relative = output.relative_to(root)
        if subprocess.run(['git', '-C', str(root), 'check-ignore', '-q', str(relative / 'probe')]).returncode:
            raise ValueError('Review output must be outside source or Git-ignored')
    if git(root, 'diff', '--name-only') or git(root, 'ls-files', '--others', '--exclude-standard'):
        raise ValueError('Stage the complete change before review (unstaged/untracked files remain)')
    flags = git(root, 'ls-files', '-v', '-z').split(b'\0')
    if any(line and (line[:1].islower() or line[:1] == b'S') for line in flags):
        raise ValueError('Clear assume-unchanged/skip-worktree flags before freezing a review')
    patch = git(root, 'diff', '--cached', '--binary', '--no-ext-diff', '--no-textconv')
    if not patch:
        raise ValueError('No staged change to review')
    source = snapshot(root)
    paths = git(root, 'diff', '--cached', '--name-only', '-z').decode().strip('\0').split('\0')
    prior = None
    if previous:
        prior = json.loads(Path(previous).read_text())
        if (prior.get('schema') != SCHEMA or prior.get('status') not in ('ready', 'blocked')
                or prior['source']['root'] != str(root) or prior['source']['head'] != source['head']
                or not set(paths) <= set(prior['paths'])):
            raise ValueError('Focused review requires the same baseline and reviewed file scope')
        findings(prior['findings'])
    output.mkdir(parents=True, mode=0o700)
    (output / 'staged.diff').write_bytes(patch)
    contract = (
        '/code-review: Review the frozen LOCAL staged diff at ' + str(output / 'staged.diff') + '.\n'
        'This is not a GitHub PR. Read repository guidance and relevant source using read-only tools. '
        'Do not run tests, edit files, commit, push, delegate, contact GitHub, or post comments. '
        'Report only concrete introduced defects with a supported failing scenario as blockers. '
        'Style, speculative hardening, performance opportunities and cleanup are followups. '
        'Return ONLY JSON: {"findings": [{"id":"R1","severity":"blocker|followup",'
        '"path":"relative/file","line":1,"reason":"concrete evidence and trigger"}],'
        '"resolved_ids": []}. Empty findings is valid. No markdown or prose.\n'
    )
    if prior:
        contract += ('FOCUSED verification only: assess the prior blocker IDs below and the fixes. '
                     'Put fixed IDs in resolved_ids. Retain unfixed blockers under the same IDs. '
                     'Do not repeat a broad review. New defects introduced by fixes may be reported.\n'
                     + json.dumps(prior['findings']))
    else:
        contract += 'One broad review only. resolved_ids must be empty.\n'
    (output / 'prompt.txt').write_text(contract)
    backend = backend or ['claude', '-p', '--permission-mode', 'plan', '--tools', 'Read,Grep,Glob',
                          '--strict-mcp-config', '--mcp-config', '{"mcpServers":{}}']
    result = {'schema': SCHEMA, 'status': 'not_ready', 'source': source, 'paths': paths,
              'diff_sha256': file_hash(output / 'staged.diff'), 'backend': backend,
              'previous': str(Path(previous).resolve()) if previous else None}
    try:
        run_logged(backend, cwd=root, env=os.environ.copy(), output=output / 'backend',
                   timeout=timeout, detect_api_errors=True, prompt=contract)
        if snapshot(root) != source:
            raise ValueError('Source changed during review; freeze and review again')
        raw = json.loads((output / 'backend/stdout.log').read_text())
        if not isinstance(raw, dict) or set(raw) != {'findings', 'resolved_ids'}:
            raise ValueError('Review response must match the JSON contract')
        items = findings(raw['findings'])
        if any(item['path'] not in paths for item in items):
            raise ValueError('Review finding is outside the staged file scope')
        resolved = raw['resolved_ids']
        old_ids = {item['id'] for item in prior['findings']} if prior else set()
        old_blockers = {item['id'] for item in prior['findings'] if item['severity'] == 'blocker'} if prior else set()
        if (not isinstance(resolved, list) or not all(isinstance(i, str) for i in resolved)
                or len(set(resolved)) != len(resolved) or not set(resolved) <= old_ids
                or set(resolved) & {i['id'] for i in items}):
            raise ValueError('Invalid resolved_ids')
        outstanding = old_blockers - set(resolved)
        retained = {item['id'] for item in items if item['severity'] == 'blocker'}
        if not outstanding <= retained:
            raise ValueError('Focused review omitted an unresolved blocker')
        result.update(findings=items, resolved_ids=resolved,
                      status='blocked' if retained else 'ready')
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        result['reason'] = str(exc)
    atomic_json(output / 'review.json', result)
    print(f"Review {result['status']}: {output / 'review.json'}", flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output', type=Path)
    parser.add_argument('--verify', type=Path, help='check an existing ready review against current source')
    parser.add_argument('--previous', type=Path, help='review.json for focused blocker verification')
    parser.add_argument('--timeout', type=float, default=300)
    parser.add_argument('--backend-json', help='explicit backend argv JSON array (no shell)')
    args = parser.parse_args()
    if args.verify:
        report = json.loads(args.verify.read_text())
        if (report.get('schema') != SCHEMA or report.get('status') != 'ready'
                or report.get('source') != snapshot(args.repo)):
            raise ValueError('Review is not ready for the current source/index/Git state')
        findings(report['findings'])
        if any(item['severity'] == 'blocker' for item in report['findings']):
            raise ValueError('Review still has a blocker')
        print('Review matches current frozen source: ' + str(args.verify))
        return 0
    if not args.output:
        parser.error('--output or --verify is required')
    backend = json.loads(args.backend_json) if args.backend_json else None
    if args.timeout <= 0 or (backend is not None and
                            (not isinstance(backend, list) or not backend or
                             not all(isinstance(s, str) and s for s in backend))):
        parser.error('positive timeout and a nonempty backend argv array required')
    result = review(args.repo, args.output, backend=backend, timeout=args.timeout, previous=args.previous)
    return 0 if result['status'] == 'ready' else 1


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        sys.exit('Review refused: ' + str(exc))
