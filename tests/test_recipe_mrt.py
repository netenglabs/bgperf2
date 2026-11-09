"""Bounded MRT input and declared oracle behavior without Docker or traffic."""
import copy
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import recipes
import recipe_mrt as mrt
from mrt_controls import CASES, control
from mrt_inventory import inventory
from mrt_attributes import AttributeInventory
from test_recipes import source, export


def bound(tmp_path, case='plain'):
    path = tmp_path/'input.mrt'
    data, spec = control(case, path, target_asn=64515, observer_asn=64516, source_asn=64520)
    path.write_bytes(data)
    batch, test = source(tmp_path, neighbors=[1], prefixes=[spec['peers'][0]['prefixes']])
    return mrt.bind(export(batch, test), spec)


@pytest.mark.parametrize('case', CASES)
def test_fixed_controls_have_predeclared_sets_and_well_formed_source(tmp_path, case):
    document = bound(tmp_path, case)
    assert recipes.validate_recipe(json.loads(json.dumps(document))) == document
    assert document['roles']['generator']['adapter'] == 'bgpdump2'
    assert document['resolved']['target']['tester_type'] == 'bgpdump2'
    assert mrt.verify_input(document)['status'] == 'verified'
    spec = document['mrt']
    attrs = AttributeInventory([0], [64515, 64516])
    value = inventory(io.BytesIO(Path(spec['input']['path']).read_bytes()),
                      expected_size=spec['input']['bytes'], expected_sha256=spec['input']['sha256'],
                      attributes=attrs)
    row = value['attribute_inventory']['peers'][0]
    assert row['malformed_entries'] == 0
    assert row['entries'] == spec['peers'][0]['prefixes']
    assert value['peers'][0]['asn'] == 64520
    if case == 'long-paths':
        assert row['max_as_sequence_length'] == 260
        assert row['counts']['multiple_as_sequence_segments'] == 4
    if case == 'export-scope':
        assert all(row['counts'][k] == 1 for k in ('no_export', 'no_advertise', 'no_export_subconfed'))
    if case == 'as-set':
        assert row['counts']['as_set'] == 1
    if case == 'as-loops':
        assert row['checked_asn_entries'] == {'64515': 1, '64516': 1}


@pytest.mark.parametrize('mutation', [
    lambda d: d['mrt'].update(unknown=True),
    lambda d: d['mrt'].update(target_asn=True),
    lambda d: d['mrt'].update(observer_asn=64515),
    lambda d: d['mrt']['peers'][0].update(asn=64516),
    lambda d: d['mrt']['peers'][0].update(prefixes=0),
    lambda d: d['mrt']['peers'][0].update(index=4096),
    lambda d: d['mrt']['peers'].append(copy.deepcopy(d['mrt']['peers'][0])),
    lambda d: d['mrt'].update(expected_prefixes=[]),
    lambda d: d['mrt'].update(expected_prefixes=['::/0']),
    lambda d: d['mrt'].update(expected_prefixes=['198.18.0.1/24']),
    lambda d: d['mrt'].update(expected_prefixes=['198.18.0.1/32']*2),
    lambda d: d['mrt']['expected_prefixes'].reverse(),
    lambda d: d['inputs'][0].update(sha256='f'*64),
    lambda d: d['roles']['generator'].update(adapter='bird'),
    lambda d: d['resolved']['target'].update(tester_type='bird'),
    lambda d: d['mrt']['input'].update(path='relative.mrt'),
    lambda d: d.update(resolved={}),
    lambda d: d.update(resolved={'target': []}),
])
def test_tampered_or_unsupported_workload_refused(tmp_path, mutation):
    document = bound(tmp_path)
    mutation(document)
    with pytest.raises(recipes.ContractError):
        recipes.validate_recipe(document)


def test_input_hash_symlink_fifo_and_deadline_fail_closed(tmp_path):
    doc = bound(tmp_path)
    path = Path(doc['mrt']['input']['path'])
    original = path.read_bytes()
    path.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
    with pytest.raises(recipes.ContractError, match='identity'):
        mrt.verify_input(doc)
    path.unlink()
    target = tmp_path/'other'
    target.write_bytes(original)
    path.symlink_to(target)
    with pytest.raises(recipes.ContractError, match='Canonical'):
        mrt.verify_input(doc)
    path.unlink()
    import os
    os.mkfifo(path)
    with pytest.raises(recipes.ContractError, match='Regular'):
        mrt.verify_input(doc)
    path.unlink()
    path.write_bytes(original)
    tick = iter((0, 121))
    with pytest.raises(recipes.ContractError, match='deadline'):
        mrt.verify_input(doc, clock=lambda: next(tick))


def test_expected_union_controls_count_and_exhaustive_identity(tmp_path):
    import recipe_prefixes as prefixes
    from test_recipe_prefixes import captured
    from recipe_assertions import default_assertions
    doc = bound(tmp_path, 'export-scope')
    assert doc['resolved']['prefixes_per_peer'] == 4
    assert prefixes.expected_count(doc) == 1
    receipt = captured(doc)
    receipt['snapshot']['prefixes'] = doc['mrt']['expected_prefixes'].copy()
    assert prefixes.inspect(receipt, doc)['missing_count'] == 0
    receipt['snapshot']['prefixes'] = ['192.0.2.0/24']
    result = prefixes.inspect(receipt, doc)
    assert result['missing_count'] == result['unexpected_count'] == 1
    definitions = {a['capability']: a['expected'] for a in default_assertions(doc, include_prefixes=True)['assertions']}
    assert definitions['observer_route_count'] == 1
    assert definitions['observer_prefix_identity'] == {'count': 1, 'layout': 'declared_mrt_ipv4_prefix_set'}
    doc['mrt']['peers'][0]['prefixes'] = 100001
    assert prefixes.capture_limits(doc) == (5_000_000, 128*1024**2, 30)


def test_scoped_adapter_preserves_fixed_mapping_full_table_and_read_only_bind(tmp_path):
    doc = bound(tmp_path)
    class Fake:
        def get_host_config(self):
            return {'Binds': [doc['mrt']['input']['path'] + ':/root/mrt_file', '/work:/root/config']}
    cls = mrt.adapter(Fake, doc)
    instance = cls()
    instance.conf = {'bgpdump-index': 0, 'neighbors': {'key': {'local-address': '10.10.0.3'}}}
    instance.target_ip, instance.guest_dir, instance.LOG_NAME = '10.10.0.1', '/root/config', 'bgpdump2.log'
    assert instance.get_index_valid(9999999) == [0]
    assert instance.get_index_asns() == {0: 64520}
    assert instance.get_host_config()['Binds'] == [doc['mrt']['input']['path'] + ':/root/mrt_file:ro', '/work:/root/config']
    command = instance.get_startup_cmd()
    assert ' -4 --blaster 10.10.0.1 -p 0 -a 64520 /root/mrt_file -T 0 -S 10.10.0.3 ' in command


def test_generated_scenario_uses_role_asns_fixed_peer_counts_and_union(tmp_path):
    import bgperf2
    import yaml
    doc = bound(tmp_path, 'export-scope')
    args = bgperf2.create_args_parser().parse_args(['bench', '-t', 'bird', '-n', '1', '-p', '4', '-g', 'bgpdump2', '--mrt-file', doc['mrt']['input']['path']])
    value = yaml.safe_load(mrt.scenario(bgperf2.gen_conf(args), doc, bgperf2.render_scenario))
    assert value['target']['as'] == 64515 and value['monitor']['as'] == 64516
    assert value['monitor']['check-points'] == [1]
    assert value['testers'][0]['bgpdump-index'] == 0
    assert next(iter(value['testers'][0]['neighbors'].values()))['count'] == 4


def test_fixture_cli_never_overwrites(tmp_path):
    from scripts.make_mrt_control import main
    args = ['--case', 'plain', '--target-asn', '64515', '--observer-asn', '64516',
            '--source-asn', '64520', '--output-dir', str(tmp_path/'fixture')]
    assert main(args) == 0
    before = (tmp_path/'fixture/input.mrt').read_bytes()
    assert main(args) == 2
    assert (tmp_path/'fixture/input.mrt').read_bytes() == before


@pytest.mark.parametrize('fails', [False, True])
def test_worker_verifies_input_outside_existing_lifecycle_and_retains_receipts(tmp_path, monkeypatch, fails):
    import bgperf2
    import recipe_worker
    import run_lifecycle
    from test_run_lifecycle import fake_run
    runtime, args, calls, components = fake_run(tmp_path)
    runtime.MONITOR_CLASSES['sink'] = runtime.MONITOR_CLASSES['gobgp']
    runtime.create_args_parser = bgperf2.create_args_parser
    runtime.dckr = SimpleNamespace(networks=lambda **kwargs: [])
    runtime.capture_tool_revision = lambda: None
    runtime.stats_header = lambda: 'failed,tester errors,tester timeouts'
    runtime.row_failed = lambda row: row[0]
    document = bound(tmp_path)
    work = tmp_path/'work'
    work.mkdir()
    def bench(scoped, parsed):
        assert (work/'mrt-input-before.json').is_file()
        assert not (work/'mrt-input-after.json').exists()
        assert parsed.tester_type == 'bgpdump2'
        assert parsed.mrt_file == document['mrt']['input']['path']
        conf = scoped.yaml.safe_load(scoped.Template(scoped.gen_conf(parsed)).render())
        assert conf['target']['as'] == 64515
        cls = scoped.scenario_mrt_tester_class(conf['testers'][0])
        assert cls.require_image() == document['roles']['generator']['image']
        if fails:
            raise RuntimeError('modeled lifecycle failure')
        return [False, 0, 0]
    monkeypatch.setattr(run_lifecycle, 'bench', bench)
    if fails:
        with pytest.raises(RuntimeError, match='modeled lifecycle'):
            recipe_worker.execute(document, work, 'attempt', runtime)
    else:
        assert recipe_worker.execute(document, work, 'attempt', runtime)['status'] == 'completed'
    assert json.loads((work/'mrt-input-after.json').read_text())['status'] == 'verified'


def test_mrt_path_is_data_even_when_it_contains_mako_syntax(tmp_path):
    import bgperf2
    import yaml
    doc = bound(tmp_path)
    value = str(tmp_path/'${1 / 0}.mrt')
    doc['mrt']['input']['path'] = value
    args = bgperf2.create_args_parser().parse_args(['bench', '-t', 'bird', '-n', '1', '-p', '3',
                                                  '-g', 'bgpdump2', '--mrt-file', value])
    conf = yaml.safe_load(mrt.generated_scenario(bgperf2, args, doc))
    assert next(iter(conf['testers'][0]['neighbors'].values()))['mrt-file'] == value


def test_selected_asn_must_match_consumed_peer_table(tmp_path):
    doc = bound(tmp_path)
    doc['mrt']['peers'][0]['asn'] = 64521
    recipes.validate_recipe(doc)  # Source declarations alone do not read disk.
    with pytest.raises(recipes.ContractError, match='peer index/ASN'):
        mrt.verify_input(doc)


def test_cli_export_binds_workload_and_preserves_synthetic_default(tmp_path):
    doc = bound(tmp_path)
    spec = tmp_path/'spec.json'
    spec.write_text(json.dumps(doc['mrt']))
    output = tmp_path/'recipe.json'
    argv = ['export', '--batch', str(tmp_path/'batch.yaml'), '--test', doc['selection']['test'],
            '--cell', doc['selection']['cell_key'], '--engine-revision', doc['engine']['revision'],
            '--question', 'Declared MRT transit check', '--output', str(output)]
    for role in ('target', 'generator', 'observer'):
        argv += ['--'+role+'-image', doc['roles'][role]['image']]
    assert recipes.main(argv + ['--mrt-spec', str(spec)]) == 0
    assert recipes.validate_recipe(recipes.read_document(output))['schema'] == mrt.SCHEMA
    synthetic = tmp_path/'synthetic.json'
    assert recipes.main(argv + ['--output', str(synthetic)]) == 0
    assert recipes.read_document(synthetic)['schema'] == recipes.RECIPE_SCHEMA
