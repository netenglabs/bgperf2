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
import os
import re
import time
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


# The log format `sink/log.go` writes. A sink that names another is refused
# rather than read: a reader that half-understood a new format would publish a
# count it parsed by guesswork.
SINK_LOG_FORMAT = 1

# The sink's own `-heartbeat` default. A heartbeat follows any second in which
# nothing else was written, so a log with no line for several of them is a
# sink that has stopped, not one with nothing to say.
SINK_HEARTBEAT_S = 1
SINK_STALE_HEARTBEATS = 3


class SinkLogError(RuntimeError):
    '''The sink's log cannot be read as a count.

    Raised for a log that is malformed, inconsistent with itself, of an unknown
    format, or silent past its heartbeat. The caller records the poll as a
    failed read of the instrument -- the same status a `gobgp neighbor -j` that
    did not answer has -- and never as a sink holding nothing.
    '''


class SinkLog:
    '''What a sink's log says so far, folded from its complete lines.

    The count is the last C line's; H and E lines restate it and are checked
    against it rather than trusted over it. A V line opens a new sink process,
    and a process that starts holds nothing, so it resets everything the
    previous one reported -- the log is opened for append, and a restarted sink
    writes after the old one's last line.

    The session is established from `S established <direction> <conn>` until
    an `S down` or `S dropped` for that same connection. Direction is not
    enough: a second connection that fails or loses to the held one is logged
    `down` too, from either direction, and must not end the session the other
    connection holds. The count does not depend on this: the sink writes its
    zero at once when the session goes.
    '''

    def __init__(self):
        self.malformed = []
        self.malformed_lines = 0
        self.lines = 0
        self.processes = 0
        # The largest distance between the dates of two consecutive lines. A
        # sink that stalled and recovered between two polls is invisible to
        # the staleness check at either poll; this is where it shows.
        self.max_line_gap_ns = None
        self.last_line_ns = None
        self._reset_process()

    def _reset_process(self):
        self.version = None
        self.boot_monotonic_ns = None
        self.boot_realtime_ns = None
        self.accepted = 0
        self.updates = 0
        self.eor = 0
        self.count_ns = None
        self.eor_ns = None
        self.session = None
        self.sessions_established = 0
        self.refused_messages = 0
        self.last_refused = None

    def _bad(self, line, why):
        self.malformed_lines += 1
        # Bounded, like every sample this tool keeps of a log that may run away.
        if len(self.malformed) < 5:
            self.malformed.append('{0}: {1!r}'.format(why, line[:200]))

    def feed(self, text):
        for line in text.split('\n'):
            if line:
                self.feed_line(line)

    def feed_line(self, line):
        self.lines += 1
        parts = line.split(' ')
        if len(parts) < 2 or len(parts[0]) != 1:
            return self._bad(line, 'not a sink log line')
        kind = parts[0]
        try:
            ns = int(parts[1])
        except ValueError:
            return self._bad(line, 'timestamp is not an integer')
        if kind != 'V' and self.processes == 0:
            return self._bad(line, 'line before the format line')

        if kind == 'V':
            if len(parts) < 3 or parts[2] != str(SINK_LOG_FORMAT):
                return self._bad(line, 'log format is not {0}'.format(
                    SINK_LOG_FORMAT))
            self.processes += 1
            self._reset_process()
            self.version = ' '.join(parts[3:]) or None
            # A new process's clock is the same clock, so the gap from the old
            # one's last line is real time the instrument was not running.
        elif kind == 'B':
            try:
                self.boot_realtime_ns = int(parts[2])
            except (IndexError, ValueError):
                return self._bad(line, 'B line without a realtime reading')
            self.boot_monotonic_ns = ns
        elif kind in 'CHE':
            want = 5 if kind != 'E' else 4
            if len(parts) != want:
                return self._bad(line, '{0} line has {1} fields, not {2}'.format(
                    kind, len(parts), want))
            try:
                fields = [int(f) for f in parts[2:]]
            except ValueError:
                return self._bad(line, 'non-integer count')
            if kind == 'C':
                self.accepted, self.updates, self.eor = fields
                self.count_ns = ns
            elif kind == 'H':
                if fields != [self.accepted, self.updates, self.eor]:
                    return self._bad(line, 'heartbeat disagrees with the last count')
            else:
                if fields != [self.accepted, self.updates]:
                    return self._bad(line, 'End-of-RIB disagrees with the last count')
                self.eor_ns = ns
        elif kind == 'S':
            state = parts[2] if len(parts) > 2 else ''
            if state in ('established', 'down', 'dropped'):
                if len(parts) < 5:
                    return self._bad(line, 'session line without a connection')
                conn = parts[3] + ' ' + parts[4]
                if state == 'established':
                    self.session = conn
                    self.sessions_established += 1
                elif conn == self.session:
                    self.session = None
        elif kind == 'M':
            self.refused_messages += 1
            self.last_refused = ' '.join(parts[2:])[:200]
        else:
            return self._bad(line, 'unknown line kind {0!r}'.format(kind))

        if self.last_line_ns is not None:
            gap = ns - self.last_line_ns
            if self.max_line_gap_ns is None or gap > self.max_line_gap_ns:
                self.max_line_gap_ns = gap
        # Lines are written in order but dated by the writer, and a count is
        # dated to its last UPDATE rather than to its write; the latest date
        # seen is what the next gap is measured from.
        if self.last_line_ns is None or ns > self.last_line_ns:
            self.last_line_ns = ns

    def clock_offset_ns(self, host_realtime_ns, host_monotonic_ns):
        '''How far the sink's monotonic clock is from the host's, in ns.

        The B line reads the sink's two clocks together; the arguments are
        the host's two, read together. CLOCK_REALTIME is one clock for every
        namespace, so the difference of the two offsets is how far apart the
        two monotonic clocks are -- zero, to within the reads' spacing and any
        realtime step between them, when the container shares the host's
        clock as the controller assumes. None before a B line has been read.
        '''
        if self.boot_monotonic_ns is None:
            return None
        return ((self.boot_realtime_ns - self.boot_monotonic_ns)
                - (host_realtime_ns - host_monotonic_ns))

    def sample(self, now_ns,
               stale_after_ns=SINK_STALE_HEARTBEATS * SINK_HEARTBEAT_S * 10**9):
        '''The count as a monitor sample, shaped as `gobgp neighbor -j` was.

        `afi_safis[0].state.accepted` is the only field any consumer reads, and
        it is always present: the sink has no "not yet" in which GoBGP omitted
        it. The rest of what the log says travels under `sink`.

        `now_ns` is the host's CLOCK_MONOTONIC when the sample was taken. A
        log whose newest line is older than `stale_after_ns` by that clock is a
        sink that has stopped writing -- it heartbeats every quiet second -- and
        its last count is not a count of anything now.
        '''
        if self.malformed_lines:
            raise SinkLogError('the sink log has {0} malformed line(s): {1}'.format(
                self.malformed_lines, '; '.join(self.malformed)))
        if self.processes == 0 or self.last_line_ns is None:
            raise SinkLogError('the sink has not written its log yet')
        silent = now_ns - self.last_line_ns
        if silent > stale_after_ns:
            raise SinkLogError(
                'the sink log has had no line for {0:.3f}s, past {1:.3f}s of '
                'heartbeats: the sink has stopped'.format(
                    silent / 1e9, stale_after_ns / 1e9))
        return {
            'afi_safis': [{'state': {'accepted': self.accepted}}],
            'state': {'session_state':
                      'established' if self.session else 'idle'},
            'sink': {
                'count_ns': self.count_ns,
                'updates': self.updates,
                'eor': self.eor,
                'eor_ns': self.eor_ns,
                'processes': self.processes,
                'sessions_established': self.sessions_established,
                'refused_messages': self.refused_messages,
                'max_line_gap_ns': self.max_line_gap_ns,
            },
        }


class SinkLogReader:
    '''Read a sink's log from the host, incrementally.

    The sink appends to a file in its bind-mounted directory, so a read costs
    no `docker exec`. It follows `bgpdump2.BlasterLogReader`: only what was
    appended since the last read is consumed, a read stops at the last complete
    line because the sink is still writing, and a log replaced underneath it
    -- a different inode, or one shorter than the saved offset -- starts over
    rather than carrying the old log's count onto a new one. What stat() cannot
    see is a log rewritten in place to past the saved offset; the reader then
    resumes mid-file, and it is the next heartbeat or End-of-RIB, restating a
    count this reader never read, that refuses the sample.

    An unreadable log raises, for the reason `BlasterLogReader.read()` gives:
    failing to ask the instrument is not the instrument answering zero.
    '''

    READ_BLOCK = 1 << 16
    READ_MAX = 4 << 20

    def __init__(self, path):
        self.path = path
        self._pos = 0
        self._log_id = None
        self.log = SinkLog()

    def read(self):
        '''Consume whatever has been appended, and return the `SinkLog`.'''
        st = os.stat(self.path)
        log_id = (st.st_dev, st.st_ino)
        if st.st_size < self._pos or (self._log_id is not None
                                      and log_id != self._log_id):
            self._pos = 0
            self.log = SinkLog()
        self._log_id = log_id
        if st.st_size <= self._pos:
            return self.log
        consumed = 0
        with open(self.path, 'rb') as f:
            while consumed < self.READ_MAX:
                f.seek(self._pos)
                block = f.read(min(self.READ_BLOCK, self.READ_MAX - consumed))
                if not block:
                    break
                end = block.rfind(b'\n')
                if end < 0:
                    if len(block) < self.READ_BLOCK:
                        break       # trailing partial line; wait for more
                    # A whole block with no newline is not a sink line; it is
                    # skipped as malformed rather than re-read forever.
                    self.log._bad(block[:200].decode('utf-8', 'replace'),
                                  'a block with no line end')
                    self._pos += len(block)
                    consumed += len(block)
                    continue
                self.log.feed(block[:end].decode('utf-8', 'replace'))
                self._pos += end + 1
                consumed += end + 1
        return self.log

    def sample(self, now_ns=None, **kwargs):
        '''Read, then return the count as a monitor sample (`SinkLog.sample`).'''
        if now_ns is None:
            now_ns = time.monotonic_ns()
        return self.read().sample(now_ns, **kwargs)
