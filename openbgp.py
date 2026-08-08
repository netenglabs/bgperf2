
from base import *
import json

class OpenBGP(Container):
    CONTAINER_NAME = None
    GUEST_DIR = '/root/config'
    IMAGE_REPO = 'bgperf/openbgp'
    # OpenBGPD is not compiled here -- it is repackaged from the upstream
    # image, so a version is a tag on openbgpd/openbgpd rather than a git ref,
    # and the inherited passthrough resolve_ref() is already correct. Upstream
    # tags every release (7.3 through 9.2 at the time of writing), so any of
    # them can be asked for by name even though only these are prebuilt.
    DEFAULT_REF = 'latest'
    VERSIONS = ('8.8', '9.2')
    # The base image is the daemon under test, so a cached copy of
    # openbgpd/openbgpd:latest means the unversioned tag stops tracking
    # upstream: a local copy pulled in 2025-02 kept `latest` at 8.8 well after
    # 9.2 shipped, and the run recorded 8.8 without anything looking wrong.
    PULL_BASE = True

    def __init__(self, host_dir, conf, image='bgperf/openbgp'):
        super(OpenBGP, self).__init__(self.CONTAINER_NAME, image, host_dir, self.GUEST_DIR, conf)

    # On the daemon base class, beside BIRD's and GoBGP's, so every role this
    # image can play reports a version.
    def get_version_cmd(self):
        return "/usr/sbin/bgpctl -V"

    def exec_version_cmd(self):
        # bgpctl prints its banner on stderr, so stderr=True is load-bearing.
        ret = (super().exec_version_cmd(stderr=True) or '').strip()
        # Match the banner rather than returning whatever came back. bgpctl is
        # reached by an absolute path, so a wrong path -- this file just fixed
        # one -- makes the exec fail and its error text would otherwise be
        # recorded as the OpenBGPD version.
        m = re.search(r'OpenBGPD (\S+)', ret)
        if not m:
            raise VersionUnavailable(
                'unexpected output from `{0}`: {1!r}'.format(
                    self.get_version_cmd(), ret))
        return m.group(1)

    @classmethod
    def build_image(cls, force=False, tag=None, checkout=None, nocache=False, version=None):
        tag = tag or cls.image_tag()
        cls.dockerfile = '''
FROM openbgpd/openbgpd:{0}

# Neutralize the upstream entrypoint. It runs `multirun bgpd bgplgd haproxy`,
# which starts bgpd on the image's own /etc/bgpd.conf before bgperf can do
# anything -- so bgperf's start.sh then hit "cannot bind to 0.0.0.0:179:
# Address in use", the target never peered, and every run sat in "Waiting N
# seconds for monitor" until it was killed.
#
# Every other bgperf image idles until exec_startup_cmd() runs start.sh; this
# makes OpenBGPD behave the same way, so the config under test is the only one
# bgpd ever reads and startup is timed like the rest.
ENTRYPOINT []
CMD ["/bin/sh"]
'''.format(checkout or cls.build_vars(version)['ref'])
        super(OpenBGP, cls).build_image(force, tag, nocache=nocache)


class OpenBGPTarget(OpenBGP, Target):
    
    CONTAINER_NAME = 'bgperf_openbgp_target'
    CONFIG_FILE_NAME = 'bgpd.conf'

    def __init__(self, host_dir, conf, image='bgperf/openbgp'):
        super(OpenBGPTarget, self).__init__(host_dir, conf, image=image)

    def write_config(self):

        config = """ASN="{0}"

AS $ASN
router-id {1}
fib-update no
""".format(self.conf['as'], self.conf['router-id'])

        def gen_neighbor_config(n):
            return ('''neighbor {0} {{
    remote-as {1}
    enforce neighbor-as no
}}
'''.format(n['router-id'], n['as']) )
    
        
        def gen_prefix_configs(n):
            pass

        def gen_filter(name, match):
            c = ['function {0}()'.format(name), '{']
            for typ, name in match:
                c.append(' if ! {0}() then return false;'.format(name))
            c.append('return true;')
            c.append('}')
            return '\n'.join(c) + '\n'

        def gen_prefix_filter(n, match):
            pass

        def gen_aspath_filter(n, match):
            pass

        def gen_community_filter(n, match):
            pass      

        def gen_ext_community_filter(n, match):
            pass   

        with open('{0}/{1}'.format(self.host_dir, self.CONFIG_FILE_NAME), 'w') as f:
            f.write(config)

            if 'policy' in self.scenario_global_conf:
                for k, v in self.scenario_global_conf['policy'].items():
                    match_info = []
                    for i, match in enumerate(v['match']):
                        n = '{0}_match_{1}'.format(k, i)
                        if match['type'] == 'prefix':
                            f.write(gen_prefix_filter(n, match))
                        elif match['type'] == 'as-path':
                            f.write(gen_aspath_filter(n, match))
                        elif match['type'] == 'community':
                            f.write(gen_community_filter(n, match))
                        elif match['type'] == 'ext-community':
                            f.write(gen_ext_community_filter(n, match))
                        match_info.append((match['type'], n))
                    f.write(gen_filter(k, match_info))

            for n in sorted(list(flatten(list(t.get('neighbors', {}).values()) for t in self.scenario_global_conf['testers'])) + [self.scenario_global_conf['monitor']], key=lambda n: n['as']):
                f.write(gen_neighbor_config(n))
            f.write('allow to any\n')
            
            if 'filter_test' in self.conf:
                f.write(self.get_filter_test_config())
                if self.conf['filter_test'] == 'ixp':
                    f.write("deny quick from any inet prefixlen > 24\n")
                    f.write('deny quick from any transit-as {174,701,1299,2914,3257,3320,3356,3491,4134,5511,6453,6461,6762,6830,7018}\n')
            else:
                f.write('allow from any\n')

            f.flush()

    def get_startup_cmd(self):
        return '\n'.join(
            ['#!/bin/sh',
             'ulimit -n 65536',
             '/usr/sbin/bgpd -f {guest_dir}/{config_file_name} -d > {guest_dir}/openbgp.log 2>&1']
        ).format(
            guest_dir=self.guest_dir,
            config_file_name=self.CONFIG_FILE_NAME,
            debug_level='info')

    def get_neighbors_state(self):
        neighbors_accepted = {}
        neighbors_received_full = {}
        neighbor_received_output = json.loads(self.local("/usr/sbin/bgpctl -j show neighbor").decode('utf-8'))
        for neigh in neighbor_received_output['neighbors']:
            neighbors_accepted[neigh['remote_addr']] = neigh['stats']['prefixes']['received']
            neighbors_received_full[neigh['remote_addr']] = False if neigh['stats']['update']['received']['eor'] == 0 else True
    

        return neighbors_received_full, neighbors_accepted


    def get_filter_test_config(self): 
        with open(REPO_ROOT / 'filters' / 'openbgp.conf') as file:
            return file.read()