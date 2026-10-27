"""Pinning must bind identity and execution, or fail before host probes."""
import copy
import json
from pathlib import Path

import pytest

import bgperf2
import recipes
from test_recipes import ROLES, source, export


PIN = 'target=0,monitor=1,testers=2-3'


@pytest.fixture(autouse=True)
def selected_host(monkeypatch):
    monkeypatch.setattr(bgperf2, 'host_cpus', lambda: frozenset(range(4)))


def test_pinned_recipe_matches_canonical_batch_identity(tmp_path):
    path, test = source(tmp_path, pin='testers=3,2,monitor=1,target=0')
    document = export(path, test)
    assert document['resolved']['pin'] == PIN
    assert json.loads(document['legacy']['cell_id'])['pin'] == PIN
    assert document['source']['text'] == path.read_text()
    assert recipes.validate_recipe(document) == document
    other_path, other_test = source(tmp_path, pin=PIN)
    other = export(other_path, other_test)
    assert other['legacy'] == document['legacy']
    assert other['resolved'] == document['resolved']
    assert recipes.recipe_sha256(other) != recipes.recipe_sha256(document)  # Original source spelling is retained.


@pytest.mark.parametrize('pin', [None, False, '', 'target=0,monitor=1',
    'target=0,monitor=0,testers=2', 'target=0,monitor=1,testers=2,receivers=3',
    'target=1-0,monitor=2,testers=3', 'target=0,monitor=1,testers=-1'])
def test_bad_layout_refused_before_cell_selection(tmp_path, pin):
    path, test = source(tmp_path, pin=pin)
    with pytest.raises(recipes.ContractError, match='pin'):
        recipes.export_recipe(path, test['name'], '0'*16, engine_revision='a'*40,
                              roles=copy.deepcopy(ROLES), question='refusal')


@pytest.mark.parametrize('pin', ['target=0-999999999999,monitor=1,testers=2',
    'target=4096,monitor=0,testers=1',
    'target=٠-٩٩٩٩٩٩٩٩٩,monitor=1,testers=2', 'target=' + '0'*5000])
def test_untrusted_ranges_are_bounded_before_expansion(tmp_path, monkeypatch, pin):
    path, _ = source(tmp_path, pin=pin)
    def forbidden(*args, **kwargs):
        pytest.fail('Oversized CPU range reached the expanding parser')
    monkeypatch.setattr(recipes, 'resolve_pin', forbidden)
    with pytest.raises(recipes.ContractError, match='pin'):
        recipes._source_tests(path.read_text())


def test_largest_recipe_cpu_id_is_an_offline_declaration(tmp_path, monkeypatch):
    monkeypatch.setattr(bgperf2, 'host_cpus', lambda: frozenset(range(4096)))
    path, test = source(tmp_path, pin='target=4095,monitor=0,testers=1')
    document = export(path, test)
    assert document['resolved']['pin'] == 'target=4095,monitor=0,testers=1'


def test_pinning_tampering_is_not_a_new_recipe(tmp_path):
    path, test = source(tmp_path, pin=PIN)
    document = export(path, test)
    document['resolved']['pin'] = 'target=3,monitor=1,testers=0,2'
    with pytest.raises(recipes.ContractError):
        recipes.validate_recipe(document)


def test_historical_unpinned_fixture_reexports_identically(tmp_path):
    fixture = recipes.read_document(Path(__file__).parents[1] / 'examples/recipes/synthetic-ipv4.recipe.json')
    path = tmp_path / 'original.yaml'
    path.write_text(fixture['source']['text'])
    actual = recipes.export_recipe(path, fixture['selection']['test'], fixture['selection']['cell_key'],
        engine_revision=fixture['engine']['revision'], roles=fixture['roles'],
        question=fixture['reproduction']['question'],
        expected_outcome=fixture['reproduction']['expected_outcome'])
    assert recipes.canonical_json(actual) == recipes.canonical_json(fixture)
    assert 'pin' not in actual['resolved']
