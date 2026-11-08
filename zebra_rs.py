# Copyright (C) 2026 bgperf2 contributors. Apache-2.0.
"""Official zebra-rs release packages through the native YAML/VTY interfaces."""
import ipaddress
import json
import re

import yaml

from base import Container, Target, VersionUnavailable, decode_cli_output, dckr


class ZebraNeighborReadError(RuntimeError):
    """Native summary did not attest valid current IPv4 received counts."""


def neighbor_counts(text):
    """Return pre-policy Adj-RIB-In counts only, never accepted/best-path counts."""
    try:
        data = json.loads(text)
        families = data['afi_safis']
        selected = [family for family in families if family['afi_safi'] == 'IPv4 Unicast']
        if len(selected) != 1 or not isinstance(selected[0]['peers'], list):
            raise ValueError('Expected exactly one IPv4 neighbor list')
        received, seen = {}, set()
        for row in selected[0]['peers']:
            address, state, count = row['neighbor'], row['state'], row['pfx_rcvd']
            if not isinstance(address, str) or not isinstance(state, str):
                raise ValueError('Neighbor address and state must be strings')
            address = str(ipaddress.IPv4Address(address))
            if address in seen or row.get('interface') is not None:
                raise ValueError('Duplicate or unsupported unnumbered neighbor')
            seen.add(address)
            if type(count) is not int or count < 0:
                raise ValueError('Invalid received count')
            if state in ('Idle', 'Connect', 'Active', 'OpenSent', 'OpenConfirm'):
                continue
            # Upstream's JSON deliberately reuses its State/PfxRcd display:
            # only Established rows render the count in place of the state.
            if state != str(count):
                raise ValueError('Established state/count mismatch')
            received[address] = count
        return received, {}
    except (KeyError, ValueError, TypeError) as exc:
        raise ZebraNeighborReadError('Invalid or unavailable zebra-rs IPv4 summary') from exc


class ZebraRS(Container):
    CONTAINER_NAME = None
    GUEST_DIR = '/root/config'
    IMAGE_REPO = 'bgperf/zebra-rs'
    DAEMON_BINARY = '/usr/bin/zebra-rs'
    WAIT_BINARY = '/usr/local/bin/bgperf-z-wait'
    VERSIONS = ('26.11.1',)
    DEFAULT_REF = '26.11.1'
    RUNTIME_IMAGE = 'debian@sha256:a72b4433de1cf7d6bae0c4cee74d0547f58601a643b3375f070c51600d63b6b2'
    PACKAGE_HASHES = {
        'amd64': 'e829f2ebd6a4758d9c9f4560d8d5ecb0de811d8f13dd261c308e03096781b2ee',
        'arm64': '803a2e9442aa0a9ae13365b42d814e608b1a234733446651d043964309a54af4',
    }

    @classmethod
    def resolve_ref(cls, version):
        selected = str(version or cls.DEFAULT_REF).removeprefix('v')
        if selected not in cls.VERSIONS:
            raise ValueError('Unsupported zebra-rs release: add verified package hashes before preparation')
        return selected

    @classmethod
    def build_image(cls, force=False, tag=None, checkout=None, nocache=False, version=None):
        selected = cls.resolve_ref(checkout or version)
        cls.dockerfile = f'''FROM {cls.RUNTIME_IMAGE}
RUN apt-get update && apt-get install -qy --no-install-recommends ca-certificates curl iproute2 libpam0g && rm -rf /var/lib/apt/lists/*
RUN architecture="$(dpkg --print-architecture)" && case "$architecture" in amd64) expected={cls.PACKAGE_HASHES['amd64']} ;; arm64) expected={cls.PACKAGE_HASHES['arm64']} ;; *) exit 1 ;; esac && curl --fail --location "https://github.com/zebra-rs/zebra-rs/releases/download/v{selected}/zebra-rs_{selected}-resolute_${{architecture}}.deb" --output /tmp/zebra-rs.deb && printf '%s  %s\\n' "$expected" /tmp/zebra-rs.deb | sha256sum -c - && dpkg-deb -x /tmp/zebra-rs.deb / && mkdir -p /usr/local/share/bgperf-zebra-rs && mv /tmp/zebra-rs.deb /usr/local/share/bgperf-zebra-rs/package.deb
RUN mkdir -p /usr/local/bin && test -x /usr/bin/timeout && ln -s /usr/bin/timeout {cls.WAIT_BINARY} && /usr/bin/zebra-rs --version && /usr/bin/vtyctl --version
WORKDIR /root
ENTRYPOINT []
CMD ["/bin/sh"]
'''
        super().build_image(force=force, tag=tag or cls.image_tag(), nocache=nocache)

    def get_version_cmd(self):
        return self.DAEMON_BINARY + ' --version'

    def exec_version_cmd(self):
        banner = super().exec_version_cmd(stderr=True).strip()
        if not re.fullmatch(r'zebra-rs \d+\.\d+\.\d+', banner):
            raise VersionUnavailable('Unexpected zebra-rs version banner: ' + repr(banner))
        return banner


class ZebraRSTarget(ZebraRS, Target):
    CONTAINER_NAME = 'bgperf_zebra_rs_target'
    CONFIG_FILE_NAME = 'zebra-rs.yaml'
    VTY = 'unix:/run/bgperf-zebra.vty'

    def __init__(self, host_dir, conf, image='bgperf/zebra-rs'):
        super().__init__(self.CONTAINER_NAME, image, host_dir, self.GUEST_DIR, conf)

    def write_config(self):
        if self.conf.get('filter_test') not in (None, 'None') or self.conf.get('threads') is not None:
            raise ValueError('zebra-rs supports permit-all IPv4 loading without thread overrides')
        config = {'policy': [{'name': 'BGPERF-PERMIT', 'entry': [{'number': 10, 'action': 'permit'}]}],
                  'router': {'bgp': {
                      'global': {'as': self.conf['as'], 'router-id': str(self.conf['router-id'])},
                      'neighbor': [{'remote-address': str(peer['router-id']), 'remote-as': peer['as'],
                                    'enabled': True, 'afi-safi': [{'name': 'ipv4', 'enabled': True,
                                      'policy': {'in': 'BGPERF-PERMIT', 'out': 'BGPERF-PERMIT'}}]}
                                   for peer in self.scenario_neighbors()]}}}
        with open(f'{self.host_dir}/{self.CONFIG_FILE_NAME}', 'w') as stream:
            yaml.safe_dump(config, stream, sort_keys=False)

    def get_startup_cmd(self):
        return (f'#!/bin/sh\nulimit -n 65536\n'
                f'{self.DAEMON_BINARY} --config-file {self.guest_dir}/{self.CONFIG_FILE_NAME} '
                f'--vty-socket {self.VTY} --log-output stdout --log-format json '
                f'> {self.guest_dir}/zebra-rs.log 2>&1')

    def get_neighbors_state(self):
        command = [self.WAIT_BINARY, '--kill-after=1', '5', '/usr/bin/vtyctl', '--vty-socket', self.VTY,
                   'show', '--json', 'show bgp summary']
        executable = dckr.exec_create(container=self.name, cmd=command)
        raw = dckr.exec_start(executable['Id'], stream=False, detach=False)
        if dckr.exec_inspect(executable['Id']).get('ExitCode') != 0:
            raise ZebraNeighborReadError('zebra-rs native CLI failed or exceeded its deadline')
        return neighbor_counts(decode_cli_output(raw, container=self.name, cmd=command))
