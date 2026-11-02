# Copyright (C) 2026 bgperf2 contributors. Apache-2.0.
"""Portable descriptive comparisons reconstructed from verified local evidence."""
import csv
import hashlib
import io
import json
import math
import os
from pathlib import Path
import statistics

import recipes
from recipe_investigation import _copy_package, _load, _read_attempt, _write
from recipe_results import _digest_file, _regular_bytes, _regular_file

SCHEMA = 'bgperf2/comparison/v1alpha1'
SCOPE = 'Descriptive repeated baseline/candidate observations; no calibrated performance verdict.'
POLICY = {'qualification': 'not_assessed', 'policy': 'disabled',
          'reason': 'Separate operator calibration must select effect sizes, repetition budget and a named regression policy.'}
ROLES = ('baseline', 'candidate')
MISSING_STATUSES = ('not_run', 'setup_refused', 'harness_failed', 'interrupted', 'inconclusive')
METRICS = {
    'memory': {
        'target_cgroup_peak_bytes': ('bytes', 'peak_bytes', 'peak_definition', 'work/diagnostics.json'),
        'target_cgroup_ending_bytes': ('bytes', 'ending_bytes', 'ending_definition', 'work/diagnostics.json'),
        'target_sampled_peak_bytes': ('bytes', 'sampled_peak_bytes', 'sampled_peak_definition', 'work/diagnostics.json'),
        'target_delivery_sampled_peak_gib': ('GiB', 'max mem (GB)',
            'Legacy maximum sampled whole-container memory during the delivery window; bytes divided by 2**30 and rounded to three decimals, not a lifetime cgroup peak.',
            'work/stats.csv')},
    'cpu': {'target_peak_cpu_percent': ('percent', 'max cpu %',
            'Legacy target CPU maximum during the delivery window; percent of one CPU, not total CPU work.', 'work/stats.csv')},
    'timing': {
        'monitor_elapsed_seconds': ('seconds', 'elapsed (s)',
            'Legacy whole-second monitor convergence elapsed time; resolution at least one second.', 'work/stats.csv'),
        'total_runtime_seconds': ('seconds', 'total time',
            'Legacy total runtime including setup; distinct from monitor convergence.', 'work/stats.csv')}}


def _safe_path(path):
    path = Path(path)
    if not path.is_absolute() or any(item.is_symlink() for item in (path, *path.parents)):
        raise recipes.ContractError('Comparison paths must be absolute and contain no symlinks')
    return path


def _optional_json(root, result, relative):
    if relative not in {item['path'] for item in result['artifacts'] if item['availability'] == 'present'}:
        return None, f'{relative} was not collected.'
    try:
        value = _load(root, relative)
        if not isinstance(value, dict):
            raise recipes.ContractError('Expected a JSON object')
        return value, None
    except (ValueError, UnicodeError, recipes.ContractError) as exc:
        return None, f'{relative}: raw evidence retained; inspection failed: {exc}'


def _stats(root, result):
    relative = 'work/stats.csv'
    if relative not in {item['path'] for item in result['artifacts'] if item['availability'] == 'present'}:
        return None, 'Final stats row was not collected; partial samples do not replace it.'
    try:
        with _regular_file(root, relative) as source:
            data = source.read(1024 * 1024 + 1)
        if len(data) > 1024 * 1024:
            raise ValueError('stats row exceeds the 1 MiB bound')
        rows = list(csv.reader(io.StringIO(data.decode('utf-8'))))
        if len(rows) != 2 or len(rows[0]) != len(rows[1]) or len(set(rows[0])) != len(rows[0]):
            raise ValueError('expected one row and unique named columns')
        row = dict(zip(rows[0], rows[1]))
        if row.get('failed') == 'FAILED':
            return None, 'Final stats row marks the experiment failed.'
        return row, None
    except (ValueError, UnicodeError, csv.Error) as exc:
        return None, f'Final stats row is unreadable: {exc}'


def _number(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) and number >= 0 else None
    except (ValueError, TypeError, OverflowError):
        return None


def _observations(attempt, root, result):
    row, row_reason = _stats(root, result) if result else (None, attempt['reason'])
    diagnostic = ((attempt.get('diagnostics') or {}).get('value') or {})
    memory = (diagnostic.get('memory') or {}).get('target') or {}
    output = {}
    for category, fields in METRICS.items():
        output[category] = {}
        for name, (units, source, definition, artifact) in fields.items():
            value, reason = None, None
            diagnostic_memory = artifact == 'work/diagnostics.json'
            boundary = memory.get(definition) if diagnostic_memory else definition
            accounting = (memory.get('accounting') if diagnostic_memory else
                          'Sampled whole-container Docker memory usage, including file-backed/cache costs; legacy GiB column rounded to three decimals.'
                          if category == 'memory' else None)
            if diagnostic_memory:
                boundary = boundary if isinstance(boundary, str) and boundary.strip() else None
                accounting = accounting if isinstance(accounting, str) and accounting.strip() else None
            if attempt['status'] != 'completed':
                reason = f"Attempt status is {attempt['status']}; excluded from descriptive performance distributions."
            elif diagnostic_memory:
                raw = memory.get(source)
                if (isinstance(raw, int) and not isinstance(raw, bool) and _number(raw) is not None
                        and isinstance(boundary, str) and boundary.strip()
                        and isinstance(accounting, str) and accounting.strip()):
                    value = raw
                else:
                    recorded_reason = memory.get('reason')
                    reason = (recorded_reason if isinstance(recorded_reason, str) and recorded_reason.strip() else
                              'No finite supported byte observation with an explicit accounting boundary and definition.')
            elif row is None:
                reason = row_reason
            else:
                value = _number(row.get(source))
                if value is None:
                    reason = f'{source}: no finite nonnegative observation.'
                elif category == 'memory' and value == 0:
                    value, reason = None, 'Legacy max mem (GB) is the never-sampled zero sentinel; no sampled extreme is established.'
            output[category][name] = {'value': value, 'units': units,
                'reason': reason, 'definition': boundary,
                'accounting': accounting, 'source': artifact}
    return output, row


def _attempt(plan, entry, path):
    from recipe_assertions import evaluate_assertions
    missing = {'status': entry['status'], 'reason': entry['reason']}
    evidence, recipe, result = _read_attempt(path, 'attempts/' + entry['id'], missing)
    if result is not None:
        if recipe != plan['recipe']:
            raise recipes.ContractError('Every comparison attempt must use the exact same frozen recipe')
        if evidence['target'] != plan['targets'][entry['role']]:
            raise recipes.ContractError('Attempt target differs from its planned role identity')
        if evidence['status'] != entry['status']:
            raise recipes.ContractError('Attempt status disagrees with its verified result package')
    item = {key: entry[key] for key in ('id', 'role', 'pair', 'index', 'status', 'reason')}
    item['package'] = 'attempts/' + entry['id'] + '/result.json' if path else None
    item['evidence'] = evidence
    item['assertions'] = evaluate_assertions(plan['assertions'], plan['recipe'], path) if path else None
    item['source_attempt_id'] = result['attempt']['id'] if result else None
    observed_timeout = item['assertions']['worker_deadline']['timeout_seconds'] if path else None
    if observed_timeout is not None and observed_timeout != plan['timeout']:
        raise recipes.ContractError('Observed worker timeout differs from the frozen comparison plan')
    item['measurements'], row = _observations(evidence, Path(path).parent if path else None, result)
    diagnostics = ((evidence.get('diagnostics') or {}).get('value') or {})
    options, options_reason = _optional_json(Path(path).parent, result, 'work/diagnostic-options.json') if path else (None, entry['reason'])
    item['diagnostic_mode'] = {'value': options.get('mode') if options else None, 'reason': options_reason}
    item['diagnostic_overhead'] = diagnostics.get('instrumentation')
    # These are recorded observations, never new host qualification thresholds.
    item['host_load'] = {key: _number((row or {}).get(key)) for key in
                         ('max foreign cpu %', 'min idle%', 'min free mem (GB)')}
    return item, result


def _distribution(attempts, category, name):
    observations = [{'id': item['id'], **item['measurements'][category][name]} for item in attempts]
    values = [item['value'] for item in observations if item['value'] is not None]
    boundaries = {(item['definition'], item['accounting']) for item in observations if item['value'] is not None}
    reason = ('Accounting definitions differ within this role.' if len(boundaries) > 1 else
              'No usable completed-attempt observations.' if not values else None)
    count = len(values)
    stats = {key: None for key in ('mean', 'median', 'min', 'max', 'stdev', 'cv_percent')}
    reasons = {}
    if reason is None:
        try:
            mean = statistics.mean(values)
            stats.update(mean=mean, median=statistics.median(values), min=min(values), max=max(values))
            if count >= 2:
                stats['stdev'] = statistics.stdev(values)
                if mean > 0:
                    stats['cv_percent'] = stats['stdev'] / mean * 100
                else:
                    reasons['cv_percent'] = 'A positive mean is required.'
            else:
                reasons.update(stdev='At least two observations are required.', cv_percent='At least two observations are required.')
        except (OverflowError, ValueError):
            reason = 'Derived arithmetic exceeded the finite supported range.'
            stats = dict.fromkeys(stats, None)
        for key, value in stats.items():
            if value is not None and _number(value) is None:
                stats[key] = None
                reasons[key] = 'Derived arithmetic exceeded the finite supported range.'
    if reason:
        reasons.update({key: reason for key in stats})
    return {'n': count, 'planned': len(attempts),
        'not_run': sum(item['status'] == 'not_run' for item in attempts),
        'failed': sum(item['status'] not in ('completed', 'not_run') for item in attempts),
        'missing': sum(item['status'] == 'completed' and observation['value'] is None
                       for item, observation in zip(attempts, observations)),
        'observations': observations, 'statistics': stats, 'withheld_reasons': reasons}


def _confounders(plan, attempts):
    issues = []
    def issue(code, reason, ids):
        issues.append({'code': code, 'reason': reason, 'attempts': ids})
    present = [item for item in attempts if item['package']]
    missing = [item['id'] for item in attempts if item['status'] != 'completed']
    if missing:
        issue('incomplete_attempts', 'Missing, failed or not-run attempts prevent a complete paired description.', missing)
    host_fields = ('hostname', 'kernel_release', 'architecture', 'boot_id', 'cpu_model', 'cpu_count', 'cpu_affinity')
    hosts = [(((item['evidence'].get('host') or {}).get('value') or {}), item['id']) for item in present]
    unknown_hosts = [name for host, name in hosts if any(host.get(key) is None for key in host_fields)]
    if unknown_hosts:
        issue('incomplete_host_identity', 'Host identity/capacity observations are incomplete; hardware qualification remains unassessed.', unknown_hosts)
    changed = [field for field in host_fields if len({json.dumps(host.get(field), sort_keys=True) for host, _ in hosts}) > 1]
    if changed:
        issue('changed_host', 'Host observations changed: ' + ', '.join(changed) + '.', [item['id'] for item in present])
    identities = [item['id'] for item in present if not all(item['evidence']['observed_images'].get(role) for role in ('target', 'generator', 'observer'))]
    if identities:
        issue('incomplete_observed_images', 'Exact observed target, generator and observer image identities are incomplete.', identities)
    for role in ('generator', 'observer'):
        observed = {item['evidence']['observed_images'].get(role) for item in present}
        if len(observed - {None}) > 1:
            issue('changed_' + role, 'The observed ' + role + ' image changed.', [item['id'] for item in present])
    instrumentation = {role: plan['targets'][role]['provenance']['instrumentation'] for role in ROLES}
    if set(instrumentation.values()) != {'optimized'}:
        issue('instrumentation', 'Declared target instrumentation: ' + json.dumps(instrumentation, sort_keys=True) + '; optimized binary properties are not independently verified.', [item['id'] for item in present])
    overhead = [item['id'] for item in present if item['diagnostic_mode']['value'] != 'none']
    if overhead:
        issue('diagnostic_overhead', 'Basic or unrecorded diagnostic probes have uncalibrated overhead.', overhead)
    mismatched_modes = [item['id'] for item in present if item['diagnostic_mode']['value'] != plan['diagnostics']]
    if mismatched_modes:
        issue('diagnostic_mode', 'Observed diagnostic mode differs from the frozen comparison plan or is unavailable.', mismatched_modes)
    contention = [item['id'] for item in present if (item['host_load']['max foreign cpu %'] or 0) > 0]
    if contention:
        issue('foreign_cpu_observed', 'Nonzero foreign CPU was recorded; no new calibrated contention threshold is inferred.', contention)
    from findings import HOST_IDLE_PERCENT
    saturated = [item['id'] for item in present if item['host_load']['min idle%'] is not None and
                 item['host_load']['min idle%'] <= HOST_IDLE_PERCENT]
    if saturated:
        issue('host_cpu_saturated', 'Host idle reached the existing engine saturation boundary; scheduler contention can affect intervals.', saturated)
    incorrect = [item['id'] for item in present if item['assertions']['outcome'] != 'passed' or
                 item['assertions']['worker_deadline']['satisfied'] is not True]
    if incorrect:
        issue('correctness_not_established', 'A named correctness assertion or the recorded worker budget failed or was unmeasured.', incorrect)
    unknown_load = [item['id'] for item in present if item['host_load']['max foreign cpu %'] is None or item['host_load']['min idle%'] is None]
    if unknown_load:
        issue('incomplete_host_load', 'Host CPU contention observations are incomplete.', unknown_load)
    if not present:
        issue('no_packages', 'No verified attempt packages are available.', [])
    return issues


def _assemble(plan, attempts):
    source_ids = [item['source_attempt_id'] for item in attempts if item['source_attempt_id'] is not None]
    if len(source_ids) != len(set(source_ids)):
        raise recipes.ContractError('Comparison repetitions require unique original result attempt IDs')
    distributions = {category: {name: {role: _distribution([item for item in attempts if item['role'] == role], category, name)
                      for role in ROLES} for name in fields} for category, fields in METRICS.items()}
    confounders = _confounders(plan, attempts)
    deltas = {}
    for category, fields in distributions.items():
        deltas[category] = {}
        for name, roles in fields.items():
            left, right = (roles[role] for role in ROLES)
            observations = left['observations'] + right['observations']
            boundaries = {(item['definition'], item['accounting']) for item in observations if item['value'] is not None}
            reason = ('Recorded confounders prevent a controlled descriptive delta.' if confounders else
                      'Every planned pair needs a valid observation with the same definition.' if
                      any(item['value'] is None for item in observations) or len(boundaries) != 1 else None)
            left_median, right_median = left['statistics']['median'], right['statistics']['median']
            if reason is None and (left_median is None or right_median is None):
                reason = 'Role medians are unavailable.'
            value = right_median - left_median if reason is None else None
            percent = value / left_median * 100 if value is not None and left_median > 0 else None
            if percent is not None and not math.isfinite(percent):
                percent = None
            deltas[category][name] = {'candidate_minus_baseline_median': value,
                'percent_of_baseline_median': percent, 'reason': reason,
                'percent_reason': reason if reason else None if percent is not None else 'A positive baseline median and finite arithmetic are required.',
                'qualification': 'unqualified_descriptive_only'}
    correctness = {}
    for role in ROLES:
        selected = [item for item in attempts if item['role'] == role]
        correctness[role] = {outcome: sum(item['assertions'] is not None and item['assertions']['outcome'] == outcome for item in selected)
                             for outcome in ('passed', 'failed', 'inconclusive')}
        correctness[role]['unavailable'] = sum(item['assertions'] is None for item in selected)
    return {'schema': SCHEMA, 'scope': SCOPE, 'plan': plan,
        'recipe_sha256': recipes.recipe_sha256(plan['recipe']), 'attempts': attempts,
        'correctness': correctness, 'measurements': distributions,
        'descriptive_deltas': deltas, 'confounders': confounders, 'performance': POLICY}


def _render(report):
    lines = ['# Baseline/candidate comparison', '', SCOPE, '',
        'Question: ' + report['plan']['recipe']['reproduction']['question'], '',
        'Performance qualification: **not_assessed**. Regression policy: **disabled**.', POLICY['reason'], '',
        'Order: ' + report['plan']['order'] + '; seed: ' + str(report['plan']['seed']) +
        '; repetitions per role: ' + str(report['plan']['repetitions']) + '.', '',
        '| Index | Pair | Role | Experiment | Assertions | Evidence |', '| --- | --- | --- | --- | --- | --- |']
    for item in report['attempts']:
        assertions = item['assertions']['outcome'] if item['assertions'] else 'unavailable'
        package = f"[package]({item['package']})" if item['package'] else item['reason'].replace('\n', ' ').replace('|', '\\|')
        lines.append(f"| {item['index']} | {item['pair']} | {item['role']} | {item['status']} | {assertions} | {package} |")
    lines += ['', 'Each package retains experiment status, reproduction outcome and individual correctness assertions separately.',
        'Count agreement does not establish route or attribute correctness.', '',
        '| Role | Assertions passed | Failed | Inconclusive | Unavailable |',
        '| --- | --- | --- | --- | --- |']
    for role, counts in report['correctness'].items():
        lines.append(f"| {role} | {counts['passed']} | {counts['failed']} | {counts['inconclusive']} | {counts['unavailable']} |")
    lines += ['', '## Target identities', '',
        '| Role | Immutable target image | Declared instrumentation | Source commit |',
        '| --- | --- | --- | --- |']
    for role, target in report['plan']['targets'].items():
        provenance = target['provenance']
        source = provenance.get('source') or {}
        lines.append(f"| {role} | `{target['image']}` | {provenance['instrumentation']} | `{source.get('commit')}` |")
    lines += ['', 'Full build flags, toolchain/runtime identities, dirty-patch hashes and provenance limits remain in the frozen target documents.', '',
        '## Measurements', '',
        'All distributions are descriptive, including confounded observations. They use completed attempts only. Failed attempts and work that has not run are counted separately.',
        'Null observations retain their reasons and are never replaced by zero. Standard deviation uses n−1.', '',
        '| Measurement | Role | n | Missing | Failed | Not run | Median | Min–max | Sample SD | CV % |',
        '| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |']
    for category, fields in report['measurements'].items():
        for name, roles in fields.items():
            for role, distribution in roles.items():
                stats = distribution['statistics']
                lines.append(f"| {category}.{name} | {role} | {distribution['n']} | {distribution['missing']} | {distribution['failed']} | {distribution['not_run']} | {stats['median']} | {stats['min']}–{stats['max']} | {stats['stdev']} | {stats['cv_percent']} |")
    lines += ['', 'Exact definitions, accounting boundaries, individual observations, withheld reasons and unqualified descriptive deltas are recorded in `comparison.json`.',
        'Legacy monitor elapsed time has at least one-second resolution; total runtime includes setup. Peak CPU is not total CPU work.',
        'Container memory includes file-backed/cache costs; it is not process RSS or a leak diagnosis.', '',
        '## Unqualified descriptive differences', '',
        '| Measurement | Candidate minus baseline median | Percent of baseline | Withheld reason |',
        '| --- | --- | --- | --- |']
    for category, fields in report['descriptive_deltas'].items():
        for name, delta in fields.items():
            lines.append(f"| {category}.{name} | {delta['candidate_minus_baseline_median']} | {delta['percent_of_baseline_median']} | {delta['reason'] or delta['percent_reason'] or ''} |")
    lines += ['', 'These differences are arithmetic descriptions only and do not establish a regression or improvement.', '',
        '## Confounders and limits', '']
    lines += ['- ' + item['code'] + ': ' + item['reason'] for item in report['confounders']]
    if not report['confounders']:
        lines.append('No listed confounder was observed. This does not qualify the host or establish calibrated comparability.')
    lines += ['', 'Target identities and complete source/build/instrumentation declarations are frozen in `comparison.json` and verified against each bundled package.',
        'Lower values and nonoverlapping ranges do not enable a performance verdict. No universal percentage threshold, automatic extra repetitions or regression ranking is applied.', '']
    return '\n'.join(lines)


def _validate_entries(plan, attempts):
    if not isinstance(attempts, list) or len(attempts) != len(plan['sequence']):
        raise recipes.ContractError('Comparison attempts must align with every planned sequence entry')
    for entry, expected in zip(attempts, plan['sequence']):
        recipes._keys(entry, ('id', 'role', 'pair', 'index', 'result', 'status', 'reason'), where='attempt')
        if any(type(entry[key]) is not type(value) or entry[key] != value for key, value in expected.items()):
            raise recipes.ContractError('Comparison attempt sequence identity differs from the plan')
        recipes._text(entry['reason'], 'attempt.reason')
        recipes._choice(entry['status'], (*MISSING_STATUSES, 'completed', 'experiment_failed'), 'attempt.status')
        if entry['result'] is None:
            if entry['status'] not in MISSING_STATUSES:
                raise recipes.ContractError('Completed or experiment-failed attempts require a result package')
        elif not isinstance(entry['result'], str):
            raise recipes.ContractError('Attempt result must be an absolute path or null')
        else:
            _safe_path(entry['result'])


def build_comparison_report(plan, attempts, output_dir):
    """Verify and copy all evidence before producing a portable new report."""
    from recipe_comparison import validate_comparison_plan
    validate_comparison_plan(plan)
    _validate_entries(plan, attempts)
    output = _safe_path(output_dir)
    if os.path.lexists(output):
        raise recipes.ContractError('Choose an absolute new comparison report directory')
    sources, derived = [], []
    for entry in attempts:
        path = Path(entry['result']) if entry['result'] else None
        if path:
            source = path.parent
            if output == source or output in source.parents or source in output.parents:
                raise recipes.ContractError('Comparison report and source package destinations must be nonnested')
        item, result = _attempt(plan, entry, path)
        derived.append(item)
        if path:
            sources.append((path, result, item['id']))
    report = _assemble(plan, derived)
    output.mkdir(parents=True, mode=0o700)
    if sources:
        (output / 'attempts').mkdir(mode=0o700)
    for path, result, identifier in sources:
        _copy_package(path, result, output / 'attempts' / identifier)
    _write(output / 'comparison.json', report)
    with (output / 'REPORT.md').open('x', encoding='utf-8') as stream:
        stream.write(_render(report))
    files = [{'path': path.relative_to(output).as_posix(),
              'sha256': _digest_file(output, path.relative_to(output).as_posix())}
             for path in sorted(output.rglob('*')) if path.is_file()]
    _write(output / 'checksums.json', {'schema': SCHEMA, 'files': files})
    verify_comparison_report(output / 'comparison.json')
    return report


def verify_comparison_report(path):
    """Recompute assertions, distributions, confounders and prose from packages."""
    from recipe_comparison import validate_comparison_plan
    path = _safe_path(path)
    root = path.parent
    if path.name != 'comparison.json':
        raise recipes.ContractError('Select the bundled comparison.json manifest')
    try:
        document = _load(root, path.name)
        recipes._keys(document, ('schema', 'scope', 'plan', 'recipe_sha256', 'attempts', 'correctness',
                                'measurements', 'descriptive_deltas', 'confounders', 'performance'))
        if document['schema'] != SCHEMA or document['scope'] != SCOPE:
            raise recipes.ContractError('Unsupported comparison schema or scope')
        validate_comparison_plan(document['plan'])
        checksums = _load(root, 'checksums.json')
        recipes._keys(checksums, ('schema', 'files'), where='checksums')
        if checksums['schema'] != SCHEMA or not isinstance(checksums['files'], list):
            raise recipes.ContractError('Invalid comparison checksum manifest')
        listed = set()
        for entry in checksums['files']:
            recipes._keys(entry, ('path', 'sha256'), where='checksums.files')
            relative = recipes._artifact_path(entry['path'], 'checksum path')
            recipes._match(entry['sha256'], recipes._HEX64, 'checksum', 'a SHA-256 digest')
            if relative in listed or relative == 'checksums.json':
                raise recipes.ContractError('Duplicate or recursive comparison checksum')
            listed.add(relative)
            if _digest_file(root, relative) != entry['sha256']:
                raise recipes.ContractError(f'{relative}: comparison checksum mismatch')
        if not {'comparison.json', 'REPORT.md'} <= listed:
            raise recipes.ContractError('Comparison manifest and human report must be checksummed')
        expected_dirs = {parent.as_posix() for name in listed for parent in Path(name).parents if parent != Path('.')}
        def fail_walk(exc):
            raise recipes.ContractError(f'Comparison traversal failed: {exc}')
        for directory, dirs, files in os.walk(root, followlinks=False, onerror=fail_walk):
            base = Path(directory)
            for name in dirs:
                candidate = base / name
                if candidate.is_symlink() or candidate.relative_to(root).as_posix() not in expected_dirs:
                    raise recipes.ContractError('Unsafe or unlisted directory in comparison package')
            for name in files:
                relative = (base / name).relative_to(root).as_posix()
                if relative != 'checksums.json' and relative not in listed:
                    raise recipes.ContractError(f'{relative}: unlisted comparison artifact')
        entries = []
        if not isinstance(document['attempts'], list):
            raise recipes.ContractError('Comparison attempts must be a list')
        for item in document['attempts']:
            expected_package = f"attempts/{item['id']}/result.json"
            if item['package'] is not None and item['package'] != expected_package:
                raise recipes.ContractError('Invalid comparison attempt package path')
            entries.append({key: item[key] for key in ('id', 'role', 'pair', 'index', 'status', 'reason')} |
                           {'result': str(root / expected_package) if item['package'] else None})
        _validate_entries(document['plan'], entries)
        attempts = [_attempt(document['plan'], entry, Path(entry['result']) if entry['result'] else None)[0] for entry in entries]
        expected = _assemble(document['plan'], attempts)
        if document != expected:
            raise recipes.ContractError('Comparison report disagrees with its reconstructed evidence')
        if _regular_bytes(root, 'REPORT.md').decode('utf-8') != _render(expected):
            raise recipes.ContractError('Human report disagrees with verified comparison evidence')
        # Rehashed extra files are still outside the report's supported inventory.
        supported = {'comparison.json', 'REPORT.md'}
        for entry in entries:
            if entry['result']:
                package = _load(Path(entry['result']).parent, 'result.json')
                prefix = f"attempts/{entry['id']}/"
                from recipe_results import package_inventory
                supported.update(prefix + name for name in package_inventory(Path(entry['result']).parent, package))
        if listed != supported:
            raise recipes.ContractError('Unlisted content outside supported comparison evidence')
    except (KeyError, TypeError, ValueError, UnicodeError) as exc:
        if isinstance(exc, recipes.ContractError):
            raise
        raise recipes.ContractError(f'Malformed comparison report: {exc}') from exc
    return {'valid': True, 'schema': SCHEMA, 'files_verified': len(listed),
            'qualification': 'not_assessed', 'policy': 'disabled'}
