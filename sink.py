'''The purpose-built monitor image: `bgperf/sink`.

Phase 7 of docs/bgperf2-measurement-implementation-plan.md replaces the GoBGP
monitor with a sink that holds the session to the target, counts prefixes, and
writes its own timestamped count to a log, so nothing has to poll it. Its Go
source lives in `sink/` in this repository; this module turns that source into
an image the way every other daemon module turns an upstream ref into one.

The source is embedded in the recipe rather than handed to Docker as a build
context, and that is deliberate. `prepare` skips a tag that already exists, and
the recipe hash stored on the image (`RECIPE_LABEL_KEY`) is what tells
`doctor`, `images` and `prepare` that a built image no longer matches what
would be built now. That hash covers the rendered Dockerfile text. With a build
context, an edit to `sink/*.go` would leave the text unchanged, and a stale
sink -- the *instrument* -- would read as current. Embedding the source puts
every byte of it inside the hash.
'''

import base64
import hashlib
import io
import re
import tarfile

from base import *


SINK_SOURCE_DIR = REPO_ROOT / 'sink'

# Base64 of the source goes into RUN steps of at most this many characters.
# One RUN's command reaches /bin/sh as a single argument, and Linux caps one
# argument at 128 KiB (MAX_ARG_STRLEN); this leaves room under that however
# large the source grows.
_CHUNK_CHARS = 32 * 1024
_LINE_CHARS = 76


def sink_source_files():
    '''The files the image compiles and tests, in a fixed order.'''
    names = [p for p in SINK_SOURCE_DIR.iterdir()
             if p.is_file() and (p.suffix == '.go' or p.name in ('go.mod', 'go.sum'))]
    return sorted(names, key=lambda p: p.name)


def sink_source_tar():
    '''The source as an uncompressed ustar archive, byte-for-byte reproducible.

    Uncompressed on purpose: gzip output depends on the zlib build, and a
    recipe whose bytes changed with the host's zlib would report a stale image
    nobody touched. Every header field that could vary between checkouts --
    mtime, owner, mode -- is fixed.
    '''
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w', format=tarfile.USTAR_FORMAT) as tar:
        for path in sink_source_files():
            data = path.read_bytes()
            info = tarfile.TarInfo(path.name)
            info.size = len(data)
            info.mtime = 0
            info.mode = 0o644
            info.uid = info.gid = 0
            info.uname = info.gname = ''
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def sink_source_hash(tar_bytes=None):
    '''The first 12 hex digits of the source archive's SHA-256.

    Compiled into the binary, so a running sink names the exact source it was
    built from -- the commit alone would not, from a dirty tree.
    '''
    if tar_bytes is None:
        tar_bytes = sink_source_tar()
    return hashlib.sha256(tar_bytes).hexdigest()[:12]


def _embed(tar_bytes):
    '''RUN steps that write the archive to /src/sink.tar.b64.'''
    encoded = base64.b64encode(tar_bytes).decode('ascii')
    steps = []
    for start in range(0, len(encoded), _CHUNK_CHARS):
        chunk = encoded[start:start + _CHUNK_CHARS]
        lines = [chunk[i:i + _LINE_CHARS] for i in range(0, len(chunk), _LINE_CHARS)]
        # printf reuses `%s` for every argument and adds nothing between
        # them, so the continuation lines rejoin into one unbroken string.
        steps.append('RUN printf %s \\\n    ' + ' \\\n    '.join(lines)
                     + ' \\\n    >> /src/sink.tar.b64')
    return '\n'.join(steps)


class Sink(Container):
    '''The sink's image. Nothing runs it as a monitor yet; see Phase 7a.'''

    CONTAINER_NAME = None
    GUEST_DIR = '/root/config'
    IMAGE_REPO = 'bgperf/sink'
    DAEMON_BINARY = '/usr/local/bin/bgperf-sink'
    # The source is in this repository, so there is no upstream ref to choose:
    # the version is whatever `sink/` holds, and the binary reports its hash.
    SUPPORTS_VERSIONS = False
    # Pinned by digest, not by tag. A tag such as `golang:1.25-bookworm` moves
    # with every patch release while the recipe text -- and so its hash --
    # stays the same, which is the stale-image trap one layer down: two builds
    # months apart would be different instruments that `doctor` calls the
    # same. With the digest in the text, a toolchain change is a recipe change.
    # These are the multi-arch index digests pulled on 2026-10-01 (Go 1.25.14,
    # the series GoBGP 4.9.0's go.mod asks for). Moving one is a deliberate
    # edit, and marks every built sink stale.
    BUILD_VARS = {
        'go_image': 'golang:1.25-bookworm@sha256:'
                    '3b4a11519ad929d1e1d261a12cff056f0c85b735253d7d861346b9c6f8b36437',
        'runtime_image': 'debian:bookworm-slim@sha256:'
                         '3783cc01769c7b2b1b83a5c5ad96c815348e28ed7da68e2e3687004faa906251',
    }

    @classmethod
    def resolve_ref(cls, version):
        '''What `prepare` and `images` name as the build's source.

        There is no git ref: the image is built from whatever `sink/` holds
        now, committed or not, and the source hash is what identifies it.
        '''
        return 'sink/ (src {0})'.format(sink_source_hash())

    def __init__(self, host_dir, conf, image='bgperf/sink'):
        super(Sink, self).__init__(self.CONTAINER_NAME, image, host_dir, self.GUEST_DIR, conf)

    def get_version_cmd(self):
        return [self.DAEMON_BINARY, '-version']

    def exec_version_cmd(self):
        '''`0.1.0 (src 1a2b3c4d5e6f; gobgp/v4 v4.9.0; go1.25.14)`.

        Matched against the banner, never taken by position, for the reason
        every parser here is. The source hash is required: a sink that cannot
        say what it was built from has no identity worth recording.
        '''
        ret = (super().exec_version_cmd() or '').strip()
        m = re.search(r'^bgperf-sink (\S+) \(src ([0-9a-f]{12})\) gobgp/v4 (\S+) (go\S+)$',
                      ret, re.M)
        if not m:
            raise VersionUnavailable(
                'unexpected output from `{0} -version`: {1!r}'.format(
                    self.DAEMON_BINARY, ret))
        return '{0} (src {1}; gobgp/v4 {2}; {3})'.format(*m.groups())

    @classmethod
    def build_image(cls, force=False, tag=None, checkout=None, nocache=False, version=None):
        tag = tag or cls.image_tag()
        v = cls.build_vars(version)
        tar_bytes = sink_source_tar()
        v['source_hash'] = sink_source_hash(tar_bytes)
        v['embedded_source'] = _embed(tar_bytes)
        # The unit tests run in the build, so an image exists only if they
        # passed against the exact source it holds. They need no network, no
        # privileges and no Docker, which keeps the Python suite Docker-free.
        cls.dockerfile = '''
FROM {go_image} AS build
WORKDIR /src
# The source of sink/ in the bgperf2 repository, as a ustar archive, hash {source_hash}.
{embedded_source}
RUN base64 -d sink.tar.b64 | tar -x && rm sink.tar.b64
RUN go mod download && go vet ./... && go test ./...
RUN CGO_ENABLED=0 go build -trimpath -ldflags '-X main.sourceHash={source_hash}' -o /bgperf-sink .

FROM {runtime_image}
COPY --from=build /bgperf-sink /usr/local/bin/bgperf-sink
'''.format(**v)
        super(Sink, cls).build_image(force, tag, nocache=nocache)
