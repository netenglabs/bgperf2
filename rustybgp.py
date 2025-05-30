
import toml
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

FROM rust:1-bullseye AS rust_builder
RUN rustup component add rustfmt
RUN git clone https://github.com/osrg/rustybgp.git 
# I don't know why, but a newer version of futures is required
RUN cd rustybgp && sed -i "s/0.3.16/0.3.31/g" daemon/Cargo.toml && cargo build --release && cp target/release/rustybgpd /root
RUN wget https://github.com/osrg/gobgp/releases/download/v2.30.0/gobgp_2.30.0_linux_amd64.tar.gz
RUN tar xzf gobgp_2.30.0_linux_amd64.tar.gz
RUN cp gobgp /root


FROM debian:bullseye
WORKDIR /root 
COPY --from=rust_builder /root/rustybgpd ./
COPY --from=rust_builder /root/gobgp ./

'''.format(checkout)
        super(RustyBGP, cls).build_image(force, tag, nocache)


class RustyBGPTarget(RustyBGP, GoBGPTarget):
    # RustyBGP has the same config as GoBGP
    #  except some things are different
    
    CONTAINER_NAME = 'bgperf_rustybgp_target'

    def __init__(self, host_dir, conf, image='bgperf/rustybgp'):
        super(GoBGPTarget, self).__init__(host_dir, conf, image=image)

    def write_config(self):
        # I don't want to figure out how to write config as TOML Instead of YAML, 
        #  but RustyBGP can only handle TOML, so I'm cheating
        config = super(RustyBGPTarget, self).write_config()
        del config['policy-definitions']
        del config['defined-sets']

        toml_config = toml.dumps(config)
        with open('{0}/{1}'.format(self.host_dir, self.CONFIG_FILE_NAME), 'w') as f:
            f.write(toml_config)
            if 'filter_test' in self.conf:
                f.write(self.get_filter_test_config())

    def get_filter_test_config(self):
        file = open("filters/rustybgpd.conf", mode='r')
        filters = file.read()
        filters += "\n[global.apply-policy.config]\n"
        filters += f"import-policy-list = [\"{self.conf['filter_test']}\"]"
        file.close
        return filters

    def get_startup_cmd(self):
        return '\n'.join(
            ['#!/bin/bash',
             'ulimit -n 65536',
             'RUST_BACKTRACE=1 /root/rustybgpd -f {guest_dir}/{config_file_name} > {guest_dir}/rustybgp.log 2>&1']
        ).format(
            guest_dir=self.guest_dir,
            config_file_name=self.CONFIG_FILE_NAME,
            debug_level='info')

    def get_version_cmd(self):
        return "/root/rustybgpd --version"
    
    def exec_version_cmd(self):
        version = self.get_version_cmd()
        i= dckr.exec_create(container=self.name, cmd=version, stderr=False)
        return dckr.exec_start(i['Id'], stream=False, detach=False).decode('utf-8').strip()
