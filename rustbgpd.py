# Copyright (C) 2026 bgperf2 contributors. Apache-2.0.
"""rustbgpd supplied-image adapter; this is not osrg/RustyBGP."""
import ipaddress
import json
import re

import toml

from base import Container, Target, VersionUnavailable, decode_cli_output, dckr


class RustBGPDNeighborReadError(RuntimeError):
    """The native CLI did not attest a usable current accepted-prefix count."""


def neighbor_counts(text):
    """Return only accepted IPv4 counts; the API has no pre-policy RX witness.

    At upstream eb1749d7, JsonNeighbor.prefixes_received comes from the
    session actor's accepted-route prefix_count. Only IPv4 unicast is enabled
    by this adapter, so that aggregate has one family. It is a gauge, not a
    cumulative UPDATE counter. No best-path/table witness is inferred.
    """
    try:
        rows = json.loads(text)
    except (TypeError, ValueError) as exc:
        raise RustBGPDNeighborReadError('rbgp neighbor did not return JSON') from exc
    if not isinstance(rows, list):
        raise RustBGPDNeighborReadError('rbgp neighbor must return an array')
    accepted, seen = {}, set()
    for row in rows:
        if not isinstance(row, dict):
            raise RustBGPDNeighborReadError('Neighbor row must be an object')
        try:
            address = str(ipaddress.IPv4Address(row['address']))
            count, state = row['prefixes_received'], row['state']
        except (KeyError, ValueError, TypeError, ipaddress.AddressValueError) as exc:
            raise RustBGPDNeighborReadError('Missing or invalid IPv4 neighbor fields') from exc
        if address in seen:
            raise RustBGPDNeighborReadError('Duplicate neighbor address: ' + address)
        seen.add(address)
        if type(count) is not int or count < 0 or not isinstance(state, str):
            raise RustBGPDNeighborReadError('Invalid neighbor state or accepted-prefix count')
        if type(row.get('stale', False)) is not bool or row.get('stale', False):
            raise RustBGPDNeighborReadError('Neighbor observation is stale or its freshness is invalid')
        if type(row.get('retention_only', False)) is not bool:
            raise RustBGPDNeighborReadError('Invalid neighbor retention flag')
        if row.get('retention_only', False):
            continue
        if state == 'Established':
            accepted[address] = count
    return {}, accepted


class RustBGPD(Container):
    CONTAINER_NAME = None
    GUEST_DIR = '/root/config'
    IMAGE_REPO = 'bgperf/rustbgpd'
    DAEMON_BINARY = '/usr/local/bin/rustbgpd'
    VERSIONS = ('0.81.0',)
    RELEASE_IMAGE = 'ghcr.io/lance0/rustbgpd@sha256:f8a6d62ced049e415d702e31c43cbd6dac62fa9bcfdd0f410938f3c6cc418a64'
    DEFAULT_REF = RELEASE_IMAGE

    @classmethod
    def resolve_ref(cls, version):
        if not version or str(version).removeprefix('v') == '0.81.0':
            return cls.RELEASE_IMAGE
        version = str(version).strip().removeprefix('v')
        if re.fullmatch(r'\d+\.\d+\.\d+', version):
            return 'ghcr.io/lance0/rustbgpd:' + version
        if re.fullmatch(r'ghcr\.io/lance0/rustbgpd:\d+\.\d+\.\d+', version):
            return version
        if re.fullmatch(r'ghcr\.io/lance0/rustbgpd@sha256:[a-f0-9]{64}', version):
            return version
        raise ValueError('rustbgpd version must be a release number or immutable upstream image digest')

    @classmethod
    def build_image(cls, force=False, tag=None, checkout=None, nocache=False, version=None):
        ref = cls.resolve_ref(checkout or version)
        cls.dockerfile = f'''FROM {ref}
USER root
RUN apt-get update && apt-get install -qy --no-install-recommends iproute2 && rm -rf /var/lib/apt/lists/*
ENTRYPOINT []
HEALTHCHECK NONE
CMD ["/bin/sh"]
'''
        super().build_image(force=force, tag=tag or cls.image_tag(), nocache=nocache)

    def get_version_cmd(self):
        return self.DAEMON_BINARY + ' --version'

    def exec_version_cmd(self):
        output = super().exec_version_cmd(stderr=True).strip()
        if not re.fullmatch(r'rustbgpd v?\d+\.\d+\.\d+(?:-[A-Za-z0-9_.-]+)?(?:\+[A-Za-z0-9_.-]+)?', output):
            raise VersionUnavailable('Unexpected rustbgpd version banner: ' + repr(output))
        return output


class RustBGPDTarget(RustBGPD, Target):
    CONTAINER_NAME = 'bgperf_rustbgpd_target'
    CONFIG_FILE_NAME = 'rustbgpd.toml'

    def __init__(self, host_dir, conf, image='bgperf/rustbgpd'):
        super().__init__(self.CONTAINER_NAME, image, host_dir, self.GUEST_DIR, conf)

    def write_config(self):
        if self.conf.get('filter_test') not in (None, 'None') or self.conf.get('threads') is not None:
            raise ValueError('rustbgpd adapter supports permit-all loading without thread overrides')
        config = {'global': {'asn': self.conf['as'], 'router_id': str(self.conf['router-id']),
                            'listen_port': 179, 'runtime_state_dir': '/var/lib/rustbgpd',
                            'ebgp_requires_policy': True,
                            'telemetry': {'prometheus_addr': '127.0.0.1:9179', 'log_format': 'json'}},
                  'policy': {'definitions': {'permit-all-import': {'default_action': 'permit'},
                                            'permit-all-export': {'default_action': 'permit'}},
                             'import_chain': ['permit-all-import'], 'export_chain': ['permit-all-export']},
                  'neighbors': [{'address': str(peer['router-id']), 'remote_asn': peer['as'],
                                 'families': ['ipv4_unicast']} for peer in self.scenario_neighbors()]}
        with open(f'{self.host_dir}/{self.CONFIG_FILE_NAME}', 'w') as stream:
            toml.dump(config, stream)

    def get_startup_cmd(self):
        return (f'#!/bin/sh\nulimit -n 65536\n'
                f'{self.DAEMON_BINARY} {self.guest_dir}/{self.CONFIG_FILE_NAME} '
                f'> {self.guest_dir}/rustbgpd.log 2>&1')

    def get_neighbors_state(self):
        command = ['/usr/local/bin/rbgp', '--json', 'neighbor']
        executable = dckr.exec_create(container=self.name, cmd=command)
        raw = dckr.exec_start(executable['Id'], stream=False, detach=False)
        return neighbor_counts(decode_cli_output(raw, container=self.name, cmd=command))
