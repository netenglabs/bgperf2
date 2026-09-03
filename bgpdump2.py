import re
from base import *
from measurements import TesterOffering
from mrt_tester import MRTTester


# --- the blaster's own log --------------------------------------------------
#
# bgpdump2 --blaster writes one line per event to stdout, each prefixed with a
# local wall-clock timestamp (`%b %d %H:%M:%S.%06lu`, no year and no zone).
# Those timestamps are deliberately not parsed: durations in this project come
# from the controller's monotonic clock, and a local timestamp with no year
# cannot be one.  What the log carries that nothing else does is the
# generator's own account of the workload -- the RIB it loaded, what it has
# encoded, whether it finished, and how much of it reached the socket.
#
# Two counters on the same line, measured at different places:
#
#   `N prefixes sent` is incremented as prefixes are *encoded* into the session
#   write buffer, and `N octets` only by a successful write() to the socket.
#   The real capture behind these fixtures shows the gap plainly: a mid-walk
#   line reads `Sent 2280 updates, 9981 prefixes sent, 0 prefixes withdrawn, 88
#   octets` -- 9,981 prefixes encoded against 88 bytes actually on the wire.
#   So prefix counts are queue-side evidence, like BIRD 2.19's, and the octet
#   count is wire-side.  Read together they say what a single number cannot.
#
# Blocked-write evidence is in the log only when the blaster was started with
# `-t io`, which bgperf does under --tester-trace-io and not otherwise; see
# Bgpdump2Tester.get_startup_cmd() for what that costs.  Three of that class's
# lines are read here:
#
#   `Full write N bytes buffer to <peer>` -- write() took the whole buffer.
#   `Partial write N bytes buffer to <peer>` -- it took only part of it, which
#   is the socket's send buffer refusing the rest.
#   `Write buffer full` -- an encode pass found fewer than BGP_MAX_MESSAGE_SIZE
#   bytes free in the 256KB session buffer and could not encode at all.
#
# The third is the one that catches a socket that has stopped taking anything:
# a write() returning EAGAIN is logged nowhere, so a fully blocked session
# writes no `Partial write` line and shows up only as the encoder stalling
# behind a buffer that never drains.
#
# `Full write` is not evidence of backpressure, but seeing any of the three is
# what proves the class is enabled -- and therefore that a count of 0 means the
# generator was never blocked, rather than that nobody asked.  A session that
# has put a byte on the wire has logged a write line, so the distinction
# resolves itself as soon as there is anything to be blocked about.

_LOG_LINE = re.compile(
    r'^[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}\.\d+\s+(?P<message>.*)$')
_STATE_CHANGE = re.compile(
    r'^Neighbor\s+(?P<peer>\S+)\s+state change from\s+(?P<old>\S+)\s+->\s+'
    r'(?P<new>\S+)$')
_RIB_START = re.compile(
    r'^RIB for peer-index\s+(?P<index>\d+):\s+AS\s+(?P<asn>\d+),\s+'
    r'ipv4 prefixes\s+(?P<ipv4>\d+),\s+ipv6 prefixes\s+(?P<ipv6>\d+),\s+'
    r'(?P<paths>\d+) paths$')
_SENT = re.compile(
    r'^Sent\s+(?P<updates>\d+) updates,\s+(?P<prefixes>\d+) prefixes sent,\s+'
    r'(?P<withdrawn>\d+) prefixes withdrawn,\s+(?P<octets>\d+) octets$')
_END_OF_RIB = re.compile(
    r'^End-of-RIB, walk time\s+(?P<seconds>\d+\.\d+)s$')
_WALK_COMPLETE = 'RIB walk complete'
_WRITE = re.compile(
    r'^(?P<kind>Full|Partial) write\s+\d+ bytes buffer to\s+\S+$')
_WRITE_BUFFER_FULL = 'Write buffer full'


class BlasterLog:
    '''One injector's `bgpdump2 --blaster` log, accumulated a chunk at a time.

    The facts live in the object rather than in one pass over the whole text
    because bgperf reads this log once a second for the length of a run, and a
    poll should cost the bytes that were appended since the last one.  Feeding
    chunks is also the only way the facts stay whole: `End-of-RIB` belongs to
    the `RIB for peer-index` line that opened the walk, which may have arrived
    several polls earlier, so parsing each chunk in isolation would drop the
    walk time it carries.

    Counts are absent until the log reports them, never 0: an injector that has
    sent nothing and an injector whose log could not be read must not produce
    the same measurement.
    '''

    def __init__(self):
        self.peer = None
        self.state = None
        # Every RIB the session walks, in walk order, holding the table it
        # loaded and -- once its End-of-RIB is logged -- the walk time bgpdump2
        # measured itself.
        self.ribs = []
        self.counters = {}
        self.walk_complete = False
        # Blocked-write evidence, present only under `-t io`. `io_traced` is
        # what separates 'never blocked' from 'never asked': until one of the
        # class's lines has been seen, a count of 0 says nothing at all.
        self.io_traced = False
        self.full_writes = 0
        self.partial_writes = 0
        self.write_stalls = 0

    def feed(self, text):
        '''Absorb a chunk of log text made of complete lines.

        A line that does not match is skipped rather than guessed at, which is
        also what makes an incremental reader safe: a half-written final line
        contributes nothing instead of a wrong number.
        '''
        for raw in text.splitlines():
            line = _LOG_LINE.match(raw)
            if not line:
                # Option parsing prints before logging starts
                # ('peer_spec_index[1]: register peer 3, asn 7018'), and an
                # incremental read can end mid-line.
                continue
            message = line.group('message').strip()

            m = _STATE_CHANGE.match(message)
            if m:
                self.state = m.group('new')
                self.peer = m.group('peer')
                continue

            m = _RIB_START.match(message)
            if m:
                self.ribs.append({
                    'peer_index': int(m.group('index')),
                    'peer_as': int(m.group('asn')),
                    'ipv4_prefixes': int(m.group('ipv4')),
                    'ipv6_prefixes': int(m.group('ipv6')),
                    'paths': int(m.group('paths')),
                    'walk_time_s': None,
                })
                continue

            m = _SENT.match(message)
            if m:
                self.counters = {
                    'updates_sent': int(m.group('updates')),
                    'prefixes_sent': int(m.group('prefixes')),
                    'prefixes_withdrawn': int(m.group('withdrawn')),
                    'octets_sent': int(m.group('octets')),
                }
                continue

            m = _END_OF_RIB.match(message)
            if m and self.ribs:
                # bgpdump2 restarts its walk clock for each RIB, so this
                # belongs to the RIB currently being walked, not to the
                # session.
                self.ribs[-1]['walk_time_s'] = float(m.group('seconds'))
                continue

            m = _WRITE.match(message)
            if m:
                # These are the only facts here that accumulate rather than
                # overwrite, so feeding a line twice would overcount where it
                # is harmless for the rest. BlasterLogReader is what keeps that
                # from happening: it feeds complete lines only and advances its
                # offset past exactly what it fed.
                self.io_traced = True
                if m.group('kind') == 'Full':
                    self.full_writes += 1
                else:
                    # The socket took part of the buffer and refused the rest.
                    self.partial_writes += 1
                continue

            if message == _WRITE_BUFFER_FULL:
                # An encode pass that could not encode: the session's 256KB
                # buffer had not drained. This is also where a write() that
                # returned EAGAIN surfaces, since that is logged nowhere.
                self.io_traced = True
                self.write_stalls += 1
                continue

            if message == _WALK_COMPLETE:
                self.walk_complete = True
        return self

    def facts(self):
        return {
            'peer': self.peer,
            'state': self.state,
            'established': self.state == 'established',
            'ribs': tuple(dict(rib) for rib in self.ribs),
            'walk_complete': self.walk_complete,
            'updates_sent': self.counters.get('updates_sent'),
            'prefixes_sent': self.counters.get('prefixes_sent'),
            'prefixes_withdrawn': self.counters.get('prefixes_withdrawn'),
            'octets_sent': self.counters.get('octets_sent'),
            'io_traced': self.io_traced,
            'full_writes': self.full_writes,
            'partial_writes': self.partial_writes,
            'write_stalls': self.write_stalls,
        }


def parse_blaster_log(text):
    '''Parse one injector's whole blaster log into facts.'''
    return BlasterLog().feed(text).facts()


class BlasterLogReader:
    '''Read one injector's blaster log from the host, incrementally.

    `start.sh` redirects the blaster's stdout into the bind-mounted host
    directory, so the controller reads this file directly and a poll costs no
    `docker exec` at all.

    Only what was appended since the last read is consumed, for the reason
    `frr._get_EOR_from_log()` does the same.  bgpdump2 logs a `Sent ...` line
    per write() to the socket, and a write carries whatever the socket would
    take at that moment -- one of the captured runs shows an 88-octet write --
    so the number of lines is a property of how the peer drained the session,
    not of the table size, and nothing bounds it in advance.  Re-reading and
    re-matching the whole file once a second is the exact shape that made the
    FRR reader the bottleneck it was supposed to be measuring.
    '''

    READ_BLOCK = 1 << 16
    # Cap the bytes one poll may consume. This process's own RSS feeds the
    # recorded min_free column, so a log that ran away must not be pulled into
    # memory in one go; the remainder is read by the next poll.
    READ_MAX = 4 << 20

    def __init__(self, path):
        self.path = path
        self._pos = 0
        self._log = BlasterLog()
        self._log_id = None

    def read(self):
        '''Consume whatever has been appended, and return the facts so far.

        An unreadable log raises. This file is the only account the injector
        gives of itself, so failing to read it is 'the generator could not be
        asked', which `offering_stats()` records as a read failure -- and that
        has to stay distinct from an injector that was read and had sent
        nothing.
        '''
        st = os.stat(self.path)
        # A replaced log is identified by inode as well as by size, the way
        # frr._get_EOR_from_log() does it: a replacement that had already grown
        # past the saved offset is not smaller, so a size check alone would
        # seek into the middle of the new file, never see the lines that open
        # its session, and keep reporting the old log's completion for a
        # session that no longer exists. What neither check can see is a log
        # truncated and rewritten to the same size between two polls, which
        # leaves nothing in stat() to notice.
        log_id = (st.st_dev, st.st_ino)
        if st.st_size < self._pos or (self._log_id is not None
                                      and log_id != self._log_id):
            # Everything the accumulated facts describe went with the old log,
            # so they are dropped rather than carried onto a different one: a
            # stale `RIB walk complete` would otherwise report a completion
            # this run never made.
            self._pos = 0
            self._log = BlasterLog()
        self._log_id = log_id
        if st.st_size <= self._pos:
            return self._log.facts()
        consumed = 0
        with open(self.path, 'rb') as f:
            while consumed < self.READ_MAX:
                f.seek(self._pos)
                block = f.read(min(self.READ_BLOCK, self.READ_MAX - consumed))
                if not block:
                    break
                # The blaster may be mid-write, so stop at the last complete
                # line and resume from the start of the partial one next time.
                end = block.rfind(b'\n')
                if end < 0:
                    if len(block) < self.READ_BLOCK:
                        break       # trailing partial line; wait for more
                    # A whole block with no newline in it would otherwise be
                    # re-read forever.
                    self._pos += len(block)
                    consumed += len(block)
                    continue
                self._log.feed(block[:end].decode('utf-8', 'replace'))
                self._pos += end + 1
                consumed += end + 1
        return self._log.facts()


def tester_offering(text):
    '''What one bgpdump2 injector says it has offered, from its whole log.'''
    return tester_offering_from_facts(parse_blaster_log(text))


def tester_offering_from_facts(parsed):
    '''What one bgpdump2 injector says it has offered, from parsed log facts.

    `send_complete` is the point of this summary.  bgpdump2 logs `RIB walk
    complete` when it has walked every RIB it was given, which is positive
    evidence of the send contract being finished -- and it has to be, because
    for MRT playback the count cannot supply it.  `-T` caps the table while the
    MRT file is read, so what an injector ends up holding is a property of that
    peer's table rather than of the number asked for; an injector that walked
    its whole RIB has finished even if the RIB held 9,998 of the 10,000
    requested, and waiting for `offered >= expected` would wait forever.  The
    configured-versus-expected comparison stays available separately, which is
    where a workload that did not load is supposed to show up.

    `offered` is queue-side and `octets_on_wire` is not; see the note above.

    `blocked_writes` and `send_stalls` are None unless the log proves the IO
    log class was on.  Zero would otherwise be indistinguishable from a run
    that never asked, and that is the one answer blocked-write evidence must
    not give: it would report a generator as never blocked on the strength of
    lines the generator was never told to write.
    '''
    ribs = parsed['ribs']
    configured = sum(rib['ipv4_prefixes'] + rib['ipv6_prefixes']
                     for rib in ribs) if ribs else None

    # Completion waits for the End-of-RIB line, not for `RIB walk complete`.
    # bgpdump2 logs the marker first, then the final `Sent ...` counters, then
    # End-of-RIB -- all three in one code path, microseconds apart, but a poll
    # can land between them. Reporting completion on the marker alone freezes
    # the counters at their mid-walk value (9,981 of 10,000 in one capture),
    # and where the marker precedes the first `Sent` line entirely it reports a
    # completion with no offered count at all -- which the lifecycle cannot
    # express, since `tester_complete` would then sort before the
    # `tester_first_update` a later poll records. End-of-RIB is the last line
    # of the group, so the counters read beside it are the final ones.
    send_complete = parsed['walk_complete'] and bool(ribs) \
        and ribs[-1]['walk_time_s'] is not None

    # A walk time covers one RIB. Several sequential walks are not one
    # interval -- summing them would silently drop whatever time passed between
    # them and publish it as the playback duration -- so it is reported only
    # when the session walked exactly one RIB, which is what bgperf configures.
    walk_time_s = ribs[0]['walk_time_s'] if len(ribs) == 1 else None

    return {
        'established': parsed['established'],
        'offered': parsed['prefixes_sent'],
        'configured': configured,
        'send_complete': send_complete,
        'updates_sent': parsed['updates_sent'],
        'octets_on_wire': parsed['octets_sent'],
        'walk_time_s': walk_time_s,
        'blocked_writes': parsed['partial_writes'] if parsed['io_traced']
                          else None,
        'send_stalls': parsed['write_stalls'] if parsed['io_traced'] else None,
    }


class Bgpdump2(Container):

    GUEST_DIR = '/root/config'

    CONTAINER_NAME = 'bgperf_bgpdump2_target'
    IMAGE_REPO = 'bgperf/bgpdump2'
    DEFAULT_REF = 'master'
    # The generator's own binary, so `verify` runs the same build-hygiene
    # checks on it as on a target. An instrumented blaster is not a neutral
    # instrument: it would send more slowly than a clean one, and the run would
    # publish that as the target's convergence time.
    DAEMON_BINARY = '/usr/local/sbin/bgpdump2'

    # bgpdump2 reports `Version: 2.0.14`, and has done for every master commit
    # this project has built. Alone that is not identity: two images compiled
    # months apart from master are indistinguishable by it, which is the same
    # shape as the gcov trap -- a cached image keeping an old build with
    # nothing in the results to show it. The build's commit is the fact that
    # separates them, and the image still carries the clone it compiled, so it
    # can be read from a container that is already running rather than baked in
    # at build time. That matters: `prepare` skips a tag that exists, so
    # anything added to the recipe is missing from every image already built.
    VERSION_CLONE = '/root/bgpdump2'

    def __init__(self, host_dir, conf, image='bgperf/bgpdump2'):
        super(Bgpdump2, self).__init__(self.CONTAINER_NAME, image, host_dir, self.GUEST_DIR, conf)

    def get_version_cmd(self):
        # One exec for both facts. git's stderr is dropped rather than shown:
        # a pruned clone is a weaker identity, not a broken image, and its
        # message would otherwise have to be told apart from the version banner.
        return ['sh', '-c',
                '{0} -V; echo "commit: $(git -C {1} rev-parse --short HEAD '
                '2>/dev/null)"'.format(self.DAEMON_BINARY, self.VERSION_CLONE)]

    def exec_version_cmd(self):
        '''`2.0.14 (a019184)`, or an explicit note when the commit is gone.

        Matched against the banner rather than taken by position, for the
        reason every parser here is: a fixed word applied to an error message
        produces a plausible-looking value, and one of those reached the
        published baseline as a BIRD version. No banner means no version, so
        this raises instead of reporting the commit on its own.
        '''
        ret = (super().exec_version_cmd() or '').strip()
        m = re.search(r'^Version:\s*(\S+)', ret, re.M)
        if not m:
            raise VersionUnavailable(
                'unexpected output from `{0}`: {1!r}'.format(
                    self.get_version_cmd(), ret))
        commit = re.search(r'^commit:\s*([0-9a-f]{7,40})\s*$', ret, re.M)
        # Said out loud rather than left off: 2.0.14 with no commit beside it
        # looks like a precise version and is not one.
        return '{0} ({1})'.format(
            m.group(1), commit.group(1) if commit else 'commit unknown')


    @classmethod
    def build_image(cls, force=False, tag=None, checkout=None, nocache=False, version=None):
        tag = tag or cls.image_tag()
        checkout = checkout or cls.build_vars(version)['ref']
        cls.dockerfile = '''
FROM ubuntu:20.04
WORKDIR /root

RUN apt update \
    && apt -y dist-upgrade \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends tzdata \
    && apt-get install -y git libarchive-dev libbz2-dev liblz-dev zlib1g-dev autoconf \
        gcc wget make iputils-ping automake-1.15 \
    && rm -rf /var/lib/apt/lists/* /var/cache/apt/*

# Upstream ships a src/Makefile.in generated before timer.c was added to
# Makefile.am, so the recipe it configures has no timer.o in it. A plain build
# recovers only by luck: automake's maintainer rebuild rules regenerate
# Makefile.in when the clone happens to write aclocal.m4 before configure.ac,
# and when it does not, the link dies on timer_add/timespec_sub -- which is
# exactly how this broke. Regenerate explicitly rather than depend on the
# mtime order of a git checkout.
RUN git clone https://github.com/rtbrick/bgpdump2.git \
    && cd bgpdump2 \
    && git checkout {0} \
    && autoreconf -fi \
    && ./configure \
    && make \
    && mv src/bgpdump2 /usr/local/sbin/

RUN touch /root/mrt_file

ENTRYPOINT ["/bin/bash"]
'''.format(checkout)
        super(Bgpdump2, cls).build_image(force, tag, nocache=nocache)



class Bgpdump2Tester(Tester, Bgpdump2, MRTTester):
    CONTAINER_NAME_PREFIX = 'bgperf_bgpdump2_tester_'
    # The blaster reports its own work, so bench() can ask this generator what
    # it put on the wire instead of inferring it from when the monitor happened
    # to see prefixes.
    REPORTS_OFFERING = True
    LOG_NAME = 'bgpdump2.log'

    def __init__(self, name, host_dir, conf, image='bgperf/bgpdump2'):
        super(Bgpdump2Tester, self).__init__(name, host_dir, conf, image)
        self._blaster_log = BlasterLogReader(
            os.path.join(self.host_dir, self.LOG_NAME))

    def injected_neighbor(self):
        '''The one session this injector actually drives, as (key, conf).

        bgpdump2 blasts a single MRT peer index at a single neighbour, so
        get_startup_cmd() takes the first configured neighbour and the poll
        must name that same one. Reporting a session the container was never
        told to open would add a peer that can never complete, and the recorder
        aggregates pessimistically on purpose -- that one key would hold the
        whole injector short of `tester_complete` for the length of the run.
        '''
        return next(iter(self.conf['neighbors'].items()))

    def get_offerings(self):
        '''What this injector says it has offered, from its own log.

        `expected` is the prefix count the run configured, never the RIB size
        the log reports: that is the generator's own account of what it loaded
        and is kept beside it as `configured`, a cross-check that the injector
        got the workload it was given.

        Completion comes from `send_complete` rather than from the counts, for
        the reason `tester_offering_from_facts()` describes: `-T` caps the
        table while the MRT file is read, so an injector ends up holding
        whatever that MRT peer's table has and `offered >= expected` can stay
        false forever on one that has demonstrably sent everything it holds.

        Blocked-write evidence is present only when the run asked for it with
        --tester-trace-io; without it these are None and the recorder reports
        backpressure as unavailable rather than as zero.  See
        get_startup_cmd() for why that is not the default.

        Two things the injector knows that this poll cannot: `octets` is
        counted on a successful write() while `offered` is counted at the
        encoder, so the pair says how much of what was encoded had reached the
        socket; and `walk time` is the blaster's own measurement of the walk,
        which is the only evidence of an injection that finished before the
        first poll -- a 10,000-prefix walk takes about a millisecond.
        '''
        key, neighbor = self.injected_neighbor()
        observed = tester_offering_from_facts(self._blaster_log.read())
        return {key: TesterOffering(
            established=observed['established'],
            expected=int(neighbor['count']),
            offered=observed['offered'],
            configured=observed['configured'],
            send_complete=observed['send_complete'],
            octets_on_wire=observed['octets_on_wire'],
            reported_send_duration_s=observed['walk_time_s'],
            blocked_writes=observed['blocked_writes'],
            send_stalls=observed['send_stalls'])}

    def configure_neighbors(self, target_conf):
        # this doesn't really do anything, but we use it to find the target
        self.target_ip = target_conf['local-address']
        return None


    def get_index_valid(self, prefix_count):
        good_indexes = []
        counts = self.local(f"/usr/local/sbin/bgpdump2 -c /root/mrt_file").decode('utf-8').split('\n')[1]
        counts = counts.split(',') 
        counts.pop(0) # first item is timestamp, we don't care
        for i, c in enumerate(counts):
            if int(c) >= int(prefix_count):
                good_indexes.append(i)
        if len(good_indexes) < 1:
            print(f"No mrt data has {prefix_count} of prefixes to send")
            exit(1)
        print(f"{len(good_indexes)} peers with more than {prefix_count} prefixes in this MRT data")
        return good_indexes

    def get_index_useful_neighbor(self, prefix_count):
        ''' dynamically figure out which of the indexes in the mrt file have enough data'''
        good_indexes = self.get_index_valid(prefix_count)

        if 'mrt-index' in self.conf:
            return good_indexes[self.conf['mrt-index'] % len(good_indexes)]
        else:
            return 3

    def get_index_asns(self):
        index_asns = {}
        asn = re.compile(r".*peer_table\[(\d+)\].*asn:(\d+).*")
        r_table = self.local(f"/usr/local/sbin/bgpdump2 -P /root/mrt_file").decode('utf-8').splitlines()
        for line in r_table:
            m_asn = asn.match(line)
            if m_asn:
                g_asn = m_asn.groups()
                index_asns[int(g_asn[0])] = int(g_asn[1])

        return index_asns

    def get_local_as(self, index):
        index_asns = self.get_index_asns()
        return index_asns[index]


    def get_startup_cmd(self):

        # we can only handle one neighbor per container; get_offerings()
        # polls that same session
        neighbor = self.injected_neighbor()[1]
        prefix_count = neighbor['count']
        index = self.conf['bgpdump-index'] if 'bgpdump-index' in self.conf else self.get_index_useful_neighbor(prefix_count)
        local_as = self.get_local_as(index) or neighbor['as']
        # `stdbuf -oL`, because bgpdump2 logs with fprintf(stdout) and stdout to
        # a file is block-buffered: every line this injector writes about what
        # it sent -- the RIB it loaded, its running counts, `RIB walk complete`,
        # its own End-of-RIB walk time -- sat in a 4KB buffer that was never
        # flushed, since nothing ends the process except the container being
        # torn down. Measured: a converged 2-injector run left both
        # bgpdump2.log files at exactly 0 bytes with the blaster still running.
        # The generator was reporting its work all along and none of it was
        # observable.
        # `-t io` is the only blocked-write evidence bgpdump2 has, and it is
        # off unless the run asked for it. Without it the log says what was
        # encoded and nothing about whether the wire took it -- a write()
        # returning EAGAIN is logged nowhere -- so a session whose socket had
        # stopped draining reads exactly like one sending freely.
        #
        # It is opt-in because the class is not only the write lines: it also
        # logs one `Read ... message` line per BGP message *received*, and the
        # target re-advertises to a tester everything it learns from the
        # others. Those lines land in the blaster's event loop while it is
        # still walking, so they lengthen the walk it is timing -- and
        # `reported_injection_s`, the generator's own measurement, is the
        # number that resolves an injection shorter than a poll. Measured on
        # this 2-injector 10,000-prefix shape, three runs each: the injector
        # whose walk overlapped the echo reported 0.01122 / 0.01128 / 0.01125s
        # without the flag and 0.01763 / 0.01756 / 0.01751s with it, a
        # reproducible 56% inflation of the measurement, and its log grew from
        # 947 bytes to 350KB. So a run that wants to know whether the generator
        # was blocked asks for it and reads a perturbed walk time; a run that
        # wants the walk time does not.
        trace = ' -t io' if self.conf.get('trace-io') else ''
        startup = '''#!/bin/bash
ulimit -n 65536
stdbuf -oL -eL /usr/local/sbin/bgpdump2 --blaster {}{} -p {} -a {} /root/mrt_file -T {}  -S {}> {}/{} 2>&1 &

'''.format(self.target_ip, trace, index,
            local_as, prefix_count, neighbor['local-address'], self.guest_dir,
            self.LOG_NAME)
        return startup

    # Both of these take the tester host directories and must match the
    # signature in base.Tester -- bench() calls them on the class as
    # find_errors(tester_dirs). They used to take no arguments and glob
    # /tmp/bgperf2 themselves, so every bgpdump2 run died with TypeError at the
    # point it had finished converging and was writing its stats row.
    @staticmethod
    def find_errors(log_dirs=()):
        return count_matching_lines(log_dirs, 'error')

    @staticmethod
    def find_timeouts(log_dirs=()):
        return count_matching_lines(log_dirs, 'timeout')
