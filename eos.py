from jinja2.loaders import FileSystemLoader
from base import *
import json

class Eos(Container):
    CONTAINER_NAME = None
    GUEST_DIR = '/mnt/flash'
    
    def __init__(self, host_dir, conf, image='ceos'):
        super(Eos, self).__init__(self.CONTAINER_NAME, image, host_dir, self.GUEST_DIR, conf)
        
        self.environment = {
        "CEOS":                                "1",
		"EOS_PLATFORM":                        "ceoslab",
		"container":                           "docker",
		"ETBA":                                "4",
		"SKIP_ZEROTOUCH_BARRIER_IN_SYSDBINIT": "1",
		"INTFTYPE":                            "eth",
		"MAPETH0":                             "1",
		"MGMT_INTF":                           "eth0",
        }
        # eos needs to have a specific command run on container creation
        self.command = "/sbin/init" 
        for k,v in self.environment.items():
            self.command += f" systemd.setenv={k}={v}"


    # don't build just download 
    # assume that you do this by hand
    @classmethod
    def build_image(cls, force=False, tag='ceos', checkout='', nocache=False):
        cls.dockerfile = ''
        print("Can't build Eos, must download yourself")



class EosTarget(Eos, Target):
    
    CONTAINER_NAME = 'bgperf_eos_target'
    CONFIG_FILE_NAME = 'startup-config'

    def __init__(self, host_dir, conf, image='ceos'):
        super(EosTarget, self).__init__(host_dir, conf, image=image)
        

    def write_config(self):
        bgp = {}
        bgp['neighbors'] = []
        bgp['asn'] = self.conf['as']
        bgp['router-id'] = self.conf['router-id']

        for n in sorted(list(flatten(list(t.get('neighbors', {}).values()) for t in self.scenario_global_conf['testers'])) + 
            [self.scenario_global_conf['monitor']], key=lambda n: n['as']):
                bgp['neighbors'].append(n)
        config = self.get_template(bgp, template_file="eos.j2")
    
        with open('{0}/{1}'.format(self.host_dir, self.CONFIG_FILE_NAME), 'w') as f:
            f.write(config)
            f.flush()



    def exec_startup_cmd(self, stream=False, detach=False):
        return None


    def get_version_cmd(self):
        return "Cli -c 'show version|json'"

    def exec_version_cmd(self):
        version = self.get_version_cmd()
        i= dckr.exec_create(container=self.name, cmd=version, stderr=True)
        results = json.loads(dckr.exec_start(i['Id'], stream=False, detach=False).decode('utf-8'))

        return results['version'].strip('(engineering build)')



    def get_neighbors_state(self):
        neighbors_accepted = {}
        neighbors_received = {}
        neighbor_received_output = self.local("Cli -c 'sh ip bgp summary |json'")
        if neighbor_received_output:
            neighbor_received_output = json.loads(neighbor_received_output.decode('utf-8'))["vrfs"]["default"]["peers"]


        for n in neighbor_received_output.keys():
            rcd = neighbor_received_output[n]['prefixAccepted'] 
            neighbors_accepted[n] = rcd
        return neighbors_received, neighbors_accepted
    




