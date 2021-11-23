from base import *
import json

class Flock(Container):
    CONTAINER_NAME = None
    GUEST_DIR = '/root/config'

    def __init__(self, host_dir, conf, image='bgperf/flock'):
        super(Flock, self).__init__(self.CONTAINER_NAME, image, host_dir, self.GUEST_DIR, conf)

    @classmethod
    def build_image(cls, force=False, tag='bgperf/flock', checkout='', nocache=False):

        cls.dockerfile = '''
FROM debian:latest

RUN apt update \
    && apt -y dist-upgrade \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends tzdata \
    && apt-get install -y curl systemd iputils-ping sudo psutils procps iproute2\
    && rm -rf /var/lib/apt/lists/* /var/cache/apt/*

RUN curl 'https://www.flocknetworks.com/?smd_process_download=1&download_id=429' --output flockd_21.1.0_amd64.deb && \
    dpkg -i ./flockd_21.1.0_amd64.deb

'''.format(checkout)
        super(Flock, cls).build_image(force, tag, nocache)


class FlockTarget(Flock, Target):
    
    CONTAINER_NAME = 'bgperf_flock_target'
    CONFIG_FILE_NAME = 'bgpd.conf'

    def __init__(self, host_dir, conf, image='bgperf/flock'):
        super(FlockTarget, self).__init__(host_dir, conf, image=image)

    def write_config(self):
        config = {}
        config["system"] = {"api": {"rest": {"bind_ip_addr": "127.0.0.1"}}}
        config["system"]["api"]["netlink_recv"] = True

        config["bgp"] = {}
        config["bgp"]["local"] = {}
        config["bgp"]["local"]["id"] = self.conf['router-id']
        config["bgp"]["local"]["asn"] = self.conf['as']
        config["bgp"]["local"]["router_server"] = True # -- not yet
        # config["static"] = {"static_routes":[{ "ip_net": "10.10.0.0/16"} ]} # from scenario this is lcal_prefix but don't have access to that here
        # config["static"]["static_routes"][0]["next_hops"] = [{"intf_name": "eth0"}] #not sure where 10.10.0.1 comes from
        # config["static"]["static_routes"].append({"ip_net": "10.10.0.3/32", "next_hops": [{ "intf_name": "eth0"}]})



        def gen_neighbor_config(n):
            config = {}
            config["asn"] = n['as']
            config["neighbor"] = []
            config["neighbor"].append({"ip": n['router-id'], "local_ip": self.conf['router-id'],
                                        "af": [{"afi": "ipv4", "safi": "unicast"}]})
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

        config["bgp"]["as"] = []

        for n in sorted(list(flatten(list(t.get('neighbors', {}).values()) for t in self.scenario_global_conf['testers'])) + 
            [self.scenario_global_conf['monitor']], key=lambda n: n['as']):
            config["bgp"]["as"].append(gen_neighbor_config(n))
        
        with open('{0}/{1}'.format(self.host_dir, self.CONFIG_FILE_NAME), 'w') as f:
            f.write(json.dumps(config))
            f.flush()

    def get_startup_cmd(self):
        return '\n'.join(
            ['#!/bin/bash',
             'ulimit -n 65536',
             'cp {guest_dir}/{config_file_name} /etc/flockd/flockd.json',
             'RUST_LOG="info,bgp=debug" FLOCK_LOG="info,bgp=debug" /usr/sbin/flockd > {guest_dir}/flock.log 2>&1']
        ).format(
            guest_dir=self.guest_dir,
            config_file_name=self.CONFIG_FILE_NAME,
            debug_level='info')

    def get_version_cmd(self):
        return "/usr/bin/flockc -V"

    def exec_version_cmd(self):
        version = self.get_version_cmd()
        i= dckr.exec_create(container=self.name, cmd=version, stderr=True)
        return dckr.exec_start(i['Id'], stream=False, detach=False).decode('utf-8').strip('\n')

    def get_neighbors_state(self):
        neighbors_accepted = {}
        neighbor_received_output = json.loads(self.local("/usr/bin/flockc bgp --host 127.0.0.1 -J").decode('utf-8'))
        return neighbor_received_output['neighbor_summary']['default']['recv_converged']
    
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


