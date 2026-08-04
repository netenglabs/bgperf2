import json
import os

from base import *


class RustBGPd(Container):
    CONTAINER_NAME = None
    GUEST_DIR = '/root/config'

    def __init__(self, host_dir, conf, image='bgperf/rustbgpd'):
        super(RustBGPd, self).__init__(self.CONTAINER_NAME, image, host_dir, self.GUEST_DIR, conf)

    @classmethod
    def build_image(cls, force=False, tag='bgperf/rustbgpd', checkout='v0.63.0', nocache=False):

        cls.dockerfile = '''
FROM rust:1.95-bookworm AS builder

RUN apt-get update && apt-get install -y --no-install-recommends protobuf-compiler && rm -rf /var/lib/apt/lists/*

WORKDIR /build
RUN git clone https://github.com/lance0/rustbgpd.git . && git checkout {0}
RUN cargo build --release -p rustbgpd -p rustbgpctl

FROM debian:bookworm-slim
WORKDIR /root

RUN apt-get update && apt-get install -y --no-install-recommends iproute2 && rm -rf /var/lib/apt/lists/*

COPY --from=builder /build/target/release/rustbgpd /usr/local/bin/rustbgpd
COPY --from=builder /build/target/release/rbgp /usr/local/bin/rbgp
'''.format(checkout)
        super(RustBGPd, cls).build_image(force, tag, nocache)


class RustBGPdTarget(RustBGPd, Target):

    CONTAINER_NAME = 'bgperf_rustbgpd_target'
    CONFIG_FILE_NAME = 'config.toml'

    def write_config(self):
        config = '[global]\n'
        config += 'asn = {}\n'.format(self.conf['as'])
        config += 'router_id = "{}"\n'.format(self.conf['router-id'])
        config += 'listen_port = 179\n'
        config += '\n'
        config += '[global.telemetry]\n'
        config += 'prometheus_addr = "0.0.0.0:9179"\n'
        config += 'log_format = "json"\n'
        config += '\n'
        # From v0.63.0 the daemon grants implicit local-operator
        # authorization on its owner-only default unix socket, so no
        # gRPC security configuration is needed for local benchmarking.

        # rustbgpd's durable event history is on by default and persists
        # route events to SQLite.  Set RUSTBGPD_EVENT_HISTORY_OFF=1 to
        # disable it and measure the daemon without that overhead.
        if os.environ.get('RUSTBGPD_EVENT_HISTORY_OFF'):
            config += '[event_history]\n'
            config += 'enabled = false\n'
            config += '\n'

        neighbors = list(flatten(
            list(t.get('neighbors', {}).values())
            for t in self.scenario_global_conf['testers']
        )) + [self.scenario_global_conf['monitor']]

        for n in neighbors:
            config += '[[neighbors]]\n'
            config += 'address = "{}"\n'.format(n['local-address'])
            config += 'remote_asn = {}\n'.format(n['as'])
            config += '\n'

        with open('{0}/{1}'.format(self.host_dir, self.CONFIG_FILE_NAME), 'w') as f:
            f.write(config)

    def get_startup_cmd(self):
        return '\n'.join(
            ['#!/bin/bash',
             'ulimit -n 65536',
             'cd {guest_dir} && exec rustbgpd {guest_dir}/{config_file_name} > {guest_dir}/rustbgpd.log 2>&1']
        ).format(
            guest_dir=self.guest_dir,
            config_file_name=self.CONFIG_FILE_NAME)

    def get_version_cmd(self):
        return "rustbgpd --version"

    def exec_version_cmd(self):
        ret = super().exec_version_cmd()
        return ret.strip()

    def get_neighbors_state(self, dckr_override=None):
        """Query neighbor state via the rbgp CLI.

        Returns (neighbors_received, neighbors_accepted) dicts keyed by
        neighbor address.  On any failure (timeout, parse error, empty
        output) returns (None, None) so callers can distinguish "query
        failed" from "zero neighbors."
        """
        import time as _time
        t0 = _time.monotonic()
        try:
            output = self.local(
                'rbgp --json neighbor',
                dckr_override=dckr_override
            )
            elapsed_ms = int((_time.monotonic() - t0) * 1000)

            if not output:
                print(f'rbgp: empty output ({elapsed_ms}ms)')
                return None, None

            data = json.loads(output.decode('utf-8'))

            neighbors_received = {}
            neighbors_accepted = {}
            for neighbor in data:
                addr = neighbor.get('address', '')
                received = neighbor.get('prefixes_received', 0)
                neighbors_received[addr] = received
                neighbors_accepted[addr] = received

            if elapsed_ms > 5000:
                print(f'rbgp: slow query ({elapsed_ms}ms)')

            return neighbors_received, neighbors_accepted

        except Exception as e:
            elapsed_ms = int((_time.monotonic() - t0) * 1000)
            print(f'rbgp: error after {elapsed_ms}ms: {e}')
            return None, None
