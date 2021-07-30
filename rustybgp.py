

from base import *
from gobgp import GoBGPTarget


class RustyBGP(Container):
    CONTAINER_NAME = None
    GUEST_DIR = '/root/config'

    def __init__(self, host_dir, conf, image='bgperf/rustybgp'):
        super(RustyBGP, self).__init__(self.CONTAINER_NAME, image, host_dir, self.GUEST_DIR, conf)

    @classmethod
    def build_image(cls, force=False, tag='bgperf/rustybgp', checkout='', nocache=False):

        cls.dockerfile = '''

FROM ekidd/rust-musl-builder


RUN pwd && git clone https://github.com/osrg/rustybgp.git
RUN sudo chown rust /root
RUN cd rustybgp && cargo build --release && cp /home/rust/src/rustybgp/target/x86_64-unknown-linux-musl/release/rustybgpd /root



# FROM golang:1.16.6
# WORKDIR /root
# RUN pwd && git clone git://github.com/osrg/gobgp && cd gobgp && go mod download
# RUN cd gobgp && go install ./cmd/gobgpd
# RUN cd gobgp && go install ./cmd/gobgp

# FROM ubuntu:18.04
# RUN apt update && apt upgrade --yes

# WORKDIR /root
# COPY --from=0 /home/rust/src/rustybgp/target/x86_64-unknown-linux-musl/release/rustybgpd /root
# COPY --from=1 


'''.format(checkout)
        super(RustyBGP, cls).build_image(force, tag, nocache)


class RustyBGPTarget(RustyBGP, GoBGPTarget):
    
    CONTAINER_NAME = 'bgperf_rustybgp_target'

    def __init__(self, host_dir, conf, image='bgperf/rustybgp'):
        super(GoBGPTarget, self).__init__(host_dir, conf, image=image)

    def get_startup_cmd(self):
        return '\n'.join(
            ['#!/bin/bash',
             'ulimit -n 65536',
             '/root/rustybgpd -f {guest_dir}/{config_file_name} > {guest_dir}/rustybgp.log 2>&1']
        ).format(
            guest_dir=self.guest_dir,
            config_file_name=self.CONFIG_FILE_NAME,
            debug_level='info')

    def get_version_cmd(self):
        return "/root/rustybgp --version"
