'''The sink image's recipe and version parser (measurement plan Phase 7a).

The sink's own behaviour -- counting, the log, the session -- is covered by Go
unit tests that run inside the image build. These cover the Python half: that
the recipe carries exactly the source in `sink/`, so the recipe hash moves when
the source does, and that the version banner is parsed rather than sliced.
'''

import base64
import io
import re
import shutil
import tarfile

import pytest

import base
import bgperf2
import contention
import sink


def embedded_archive(dockerfile):
    '''Reassemble the archive the RUN printf steps write, as the build does.'''
    steps = re.findall(r'^RUN printf %s \\\n(.*?)>> /src/sink\.tar\.b64$',
                       dockerfile, re.M | re.S)
    assert steps, 'no embedded source in the recipe'
    encoded = ''.join(''.join(part.split()).replace('\\', '') for part in steps)
    return base64.b64decode(encoded)


def test_archive_is_reproducible():
    assert sink.sink_source_tar() == sink.sink_source_tar()


def test_archive_holds_exactly_the_source_files():
    with tarfile.open(fileobj=io.BytesIO(sink.sink_source_tar())) as tar:
        names = tar.getnames()
        for member in tar.getmembers():
            assert member.mtime == 0 and member.uid == 0
            assert tar.extractfile(member).read() == (sink.SINK_SOURCE_DIR / member.name).read_bytes()
    assert names == sorted(names)
    assert {'go.mod', 'go.sum', 'main.go', 'table.go', 'session.go', 'log.go'} <= set(names)
    assert any(n.endswith('_test.go') for n in names), 'the build runs the Go tests'


def test_recipe_embeds_the_archive_and_names_its_hash():
    dockerfile = sink.Sink.render_dockerfile()
    archive = embedded_archive(dockerfile)
    assert archive == sink.sink_source_tar()
    h = sink.sink_source_hash(archive)
    assert "-X main.sourceHash={0}'".format(h) in dockerfile
    assert 'go test ./...' in dockerfile


def test_chunked_embedding_reassembles(monkeypatch):
    '''A source too large for one RUN argument is split, and still decodes.'''
    monkeypatch.setattr(sink, '_CHUNK_CHARS', 1000)
    dockerfile = sink.Sink.render_dockerfile()
    assert dockerfile.count('RUN printf %s') > 10
    assert embedded_archive(dockerfile) == sink.sink_source_tar()


def test_editing_the_source_moves_the_recipe_hash(tmp_path, monkeypatch):
    '''The reason the source is embedded: a stale sink must read as stale.'''
    copy = tmp_path / 'sink'
    shutil.copytree(sink.SINK_SOURCE_DIR, copy)
    monkeypatch.setattr(sink, 'SINK_SOURCE_DIR', copy)
    before = sink.Sink.current_recipe_hash()
    (copy / 'table.go').write_text((copy / 'table.go').read_text() + '\n// edited\n')
    assert sink.Sink.current_recipe_hash() != before


def test_no_versions_to_select():
    assert sink.Sink.image_tag() == 'bgperf/sink:latest'
    with pytest.raises(base.VersionNotSupported):
        sink.Sink.image_tag('1.0')


def probe(monkeypatch, output):
    monkeypatch.setattr(base.Container, 'exec_version_cmd',
                        lambda self, stderr=False: output)
    s = sink.Sink.__new__(sink.Sink)
    s.name = 'probe'
    return s


def test_version_banner(monkeypatch):
    s = probe(monkeypatch, 'bgperf-sink 0.1.0 (src 793fa1b81a76) gobgp/v4 v4.9.0 go1.25.14\n')
    assert s.exec_version_cmd() == '0.1.0 (src 793fa1b81a76; gobgp/v4 v4.9.0; go1.25.14)'
    # No comma survives into a row that is joined with commas.
    assert ',' not in s.version_string()


@pytest.mark.parametrize('output', [
    '',
    'OCI runtime exec failed: exec failed: unable to start container process',
    # Built without the source hash: no identity worth recording.
    'bgperf-sink 0.1.0 (src unknown) gobgp/v4 v4.9.0 go1.25.14',
])
def test_version_refuses_anything_else(monkeypatch, output):
    s = probe(monkeypatch, output)
    with pytest.raises(base.VersionUnavailable):
        s.exec_version_cmd()
    assert s.version_string().startswith(base.VERSION_UNKNOWN)


def test_registered_for_prepare_verify_and_contention():
    assert bgperf2.BUILDABLE_IMAGES['sink'] is sink.Sink
    assert 'sink' in bgperf2.PREPARE_IMAGES
    # Its own load must never be published as contention.
    assert 'bgperf-sink' in contention.BGPERF_PROCESSES
    assert sink.Sink.DAEMON_BINARY.rsplit('/', 1)[-1] == 'bgperf-sink'
