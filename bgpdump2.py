import re
from base import *
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


def parse_blaster_log(text):
    '''Parse one injector's `bgpdump2 --blaster` log into facts.

    Counts are None when the log has not reported them yet, never 0: an
    injector that has sent nothing and an injector whose log could not be read
    must not produce the same measurement.

    Every RIB the session walks gets an entry in `ribs`, in walk order, holding
    the table it loaded and -- once its End-of-RIB is logged -- the walk time
    bgpdump2 measured itself.  A line that does not match is skipped rather
    than guessed at, which is also what makes an incremental reader safe: a
    half-written final line contributes nothing instead of a wrong number.
    '''
    state = None
    peer = None
    ribs = []
    counters = {}
    walk_complete = False

    for raw in text.splitlines():
        line = _LOG_LINE.match(raw)
        if not line:
            # Option parsing prints before logging starts ('peer_spec_index[1]:
            # register peer 3, asn 7018'), and an incremental read can end
            # mid-line.
            continue
        message = line.group('message').strip()

        m = _STATE_CHANGE.match(message)
        if m:
            state = m.group('new')
            peer = m.group('peer')
            continue

        m = _RIB_START.match(message)
        if m:
            ribs.append({
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
            counters = {
                'updates_sent': int(m.group('updates')),
                'prefixes_sent': int(m.group('prefixes')),
                'prefixes_withdrawn': int(m.group('withdrawn')),
                'octets_sent': int(m.group('octets')),
            }
            continue

        m = _END_OF_RIB.match(message)
        if m and ribs:
            # bgpdump2 restarts its walk clock for each RIB, so this belongs to
            # the RIB that is currently being walked, not to the session.
            ribs[-1]['walk_time_s'] = float(m.group('seconds'))
            continue

        if message == _WALK_COMPLETE:
            walk_complete = True

    return {
        'peer': peer,
        'state': state,
        'established': state == 'established',
        'ribs': tuple(ribs),
        'walk_complete': walk_complete,
        'updates_sent': counters.get('updates_sent'),
        'prefixes_sent': counters.get('prefixes_sent'),
        'prefixes_withdrawn': counters.get('prefixes_withdrawn'),
        'octets_sent': counters.get('octets_sent'),
    }


def tester_offering(text):
    '''What one bgpdump2 injector says it has offered, from its own log.

    `send_complete` is the point of this parser.  bgpdump2 logs `RIB walk
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
    '''
    parsed = parse_blaster_log(text)

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
    }


class Bgpdump2(Container):

    GUEST_DIR = '/root/config'

    CONTAINER_NAME = 'bgperf_bgpdump2_target'
    IMAGE_REPO = 'bgperf/bgpdump2'
    DEFAULT_REF = 'master'

    def __init__(self, host_dir, conf, image='bgperf/bgpdump2'):
        super(Bgpdump2, self).__init__(self.CONTAINER_NAME, image, host_dir, self.GUEST_DIR, conf)


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

    def __init__(self, name, host_dir, conf, image='bgperf/bgpdump2'):
        super(Bgpdump2Tester, self).__init__(name, host_dir, conf, image)

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

        # just get the first neighbor, we can only handle one neighbor per container
        neighbor = next(iter(self.conf['neighbors'].values()))
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
        startup = '''#!/bin/bash
ulimit -n 65536
stdbuf -oL -eL /usr/local/sbin/bgpdump2 --blaster {} -p {} -a {} /root/mrt_file -T {}  -S {}> {}/bgpdump2.log 2>&1 &

'''.format(self.target_ip, index,
            local_as, prefix_count, neighbor['local-address'], self.guest_dir)
        return startup
#> {}/bgpdump2.log 2>&1 

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
