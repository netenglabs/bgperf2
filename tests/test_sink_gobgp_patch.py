"""SIMULATED dependency files; no Docker, downloads or real module-cache edits."""
import hashlib
import json
from pathlib import Path
import subprocess

import pytest
import sink_gobgp_patch as patch


def command(tmp_path, monkeypatch, body=None):
    source = tmp_path/'module/pkg/packet/bgp/bgp.go'
    source.parent.mkdir(parents=True)
    (tmp_path/'module/LICENSE').write_text('SIMULATED upstream license retained')
    project = tmp_path/'project';project.mkdir()
    (project/'go.mod').write_text('module example.test/sink\nrequire (\n\tgithub.com/osrg/gobgp/v4 v4.9.0\n)\n')
    (project/'go.sum').write_text('SIMULATED locked checksums\n')
    original = ('package bgp\n'+patch.OLD+'\n').encode() if body is None else body
    source.write_bytes(original)
    monkeypatch.setattr(patch, 'SOURCE_SHA256', hashlib.sha256(original).hexdigest())
    destination = tmp_path/'fresh overlay'
    return source, destination, original, patch.build_dependency_command(source=str(source), destination=str(destination),project=str(project))


def test_private_copy_is_exclusive_and_keeps_dependency_bytes_unchanged(tmp_path, monkeypatch):
    source, destination, original, shell = command(tmp_path, monkeypatch)
    result = subprocess.run(['sh','-c',shell],capture_output=True,text=True)
    assert result.returncode == 0, result.stderr
    assert source.read_bytes() == original
    assert (destination/'gobgp/pkg/packet/bgp/bgp.go').read_text() == original.decode().replace(patch.OLD, patch.NEW)
    assert (destination/'go.mod').read_text().endswith('replace github.com/osrg/gobgp/v4 => '+json.dumps(str(destination/'gobgp'))+'\n')
    assert (destination/'gobgp/LICENSE').read_text() == 'SIMULATED upstream license retained'
    before = (destination/'gobgp/pkg/packet/bgp/bgp.go').read_bytes()
    assert subprocess.run(['sh','-c',shell],capture_output=True).returncode != 0
    assert (destination/'gobgp/pkg/packet/bgp/bgp.go').read_bytes() == before and source.read_bytes() == original


@pytest.mark.parametrize('failure', ['hash','missing_statement','duplicate_statement'])
def test_drift_refuses_before_overlay_publication(tmp_path, monkeypatch, failure):
    body = None
    if failure == 'missing_statement': body = b'package changed\n'
    if failure == 'duplicate_statement': body = (patch.OLD+'\n'+patch.OLD+'\n').encode()
    source, destination, original, shell = command(tmp_path, monkeypatch, body)
    if failure == 'hash': source.write_bytes(original+b'changed')
    assert subprocess.run(['sh','-c',shell],capture_output=True).returncode != 0
    assert not destination.exists()


def test_paths_are_shell_quoted_and_never_interpreted(tmp_path, monkeypatch):
    parent = tmp_path/"source ' $(false)";parent.mkdir()
    source,destination,original,shell=command(parent,monkeypatch)
    result = subprocess.run(['sh','-c',shell],capture_output=True,text=True)
    assert result.returncode == 0, result.stderr
    assert source.read_bytes() == original
    assert json.dumps(str(destination/'gobgp')) in (destination/'go.mod').read_text()


@pytest.mark.parametrize('source,destination', [('relative','/tmp/owned'),('/source','relative'),('/source','/tmp/../other')])
def test_relative_or_parent_traversal_refused(source,destination):
    with pytest.raises(ValueError): patch.build_dependency_command(source=source,destination=destination)


@pytest.mark.parametrize('change', ['version', 'replace'])
def test_project_dependency_drift_refuses_instead_of_overriding_it(tmp_path, monkeypatch, change):
    source,destination,original,shell=command(tmp_path,monkeypatch)
    modfile=tmp_path/'project/go.mod'
    text=modfile.read_text()
    modfile.write_text(text.replace('v4.9.0','v4.9.1') if change=='version' else text+'replace x => y\n')
    assert subprocess.run(['sh','-c',shell],capture_output=True).returncode != 0
    assert not destination.exists() and source.read_bytes()==original



def test_dependency_command_is_safe_as_one_docker_run_instruction():
    command_text=patch.build_dependency_command()
    assert '\n' not in command_text and '\r' not in command_text
    assert "printf '\\n%s\\n'" in command_text


@pytest.mark.parametrize('path', ['/tmp/line\nbreak','/tmp/line\rbreak','/tmp/nul\0byte'])
def test_multiline_or_nul_paths_refused_for_dockerfile_context(path):
    with pytest.raises(ValueError): patch.build_dependency_command(destination=path)
