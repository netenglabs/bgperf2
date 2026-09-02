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

from base import *
import textfsm


# --- birdc 'show protocols all' --------------------------------------------
#
# Read by column *name*, never by position. BIRD 3 inserts two columns into the
# route-change-stats table that BIRD 2 does not have:
#
#   2.19  received rejected filtered ignored                accepted
#   3.3.2 received rejected filtered ignored RX limit limit accepted
#
# so `fields[4]` is `accepted` on one and `RX limit` on the other. `prepare`
# builds both series, and a positional read would not fail -- it would report a
# plausible wrong number for half the matrix, which is the failure mode this
# project keeps hitting. The `Routes:` line moves the same way: a channel with
# a filter reports an extra `filtered` term between `imported` and `exported`.

_PROTOCOL_HEADER = re.compile(
    r'^(?P<name>\S+)\s+(?P<proto>\S+)\s+(?P<table>\S+)\s+(?P<state>\S+)'
    r'\s+(?P<since>\S+)\s*(?P<info>.*?)\s*$')
_ROUTES = re.compile(r'(\d+)\s+([a-z]+)')
_PENDING_PREFIXES = re.compile(r'total\s+(\d+)\s+prefixes to send')
_TX_PENDING = re.compile(r'^TX pending:\s+(\d+)\s+bytes')


def _stat_value(token):
    '''A route-change-stats cell: an integer, or None for BIRD\'s `---`.'''
    return None if token == '---' else int(token)


def parse_protocols(text):
    '''Parse `birdc show protocols all` into {protocol name: facts}.

    Each protocol carries its header fields, any BGP session detail, and a
    `channels` dict, because a protocol can have more than one channel and only
    the ipv4 one carries this benchmark\'s workload. Unrecognised lines are
    skipped rather than guessed at.
    '''
    protocols = {}
    protocol = None
    channel = None
    columns = None

    for raw in text.splitlines():
        if not raw.strip():
            continue

        if not raw[:1].isspace():
            # A new protocol header ends the previous protocol's indented
            # block, so drop the channel/column context with it.
            protocol = channel = columns = None
            m = _PROTOCOL_HEADER.match(raw)
            # The table header and the `BIRD <version> ready.` banner both sit
            # at column 0; neither is a protocol.
            if not m or m.group('name') == 'Name':
                continue
            protocol = {
                'proto': m.group('proto'),
                'table': m.group('table'),
                'state': m.group('state'),
                'info': m.group('info'),
                'bgp_state': None,
                'neighbor_address': None,
                'neighbor_range': None,
                'tx_pending_bytes': None,
                'channels': {},
            }
            protocols[m.group('name')] = protocol
            continue

        if protocol is None:
            continue
        line = raw.strip()

        if line.startswith('Channel '):
            channel = line.split(None, 1)[1].strip()
            protocol['channels'][channel] = {
                'routes': {},
                'stats': {},
                'pending_prefixes': None,
            }
            columns = None
            continue

        if line.startswith('BGP state:'):
            protocol['bgp_state'] = line.split(':', 1)[1].strip()
            continue

        if line.startswith('Neighbor address:'):
            # BIRD appends the interface for a link-local or bound session:
            # `10.10.255.254%eth1`.
            protocol['neighbor_address'] = \
                line.split(':', 1)[1].strip().split('%')[0]
            continue

        if line.startswith('Neighbor range:'):
            # A `neighbor range` protocol is the listener for dynamic peers,
            # not a session of its own. It sits in Passive for the whole run.
            protocol['neighbor_range'] = line.split(':', 1)[1].strip()
            continue

        m = _TX_PENDING.match(line)
        if m:
            # BIRD 3 only. Its absence is what makes backpressure evidence
            # unavailable on 2.x, and that has to be recorded, not assumed zero.
            protocol['tx_pending_bytes'] = int(m.group(1))
            continue

        if channel is None:
            continue

        if line.startswith('Routes:'):
            protocol['channels'][channel]['routes'] = {
                name: int(count)
                for count, name in _ROUTES.findall(line.split(':', 1)[1])
            }
            continue

        if line.startswith('Route change stats:'):
            # Column names contain spaces ('RX limit'), so split on runs of
            # two or more spaces rather than on whitespace.
            columns = re.split(r'\s{2,}', line.split(':', 1)[1].strip())
            continue

        if line.startswith('Pending '):
            m = _PENDING_PREFIXES.search(line)
            if m:
                protocol['channels'][channel]['pending_prefixes'] = int(m.group(1))
            continue

        if columns and line.split(':', 1)[0] in (
                'Import updates', 'Import withdraws',
                'Export updates', 'Export withdraws'):
            key, _, rest = line.partition(':')
            values = rest.split()
            if len(values) != len(columns):
                # A row that does not line up with its own header is evidence
                # of a format this parser has not seen; recording it under
                # guessed names is how a wrong number gets published.
                continue
            protocol['channels'][channel]['stats'][key] = {
                name: _stat_value(value)
                for name, value in zip(columns, values)
            }

    return protocols


def tester_offering(text, channel='ipv4'):
    '''What a BIRD load generator has offered its peer, from its own CLI.

    `offered` is the cumulative count of export updates BIRD accepted for the
    session -- the generator\'s own account of what it put on the wire, which is
    the point: it is measured at the tester, independently of what the monitor
    later sees. `configured` is the size of the static table it was given, so
    expected and observed workload can be compared without trusting the config.

    Returns counts of None when the evidence is not present rather than 0, so a
    parse that found nothing cannot be mistaken for a generator that sent
    nothing.
    '''
    protocols = parse_protocols(text)

    # A `neighbor range` template is a listener, not a peering: it stays
    # Passive for the whole run, so counting it would mean a generator using
    # dynamic neighbors never reported itself ready. Sessions that have not
    # come up yet are still counted -- BIRD prints `Neighbor address` for those
    # too -- because dropping them is how a slow peer gets hidden.
    bgp = {name: p for name, p in protocols.items()
           if p['proto'] == 'BGP' and p['neighbor_range'] is None}
    offered = None
    exported = None
    tx_pending = None
    pending_prefixes = None
    for p in bgp.values():
        # Session-level, so it is read before the channel guard: a session that
        # reports a queue depth but whose channel block could not be read is
        # still a session we have blocked-write evidence for.
        if p['tx_pending_bytes'] is not None:
            tx_pending = p['tx_pending_bytes'] if tx_pending is None \
                else tx_pending + p['tx_pending_bytes']
        c = p['channels'].get(channel)
        if c is None:
            continue
        accepted = c['stats'].get('Export updates', {}).get('accepted')
        if accepted is not None:
            offered = accepted if offered is None else offered + accepted
        if 'exported' in c['routes']:
            exported = c['routes']['exported'] if exported is None \
                else exported + c['routes']['exported']
        if c['pending_prefixes'] is not None:
            pending_prefixes = c['pending_prefixes'] if pending_prefixes is None \
                else pending_prefixes + c['pending_prefixes']

    configured = None
    for p in protocols.values():
        if p['proto'] != 'Static':
            continue
        imported = p['channels'].get(channel, {}).get('routes', {}).get('imported')
        if imported is not None:
            configured = imported if configured is None else configured + imported

    return {
        # Every BGP session this generator runs must be up. One established
        # session out of two is not a generator that is ready to send.
        'established': bool(bgp) and all(
            p['bgp_state'] == 'Established' for p in bgp.values()),
        'sessions': len(bgp),
        'offered': offered,
        'exported': exported,
        'configured': configured,
        'tx_pending_bytes': tx_pending,
        'pending_prefixes': pending_prefixes,
    }


class BIRD(Container):

    CONTAINER_NAME = None
    GUEST_DIR = '/root/config'
    IMAGE_REPO = 'bgperf/bird'
    DAEMON_BINARY = '/usr/local/sbin/bird'
    VERSIONS = ('2.19.2', '3.3.2')
    DEFAULT_REF = 'master'

    def __init__(self, host_dir, conf, image='bgperf/bird', name=None):
        super(BIRD, self).__init__(name if name is not None else self.CONTAINER_NAME, image, host_dir, self.GUEST_DIR, conf)

    # Version reading lives on the daemon base class, not on BIRDTarget, so a
    # BIRD tester can report its version too -- the load generator's build is
    # part of what makes a result reproducible.
    def get_version_cmd(self):
        return "bird --version"

    def exec_version_cmd(self):
        # bird prints its banner on stderr, so stderr=True is load-bearing.
        ret = (super().exec_version_cmd(stderr=True) or '').strip()
        # Match the banner rather than taking the third word of whatever came
        # back: applied to an error message that produced 'exec', which reached
        # benchmarks/baseline/baseline-benchmark.csv as a BIRD version.
        m = re.search(r'BIRD version (\S+)', ret)
        if not m:
            raise VersionUnavailable(
                'unexpected output from `{0}`: {1!r}'.format(
                    self.get_version_cmd(), ret))
        return m.group(1)

    @classmethod
    def resolve_ref(cls, version):
        '''BIRD tags releases as v<version>; branches pass through.'''
        if not version:
            return cls.DEFAULT_REF
        version = str(version).strip()
        if re.fullmatch(r'\d+(\.\d+)*', version):
            return 'v{0}'.format(version)
        return version

    BUILD_VARS = {
        'base_image': 'ubuntu:latest',
        'packages': 'git autoconf libtool gawk make flex bison libncurses-dev '
                    'libreadline6-dev iproute2',
        'configure_extra': '',
    }
    # BIRD 3 has different build dependencies from BIRD 2; override per series
    # here, or drop a whole Dockerfile in dockerfiles/bird/<version>.dockerfile.
    VERSION_BUILD_VARS = ()

    @classmethod
    def build_image(cls, force=False, tag=None, checkout=None, nocache=False, version=None):
        # Clone and checkout share a layer so the ref is part of the layer key:
        # a cached clone from an older build would not know a newer tag.
        tag = tag or cls.image_tag()
        v = cls.build_vars(version)
        v['ref'] = checkout or v['ref']
        cls.dockerfile = '''
FROM {base_image}
WORKDIR /root
RUN apt-get update && apt-get install -qy {packages}
RUN git config --global http.sslverify false && git clone https://gitlab.nic.cz/labs/bird.git bird && cd bird && git checkout {ref}
RUN cd bird && autoreconf -i && ./configure {configure_extra} && make && make install
'''.format(**v)
        super(BIRD, cls).build_image(force, tag, nocache=nocache)


class BIRDTarget(BIRD, Target):

    CONTAINER_NAME = 'bgperf_bird_target'
    CONFIG_FILE_NAME = 'bird.conf'
    DYNAMIC_NEIGHBORS = True

    def write_config(self):
        # BIRD 3 is the multi-threaded rewrite, but it starts a single worker
        # unless told otherwise -- benchmarked without this it looks like 2.x.
        # BIRD 2 parses the keyword and ignores it, so a shared batch config
        # can set it for both.
        threads = ''
        if self.conf.get('threads'):
            threads = 'threads {0};\n'.format(int(self.conf['threads']))

        config = '''{2}router id {0};
protocol device {{ }}
protocol direct {{ disabled; }}
protocol kernel {{ ipv4 {{ import none; export none; }}; }}

log stderr all;
#debug protocols all; # this seems to add a lot of extra load especially in internet/mrt tests
'''.format(self.conf['router-id'], ' sorted' if self.conf['single-table'] else '', threads)

        def gen_filter_assignment(n):
            if 'filter' in n:
                c = []
                if 'in' not in n['filter'] or len(n['filter']['in']) == 0:
                    c.append('import all;')
                else:
                    c.append('import where {0};'.format( '&&'.join(x + '()' for x in n['filter']['in'])))

                if 'out' not in n['filter'] or len(n['filter']['out']) == 0:
                    c.append('export all;')
                else:
                    c.append('export where {0};'.format( '&&'.join(x + '()' for x in n['filter']['out'])))

                return '\n'.join(c)
            return '''import all;
export all;
'''

        def gen_neighbor_config(n):
            filter = 'all'
            if 'filter_test' in self.conf:
                filter = f"filter {self.conf['filter_test']}"
            return ('''ipv4 table table_{0};
protocol pipe pipe_{0} {{
    table master4;
    peer table table_{0};
}}
'''.format(n['as']) if not self.conf['single-table'] else '') + '''protocol bgp bgp_{0} {{
    local as {1};
    neighbor {2} as {0};

    ipv4 {{ import {}; export all; }};
    rs client;
}}
'''.format(n['as'], self.conf['as'], n['local-address'], 'secondary' if self.conf['single-table'] else '', filter)


        def gen_prefix_filter(name, match):
            return '''function {0}()
prefix set prefixes;
{{
prefixes = [
{1}
];
if net ~ prefixes then return false;
return true;
}}
'''.format(name, ',\n'.join(match['value']))

        def gen_aspath_filter(name, match):
            c = '''function {0}()
{{
'''.format(name)
            c += '\n'.join('if (bgp_path ~ [= * {0} * =]) then return false;'.format(v) for v in match['value'])
            c += '''
return true;
}
'''
            return c

        def gen_community_filter(name, match):
            c = '''function {0}()
{{
'''.format(name)
            c += '\n'.join('if ({0}, {1}) ~ bgp_community then return false;'.format(*v.split(':')) for v in match['value'])
            c += '''
return true;
}
'''
            return c

        def gen_ext_community_filter(name, match):
            c = '''function {0}()
{{
'''.format(name)
            c += '\n'.join('if ({0}, {1}, {2}) ~ bgp_ext_community then return false;'.format(*v.split(':')) for v in match['value'])
            c += '''
return true;
}
'''
            return c

        def gen_filter(name, match):
            c = ['function {0}()'.format(name), '{']
            for typ, name in match:
                c.append(' if ! {0}() then return false;'.format(name))
            c.append('return true;')
            c.append('}')
            return '\n'.join(c) + '\n'

        with open('{0}/{1}'.format(self.host_dir, self.CONFIG_FILE_NAME), 'w') as f:
            f.write(config)
            if 'filter_test' in self.conf:
                f.write(self.get_filter_test_config())

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
            if self.DYNAMIC_NEIGHBORS:
                config = self.get_dynamic_neighbor_config()
                f.write(config)
                f.flush()

            else:
                for n in sorted(list(flatten(list(t.get('neighbors', {}).values()) for t in self.scenario_global_conf['testers'])) + [self.scenario_global_conf['monitor']], key=lambda n: n['as']):
                    f.write(gen_neighbor_config(n))

            
    def get_dynamic_neighbor_config(self):
        filter = 'all'
        if 'filter_test' in self.conf:
            filter = f"filter {self.conf['filter_test']}"
        config = '''protocol bgp everything {{
    local as {};
    neighbor range 10.0.0.0/8 external;
    #hold time 10;
    connect delay time 1;
    ipv4 {{import {}; export all; }};
    #rs client;
}}
'''.format(self.conf['as'], filter)

        return config


    def get_filter_test_config(self): 
        with open(REPO_ROOT / 'filters' / 'bird.conf') as file:
            return file.read()

    def get_startup_cmd(self):
        return '\n'.join(
            ['#!/bin/bash',
             'ulimit -n 65536',
             'bird -c {guest_dir}/{config_file_name} -d > {guest_dir}/bird.log 2>&1']
        ).format(
            guest_dir=self.guest_dir,
            config_file_name=self.CONFIG_FILE_NAME)

    def get_neighbors_state(self):
        neighbors_accepted = {}
        neighbors_received = {}
        neighbor_received_output = self.local("birdc 'show protocols all'").decode('utf-8')
        
        with open(REPO_ROOT / 'bird.tfsm') as template:
            fsm = textfsm.TextFSM(template)
            result = fsm.ParseText(neighbor_received_output)

        for r in result:
            if r[0] == '' :
                continue
            else:
                neighbors_accepted[r[0]] = int(r[2]) if r[2] != '' else 0
                neighbors_received[r[0]] = int(r[1]) if r[1] != '' else 0

        return neighbors_received, neighbors_accepted
