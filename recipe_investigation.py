# Copyright (C) 2026 bgperf2 contributors. Apache-2.0.
"""Evidence-backed baseline/fix investigations; no statistical performance verdicts."""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil

import recipes
from recipe_results import _regular_file, _regular_bytes, verify_result_package

SCHEMA = 'bgperf2/investigation/v1alpha1'
CONTROLLER_STOP_SCHEMA = 'bgperf2/investigation-controller-stop/v1alpha1'
SCOPE = 'A functional baseline/fix investigation with declared and observed identities; no performance comparison is assessed.'
ROOT = Path(__file__).parent


def _json(document):
    return json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + '\n'


def _write(path, document):
    with path.open('x', encoding='utf-8') as output:
        output.write(_json(document))


def _load(root, relative):
    # Use the same nonblocking/no-follow artifact boundary as package verification.
    with _regular_file(root, relative) as stream:
        data = stream.read(8 * 1024 * 1024 + 1)
    if len(data) > 8 * 1024 * 1024:
        raise recipes.ContractError(f'{relative}: JSON evidence exceeds the 8 MiB inspection bound')
    return json.loads(data.decode('utf-8'), object_pairs_hook=recipes._pairs,
                      parse_constant=recipes._nonfinite)


def _validate_controller_stop(record):
    recipes._keys(record, ('schema', 'attempt', 'status', 'exit_code', 'reason'), where='controller stop')
    if record['schema'] != CONTROLLER_STOP_SCHEMA:
        raise recipes.ContractError('Unsupported investigation controller stop schema')
    recipes._choice(record['attempt'], ('baseline', 'candidate'), 'controller stop attempt')
    recipes._choice(record['status'], ('harness_failed', 'interrupted'), 'controller stop status')
    recipes._text(record['reason'], 'controller stop reason')
    allowed = (3,) if record['status'] == 'harness_failed' else (130, 143)
    if type(record['exit_code']) is not int or record['exit_code'] not in allowed:
        raise recipes.ContractError('Controller stop status and exit code disagree')
    return record


def _read_controller_stop(root, document):
    if 'controller_stop' not in document:
        return None
    reference = document['controller_stop']
    recipes._keys(reference, ('path', 'sha256'), where='controller stop reference')
    if reference['path'] != 'controller-stop.json':
        raise recipes.ContractError('Unsupported controller stop evidence path')
    recipes._match(reference['sha256'], recipes._HEX64, 'controller stop checksum', 'a SHA-256 digest')
    if hashlib.sha256(_regular_bytes(root, reference['path'])).hexdigest() != reference['sha256']:
        raise recipes.ContractError('Controller stop evidence checksum mismatch')
    return _validate_controller_stop(_load(root, reference['path']))


def _controller_context(record, attempts):
    if record is None:
        return
    stopped = attempts[record['attempt']]
    if stopped['availability'] == 'missing' and (stopped['status'] != record['status'] or stopped['reason'] != record['reason']):
        raise recipes.ContractError('Unavailable attempt disagrees with its controller stop')
    if record['attempt'] == 'baseline':
        candidate = attempts['candidate']
        if candidate['availability'] != 'missing' or candidate['status'] != 'not_run':
            raise recipes.ContractError('A baseline controller stop cannot have a candidate execution')
    elif attempts['baseline']['availability'] != 'present' or attempts['baseline']['status'] not in ('completed', 'experiment_failed'):
        raise recipes.ContractError('A candidate controller stop requires an available completed baseline operation')


def _new_roots(workdir, results_dir):
    roots = [Path(value) for value in (workdir, results_dir)]
    for path in roots:
        if not path.is_absolute():
            raise recipes.ContractError('Investigation destinations must be absolute')
        if os.path.lexists(path):
            raise recipes.ContractError(f'{path}: investigation destination already exists')
    work, results = (path.resolve() for path in roots)
    if work == results or work in results.parents or results in work.parents:
        raise recipes.ContractError('Investigation work and results must be distinct and nonnested')
    engine = ROOT.resolve()
    if any(path == engine or engine in path.parents for path in (work, results)):
        raise recipes.ContractError('Investigation destinations must be outside the engine checkout')
    return work, results


def _optional_artifact(root, result, relative):
    listed = {item['path'] for item in result['artifacts'] if item['availability'] == 'present'}
    if relative not in listed:
        return {'availability': 'missing', 'reason': f'{relative} was not collected.', 'value': None}
    try:
        value = _load(root, relative)
        if not isinstance(value, dict):
            raise recipes.ContractError('Expected a JSON object for optional evidence')
        if relative == 'work/prerequisites.json':
            checks = value.get('checks', [])
            if not isinstance(checks, list) or any(not isinstance(item, dict) or
                    not isinstance(item.get('details', {}), dict) for item in checks):
                raise recipes.ContractError('Malformed prerequisite observations')
        if relative == 'work/diagnostics.json':
            memory, containers, errors = value.get('memory', {}), value.get('containers', []), value.get('errors', [])
            if not isinstance(memory, dict) or not isinstance(memory.get('target', {}), dict):
                raise recipes.ContractError('Malformed target memory observations')
            target_memory = memory.get('target', {})
            if target_memory.get('units', 'bytes') != 'bytes':
                raise recipes.ContractError('Unsupported memory units; byte values are not inferred')
            for field in ('peak_bytes', 'ending_bytes', 'sampled_peak_bytes'):
                count = target_memory.get(field)
                if count is not None and (isinstance(count, bool) or not isinstance(count, int) or count < 0):
                    raise recipes.ContractError('Malformed memory byte count')
            if not isinstance(containers, list) or not isinstance(errors, list) or any(not isinstance(item, str) for item in errors):
                raise recipes.ContractError('Malformed diagnostic collections')
            for item in containers:
                if not isinstance(item, dict) or not isinstance(item.get('state', {}), dict) or (item.get('log') is not None and not isinstance(item['log'], dict)):
                    raise recipes.ContractError('Malformed container diagnostic observation')
                log = item.get('log') or {}
                if log.get('path') is not None:
                    recipes._artifact_path(log['path'], 'diagnostic log path')
    except (ValueError, UnicodeError, OSError) as exc:
        return {'availability': 'present', 'reason': f'Raw artifact retained; JSON inspection failed: {exc}', 'value': None}
    return {'availability': 'present', 'reason': None, 'value': value}


def _read_attempt(path, label, missing):
    if path is None:
        state = missing or {'status': 'not_run', 'reason': 'No attempt package was supplied.'}
        if state.get('status') not in ('not_run', 'setup_refused', 'harness_failed', 'interrupted', 'inconclusive'):
            raise recipes.ContractError('Unsupported unavailable-attempt status')
        recipes._text(state.get('reason'), 'unavailable attempt reason')
        return {'availability': 'missing', 'status': state['status'], 'reason': state['reason'],
                'package': None, 'reproduction': {'outcome': 'not_evaluated', 'reason': state['reason']},
                'target': None, 'host': None, 'diagnostics': None, 'stages': None, 'observed_images': {}}, None, None
    from recipe_targets import validate_target, effective_roles
    path = Path(path)
    verify_result_package(path)
    root = path.parent
    result = _load(root, path.name)
    recipe = _load(root, 'recipe.json')
    target = _optional_artifact(root, result, 'work/target.json')
    if target['value'] is None:
        raise recipes.ContractError(f'{label}: target build identity is missing; rerun through the investigation workflow')
    validate_target(target['value'], recipe)
    expected = effective_roles(recipe, target['value'])
    prereq = _optional_artifact(root, result, 'work/prerequisites.json')
    observed = {}
    if prereq['value'] is not None:
        checks = prereq['value'].get('checks', [])
        for role in expected:
            check = next((item for item in checks if item.get('name') == 'image.' + role), None)
            if check is not None and check.get('status') == 'pass':
                details = check.get('details', {})
                if details.get('requested') != expected[role]['image']:
                    raise recipes.ContractError(f'{label}: observed {role} image request differs from target selection')
                image_id = details.get('image_id')
                if image_id is not None:
                    recipes._match(image_id, re.compile(r'sha256:[0-9a-f]{64}\Z'),
                                   f'{label}.{role}.image_id', 'a full immutable image ID')
                    requested = expected[role]['image']
                    if requested.startswith('sha256:') and image_id != requested:
                        raise recipes.ContractError(f'{label}: observed {role} image ID differs from its pin')
                    if not requested.startswith('sha256:') and requested not in (details.get('repo_digests') or []):
                        raise recipes.ContractError(f'{label}: observed {role} repository digest differs from its pin')
                observed[role] = image_id
    diagnostics = _optional_artifact(root, result, 'work/diagnostics.json')
    host = _optional_artifact(root, result, 'work/host.json')
    live = _optional_artifact(root, result, 'work/live-diagnostics.json')
    stages = _optional_artifact(root, result, 'work/stages.json')
    return {'availability': 'present', 'status': result['status'], 'exit_code': result['exit_code'],
            'reason': result['reproduction']['reason'], 'package': f'{label}/result.json',
            'result_sha256': hashlib.sha256(_regular_bytes(root, path.name)).hexdigest(),
            'reproduction': result['reproduction'], 'target': target['value'],
            'effective_roles': expected, 'observed_images': observed,
            'host': host, 'diagnostics': diagnostics, 'live_diagnostics': live, 'stages': stages,
            'artifacts': [{'kind': item['kind'], 'availability': item['availability'],
                           'path': f'{label}/{item["path"]}' if item['path'] else None,
                           'reason': item['reason']} for item in result['artifacts']]}, recipe, result


def _copy_package(path, result, destination):
    root = Path(path).parent
    destination.mkdir(mode=0o700)
    names = [Path(path).name] + [item['path'] for item in result['artifacts'] if item['availability'] == 'present']
    for name in names:
        target = destination / ('result.json' if name == Path(path).name else name)
        target.parent.mkdir(parents=True, exist_ok=True)
        with _regular_file(root, name) as source, target.open('xb') as output:
            shutil.copyfileobj(source, output, length=1024 * 1024)
    # A source changing between initial verification and snapshot is a refusal.
    verify_result_package(destination / 'result.json')


def _differences(baseline, candidate):
    differences = []
    for key in ('image', 'label', 'provenance'):
        left, right = baseline['target'][key], candidate['target'][key]
        if left != right:
            differences.append({'field': 'target.' + key, 'baseline': left, 'candidate': right})
    return differences


def _host_changes(attempts):
    left = ((attempts['baseline'].get('host') or {}).get('value') or {})
    right = ((attempts['candidate'].get('host') or {}).get('value') or {})
    return [key for key in ('hostname', 'kernel_release', 'architecture', 'boot_id')
            if left.get(key) is not None and right.get(key) is not None and left[key] != right[key]]


def _assessment(attempts, recipe, controller_stop=None):
    baseline, candidate = attempts['baseline'], attempts['candidate']
    available = all(item['availability'] == 'present' for item in attempts.values())
    reasons = []
    if not available:
        reasons.append('An attempt is unavailable; no baseline/fix conclusion is supported.')
    witnessed = available and all(all(item['observed_images'].get(role) for role in ('target', 'generator', 'observer')) for item in attempts.values())
    if not witnessed:
        reasons.append('Exact observed image identities are incomplete.')
    if witnessed:
        for role in ('generator', 'observer'):
            if baseline['observed_images'][role] != candidate['observed_images'][role]:
                raise recipes.ContractError(f'The observed {role} image changed between attempts')
    inconclusive = {'setup_refused', 'harness_failed', 'interrupted', 'inconclusive'}
    stopped = any(item['status'] in inconclusive for item in attempts.values())
    usable = witnessed and not stopped
    changed_host = _host_changes(attempts)
    if changed_host:
        usable = False
        reasons.append('Host identity changed (' + ', '.join(changed_host) + '); no controlled target-change attribution is supported.')
    if available and stopped:
        reasons.append('Failed harness, interruption or inconclusive evidence prevents a functional pair verdict.')
    if controller_stop is not None:
        usable = False
        reasons.append(f"Investigation controller stopped during {controller_stop['attempt']} "
                       f"({controller_stop['status']}, exit {controller_stop['exit_code']}); "
                       'no functional pair verdict is supported.')
    if usable:
        outcomes = (baseline['reproduction']['outcome'], candidate['reproduction']['outcome'])
        outcome = ('baseline_reproduced_candidate_not_reproduced' if outcomes == ('reproduced', 'not_reproduced')
                   else 'same_observed_reproduction' if outcomes[0] == outcomes[1] and outcomes[0] in ('reproduced', 'not_reproduced')
                   else 'inconclusive')
        reasons.append('These are observed recipe reproduction outcomes; they do not prove a general bug fix.')
    else:
        outcome = 'inconclusive'
    return {'outcome': outcome, 'reasons': reasons,
            'predicate': recipe['reproduction'] if recipe is not None else None,
            'performance': {'qualification': 'not_assessed',
                            'reason': 'One functional baseline/fix pair supplies no calibrated timing, CPU or memory regression verdict.'}}


def _distinct_originals(results):
    """Two report slots must not count one verified original observation twice."""
    identities = [result['attempt']['id'] for result in results if result is not None]
    if len(identities) != len(set(identities)):
        raise recipes.ContractError('Baseline and candidate require distinct original attempt IDs; '
                                    'copying a result package does not create a second observation')


def _memory(attempt):
    diagnostics = attempt.get('diagnostics') or {}
    value = diagnostics.get('value') or {}
    memory = value.get('memory') or {}
    target = memory.get('target') or {}
    if not isinstance(target, dict):
        return None
    return target


def _render(report, controller_stop=None):
    predicate = report['assessment']['predicate'] or {}
    lines = ['# Baseline/fix investigation', '', report['scope'], '',
             'Question: ' + predicate.get('question', 'No executed recipe evidence is available.'), '',
             f"Observed outcome: **{report['assessment']['outcome']}**", '',
             'Each attempt preserves experiment status separately from reproduction outcome.', '',
             '| Attempt | Experiment | Reproduction | Instrumentation | Target image |', '| --- | --- | --- | --- | --- |']
    for label, attempt in report['attempts'].items():
        target = attempt.get('target') or {}
        image = target.get('image', 'unavailable')
        instrumentation = (target.get('provenance') or {}).get('instrumentation', 'unknown')
        lines.append(f"| {label} | {attempt['status']} | {attempt['reproduction']['outcome']} | {instrumentation} | `{image}` |")
    lines += ['', '## Frozen controls', '',
              'Both available attempts must reference the exact same canonical recipe. Only the target selection may change.',
              'Generator and observer requested identities are fixed; observed identities must agree before a pair verdict.', '',
              '## Target/build differences', '']
    for difference in report['differences']:
        # Human report names differences and links full machine-readable identities.
        lines.append(f"- `{difference['field']}` differs; inspect `investigation.json` and each package's `work/target.json`.")
    if not report['differences']:
        lines.append('No target/build differences were established from two available packages.')
    for label, attempt in report['attempts'].items():
        provenance = (attempt.get('target') or {}).get('provenance') or {}
        source, build = provenance.get('source') or {}, provenance.get('build') or {}
        lines += ['', f"### {label} identity", '',
                  f"Source commit: `{source.get('commit')}`; dirty patch SHA-256: `{source.get('patch_sha256')}`.",
                  f"Compiler flags: `{build.get('compiler_flags')}`; configure flags: `{build.get('configure_flags')}`.",
                  f"Linker flags: `{build.get('linker_flags')}`.",
                  f"Toolchain image: `{build.get('toolchain_image')}`; runtime base: `{build.get('runtime_image')}`."]
        lines += provenance.get('limits', ['Build identity is unavailable.'])
    lines += ['', '## Diagnostics and memory', '',
              'Memory values retain their declared accounting and sampling boundaries. Unavailable observations remain unknown.', '']
    for label, attempt in report['attempts'].items():
        memory = _memory(attempt)
        host = ((attempt.get('host') or {}).get('value') or {})
        lines.append(f"- {label} host: `{host.get('hostname')}`, kernel `{host.get('kernel_release')}`, architecture `{host.get('architecture')}`. Host qualification is unassessed.")
        lines.append(f"- {label}: peak `{memory.get('peak_bytes') if memory else None}` bytes; ending `{memory.get('ending_bytes') if memory else None}` bytes.")
        if memory:
            lines.append('  Accounting: ' + str(memory.get('accounting', memory.get('reason', 'See diagnostics.json for the exact boundary.'))))
            for field in ('peak_definition', 'ending_definition', 'daemon_process_reason', 'reason'):
                if memory.get(field):
                    lines.append('  ' + str(memory[field]))
        package = attempt.get('package')
        if package:
            lines.append(f"  [Verified package]({package}); diagnostic, stage and missing-artifact details are preserved in `investigation.json`.")
            lines.append('  Reproduction evidence: ' + attempt['reproduction']['reason'])
            for path in attempt['reproduction'].get('evidence', []):
                lines.append(f'  [Witness artifact]({label}/{path})')
            if (attempt.get('diagnostics') or {}).get('availability') == 'present':
                lines.append(f'  [Container states and diagnostics]({label}/work/diagnostics.json)')
                diagnostic = attempt['diagnostics']['value'] or {}
                if attempt['diagnostics'].get('reason'):
                    lines.append('  ' + attempt['diagnostics']['reason'])
                for container in diagnostic.get('containers', []):
                    state = container.get('state') or {}
                    lines.append(f"  Container `{container.get('role')}`: running `{state.get('Running')}`, exit `{state.get('ExitCode')}`, OOM `{state.get('OOMKilled')}`.")
                    log = container.get('log') or {}
                    if log.get('path'):
                        relative = recipes._artifact_path(log['path'], 'diagnostic log path')
                        reference = f'{label}/work/{relative}'
                        available = {item['path'] for item in attempt['artifacts'] if item['availability'] == 'present'}
                        if reference in available:
                            lines.append(f"  [Collected role log]({reference}); truncated: `{log.get('truncated')}`.")
                        else:
                            lines.append('  Referenced role log was not collected; no log content is inferred.')
                for error in diagnostic.get('errors', []):
                    lines.append('  Diagnostic collection error: ' + str(error))
            missing = [item['kind'] for item in attempt['artifacts'] if item['availability'] == 'missing']
            if missing:
                lines.append('  Unavailable artifact kinds: ' + ', '.join(missing) + '.')
        else:
            lines.append('  ' + attempt['reason'])
    if controller_stop is not None:
        lines += ['', '## Controller stop', '',
                  f"The investigation controller stopped during **{controller_stop['attempt']}**: "
                  f"`{controller_stop['status']}` (exit {controller_stop['exit_code']}).", '',
                  controller_stop['reason'], '',
                  'Available verified worker packages retain their original experiment status and reproduction evidence.',
                  '[Controller stop evidence](controller-stop.json) is separate from the immutable worker results.']
    lines += ['', '## Interpretation limits', '', *report['assessment']['reasons'],
              report['assessment']['performance']['reason'],
              'A lower memory observation is not a leak diagnosis. Different instrumentation/build inputs are recorded, never normalized away.',
              'No route-attribute oracle, statistical comparison or universal regression policy is supplied.', '']
    return '\n'.join(lines)


def write_investigation_report(*, baseline, candidate=None, output_dir,
                               baseline_missing=None, candidate_missing=None,
                               controller_stop=None):
    """Verify and snapshot supplied packages into a portable new report directory."""
    output = Path(output_dir)
    if not output.is_absolute() or os.path.lexists(output):
        raise recipes.ContractError('Choose an absolute new investigation report directory')
    if controller_stop is not None:
        _validate_controller_stop(controller_stop)
    attempts, sources, recipe, originals = {}, {}, None, []
    for label, path, missing in (('baseline', baseline, baseline_missing), ('candidate', candidate, candidate_missing)):
        attempt, bound, result = _read_attempt(path, label, missing)
        attempts[label] = attempt
        originals.append(result)
        if bound is not None:
            if recipe is not None and recipes.recipe_sha256(bound) != recipes.recipe_sha256(recipe):
                raise recipes.ContractError('Baseline and candidate must use the exact same frozen recipe')
            recipe = bound
            sources[label] = (path, result)
            root = Path(path).parent.resolve()
            target = output.resolve()
            if target == root or root in target.parents or target in root.parents:
                raise recipes.ContractError('Report and source package destinations must be nonnested')
    _distinct_originals(originals)
    _controller_context(controller_stop, attempts)
    assessment = _assessment(attempts, recipe, controller_stop)
    differences = _differences(attempts['baseline'], attempts['candidate']) if len(sources) == 2 else []
    report = {'schema': SCHEMA,
              'scope': SCOPE,
              'recipe_sha256': recipes.recipe_sha256(recipe) if recipe is not None else None,
              'frozen_recipe': recipe, 'attempts': attempts, 'differences': differences,
              'assessment': assessment}
    if controller_stop is not None:
        report['controller_stop'] = {'path': 'controller-stop.json',
                                    'sha256': hashlib.sha256(_json(controller_stop).encode('utf-8')).hexdigest()}
    output.mkdir(parents=True, mode=0o700)
    for label, (path, result) in sources.items():
        _copy_package(path, result, output / label)
    if controller_stop is not None:
        _write(output / 'controller-stop.json', controller_stop)
    _write(output / 'investigation.json', report)
    with (output / 'REPORT.md').open('x', encoding='utf-8') as stream:
        stream.write(_render(report, controller_stop))
    references = []
    for path in sorted(output.rglob('*')):
        if path.is_file():
            relative = path.relative_to(output).as_posix()
            digest = hashlib.sha256()
            with _regular_file(output, relative) as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    digest.update(block)
            references.append({'path': relative, 'sha256': digest.hexdigest()})
    _write(output / 'checksums.json', {'schema': SCHEMA, 'files': references})
    verify_investigation_report(output / 'investigation.json')
    return report


def verify_investigation_report(path):
    path = Path(path)
    root = path.parent
    if path.name != 'investigation.json':
        raise recipes.ContractError('Select the bundled investigation.json manifest')
    document = _load(root, path.name)
    recipes._keys(document, ('schema', 'scope', 'recipe_sha256', 'frozen_recipe', 'attempts', 'differences', 'assessment'),
                  optional=('controller_stop',))
    recipes._keys(document['attempts'], ('baseline', 'candidate'), where='attempts')
    if document.get('schema') != SCHEMA or set(document.get('attempts', {})) != {'baseline', 'candidate'}:
        raise recipes.ContractError('Unsupported investigation report')
    if document['scope'] != SCOPE:
        raise recipes.ContractError('Investigation scope differs from its supported interpretation')
    checksums = _load(root, 'checksums.json')
    recipes._keys(checksums, ('schema', 'files'), where='checksums')
    if checksums.get('schema') != SCHEMA or not isinstance(checksums.get('files'), list):
        raise recipes.ContractError('Invalid investigation checksum manifest')
    listed = set()
    for entry in checksums['files']:
        recipes._keys(entry, ('path', 'sha256'), where='checksums.files')
        relative = recipes._artifact_path(entry['path'], 'checksums.files.path')
        recipes._match(entry['sha256'], recipes._HEX64, 'checksums.files.sha256', 'a SHA-256 digest')
        if relative in listed or relative == 'checksums.json':
            raise recipes.ContractError('Duplicate or recursive investigation checksum entry')
        listed.add(relative)
        digest = hashlib.sha256()
        with _regular_file(root, relative) as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
        if digest.hexdigest() != entry['sha256']:
            raise recipes.ContractError(f'{relative}: investigation checksum mismatch')
    if not {'investigation.json', 'REPORT.md'} <= listed:
        raise recipes.ContractError('Investigation report and prose must be checksummed')
    controller_stop = _read_controller_stop(root, document)
    if controller_stop is not None and 'controller-stop.json' not in listed:
        raise recipes.ContractError('Controller stop evidence must be checksummed')
    if controller_stop is None and 'controller-stop.json' in listed:
        raise recipes.ContractError('Controller stop evidence lacks its report binding')
    def fail_walk(exc):
        raise recipes.ContractError(f'Investigation traversal failed: {exc}')
    for directory, dirs, files in os.walk(root, followlinks=False, onerror=fail_walk):
        base = Path(directory)
        if any((base / name).is_symlink() for name in dirs):
            raise recipes.ContractError('Symlink directory in investigation package')
        for name in files:
            relative = (base / name).relative_to(root).as_posix()
            if relative != 'checksums.json' and relative not in listed:
                raise recipes.ContractError(f'{relative}: unlisted investigation artifact')
    # Reconstruct semantics from the verified bundled packages, never trust edited prose.
    attempts, recipe, originals = {}, None, []
    for label, item in document['attempts'].items():
        if not isinstance(item, dict):
            raise recipes.ContractError('Malformed investigation attempt')
        recipes._choice(item.get('availability'), ('present', 'missing'), 'attempt availability')
        present = item.get('availability') == 'present'
        expected = f'{label}/result.json'
        if present and item.get('package') != expected:
            raise recipes.ContractError('Invalid bundled result package path')
        actual, bound, result = _read_attempt(root / expected if present else None, label,
                                       {'status': item.get('status'), 'reason': item.get('reason')} if not present else None)
        originals.append(result)
        if actual != item:
            raise recipes.ContractError(f'{label}: report disagrees with its bundled package')
        attempts[label] = actual
        if bound is not None:
            if recipe is not None and recipes.recipe_sha256(bound) != recipes.recipe_sha256(recipe):
                raise recipes.ContractError('Bundled recipes differ')
            recipe = bound
    _distinct_originals(originals)
    _controller_context(controller_stop, attempts)
    if document.get('frozen_recipe') != recipe or document.get('recipe_sha256') != (recipes.recipe_sha256(recipe) if recipe else None):
        raise recipes.ContractError('Investigation frozen recipe binding differs')
    if document.get('assessment') != _assessment(attempts, recipe, controller_stop):
        raise recipes.ContractError('Investigation assessment disagrees with evidence')
    differences = _differences(attempts['baseline'], attempts['candidate']) if all(x['availability'] == 'present' for x in attempts.values()) else []
    if document.get('differences') != differences:
        raise recipes.ContractError('Investigation differences disagree with evidence')
    if _regular_bytes(root, 'REPORT.md').decode('utf-8') != _render(document, controller_stop):
        raise recipes.ContractError('Human report disagrees with the verified investigation evidence')
    return {'valid': True, 'schema': SCHEMA, 'files_verified': len(listed),
            'outcome': document['assessment']['outcome']}


def rebuild_investigation_report(path, *, output_dir):
    """Verify an existing report, then preserve its evidence and stop meanings."""
    path = Path(path)
    verify_investigation_report(path)
    root, output = path.parent.resolve(), Path(output_dir)
    target = output.resolve()
    if target == root or root in target.parents or target in root.parents:
        raise recipes.ContractError('Rebuilt report and original report must be nonnested')
    document = _load(path.parent, path.name)
    inputs = {}
    for label in ('baseline', 'candidate'):
        attempt = document['attempts'][label]
        inputs[label] = path.parent / label / 'result.json' if attempt['availability'] == 'present' else None
        inputs[label + '_missing'] = ({'status': attempt['status'], 'reason': attempt['reason']}
                                      if attempt['availability'] == 'missing' else None)
    return write_investigation_report(**inputs, output_dir=output,
                                     controller_stop=_read_controller_stop(path.parent, document))


def _recover_package(path, label, recipe, target):
    """Only the selected exact package can survive an outer controller error."""
    if not os.path.lexists(path):
        return None, None
    try:
        attempt, bound, _ = _read_attempt(path, label, None)
        if recipes.recipe_sha256(bound) != recipes.recipe_sha256(recipe) or attempt['target'] != target:
            raise recipes.ContractError('Existing package differs from the selected recipe or target')
    except Exception as exc:
        return None, f'Existing selected package retained at {path}, but unavailable for reporting: {type(exc).__name__}: {exc}'
    return path, None


def run_investigation(recipe, *, baseline_target, candidate_target, workdir, results_dir,
                      timeout=300, diagnostics='basic', run=None, check=None):
    """Run at most one serial baseline and candidate, then preserve a portable report."""
    from recipe_targets import validate_target
    recipes.validate_recipe(recipe)
    for target in (baseline_target, candidate_target):
        validate_target(target, recipe)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise recipes.ContractError('Investigation timeout must be finite and positive')
    if diagnostics not in ('basic', 'none'):
        raise recipes.ContractError('Unsupported diagnostics mode')
    work, results = _new_roots(workdir, results_dir)
    from recipe_preflight import check_recipe
    precheck = check or check_recipe
    reports = [precheck(recipe, workdir=work / label, results_dir=results / label, target=target)
               for label, target in (('baseline', baseline_target), ('candidate', candidate_target))]
    if any(report['status'] != 'checks_passed' for report in reports):
        return {'schema': SCHEMA, 'status': 'setup_refused', 'exit_code': 2,
                'reason': 'Both selected targets must pass prerequisites before either experiment starts.', 'prerequisites': reports}
    work.mkdir(parents=True, mode=0o700)
    results.mkdir(parents=True, mode=0o700)
    _write(results / 'investigation-plan.json', {'recipe': recipe, 'targets': {'baseline': baseline_target, 'candidate': candidate_target},
                                               'diagnostics': diagnostics, 'timeout_per_attempt_seconds': timeout})
    from recipe_run import run_recipe
    execute = run or run_recipe
    paths = {'baseline': None, 'candidate': None}
    missing = {'baseline': None, 'candidate': {'status': 'not_run', 'reason': 'Candidate has not run.'}}
    stop_exit = 0
    controller_stop = None
    for label, target in (('baseline', baseline_target), ('candidate', candidate_target)):
        try:
            result = execute(recipe, workdir=work / label, results_dir=results / label,
                             timeout=timeout, target=target, diagnostics=diagnostics)
            path = results / label / 'result.json'
            if path.is_file():
                paths[label] = path
            else:
                status = result.get('status', 'harness_failed')
                if status in ('completed', 'experiment_failed'):
                    status = 'harness_failed'
                missing[label] = {'status': status,
                                  'reason': result.get('reason', 'No attempt package was produced.')}
                if status == 'harness_failed':
                    result = {'status': 'harness_failed', 'exit_code': 3}
            if result.get('status') not in ('completed', 'experiment_failed'):
                stop_exit = result.get('exit_code', 3)
                if label == 'baseline':
                    missing['candidate'] = {'status': 'not_run', 'reason': 'Baseline setup/harness failure, stop or inconclusive result prevented candidate execution.'}
                break
        except (Exception, KeyboardInterrupt, SystemExit) as exc:
            interrupted = isinstance(exc, (KeyboardInterrupt, SystemExit))
            stop_exit = (exc.code if isinstance(exc, SystemExit) and exc.code in (130, 143)
                         else 130 if interrupted else 3)
            missing[label] = {'status': 'interrupted' if interrupted else 'harness_failed',
                              'reason': f'{type(exc).__name__}: {exc}; available work is retained.'}
            paths[label], unavailable = _recover_package(results / label / 'result.json', label, recipe, target)
            if unavailable is not None:
                missing[label]['reason'] += ' ' + unavailable
            controller_stop = {'schema': CONTROLLER_STOP_SCHEMA, 'attempt': label,
                               'status': missing[label]['status'], 'exit_code': stop_exit,
                               'reason': missing[label]['reason']}
            if label == 'baseline':
                missing['candidate'] = {'status': 'not_run', 'reason': 'Baseline operation stopped before candidate execution.'}
            break
    report = write_investigation_report(baseline=paths['baseline'], candidate=paths['candidate'],
                                       output_dir=results / 'report', baseline_missing=missing['baseline'],
                                       candidate_missing=missing['candidate'], controller_stop=controller_stop)
    return {'schema': SCHEMA, 'status': 'recorded', 'exit_code': stop_exit,
            'report': str(results / 'report/investigation.json'), 'assessment': report['assessment']}
