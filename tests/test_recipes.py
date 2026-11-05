"""Public recipe boundaries: declarative, pinned and usable without a runtime."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

import bgperf2
import recipes


ROOT = Path(__file__).resolve().parents[1]
REVISION = 'a' * 40
ROLES = {role: {'adapter': adapter, 'image': 'sha256:' + digit * 64}
         for role, adapter, digit in [('target', 'bird', '1'),
                                      ('generator', 'bird', '2'),
                                      ('observer', 'sink', '3')]}


def source(tmp_path, **changes):
    test = {'name': 'portable', 'neighbors': [1, 2], 'prefixes': [100],
            'filter_test': ['None'], 'monitor': 'sink', 'targets': [{'name': 'bird'}]}
    test.update(changes)
    path = tmp_path / 'batch.yaml'
    path.write_text(yaml.safe_dump({'tests': [test]}))
    return path, test


def export(path, test, **changes):
    cell = bgperf2.expand_batch_cells(test, bgperf2.expand_target_versions(test['targets']))[0]
    kwargs = {'engine_revision': REVISION, 'roles': copy.deepcopy(ROLES),
              'question': 'Does the target complete this synthetic workload?'}
    kwargs.update(changes)
    return recipes.export_recipe(str(path), test['name'],
                                 bgperf2.batch_cell_key(bgperf2.batch_cell_id(test['name'], cell)),
                                 **kwargs)


@pytest.fixture
def recipe(tmp_path):
    path, test = source(tmp_path)
    return export(path, test)


def test_recipe_round_trip_preserves_source_normalization_and_legacy_identity(tmp_path):
    path, test = source(tmp_path, neighbors=[2], prefixes=[200], prefix_scope='total')
    doc = export(path, test)
    assert recipes.validate_recipe(json.loads(json.dumps(doc))) == doc
    assert doc['source']['text'] == path.read_text()
    assert doc['source']['sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert doc['source']['raw_target'] == {'name': 'bird'}
    assert doc['resolved']['target']['tester_type'] == 'bird'
    assert doc['resolved']['target']['filter_type'] == 'in'
    assert doc['resolved']['prefix_scope'] == 'per-peer'
    assert doc['resolved']['prefixes_per_peer'] == 100
    assert json.loads(doc['legacy']['cell_id'])['target'] == {'name': 'bird'}
    assert doc['selection']['cell_key'] == doc['legacy']['cell_key']
    assert doc['inputs'] == []
    assert all(value is None for value in doc['resources'].values())


@pytest.mark.parametrize('field', ['source', 'selection', 'legacy', 'resolved', 'roles',
                                  'engine', 'resources', 'completion', 'reproduction', 'seeds'])
def test_unknown_nested_fields_are_refused(recipe, field):
    recipe[field]['run_shell'] = 'echo unexpected'
    with pytest.raises(ValueError):
        recipes.validate_recipe(recipe)


def test_unknown_top_level_capability_is_refused(recipe):
    recipe['hooks'] = ['echo unexpected']
    with pytest.raises(ValueError):
        recipes.validate_recipe(recipe)


@pytest.mark.parametrize('role', ['target', 'generator', 'observer'])
@pytest.mark.parametrize('image', ['bgperf/bird:latest', 'bgperf/bird:2.19.2', '', 'sha256:abc'])
def test_every_role_requires_immutable_identity(recipe, role, image):
    recipe['roles'][role]['image'] = image
    with pytest.raises(ValueError):
        recipes.validate_recipe(recipe)


@pytest.mark.parametrize('revision', ['main', 'a' * 7, '', 'g' * 40])
def test_engine_requires_full_commit_identity(recipe, revision):
    recipe['engine']['revision'] = revision
    with pytest.raises(ValueError):
        recipes.validate_recipe(recipe)


@pytest.mark.parametrize('field', ['neighbors', 'prefixes_per_peer'])
def test_boolean_counts_are_refused(recipe, field):
    recipe['resolved'][field] = True
    with pytest.raises(ValueError):
        recipes.validate_recipe(recipe)


@pytest.mark.parametrize('field', ['cell_id', 'cell_key'])
def test_legacy_identity_tampering_is_refused(recipe, field):
    recipe['legacy'][field] += '0'
    with pytest.raises(ValueError):
        recipes.validate_recipe(recipe)


def test_source_edit_is_refused(recipe):
    recipe['source']['text'] += '\n# changed\n'
    with pytest.raises(ValueError):
        recipes.validate_recipe(recipe)


def test_canonical_recipe_digest_escapes_unicode_and_preserves_string_whitespace():
    document = {'question': '  café 🚀\n', 'source': {'text': 'line 1\r\n  line 2\n'}}
    expected = ('{"question":"  caf\\u00e9 \\ud83d\\ude80\\n",'
                '"source":{"text":"line 1\\r\\n  line 2\\n"}}')
    assert recipes.canonical_json(document) == expected
    assert recipes.recipe_sha256(document) == 'db0cb4001a42945c63c1fd536464185020f9a1d8970100692ddc41285b4ea988'
    assert not recipes.canonical_json(document).endswith('\n')


@pytest.mark.parametrize('changes,diagnostic', [
    ({'seed': 1}, 'seed'), ({'order': 'shuffle'}, 'seed'),
    ({'order': 'shuffle', 'seed': True}, 'seed'),
    ({'neighbors': [True]}, 'neighbors'), ({'filter_test': ['prefix']}, 'filter_test'),
    ({'monitor': 'gobgp'}, 'monitor'), ({'monitor': False}, 'monitor'),
    ({'prefix_scope': 'totl'}, 'prefix_scope'),
    ({'targets': [{'name': 'bird', 'file': 'scenario.yaml'}]}, 'file'),
    ({'targets': [{'name': 'bird', 'command': 'echo unexpected'}]}, 'command'),
    ({'targets': [{'name': 'bird', 'pin': 'target=0,monitor=1,testers=2'}]}, 'pin'),
    ({'targets': [{'name': 'bird', 'tester_type': 'bgpdump2'}]}, 'tester_type'),
    ({'targets': [{'name': 'bird', 'tester_type': False}]}, 'tester_type'),
    ({'targets': [{'name': 'bird', 'tester_type': 0}]}, 'tester_type'),
    ({'targets': [{'name': 'bird', 'tester_type': ''}]}, 'tester_type'),
    ({'targets': [{'name': 'bird', 'image': 'bgperf/bird:latest'}]}, 'image'),
    ({'path_diversity': 2}, 'path_diversity'), ({'receivers': 1}, 'receivers'),
    ({'post_run': 'echo unexpected'}, 'post_run')])
def test_unsupported_or_unpinned_source_is_refused(tmp_path, changes, diagnostic):
    path, test = source(tmp_path, **changes)
    with pytest.raises(ValueError, match=diagnostic):
        # Avoid the legacy validator: refusing hostile input is the pure exporter's job.
        recipes.export_recipe(str(path), test['name'], '0' * 16,
                              engine_revision=REVISION, roles=ROLES, question='why?')


def test_explicit_unknown_selection_is_refused(tmp_path):
    path, test = source(tmp_path)
    for name, key in [('missing', '0' * 16), (test['name'], '0' * 16)]:
        with pytest.raises(ValueError):
            recipes.export_recipe(str(path), name, key, engine_revision=REVISION,
                                  roles=ROLES, question='why?')


def test_export_selects_one_repetition_and_records_stated_shuffle_seed(tmp_path):
    path, test = source(tmp_path, repetitions=2, order='shuffle', seed=7)
    cells = bgperf2.expand_batch_cells(test, test['targets'])
    selected = cells[-1]
    key = bgperf2.batch_cell_key(bgperf2.batch_cell_id(test['name'], selected))
    doc = recipes.export_recipe(str(path), test['name'], key, engine_revision=REVISION,
                                roles=ROLES, question='why?')
    assert doc['selection'] == {'test': test['name'], 'cell_key': key}
    assert doc['resolved']['neighbors'] == 2
    assert doc['resolved']['repetition'] == 2
    assert doc['seeds'] == {'order': 'shuffle', 'seed': 7, 'workload': None}


def test_duplicate_test_names_are_refused_before_selection(tmp_path):
    path, test = source(tmp_path)
    path.write_text(yaml.safe_dump({'tests': [test, test]}))
    with pytest.raises(ValueError, match='duplicate|unique'):
        recipes.export_recipe(str(path), test['name'], '0' * 16, engine_revision=REVISION,
                              roles=ROLES, question='why?')


def test_modified_normalized_value_is_refused(recipe):
    recipe['resolved']['prefixes_per_peer'] += 1
    with pytest.raises(ValueError):
        recipes.validate_recipe(recipe)


def pure_cli(tmp_path, *arguments):
    """A fresh interpreter cannot inherit conftest's fake settings module."""
    script = '''
import importlib.abc, runpy, socket, sys
class BlockRuntime(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'docker', 'settings', 'bgperf2', 'base'}:
            raise AssertionError('runtime import forbidden: ' + fullname)
sys.meta_path.insert(0, BlockRuntime())
def forbidden(*args, **kwargs):
    raise AssertionError('socket operation forbidden')
socket.socket.connect = forbidden
socket.create_connection = forbidden
sys.path.insert(0, sys.argv.pop(1))
if sys.argv[1:] == ['IMPORT']:
    import recipes, batch_cells
else:
    runpy.run_module('recipes', run_name='__main__')
'''
    return subprocess.run([sys.executable, '-c', script, str(ROOT), *map(str, arguments)],
                          cwd=tmp_path, env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'},
                          capture_output=True, text=True)


def test_pure_import_and_cli_round_trip_from_unrelated_directory(tmp_path):
    result = pure_cli(tmp_path, 'IMPORT')
    assert result.returncode == 0, result.stderr
    path, test = source(tmp_path)
    expected = export(path, test)
    output = tmp_path / 'recipe.json'
    args = ['export', '--batch', path, '--test', test['name'], '--cell',
            expected['selection']['cell_key'], '--engine-revision', REVISION,
            '--target-image', ROLES['target']['image'],
            '--generator-image', ROLES['generator']['image'],
            '--observer-image', ROLES['observer']['image'],
            '--question', expected['reproduction']['question'], '--output', output]
    result = pure_cli(tmp_path, *args)
    assert result.returncode == 0, result.stderr
    original = output.read_bytes()
    assert json.loads(original) == expected
    for operation in ['validate', 'inspect']:
        result = pure_cli(tmp_path, operation, output)
        assert result.returncode == 0, result.stderr
    result = pure_cli(tmp_path, *args)
    assert result.returncode == 2
    assert output.read_bytes() == original


def test_cli_refusal_has_stable_exit_and_no_output_artifact(tmp_path):
    path = tmp_path / 'invalid.json'
    path.write_text('{"schema":"future"}')
    result = pure_cli(tmp_path, 'validate', path)
    assert result.returncode == 2
    assert result.stderr


def result_manifest(status='experiment_failed', outcome='reproduced'):
    return {
        'schema': 'bgperf2/result/v1alpha1', 'recipe_sha256': '4' * 64,
        'engine': {'revision': REVISION}, 'attempt': {'id': 'fixture-attempt'},
        'status': status,
        'exit_code': {'completed': 0, 'setup_refused': 2, 'harness_failed': 3,
                      'experiment_failed': 4, 'interrupted': 143, 'inconclusive': 5}[status],
        'reproduction': {'outcome': outcome, 'reason': 'Synthetic contract fixture only.',
                         'evidence': ['target.log']},
        'comparison': {'qualification': 'not_assessed', 'reason': 'No host qualification.'},
        'artifacts': [
            {'kind': kind, 'path': None, 'sha256': None, 'availability': 'missing',
             'reason': 'Synthetic fixture contains no collected evidence.'}
            for kind in ['events', 'provenance', 'samples', 'configuration']
        ] + [{'kind': 'log', 'path': 'target.log', 'sha256': '5' * 64,
              'availability': 'present', 'reason': None}],
    }


@pytest.mark.parametrize('status', ['setup_refused', 'harness_failed', 'experiment_failed',
                                   'interrupted', 'inconclusive', 'completed'])
@pytest.mark.parametrize('outcome', ['reproduced', 'not_reproduced', 'inconclusive',
                                    'not_evaluated'])
def test_experiment_status_and_reproduction_are_separate_axes(status, outcome):
    doc = result_manifest(status, outcome)
    if status == 'setup_refused' and outcome in ('reproduced', 'not_reproduced'):
        with pytest.raises(ValueError, match='reproduction'):
            recipes.validate_result(doc)
    else:
        assert recipes.validate_result(json.loads(json.dumps(doc))) == doc


@pytest.mark.parametrize('mutation', [
    lambda d: d.update(status='success'),
    lambda d: d.update(exit_code=0),
    lambda d: d.update(run_shell='echo unexpected'),
    lambda d: d['reproduction'].update(outcome='passed'),
    lambda d: d['reproduction'].update(evidence=['unlisted.log']),
    lambda d: d['comparison'].update(qualification='comparable'),
    lambda d: d['artifacts'].pop(0),
    lambda d: d['artifacts'][0].update(reason=None),
    lambda d: d['artifacts'][-1].update(path='../target.log'),
    lambda d: d['artifacts'][-1].update(path='/tmp/target.log'),
    lambda d: d['artifacts'][-1].update(path='target\x00.log'),
    lambda d: d['artifacts'][-1].update(sha256=None),
    lambda d: d['artifacts'].append(copy.deepcopy(d['artifacts'][-1])),
])
def test_result_refuses_ambiguous_or_unsafe_evidence(mutation):
    doc = result_manifest()
    mutation(doc)
    with pytest.raises(ValueError):
        recipes.validate_result(doc)


def test_result_cli_is_pure(tmp_path):
    path = tmp_path / 'result.json'
    path.write_text(json.dumps(result_manifest()))
    result = pure_cli(tmp_path, 'result-validate', path)
    assert result.returncode == 0, result.stderr


def test_public_fixtures_round_trip_without_runtime(tmp_path):
    directory = ROOT / 'examples' / 'recipes'
    recipe_path = directory / 'synthetic-ipv4.recipe.json'
    doc = json.loads(recipe_path.read_text())
    assert doc['source']['text'] == (directory / 'synthetic-ipv4.yaml').read_text()
    regenerated = recipes.export_recipe(
        directory / 'synthetic-ipv4.yaml', doc['selection']['test'],
        doc['selection']['cell_key'], engine_revision=doc['engine']['revision'],
        roles=doc['roles'], question=doc['reproduction']['question'])
    assert regenerated == doc
    result_path = directory / 'synthetic-ipv4.result.json'
    result = json.loads(result_path.read_text())
    assert result['recipe_sha256'] == recipes.recipe_sha256(doc)
    for command, path in [('validate', recipe_path), ('inspect', recipe_path),
                          ('result-validate', result_path)]:
        completed = pure_cli(tmp_path, command, path)
        assert completed.returncode == 0, completed.stderr


def test_duplicate_source_fields_are_refused(tmp_path):
    path, test = source(tmp_path)
    path.write_text(path.read_text() + '\ntests: []\n')
    with pytest.raises(ValueError, match='duplicate'):
        recipes.export_recipe(path, test['name'], '0' * 16, engine_revision=REVISION,
                              roles=ROLES, question='why?')


@pytest.mark.parametrize('text', ['{"schema":1,"schema":2}', '{"value":NaN}',
                                  '{"value":Infinity}'])
def test_nonstandard_or_ambiguous_json_is_refused_by_cli(tmp_path, text):
    path = tmp_path / 'invalid.json'
    path.write_text(text)
    result = pure_cli(tmp_path, 'validate', path)
    assert result.returncode == 2
    assert 'Traceback' not in result.stderr
