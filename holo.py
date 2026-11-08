# Copyright (C) 2026 bgperf2 contributors. Apache-2.0.
"""Holo IPv4 loading through its native transactional gRPC interface."""
import ipaddress
import json
import re

import toml

from base import Container, Target, VersionUnavailable, decode_cli_output, dckr


class HoloNeighborReadError(RuntimeError):
    """Native operational state did not attest valid per-peer counts."""


PROTOCOL_PATH = ('/ietf-routing:routing/control-plane-protocols/'
                 'control-plane-protocol[type="ietf-bgp:bgp"][name="bgperf"]')


def neighbor_counts(text):
    """Decode one grpcurl Get response: received is pre-, installed post-policy."""
    try:
        response = json.loads(text)
        tree = json.loads(response['data']['dataString'])
        protocols = tree['ietf-routing:routing']['control-plane-protocols']['control-plane-protocol']
        selected = [p for p in protocols if p['name'] == 'bgperf' and p['type'] == 'ietf-bgp:bgp']
        if len(selected) != 1:
            raise ValueError('Expected exactly one selected BGP protocol')
        rows = selected[0]['ietf-bgp:bgp']['neighbors']['neighbor']
        if not isinstance(rows, list):
            raise ValueError('Expected neighbor list')
        received, accepted, seen = {}, {}, set()
        for row in rows:
            address = str(ipaddress.IPv4Address(row['remote-address']))
            if address in seen:
                raise ValueError('Duplicate neighbor')
            seen.add(address)
            state = row['session-state']
            if not isinstance(state, str):
                raise ValueError('Invalid neighbor state')
            if state != 'established':
                continue
            families = row['afi-safis']['afi-safi']
            ipv4 = [family for family in families if family['name'] == 'iana-bgp-types:ipv4-unicast']
            if len(ipv4) != 1:
                raise ValueError('Expected exactly one IPv4 channel')
            counters = ipv4[0]['prefixes']
            rx, installed = counters['received'], counters['installed']
            if any(type(value) is not int or value < 0 for value in (rx, installed)):
                raise ValueError('Invalid prefix counts')
            received[address], accepted[address] = rx, installed
        return received, accepted
    except (KeyError, ValueError, TypeError) as exc:
        raise HoloNeighborReadError('Invalid or unavailable Holo IPv4 neighbor state') from exc


class Holo(Container):
    CONTAINER_NAME = None
    GUEST_DIR = '/root/config'
    IMAGE_REPO = 'bgperf/holo'
    DAEMON_BINARY = '/usr/local/sbin/holod'
    VERSIONS = ('0.9.0',)
    DEFAULT_REF = '947daeb2811b0cb90f457458f35c3b1a3c989b6b'
    BUILDER_IMAGE = 'rust@sha256:b1b3c9c0d921d7fa0a6d1f9ec7e4eab87f8c8ec97644c3d791450f131dec813f'
    RUNTIME_IMAGE = 'debian@sha256:a72b4433de1cf7d6bae0c4cee74d0547f58601a643b3375f070c51600d63b6b2'
    CLIENT_IMAGE = 'fullstorydev/grpcurl@sha256:085e183ca334eb4e81ca81ee12cbb2b2737505d1d77f5e33dabc5d066593d998'

    @classmethod
    def resolve_ref(cls, version):
        if not version or str(version).removeprefix('v') == '0.9.0':
            return cls.DEFAULT_REF
        text = str(version).strip()
        if re.fullmatch(r'[a-f0-9]{40}', text):
            return text
        if re.fullmatch(r'v?\d+\.\d+\.\d+', text):
            return 'v' + text.removeprefix('v')
        raise ValueError('Holo requires a release number or full source commit')

    @classmethod
    def build_image(cls, force=False, tag=None, checkout=None, nocache=False, version=None):
        ref = cls.resolve_ref(checkout or version)
        cls.dockerfile = f'''FROM {cls.CLIENT_IMAGE} AS client
FROM {cls.BUILDER_IMAGE} AS build
RUN apt-get update && apt-get install -qy --no-install-recommends build-essential cmake libpcre2-dev protobuf-compiler ca-certificates git
RUN git clone https://github.com/holo-routing/holo.git /src && cd /src && git checkout {ref} && git rev-parse HEAD > /tmp/holo-source-id
WORKDIR /src
RUN dpkg-query -W > /tmp/holo-build-packages.txt && rustc --version --verbose > /tmp/holo-rustc.txt && cargo tree --locked -p holo-daemon > /tmp/holo-dependencies.txt && GIT_HASH="$(git rev-parse HEAD)" cargo build --locked --release -p holo-daemon
FROM {cls.RUNTIME_IMAGE}
RUN apt-get update && apt-get install -qy --no-install-recommends iproute2 libpcre2-8-0 && rm -rf /var/lib/apt/lists/* && mkdir -p /var/opt/holo /usr/local/share/holo
COPY --from=build /src/target/release/holod /usr/local/sbin/holod
COPY --from=build /src/Cargo.lock /src/LICENSE /src/proto/holo.proto /usr/local/share/holo/
COPY --from=build /tmp/holo-source-id /usr/local/share/holo/source-id
COPY --from=build /tmp/holo-build-packages.txt /tmp/holo-rustc.txt /tmp/holo-dependencies.txt /usr/local/share/holo/
COPY --from=client /bin/grpcurl /usr/local/bin/grpcurl
ENV RUST_LOG=holo=info
WORKDIR /root
ENTRYPOINT []
CMD ["/bin/sh"]
'''
        super().build_image(force=force, tag=tag or cls.image_tag(), nocache=nocache)

    def get_version_cmd(self):
        return self.DAEMON_BINARY + ' --version'

    def exec_version_cmd(self):
        banner = super().exec_version_cmd(stderr=True).strip()
        if not re.fullmatch(r'(?:Holo routing daemon|holod) \d+\.\d+\.\d+(?: \([a-f0-9]{7,40}\))?', banner):
            raise VersionUnavailable('Unexpected Holo version banner: ' + repr(banner))
        return banner


class HoloTarget(Holo, Target):
    CONTAINER_NAME = 'bgperf_holo_target'
    CONFIG_FILE_NAME = 'holod.toml'
    GRPC = ['/usr/local/bin/grpcurl', '-plaintext',
            '-import-path', '/usr/local/share/holo', '-proto', 'holo.proto']
    ADDRESS = '127.0.0.1:50051'

    def __init__(self, host_dir, conf, image='bgperf/holo'):
        super().__init__(self.CONTAINER_NAME, image, host_dir, self.GUEST_DIR, conf)

    def write_config(self):
        if self.conf.get('filter_test') not in (None, 'None') or self.conf.get('threads') is not None:
            raise ValueError('Holo supports permit-all IPv4 loading without thread overrides')
        boot = {'user': 'root', 'group': 'root', 'database_path': '/var/opt/holo/holo.db',
                'logging': {'stdout': {'enabled': True, 'style': 'json'}, 'file': {'enabled': False}},
                'plugins': {'grpc': {'enabled': True, 'address': self.ADDRESS}, 'gnmi': {'enabled': False}}}
        family = {'name': 'iana-bgp-types:ipv4-unicast', 'enabled': True,
                  'apply-policy': {'default-import-policy': 'accept-route', 'default-export-policy': 'accept-route'}}
        protocol = {'type': 'ietf-bgp:bgp', 'name': 'bgperf', 'ietf-bgp:bgp': {
            'global': {'as': self.conf['as'], 'identifier': str(self.conf['router-id']),
                       'afi-safis': {'afi-safi': [family]}},
            'neighbors': {'neighbor': [{'remote-address': str(peer['router-id']), 'peer-as': peer['as'],
                'afi-safis': {'afi-safi': [family]}} for peer in self.scenario_neighbors()]}}}
        tree = {'ietf-interfaces:interfaces': {'interface': [{'name': self.dev,
                    'type': 'iana-if-type:ethernetCsmacd', 'ietf-ip:ipv4': {}}]},
                'ietf-routing:routing': {'control-plane-protocols': {'control-plane-protocol': [protocol]}}}
        request = {'operation': 'REPLACE', 'config': {'encoding': 'JSON', 'data_string': json.dumps(tree)},
                   'comment': 'bgperf explicit permit-all IPv4 loading'}
        with open(f'{self.host_dir}/{self.CONFIG_FILE_NAME}', 'w') as stream:
            toml.dump(boot, stream)
        with open(f'{self.host_dir}/holo-commit.json', 'w') as stream:
            json.dump(request, stream, indent=2)

    def exec_startup_cmd(self, stream=False, detach=False):
        # Target.run writes once before Container.run discovers self.dev.
        # Refresh after attachment and before any daemon consumes the files.
        self.write_config()
        return super().exec_startup_cmd(stream=stream, detach=detach)

    def get_startup_cmd(self):
        capabilities = ' '.join(self.GRPC + ['-max-time', '1'])
        commit = ' '.join(self.GRPC + ['-max-time', '10'])
        return f'''#!/bin/sh
set -eu
ulimit -n 65536 || true
{self.DAEMON_BINARY} -c {self.guest_dir}/{self.CONFIG_FILE_NAME} > {self.guest_dir}/holod.log 2>&1 &
daemon_pid=$!
trap 'kill "$daemon_pid" 2>/dev/null || true' EXIT
attempts=0
until {capabilities} {self.ADDRESS} holo.Northbound/Capabilities > /dev/null 2>&1; do
    kill -0 "$daemon_pid" || exit 1
    attempts=$((attempts + 1))
    if [ "$attempts" -ge 40 ]; then exit 1; fi
    sleep 0.25
done
{commit} -d @ {self.ADDRESS} holo.Northbound/Commit < {self.guest_dir}/holo-commit.json > {self.guest_dir}/holo-commit.log 2>&1
wait "$daemon_pid"
'''

    def get_neighbors_state(self):
        request = json.dumps({'type': 'STATE', 'encoding': 'JSON', 'path': PROTOCOL_PATH + '/ietf-bgp:bgp/neighbors'})
        command = self.GRPC + ['-max-time', '5', '-d', request, self.ADDRESS, 'holo.Northbound/Get']
        executable = dckr.exec_create(container=self.name, cmd=command)
        raw = dckr.exec_start(executable['Id'], stream=False, detach=False)
        return neighbor_counts(decode_cli_output(raw, container=self.name, cmd=command))
