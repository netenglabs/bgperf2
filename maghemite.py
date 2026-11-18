# Copyright (C) 2026 bgperf2 contributors. Apache-2.0.
"""Maghemite native IPv4 BGP through its versioned local management API."""
import ipaddress
import json
import re

from base import Container, Target, VersionUnavailable


class Maghemite(Container):
    CONTAINER_NAME = None
    GUEST_DIR = '/root/config'
    IMAGE_REPO = 'bgperf/maghemite'
    DAEMON_BINARY = '/usr/local/sbin/mgd'
    HTTP_BINARY = '/usr/local/bin/bgperf-mg-http'
    DEFAULT_REF = '277f4368d7b6e6c75bf339db132f8de1ac9b019a'
    # There is no published release catalog. A raw source commit is selectable,
    # but is not a release version that the daemon's package banner can attest.
    VERSIONS = ()
    BUILDER_IMAGE = 'rust@sha256:b1b3c9c0d921d7fa0a6d1f9ec7e4eab87f8c8ec97644c3d791450f131dec813f'
    RUNTIME_IMAGE = 'debian@sha256:a72b4433de1cf7d6bae0c4cee74d0547f58601a643b3375f070c51600d63b6b2'

    @classmethod
    def resolve_ref(cls, version):
        if not version:
            return cls.DEFAULT_REF
        value = str(version).strip()
        if not re.fullmatch(r'[a-f0-9]{40}', value):
            raise ValueError('Maghemite requires a full source commit; package version is not a release ref')
        return value

    @classmethod
    def build_image(cls, force=False, tag=None, checkout=None, nocache=False, version=None):
        ref = cls.resolve_ref(checkout or version)
        cls.dockerfile = f'''FROM {cls.BUILDER_IMAGE} AS build
ENV RUSTUP_TOOLCHAIN=1.97.1
RUN apt-get update && apt-get install -qy --no-install-recommends build-essential pkg-config libssl-dev cmake libclang-dev ca-certificates git
RUN git clone https://github.com/oxidecomputer/maghemite.git /src && cd /src && git checkout {ref} && git rev-parse HEAD > /tmp/maghemite-source-id
WORKDIR /src
RUN dpkg-query -W > /tmp/maghemite-build-packages.txt && rustc --version --verbose > /tmp/maghemite-rustc.txt && cargo tree --locked -p mgd > /tmp/maghemite-dependencies.txt && cargo build --locked --release -p mgd
FROM {cls.RUNTIME_IMAGE}
RUN apt-get update && apt-get install -qy --no-install-recommends iproute2 curl ca-certificates libssl3t64 && rm -rf /var/lib/apt/lists/* && mkdir -p /var/lib/bgperf-maghemite /usr/local/share/maghemite && ln -s /usr/bin/curl {cls.HTTP_BINARY}
RUN curl --version > /usr/local/share/maghemite/http-client.txt && read curl_name curl_version curl_rest < /usr/local/share/maghemite/http-client.txt && test "$curl_name" = curl && dpkg --compare-versions "$curl_version" ge 8.4.0
COPY --from=build /src/target/release/mgd {cls.DAEMON_BINARY}
COPY --from=build /src/Cargo.lock /src/rust-toolchain.toml /src/LICENSE /usr/local/share/maghemite/
COPY --from=build /src/openapi/mg-admin/mg-admin-latest.json /usr/local/share/maghemite/
COPY --from=build /tmp/maghemite-source-id /tmp/maghemite-build-packages.txt /tmp/maghemite-rustc.txt /tmp/maghemite-dependencies.txt /usr/local/share/maghemite/
WORKDIR /root
ENTRYPOINT []
CMD ["/bin/sh"]
'''
        super().build_image(force=force, tag=tag or cls.image_tag(), nocache=nocache)

    def get_version_cmd(self):
        return self.DAEMON_BINARY + ' --version'

    def exec_version_cmd(self):
        banner = super().exec_version_cmd(stderr=True).strip()
        if not re.fullmatch(r'mgd \d+\.\d+\.\d+(?:[-+][A-Za-z0-9_.-]+)?', banner):
            raise VersionUnavailable('Unexpected mgd version banner: ' + repr(banner))
        return banner


class MaghemiteTarget(Maghemite, Target):
    CONTAINER_NAME = 'bgperf_maghemite_target'
    CONFIG_FILE_NAME = 'maghemite-router.json'
    PEERS_FILE_NAME = 'maghemite-peers.json'
    API = 'http://127.0.0.1:4676'
    API_VERSION = '13.0.0'

    def __init__(self, host_dir, conf, image='bgperf/maghemite'):
        super().__init__(self.CONTAINER_NAME, image, host_dir, self.GUEST_DIR, conf)

    def write_config(self):
        if self.conf.get('filter_test') not in (None, 'None') or self.conf.get('threads') is not None:
            raise ValueError('Maghemite supports permit-all IPv4 loading without thread overrides')
        local = str(ipaddress.IPv4Interface(self.conf.get('local-address', self.conf['router-id'])).ip)
        router = {'asn': self.conf['as'], 'id': int(ipaddress.IPv4Address(self.conf['router-id'])),
                  'listen': '0.0.0.0:179', 'graceful_shutdown': False}
        neighbors = []
        for index, peer in enumerate(self.scenario_neighbors()):
            address = str(ipaddress.IPv4Interface(peer.get('local-address', peer['router-id'])).ip)
            neighbors.append({'host': address + ':179', 'name': f'peer-{index}',
                'hold_time': 6, 'idle_hold_time': 0, 'delay_open': 0, 'connect_retry': 5,
                'keepalive': 2, 'resolution': 100, 'passive': False, 'remote_asn': peer['as'],
                'min_ttl': None, 'md5_auth_key': None, 'multi_exit_discriminator': None,
                'communities': [], 'local_pref': None, 'enforce_first_as': True, 'vlan_id': None,
                'ipv4_unicast': {'nexthop': None, 'import_policy': 'NoFiltering', 'export_policy': 'NoFiltering'},
                'ipv6_unicast': None, 'deterministic_collision_resolution': False,
                'idle_hold_jitter': None, 'connect_retry_jitter': None, 'src_addr': local, 'src_port': None})
        peers = {'asn': self.conf['as'], 'originate': [], 'checker': None, 'shaper': None,
                 'peers': {'bgperf': neighbors}, 'unnumbered_peers': {}}
        for filename, value in ((self.CONFIG_FILE_NAME, router), (self.PEERS_FILE_NAME, peers)):
            with open(f'{self.host_dir}/{filename}', 'w') as stream:
                json.dump(value, stream, indent=2, sort_keys=True)
                stream.write('\n')

    def get_startup_cmd(self):
        # Fixed engine-owned files avoid stale peer globs on a reused bench.
        client = f"{self.HTTP_BINARY} --fail --silent --show-error --max-filesize 8388608 -H 'api-version: {self.API_VERSION}'"
        return f'''#!/bin/sh
set -eu
ulimit -n 65536 || true
{self.DAEMON_BINARY} run --admin-addr 127.0.0.1 --admin-port 4676 --data-dir /var/lib/bgperf-maghemite --bgp-dispatcher-addr 0.0.0.0:179 > {self.guest_dir}/mgd.log 2>&1 &
daemon_pid=$!
trap 'kill "$daemon_pid" 2>/dev/null || true' EXIT INT TERM
attempts=0
until {client} --max-time 1 {self.API}/bgp/config/routers > {self.guest_dir}/maghemite-ready.json 2>> {self.guest_dir}/maghemite-startup.log; do
    kill -0 "$daemon_pid" || exit 1
    attempts=$((attempts + 1))
    [ "$attempts" -ge 40 ] && exit 1
    sleep 1
done
status="$({client} --max-time 10 -H 'Content-Type: application/json' -X PUT --data-binary @{self.guest_dir}/{self.CONFIG_FILE_NAME} --output {self.guest_dir}/maghemite-router-response.txt --write-out '%{{http_code}}' {self.API}/bgp/config/router)"
[ "$status" = 204 ] || exit 1
status="$({client} --max-time 10 -H 'Content-Type: application/json' -X POST --data-binary @{self.guest_dir}/{self.PEERS_FILE_NAME} --output {self.guest_dir}/maghemite-peers-response.txt --write-out '%{{http_code}}' {self.API}/bgp/omicron/apply)"
[ "$status" = 204 ] || exit 1
wait "$daemon_pid"
'''

    def get_neighbors_state(self):
        # Selected source only declares/reads its prefix atomics; nothing updates
        # them. Independent observer/offering witnesses use the full window.
        return {}, {}
