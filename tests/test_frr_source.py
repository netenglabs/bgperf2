"""Inert local FRR source and simulated builders never execute daemon code."""
import copy
import hashlib
import json

import pytest

import recipe_targets as targets
import recipes
from test_frr_contracts import frr_recipe
from test_recipe_targets import source, build_host, git, TOOLCHAIN, RUNTIME, BUILT


@pytest.fixture
def frr_source(source):
    root, _ = source
    (root / 'Makefile.in').unlink()
    (root / 'Makefile.am').write_text('# Inert FRR build fixture\n')
    (root / 'bootstrap.sh').write_text('# Inert FRR bootstrap, never executed\n')
    git(root, 'add', '.')
    git(root, 'commit', '-qm', 'fixture: inert FRR source shape')
    return root, git(root, 'rev-parse', 'HEAD')


def plan(source, **options):
    return targets.plan_source_build(frr_recipe(), *source,
        toolchain_image=TOOLCHAIN, runtime_image=RUNTIME, **options)


def test_local_frr_plan_binds_source_dirty_changes_and_adapter(frr_source):
    document = plan(frr_source)
    assert document['build_recipe'] == 'frr-local/v1'
    assert document['network'] == 'none' and not document['source']['dirty']
    root, revision = frr_source
    assert git(root, 'rev-parse', 'HEAD') == revision
    (root / 'main.c').write_text('/* explicit local candidate */\n')
    with pytest.raises(recipes.ContractError, match='include_dirty'):
        plan(frr_source)
    dirty = plan(frr_source, include_dirty=True)
    assert dirty['source']['snapshot_sha256'] != document['source']['snapshot_sha256']
    assert dirty['source']['patch_sha256'] != document['source']['patch_sha256']
    with pytest.raises(recipes.ContractError, match='build_recipe'):
        targets.validate_build_plan(dict(document, build_recipe='bird-local/v1'))


@pytest.mark.parametrize('flags', [['--prefix=/tmp'], ['--sbindir=/bin'],
    ['--enable-user=root'], ['--enable-vty-group=root'], ['--bindir=/tmp'],
    ['--disable-user'], ['--disable-vty-group']])
def test_frr_adapter_layout_cannot_be_overridden_before_source_probe(flags, monkeypatch):
    monkeypatch.setattr(targets, '_snapshot', lambda *a, **k: pytest.fail('source probed'))
    with pytest.raises(recipes.ContractError, match='fixes installation'):
        plan(('/must-not-open', 'a' * 40), configure_flags=flags)


def test_frr_optimized_gcov_refused_before_source_probe(monkeypatch):
    monkeypatch.setattr(targets, '_snapshot', lambda *a, **k: pytest.fail('source probed'))
    with pytest.raises(recipes.ContractError, match='gcov'):
        plan(('/must-not-open', 'a' * 40), instrumentation='optimized', cflags='-O2',
             configure_flags=['--enable-gcov'])


def test_frr_builder_returns_matching_source_identity_and_fixed_runtime(frr_source, tmp_path, build_host):
    calls, state, command = build_host
    document = plan(frr_source)
    state['snapshot'] = document['source']['snapshot_sha256']
    output = tmp_path / 'frr-build'
    disclosures = []
    target = targets.build_target(document, output_dir=output,
        emit_disclosure=disclosures.append, command=command)
    assert target['adapter'] == 'frr_c' and target['image'] == BUILT
    assert target['provenance']['build']['recipe'] == 'frr-local/v1'
    assert target['provenance']['build']['binary_sha256'] is None
    assert target['provenance']['build']['reconstructible'] is False
    assert disclosures[0]['tag'].startswith('bgperf/frr-local:')
    assert hashlib.sha256((output / 'source.tar').read_bytes()).hexdigest() == state['snapshot']
    dockerfile = (output / 'Dockerfile').read_text()
    assert 'bash ./bootstrap.sh && ./configure' in dockerfile
    assert '--sbindir=/usr/lib/frr --sysconfdir=/etc ' in dockerfile
    assert 'test -x /install/usr/lib/frr/bgpd' in dockerfile
    assert 'test -x /install/usr/bin/vtysh' in dockerfile
    assert 'COPY --from=build /install/ /' in dockerfile
    assert 'frrvty /etc/frr /var/run/frr' in dockerfile
    assert 'git clone' not in dockerfile and 'apt' not in dockerfile
    assert json.loads((output / 'target.json').read_text()) == target
    wrong = copy.deepcopy(target)
    wrong['provenance']['build']['recipe'] = 'bird-local/v1'
    with pytest.raises(recipes.ContractError, match='build.recipe'):
        targets.validate_target(wrong)
    command_args = next(args for kind, args in calls if kind == 'build')
    assert '--network=none' in command_args and '--pull=false' in command_args


def test_frr_build_failure_keeps_source_and_partial_log(frr_source, tmp_path, build_host):
    _, state, command = build_host
    document = plan(frr_source)
    state.update(snapshot=document['source']['snapshot_sha256'], fail=RuntimeError('modeled compiler failure'))
    output = tmp_path / 'failed'
    with pytest.raises(RuntimeError, match='compiler failure'):
        targets.build_target(document, output_dir=output, emit_disclosure=lambda _: None, command=command)
    assert (output / 'source.tar').is_file() and (output / 'build.log').is_file()
    assert json.loads((output / 'build-result.json').read_text())['status'] == 'failed'
    assert not (output / 'target.json').exists()
