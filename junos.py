from jinja2.loaders import FileSystemLoader
from base import *
import json
import gzip


class Junos(Container):
    CONTAINER_NAME = None
    GUEST_DIR = '/config'
    LOG_DIR = '/var/log'

    def __init__(self, host_dir, conf, image='crpd'):
        super(Junos, self).__init__(self.CONTAINER_NAME, image, host_dir, self.GUEST_DIR, conf)
        self.volumes = [self.guest_dir, self.LOG_DIR]
        self.host_log_dir = f"{host_dir}/log"
        if not os.path.exists(self.host_log_dir):
            os.makedirs(self.host_log_dir)
            os.chmod(self.host_log_dir, 0o777)


    # don't build just download 
    # assume that you do this by hand
    @classmethod
    def build_image(cls, force=False, tag='crpd', checkout='', nocache=False):
        cls.dockerfile = ''
        print("Can't build junos, must download yourself")
        print("https://www.juniper.net/us/en/dm/crpd-free-trial.html")
        print("Must also tag image: docker tag 'crpd:21.3R1-S1.1 crpd:latest'")


class JunosTarget(Junos, Target):
    
    CONTAINER_NAME = 'bgperf_junos_target'
    CONFIG_FILE_NAME = 'juniper.conf.gz'

    def __init__(self, host_dir, conf, image='crpd'):
        super(JunosTarget, self).__init__(host_dir, conf, image=image)


        

    def write_config(self):
        #bgp = self.conf['neighbors']
        bgp = {}
        bgp['neighbors'] = []
        bgp['asn'] = self.conf['as']
        bgp['router-id'] = self.conf['router-id']

        for n in sorted(list(flatten(list(t.get('neighbors', {}).values()) for t in self.scenario_global_conf['testers'])) + 
            [self.scenario_global_conf['monitor']], key=lambda n: n['as']):
                bgp['neighbors'].append(n)
        config = self.get_template(bgp, template_file="junos.j2")
     
        # junos expects the config file to be compressed
        with gzip.open('{0}/{1}'.format(self.host_dir, self.CONFIG_FILE_NAME), 'w') as f:
            f.write(config.encode('utf8'))
            f.flush()



    def exec_startup_cmd(self, stream=False, detach=False):
        return None


    def get_version_cmd(self):
        return "cli show version"

    def exec_version_cmd(self):
        version = self.get_version_cmd()
        i= dckr.exec_create(container=self.name, cmd=version, stderr=True)
        return dckr.exec_start(i['Id'], stream=False, detach=False).decode('utf-8').split('\n')[3].strip('\n').split(':')[1].split(' ')[1]


    def get_neighbors_state(self):
        neighbors_accepted = {}
        neighbors_received = {}
        neighbor_received_output = json.loads(self.local("cli show bgp neighbor \| no-more \| display json").decode('utf-8'))

        for neighbor in neighbor_received_output['bgp-information'][0]['bgp-peer']:

            ip = neighbor['peer-address'][0]["data"].split('+')[0]
            if 'bgp-rib' in neighbor:
                neighbors_received[ip] = int(neighbor['bgp-rib'][0]['received-prefix-count'][0]["data"])
                neighbors_accepted[ip] = int(neighbor['bgp-rib'][0]['accepted-prefix-count'][0]["data"])
            else:
                neighbors_received[ip] = 0
                neighbors_accepted[ip] = 0

        return neighbors_received, neighbors_accepted
    


    # have to complete copy and add from parent because we need to bind an extra volume
    def get_host_config(self):
        host_config = dckr.create_host_config(
            binds=['{0}:{1}'.format(os.path.abspath(self.host_dir), self.guest_dir),
                   '{0}:{1}'.format(os.path.abspath(self.host_log_dir), self.LOG_DIR) ],
            privileged=True,
            network_mode='bridge',
            cap_add=['NET_ADMIN']
        )
        return host_config


