# Copyright (C) 2016 Nippon Telegraph and Telephone Corporation.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from settings import dckr
import io
import os
from itertools import chain
from threading import Thread
import netaddr
import sys
import time
import datetime
from jinja2 import Environment, FileSystemLoader, PackageLoader, StrictUndefined, make_logging_undefined


flatten = lambda l: chain.from_iterable(l)

def get_ctn_names():
    names = list(flatten(n['Names'] for n in dckr.containers(all=True)))
    return [n[1:] if n[0] == '/' else n for n in names]


def ctn_exists(name):
    return name in get_ctn_names()


def img_exists(name):
    return name in [ctn['RepoTags'][0].split(':')[0] for ctn in dckr.images() if ctn['RepoTags'] != None and len(ctn['RepoTags']) > 0]


def rm_line():
    print('\x1b[1A\x1b[2K\x1b[1D\x1b[1A')


class Container(object):
    def __init__(self, name, image, host_dir, guest_dir, conf):
        self.name = name
        self.image = image
        self.host_dir = host_dir
        self.guest_dir = guest_dir
        self.conf = conf
        self.config_name = None
        self.stop_monitoring = False
        self.command = None
        self.environment = None
        self.volumes = [self.guest_dir]
        if not os.path.exists(host_dir):
            os.makedirs(host_dir)
            os.chmod(host_dir, 0o777)

    @classmethod
    def build_image(cls, force, tag, nocache=False):
        def insert_after_from(dockerfile, line):
            lines = dockerfile.split('\n')
            i = -1
            for idx, l in enumerate(lines):
                elems = [e.strip() for e in l.split()]
                if len(elems) > 0 and elems[0] == 'FROM':
                    i = idx
            if i < 0:
                raise Exception('no FROM statement')
            lines.insert(i+1, line)
            return '\n'.join(lines)

        for env in ['http_proxy', 'https_proxy']:
            if env in os.environ:
                cls.dockerfile = insert_after_from(cls.dockerfile, 'ENV {0} {1}'.format(env, os.environ[env]))

        f = io.BytesIO(cls.dockerfile.encode('utf-8'))
        if force or not img_exists(tag):
            print('build {0}...'.format(tag))
            for line in dckr.build(fileobj=f, rm=False, tag=tag, decode=True, nocache=nocache):
                if 'stream' in line:
                    print(line['stream'].strip())

                if 'errorDetail' in line:
                    print(line['errorDetail'])

    def get_ipv4_addresses(self):
        if 'local-address' in self.conf:
            local_addr = self.conf['local-address']
            return [local_addr]
        raise NotImplementedError()

    def get_host_config(self):
        host_config = dckr.create_host_config(
            binds=['{0}:{1}'.format(os.path.abspath(self.host_dir), self.guest_dir)],
            privileged=True,
            network_mode='bridge',
            cap_add=['NET_ADMIN']
        )
        return host_config

    def run(self, dckr_net_name='', rm=True):

        if rm and ctn_exists(self.name):
            print('remove container:', self.name)
            dckr.remove_container(self.name, force=True)

        host_config = self.get_host_config()

        ctn = dckr.create_container(image=self.image, command=self.command, environment=self.environment,
                                    detach=True, name=self.name,
                                    stdin_open=True, volumes=self.volumes, host_config=host_config)
        self.ctn_id = ctn['Id']

        ipv4_addresses = self.get_ipv4_addresses()

        net_id = None
        for network in dckr.networks(names=[dckr_net_name]):
            if network['Name'] != dckr_net_name:
                continue

            net_id = network['Id']
            if not 'IPAM' in network:
                print(('can\'t verify if container\'s IP addresses '
                      'are valid for Docker network {}: missing IPAM'.format(dckr_net_name)))
                break
            ipam = network['IPAM']

            if not 'Config' in ipam:
                print(('can\'t verify if container\'s IP addresses '
                      'are valid for Docker network {}: missing IPAM.Config'.format(dckr_net_name)))
                break

            ip_ok = False
            network_subnets = [item['Subnet'] for item in ipam['Config'] if 'Subnet' in item]
            for ip in ipv4_addresses:
                for subnet in network_subnets:
                    ip_ok = netaddr.IPAddress(ip) in netaddr.IPNetwork(subnet)

                if not ip_ok:
                    print(('the container\'s IP address {} is not valid for Docker network {} '
                          'since it\'s not part of any of its subnets ({})'.format(
                              ip, dckr_net_name, ', '.join(network_subnets))))
                    print(('Please consider removing the Docket network {net} '
                          'to allow bgperf to create it again using the '
                          'expected subnet:\n'
                          '  docker network rm {net}'.format(net=dckr_net_name)))
                    sys.exit(1)
            break

        if net_id is None:
            print('Docker network "{}" not found!'.format(dckr_net_name))
            return

        dckr.connect_container_to_network(self.ctn_id, net_id, ipv4_address=ipv4_addresses[0])
        dckr.start(container=self.name)

        if len(ipv4_addresses) > 1:

            # get the interface used by the first IP address already added by Docker
            dev = None
            pxlen = None
            res = self.local('ip addr').decode("utf-8")

            for line in res.split('\n'):
                if ipv4_addresses[0] in line:
                    dev = line.split(' ')[-1].strip()
                    pxlen = line.split('/')[1].split(' ')[0].strip()
            if not dev:
                dev = "eth0"
                pxlen = 8

            for ip in ipv4_addresses[1:]:
                self.local(f'ip addr add {ip}/{pxlen} dev {dev}')

        return ctn

    def stats(self, queue):
        def stats():
            if self.stop_monitoring:
                return

            for stat in dckr.stats(self.ctn_id, decode=True):
                if self.stop_monitoring:
                    return
                cpu_percentage = 0.0
                prev_cpu = stat['precpu_stats']['cpu_usage']['total_usage']
                if 'system_cpu_usage' in stat['precpu_stats']:
                    prev_system = stat['precpu_stats']['system_cpu_usage']
                else:
                    prev_system = 0
                cpu = stat['cpu_stats']['cpu_usage']['total_usage']
                system = stat['cpu_stats']['system_cpu_usage'] if 'system_cpu_usage' in stat['cpu_stats'] else 0
                if not 'percpu_usage' in stat['cpu_stats']['cpu_usage']:
                    continue
                cpu_num = len(stat['cpu_stats']['cpu_usage']['percpu_usage'])
                cpu_delta = float(cpu) - float(prev_cpu)
                system_delta = float(system) - float(prev_system)
                if system_delta > 0.0 and cpu_delta > 0.0:
                    cpu_percentage = (cpu_delta / system_delta) * float(cpu_num) * 100.0
                mem_usage = stat['memory_stats'].get('usage', 0)
                queue.put({'who': self.name, 'cpu': cpu_percentage, 'mem': mem_usage, 'time': datetime.datetime.now()})

        t = Thread(target=stats)
        t.daemon = True
        t.start()

    def neighbor_stats(self, queue):
        def stats():
            while True:
                if self.stop_monitoring:
                    return
                neighbors_received_full, neighbors_checked = self.get_neighbor_received_routes()
                queue.put({'who': self.name, 'neighbors_checked': neighbors_checked})
                queue.put({'who': self.name, 'neighbors_received_full': neighbors_received_full})
                time.sleep(1)

        t = Thread(target=stats)
        t.daemon = True
        t.start()

    def local(self, cmd, stream=False, detach=False, stderr=False):
        i = dckr.exec_create(container=self.name, cmd=cmd, stderr=stderr)
        return dckr.exec_start(i['Id'], stream=stream, detach=detach)

    def get_startup_cmd(self):
        raise NotImplementedError()

    def get_version_cmd(self):
        raise NotImplementedError()

    def exec_version_cmd(self):
        version = self.get_version_cmd()
        i = dckr.exec_create(container=self.name, cmd=version, stderr=False)
        return dckr.exec_start(i['Id'], stream=False, detach=False).decode('utf-8')

    def exec_startup_cmd(self, stream=False, detach=False):
        startup_content = self.get_startup_cmd()

        if not startup_content:
            return
        filename = '{0}/start.sh'.format(self.host_dir)
        with open(filename, 'w') as f:
            f.write(startup_content)
        os.chmod(filename, 0o777)

        return self.local('{0}/start.sh'.format(self.guest_dir),
                          detach=detach,
                          stream=stream)

    def get_test_counts(self):
        '''gets the configured counts that each tester is supposed to send'''
        tester_count = {}
        neighbors_checked = {}
        for tester in self.scenario_global_conf['testers']:
            for n in tester['neighbors'].keys():
                tester_count[n] = tester['neighbors'][n]['check-points']
                neighbors_checked[n] = False
        return tester_count, neighbors_checked

    def get_neighbor_received_routes(self):
        ## if we ccall this before the daemon starts we will not get output
        
        tester_count, neighbors_checked = self.get_test_counts()
        neighbors_received_full = neighbors_checked.copy()
        neighbors_received, neighbors_accepted = self.get_neighbors_state()
        for n in neighbors_accepted.keys():

            #this will include the monitor, we don't want to check that
            if n in tester_count and neighbors_accepted[n] >= tester_count[n]: 
                neighbors_checked[n] = True

        
        for n in neighbors_received.keys():

            #this will include the monitor, we don't want to check that
            if (n in tester_count and neighbors_received[n] >= tester_count[n]) or neighbors_received[n] == True: 
                neighbors_received_full[n] = True

        return neighbors_received_full, neighbors_checked 

class Target(Container):

    CONFIG_FILE_NAME = None

    def write_config(self):
        raise NotImplementedError()

    def use_existing_config(self):
        if 'config_path' in self.conf:
            with open('{0}/{1}'.format(self.host_dir, self.CONFIG_FILE_NAME), 'w') as f:
                with open(self.conf['config_path'], 'r') as orig:
                    f.write(orig.read())
            return True
        return False

    def run(self, scenario_global_conf, dckr_net_name=''):
        self.scenario_global_conf = scenario_global_conf
        # create config before container is created
        if not self.use_existing_config():
            self.write_config()

        ctn = super(Target, self).run(dckr_net_name)


        self.exec_startup_cmd(detach=True)

        return ctn
    
    def get_template(self, data, template_file="junos.j2",):
        env = Environment(loader=FileSystemLoader(searchpath="./nos_templates"))
        template = env.get_template(template_file)
        output = template.render(data=data)
        return output

class Tester(Container):

    CONTAINER_NAME_PREFIX = None

    def __init__(self, name, host_dir, conf, image):
        Container.__init__(self, self.CONTAINER_NAME_PREFIX + name, image, host_dir, self.GUEST_DIR, conf)

    def get_ipv4_addresses(self):
        res = []
        peers = list(self.conf.get('neighbors', {}).values())
        for p in peers:
            res.append(p['local-address'])
        return res

    def configure_neighbors(self, target_conf):
        raise NotImplementedError()

    def run(self, target_conf, dckr_net_name):
        self.ctn = super(Tester, self).run(dckr_net_name)

        self.configure_neighbors(target_conf)

    def launch(self):
        output = self.exec_startup_cmd(stream=True, detach=False)

        cnt = 0
        prev_pid = 0
        for lines in output: # This is the ExaBGP output
            lines = lines.decode("utf-8").strip().split('\n')
            for line in lines:
                fields = line.split('|')
                if len(fields) >2:
                    # Get PID from ExaBGP output
                    try:
                        # ExaBGP Version >= 4
                        # e.g. 00:00:00 | 111 | control | command/comment
                        pid = int(fields[1])
                    except ValueError:
                        # ExaBGP Version = 3
                        # e.g. 00:00:00 | INFO | 111 | control | command
                        pid = int(fields[2])
                    if pid != prev_pid:
                        prev_pid = pid
                        cnt += 1
                        if cnt > 1:
                            rm_line()
                        print('tester booting.. ({0}/{1})'.format(cnt, len(list(self.conf.get('neighbors', {}).values()))))
                else:
                    print(lines)

        return None

    def find_errors():
        return 0

    def find_timeouts():
        return 0
