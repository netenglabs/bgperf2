from base import *
import json


class SRLinux(Container):
    CONTAINER_NAME = None
    GUEST_DIR = '/etc/opt/srlinux'

    def __init__(self, host_dir, conf, image='ghcr.io/nokia/srlinux'):
        super(SRLinux, self).__init__(self.CONTAINER_NAME, image, host_dir, self.GUEST_DIR, conf)


    # don't build just download from docker pull ghcr.io/nokia/srlinux
    # assume that you do this by hand
    @classmethod
    def build_image(cls, force=False, tag='ghcr.io/nokia/srlinux', checkout='', nocache=False):
        cls.dockerfile = ''
        print("Can't build SRLinux, must download yourself")
        print("docker pull ghcr.io/nokia/srlinux")


class SRLinuxTarget(SRLinux, Target):
    
    CONTAINER_NAME = 'bgperf_SRLinux_target'
    CONFIG_FILE_NAME = 'config.json'

    def __init__(self, host_dir, conf, image='ghcr.io/nokia/srlinux'):
        super(SRLinuxTarget, self).__init__(host_dir, conf, image=image)

    def write_config(self):
        config = {}
        key = "network-instance"
        bgp = 'srl_nokia-bgp:bgp'

        config = '''
enter candidate
set / network-instance default
set / network-instance default protocols
set / network-instance default protocols bgp
set / network-instance default protocols bgp admin-state enable
set / network-instance default protocols bgp router-id {0}
set / network-instance default protocols bgp autonomous-system {1}
set / network-instance default protocols bgp group neighbors
set / network-instance default protocols bgp group neighbors ipv4-unicast
set / network-instance default protocols bgp group neighbors ipv4-unicast admin-state enable
'''.format(self.conf['router-id'], self.conf['as'])

        config = {}
        config[key] = {"default": {"protocols": {"bgp": {}}}}
        config[key]["default"]["protocols"]["bgp"]["admin-state"] = 'enable'
        config[key]["default"]["protocols"]["bgp"]["autonomous-system"] = self.conf['as']
        config[key]["default"]["protocols"]["bgp"]["router-id"] = self.conf['router-id']
        config[key]["default"]["protocols"]["bgp"]['group neighbors'] = {"ipv4-unicast": {"admin-state": "enable"}}



        def gen_neighbor_config(n):
            config = '''
set / network-instance default protocols bgp neighbor {0}       
set / network-instance default protocols bgp neighbor {0} peer-as {1}     
set / network-instance default protocols bgp neighbor {0} peer-group neighbors

'''.format(n['router-id'], n['as'])
            config = {f"neighbor {n['router-id']}": {}}
            config[f"neighbor {n['router-id']}"]["peer-as"] = n["as"]
            config[f"neighbor {n['router-id']}"]["peer-group"] = "neighbors"

            return config
    
        
        def gen_prefix_configs(n):
            pass

        def gen_filter(name, match):
            pass
            
        def gen_prefix_filter(n, match):
            pass

        def gen_aspath_filter(n, match):
            pass

        def gen_community_filter(n, match):
            pass      

        def gen_ext_community_filter(n, match):
            pass   


        for n in sorted(list(flatten(list(t.get('neighbors', {}).values()) for t in self.scenario_global_conf['testers'])) + 
            [self.scenario_global_conf['monitor']], key=lambda n: n['as']):
            config[key]["default"]["protocols"].update(gen_neighbor_config(n))
        

        with open('{0}/{1}'.format(self.host_dir, self.CONFIG_FILE_NAME), 'w') as f:
            f.write(json.dumps(config))
            f.flush()



    def exec_startup_cmd(self, stream=False, detach=False):
        return self.local('sudo bash -c /opt/srlinux/bin/sr_linux',
                          detach=detach,
                          stream=stream)


    def get_version_cmd(self):
        return "/usr/bin/SRLinuxc -V"

    def exec_version_cmd(self):
        version = self.get_version_cmd()
        i= dckr.exec_create(container=self.name, cmd=version, stderr=True)
        return dckr.exec_start(i['Id'], stream=False, detach=False).decode('utf-8').strip('\n')


    def get_neighbors_state(self):
        neighbors_accepted = {}
        neighbor_received_output = json.loads(self.local("/usr/bin/SRLinuxc bgp --host 127.0.0.1 -J").decode('utf-8'))

        return neighbor_received_output['neighbor_summary']['recv_converged']
    
    def get_neighbor_received_routes(self):
        ## if we call this before the daemon starts we will not get output
        
        tester_count, neighbors_checked = self.get_test_counts()
        neighbors_accepted = self.get_neighbors_state() - 1 # have to discount the monitor

        i = 0
        for n in neighbors_checked.keys():
            if i >= neighbors_accepted:
                break
            neighbors_checked[n] = True
            i += 1


        return neighbors_checked, neighbors_checked


