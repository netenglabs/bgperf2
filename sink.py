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
    '''The sink's image. `monitor.SinkMonitor` is the class that runs it.'''

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

# Past this, the sink's monotonic clock is not the host's in any sense the
# controller could date an event by. The measured offsets are 1-3 µs; a
# container in its own time namespace is off by its whole offset, which is
# seconds or more. `scripts/monitor_pair_review.py` fails a pair on the same
# number (it imports nothing from here, and a test pins the two together).
SINK_CLOCK_OFFSET_LIMIT_NS = 1_000_000


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

    def __init__(self, required=None):
        # The monitor's check-point, so the line on which the count first
        # reached it can be dated (measurement plan 7b). None for a log read
        # without one -- a receiver's, or the evidence read at a run's end.
        self.required = required
        self.malformed = []
        self.malformed_lines = 0
        self.lines = 0
        self.processes = 0
        # The largest distance between the dates of two consecutive lines. A
        # sink that stalled and recovered between two polls is invisible to
        # the staleness check at either poll; this is where it shows.
        self.max_line_gap_ns = None
        self.last_line_ns = None
        # Held sessions that ended, by `down` or `dropped` on the connection
        # the session was on; a lost collision is not one. Counted over the
        # whole log, not per process: a restart must not erase the loss that
        # came before it.
        self.sessions_lost = 0
        # Over the whole log for the same reason, so the three are read on
        # one scope: established 2, lost 1 means a session came back.
        self.sessions_established = 0
        self.refused_messages = 0
        self.last_refused = None
        # UPDATEs the session was kept through under GoBGP's revised error
        # handling, which an M line names by its first word (`keptLine()` in
        # `sink/session.go`). Not refusals: GoBGP did the same, so they are
        # counted apart rather than reported as a fault in the instrument.
        self.kept_messages = 0
        self.last_kept = None
        self.session = None
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
        # The three moments the monitor's lifecycle events are dated to, each
        # as (the C line's date, the date of the line before it, the count the
        # line shows). A count
        # first shown on a C line became true after the previous line and no
        # later than its own (`sink/log.go`), so the pair is the event and the
        # bound on it. Per process, like the count they describe: a restarted
        # sink holds nothing, and its first prefix is a first prefix again.
        self.first_prefix_at = None
        self.required_at = None
        self.changed_at = None
        if self.session is not None:
            # A process that ends holds nothing, so a session it held when
            # the next one started was lost with it.
            self.sessions_lost += 1
        self.session = None

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
                previous = self.accepted
                self.accepted, self.updates, self.eor = fields
                self.count_ns = ns
                self._date_count(ns, previous)
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
                    self.sessions_lost += 1
        elif kind == 'M':
            detail = ' '.join(parts[2:])[:200]
            if parts[2:3] in (['treat-as-withdraw'], ['attribute-discard']):
                self.kept_messages += 1
                self.last_kept = detail
            else:
                self.refused_messages += 1
                self.last_refused = detail
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

    def _date_count(self, ns, previous):
        '''Date what this C line changed, to the line and the one before it.

        `last_line_ns` has not moved yet, so it is the latest date of any line
        before this one. That can be *later* than this line's own date: the
        sink stamps an UPDATE before it takes the log's lock, and a heartbeat
        can be written in between. The pair is kept as read, inverted or not,
        and `measurements.SinkDates` refuses an inverted one -- a bound that
        ends before it starts is not a resolution of zero.

        Each date marks the start of the stretch the count is in now. A
        first prefix is re-armed when the count returns to zero, and the
        check-point when it falls below it: a session that dropped holds
        nothing, so a crossing it lost is not the one a later poll sees.
        '''
        at = (ns, self.last_line_ns, self.accepted)
        if self.accepted == previous:
            # A C line is also written for an UPDATE that left the count where
            # it was -- a re-announcement, a withdrawal of a prefix not held.
            # That is not a change of the count, and `monitor_last_change`
            # must not be dated to it.
            return
        self.changed_at = at
        if self.accepted == 0:
            self.first_prefix_at = None
        elif self.first_prefix_at is None:
            self.first_prefix_at = at
        if self.required is not None:
            if self.accepted < self.required:
                self.required_at = None
            elif self.required_at is None:
                self.required_at = at

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

    def evidence(self, host_realtime_ns, host_monotonic_ns):
        '''What the log says about the instrument itself, for the artifact.

        The run's samples carry the count; this carries what would make the
        count doubtful. A session that was lost and came back, a sink process
        that restarted (`processes` above 1), a stall between two lines, a
        monotonic clock that is not the host's, and a malformed line are each
        invisible in a count that ended right. 7a's checks 3 and 5 read them
        from here, rather than from a log the next run overwrites.
        '''
        return {
            'version': self.version,
            'processes': self.processes,
            'lines': self.lines,
            'malformed_lines': self.malformed_lines,
            'malformed': list(self.malformed),
            'accepted': self.accepted,
            'updates': self.updates,
            'eor': self.eor,
            'sessions_established': self.sessions_established,
            'sessions_lost': self.sessions_lost,
            'refused_messages': self.refused_messages,
            'last_refused': self.last_refused,
            'kept_messages': self.kept_messages,
            'last_kept': self.last_kept,
            'max_line_gap_ns': self.max_line_gap_ns,
            'clock_offset_ns': self.clock_offset_ns(host_realtime_ns,
                                                    host_monotonic_ns),
        }

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
                'kept_messages': self.kept_messages,
                'max_line_gap_ns': self.max_line_gap_ns,
                'first_prefix_at': self.first_prefix_at,
                'required_at': self.required_at,
                'changed_at': self.changed_at,
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

    def __init__(self, path, required=None):
        self.path = path
        # Held here as well as on the log, because a replaced log starts a
        # new `SinkLog` and the check-point must survive that.
        self.required = required
        self._pos = 0
        self._log_id = None
        self._offset_key = None
        self._offset = None
        self.log = SinkLog(required)

    def read(self, until_ns=None):
        '''Consume whatever has been appended, and return the `SinkLog`.

        With `until_ns`, a line dated after it is left unread, and so is
        everything after that line, for the next read. A poll stamps its
        sample *before* it reads, so without this a sample would carry a count
        and dates the sink wrote during the read, after the instant the sample
        claims to describe -- and an event dated after its own sample is one
        the controller has to refuse (measurement plan 7b).
        '''
        st = os.stat(self.path)
        log_id = (st.st_dev, st.st_ino)
        if st.st_size < self._pos or (self._log_id is not None
                                      and log_id != self._log_id):
            self._pos = 0
            self.log = SinkLog(self.required)
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
                if until_ns is None:
                    self.log.feed(block[:end].decode('utf-8', 'replace'))
                    self._pos += end + 1
                    consumed += end + 1
                    continue
                taken = self._feed_until(block[:end + 1], until_ns)
                self._pos += taken
                consumed += taken
                if taken < end + 1:
                    break
        return self.log

    def _feed_until(self, lines, until_ns):
        '''Feed complete lines up to the first dated after `until_ns`.

        Returns the bytes consumed. `until_ns` is on the host's clock and a
        line's date on the sink's, so a line is held back only while the
        sink's clock has been shown to be the host's: a V or B line never is,
        and nothing is held before a B line has been read or when its offset
        is past `SINK_CLOCK_OFFSET_LIMIT_NS`. Otherwise a sink whose clock ran
        ahead would have every line held, and the run would wait forever for
        a count -- where the rule is that such a sink's *dates* are refused,
        not its count. A line whose date does not parse is fed, and `SinkLog`
        refuses it as malformed: holding it back would re-read it forever.
        '''
        taken = 0
        for raw in lines.splitlines(keepends=True):
            parts = raw.split(b' ', 2)
            if parts[0] not in (b'V', b'B') and self.clock_agrees():
                try:
                    if len(parts) > 1 and int(parts[1]) > until_ns:
                        break
                except ValueError:
                    pass
            self.log.feed(raw.decode('utf-8', 'replace'))
            taken += len(raw)
        return taken

    def clock_offset_ns(self):
        '''The sink process's clock offset from the host's, measured once.

        Measured once per B line rather than per read, because CLOCK_REALTIME
        can be stepped mid-run while both monotonic clocks run on untouched,
        and a step of a millisecond would flip the rest of the run to refused
        dating partway through -- one run's events dated two ways for a reason
        that says nothing about the clock the dates are on. A new B line, a
        restarted sink or a replaced log, is measured afresh. None before a B
        line.
        '''
        log = self.log
        key = (id(log), log.processes, log.boot_monotonic_ns)
        if self._offset_key != key:
            self._offset_key = key
            self._offset = log.clock_offset_ns(time.time_ns(),
                                               time.monotonic_ns())
        return self._offset

    def clock_agrees(self):
        offset = self.clock_offset_ns()
        return offset is not None and abs(offset) <= SINK_CLOCK_OFFSET_LIMIT_NS

    def read_all(self):
        '''Read to the last complete line, however many bounded reads it takes.

        `read()` stops at `READ_MAX` and expects to be called again, which is
        right for a poll. A one-shot reading of the whole log -- the evidence
        written at the end of a run -- would otherwise describe only its first
        4 MiB.
        '''
        while True:
            before = self._pos
            log = self.read()
            if self._pos == before:
                return log

    def sample(self, now_ns=None, **kwargs):
        '''Read, then return the count as a monitor sample (`SinkLog.sample`).'''
        if now_ns is None:
            now_ns = time.monotonic_ns()
        # As of `now_ns`: the count, its dates and the staleness check all
        # describe one instant.
        return self.read(until_ns=now_ns).sample(now_ns, **kwargs)
