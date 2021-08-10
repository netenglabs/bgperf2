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

# RUN ln -fs /usr/share/zoneinfo/GMT /etc/local/time \
#     && apt-get install -y tzdata &&
#     dpkg-reconfigure --frontend noninteractive tzdata


RUN apt update \
    && apt -y dist-upgrade \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends tzdata \
    && apt-get install -y git libarchive-dev libbz2-dev liblz-dev zlib1g-dev autoconf \
        gcc wget make iputils-ping\
    && rm -rf /var/lib/apt/lists/* /var/cache/apt/*

RUN git clone https://github.com/jopietsch/bgpdump2.git \
    && cd bgpdump2 \
    && ./configure \
    && make \
    && mv src/bgpdump2 /usr/local/sbin/

## cheating and just hard coding MRT data for now
RUN wget -q http://archive.routeviews.org/bgpdata/2021.08/RIBS/rib.20210801.0000.bz2 \
   && bzip2 -d rib.20210801.0000.bz2

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

    def get_index_useful_neighbor(self):
        # only some of the neighbors in any mrt dump are useful
        # for now we just hardocde
        if 'mrt-index' in self.conf:
            return self.conf['mrt-index']
        else:
            return 3

    def get_mrt_file(sef):
        # harcoded for now
        return 'rib.20210801.0000'



    def get_startup_cmd(self):
        #breakpoint()
        # just get the first neighbor, we can only handle one neighbor per container
        neighbor = next(iter(self.conf['neighbors'].values()))
        prefix_count = neighbor['count']
        startup = '''#!/bin/bash
ulimit -n 65536
/usr/local/sbin/bgpdump2 --blaster {} -p {} -a {} {} -T {} & > {}/bgpdump2.log 2>&1
        
'''.format(self.target_ip, self.get_index_useful_neighbor(), 
            neighbor['as'], self.get_mrt_file(), prefix_count, self.guest_dir)
        return startup
#> {}/bgpdump2.log 2>&1 