"""Offline case preparation freezes bytes/commands, never a build or worker."""
import hashlib
import json
from pathlib import Path
import socket
import zipfile

import pytest

import recipes
from scripts import prepare_prefix_identity_case as case


@pytest.fixture
def packet(tmp_path, monkeypatch):
    cache = tmp_path/'cache'
    cache.mkdir()
    for module, version in case.MODULES:
        stem = cache/(module + '/@v/' + version)
        stem.parent.mkdir(parents=True)
        stem.with_suffix(stem.suffix+'.info').write_text(json.dumps({'Version': version}))
        Path(str(stem)+'.mod').write_text('module '+module+'\ngo 1.25.0\n')
        with zipfile.ZipFile(str(stem)+'.zip', 'w') as archive:
            archive.writestr(module+'@'+version+'/inert-fixture.txt', 'not executable source')
        Path(str(stem)+'.ziphash').write_text('DO NOT TRUST OR COPY THIS STAMP')
    monkeypatch.setattr(case, 'revision', lambda: 'e7798ad1e2f91d7c7197dfc79bf7295cfb55bd3d')
    return cache, tmp_path/'case01', tmp_path/'execution01'


def test_prepare_verifies_context_and_exact_bounded_commands_without_runtime(packet, monkeypatch):
    def forbidden(*a, **kw):
        pytest.fail('Preparation attempted a runtime/network operation')
    monkeypatch.setattr(socket.socket, '__init__', forbidden)
    cache, output, execution = packet
    before = {str(p): (p.read_bytes(), p.stat().st_mtime_ns) for p in cache.rglob('*') if p.is_file()}
    assert case.prepare(*packet)['valid']
    assert not execution.exists()
    assert case.verify(output)['execution_root_absent']
    dockerfile = (output/'context/Dockerfile').read_text()
    assert 'GOPROXY=off' in dockerfile and 'GOTOOLCHAIN=local' in dockerfile
    assert 'go mod download && go mod verify && go vet' in dockerfile
    assert 'CGO_ENABLED=0 go build' in dockerfile
    assert 'test ! -e "$GOMODCACHE"' in dockerfile
    assert not list((output/'inputs/cache').rglob('*.ziphash'))
    assert len(list((output/'inputs/cache').rglob('*.zip'))) == 2
    graph = recipes.read_document(output/'commands.json')
    assert '--network=none' in graph['build'] and '--pull=false' in graph['build']
    assert '--rm=false' in graph['build'] and '900' in graph['build']
    assert '--observer-prefixes' in graph['run'] and '120' in graph['run']
    assert '--diagnostics' in graph['run']
    after = {str(p): (p.read_bytes(), p.stat().st_mtime_ns) for p in cache.rglob('*') if p.is_file()}
    assert before == after


def test_source_archive_matches_the_existing_sink_identity():
    import sink
    assert case.source_archive() == sink.sink_source_tar()
    assert case.sha(case.source_archive())[:12] == sink.sink_source_hash()


def test_retained_legacy_build_stages_are_labeled_before_other_instructions():
    text=case.dockerfile('a'*64,'fixed-case').decode()
    stages=text.split('FROM ')[1:]
    assert len(stages)==2
    for stage in stages:
        instructions=stage.splitlines()[1:]
        assert instructions[0].startswith('LABEL org.bgperf2.validation.case="fixed-case"')
    assert 'source-sha256="'+'a'*64+'"' in stages[1].splitlines()[1]


@pytest.mark.parametrize('name', ['context/Dockerfile', 'commands.json', 'CASE.md', 'case.json'])
def test_hash_valid_packet_edits_do_not_widen_selected_case(packet, name):
    _, output, _ = packet
    case.prepare(*packet)
    path = output/name
    path.write_bytes(path.read_bytes().replace(b'900', b'999'))
    if name == 'case.json':
        value = json.loads(path.read_bytes())
        value['workers'] = 9
        path.write_text(json.dumps(value))
    if name == 'context/Dockerfile':
        path.write_bytes(path.read_bytes().replace(b'GOPROXY=off', b'GOPROXY=direct'))
    manifest = recipes.read_document(output/'SHA256SUMS.json')
    manifest[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    (output/'SHA256SUMS.json').write_text(json.dumps(manifest))
    with pytest.raises(recipes.ContractError, match='reconstructed'):
        case.verify(output)


def test_execution_path_cannot_be_rebound_inside_source_even_with_rehashed_packet(packet):
    _, output, _ = packet
    case.prepare(*packet)
    value = recipes.read_document(output/'case.json')
    value['execution'] = str(case.ROOT/'unauthorized-output')
    (output/'case.json').write_text(json.dumps(value))
    with pytest.raises(recipes.ContractError, match='disjoint'):
        case.verify(output, started=True)


def test_fully_rehashed_disjoint_destination_substitution_is_refused(packet):
    cache, output, execution = packet
    case.prepare(*packet)
    alternate = execution.with_name('previous-evidence')
    changed = case.material(cache, output, alternate)
    for name, data in changed.items():
        (output/name).write_bytes(data)
    (output/'SHA256SUMS.json').write_bytes(case.encode({name: case.sha(data) for name, data in changed.items()}))
    with pytest.raises(recipes.ContractError, match='fixed sibling'):
        case.verify(output, started=True)


def test_refuses_overlap_existing_destinations_and_unsafe_cache(packet):
    cache, output, execution = packet
    with pytest.raises(recipes.ContractError, match='disjoint'):
        case.prepare(cache, output, output/'nested')
    leaf = next(cache.rglob('*.zip'))
    original = leaf.read_bytes()
    target = cache/'original.zip'
    target.write_bytes(original)
    leaf.unlink()
    leaf.symlink_to(target)
    with pytest.raises(recipes.ContractError):
        case.prepare(*packet)
    assert not output.exists() and not execution.exists()


@pytest.mark.parametrize('bad_name', ['../outside', '/absolute', 'wrong-module@v/entry'])
def test_cached_zip_members_are_bounded_before_output(packet, bad_name):
    cache, output, _ = packet
    leaf = next(cache.rglob('*.zip'))
    with zipfile.ZipFile(leaf, 'w') as archive:
        archive.writestr(bad_name, 'inert fixture')
    with pytest.raises(recipes.ContractError, match='archive'):
        case.prepare(*packet)
    assert not output.exists()


def built_readbacks(packet):
    _, output, execution = packet
    case.prepare(*packet)
    build = execution/'build'
    build.mkdir(parents=True)
    meta = recipes.read_document(output/'case.json')
    image_id = 'sha256:'+'4'*64
    (build/'image-id.txt').write_text(image_id+'\n')
    (build/'image-inspect.json').write_text(json.dumps([{'Id': image_id, 'Os': 'linux',
        'Config': {'Labels': {'org.bgperf2.validation.source-sha256': meta['source_sha256'],
                              'org.bgperf2.validation.case': meta['case_id']}}}]))
    (build/'version.txt').write_text(f'bgperf-sink 0.2.0 (src {meta["source_sha256"][:12]}) gobgp/v4 v4.9.0 go1.25.14\n')
    for name in ('build', 'inspect', 'version'):
        (build/(name+'-exit.json')).write_text('{"exit_code":0}\n')
    return output, execution, build, image_id


def test_future_image_is_bound_only_after_exact_successful_readbacks(packet, monkeypatch):
    output, execution, _, image = built_readbacks(packet)
    monkeypatch.setattr(socket.socket, '__init__', lambda *a, **kw: pytest.fail('Runtime operation'))
    with pytest.raises(recipes.ContractError, match='Execution root exists'):
        case.verify(output)
    assert case.verify(output, started=True)['valid']
    probe = case.image_commands(output)
    assert probe['image_id'] == image
    assert '--network=none' in probe['version'] and '--pull=never' in probe['version']
    assert '--label' in probe['version'] and '--name' in probe['version']
    assert case.bind(output)['valid']
    recipe = recipes.read_document(execution/'bound/recipe.json')
    assert recipe['roles']['observer']['image'] == image
    assert recipe['roles']['target']['image'] == recipe['roles']['generator']['image'] == case.BIRD
    assert recipe['resolved']['neighbors'] == 1 and recipe['resolved']['prefixes_per_peer'] == 100
    assertions = recipes.read_document(execution/'bound/assertions.json')
    assert len(assertions['assertions']) == 6
    assert case.verify_bound(output)['valid']
    # A valid recipe with a different question must still fail case binding.
    recipe['reproduction']['question'] = 'A different, unapproved question'
    (execution/'bound/recipe.json').write_text(json.dumps(recipe))
    with pytest.raises(recipes.ContractError, match='selected case'):
        case.verify_bound(output)


@pytest.mark.parametrize('mutation', ['image', 'version', 'exit', 'label'])
def test_failed_or_different_build_readbacks_cannot_create_runtime_recipe(packet, mutation):
    output, execution, build, _ = built_readbacks(packet)
    if mutation == 'image':
        (build/'image-id.txt').write_text(case.BIRD)
    elif mutation == 'version':
        (build/'version.txt').write_text('bgperf-sink 0.1.0')
    elif mutation == 'exit':
        (build/'build-exit.json').write_text('{"exit_code":124}')
    else:
        value = json.loads((build/'image-inspect.json').read_text())
        value[0]['Config']['Labels']['org.bgperf2.validation.case'] = 'another-case'
        (build/'image-inspect.json').write_text(json.dumps(value))
    with pytest.raises(recipes.ContractError):
        case.bind(output)
    assert not (execution/'bound').exists()
