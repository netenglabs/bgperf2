import re
from subprocess import check_output, Popen, PIPE
from base import *
from mrt_tester import MRTTester

class Bgpdump2(Container):

    GUEST_DIR = '/root/config'

    CONTAINER_NAME = 'bgperf_bgpdump2_target'

    def __init__(self, host_dir, conf, image='bgperf/bgpdump2'):
        super(Bgpdump2, self).__init__(self.CONTAINER_NAME, image, host_dir, self.GUEST_DIR, conf)


    @classmethod
    def build_image(cls, force=False, tag='bgperf/bgpdump2', checkout='HEAD', nocache=False):
        cls.dockerfile = '''
FROM ubuntu:20.04
WORKDIR /root

RUN apt update \
    && apt -y dist-upgrade \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends tzdata \
    && apt-get install -y git libarchive-dev libbz2-dev liblz-dev zlib1g-dev autoconf \
        gcc wget make iputils-ping automake-1.15 \
    && rm -rf /var/lib/apt/lists/* /var/cache/apt/*

RUN git clone https://github.com/rtbrick/bgpdump2.git \
    && cd bgpdump2 \
    && ./configure \
    && make \
    && mv src/bgpdump2 /usr/local/sbin/

RUN touch /root/mrt_file

ENTRYPOINT ["/bin/bash"]
'''.format(checkout)
        super(Bgpdump2, cls).build_image(force, tag, nocache)



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
        asn = re.compile(f".*peer_table\[(\d+)\].*asn:(\d+).*")
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
        startup = '''#!/bin/bash
ulimit -n 65536
/usr/local/sbin/bgpdump2 --blaster {} -p {} -a {} /root/mrt_file -T {}  -S {}> {}/bgpdump2.log 2>&1 &
        
'''.format(self.target_ip, index, 
            local_as, prefix_count, neighbor['local-address'], self.guest_dir)
        return startup
#> {}/bgpdump2.log 2>&1 

    def find_errors():
        grep1 = Popen(('grep -i error /tmp/bgperf2/mrt-injector*/*.log'), shell=True, stdout=PIPE)
        errors = check_output(('wc', '-l'), stdin=grep1.stdout)
        grep1.wait()
        return errors.decode('utf-8').strip()

    def find_timeouts():
        grep1 = Popen(('grep -i timeout /tmp/bgperf2/mrt-injector*/*.log'), shell=True, stdout=PIPE)
        timeouts = check_output(('wc', '-l'), stdin=grep1.stdout)
        grep1.wait()
        return timeouts.decode('utf-8').strip()
