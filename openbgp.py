
from base import *

class OpenBGP(Container):
    CONTAINER_NAME = None
    GUEST_DIR = '/root/config'

    def __init__(self, host_dir, conf, image='bgperf/openbgp'):
        super(OpenBGP, self).__init__(self.CONTAINER_NAME, image, host_dir, self.GUEST_DIR, conf)

    @classmethod
    def build_image(cls, force=False, tag='bgperf/openbgp', checkout='', nocache=False):

        cls.dockerfile = '''
FROM pierky/openbgpd:7.1p0

'''.format(checkout)
        super(OpenBGP, cls).build_image(force, tag, nocache)


class OpenBGPTarget(OpenBGP, Target):
    # OpenBGP has the same config as GoBGP
    #  except some things are different
    
    CONTAINER_NAME = 'bgperf_openbgp_target'

    def __init__(self, host_dir, conf, image='bgperf/openbgp'):
        super(OpenBGPTarget, self).__init__(host_dir, conf, image=image)

    def write_config(self, scenario_global_conf):
        # I don't want to figure out how to write config as TOML Instead of YAML, 
        #  but OpenBGP can only handle TOML, so I'm cheating
        config = super(OpenBGPTarget, self).write_config(scenario_global_conf)
        del config['policy-definitions']
        del config['defined-sets']

        toml_config = toml.dumps(config)
        with open('{0}/{1}'.format(self.host_dir, self.CONFIG_FILE_NAME), 'w') as f:
            f.write(toml_config)

    def get_startup_cmd(self):
        return '\n'.join(
            ['#!/bin/bash',
             'ulimit -n 65536',
             '/root/openbgpd -f {guest_dir}/{config_file_name} > {guest_dir}/openbgp.log 2>&1']
        ).format(
            guest_dir=self.guest_dir,
            config_file_name=self.CONFIG_FILE_NAME,
            debug_level='info')

    def get_version_cmd(self):
        return "/root/openbgp --version"
