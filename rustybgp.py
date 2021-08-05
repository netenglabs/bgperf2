
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

FROM ekidd/rust-musl-builder


RUN pwd && git clone https://github.com/osrg/rustybgp.git
RUN sudo chown rust /root
RUN cd rustybgp && cargo build --release && cp /home/rust/src/rustybgp/target/*/release/rustybgpd /root

'''.format(checkout)
        super(RustyBGP, cls).build_image(force, tag, nocache)


class RustyBGPTarget(RustyBGP, GoBGPTarget):
    # RustyBGP has the same config as GoBGP
    #  except some things are different
    
    CONTAINER_NAME = 'bgperf_rustybgp_target'

    def __init__(self, host_dir, conf, image='bgperf/rustybgp'):
        super(GoBGPTarget, self).__init__(host_dir, conf, image=image)

    def write_config(self, scenario_global_conf):
        # I don't want to figure out how to write config as TOML Instead of YAML, 
        #  but RustyBGP can only handle TOML, so I'm cheating
        config = super(RustyBGPTarget, self).write_config(scenario_global_conf)
        del config['policy-definitions']
        del config['defined-sets']

        toml_config = toml.dumps(config)
        with open('{0}/{1}'.format(self.host_dir, self.CONFIG_FILE_NAME), 'w') as f:
            f.write(toml_config)

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
        return "/root/rustybgpd --version"
    
    def exec_version_cmd(self):
        version = self.get_version_cmd()
        i= dckr.exec_create(container=self.name, cmd=version, stderr=False)
        return dckr.exec_start(i['Id'], stream=False, detach=False).decode('utf-8').strip()
