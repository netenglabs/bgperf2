# Copyright (C) 2026 bgperf2 contributors. Apache-2.0.
"""Bio-Routing native IPv4 loading; selected service exposes no prefix gauges."""
import ipaddress
import re

import yaml

from base import Container, Target


class BioRouting(Container):
    CONTAINER_NAME = None
    GUEST_DIR = '/root/config'
    IMAGE_REPO = 'bgperf/bio-routing'
    DAEMON_BINARY = '/usr/local/sbin/bio-rd'
    HTTP_BINARY = '/usr/local/bin/bgperf-bio-http'
    VERSIONS = ('0.1.10',)
    DEFAULT_REF = 'f422dbad63bd7977e94a16aa0718fb9876df23ee'
    BUILDER_IMAGE = 'golang@sha256:3b4a11519ad929d1e1d261a12cff056f0c85b735253d7d861346b9c6f8b36437'
    RUNTIME_IMAGE = 'debian@sha256:a72b4433de1cf7d6bae0c4cee74d0547f58601a643b3375f070c51600d63b6b2'

    @classmethod
    def resolve_ref(cls, version):
        if not version or str(version).removeprefix('v') == '0.1.10':
            return cls.DEFAULT_REF
        value = str(version).strip()
        if re.fullmatch(r'[a-f0-9]{40}', value):
            return value
        if re.fullmatch(r'v?\d+\.\d+\.\d+', value):
            return 'v' + value.removeprefix('v')
        raise ValueError('Bio-Routing requires a release number or full source commit')

    @classmethod
    def build_image(cls, force=False, tag=None, checkout=None, nocache=False, version=None):
        ref = cls.resolve_ref(checkout or version)
        cls.dockerfile = f'''FROM {cls.BUILDER_IMAGE} AS build
ENV GOTOOLCHAIN=local CGO_ENABLED=0
RUN git clone https://github.com/bio-routing/bio-rd.git /src && cd /src && git checkout {ref} && git rev-parse HEAD > /tmp/bio-source-id
WORKDIR /src
RUN go version > /tmp/bio-compiler.txt && go list -mod=readonly -m all > /tmp/bio-modules.txt && go build -mod=readonly -trimpath -o /tmp/bio-rd ./cmd/bio-rd && go version -m /tmp/bio-rd > /tmp/bio-buildinfo.txt
FROM {cls.RUNTIME_IMAGE}
RUN apt-get update && apt-get install -qy --no-install-recommends iproute2 curl ca-certificates && rm -rf /var/lib/apt/lists/* && mkdir -p /usr/local/share/bio-routing && ln -s /usr/bin/curl {cls.HTTP_BINARY}
RUN curl --version > /usr/local/share/bio-routing/http-client.txt && read curl_name curl_version curl_rest < /usr/local/share/bio-routing/http-client.txt && test "$curl_name" = curl && dpkg --compare-versions "$curl_version" ge 8.4.0
COPY --from=build /tmp/bio-rd {cls.DAEMON_BINARY}
COPY --from=build /src/go.mod /src/go.sum /src/LICENSE /usr/local/share/bio-routing/
COPY --from=build /tmp/bio-source-id /tmp/bio-compiler.txt /tmp/bio-modules.txt /tmp/bio-buildinfo.txt /usr/local/share/bio-routing/
WORKDIR /root
ENTRYPOINT []
CMD ["/bin/sh"]
'''
        super().build_image(force=force, tag=tag or cls.image_tag(), nocache=nocache)

    # No version command exists at this source. The base records UNKNOWN;
    # image/binary hashes and retained Go build metadata supply separate identity.


class BioRoutingTarget(BioRouting, Target):
    CONTAINER_NAME = 'bgperf_bio_routing_target'
    CONFIG_FILE_NAME = 'bio-rd.yaml'

    def __init__(self, host_dir, conf, image='bgperf/bio-routing'):
        super().__init__(self.CONTAINER_NAME, image, host_dir, self.GUEST_DIR, conf)

    def write_config(self):
        if self.conf.get('filter_test') not in (None, 'None') or self.conf.get('threads') is not None:
            raise ValueError('Bio-Routing supports permit-all IPv4 loading without thread overrides')
        local = str(ipaddress.IPv4Interface(self.conf.get('local-address', self.conf['router-id'])).ip)
        neighbors = [{'peer_address': str(ipaddress.IPv4Interface(
                          peer.get('local-address', peer['router-id'])).ip), 'peer_as': peer['as'],
                      'advertise_ipv4_multiprotocol': True}
                     for peer in self.scenario_neighbors()]
        policy = 'BGPERF-PERMIT'
        config = {'routing_options': {'autonomous_system': self.conf['as'],
                                     'router_id': str(self.conf['router-id'])},
                  'policy_options': {'policy_statements': [{'name': policy, 'terms': [
                      {'name': 'all', 'then': {'accept': True}}]}]},
                  'protocols': {'bgp': {'groups': [{'name': 'bgperf', 'local_address': local,
                      'passive': False, 'ipv4': {}, 'import': [policy], 'export': [policy],
                      'neighbors': neighbors}]}}}
        with open(f'{self.host_dir}/{self.CONFIG_FILE_NAME}', 'w') as stream:
            yaml.safe_dump(config, stream, sort_keys=False)

    def get_startup_cmd(self):
        return (f'#!/bin/sh\nulimit -n 65536 || true\n'
                f'{self.DAEMON_BINARY} -config.file {self.guest_dir}/{self.CONFIG_FILE_NAME} '
                f'> {self.guest_dir}/bio-rd.log 2>&1')

    def get_neighbors_state(self):
        # At f422dbad, cmd/bio-rd never registers the library's BGP Prometheus
        # collector (only examples/bgp does), and ListSessions is unimplemented.
        # No prefix observation exists: empty mappings, never per-peer zeros,
        # cumulative UPDATE counts, or a patched daemon to manufacture gauges.
        return {}, {}
